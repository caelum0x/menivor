"""Unit tests for the ReelForge worker/telemetry layer.

Covers three modules against the INTEGRATION_CONTRACT (§6, §8):

  * ``app/workers/context.py``   — JobContext (de)serialisation stays JSON-safe;
    round-trips through ``json.dumps``; live objects (e.g. ``SubMaker``) are
    rejected at the boundary; ``merge_partials`` fan-in unions parallel keys.
  * ``app/telemetry/progress.py`` — weighted progress math using the *real*
    ``REELFORGE_STAGE_WEIGHTS`` constant; upload excluded when no platforms.
  * ``app/workers/pipeline.py``  — ``build_chain`` returns a Celery chain
    signature whose flattened stages match the DAG, excluding upload when
    ``params.platforms`` is empty; ``start_pipeline`` returns the root task id
    (celery ``.apply_async`` mocked).

Run:
    NEON_DATABASE_URL='sqlite:///:memory:' R2_ACCOUNT_ID=x R2_ACCESS_KEY_ID=x \\
    R2_SECRET_ACCESS_KEY=x R2_BUCKET=x \\
    .venv/bin/python -m pytest tests/reelforge/test_workers.py -q
"""

from __future__ import annotations

import json

import pytest

import contextlib

from sqlalchemy import create_engine, text, update
from sqlalchemy.orm import sessionmaker

from app.models.const import REELFORGE_STAGE_WEIGHTS
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.db.repositories import JobRepository
from app.services.reelforge import ReelForgeParams
from app.telemetry import progress
from app.workers import context, pipeline, tasks


@pytest.fixture(autouse=True)
def _ample_render_disk(monkeypatch):
    """Pipeline tests must not depend on the host's free disk: the render-space preflight
    (10 GB floor) would refuse to start them on a nearly full machine. The disk reading
    itself is mocked (1 TB free); the refusal path is tested in test_mg8_degrade.py."""
    from app.workers import preflight

    monkeypatch.setattr(preflight, "_free_bytes", lambda path, statvfs: 1024 ** 4)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STAGE_PREFIX = "app.workers.tasks."


def _collect_stage_names(sig, out: list[str] | None = None) -> list[str]:
    """Recursively flatten a Celery canvas signature to a list of task names.

    Handles plain ``Signature``, ``chain``, ``group`` and ``chord`` (header +
    callback body), which is how ``build_chain`` folds the appended upload step
    into the chord callback.
    """
    if out is None:
        out = []
    if isinstance(sig, (list, tuple)):
        for s in sig:
            _collect_stage_names(s, out)
        return out
    task = getattr(sig, "task", None)
    if task == "celery.chord":
        _collect_stage_names(sig.tasks, out)  # group header (avatar ∥ captions)
        _collect_stage_names(sig.body, out)  # callback (compose [→ upload])
    elif task in ("celery.chain", "celery.group") or type(sig).__name__ in (
        "_chain",
        "group",
        "_chord",
    ):
        _collect_stage_names(getattr(sig, "tasks", []), out)
        body = getattr(sig, "body", None)
        if body is not None:
            _collect_stage_names(body, out)
    elif task:
        out.append(task)
    return out


#: MN5: the pipeline's compose callback lives in tasks_provenance (compose, then
#: the AI-generated provenance tag); it keeps the bare ``stage_compose_task`` name.
_STAGE_PREFIXES = (_STAGE_PREFIX, "app.workers.tasks_provenance.")


def _short_stage_names(sig) -> list[str]:
    """Flattened stage names stripped to their bare ``stage_x_task`` form."""
    out = []
    for name in _collect_stage_names(sig):
        for prefix in _STAGE_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break
        out.append(name)
    return out


class _FakeAsyncResult:
    """Stand-in for ``celery.result.AsyncResult`` returned by apply_async."""

    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeSubMaker:
    """A live, non-JSON-serialisable object that must never enter a context."""

    def __init__(self) -> None:
        self.subs = ["a", "b"]
        self.offset = [(0, 1_000_000)]


# ---------------------------------------------------------------------------
# context.py — JSON-safety / round-trip
# ---------------------------------------------------------------------------


def _sample_context() -> dict:
    """A fully-populated, JSON-safe JobContext mirroring the contract shape."""
    return {
        "job_id": "job-abc",
        "params": ReelForgeParams(video_subject="cats").__dict__,
        "script": "Hello there.",
        "audio_key": "audio/job-abc.mp3",
        "audio_url": "https://cdn.example.com/audio/job-abc.mp3",
        "audio_duration": 12.34,
        "words": [["Hello", 0.0, 0.5], ["there", 0.5, 1.0]],
        "avatar_key": "avatar/job-abc.mp4",
        "avatar_video": "/tmp/job-abc/avatar.mp4",
        "avatar_duration": 12.30,
        "ass_key": "captions/job-abc.ass",
        "ass_path": "/tmp/job-abc/captions.ass",
    }


def test_new_context_seeds_only_job_id_and_params():
    params = ReelForgeParams(video_subject="dogs").__dict__
    ctx = context.new_context("job-1", params)

    assert ctx == {"job_id": "job-1", "params": params}
    # new_context must copy params, not alias the caller's dict.
    assert ctx["params"] is not params


def test_dumps_loads_round_trip_is_stable():
    ctx = _sample_context()
    raw = context.dumps_context(ctx)

    # It is a real JSON string.
    assert isinstance(raw, str)
    # dumps_context and json.dumps agree on parseability.
    reparsed = context.loads_context(raw)

    # tuples (params.platforms) serialise as lists; compare against the
    # json-normalised original so the round-trip is exact.
    expected = json.loads(json.dumps(ctx))
    assert reparsed == expected
    # Idempotent: dumping the reloaded context yields identical JSON.
    assert context.dumps_context(reparsed) == raw


def test_round_trip_contains_no_live_objects_only_primitives():
    ctx = _sample_context()
    reloaded = context.loads_context(context.dumps_context(ctx))

    def _assert_json_primitive(value):
        assert value is None or isinstance(
            value, (str, int, float, bool, list, dict)
        ), f"non-JSON value leaked: {type(value).__name__}"
        if isinstance(value, dict):
            for v in value.values():
                _assert_json_primitive(v)
        elif isinstance(value, list):
            for v in value:
                _assert_json_primitive(v)

    _assert_json_primitive(reloaded)


