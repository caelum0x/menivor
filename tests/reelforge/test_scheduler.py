"""Unit tests for the Scheduled Publishing service (app/services/scheduler.py).

Runs entirely against an in-memory SQLite engine — no Postgres/Neon required —
and monkeypatches ``app.services.publish.publish_job_output`` so no real
cross-post / network I/O happens. Covers:

* ``schedule_publish`` validates job ownership + done-state and normalizes /
  validates platforms.
* ``process_due_publishes`` claims due schedules, publishes them, marks them
  published, marks failed (with ``attempts+1``) on a publish error WITHOUT
  raising out of the loop, and never touches not-yet-due / canceled schedules.
* ``list_scheduled`` / ``cancel_scheduled`` convenience wrappers.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import const
from app.models.db.base import Base
from app.models.db.models import Job, ScheduledPublish, User
from app.models.db.repositories import ScheduledPublishRepository
from app.services import scheduler


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def engine():
    """A shared in-memory SQLite engine (StaticPool) with all tables created."""
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture()
def factory(engine):
    """A context-manager session factory mirroring base.get_session()."""
    maker = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )

    @contextlib.contextmanager
    def _session_factory():
        sess = maker()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    return _session_factory


@pytest.fixture()
def session(engine) -> Session:
    """A standalone session for arranging fixtures / assertions."""
    maker = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    sess = maker()
    try:
        yield sess
    finally:
        sess.close()


def _make_user(session: Session, email: str = "creator@example.com") -> User:
    u = User(email=email)
    session.add(u)
    session.flush()
    return u


def _make_job(session: Session, user_id: str, *, state: int) -> Job:
    job = Job(
        user_id=user_id,
        kind="avatar_reel",
        state=state,
        progress=100 if state == const.TASK_STATE_COMPLETE else 0,
        stages={},
        params={},
        result_key="outputs/final.mp4",
    )
    session.add(job)
    session.flush()
    return job


def _dt(offset_seconds: int = 0) -> datetime:
    base = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=offset_seconds)


# --------------------------------------------------------------------------- #
# schedule_publish — validation
# --------------------------------------------------------------------------- #
def test_schedule_publish_creates_pending_row(session: Session):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()

    row = scheduler.schedule_publish(
        session,
        user_id=user.id,
        job_id=job.id,
        platforms=["tiktok", "youtube_shorts"],
        scheduled_at=_dt(3600),
        now=_dt(0),
    )

    assert row.id and len(row.id) == 32
    assert row.user_id == user.id
    assert row.job_id == job.id
    assert row.platforms == ["tiktok", "youtube_shorts"]
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.youtube_privacy_status == "private"


def test_schedule_publish_normalizes_platforms(session: Session):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()

    row = scheduler.schedule_publish(
        session,
        user_id=user.id,
        job_id=job.id,
        platforms=[" tiktok ", "tiktok", "", "instagram"],
        scheduled_at=_dt(60),
        now=_dt(0),
    )
    # Blanks dropped, duplicates removed, order preserved.
    assert row.platforms == ["tiktok", "instagram"]


def test_schedule_publish_rejects_foreign_job(session: Session):
    owner = _make_user(session, "owner@example.com")
    other = _make_user(session, "other@example.com")
    job = _make_job(session, owner.id, state=const.TASK_STATE_COMPLETE)
    session.commit()

    with pytest.raises(scheduler.ScheduleError, match="job not found"):
        scheduler.schedule_publish(
            session,
            user_id=other.id,
            job_id=job.id,
            platforms=["tiktok"],
            scheduled_at=_dt(60),
            now=_dt(0),
        )


def test_schedule_publish_rejects_missing_job(session: Session):
    user = _make_user(session)
    session.commit()
    with pytest.raises(scheduler.ScheduleError, match="job not found"):
        scheduler.schedule_publish(
            session,
            user_id=user.id,
            job_id="does-not-exist",
            platforms=["tiktok"],
            scheduled_at=_dt(60),
            now=_dt(0),
        )


def test_schedule_publish_rejects_not_done_job(session: Session):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_PROCESSING)
    session.commit()
    with pytest.raises(scheduler.ScheduleError, match="not complete"):
        scheduler.schedule_publish(
            session,
            user_id=user.id,
            job_id=job.id,
            platforms=["tiktok"],
            scheduled_at=_dt(60),
            now=_dt(0),
        )


def test_schedule_publish_rejects_no_platforms(session: Session):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    with pytest.raises(scheduler.ScheduleError, match="at least one platform"):
        scheduler.schedule_publish(
            session,
            user_id=user.id,
            job_id=job.id,
            platforms=["", "   "],
            scheduled_at=_dt(60),
            now=_dt(0),
        )


def test_schedule_publish_rejects_unknown_platform(session: Session):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    with pytest.raises(scheduler.ScheduleError, match="unsupported platform"):
        scheduler.schedule_publish(
            session,
            user_id=user.id,
            job_id=job.id,
            platforms=["myspace"],
            scheduled_at=_dt(60),
            now=_dt(0),
        )


def test_schedule_publish_rejects_bad_scheduled_at(session: Session):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    with pytest.raises(scheduler.ScheduleError, match="scheduled_at"):
        scheduler.schedule_publish(
            session,
            user_id=user.id,
            job_id=job.id,
            platforms=["tiktok"],
            scheduled_at="2026-08-11T12:00:00Z",  # type: ignore[arg-type]
        )


def test_schedule_publish_rejects_past_scheduled_at(session: Session):
    """The service (not just the HTTP controller) enforces future-only times.

    A caller bypassing the controller must not be able to insert a past-time
    schedule that the due-runner would publish immediately on the next tick.
    """
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()

    # In the past relative to the injected ``now`` ...
    with pytest.raises(scheduler.ScheduleError, match="must be in the future"):
        scheduler.schedule_publish(
            session,
            user_id=user.id,
            job_id=job.id,
            platforms=["tiktok"],
            scheduled_at=_dt(-60),
            now=_dt(0),
        )
    # ... and exactly equal to ``now`` is rejected too (strictly future).
    with pytest.raises(scheduler.ScheduleError, match="must be in the future"):
        scheduler.schedule_publish(
            session,
            user_id=user.id,
            job_id=job.id,
            platforms=["tiktok"],
            scheduled_at=_dt(0),
            now=_dt(0),
        )


# --------------------------------------------------------------------------- #
# list_scheduled / cancel_scheduled wrappers
# --------------------------------------------------------------------------- #
def test_list_scheduled_filters_by_status(session: Session):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()

    scheduler.schedule_publish(
        session, user_id=user.id, job_id=job.id,
        platforms=["tiktok"], scheduled_at=_dt(10), now=_dt(0),
    )
    scheduler.schedule_publish(
        session, user_id=user.id, job_id=job.id,
        platforms=["instagram"], scheduled_at=_dt(20), now=_dt(0),
    )
    session.commit()

    assert len(scheduler.list_scheduled(session, user.id)) == 2
    assert len(scheduler.list_scheduled(session, user.id, status="pending")) == 2
    assert scheduler.list_scheduled(session, user.id, status="published") == []


def test_cancel_scheduled_only_pending(session: Session):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    row = scheduler.schedule_publish(
        session, user_id=user.id, job_id=job.id,
        platforms=["tiktok"], scheduled_at=_dt(10), now=_dt(0),
    )
    session.commit()

    # Owner cancels a pending schedule.
    assert scheduler.cancel_scheduled(session, row.id, user.id) is True
    assert scheduler.list_scheduled(session, user.id)[0].status == "canceled"
    # A second cancel is a no-op False (no longer pending).
    assert scheduler.cancel_scheduled(session, row.id, user.id) is False


# --------------------------------------------------------------------------- #
# process_due_publishes — the due-runner
# --------------------------------------------------------------------------- #
# Scheduled publishes go through the owner-scoped native connectors (the same
# path as "Publish now"), never a shared operator account.
_NATIVE_PUBLISH = "app.domains.publishing.native_service.publish_scheduled_reel_native"


@pytest.fixture(autouse=True)
def _grant_pro_entitlement(monkeypatch):
    """Grant RevenueCat Pro so these tests exercise the scheduler loop. The
    execution-time entitlement re-check has its own test below."""
    from app.services.billing import revenuecat_client

    monkeypatch.setattr(
        revenuecat_client, "require_pro_entitlement", lambda *a, **k: None
    )


def _seed_schedule(
    factory, user_id: str, job_id: str, *, when: datetime, platforms=None
) -> str:
    with factory() as sess:
        row = ScheduledPublishRepository(sess).create(
            user_id=user_id,
            job_id=job_id,
            platforms=platforms or ["tiktok"],
            scheduled_at=when,
        )
        return row.id


def test_process_due_publishes_publishes_due_ones(
    session: Session, factory, monkeypatch
):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()

    due_id = _seed_schedule(factory, user.id, job.id, when=_dt(-60))
    future_id = _seed_schedule(factory, user.id, job.id, when=_dt(3600))

    calls: list[str] = []

    def _fake_publish(user_id, job_id, platforms, youtube_privacy_status=None):
        calls.append(job_id)
        return {"success": True, "request_id": "req-1", "platforms": platforms}

    monkeypatch.setattr(
        _NATIVE_PUBLISH, _fake_publish
    )

    summary = scheduler.process_due_publishes(
        now=_dt(0), session_factory=factory
    )

    assert summary == {"claimed": 1, "published": 1, "failed": 0}
    assert calls == [job.id]  # only the due schedule was published

    with factory() as sess:
        repo = ScheduledPublishRepository(sess)
        due = sess.get(ScheduledPublish, due_id)
        future = sess.get(ScheduledPublish, future_id)
        assert due.status == "published"
        assert due.result["request_id"] == "req-1"
        assert future.status == "pending"  # not yet due, untouched
        assert repo.get_owned(due_id, user.id).error == ""


def test_process_due_marks_failed_without_raising(
    session: Session, factory, monkeypatch
):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    due_id = _seed_schedule(factory, user.id, job.id, when=_dt(-30))

    def _boom(user_id, job_id, platforms, youtube_privacy_status=None):
        raise RuntimeError("upload-post exploded")

    monkeypatch.setattr(_NATIVE_PUBLISH, _boom)

    # Must NOT raise out of the loop.
    summary = scheduler.process_due_publishes(now=_dt(0), session_factory=factory)

    assert summary == {"claimed": 1, "published": 0, "failed": 1}
    with factory() as sess:
        row = sess.get(ScheduledPublish, due_id)
        assert row.status == "failed"
        assert row.attempts == 1
        assert "exploded" in row.error


def test_process_due_sanitizes_secret_in_failure_error(
    session: Session, factory, monkeypatch
):
    """A secret leaked in an SDK exception must not reach the stored row.error.

    ``row.error`` is served back to the owner via GET /me/scheduled, so any
    token-looking fragment embedded in the exception text is redacted before it
    is persisted.
    """
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    due_id = _seed_schedule(factory, user.id, job.id, when=_dt(-30))

    leaked = "ya29AbCdEf1234567890ABCDEFghijkl0987654321XYZ"

    def _boom(user_id, job_id, platforms, youtube_privacy_status=None):
        raise RuntimeError(f"HTTP 401 Unauthorized: Bearer {leaked}")

    monkeypatch.setattr(_NATIVE_PUBLISH, _boom)

    summary = scheduler.process_due_publishes(now=_dt(0), session_factory=factory)
    assert summary == {"claimed": 1, "published": 0, "failed": 1}

    with factory() as sess:
        row = sess.get(ScheduledPublish, due_id)
        assert row.status == "failed"
        # The secret is gone; a placeholder marks where it was.
        assert leaked not in row.error
        assert "[redacted]" in row.error


def test_process_due_is_idempotent_second_run_claims_nothing(
    session: Session, factory, monkeypatch
):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    _seed_schedule(factory, user.id, job.id, when=_dt(-10))

    monkeypatch.setattr(
        _NATIVE_PUBLISH,
        lambda *a, **k: {"success": True, "request_id": "r"},
    )

    first = scheduler.process_due_publishes(now=_dt(0), session_factory=factory)
    second = scheduler.process_due_publishes(now=_dt(0), session_factory=factory)

    assert first == {"claimed": 1, "published": 1, "failed": 0}
    # Already published -> no longer pending/due -> nothing to claim.
    assert second == {"claimed": 0, "published": 0, "failed": 0}


def test_process_due_skips_canceled(
    session: Session, factory, monkeypatch
):
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    sid = _seed_schedule(factory, user.id, job.id, when=_dt(-10))
    with factory() as sess:
        ScheduledPublishRepository(sess).cancel(sid, user.id)

    called = []
    monkeypatch.setattr(
        _NATIVE_PUBLISH,
        lambda *a, **k: called.append(1) or {"success": True},
    )

    summary = scheduler.process_due_publishes(now=_dt(0), session_factory=factory)
    assert summary == {"claimed": 0, "published": 0, "failed": 0}
    assert called == []


def test_process_due_empty_is_safe(factory, monkeypatch):
    monkeypatch.setattr(
        _NATIVE_PUBLISH,
        lambda *a, **k: {"success": True},
    )
    summary = scheduler.process_due_publishes(now=_dt(0), session_factory=factory)
    assert summary == {"claimed": 0, "published": 0, "failed": 0}


def test_process_due_uses_real_utc_now_when_none(
    session: Session, factory, monkeypatch
):
    """When ``now`` is omitted the runner falls back to real UTC time.

    A schedule set far in the past is due against the wall clock and publishes.
    """
    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    _seed_schedule(factory, user.id, job.id, when=past)

    monkeypatch.setattr(
        _NATIVE_PUBLISH,
        lambda *a, **k: {"success": True, "request_id": "r"},
    )
    summary = scheduler.process_due_publishes(session_factory=factory)
    assert summary["claimed"] == 1
    assert summary["published"] == 1


def test_process_due_fails_closed_when_pro_lapsed(
    session: Session, factory, monkeypatch
):
    """Entitlement is re-checked at execution time; a lapsed Pro plan marks the
    schedule failed instead of publishing."""
    from app.services.billing import revenuecat_client

    user = _make_user(session)
    job = _make_job(session, user.id, state=const.TASK_STATE_COMPLETE)
    session.commit()
    due_id = _seed_schedule(factory, user.id, job.id, when=_dt(-30))

    def _deny(*_a, **_k):
        raise revenuecat_client.RevenueCatAccessDenied("Pro required")

    monkeypatch.setattr(revenuecat_client, "require_pro_entitlement", _deny)
    published: list[str] = []
    monkeypatch.setattr(
        _NATIVE_PUBLISH, lambda *a, **k: published.append("x") or {"results": []}
    )

    summary = scheduler.process_due_publishes(now=_dt(0), session_factory=factory)

    assert summary == {"claimed": 1, "published": 0, "failed": 1}
    assert published == []
    with factory() as sess:
        assert sess.get(ScheduledPublish, due_id).status == "failed"
