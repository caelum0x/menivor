"""Integration tests for the channel-runner repositories (in-memory SQLite).

No Postgres/Neon required. Exercises the real ORM + queries:

* ``seen_hashes`` round-trips a persisted ``spec_hash`` ACROSS two runner passes
  (cross-run dedupe), and is strictly channel-scoped,
* ``create`` persists a clip and defaults it to ``pending``,
* ``list_pending_publish`` returns only clips whose owning Job is COMPLETE and
  which are still ``pending`` / unscheduled,
* ``mark_scheduled`` links the clip to a ScheduledPublish id and flips it out of
  the pending set (idempotent re-schedule guard).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import const
from app.models.db.base import Base
from app.models.db.models import Job, ScheduledPublish, User
from app.models.db.repositories import JobRepository
from app.models.db.series_runs import (
    CLIP_STATUS_PENDING,
    CLIP_STATUS_SCHEDULED,
)
from app.domains.series.repository import (
    ChannelClipRepository,
    ChannelRunRepository,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def user(session: Session) -> User:
    u = User(email="runner@example.com", display_name="Runner", credits=0)
    session.add(u)
    session.flush()
    return u


def _job(session: Session, user_id: str, *, state: int) -> Job:
    job = JobRepository(session).create(user_id=user_id, kind="avatar_reel", params={}, batch_id="run-1")
    job.state = state
    session.flush()
    return job


def _run(session: Session, user: User) -> str:
    run = ChannelRunRepository(session).create(
        user_id=user.id, channel_id="chan-1", params={"k": "v"}
    )
    return run.id


# --------------------------------------------------------------------------- #
# seen_hashes / cross-run dedupe
# --------------------------------------------------------------------------- #
def test_seen_hashes_roundtrips_across_two_runner_passes(session, user):
    repo = ChannelClipRepository(session)
    run_id = _run(session, user)
    job = _job(session, user.id, state=const.TASK_STATE_PROCESSING)

    # Pass 1 records a spec_hash.
    assert repo.seen_hashes("chan-1") == set()
    repo.create(
        channel_id="chan-1", run_id=run_id, spec_hash="deadbeefcafef00d",
        job_id=job.id, account="acct1", platform="youtube_shorts",
    )

    # Pass 2 (a fresh repo on the same DB) sees the prior hash — cross-run dedupe.
    repo2 = ChannelClipRepository(session)
    assert repo2.seen_hashes("chan-1") == {"deadbeefcafef00d"}


def test_seen_hashes_is_channel_scoped(session, user):
    repo = ChannelClipRepository(session)
    run_id = _run(session, user)
    job = _job(session, user.id, state=const.TASK_STATE_PROCESSING)
    repo.create(
        channel_id="chan-1", run_id=run_id, spec_hash="aaaa1111bbbb2222",
        job_id=job.id, account="a", platform="tiktok",
    )
    assert repo.seen_hashes("chan-1") == {"aaaa1111bbbb2222"}
    assert repo.seen_hashes("chan-OTHER") == set()
    assert repo.seen_hashes("") == set()


def test_create_defaults_to_pending(session, user):
    repo = ChannelClipRepository(session)
    run_id = _run(session, user)
    job = _job(session, user.id, state=const.TASK_STATE_PROCESSING)
    clip = repo.create(
        channel_id="chan-1", run_id=run_id, spec_hash="hash0001",
        job_id=job.id, account="a", platform="tiktok",
    )
    assert clip.status == CLIP_STATUS_PENDING
    assert clip.scheduled_publish_id is None
    assert clip.id


# --------------------------------------------------------------------------- #
# list_pending_publish — COMPLETE-only
# --------------------------------------------------------------------------- #
def test_list_pending_publish_only_returns_complete_jobs(session, user):
    repo = ChannelClipRepository(session)
    run_id = _run(session, user)
    done_job = _job(session, user.id, state=const.TASK_STATE_COMPLETE)
    busy_job = _job(session, user.id, state=const.TASK_STATE_PROCESSING)

    done_clip = repo.create(
        channel_id="chan-1", run_id=run_id, spec_hash="done0001",
        job_id=done_job.id, account="a", platform="youtube_shorts",
    )
    repo.create(
        channel_id="chan-1", run_id=run_id, spec_hash="busy0001",
        job_id=busy_job.id, account="a", platform="youtube_shorts",
    )

    pending = repo.list_pending_publish("chan-1")
    assert [c.id for c in pending] == [done_clip.id]


def test_mark_scheduled_removes_from_pending_set(session, user):
    repo = ChannelClipRepository(session)
    run_id = _run(session, user)
    done_job = _job(session, user.id, state=const.TASK_STATE_COMPLETE)
    clip = repo.create(
        channel_id="chan-1", run_id=run_id, spec_hash="done0002",
        job_id=done_job.id, account="a", platform="youtube_shorts",
    )
    assert [c.id for c in repo.list_pending_publish("chan-1")] == [clip.id]

    updated = repo.mark_scheduled(clip.id, "sched-xyz")
    assert updated.status == CLIP_STATUS_SCHEDULED
    assert updated.scheduled_publish_id == "sched-xyz"

    # Re-fetch confirms it left the pending set (idempotent re-schedule guard).
    assert repo.list_pending_publish("chan-1") == []


def test_list_pending_publish_channel_scoped(session, user):
    repo = ChannelClipRepository(session)
    run_id = _run(session, user)
    done_job = _job(session, user.id, state=const.TASK_STATE_COMPLETE)
    repo.create(
        channel_id="chan-1", run_id=run_id, spec_hash="done0003",
        job_id=done_job.id, account="a", platform="tiktok",
    )
    assert len(repo.list_pending_publish("chan-1")) == 1
    assert repo.list_pending_publish("chan-2") == []


# --------------------------------------------------------------------------- #
# Cross-tick / per-day seams: scheduled_run_ats / rendered_today_counts /
# consecutive_publish_failures
# --------------------------------------------------------------------------- #
def _sched(session: Session, user_id: str, job_id: str, *, when: datetime, status: str) -> ScheduledPublish:
    row = ScheduledPublish(
        user_id=user_id, job_id=job_id, platforms=["tiktok"],
        scheduled_at=when, status=status, attempts=0, result={}, error="",
    )
    session.add(row)
    session.flush()
    return row


def _NOW() -> datetime:
    return datetime.now(timezone.utc)


def test_scheduled_run_ats_returns_todays_scheduled_times(session, user):
    repo = ChannelClipRepository(session)
    run_id = _run(session, user)
    now = _NOW()

    # A clip scheduled TODAY -> included.
    job_a = _job(session, user.id, state=const.TASK_STATE_COMPLETE)
    clip_a = repo.create(
        channel_id="chan-1", run_id=run_id, spec_hash="a1a1a1a1a1a1a1a1",
        job_id=job_a.id, account="acct1", platform="youtube_shorts",
    )
    sp_today = _sched(session, user.id, job_a.id, when=now.replace(hour=15, minute=0, second=0, microsecond=0), status="pending")
    repo.mark_scheduled(clip_a.id, sp_today.id)

    # A clip scheduled YESTERDAY -> excluded (before today's UTC midnight).
    job_b = _job(session, user.id, state=const.TASK_STATE_COMPLETE)
    clip_b = repo.create(
        channel_id="chan-1", run_id=run_id, spec_hash="b2b2b2b2b2b2b2b2",
        job_id=job_b.id, account="acct1", platform="youtube_shorts",
    )
    sp_yesterday = _sched(session, user.id, job_b.id, when=now - timedelta(days=1), status="published")
    repo.mark_scheduled(clip_b.id, sp_yesterday.id)

    rows = repo.scheduled_run_ats("chan-1", now=now)
    assert len(rows) == 1
    account, platform, when = rows[0]
    assert account == "acct1"
    assert platform == "youtube_shorts"
    assert when.date() == now.date()
    assert repo.scheduled_run_ats("chan-OTHER", now=now) == []


def test_rendered_today_counts_excludes_failed_and_scopes_by_channel(session, user):
    repo = ChannelClipRepository(session)
    run_id = _run(session, user)
    job = _job(session, user.id, state=const.TASK_STATE_PROCESSING)

    repo.create(channel_id="chan-1", run_id=run_id, spec_hash="c1", job_id=job.id, account="acct1", platform="tiktok")
    repo.create(channel_id="chan-1", run_id=run_id, spec_hash="c2", job_id=job.id, account="acct1", platform="tiktok")
    repo.create(channel_id="chan-1", run_id=run_id, spec_hash="c3", job_id=job.id, account="acct2", platform="tiktok")
    failed = repo.create(channel_id="chan-1", run_id=run_id, spec_hash="c4", job_id=job.id, account="acct1", platform="tiktok")
    repo.mark_failed(failed.id)  # failed renders don't count toward the day's budget

    counts = repo.rendered_today_counts("chan-1")
    assert counts == {"acct1": 2, "acct2": 1}
    assert repo.rendered_today_counts("chan-2") == {}


def test_consecutive_publish_failures_counts_only_trailing_run(session, user):
    repo = ChannelClipRepository(session)
    run_id = _run(session, user)
    now = _NOW()

    def _linked(spec_hash: str, account: str, platform: str, *, when: datetime, status: str):
        job = _job(session, user.id, state=const.TASK_STATE_COMPLETE)
        clip = repo.create(channel_id="chan-1", run_id=run_id, spec_hash=spec_hash, job_id=job.id, account=account, platform=platform)
        sp = _sched(session, user.id, job.id, when=when, status=status)
        repo.mark_scheduled(clip.id, sp.id)

    # acct1: newest two failed, then a published one -> trailing streak == 2.
    _linked("f1f1f1f1f1f1f1f1", "acct1", "tiktok", when=now, status="failed")
    _linked("f2f2f2f2f2f2f2f2", "acct1", "tiktok", when=now - timedelta(hours=3), status="failed")
    _linked("f3f3f3f3f3f3f3f3", "acct1", "tiktok", when=now - timedelta(hours=6), status="published")

    # acct2: newest is published -> streak broken -> absent from the map.
    _linked("aaaa0000aaaa0000", "acct2", "tiktok", when=now, status="published")
    _linked("bbbb0000bbbb0000", "acct2", "tiktok", when=now - timedelta(hours=3), status="failed")

    failures = repo.consecutive_publish_failures("chan-1")
    assert failures.get(("acct1", "tiktok")) == 2
    assert ("acct2", "tiktok") not in failures


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