def test_words_flattened_to_plain_lists_not_tuples_after_round_trip():
    ctx = _sample_context()
    reloaded = context.loads_context(context.dumps_context(ctx))
    for word in reloaded["words"]:
        assert isinstance(word, list)
        text, start, end = word
        assert isinstance(text, str)
        assert isinstance(start, (int, float))
        assert isinstance(end, (int, float))


def test_dumps_context_rejects_live_submaker():
    ctx = _sample_context()
    ctx["sub_maker"] = _FakeSubMaker()  # contract violation

    with pytest.raises(TypeError):
        context.dumps_context(ctx)


def test_loads_context_rejects_non_object_payload():
    with pytest.raises(ValueError):
        context.loads_context(json.dumps([1, 2, 3]))
    with pytest.raises(ValueError):
        context.loads_context(json.dumps("just-a-string"))


def test_merge_partials_unions_avatar_and_caption_keys():
    base = {
        "job_id": "job-x",
        "params": {"video_subject": "x"},
        "script": "s",
        "audio_duration": 9.0,
        "words": [["hi", 0.0, 0.2]],
    }
    avatar_partial = {
        **base,
        "avatar_key": "a/k",
        "avatar_video": "/tmp/a.mp4",
        "avatar_duration": 9.0,
    }
    caption_partial = {
        **base,
        "ass_key": "c/k",
        "ass_path": "/tmp/c.ass",
    }

    merged = context.merge_partials([avatar_partial, caption_partial])

    # Both stage-specific key groups survive the fan-in.
    assert merged["avatar_key"] == "a/k"
    assert merged["avatar_video"] == "/tmp/a.mp4"
    assert merged["ass_key"] == "c/k"
    assert merged["ass_path"] == "/tmp/c.ass"
    # Shared base keys preserved.
    assert merged["job_id"] == "job-x"
    assert merged["audio_duration"] == 9.0
    # The merged context stays JSON-safe.
    assert context.loads_context(context.dumps_context(merged)) == merged


def test_merge_partials_order_independent():
    avatar_partial = {"job_id": "j", "avatar_key": "a"}
    caption_partial = {"job_id": "j", "ass_key": "c"}

    forward = context.merge_partials([avatar_partial, caption_partial])
    reverse = context.merge_partials([caption_partial, avatar_partial])

    assert forward == reverse
    assert forward["avatar_key"] == "a"
    assert forward["ass_key"] == "c"


def test_merge_partials_rejects_empty_and_non_dict():
    with pytest.raises(ValueError):
        context.merge_partials([])
    with pytest.raises(ValueError):
        context.merge_partials([{"job_id": "j"}, "not-a-dict"])


# ---------------------------------------------------------------------------
# progress.py — weighted math with the REAL const weights
# ---------------------------------------------------------------------------


def test_progress_uses_real_reelforge_stage_weights():
    assert progress.stage_weights() == REELFORGE_STAGE_WEIGHTS
    # A copy is returned; mutating it must not corrupt the const.
    weights = progress.stage_weights()
    weights["script"] = 999
    assert REELFORGE_STAGE_WEIGHTS["script"] == 10


def test_total_active_weight_with_and_without_platforms():
    # 10 + 20 + 30 + 15 + 20 + 5 = 100
    assert progress.total_active_weight(has_platforms=True) == 100
    # upload (5) excluded => 95
    assert progress.total_active_weight(has_platforms=False) == 95


def test_active_stages_excludes_upload_when_no_platforms():
    assert "upload" in progress.active_stages(has_platforms=True)
    assert "upload" not in progress.active_stages(has_platforms=False)


@pytest.mark.parametrize(
    ("done", "has_platforms", "expected"),
    [
        # --- with platforms: denominator = 100 ---
        ([], True, 0),
        (["script"], True, 10),  # 100*10/100
        (["script", "tts"], True, 30),  # 100*30/100
        (["script", "tts", "avatar", "captions"], True, 75),  # 100*75/100
        (["script", "tts", "avatar", "captions", "compose"], True, 95),
        (
            ["script", "tts", "avatar", "captions", "compose", "upload"],
            True,
            100,
        ),
        # --- no platforms: denominator = 95, upload ignored ---
        ([], False, 0),
        (["script"], False, 11),  # round(100*10/95)=round(10.526)=11
        (["script", "tts"], False, 32),  # round(100*30/95)=round(31.578)=32
        (
            ["script", "tts", "avatar", "captions", "compose"],
            False,
            100,
        ),  # 100*95/95
    ],
)
def test_compute_progress_exact_numbers(done, has_platforms, expected):
    assert progress.compute_progress(done, has_platforms) == expected


def test_compute_progress_matches_contract_formula():
    """Cross-check against the literal §6 formula for every subset boundary."""
    weights = REELFORGE_STAGE_WEIGHTS
    for has_platforms in (True, False):
        active = progress.active_stages(has_platforms)
        total = sum(weights[s] for s in active)
        # progressively complete the active stages in order
        for i in range(len(active) + 1):
            done = list(active[:i])
            done_weight = sum(weights[s] for s in done)
            expected = round(100 * done_weight / total)
            assert progress.compute_progress(done, has_platforms) == expected


def test_compute_progress_ignores_unknown_and_inactive_stages():
    # Unknown stage names cannot inflate progress.
    assert progress.compute_progress(["script", "bogus"], True) == 10
    # upload counts nothing when the job has no platforms even if reported done.
    assert progress.compute_progress(["script", "upload"], False) == 11


def test_compute_progress_clamped_to_range():
    # Duplicates / already-counted stages never exceed 100.
    all_stages = list(REELFORGE_STAGE_WEIGHTS.keys())
    assert progress.compute_progress(all_stages * 3, True) == 100
    assert progress.compute_progress([], True) == 0


def test_stage_weight_single_and_unknown():
    assert progress.stage_weight("avatar") == 30
    assert progress.stage_weight("nope") == 0


# ---------------------------------------------------------------------------
# pipeline.py — chain assembly + start_pipeline enqueue
# ---------------------------------------------------------------------------


def test_build_chain_returns_celery_chain_signature():
    from celery.canvas import Signature, _chain

    params = ReelForgeParams(video_subject="topic")
    built = pipeline.build_chain("job-1", params)

    # It is an un-applied chain signature (has apply_async, not yet run).
    assert isinstance(built, _chain)
    assert isinstance(built, Signature)
    assert built.task == "celery.chain"
    assert hasattr(built, "apply_async")


