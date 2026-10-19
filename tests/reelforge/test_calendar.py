"""Unit tests for the Publishing Calendar (app/services/calendar.py) plus the
owner-scoped ``ScheduledPublishRepository`` additions it depends on
(``list_in_range`` / ``reschedule`` / ``get_for_user``).

Runs entirely against an in-memory SQLite engine — no Postgres/Neon required and
no network I/O. Covers:

* ``list_in_range`` returns ONLY the caller's rows inside the window (never
  another user's, never an out-of-range row), soonest-first.
* ``reschedule`` moves a still-pending row's ``scheduled_at`` and returns it.
* ``reschedule`` of a non-pending / published / foreign / missing row returns
  ``None`` and leaves the row unchanged.
* ``get_for_user`` is strictly owner-scoped.
* ``calendar_view`` yields the safe DTO (no ``user_id`` / ``error`` / ``result``)
  and clamps an over-wide window; ``reschedule_publish`` enforces ownership +
  pending-only; both reject an inverted range.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import const
from app.models.db.base import Base
from app.models.db.models import Job, ScheduledPublish, User
from app.models.db.repositories import ScheduledPublishRepository
from app.services import calendar


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def engine():
    """A shared in-memory SQLite engine (StaticPool) with all tables created."""
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


def _make_user(session: Session, email: str) -> User:
    u = User(email=email)
    session.add(u)
    session.flush()
    return u


def _make_job(session: Session, user_id: str) -> Job:
    job = Job(
        user_id=user_id,
        kind="avatar_reel",
        state=const.TASK_STATE_COMPLETE,
        progress=100,
        stages={},
        params={},
        result_key="outputs/final.mp4",
    )
    session.add(job)
    session.flush()
    return job


def _dt(offset_seconds: int = 0) -> datetime:
    base = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=offset_seconds)


def _as_utc(value: datetime) -> datetime:
    """Normalise a DB-read datetime to aware UTC.

    SQLite (the test backend) round-trips a ``DateTime`` as a *naive* value, so a
    plain ``.astimezone(utc)`` would wrongly reinterpret it as local time. A
    stored value is always UTC here, so a naive one is simply tagged UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _seed(
    session: Session,
    user_id: str,
    job_id: str,
    *,
    when: datetime,
    platforms=None,
    status: str = "pending",
) -> ScheduledPublish:
    repo = ScheduledPublishRepository(session)
    row = repo.create(
        user_id=user_id,
        job_id=job_id,
        platforms=platforms or ["tiktok"],
        scheduled_at=when,
    )
    if status != "pending":
        row.status = status
    session.flush()
    return row


# --------------------------------------------------------------------------- #
# Repository: list_in_range
# --------------------------------------------------------------------------- #
def test_list_in_range_owner_scoped_and_bounded(session: Session):
    owner = _make_user(session, "owner@example.com")
    other = _make_user(session, "other@example.com")
    owner_job = _make_job(session, owner.id)
    other_job = _make_job(session, other.id)
    session.commit()

    # In-range for the owner (out of insertion order to prove ordering).
    b = _seed(session, owner.id, owner_job.id, when=_dt(7200))
    a = _seed(session, owner.id, owner_job.id, when=_dt(3600))
    # On the inclusive bounds.
    lo = _seed(session, owner.id, owner_job.id, when=_dt(0))
    hi = _seed(session, owner.id, owner_job.id, when=_dt(86400))
    # Out of range (before the window / after the window).
    _seed(session, owner.id, owner_job.id, when=_dt(-3600))
    _seed(session, owner.id, owner_job.id, when=_dt(90000))
    # Another user's row inside the window — must NOT leak.
    _seed(session, other.id, other_job.id, when=_dt(3600))
    session.commit()

    repo = ScheduledPublishRepository(session)
    rows = repo.list_in_range(owner.id, _dt(0), _dt(86400))

    ids = [r.id for r in rows]
    # Inclusive bounds + in-window rows only, soonest-first.
    assert ids == [lo.id, a.id, b.id, hi.id]
    # Every returned row is the owner's.
    assert all(r.user_id == owner.id for r in rows)


