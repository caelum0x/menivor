"""Unit tests for the unattended channel runner's render pass.

All impure seams (the story contract, job creation, render enqueue, clip
persistence) are in-memory fakes — no Celery, DB, network or the stories layer.
Asserts:

* ``plan_fanout`` dedupe via ``clip_repo.seen_hashes`` (cross-run dedupe),
* ``pace_by_account`` cap == the platform ``daily_cap`` (or an override),
* EVERY built ReelForgeParams renders with ``platforms=()`` (skip stage_upload),
* the fan-out ``spec_hash`` is persisted for each rendered clip,
* all jobs of a run share one ``batch_id`` (== run_id),
* an enqueue failure is reconciled (job marked failed) and its ``spec_hash`` is
  NOT persisted, so the spec stays eligible for a later retry.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.domains.series.runner import ChannelRunConfig, RunnerDeps, run_channel


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
@dataclass
class _FakeParams:
    """Stand-in for ReelForgeParams (only what the runner reads/stores)."""

    video_script: str
    video_subject: str
    aspect: str
    voice_name: str
    platforms: tuple[str, ...]


class _FakeContract:
    """Deterministic story-contract seam: script == the item body."""

    def __init__(self) -> None:
        self.built_params: list[_FakeParams] = []

    def build_script(self, item, *, max_words):
        return str(item.get("body") or "").strip()

    def build_params(self, script, *, subject, aspect, voice_id, platforms):
        p = _FakeParams(
            video_script=script,
            video_subject=subject,
            aspect=aspect,
            voice_name=(f"elevenlabs:{voice_id}" if voice_id else "default"),
            platforms=tuple(platforms),
        )
        self.built_params.append(p)
        return p


class _FakeJob:
    def __init__(self, job_id: str, user_id: str, params: dict, batch_id):
        self.id = job_id
        self.user_id = user_id
        self.params = params
        self.batch_id = batch_id
        self.state = "processing"
        self.failed_stage = None
        self.error = ""


class _FakeJobRepo:
    def __init__(self, *, fail_ids: set[str] | None = None):
        self.jobs: dict[str, _FakeJob] = {}
        self._n = 0
        self.failed: list[str] = []

    def create(self, *, user_id, kind, params, batch_id):
        self._n += 1
        job_id = f"job-{self._n}"
        job = _FakeJob(job_id, user_id, params, batch_id)
        self.jobs[job_id] = job
        return job

    def mark_failed(self, job_id, stage, error):
        job = self.jobs.get(job_id)
        if job is not None:
            job.state = "failed"
            job.failed_stage = stage
            job.error = error
            self.failed.append(job_id)
        return job


@dataclass
class _FakeClip:
    id: str
    channel_id: str
    run_id: str
    spec_hash: str
    job_id: str
    account: str
    platform: str
    status: str = "pending"
    scheduled_publish_id: str | None = None


class _FakeClipRepo:
    """In-memory clip repo; ``seed`` primes prior-run hashes for cross-run dedupe."""

    def __init__(self, *, seed: dict[str, set[str]] | None = None):
        self._seen: dict[str, set[str]] = {k: set(v) for k, v in (seed or {}).items()}
        self.clips: list[_FakeClip] = []
        self._n = 0
        # Optional per-day pacing seam (default empty -> per-run pacing only).
        self.today_counts: dict[str, int] = {}

    def seen_hashes(self, channel_id):
        return set(self._seen.get(channel_id, set()))

    def rendered_today_counts(self, channel_id):
        return dict(self.today_counts)

    def create(self, *, channel_id, run_id, spec_hash, job_id, account, platform):
        self._n += 1
        clip = _FakeClip(
            id=f"clip-{self._n}",
            channel_id=channel_id,
            run_id=run_id,
            spec_hash=spec_hash,
            job_id=job_id,
            account=account,
            platform=platform,
        )
        self.clips.append(clip)
        self._seen.setdefault(channel_id, set()).add(spec_hash)
        return clip

    def list_pending_publish(self, channel_id):  # unused here
        return [c for c in self.clips if c.channel_id == channel_id]

    def mark_scheduled(self, clip_id, scheduled_publish_id):  # unused here
        return None


class _RecordingEnqueue:
    """Records ``start_pipeline`` calls; optionally raises for chosen job ids."""

    def __init__(self, *, fail_jobs: set[str] | None = None):
        self.calls: list[tuple[str, object]] = []
        self._fail = fail_jobs or set()

    def __call__(self, job_id, params):
        self.calls.append((job_id, params))
        if job_id in self._fail:
            raise RuntimeError("broker down")
        return f"task-{job_id}"


def _deps(job_repo, clip_repo, enqueue, contract) -> RunnerDeps:
    return RunnerDeps(
        job_repo=job_repo,
        clip_repo=clip_repo,
        start_pipeline=enqueue,
        schedule_publish=lambda *a, **k: None,
        session=object(),
        contract=contract,
        charge=lambda user_id, job: True,  # funded; charging is covered in test_mn1_*
        refund=lambda job_id: 0,
        pause=lambda channel_id, reason: True,
        resume=lambda channel_id: False,
    )


def _config(**overrides) -> ChannelRunConfig:
    base = dict(
        channel_id="chan-1",
        user_id="user-1",
        hooks=("hookA", "hookB"),
        aspects=("9:16",),
        accounts=("acct1", "acct2"),
        platforms=("youtube_shorts",),
        subject="minecraft story",
        voice_id="vox",
    )
    base.update(overrides)
    return ChannelRunConfig(**base)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_run_channel_renders_full_matrix_and_persists_spec_hash():
    contract = _FakeContract()
    job_repo = _FakeJobRepo()
    clip_repo = _FakeClipRepo()
    enqueue = _RecordingEnqueue()
    # 2 bodies x 2 hooks x 1 template x 1 aspect x 2 accounts = 8 combos.
    # youtube daily_cap == 2 -> cap 2 per account -> 4 rendered.
    config = _config()
    items = [{"body": "story one"}, {"body": "story two"}]

    result = run_channel(config, source_items=items, deps=_deps(job_repo, clip_repo, enqueue, contract))

    assert result.rendered == 4
    assert result.paced_out == 4  # 8 planned - 4 paced cap
    assert len(clip_repo.clips) == 4
    # Every rendered clip persisted its fan-out spec_hash.
    assert all(c.spec_hash for c in clip_repo.clips)
    assert len({c.spec_hash for c in clip_repo.clips}) == 4
    # Never more than daily_cap (2) per account this run.
    per_account: dict[str, int] = {}
    for c in clip_repo.clips:
        per_account[c.account] = per_account.get(c.account, 0) + 1
    assert per_account == {"acct1": 2, "acct2": 2}


def test_every_params_render_with_empty_platforms():
    contract = _FakeContract()
    result = run_channel(
        _config(),
        source_items=[{"body": "a"}, {"body": "b"}],
        deps=_deps(_FakeJobRepo(), _FakeClipRepo(), _RecordingEnqueue(), contract),
    )
    assert result.rendered > 0
    # platforms=() on EVERY built params so the DAG skips stage_upload.
    assert contract.built_params
    assert all(p.platforms == () for p in contract.built_params)


def test_all_jobs_share_one_batch_id_equal_to_run_id():
    job_repo = _FakeJobRepo()
    result = run_channel(
        _config(),
        source_items=[{"body": "a"}, {"body": "b"}],
        deps=_deps(job_repo, _FakeClipRepo(), _RecordingEnqueue(), _FakeContract()),
    )
    batch_ids = {j.batch_id for j in job_repo.jobs.values()}
    assert batch_ids == {result.run_id}


def test_pace_cap_uses_explicit_override():
    clip_repo = _FakeClipRepo()
    # override cap == 1 per account -> 2 accounts -> 2 rendered.
    result = run_channel(
        _config(max_per_account=1),
        source_items=[{"body": "a"}, {"body": "b"}],
        deps=_deps(_FakeJobRepo(), clip_repo, _RecordingEnqueue(), _FakeContract()),
    )
    assert result.rendered == 2
    per_account: dict[str, int] = {}
    for c in clip_repo.clips:
        per_account[c.account] = per_account.get(c.account, 0) + 1
    assert per_account == {"acct1": 1, "acct2": 1}


def test_cross_run_dedupe_skips_seen_hashes():
    contract = _FakeContract()
    # First run to learn the produced hashes.
    clip_repo = _FakeClipRepo()
    run_channel(
        _config(max_per_account=0),  # 0 == no cap: render all 8
        source_items=[{"body": "a"}, {"body": "b"}],
        deps=_deps(_FakeJobRepo(), clip_repo, _RecordingEnqueue(), contract),
    )
    assert len(clip_repo.clips) == 8
    seeded = clip_repo.seen_hashes("chan-1")

    # Second run with the SAME inputs but seen_hashes primed -> everything skipped.
    clip_repo2 = _FakeClipRepo(seed={"chan-1": seeded})
    result2 = run_channel(
        _config(max_per_account=0),
        source_items=[{"body": "a"}, {"body": "b"}],
        deps=_deps(_FakeJobRepo(), clip_repo2, _RecordingEnqueue(), contract),
    )
    assert result2.rendered == 0
    assert result2.skipped_duplicates == 8
    assert clip_repo2.clips == []


def test_rerun_is_idempotent_when_seen_persists():
    """Re-running with the same clip_repo (persisted hashes) renders nothing new."""
    contract = _FakeContract()
    clip_repo = _FakeClipRepo()
    deps = _deps(_FakeJobRepo(), clip_repo, _RecordingEnqueue(), contract)
    cfg = _config(max_per_account=0)
    items = [{"body": "a"}, {"body": "b"}]

    first = run_channel(cfg, source_items=items, deps=deps)
    assert first.rendered == 8
    # Same repo carries the persisted spec_hashes into the next pass.
    second = run_channel(cfg, source_items=items, deps=deps)
    assert second.rendered == 0
    assert second.skipped_duplicates == 8
    assert len(clip_repo.clips) == 8  # unchanged


def test_enqueue_failure_reconciles_and_does_not_persist_hash():
    contract = _FakeContract()
    job_repo = _FakeJobRepo()
    clip_repo = _FakeClipRepo()
    # Fail the enqueue for the very first job created.
    enqueue = _RecordingEnqueue(fail_jobs={"job-1"})
    result = run_channel(
        _config(max_per_account=0),
        source_items=[{"body": "a"}, {"body": "b"}],
        deps=_deps(job_repo, clip_repo, enqueue, contract),
    )
    # 8 combos, one enqueue failed.
    assert result.enqueue_failures == 1
    assert result.rendered == 7
    # The failed job was reconciled (marked failed) and produced NO clip row.
    assert "job-1" in job_repo.failed
    assert job_repo.jobs["job-1"].state == "failed"
    assert all(c.job_id != "job-1" for c in clip_repo.clips)
    assert len(clip_repo.clips) == 7


def test_pace_cap_subtracts_clips_already_rendered_today():
    # acct1 already rendered 2 clips TODAY (youtube cap == 2) -> 0 more this run;
    # acct2 has none -> gets its full cap of 2. The pace-cap is a per-DAY budget,
    # so hourly ticks can't jointly exceed it (regression: per-run over-render).
    clip_repo = _FakeClipRepo()
    clip_repo.today_counts = {"acct1": 2}
    result = run_channel(
        _config(),
        source_items=[{"body": "a"}, {"body": "b"}],
        deps=_deps(_FakeJobRepo(), clip_repo, _RecordingEnqueue(), _FakeContract()),
    )
    per_account: dict[str, int] = {}
    for c in clip_repo.clips:
        per_account[c.account] = per_account.get(c.account, 0) + 1
    assert per_account.get("acct1", 0) == 0
    assert per_account.get("acct2", 0) == 2
    assert result.rendered == 2


def test_spec_hash_is_committed_around_enqueue_for_crash_recovery():
    # The job must be committed BEFORE enqueue (so a queued task never dangles on
    # a rolled-back job_id) and the clip's spec_hash committed right AFTER a
    # successful enqueue (durable per-clip dedupe key). Regression: a whole-run
    # single commit rolled back already-enqueued specs on a mid-run crash.
    events: list[str] = []

    class _RecordingSession:
        def commit(self):
            events.append("commit")

    class _LoggingEnqueue:
        def __call__(self, job_id, params):
            events.append("enqueue")
            return "task"

    class _LoggingJobRepo(_FakeJobRepo):
        def create(self, **kw):
            events.append("job")
            return super().create(**kw)

    class _LoggingClipRepo(_FakeClipRepo):
        def create(self, **kw):
            events.append("clip")
            return super().create(**kw)

    deps = RunnerDeps(
        job_repo=_LoggingJobRepo(),
        clip_repo=_LoggingClipRepo(),
        start_pipeline=_LoggingEnqueue(),
        schedule_publish=lambda *a, **k: None,
        session=_RecordingSession(),
        contract=_FakeContract(),
        charge=lambda user_id, job: True,
        resume=lambda channel_id: False,
    )
    run_channel(
        _config(max_per_account=1, accounts=("acct1",), hooks=("h",)),
        source_items=[{"body": "a"}],
        deps=deps,
    )
    assert events == ["job", "commit", "enqueue", "clip", "commit"]


def test_no_scripts_renders_nothing():
    result = run_channel(
        _config(),
        source_items=[{"body": "   "}, {"body": ""}],
        deps=_deps(_FakeJobRepo(), _FakeClipRepo(), _RecordingEnqueue(), _FakeContract()),
    )
    assert result.rendered == 0
    assert result.planned == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