def test_build_chain_excludes_upload_when_no_platforms():
    params = ReelForgeParams(video_subject="topic", platforms=())
    stages = _short_stage_names(pipeline.build_chain("job-1", params))

    assert stages == [
        "stage_script_task",
        "stage_tts_task",
        "stage_avatar_task",
        "stage_captions_task",
        "stage_compose_task",
    ]
    assert "stage_upload_task" not in stages


def test_build_chain_includes_upload_when_platforms_present():
    params = ReelForgeParams(
        video_subject="topic", platforms=("youtube", "tiktok")
    )
    stages = _short_stage_names(pipeline.build_chain("job-1", params))

    assert stages == [
        "stage_script_task",
        "stage_tts_task",
        "stage_avatar_task",
        "stage_captions_task",
        "stage_compose_task",
        "stage_upload_task",
    ]


def test_build_chain_seeds_job_id_and_params_into_first_stage():
    params = ReelForgeParams(video_subject="topic", platforms=("youtube",))
    built = pipeline.build_chain("job-42", params)

    # The first signature carries the seed context as its first positional arg.
    first = built.tasks[0]
    assert first.task == "app.workers.tasks.stage_script_task"
    seed = first.args[0]
    assert seed["job_id"] == "job-42"
    assert seed["params"] == params.__dict__
    # The seed must be JSON-serialisable (it rides the same context contract).
    assert context.loads_context(context.dumps_context(seed)) == json.loads(
        json.dumps(seed)
    )


def test_start_pipeline_returns_root_task_id_with_apply_async_mocked(monkeypatch):
    from celery.canvas import _chain

    captured = {}

    def _fake_apply_async(self, *args, **kwargs):
        captured["called"] = True
        captured["stages"] = _short_stage_names(self)
        return _FakeAsyncResult("celery-root-id-123")

    monkeypatch.setattr(_chain, "apply_async", _fake_apply_async)

    params = ReelForgeParams(video_subject="topic", platforms=("youtube",))
    task_id = pipeline.start_pipeline("job-99", params)

    assert task_id == "celery-root-id-123"
    assert captured.get("called") is True
    # start_pipeline enqueues the assembled chain (upload included here).
    assert "stage_upload_task" in captured["stages"]


def test_start_pipeline_no_platforms_enqueues_chain_without_upload(monkeypatch):
    from celery.canvas import _chain

    captured = {}

    def _fake_apply_async(self, *args, **kwargs):
        captured["stages"] = _short_stage_names(self)
        return _FakeAsyncResult("root-noupload")

    monkeypatch.setattr(_chain, "apply_async", _fake_apply_async)

    params = ReelForgeParams(video_subject="topic", platforms=())
    task_id = pipeline.start_pipeline("job-100", params)

    assert task_id == "root-noupload"
    assert "stage_upload_task" not in captured["stages"]


# ---------------------------------------------------------------------------
# pipeline.py — retry_pipeline resume chain shape + reconstruction fallback
# ---------------------------------------------------------------------------


def _full_seed(platforms=("youtube",)) -> dict:
    """A fully-reconstructed JobContext with every resumable artifact key."""
    return {
        "job_id": "job-1",
        "params": ReelForgeParams(
            video_subject="t", platforms=platforms
        ).__dict__,
        "script": "hello",
        "audio_key": "jobs/job-1/audio.mp3",
        "audio_url": "https://cdn.example.com/audio.mp3",
        "audio_duration": 9.0,
        "words": [["hi", 0.0, 0.2]],
        "avatar_key": "jobs/job-1/avatar.mp4",
        "avatar_duration": 9.0,
        "ass_key": "jobs/job-1/captions.ass",
        "final_key": "jobs/job-1/final.mp4",
    }


@pytest.mark.parametrize(
    ("failed_stage", "expected"),
    [
        (
            "script",
            [
                "stage_script_task",
                "stage_tts_task",
                "stage_avatar_task",
                "stage_captions_task",
                "stage_compose_task",
                "stage_upload_task",
            ],
        ),
        (
            "tts",
            [
                "stage_tts_task",
                "stage_avatar_task",
                "stage_captions_task",
                "stage_compose_task",
                "stage_upload_task",
            ],
        ),
        (
            "avatar",
            [
                "stage_avatar_task",
                "stage_captions_task",
                "stage_compose_task",
                "stage_upload_task",
            ],
        ),
        (
            "captions",
            [
                "stage_avatar_task",
                "stage_captions_task",
                "stage_compose_task",
                "stage_upload_task",
            ],
        ),
        ("compose", ["stage_compose_task", "stage_upload_task"]),
        ("upload", ["stage_upload_task"]),
    ],
)
def test_build_retry_chain_shape_from_each_failed_stage(failed_stage, expected):
    params = ReelForgeParams(video_subject="t", platforms=("youtube",))
    built = pipeline.build_retry_chain("job-1", params, failed_stage, _full_seed())

    from celery.canvas import _chain

    assert isinstance(built, _chain)
    assert _short_stage_names(built) == expected


def test_build_retry_chain_excludes_upload_when_no_platforms():
    params = ReelForgeParams(video_subject="t", platforms=())
    stages = _short_stage_names(
        pipeline.build_retry_chain("job-1", params, "avatar", _full_seed(()))
    )
    assert stages == [
        "stage_avatar_task",
        "stage_captions_task",
        "stage_compose_task",
    ]
    assert "stage_upload_task" not in stages


def test_build_retry_chain_unknown_stage_is_full_rerun():
    params = ReelForgeParams(video_subject="t", platforms=("youtube",))
    stages = _short_stage_names(
        pipeline.build_retry_chain("job-1", params, "bogus", _full_seed())
    )
    assert stages[0] == "stage_script_task"
    assert "stage_upload_task" in stages


def test_build_retry_chain_seeds_context_into_resumed_stage():
    params = ReelForgeParams(video_subject="t", platforms=("youtube",))
    seed = _full_seed()

    # tts resume: seed rides the first task's first positional arg.
    tts_chain = pipeline.build_retry_chain("job-1", params, "tts", seed)
    first = tts_chain.tasks[0]
    assert first.task == "app.workers.tasks.stage_tts_task"
    assert first.args[0]["audio_url"] == seed["audio_url"]

    # compose resume: the chord callback needs a *list* of partials.
    compose_chain = pipeline.build_retry_chain("job-1", params, "compose", seed)
    compose_first = compose_chain.tasks[0]
    assert compose_first.task == "app.workers.tasks_provenance.stage_compose_task"
    assert compose_first.args[0] == [seed]


