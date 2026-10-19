"""Tests for consent capture + lookup (Compliance, Epic 5).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered:

* :func:`consent.record_consent` appends an immutable decision and audits it;
* :func:`consent.get_consent` returns the CURRENT (newest) decision per kind;
* the trail is append-only (history preserved) and strictly owner-scoped;
* blank user id / kind are rejected.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import AuditLog, User
from app.services.compliance import consent


@pytest.fixture()
def session_factory():
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


@contextmanager
def _session(factory):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _make_user(session, email: str) -> str:
    user = User(email=email, credits=0)
    session.add(user)
    session.flush()
    return user.id


def test_record_and_get_consent(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        rec = consent.record_consent(s, a, "tos", True, version="2026-08")
        assert rec.granted is True
        assert rec.kind == "tos"

        current = consent.get_consent(s, a, "tos")
        assert current is not None
        assert current.id == rec.id
        assert current.granted is True
        assert current.version == "2026-08"


def test_latest_consent_wins_and_history_preserved(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        consent.record_consent(s, a, "marketing", True, version="1")
        consent.record_consent(s, a, "marketing", False, version="2")

        current = consent.get_consent(s, a, "marketing")
        assert current.granted is False
        assert current.version == "2"

        # Append-only: both rows preserved as a trail.
        trail = consent.list_consents(s, a)
        assert len(trail) == 2
        assert [c.version for c in trail] == ["1", "2"]


def test_consent_is_owner_scoped(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        b = _make_user(s, "bob@example.com")
        consent.record_consent(s, a, "tos", True)

        # Bob has no consent for tos and never sees Alice's.
        assert consent.get_consent(s, b, "tos") is None
        assert consent.list_consents(s, b) == []


def test_record_consent_is_audited(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        consent.record_consent(s, a, "ai_disclosure", True, version="v1")

        rows = list(
            s.execute(
                select(AuditLog).where(
                    AuditLog.action == "compliance.consent_recorded"
                )
            ).scalars().all()
        )
        assert len(rows) == 1
        assert rows[0].actor_user_id == a
        assert rows[0].meta.get("kind") == "ai_disclosure"


def test_record_consent_validates_input(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        with pytest.raises(ValueError):
            consent.record_consent(s, "", "tos", True)
        with pytest.raises(ValueError):
            consent.record_consent(s, a, "   ", True)
