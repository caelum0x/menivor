"""MG5: money lifecycle mail (payment failed, Autopilot paused, credits low).

Real SQLite ledger, audit, consent and notifications; only SMTP is faked.
Contract: gtm/policy/ACCOUNT-LIFECYCLE.md section 4 (budget 3 a month, one per
cause, one-click unsubscribe, nothing after cancel with no balance).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.db.base as db_base
from app.events.bus import Event, EventBus
from app.models.db.base import Base
from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.models import Job, Notification, User
from app.models.db.repositories import CreditRepository
from app.models.db.series_runs import ChannelRun
from app.services import mailer
from app.services.billing import creator_subscriptions, lifecycle_mail

PERIOD_END = datetime(2026, 10, 25, tzinfo=timezone.utc)


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setenv("MENIVOR_MAIL_UNSUBSCRIBE_SECRET", "test-secret")
    monkeypatch.setenv("SMTP_FROM", "Menivor <hello@menivor.com>")
    sent: list[dict] = []

    def fake_send(*, to, subject, text, html=None, headers=None):
        sent.append({"to": to, "subject": subject, "text": text, "html": html, "headers": headers or {}})
        return True

    monkeypatch.setattr(mailer, "send_email", fake_send)
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(lifecycle_mail, "_portal_url", lambda user_id: "https://pay.example/portal/abc")
    with _session() as s:
        user = User(email="maker@example.com", display_name="Maker")
        s.add(user)
        s.flush()
        uid = user.id
    return Factory, _session, uid, sent


def _plan(Session, uid, status="active"):
    with Session() as s:
        s.add(CreatorSubscription(
            user_id=uid, plan_key="creator", interval="month", provider="dodo",
            provider_ref="sub_1", customer_ref="cus_1", status=status, current_period_end=PERIOD_END,
        ))


def _spend_to(Session, uid, grant: int, spend: int):
    with Session() as s:
        CreditRepository(s).grant(uid, grant, "purchase:dodo:pay_1")
    for _ in range(spend):
        with Session() as s:
            job = Job(user_id=uid, kind="avatar_reel")
            s.add(job)
            s.flush()
            CreditRepository(s).debit(uid, 1, job.id, "job_debit")


def _notifications(Factory, uid):
    with Factory() as s:
        return list(s.execute(select(Notification.kind).where(Notification.user_id == uid)).scalars())


# --------------------------------------------------------------------------- #
# Payment failed
# --------------------------------------------------------------------------- #
def test_failed_payment_mails_once_with_portal_and_unsubscribe(env):
    Factory, Session, uid, sent = env
    _plan(Session, uid)
    update = {"user_id": uid, "provider_ref": "sub_1", "status": "past_due", "period_end": PERIOD_END,
              "provider": "dodo", "plan_key": "creator", "interval": "month"}
    creator_subscriptions.apply_update(dict(update))
    creator_subscriptions.apply_update(dict(update))  # webhook replay
    assert lifecycle_mail.sweep() == {"payment_failed": 0, "autopilot_paused": 0, "credits_low": 0}
    assert len(sent) == 1
    mail = sent[0]
    assert mail["to"] == "maker@example.com"
    assert "https://pay.example/portal/abc" in mail["text"]
    assert "Unsubscribe: https://api.menivor.com/api/v1/mail/unsubscribe?u=" in mail["text"]
    assert mail["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "mailto:hello@menivor.com" in mail["headers"]["List-Unsubscribe"]
    assert _notifications(Factory, uid) == ["billing_payment_failed"]


def test_active_status_sends_nothing(env):
    _, Session, uid, sent = env
    assert lifecycle_mail.on_plan_status(uid, "active", "sub_1", PERIOD_END) == "ignored"
    assert sent == []


def test_next_failed_renewal_is_a_new_cause(env):
    _, Session, uid, sent = env
    later = datetime(2026, 11, 25, tzinfo=timezone.utc)
    assert lifecycle_mail.on_plan_status(uid, "past_due", "sub_1", PERIOD_END) == "sent"
    assert lifecycle_mail.on_plan_status(uid, "past_due", "sub_1", PERIOD_END) == "duplicate"
    assert lifecycle_mail.on_plan_status(uid, "past_due", "sub_1", later) == "sent"
    assert len(sent) == 2


# --------------------------------------------------------------------------- #
# Budget and priority
# --------------------------------------------------------------------------- #
def test_budget_is_three_a_month_and_credits_low_keeps_a_slot(env):
    Factory, Session, uid, sent = env
    assert lifecycle_mail.notify("autopilot_paused", uid, "ch1:a") == "sent"
    assert lifecycle_mail.notify("autopilot_paused", uid, "ch1:b") == "sent"
    assert lifecycle_mail.notify("credits_low", uid, "grant:9") == "suppressed:budget"
    assert lifecycle_mail.notify("payment_failed", uid, "sub_1:1") == "sent"
    assert lifecycle_mail.notify("payment_failed", uid, "sub_1:2") == "suppressed:budget"
    assert len(sent) == 3
    assert len(_notifications(Factory, uid)) == 5  # the in-app notice always shows
    next_month = datetime(2099, 1, 2, tzinfo=timezone.utc)
    with Factory() as s:
        assert lifecycle_mail.sent_this_month(s, uid, next_month) == 0


# --------------------------------------------------------------------------- #
# Unsubscribe
# --------------------------------------------------------------------------- #
def _client():
    from app.controllers.v1 import lifecycle_mail as controller

    app = FastAPI()
    app.include_router(controller.router)
    return TestClient(app)


def test_one_click_unsubscribe_stops_lifecycle_mail_only(env):
    Factory, Session, uid, sent = env
    client = _client()
    token = lifecycle_mail.unsubscribe_token(uid)
    assert client.post(f"/api/v1/mail/unsubscribe?u={uid}&t=wrong").status_code == 400
    page = client.get(f"/api/v1/mail/unsubscribe?u={uid}&t={token}")
    assert page.status_code == 200 and 'method="post"' in page.text
    with Factory() as s:
        assert not lifecycle_mail.opted_out(s, uid)  # GET alone never unsubscribes
    resp = client.post(f"/api/v1/mail/unsubscribe?u={uid}&t={token}", data={"List-Unsubscribe": "One-Click"})
    assert resp.status_code == 200 and "Unsubscribed" in resp.text
    assert client.post(f"/api/v1/mail/unsubscribe?u={uid}&t={token}").status_code == 200  # idempotent
    assert lifecycle_mail.notify("payment_failed", uid, "sub_1:1") == "suppressed:unsubscribed"
    assert sent == []
    assert _notifications(Factory, uid) == ["billing_payment_failed"]


def test_no_signing_secret_means_in_app_only(env, monkeypatch):
    _, _, uid, sent = env
    monkeypatch.delenv("MENIVOR_MAIL_UNSUBSCRIBE_SECRET")
    monkeypatch.setattr(lifecycle_mail, "_secret", lambda: "")
    assert lifecycle_mail.notify("payment_failed", uid, "sub_1:1") == "suppressed:no_unsubscribe_secret"
    assert sent == []


# --------------------------------------------------------------------------- #
# Autopilot paused (MN1 channel_paused signal) + sweep agree on the cause
# --------------------------------------------------------------------------- #
def test_channel_paused_signal_mails_once_and_sweep_does_not_repeat(env):
    Factory, Session, uid, sent = env
    with Session() as s:
        s.add(ChannelRun(user_id=uid, channel_id="chan1", params={
            "kind": "channel", "name": "Daily facts", "active": True, "autorun": True,
            "paused_reason": "credits", "paused_at": "2026-10-10T12:00:00+00:00",
        }))
    from app.domains.series import channels

    with Factory() as s:
        assert channels.get_definition(s, "chan1") is not None
    bus = EventBus()
    assert lifecycle_mail.install(bus) is True
    assert lifecycle_mail.install(bus) is False
    bus.emit(Event(type="channel_paused", key="chan1", payload={"user_id": uid, "run_id": "r1"}))
    assert len(sent) == 1 and "Daily facts" in sent[0]["text"]
    assert lifecycle_mail.sweep()["autopilot_paused"] == 0
    assert len(sent) == 1


# --------------------------------------------------------------------------- #
# Credits low
# --------------------------------------------------------------------------- #
def test_credits_low_mails_once_per_top_up(env):
    Factory, Session, uid, sent = env
    _spend_to(Session, uid, grant=3, spend=2)  # balance 1
    assert lifecycle_mail.sweep()["credits_low"] == 1
    assert lifecycle_mail.sweep()["credits_low"] == 0
    assert "1 credit left" in sent[0]["text"]
    _spend_to(Session, uid, grant=1, spend=1)  # new top-up cycle, balance 1 again
    assert lifecycle_mail.sweep()["credits_low"] == 1


def test_healthy_balance_sends_nothing(env):
    _, Session, uid, sent = env
    _spend_to(Session, uid, grant=10, spend=2)
    assert lifecycle_mail.sweep()["credits_low"] == 0
    assert lifecycle_mail.on_balance(uid, 8) == "ignored"
    assert sent == []


def test_cancelled_with_no_balance_gets_no_nudges(env):
    _, Session, uid, sent = env
    _plan(Session, uid, status="canceled")
    _spend_to(Session, uid, grant=1, spend=1)
    assert lifecycle_mail.on_balance(uid, 0) == "suppressed:cancelled_no_balance"
    assert sent == []


def test_deleted_account_gets_nothing(env):
    Factory, Session, uid, sent = env
    with Session() as s:
        s.get(User, uid).email = f"deleted+{uid}@invalid.menivor"
    assert lifecycle_mail.notify("payment_failed", uid, "sub_1:1") == "suppressed:no_address"
    assert sent == []