def test_build_retry_chain_backfills_job_id_and_params_when_seed_partial():
    params = ReelForgeParams(video_subject="t", platforms=())
    built = pipeline.build_retry_chain("job-77", params, "upload", {"final_key": "f"})
    seed = built.tasks[0].args[0]
    assert seed["job_id"] == "job-77"
    assert seed["params"] == params.__dict__
    assert seed["final_key"] == "f"


def test_retry_pipeline_resumes_from_reconstructed_context(monkeypatch):
    from celery.canvas import _chain

    monkeypatch.setattr(
        pipeline, "_reconstruct_context", lambda job_id, params: _full_seed()
    )
    captured: dict = {}

    def _fake_apply_async(self, *args, **kwargs):
        captured["stages"] = _short_stage_names(self)
        return _FakeAsyncResult("resume-id")

    monkeypatch.setattr(_chain, "apply_async", _fake_apply_async)

    params = ReelForgeParams(video_subject="t", platforms=("youtube",))
    task_id = pipeline.retry_pipeline("job-1", params, "compose")

    assert task_id == "resume-id"
    assert captured["stages"] == ["stage_compose_task", "stage_upload_task"]


def test_retry_pipeline_falls_back_when_reconstruction_incomplete(monkeypatch):
    from celery.canvas import _chain

    # Missing avatar_key/ass_key -> compose cannot resume -> full re-run.
    partial = {"job_id": "job-1", "params": {}, "audio_key": "a"}
    monkeypatch.setattr(
        pipeline, "_reconstruct_context", lambda job_id, params: partial
    )
    captured: dict = {}

    def _fake_apply_async(self, *args, **kwargs):
        captured["stages"] = _short_stage_names(self)
        return _FakeAsyncResult("fallback-id")

    monkeypatch.setattr(_chain, "apply_async", _fake_apply_async)

    params = ReelForgeParams(video_subject="t", platforms=("youtube",))
    task_id = pipeline.retry_pipeline("job-1", params, "compose")

    assert task_id == "fallback-id"
    # Full re-run: chain starts at script and includes every stage.
    assert captured["stages"][0] == "stage_script_task"
    assert "stage_upload_task" in captured["stages"]


def test_retry_pipeline_falls_back_when_db_unavailable(monkeypatch):
    from celery.canvas import _chain

    monkeypatch.setattr(
        pipeline, "_reconstruct_context", lambda job_id, params: None
    )
    captured: dict = {}

    def _fake_apply_async(self, *args, **kwargs):
        captured["stages"] = _short_stage_names(self)
        return _FakeAsyncResult("fb-none")

    monkeypatch.setattr(_chain, "apply_async", _fake_apply_async)

    params = ReelForgeParams(video_subject="t", platforms=())
    task_id = pipeline.retry_pipeline("job-1", params, "captions")

    assert task_id == "fb-none"
    assert captured["stages"][0] == "stage_script_task"


@pytest.mark.parametrize("failed_stage", ["script", "", "bogus"])
def test_retry_pipeline_top_of_dag_is_full_rerun(monkeypatch, failed_stage):
    from celery.canvas import _chain

    # Reconstruction must NOT even be attempted for these.
    def _boom(job_id, params):  # pragma: no cover - must not be called
        raise AssertionError("reconstruction should be skipped")

    monkeypatch.setattr(pipeline, "_reconstruct_context", _boom)
    captured: dict = {}

    def _fake_apply_async(self, *args, **kwargs):
        captured["stages"] = _short_stage_names(self)
        return _FakeAsyncResult("full")

    monkeypatch.setattr(_chain, "apply_async", _fake_apply_async)

    params = ReelForgeParams(video_subject="t", platforms=("youtube",))
    task_id = pipeline.retry_pipeline("job-1", params, failed_stage)

    assert task_id == "full"
    assert captured["stages"][0] == "stage_script_task"


def test_retry_pipeline_upload_without_platforms_falls_back(monkeypatch):
    from celery.canvas import _chain

    def _boom(job_id, params):  # pragma: no cover - must not be called
        raise AssertionError("reconstruction should be skipped")

    monkeypatch.setattr(pipeline, "_reconstruct_context", _boom)
    captured: dict = {}

    def _fake_apply_async(self, *args, **kwargs):
        captured["stages"] = _short_stage_names(self)
        return _FakeAsyncResult("up-fb")

    monkeypatch.setattr(_chain, "apply_async", _fake_apply_async)

    params = ReelForgeParams(video_subject="t", platforms=())
    task_id = pipeline.retry_pipeline("job-1", params, "upload")

    assert task_id == "up-fb"
    # No platforms => a full re-run that omits the upload stage entirely.
    assert captured["stages"][0] == "stage_script_task"
    assert "stage_upload_task" not in captured["stages"]


# ---------------------------------------------------------------------------
# tasks.py — monotonic progress across parallel completion orders (LOW #5)
# ---------------------------------------------------------------------------


class _FakeJob:
    """Minimal Job stand-in carrying the mutable stages map + progress cache."""

    def __init__(self) -> None:
        self.stages: dict = {}
        self.progress: int = 0


def _new_job_db():
    """Create a fresh in-memory SQLite DB seeded with one PROCESSING job.

    Returns ``(factory, job_id)`` where ``factory`` is a ``sessionmaker``
    mirroring the production session config (``expire_on_commit=False``) so the
    identity-map staleness the real bug exploits is faithfully reproduced.
    """
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    with factory() as seed:
        user = User(email="prog@example.com", display_name="Prog", credits=0)
        seed.add(user)
        seed.flush()
        job = Job(
            user_id=user.id,
            kind="avatar_reel",
            state=4,
            progress=0,
            stages={},
            params={},
        )
        seed.add(job)
        seed.flush()
        job_id = job.id
        seed.commit()
    return factory, job_id


def _patch_real_session(monkeypatch, factory):
    """Point ``_safe_set_progress`` at real (per-call) sessions from ``factory``.

    Mirrors the production ``get_session`` contract: a fresh session per call,
    committed on clean exit and always closed — so each ``_safe_set_progress``
    invocation runs in its own transaction just like a Celery task would.
    """

    @contextlib.contextmanager
    def _real_get_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr("app.models.db.base.get_session", _real_get_session)


