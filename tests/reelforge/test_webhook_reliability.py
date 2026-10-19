"""MN8 webhook reliability.

* Failed deliveries are retried with backoff by a beat tick, then marked dead
  and never retried again.
* A failed job emits ``job.failed`` carrying its real ``refunded`` state (read
  from the ledgers), once per failure cycle.
* A user with no workspace can subscribe (service and ``POST /me/webhooks``).
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.webhooks_admin as webhooks_mod
from app.models import const
from app.models.db.base import Base
from app.models.db.models import (
    CreditLedger,
    Job,
    User,
    WebhookDelivery,
    Workspace,
    WorkspaceMember,
)
from app.models.exception import HttpException
from app.services import webhook_job_events, webhook_subscriptions, webhooks
from app.utils import utils

_PUBLIC_URL = "https://93.184.216.34/hook"


@pytest.fixture(autouse=True)
def _token_key(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "test-webhook-signing-key")


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _deliveries(monkeypatch, *, delivered: bool = True):
    calls: list[dict] = []

    def _fake(url, payload, secret=None, timeout_s=10.0):  # noqa: ANN001
        calls.append({"url": url, "payload": payload})
        return {"delivered": delivered, "status": 200 if delivered else 500}

    monkeypatch.setattr(webhooks, "deliver_webhook", _fake)
    return calls


def _user(s, email: str) -> str:
    u = User(email=email, credits=0)
    s.add(u)
    s.flush()
    return u.id


def _owned_workspace(s, owner: str) -> str:
    ws = Workspace(owner_id=owner, name="Team")
    s.add(ws)
    s.flush()
    s.add(WorkspaceMember(workspace_id=ws.id, user_id=owner, role="owner"))
    s.flush()
    return ws.id


def _failed_job(s, owner: str, *, age_s: int = 120, params: dict | None = None) -> str:
    stamp = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=age_s)
    job = Job(
        user_id=owner,
        kind="avatar_reel",
        state=const.TASK_STATE_FAILED,
        failed_stage="compose",
        error="Render failed",
        params=params or {},
        updated_at=stamp,
    )
    s.add(job)
    s.flush()
    return job.id


def _ledger(s, owner: str, job_id: str, delta: int, reason: str) -> None:
    s.add(CreditLedger(user_id=owner, job_id=job_id, delta=delta, reason=reason, balance_after=0))
    s.flush()


# --------------------------------------------------------------------------- #
# Retry, backoff, dead
# --------------------------------------------------------------------------- #
def test_failed_delivery_is_retried_then_dead_and_never_retried_again(factory, monkeypatch):
    calls = _deliveries(monkeypatch, delivered=False)
    with factory() as s:
        owner = _user(s, "a@example.com")
        ws = _owned_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.completed"])
        (delivery,) = webhook_subscriptions.dispatch(s, ws, "job.completed", {}, event_id="e1")
        assert delivery.status == webhook_subscriptions.DELIVERY_PENDING

        # Not due yet: the backoff holds the retry back.
        webhook_subscriptions.retry_pending(s, now=datetime.now(timezone.utc))
        assert len(calls) == 1

        now = datetime.now(timezone.utc)
        for i in range(1, webhook_subscriptions.MAX_DELIVERY_ATTEMPTS + 3):
            webhook_subscriptions.retry_pending(
                s, now=now + timedelta(seconds=webhook_subscriptions.RETRY_MAX_SECONDS * i)
            )
        s.refresh(delivery)
        assert delivery.status == webhook_subscriptions.DELIVERY_DEAD
        assert delivery.attempts == webhook_subscriptions.MAX_DELIVERY_ATTEMPTS
        assert len(calls) == webhook_subscriptions.MAX_DELIVERY_ATTEMPTS

        # Dead is terminal.
        webhook_subscriptions.retry_pending(s, now=now + timedelta(days=30))
        assert len(calls) == webhook_subscriptions.MAX_DELIVERY_ATTEMPTS


def test_retry_tick_is_on_the_beat_schedule_and_housekeeping_queue():
    # The worker imports celery_app first (``celery -A app.workers.celery_app``).
    from app.workers.celery_app import HOUSEKEEPING_QUEUE, celery_app
    from app.workers import tasks_webhooks

    beat = celery_app.conf.beat_schedule
    for name in tasks_webhooks.BEAT_SCHEDULE:
        assert name in beat
        assert beat[name]["options"]["queue"] == HOUSEKEEPING_QUEUE
    assert beat["menivor-webhook-retry"]["task"] == tasks_webhooks.RETRY_TASK


def test_retry_tick_uses_own_session(factory, monkeypatch):
    from app.workers import tasks_webhooks

    _deliveries(monkeypatch, delivered=True)

    @contextmanager
    def _gs():
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr("app.models.db.base.get_session", _gs)
    with factory() as s:
        owner = _user(s, "a@example.com")
        ws = _owned_workspace(s, owner)
        sub, _ = webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.completed"])
        s.add(WebhookDelivery(subscription_id=sub.id, event_type="job.completed", event_id="x", payload={}))
        s.commit()
    assert tasks_webhooks.retry_webhook_deliveries_task() == {"attempted": 1, "delivered": 1}
    monkeypatch.setenv("MENIVOR_WEBHOOK_TICKS", "0")
    assert tasks_webhooks.retry_deliveries() == {"attempted": 0}


# --------------------------------------------------------------------------- #
# job.failed with refunded
# --------------------------------------------------------------------------- #
def test_failed_refunded_job_emits_job_failed_with_refunded_true(factory, monkeypatch):
    calls = _deliveries(monkeypatch)
    with factory() as s:
        owner = _user(s, "a@example.com")
        ws = _owned_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.failed"])
        job_id = _failed_job(s, owner)
        _ledger(s, owner, job_id, -3, "reel")
        _ledger(s, owner, job_id, 3, "failure_refund")
        s.commit()

        assert webhook_job_events.emit_failed_jobs(s) == 1
        assert len(calls) == 1
        body = calls[0]["payload"]
        assert body["event_type"] == "job.failed"
        assert body["job_id"] == job_id
        assert body["refunded"] is True
        assert body["charged"] is True
        assert body["credits_refunded"] == 3
        assert body["event_id"] == f"job.failed:{job_id}:1"

        # A second sweep never re-sends the same failure.
        webhook_job_events.emit_failed_jobs(s)
        assert len(calls) == 1


def test_unrefunded_and_uncharged_jobs_report_honestly(factory, monkeypatch):
    calls = _deliveries(monkeypatch)
    with factory() as s:
        owner = _user(s, "a@example.com")
        ws = _owned_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.failed"])
        held = _failed_job(s, owner)
        _ledger(s, owner, held, -2, "reel")
        free = _failed_job(s, owner)
        s.commit()
        webhook_job_events.emit_failed_jobs(s)

    by_job = {c["payload"]["job_id"]: c["payload"] for c in calls}
    assert by_job[held]["charged"] is True and by_job[held]["refunded"] is False
    assert by_job[free]["charged"] is False and by_job[free]["refunded"] is False


def test_partial_credit_return_is_not_reported_as_refunded(factory, monkeypatch):
    """Verifier fix: 3 of 10 credits back is not ``refunded: true``."""
    with factory() as s:
        owner = _user(s, "a@example.com")
        job_id = _failed_job(s, owner)
        _ledger(s, owner, job_id, -10, "reel")
        _ledger(s, owner, job_id, 3, "failure_refund")
        s.commit()
        state = webhook_job_events.refund_state(s, s.get(Job, job_id))
    assert state["charged"] is True and state["refunded"] is False
    assert state["credits_refunded"] == 3


def test_retried_paid_job_that_fails_again_emits_a_second_event(factory, monkeypatch):
    calls = _deliveries(monkeypatch)
    with factory() as s:
        owner = _user(s, "a@example.com")
        ws = _owned_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.failed"])
        job_id = _failed_job(s, owner)
        _ledger(s, owner, job_id, -1, "reel")
        _ledger(s, owner, job_id, 1, "failure_refund")
        s.commit()
        webhook_job_events.emit_failed_jobs(s)
        _ledger(s, owner, job_id, -1, "retry")
        _ledger(s, owner, job_id, 1, "failure_refund")
        s.commit()
        webhook_job_events.emit_failed_jobs(s)
    assert [c["payload"]["event_id"] for c in calls] == [
        f"job.failed:{job_id}:1",
        f"job.failed:{job_id}:2",
    ]


def test_job_is_reported_only_after_refund_hooks_settle(factory, monkeypatch):
    calls = _deliveries(monkeypatch)
    with factory() as s:
        owner = _user(s, "a@example.com")
        ws = _owned_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.failed"])
        _failed_job(s, owner, age_s=1)
        _failed_job(s, owner, age_s=3 * 24 * 3600)  # outside the lookback
        s.commit()
        assert webhook_job_events.emit_failed_jobs(s) == 0
    assert calls == []


def test_no_job_failed_subscription_means_no_work(factory, monkeypatch):
    calls = _deliveries(monkeypatch)
    with factory() as s:
        owner = _user(s, "a@example.com")
        ws = _owned_workspace(s, owner)
        webhook_subscriptions.create(s, ws, _PUBLIC_URL, ["job.completed"])
        _failed_job(s, owner)
        s.commit()
        assert webhook_job_events.emit_failed_jobs(s) == 0
    assert calls == []


def test_wallet_and_flagged_refunds_are_read_not_guessed(factory):
    with factory() as s:
        owner = _user(s, "a@example.com")
        mint_released = _failed_job(
            s, owner,
            params={"_wallet": {"reserved_micros": 10, "mint_hold_id": "h", "settlement_status": "released"}},
        )
        mint_held = _failed_job(
            s, owner, params={"_wallet": {"reserved_micros": 10, "mint_hold_id": "h"}}
        )
        flagged = _failed_job(s, owner, params={"refunded": True})
        states = {
            j: webhook_job_events.refund_state(s, s.get(Job, j))
            for j in (mint_released, mint_held, flagged)
        }
    assert states[mint_released]["refunded"] is True
    assert states[mint_held]["refunded"] is False
    assert states[flagged] == {**states[flagged], "charged": True, "refunded": True}


# --------------------------------------------------------------------------- #
# No workspace needed
# --------------------------------------------------------------------------- #
def test_user_with_no_workspace_can_subscribe(factory, monkeypatch):
    _deliveries(monkeypatch)
    with factory() as s:
        loner = _user(s, "solo@example.com")
        sub, secret = webhook_subscriptions.create_for_user(s, loner, _PUBLIC_URL, ["job.failed"])
        assert secret
        ws = s.get(Workspace, sub.workspace_id)
        assert ws.owner_id == loner and ws.name == webhook_subscriptions.PERSONAL_WORKSPACE_NAME
        # A second subscription reuses the same workspace.
        sub2, _ = webhook_subscriptions.create_for_user(s, loner, _PUBLIC_URL, ["job.completed"])
        assert sub2.workspace_id == sub.workspace_id


def test_rejected_url_creates_no_workspace(factory):
    with factory() as s:
        loner = _user(s, "solo@example.com")
        with pytest.raises(webhook_subscriptions.WebhookSubscriptionError):
            webhook_subscriptions.create_for_user(s, loner, "http://10.0.0.1/x", ["job.failed"])
        assert s.execute(select(Workspace)).scalars().all() == []


def test_member_who_owns_nothing_gets_own_workspace(factory):
    with factory() as s:
        boss = _user(s, "boss@example.com")
        team = _owned_workspace(s, boss)
        viewer = _user(s, "viewer@example.com")
        s.add(WorkspaceMember(workspace_id=team, user_id=viewer, role="viewer"))
        s.flush()
        mine = webhook_subscriptions.ensure_personal_workspace(s, viewer)
        assert mine != team
        assert webhook_subscriptions.ensure_personal_workspace(s, boss) == team


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_api_subscribe_without_workspace(factory, monkeypatch):
    _deliveries(monkeypatch)

    @contextmanager
    def _gs():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(webhooks_mod, "get_session", _gs)
    app = FastAPI()
    app.include_router(webhooks_mod.router)

    def _handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _handler)
    client = TestClient(app)
    with factory() as s:
        s.add(User(email="solo@example.com", api_key_hash=_key_hash("solo-key")))
        s.commit()

    headers = {"x-api-key": "solo-key"}
    res = client.post("/api/v1/me/webhooks", json={"url": _PUBLIC_URL, "event_types": ["job.failed"]}, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["secret"] and data["workspace_id"]

    ensured = client.post("/api/v1/me/webhooks/workspace", headers=headers).json()["data"]
    assert ensured["workspace_id"] == data["workspace_id"]

    listed = client.get(f"/api/v1/me/workspaces/{data['workspace_id']}/webhooks", headers=headers)
    assert listed.status_code == 200
    assert "secret" not in listed.json()["data"][0]

    bad = client.post("/api/v1/me/webhooks", json={"url": _PUBLIC_URL, "event_types": ["nope"]}, headers=headers)
    assert bad.status_code == 400
