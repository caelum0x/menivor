"""Internal accounts (smoke tests, Megaphone renders, QA) never count in the funnel."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.domains.funnel_readout.models  # noqa: F401 - registers funnel_attribution
import app.models.db.base as db_base
from app.models.const import TASK_STATE_COMPLETE
from app.models.db.base import Base
from app.models.db.models import CreditLedger, Job, User
from app.services.funnel import internal, store

AT = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.delenv("MENIVOR_INTERNAL_EMAIL_DOMAINS", raising=False)
    monkeypatch.delenv("MENIVOR_INTERNAL_EMAILS", raising=False)
    with factory() as s:
        s.add(User(id="real", email="founder@example.com", created_at=AT))
        s.add(User(id="smoke", email="smoke-internal@menivor.com", created_at=AT))
        s.flush()
        for uid in ("real", "smoke"):
            s.add(CreditLedger(user_id=uid, delta=3, reason="signup", balance_after=3, created_at=AT))
            s.add(Job(id=f"j-{uid}", user_id=uid, state=TASK_STATE_COMPLETE, updated_at=AT))
        s.commit()
    return factory


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("smoke-internal@menivor.com", True),
        ("QA@Ereboslab.com", True),
        ("someone@example.com", False),
        ("", False),
        ("not-an-email", False),
    ],
)
def test_is_internal_email_defaults(monkeypatch, email, expected):
    monkeypatch.delenv("MENIVOR_INTERNAL_EMAIL_DOMAINS", raising=False)
    monkeypatch.delenv("MENIVOR_INTERNAL_EMAILS", raising=False)
    assert internal.is_internal_email(email) is expected


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("MENIVOR_INTERNAL_EMAIL_DOMAINS", "corp.test")
    monkeypatch.setenv("MENIVOR_INTERNAL_EMAILS", "me@gmail.com")
    assert internal.is_internal_email("a@corp.test")
    assert internal.is_internal_email("ME@gmail.com")
    assert not internal.is_internal_email("smoke-internal@menivor.com")


def test_sync_and_counts_skip_internal_users(db):
    store.sync_events()
    totals, _ = store.load_counts(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert totals["signup"] == 1
    assert totals["card_check"] == 1
    assert totals["first_reel"] == 1


def test_record_step_ignores_internal_user(db):
    assert store.record_step("smoke", "first_link") is False
    assert store.record_step("real", "first_link") is True


def test_readout_skips_internal_users(db):
    from app.domains.funnel_readout.service import readout

    with db() as s:
        rows = readout(s, since=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert [r.user_id for r in rows] == ["real"]