def _read_progress(factory, job_id: str) -> int:
    with factory() as session:
        return int(JobRepository(session).get(job_id).progress)


def _drive_progress(monkeypatch, factory, job_id, completion_order, has_platforms):
    """Simulate the real _report_success order: mark complete, then recompute.

    Runs against a real SQLite-backed ``Job`` row. Returns the list of persisted
    progress values observed after each stage completion, in ``completion_order``.
    """
    _patch_real_session(monkeypatch, factory)

    observed: list[int] = []
    for stage in completion_order:
        # _report_success writes stage=complete (committed) BEFORE set_progress.
        with factory() as session:
            JobRepository(session).update_stage(job_id, stage, "complete")
            session.commit()
        tasks._safe_set_progress(job_id, stage, has_platforms)
        observed.append(_read_progress(factory, job_id))
    return observed


def test_progress_never_regresses_when_captions_finishes_after_avatar(monkeypatch):
    """The exact LOW #5 bug: avatar (60%) then captions must not drop to 45%."""
    factory, job_id = _new_job_db()
    observed = _drive_progress(
        monkeypatch, factory, job_id, ["script", "tts", "avatar", "captions"], True
    )

    # Strictly non-decreasing throughout.
    assert observed == sorted(observed)
    # After avatar the union {script,tts,avatar} = 60%.
    assert observed[2] == 60
    # After captions the union {script,tts,avatar,captions} = 75% (NOT 45%).
    assert observed[3] == 75


@pytest.mark.parametrize(
    "order",
    [
        ["script", "tts", "avatar", "captions", "compose", "upload"],
        ["script", "tts", "captions", "avatar", "compose", "upload"],
    ],
)
def test_progress_monotonic_across_parallel_completion_orders(monkeypatch, order):
    factory, job_id = _new_job_db()
    observed = _drive_progress(monkeypatch, factory, job_id, order, True)

    # Never decreases regardless of which parallel branch reports first.
    assert observed == sorted(observed)
    # Both orders converge to the same terminal progress.
    assert observed[-1] == 100


def test_progress_guarded_update_rejects_stale_lower_write(monkeypatch):
    """LOW #5 lost-update: a stale session must not clobber a higher commit.

    Reproduces the avatar ∥ captions race at its root — the identity-map hit.
    ``_safe_set_progress`` reads the ``Job`` row, then (BEFORE it writes) a
    concurrent sibling commits a HIGHER progress. The bug's read-then-write
    clamped against the stale in-session snapshot and unconditionally wrote a
    lower value; the atomic guarded ``UPDATE ... WHERE progress < :value`` must
    refuse the regression.

    The concurrent commit is injected via ``compute_progress`` (called after the
    read, before the write) which bumps ``progress`` to 80 with a raw SQL UPDATE
    — leaving the already-loaded ORM object stale at its read value, exactly the
    production identity-map mechanism — and returns a LOWER computed value (60).
    """
    factory, job_id = _new_job_db()
    with factory() as seed:
        JobRepository(seed).set_progress(job_id, 50)
        seed.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                stages={
                    "script": "complete",
                    "tts": "complete",
                    "avatar": "complete",
                }
            )
        )
        seed.commit()

    _patch_real_session(monkeypatch, factory)

    captured: dict = {}

    @contextlib.contextmanager
    def _capturing_get_session():
        session = factory()
        captured["session"] = session
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr("app.models.db.base.get_session", _capturing_get_session)

    def _stale_compute(done, has_platforms):
        # A concurrent sibling commits a HIGHER progress AFTER this session read
        # the row. Raw SQL so the already-loaded ORM object stays stale (=50).
        session = captured["session"]
        session.execute(
            text("UPDATE jobs SET progress = 80 WHERE id = :id"), {"id": job_id}
        )
        session.flush()
        return 60  # this session's own (now stale) lower computation

    monkeypatch.setattr(tasks, "compute_progress", _stale_compute)

    tasks._safe_set_progress(job_id, "avatar", True)

    # The guarded UPDATE must NOT lower the already-committed 80 back to 60.
    assert _read_progress(factory, job_id) == 80


def test_completed_stages_unions_db_complete_stages():
    job = _FakeJob()
    job.stages = {
        "script": "complete",
        "tts": "complete",
        "avatar": "complete",
        "captions": "running",  # not yet complete
    }
    # Even resuming from the captions closure, avatar (from the DB) is counted.
    done = tasks._completed_stages(job, "captions")
    assert {"script", "tts", "avatar", "captions"} <= done


# ---------------------------------------------------------------------------
# tasks.py — in-app notification emit on job lifecycle (best-effort)
#
# A job reaching DONE (its terminal stage completes) emits a ``job_complete``
# notification; a job marked FAILED (on_failure/mark_failed path) emits a
# ``job_failed`` one. Both are best-effort: a notification failure must NEVER
# fail a job. These tests monkeypatch the notifications module + the repo/session
# used to resolve the owning ``user_id`` from the Job row.
# ---------------------------------------------------------------------------


class _FakeNotifications:
    """Capturing stand-in for ``app.services.notifications``."""

    def __init__(self) -> None:
        self.complete_calls: list[tuple] = []
        self.failed_calls: list[tuple] = []

    def notify_job_complete(self, user_id, job_id, result_url=None):
        self.complete_calls.append((user_id, job_id, result_url))
        return "notif-complete-id"

    def notify_job_failed(self, user_id, job_id, error):
        self.failed_calls.append((user_id, job_id, error))
        return "notif-failed-id"


