"""Activation funnel: pure report, server-side step recording, weekly email.

Real SQLite DB with the real ORM models; only SMTP is faked.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.db.base as db_base
from app.models.const import TASK_STATE_COMPLETE, TASK_STATE_PROCESSING
from app.models.db.base import Base
from app.models.db.funnel import FunnelEvent, FunnelReport
from app.models.db.models import CreditLedger, Job, User
from app.services import mailer
from app.services.funnel import report, store, weekly

MONDAY_0800 = datetime(2026, 9, 28, 8, 0, tzinfo=timezone.utc)


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
    return factory


def _seed(factory) -> None:
    at = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    with factory() as s:
        for i in range(4):
            s.add(User(id=f"u{i}", email=f"u{i}@example.com", created_at=at))
        s.flush()
        # u0 passed the card check ($1 = 1 credit) and later bought a pack.
        s.add(CreditLedger(user_id="u0", delta=1, reason="purchase:creem:ch_1", balance_after=1, created_at=at))
        s.add(CreditLedger(user_id="u0", delta=3, reason="signup", balance_after=4, created_at=at))
        s.add(CreditLedger(user_id="u0", delta=20, reason="purchase:creem:ch_2", balance_after=24, created_at=at))
        # u1 only passed the card check.
        s.add(CreditLedger(user_id="u1", delta=1, reason="purchase:creem:ch_3", balance_after=1, created_at=at))
        # u2 is a mobile device signup: free reels, no card check.
        s.add(CreditLedger(user_id="u2", delta=3, reason="mobile_device_signup", balance_after=3, created_at=at))
        # u3 bought a pack that was refunded: neither a card check nor paid.
        s.add(CreditLedger(user_id="u3", delta=30, reason="purchase:dodo:pay_x", balance_after=30, created_at=at))
        s.add(CreditLedger(user_id="u3", delta=-30, reason="refund:dodo:pay_x", balance_after=0, created_at=at))
        # u0 has a finished reel; u1 only a job still rendering.
        s.add(Job(id="j0", user_id="u0", state=TASK_STATE_COMPLETE, updated_at=at))
        s.add(Job(id="j1", user_id="u1", state=TASK_STATE_PROCESSING, updated_at=at))
        s.commit()


def test_report_math_and_drop_off():
    rep = report.build_report({"signup": 10, "card_check": 4, "first_link": 4, "first_reel": 1}, {"signup": 2})
    assert [r.key for r in rep.rows] == [k for k, _ in report.STEPS]
    assert rep.rows[1].from_previous == pytest.approx(0.4)
    assert rep.drop_off is not None
    assert rep.drop_off.to_label == "Pack or plan bought"
    assert rep.drop_off.lost == 1
    assert report.format_percent(None) == "-"
    assert report.format_percent(0.034) == "3.4%"
    assert "1 new signup" not in report.subject(rep)
    assert report.subject(rep).startswith("Menivor funnel: 2 new signups this week")


def test_report_never_invents_numbers():
    rep = report.build_report({"signup": -3, "card_check": "x"}, {})  # type: ignore[dict-item]
    assert all(r.total == 0 and r.from_previous is None for r in rep.rows)
    assert rep.drop_off is None


def test_schedule_is_monday_0700_utc():
    assert report.is_report_due(datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc))
    assert not report.is_report_due(datetime(2026, 9, 28, 6, 59, tzinfo=timezone.utc))
    assert not report.is_report_due(datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc))
    assert report.week_start_utc(datetime(2026, 10, 1, 12, tzinfo=timezone.utc)).date().isoformat() == "2026-09-28"


def test_sync_derives_first_steps_idempotently(db):
    _seed(db)
    first = store.sync_events()
    assert first["failed_steps"] == []
    again = store.sync_events()
    assert again["inserted"] == 0
    with db() as s:
        rows = {(e.user_id, e.step) for e in s.execute(select(FunnelEvent)).scalars()}
    assert {("u0", "signup"), ("u3", "signup")} <= rows
    assert ("u0", "card_check") in rows and ("u1", "card_check") in rows
    assert ("u2", "card_check") not in rows  # mobile free grant is not a card check
    assert ("u3", "card_check") not in rows and ("u3", "paid") not in rows  # refunded
    assert ("u0", "first_reel") in rows and ("u1", "first_reel") not in rows
    # The $1 card check alone is not "paid"; the 20-credit pack is.
    assert ("u0", "paid") in rows and ("u1", "paid") not in rows


def test_record_step_is_first_time_only(db):
    _seed(db)
    assert store.record_step("u2", "first_link") is True
    assert store.record_step("u2", "first_link") is False
    assert store.record_step("u2", "not_a_step") is False
    assert store.record_step(None, "first_link") is False


def test_weekly_sends_once_per_week_with_real_counts(db, monkeypatch):
    _seed(db)
    store.record_step("u0", "first_link", at=MONDAY_0800 - timedelta(days=1))
    sent: list[dict] = []
    monkeypatch.setattr(mailer, "send_email", lambda **kw: sent.append(kw) or True)

    assert weekly.run(now=MONDAY_0800 - timedelta(days=1))["status"] == "synced"
    assert weekly.run(now=MONDAY_0800)["status"] == "sent"
    assert weekly.run(now=MONDAY_0800 + timedelta(hours=1))["status"] == "already_sent"
    assert len(sent) == 1
    mail = sent[0]
    assert mail["to"] == "subasiarhan3@gmail.com"
    assert "Signed up | 4 | 4 | -" in mail["text"]
    assert "Card check passed | 2 | 2 | 50%" in mail["text"]
    assert "Biggest drop-off" in mail["text"]
    with db() as s:
        assert s.get(FunnelReport, "2026-09-28") is not None


def test_failed_send_releases_the_week_for_a_retry(db, monkeypatch):
    _seed(db)
    monkeypatch.setattr(mailer, "send_email", lambda **kw: False)
    assert weekly.run(now=MONDAY_0800)["status"] == "send_failed"
    monkeypatch.setattr(mailer, "send_email", lambda **kw: True)
    assert weekly.run(now=MONDAY_0800 + timedelta(hours=1))["status"] == "sent"


def test_recipient_override(monkeypatch):
    monkeypatch.setenv("MENIVOR_FUNNEL_REPORT_TO", "ops@example.com")
    assert weekly.recipient() == "ops@example.com"
    monkeypatch.setenv("MENIVOR_FUNNEL_REPORT_TO", "nope")
    assert weekly.recipient() == "subasiarhan3@gmail.com"


def test_mailer_skips_without_config(monkeypatch):
    for name in ("SMTP_HOST", "SMTP_FROM", "EMAIL_FROM", "MENIVOR_SMTP_HOST", "MENIVOR_SMTP_FROM", "MENIVOR_EMAIL_FROM"):
        monkeypatch.delenv(name, raising=False)
    assert mailer.configured() is False
    assert mailer.send_email(to="a@example.com", subject="s", text="t") is False


def test_mailer_falls_back_to_email_from(monkeypatch):
    for name in ("SMTP_FROM", "MENIVOR_SMTP_FROM", "SMTP_SENDER_NAME", "MENIVOR_SMTP_SENDER_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "Menivor Team <hello@menivor.com>")
    assert mailer.configured() is True
    msg = mailer.build_message("a@example.com", "s", "t")
    assert msg["From"] == "Menivor Team <hello@menivor.com>"


def test_mailer_builds_a_safe_message(monkeypatch):
    monkeypatch.setenv("SMTP_FROM", "noreply@menivor.com")
    msg = mailer.build_message("a@example.com", "Hi\r\nBcc: x@y.z", "text", "<p>html</p>")
    assert msg["Subject"] == "Hi  Bcc: x@y.z"
    assert "noreply@menivor.com" in msg["From"]
    assert msg.is_multipart()


def test_record_step_uses_the_given_session_factory(db, monkeypatch):
    _seed(db)

    def _boom():
        raise AssertionError("default session must not be used")

    monkeypatch.setattr(db_base, "get_session", _boom)

    @contextmanager
    def _factory():
        s = db()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    assert store.record_step("u3", "first_link", session_factory=_factory) is True