def test_list_in_range_status_filter(session: Session):
    owner = _make_user(session, "owner@example.com")
    job = _make_job(session, owner.id)
    session.commit()

    pending = _seed(session, owner.id, job.id, when=_dt(60))
    published = _seed(
        session, owner.id, job.id, when=_dt(120), status="published"
    )
    session.commit()

    repo = ScheduledPublishRepository(session)
    only_pending = repo.list_in_range(
        owner.id, _dt(0), _dt(3600), statuses=["pending"]
    )
    assert [r.id for r in only_pending] == [pending.id]

    both = repo.list_in_range(owner.id, _dt(0), _dt(3600))
    assert {r.id for r in both} == {pending.id, published.id}


# --------------------------------------------------------------------------- #
# Repository: reschedule + get_for_user
# --------------------------------------------------------------------------- #
def test_reschedule_moves_pending_row(session: Session):
    owner = _make_user(session, "owner@example.com")
    job = _make_job(session, owner.id)
    session.commit()
    row = _seed(session, owner.id, job.id, when=_dt(3600))
    session.commit()

    repo = ScheduledPublishRepository(session)
    moved = repo.reschedule(row.id, owner.id, _dt(7200))

    assert moved is not None
    assert moved.id == row.id
    assert _as_utc(moved.scheduled_at) == _dt(7200)
    assert moved.status == "pending"

    # Persisted, not just cached.
    session.expire_all()
    assert _as_utc(session.get(ScheduledPublish, row.id).scheduled_at) == _dt(7200)


def test_reschedule_non_pending_returns_none_unchanged(session: Session):
    owner = _make_user(session, "owner@example.com")
    job = _make_job(session, owner.id)
    session.commit()
    row = _seed(
        session, owner.id, job.id, when=_dt(3600), status="published"
    )
    session.commit()

    repo = ScheduledPublishRepository(session)
    assert repo.reschedule(row.id, owner.id, _dt(7200)) is None

    session.expire_all()
    still = session.get(ScheduledPublish, row.id)
    assert still.status == "published"
    assert _as_utc(still.scheduled_at) == _dt(3600)


def test_reschedule_foreign_returns_none_unchanged(session: Session):
    owner = _make_user(session, "owner@example.com")
    other = _make_user(session, "other@example.com")
    job = _make_job(session, owner.id)
    session.commit()
    row = _seed(session, owner.id, job.id, when=_dt(3600))
    session.commit()

    repo = ScheduledPublishRepository(session)
    # A different user's guessed id never moves the row.
    assert repo.reschedule(row.id, other.id, _dt(7200)) is None
    # A missing id is likewise a no-op None.
    assert repo.reschedule("does-not-exist", owner.id, _dt(7200)) is None

    session.expire_all()
    assert _as_utc(session.get(ScheduledPublish, row.id).scheduled_at) == _dt(3600)


def test_get_for_user_owner_scoped(session: Session):
    owner = _make_user(session, "owner@example.com")
    other = _make_user(session, "other@example.com")
    job = _make_job(session, owner.id)
    session.commit()
    row = _seed(session, owner.id, job.id, when=_dt(3600))
    session.commit()

    repo = ScheduledPublishRepository(session)
    assert repo.get_for_user(row.id, owner.id).id == row.id
    assert repo.get_for_user(row.id, other.id) is None
    assert repo.get_for_user("nope", owner.id) is None


