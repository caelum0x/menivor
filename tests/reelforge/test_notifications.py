"""Unit tests for the in-app notification emit layer.

Runs against an in-memory SQLite DB built from the live ORM metadata so the
tests exercise the real :class:`NotificationRepository.create` INSERT path — no
fakes for the write itself. ``app.services.notifications.get_session`` is
monkeypatched to a context manager backed by that in-memory engine so the pure
emit layer persists into the test DB.

Covered behaviour:

* each emitter writes exactly one ``Notification`` row with the right
  ``kind``/``data`` (and optional ``result_url``),
* ``emit_for_job`` dispatches on job state (complete/failed) and no-ops for a
  still-processing job,
* the best-effort contract: a repository error is swallowed (returns ``None``,
  never raises), and an empty ``user_id`` / unavailable persistence layer is a
  logged no-op.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import const
from app.models.db.base import Base
from app.models.db.models import Notification, User
from app.services import notifications


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def session_factory() -> sessionmaker:
    """In-memory SQLite session factory sharing one connection (StaticPool)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture()
def patched(monkeypatch, session_factory: sessionmaker) -> sessionmaker:
    """Point ``notifications.get_session`` at the in-memory test DB.

    Returns the session factory so a test can open its own session to assert on
    the persisted rows.
    """

    @contextmanager
    def _get_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(notifications, "get_session", _get_session)
    return session_factory


def _make_user(session_factory: sessionmaker, credits: int = 5) -> str:
    """Insert a user (satisfies the notifications.user_id FK) and return its id."""
    with session_factory() as session:
        user = User(email=f"u{credits}@example.com", credits=credits)
        session.add(user)
        session.commit()
        return user.id


def _rows(session_factory: sessionmaker, user_id: str) -> list[Notification]:
    with session_factory() as session:
        return list(
            session.execute(
                select(Notification).where(Notification.user_id == user_id)
            )
            .scalars()
            .all()
        )


# --------------------------------------------------------------------------- #
# Emitters write the right kind / data
# --------------------------------------------------------------------------- #
def test_notify_job_complete_writes_row(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    note_id = notifications.notify_job_complete(
        user_id, "job-123", result_url="https://cdn.example/reel.mp4"
    )

    assert note_id
    rows = _rows(patched, user_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == note_id
    assert row.kind == notifications.KIND_JOB_COMPLETE
    assert row.read is False
    assert row.data["job_id"] == "job-123"
    assert row.data["result_url"] == "https://cdn.example/reel.mp4"
    assert row.title


def test_notify_job_complete_omits_absent_result_url(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    notifications.notify_job_complete(user_id, "job-xyz")

    row = _rows(patched, user_id)[0]
    assert row.data == {"job_id": "job-xyz"}
    assert "result_url" not in row.data


def test_notify_job_failed_writes_row(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    notifications.notify_job_failed(user_id, "job-9", "tts stage exploded")

    row = _rows(patched, user_id)[0]
    assert row.kind == notifications.KIND_JOB_FAILED
    assert row.data["job_id"] == "job-9"
    assert row.data["error"] == "tts stage exploded"


def test_notify_job_failed_defaults_blank_error(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    notifications.notify_job_failed(user_id, "job-9", "   ")

    row = _rows(patched, user_id)[0]
    assert row.data["error"] == "unknown error"


def test_notify_low_credits_writes_row(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    notifications.notify_low_credits(user_id, balance=2)

    row = _rows(patched, user_id)[0]
    assert row.kind == notifications.KIND_LOW_CREDITS
    assert row.data["balance"] == 2
    assert row.data["threshold"] == notifications.DEFAULT_LOW_CREDITS_THRESHOLD


def test_notify_low_credits_custom_threshold(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    notifications.notify_low_credits(user_id, balance=0, threshold=10)

    row = _rows(patched, user_id)[0]
    assert row.data == {"balance": 0, "threshold": 10}


def test_notify_referral_earned_writes_row(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    notifications.notify_referral_earned(user_id, credits=10)

    row = _rows(patched, user_id)[0]
    assert row.kind == notifications.KIND_REFERRAL_EARNED
    assert row.data["credits"] == 10


# --------------------------------------------------------------------------- #
# emit_for_job dispatch
# --------------------------------------------------------------------------- #
class _FakeJob:
    """Duck-typed stand-in for an ORM Job row."""

    def __init__(self, id: str, state: int, error: str = "") -> None:
        self.id = id
        self.state = state
        self.error = error


def test_emit_for_job_complete(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    notifications.emit_for_job(
        user_id, _FakeJob("job-c", const.TASK_STATE_COMPLETE)
    )

    row = _rows(patched, user_id)[0]
    assert row.kind == notifications.KIND_JOB_COMPLETE
    assert row.data["job_id"] == "job-c"


def test_emit_for_job_failed(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    notifications.emit_for_job(
        user_id, _FakeJob("job-f", const.TASK_STATE_FAILED, error="boom")
    )

    row = _rows(patched, user_id)[0]
    assert row.kind == notifications.KIND_JOB_FAILED
    assert row.data == {"job_id": "job-f", "error": "boom"}


def test_emit_for_job_processing_is_noop(patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    result = notifications.emit_for_job(
        user_id, _FakeJob("job-p", const.TASK_STATE_PROCESSING)
    )

    assert result is None
    assert _rows(patched, user_id) == []


# --------------------------------------------------------------------------- #
# Best-effort contract: failures are swallowed, never raised
# --------------------------------------------------------------------------- #
def test_emit_swallows_repository_error(monkeypatch, patched: sessionmaker) -> None:
    user_id = _make_user(patched)

    class _BoomRepo:
        def __init__(self, session: Session) -> None:
            self._session = session

        def create(self, *args, **kwargs):
            raise RuntimeError("db is down")

    monkeypatch.setattr(notifications, "NotificationRepository", _BoomRepo)

    # Must NOT raise, and must report failure via None.
    assert notifications.notify_job_complete(user_id, "job-1") is None
    assert notifications.notify_job_failed(user_id, "job-1", "x") is None
    assert notifications.notify_low_credits(user_id, 1) is None
    assert notifications.notify_referral_earned(user_id, 3) is None
    # Nothing persisted.
    assert _rows(patched, user_id) == []


def test_emit_swallows_session_error(monkeypatch, patched: sessionmaker) -> None:
    def _boom_session():
        raise RuntimeError("cannot connect")

    monkeypatch.setattr(notifications, "get_session", _boom_session)

    assert notifications.notify_referral_earned("user-1", 3) is None


def test_empty_user_id_is_noop(patched: sessionmaker) -> None:
    assert notifications.notify_job_complete("", "job-1") is None


def test_missing_persistence_layer_is_noop(monkeypatch) -> None:
    monkeypatch.setattr(notifications, "get_session", None)
    monkeypatch.setattr(notifications, "NotificationRepository", None)

    assert notifications.notify_low_credits("user-1", 0) is None