class _OwnedJob:
    """Minimal Job row exposing the ``user_id`` the emit path resolves."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id


class _OwnerJobRepo:
    """In-memory JobRepository whose ``get`` returns the seeded Job row.

    ``mark_failed``/``update_stage``/``set_progress`` are no-op stubs so the
    surrounding best-effort reporting helpers never raise during these tests.
    """

    def __init__(self, session) -> None:  # noqa: ANN001 - session doubles as row
        self._job = session

    def get(self, job_id: str):
        return self._job

    def mark_failed(self, job_id: str, stage: str, error: str):
        return self._job

    def update_stage(self, job_id: str, stage: str, status: str):
        return self._job

    def set_progress(self, job_id: str, progress: int) -> None:
        return None


def _patch_owner(monkeypatch, user_id: str = "owner-1") -> _OwnedJob:
    """Patch get_session/JobRepository so ``_resolve_user_id`` finds ``user_id``."""
    job_row = _OwnedJob(user_id)

    @contextlib.contextmanager
    def _fake_get_session():
        yield job_row  # the "session" doubles as the Job-row store

    monkeypatch.setattr("app.models.db.base.get_session", _fake_get_session)
    monkeypatch.setattr("app.models.db.repositories.JobRepository", _OwnerJobRepo)
    return job_row


def test_is_terminal_stage_matches_build_chain_dag():
    # upload is terminal only when platforms were requested.
    assert tasks._is_terminal_stage("upload", has_platforms=True) is True
    assert tasks._is_terminal_stage("compose", has_platforms=True) is False
    # without platforms the chain omits upload -> compose is terminal.
    assert tasks._is_terminal_stage("compose", has_platforms=False) is True
    assert tasks._is_terminal_stage("upload", has_platforms=False) is False
    # intermediate stages are never terminal.
    for stage in ("script", "tts", "avatar", "captions"):
        assert tasks._is_terminal_stage(stage, has_platforms=True) is False


def test_resolve_user_id_reads_from_job_row(monkeypatch):
    _patch_owner(monkeypatch, "owner-42")
    assert tasks._resolve_user_id("job-1") == "owner-42"


def test_resolve_user_id_empty_when_job_missing(monkeypatch):
    class _NoneRepo:
        def __init__(self, session) -> None:  # noqa: ANN001
            pass

        def get(self, job_id: str):
            return None

    @contextlib.contextmanager
    def _fake_get_session():
        yield object()

    monkeypatch.setattr("app.models.db.base.get_session", _fake_get_session)
    monkeypatch.setattr("app.models.db.repositories.JobRepository", _NoneRepo)
    assert tasks._resolve_user_id("job-x") == ""


def test_resolve_user_id_empty_for_blank_job_id(monkeypatch):
    # No DB access at all for an empty job id.
    def _boom():  # pragma: no cover - must not be called
        raise AssertionError("get_session must not be called for blank job_id")

    monkeypatch.setattr("app.models.db.base.get_session", _boom)
    assert tasks._resolve_user_id("") == ""


def test_resolve_user_id_swallows_db_error(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.models.db.base.get_session", _boom)
    # Best-effort: a DB failure degrades to "" rather than raising.
    assert tasks._resolve_user_id("job-1") == ""


def test_done_job_emits_job_complete_via_run_stage(monkeypatch):
    """A terminal (upload) stage completing emits a ``job_complete``."""
    fake = _FakeNotifications()
    monkeypatch.setattr(tasks, "notifications", fake)
    _patch_owner(monkeypatch, "owner-done")
    # Isolate the notification wiring from telemetry/DB reporting.
    monkeypatch.setattr(tasks, "_report_start", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_report_success", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_safe_record_cost", lambda *a, **k: None)

    ctx = {
        "job_id": "job-done",
        "params": ReelForgeParams(
            video_subject="t", platforms=("youtube",)
        ).__dict__,
        "final_key": "jobs/job-done/final.mp4",
    }
    out = tasks._run_stage(
        ctx, "upload", lambda job_id, params, c: {"upload_results": []}
    )

    assert out["job_id"] == "job-done"
    # No presigned URL is persisted — the notification carries only the job_id;
    # the download link is presigned at read time from Job.result_key.
    assert fake.complete_calls == [("owner-done", "job-done", None)]
    assert fake.failed_calls == []


def test_done_job_no_platforms_emits_on_compose(monkeypatch):
    """Without platforms, compose is terminal and emits ``job_complete``."""
    fake = _FakeNotifications()
    monkeypatch.setattr(tasks, "notifications", fake)
    _patch_owner(monkeypatch, "owner-c")
    monkeypatch.setattr(tasks, "_report_start", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_report_success", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_safe_record_cost", lambda *a, **k: None)

    ctx = {
        "job_id": "job-nc",
        "params": ReelForgeParams(video_subject="t", platforms=()).__dict__,
        "final_key": "jobs/job-nc/final.mp4",
    }
    tasks._run_stage(ctx, "compose", lambda job_id, params, c: {"final_key": "k"})

    assert fake.complete_calls == [("owner-c", "job-nc", None)]


def test_intermediate_stage_does_not_emit(monkeypatch):
    """A non-terminal stage (compose WITH platforms) emits nothing."""
    fake = _FakeNotifications()
    monkeypatch.setattr(tasks, "notifications", fake)
    _patch_owner(monkeypatch, "owner-mid")
    monkeypatch.setattr(tasks, "_report_start", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_report_success", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_safe_record_cost", lambda *a, **k: None)

    ctx = {
        "job_id": "job-mid",
        "params": ReelForgeParams(
            video_subject="t", platforms=("youtube",)
        ).__dict__,
    }
    tasks._run_stage(ctx, "compose", lambda job_id, params, c: {"final_key": "k"})

    assert fake.complete_calls == []
    assert fake.failed_calls == []


def test_failed_job_emits_job_failed_via_report_failure(monkeypatch):
    """The on_failure/mark_failed path emits a ``job_failed`` notification."""
    fake = _FakeNotifications()
    monkeypatch.setattr(tasks, "notifications", fake)
    # Silence telemetry + the real mark_failed (DB) so we assert only the emit.
    monkeypatch.setattr(tasks, "record_event", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_safe_mark_failed", lambda *a, **k: None)
    _patch_owner(monkeypatch, "owner-fail")

    tasks._report_failure("job-fail", "avatar", RuntimeError("boom"))

    assert fake.failed_calls == [("owner-fail", "job-fail", "boom")]
    assert fake.complete_calls == []


def test_on_failure_hook_emits_job_failed(monkeypatch):
    """``StageTask.on_failure`` drives the failed-notification emit end to end."""
    fake = _FakeNotifications()
    monkeypatch.setattr(tasks, "notifications", fake)
    monkeypatch.setattr(tasks, "record_event", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_safe_mark_failed", lambda *a, **k: None)
    _patch_owner(monkeypatch, "owner-oh")

    # Invoke the base Task.on_failure unbound with a stub carrying the task name.
    stub = type("_S", (), {"name": "app.workers.tasks.stage_tts_task"})()
    tasks.StageTask.on_failure(
        stub,
        RuntimeError("kaboom"),
        "task-id",
        ({"job_id": "job-oh"},),
        {},
        None,
    )

    assert fake.failed_calls == [("owner-oh", "job-oh", "kaboom")]


def test_notify_helpers_noop_when_layer_unavailable(monkeypatch):
    """A stripped image with no notifications layer degrades to a no-op."""
    monkeypatch.setattr(tasks, "notifications", None)

    def _boom():  # pragma: no cover - user resolution must be skipped
        raise AssertionError("must not resolve user without a notifications layer")

    monkeypatch.setattr("app.models.db.base.get_session", _boom)
    # Neither call raises nor touches the DB.
    tasks._safe_notify_job_complete("job-1", {"final_key": "k"})
    tasks._safe_notify_job_failed("job-1", "err")


def test_notify_complete_swallows_emit_error(monkeypatch):
    """A raising notify_job_complete must never propagate out of the emit."""

    class _BoomNotifications:
        def notify_job_complete(self, *a, **k):
            raise RuntimeError("notifications down")

    monkeypatch.setattr(tasks, "notifications", _BoomNotifications())
    _patch_owner(monkeypatch, "u")
    # No exception escapes (best-effort contract).
    tasks._safe_notify_job_complete("job-1", {"final_key": "k"})


def test_report_failure_survives_notification_error(monkeypatch):
    """A notification failure must NEVER fail the job's failure path."""

    class _BoomNotifications:
        def notify_job_failed(self, *a, **k):
            raise RuntimeError("notifications down")

    monkeypatch.setattr(tasks, "notifications", _BoomNotifications())
    monkeypatch.setattr(tasks, "record_event", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "_safe_mark_failed", lambda *a, **k: None)
    _patch_owner(monkeypatch, "u")

    # _report_failure completes normally despite the notification blowing up.
    tasks._report_failure("job-1", "tts", RuntimeError("x"))


