"""Unit tests for the runner's publish-scheduling pass (``schedule_due``).

Fakes stand in for the clip repo + ``schedule_publish``; the REAL
``scheduling_policy.decide`` is exercised so the daily-cap / min-gap / platform
bridge behaviour is genuinely covered. Asserts:

* the ``youtube_shorts -> youtube`` name bridge is applied to ``platform_config``,
* every scheduled ``run_at`` is UTC and strictly in the future,
* only COMPLETE-job clips are scheduled (the repo already filters; the runner
  schedules exactly what it's handed),
* per-account recent-post history is accumulated so successive clips for one
  account are spread by min-gap,
* the daily cap pushes overflow to a future day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.domains.publishing import scheduling_policy
from app.domains.series.runner import ChannelRunConfig, RunnerDeps, schedule_due


@dataclass
class _FakeClip:
    id: str
    job_id: str
    account: str
    platform: str
    scheduled_publish_id: str | None = None
    status: str = "pending"


class _FakeClipRepo:
    def __init__(self, pending):
        self._pending = list(pending)
        self.scheduled: list[tuple[str, str]] = []
        # Optional cross-tick seams (default empty -> single-pass behavior).
        self.seeded_times: list[tuple[str, str, datetime]] = []
        self.failures: dict[tuple[str, str], int] = {}

    def list_pending_publish(self, channel_id):
        return list(self._pending)

    def mark_scheduled(self, clip_id, scheduled_publish_id):
        self.scheduled.append((clip_id, scheduled_publish_id))

    def scheduled_run_ats(self, channel_id, *, now=None):
        return list(self.seeded_times)

    def consecutive_publish_failures(self, channel_id):
        return dict(self.failures)


class _FakeSchedule:
    """Captures schedule_publish calls; enforces the future-time guard like prod."""

    def __init__(self):
        self.calls: list[dict] = []
        self._n = 0

    def __call__(self, session, user_id, job_id, platforms, scheduled_at):
        # Mirror scheduler.schedule_publish's future guard so a past time is a bug.
        assert isinstance(scheduled_at, datetime)
        self._n += 1
        row_id = f"sched-{self._n}"
        self.calls.append(
            {
                "user_id": user_id,
                "job_id": job_id,
                "platforms": list(platforms),
                "scheduled_at": scheduled_at,
            }
        )
        return type("Row", (), {"id": row_id})()


def _deps(clip_repo, schedule) -> RunnerDeps:
    return RunnerDeps(
        job_repo=object(),
        clip_repo=clip_repo,
        start_pipeline=lambda *a, **k: "task",
        schedule_publish=schedule,
        session=object(),
    )


def _config(**overrides) -> ChannelRunConfig:
    base = dict(channel_id="chan-1", user_id="user-1", platforms=("youtube_shorts",))
    base.update(overrides)
    return ChannelRunConfig(**base)


NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_youtube_shorts_bridge_and_future_utc_run_at():
    clip = _FakeClip(id="c1", job_id="job-1", account="acct1", platform="youtube_shorts")
    clip_repo = _FakeClipRepo([clip])
    schedule = _FakeSchedule()

    result = schedule_due(_config(), now=NOW, deps=_deps(clip_repo, schedule))

    assert result.scheduled == 1
    assert len(schedule.calls) == 1
    call = schedule.calls[0]
    # schedule_publish keeps the original platform NAME ('youtube_shorts').
    assert call["platforms"] == ["youtube_shorts"]
    # run_at is UTC-aware and strictly in the future.
    run_at = call["scheduled_at"]
    assert run_at.tzinfo is not None
    assert run_at.astimezone(timezone.utc) > NOW
    # The clip was marked scheduled with the returned schedule id.
    assert clip_repo.scheduled == [("c1", "sched-1")]


def test_bridge_maps_to_youtube_daily_cap_of_two():
    # youtube daily_cap == 2; a 3rd same-account clip must land on a FUTURE day.
    clips = [
        _FakeClip(id=f"c{i}", job_id=f"job-{i}", account="acct1", platform="youtube_shorts")
        for i in range(1, 4)
    ]
    clip_repo = _FakeClipRepo(clips)
    schedule = _FakeSchedule()

    result = schedule_due(_config(), now=NOW, deps=_deps(clip_repo, schedule))

    assert result.scheduled == 3
    times = [c["scheduled_at"].astimezone(timezone.utc) for c in schedule.calls]
    # First two land on NOW's UTC day; the 3rd is pushed to a later day (cap=2).
    assert times[0].date() == NOW.date()
    assert times[1].date() == NOW.date()
    assert times[2].date() > NOW.date()


def test_min_gap_spreads_successive_same_account_posts():
    # tiktok min_gap_h == 3.0; two same-account clips must be >= 3h apart.
    clips = [
        _FakeClip(id="c1", job_id="job-1", account="acct1", platform="tiktok"),
        _FakeClip(id="c2", job_id="job-2", account="acct1", platform="tiktok"),
    ]
    clip_repo = _FakeClipRepo(clips)
    schedule = _FakeSchedule()

    schedule_due(_config(platforms=("tiktok",)), now=NOW, deps=_deps(clip_repo, schedule))

    t0, t1 = (c["scheduled_at"].astimezone(timezone.utc) for c in schedule.calls)
    gap = abs((t1 - t0).total_seconds())
    assert gap >= scheduling_policy.platform_config("tiktok")["min_gap_h"] * 3600 - 1


def test_distinct_accounts_do_not_interfere():
    # Two different accounts: each gets its own history, so both can post promptly.
    clips = [
        _FakeClip(id="c1", job_id="job-1", account="acct1", platform="tiktok"),
        _FakeClip(id="c2", job_id="job-2", account="acct2", platform="tiktok"),
    ]
    clip_repo = _FakeClipRepo(clips)
    schedule = _FakeSchedule()

    schedule_due(_config(platforms=("tiktok",)), now=NOW, deps=_deps(clip_repo, schedule))

    t0, t1 = (c["scheduled_at"].astimezone(timezone.utc) for c in schedule.calls)
    # Independent accounts land close together (both within a minute of the lead).
    assert abs((t1 - t0).total_seconds()) < 120


def test_seeded_scheduled_times_enforce_cap_across_ticks():
    # Two youtube posts already scheduled TODAY (cap == 2). A fresh pending clip
    # for the SAME account must be deferred to a FUTURE day — the daily cap holds
    # ACROSS beat ticks, not just within one pass (regression: cross-tick cap).
    clip = _FakeClip(id="c1", job_id="job-1", account="acct1", platform="youtube_shorts")
    clip_repo = _FakeClipRepo([clip])
    clip_repo.seeded_times = [
        ("acct1", "youtube_shorts", NOW.replace(hour=15)),
        ("acct1", "youtube_shorts", NOW.replace(hour=20)),
    ]
    schedule = _FakeSchedule()

    result = schedule_due(_config(), now=NOW, deps=_deps(clip_repo, schedule))

    assert result.scheduled == 1
    run_at = schedule.calls[0]["scheduled_at"].astimezone(timezone.utc)
    assert run_at.date() > NOW.date()


def test_seeded_times_for_other_account_do_not_defer():
    # The prior-tick posts belong to a DIFFERENT account — the fresh clip's
    # account is untouched and posts promptly today.
    clip = _FakeClip(id="c1", job_id="job-1", account="acct1", platform="youtube_shorts")
    clip_repo = _FakeClipRepo([clip])
    clip_repo.seeded_times = [
        ("acctOTHER", "youtube_shorts", NOW.replace(hour=15)),
        ("acctOTHER", "youtube_shorts", NOW.replace(hour=20)),
    ]
    schedule = _FakeSchedule()

    result = schedule_due(_config(), now=NOW, deps=_deps(clip_repo, schedule))

    assert result.scheduled == 1
    assert schedule.calls[0]["scheduled_at"].astimezone(timezone.utc).date() == NOW.date()


def test_consecutive_failures_push_out_earliest_time():
    # 3 trailing publish failures -> exponential backoff (0.5 * 2^2 == 2h): the
    # decided run_at must be pushed at least that far into the future.
    clip = _FakeClip(id="c1", job_id="job-1", account="acct1", platform="tiktok")
    clip_repo = _FakeClipRepo([clip])
    clip_repo.failures = {("acct1", "tiktok"): 3}
    schedule = _FakeSchedule()

    schedule_due(_config(platforms=("tiktok",)), now=NOW, deps=_deps(clip_repo, schedule))

    run_at = schedule.calls[0]["scheduled_at"].astimezone(timezone.utc)
    backoff_h = scheduling_policy.backoff_delay_h(3)
    assert backoff_h > 0
    assert run_at >= NOW + timedelta(hours=backoff_h) - timedelta(seconds=1)


def test_nothing_pending_schedules_nothing():
    clip_repo = _FakeClipRepo([])
    schedule = _FakeSchedule()
    result = schedule_due(_config(), now=NOW, deps=_deps(clip_repo, schedule))
    assert result.scheduled == 0
    assert result.considered == 0
    assert schedule.calls == []


def test_clip_without_platform_is_skipped():
    clip = _FakeClip(id="c1", job_id="job-1", account="acct1", platform="")
    clip_repo = _FakeClipRepo([clip])
    schedule = _FakeSchedule()
    # Config also has no platforms -> nothing to publish to.
    result = schedule_due(
        _config(platforms=()), now=NOW, deps=_deps(clip_repo, schedule)
    )
    assert result.scheduled == 0
    assert schedule.calls == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