# --------------------------------------------------------------------------- #
# Service: calendar_view
# --------------------------------------------------------------------------- #
def test_calendar_view_returns_safe_dto(session: Session):
    owner = _make_user(session, "owner@example.com")
    other = _make_user(session, "other@example.com")
    owner_job = _make_job(session, owner.id)
    other_job = _make_job(session, other.id)
    session.commit()

    row = _seed(
        session, owner.id, owner_job.id, when=_dt(3600),
        platforms=["tiktok", "instagram"],
    )
    _seed(session, other.id, other_job.id, when=_dt(3600))  # must not leak
    session.commit()

    view = calendar.calendar_view(session, owner.id, _dt(0), _dt(86400))

    assert len(view) == 1
    entry = view[0]
    # Exactly the safe fields — no user_id / error / result / attempts /
    # youtube_privacy_status.
    assert set(entry.keys()) == {
        "id",
        "job_id",
        "platforms",
        "scheduled_at",
        "status",
    }
    assert entry["id"] == row.id
    assert entry["job_id"] == owner_job.id
    assert entry["platforms"] == ["tiktok", "instagram"]
    assert entry["status"] == "pending"
    assert entry["scheduled_at"] == _dt(3600).isoformat()


def test_calendar_view_clamps_over_wide_window(session: Session):
    owner = _make_user(session, "owner@example.com")
    job = _make_job(session, owner.id)
    session.commit()

    inside = _seed(session, owner.id, job.id, when=_dt(3600))
    # Beyond the 92-day clamp measured from ``start`` — must be excluded even
    # though the *requested* end is far past it.
    beyond = _dt(0) + timedelta(days=120)
    _seed(session, owner.id, job.id, when=beyond)
    session.commit()

    requested_end = _dt(0) + timedelta(days=365)
    view = calendar.calendar_view(session, owner.id, _dt(0), requested_end)

    ids = [e["id"] for e in view]
    assert inside.id in ids
    # The row past the clamped horizon is not returned.
    assert all(e["scheduled_at"] != beyond.isoformat() for e in view)


def test_calendar_view_rejects_inverted_range(session: Session):
    owner = _make_user(session, "owner@example.com")
    session.commit()

    with pytest.raises(calendar.CalendarError, match="before end"):
        calendar.calendar_view(session, owner.id, _dt(86400), _dt(0))
    # Empty range (start == end) is rejected too.
    with pytest.raises(calendar.CalendarError, match="before end"):
        calendar.calendar_view(session, owner.id, _dt(0), _dt(0))


# --------------------------------------------------------------------------- #
# Service: reschedule_publish
# --------------------------------------------------------------------------- #
def test_reschedule_publish_moves_pending(session: Session):
    owner = _make_user(session, "owner@example.com")
    job = _make_job(session, owner.id)
    session.commit()
    row = _seed(session, owner.id, job.id, when=_dt(3600))
    session.commit()

    dto = calendar.reschedule_publish(session, owner.id, row.id, _dt(7200))

    assert dto["id"] == row.id
    assert dto["scheduled_at"] == _dt(7200).isoformat()
    assert dto["status"] == "pending"
    assert "user_id" not in dto and "error" not in dto


def test_reschedule_publish_rejects_non_pending(session: Session):
    owner = _make_user(session, "owner@example.com")
    job = _make_job(session, owner.id)
    session.commit()
    row = _seed(
        session, owner.id, job.id, when=_dt(3600), status="published"
    )
    session.commit()

    with pytest.raises(calendar.CalendarError, match="not pending"):
        calendar.reschedule_publish(session, owner.id, row.id, _dt(7200))

    session.expire_all()
    assert _as_utc(session.get(ScheduledPublish, row.id).scheduled_at) == _dt(3600)


def test_reschedule_publish_rejects_foreign(session: Session):
    owner = _make_user(session, "owner@example.com")
    other = _make_user(session, "other@example.com")
    job = _make_job(session, owner.id)
    session.commit()
    row = _seed(session, owner.id, job.id, when=_dt(3600))
    session.commit()

    with pytest.raises(PermissionError):
        calendar.reschedule_publish(session, other.id, row.id, _dt(7200))
    with pytest.raises(PermissionError):
        calendar.reschedule_publish(session, owner.id, "nope", _dt(7200))

    session.expire_all()
    assert _as_utc(session.get(ScheduledPublish, row.id).scheduled_at) == _dt(3600)