def test_notify_complete_skips_when_user_unresolved(monkeypatch):
    """No user_id (missing job) => no notification is emitted."""
    fake = _FakeNotifications()
    monkeypatch.setattr(tasks, "notifications", fake)
    monkeypatch.setattr(tasks, "_resolve_user_id", lambda job_id: "")

    tasks._safe_notify_job_complete("job-1", {"final_key": "k"})
    tasks._safe_notify_job_failed("job-1", "err")

    assert fake.complete_calls == []
    assert fake.failed_calls == []


def test_notify_complete_never_persists_presigned_url(monkeypatch):
    """job_complete emits only the job_id — the presigned URL is read-time only.

    A short-lived R2 presigned credential must never land in Notification.data
    (it would expire while the row lives on). Even with a ``final_key`` in the
    context, no ``result_url`` is passed into the notification.
    """
    fake = _FakeNotifications()
    monkeypatch.setattr(tasks, "notifications", fake)
    _patch_owner(monkeypatch, "owner-x")

    tasks._safe_notify_job_complete("job-x", {"final_key": "jobs/job-x/final.mp4"})

    assert fake.complete_calls == [("owner-x", "job-x", None)]


class _FailGuardJob:
    """Job row modelling the repository's first-failure guard state."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.error: str = ""
        self.failed_stage: str | None = None


class _FailGuardRepo:
    """In-memory JobRepository whose ``mark_failed`` honours the first-failure guard.

    The first call stamps ``failed_stage`` with the failing stage; later calls
    (the parallel sibling) find it already set and return the row unchanged with
    the *earliest* root cause — exactly as the real repository does under a row
    lock.
    """

    def __init__(self, session) -> None:  # noqa: ANN001 - session doubles as row
        self._job = session

    def get(self, job_id: str):
        return self._job

    def mark_failed(self, job_id: str, stage: str, error: str):
        job = self._job
        if job.failed_stage:  # earliest root cause already recorded — keep it.
            return job
        job.failed_stage = stage
        job.error = str(error)
        return job


def test_parallel_failures_emit_job_failed_exactly_once(monkeypatch):
    """Both avatar ∥ captions chord siblings failing must emit ONE notification.

    Each parallel chord header task has its own ``on_failure`` hook, so both can
    reach ``_report_failure`` independently. The emit is gated on the repository
    first-failure signal so the user sees a single 'video failed' bell entry, not
    a duplicate per sibling.
    """
    fake = _FakeNotifications()
    monkeypatch.setattr(tasks, "notifications", fake)
    monkeypatch.setattr(tasks, "record_event", lambda *a, **k: None)

    job_row = _FailGuardJob("owner-dup")

    @contextlib.contextmanager
    def _fake_get_session():
        yield job_row  # the "session" doubles as the Job-row store

    monkeypatch.setattr("app.models.db.base.get_session", _fake_get_session)
    monkeypatch.setattr("app.models.db.repositories.JobRepository", _FailGuardRepo)

    tasks._report_failure("job-dup", "avatar", RuntimeError("avatar boom"))
    tasks._report_failure("job-dup", "captions", RuntimeError("captions boom"))

    # Exactly one notification, carrying the earliest (avatar) root cause.
    assert fake.failed_calls == [("owner-dup", "job-dup", "avatar boom")]
    assert fake.complete_calls == []


def test_safe_mark_failed_reports_first_failure_signal(monkeypatch):
    """_safe_mark_failed returns True for the first stage, False for the sibling."""
    job_row = _FailGuardJob("owner-sig")

    @contextlib.contextmanager
    def _fake_get_session():
        yield job_row

    monkeypatch.setattr("app.models.db.base.get_session", _fake_get_session)
    monkeypatch.setattr("app.models.db.repositories.JobRepository", _FailGuardRepo)

    # First failure records the root cause.
    assert tasks._safe_mark_failed("job-sig", "avatar", "boom") is True
    # Second (parallel) failure is a suppressed duplicate.
    assert tasks._safe_mark_failed("job-sig", "captions", "boom2") is False
    # Empty job id / unknown outcome degrades to None (caller defaults to emit).
    assert tasks._safe_mark_failed("", "avatar", "boom") is None


# ---------------------------------------------------------------------------
# tasks.py + celery_app.py — scheduled-publishing due-runner (Celery beat)
#
# `process_due_publishes_task` is the beat entrypoint fired every minute. It
# delegates to `app.services.scheduler.process_due_publishes` and returns its
# `{"claimed","published","failed"}` summary. It must NEVER raise: a missing
# scheduler layer or a raising entrypoint degrades to a logged zeroed summary so
# a beat tick can never crash the worker. The beat schedule must carry an entry
# wiring this task at a 60s cadence.
# ---------------------------------------------------------------------------


class _FakeScheduler:
    """Capturing stand-in for ``app.services.scheduler``."""

    def __init__(self, summary=None, exc: Exception | None = None) -> None:
        self.summary = (
            summary
            if summary is not None
            else {"claimed": 2, "published": 1, "failed": 1}
        )
        self.exc = exc
        self.calls: list[tuple] = []

    def process_due_publishes(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.summary


def _run_beat_task():
    """Invoke the bound beat task exactly as Celery would (``self`` = the task)."""
    return tasks.process_due_publishes_task.run()


def test_process_due_publishes_task_delegates_to_scheduler(monkeypatch):
    """The beat task calls scheduler.process_due_publishes and returns its summary."""
    fake = _FakeScheduler(summary={"claimed": 3, "published": 3, "failed": 0})
    monkeypatch.setattr(tasks, "scheduler", fake)

    result = _run_beat_task()

    # Delegated exactly once with no explicit args (real UTC now inside scheduler).
    assert fake.calls == [((), {})]
    # The scheduler's summary is returned verbatim.
    assert result == {"claimed": 3, "published": 3, "failed": 0}


def test_process_due_publishes_task_never_raises_on_scheduler_error(monkeypatch):
    """A raising scheduler degrades to a zeroed summary — the tick never crashes."""
    fake = _FakeScheduler(exc=RuntimeError("db exploded"))
    monkeypatch.setattr(tasks, "scheduler", fake)

    result = _run_beat_task()

    assert fake.calls == [((), {})]
    assert result == {"claimed": 0, "published": 0, "failed": 0}


def test_process_due_publishes_task_noop_when_scheduler_unavailable(monkeypatch):
    """A stripped image with no scheduler layer degrades to a zeroed no-op summary."""
    monkeypatch.setattr(tasks, "scheduler", None)

    result = _run_beat_task()

    assert result == {"claimed": 0, "published": 0, "failed": 0}


def test_process_due_publishes_task_coerces_non_dict_summary(monkeypatch):
    """A defensive guard: a non-dict return degrades to the zeroed summary."""
    fake = _FakeScheduler(summary="not-a-dict")  # type: ignore[arg-type]
    monkeypatch.setattr(tasks, "scheduler", fake)

    result = _run_beat_task()

    assert result == {"claimed": 0, "published": 0, "failed": 0}


def test_process_due_publishes_task_is_registered_on_celery_app():
    """The beat task is a registered Celery task under its fully-qualified name."""
    from app.workers.celery_app import celery_app

    name = "app.workers.tasks.process_due_publishes_task"
    assert tasks.process_due_publishes_task.name == name
    assert name in celery_app.tasks


def test_beat_schedule_contains_due_publishes_entry_every_60s():
    """celery_app.conf.beat_schedule wires the due-runner at a 60s cadence."""
    from app.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert isinstance(schedule, dict) and schedule, "beat_schedule must be populated"

    entries = [
        entry
        for entry in schedule.values()
        if entry.get("task") == "app.workers.tasks.process_due_publishes_task"
    ]
    assert len(entries) == 1, "exactly one due-publishes beat entry expected"
    assert float(entries[0]["schedule"]) == 60.0


def test_beat_schedule_does_not_disturb_existing_task_routes():
    """Adding beat_schedule must keep the existing render-queue routing intact."""
    from app.workers.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert routes["app.workers.tasks.stage_avatar_task"] == {"queue": "render"}
    assert routes["app.workers.tasks.stage_compose_task"] == {"queue": "render"}


class _FakeOAuthRefresh:
    def __init__(self, summary=None, exc: Exception | None = None) -> None:
        self.summary = summary if summary is not None else {
            "considered": 2,
            "refreshed": 2,
            "failed": 0,
        }
        self.exc = exc
        self.calls: list[tuple] = []

    def sweep_expiring_accounts(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.summary


def test_sweep_oauth_token_refresh_task_is_best_effort(monkeypatch):
    fake = _FakeOAuthRefresh()
    monkeypatch.setattr(tasks, "oauth_connect", fake)

    result = tasks.sweep_oauth_token_refresh_task.run()

    assert fake.calls == [((), {})]
    assert result == {"considered": 2, "refreshed": 2, "failed": 0}


def test_sweep_oauth_token_refresh_task_never_raises(monkeypatch):
    fake = _FakeOAuthRefresh(exc=RuntimeError("provider down"))
    monkeypatch.setattr(tasks, "oauth_connect", fake)

    assert tasks.sweep_oauth_token_refresh_task.run() == {
        "considered": 0,
        "refreshed": 0,
        "failed": 0,
    }


def test_beat_schedule_contains_oauth_refresh_sweep():
    from app.workers.celery_app import celery_app

    entries = [
        entry
        for entry in celery_app.conf.beat_schedule.values()
        if entry.get("task") == "app.workers.tasks.sweep_oauth_token_refresh_task"
    ]
    assert len(entries) == 1
    assert float(entries[0]["schedule"]) == 300.0


class _FakeJobIdempotency:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[tuple] = []

    def sweep_expired_job_requests(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.exc is not None:
            raise self.exc
        return {"deleted": 3}


def test_sweep_job_idempotency_task_is_best_effort(monkeypatch):
    fake = _FakeJobIdempotency()
    monkeypatch.setattr(tasks, "job_idempotency", fake)

    assert tasks.sweep_job_idempotency_task.run() == {"deleted": 3}
    assert fake.calls == [((), {})]


def test_sweep_job_idempotency_task_never_raises(monkeypatch):
    monkeypatch.setattr(
        tasks, "job_idempotency", _FakeJobIdempotency(RuntimeError("db down"))
    )

    assert tasks.sweep_job_idempotency_task.run() == {"deleted": 0}


def test_beat_schedule_contains_job_idempotency_sweep():
    from app.workers.celery_app import celery_app

    entries = [
        entry
        for entry in celery_app.conf.beat_schedule.values()
        if entry.get("task") == "app.workers.tasks.sweep_job_idempotency_task"
    ]
    assert len(entries) == 1
    assert float(entries[0]["schedule"]) == 24 * 60 * 60.0
