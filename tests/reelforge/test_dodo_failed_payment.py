# ruff: noqa: F811 - pytest fixtures are imported from test_dodo_payments
"""Dodo Payments: the recurring-billing failure path (the one gap the plan
flagged as untested: signature + idempotency and refund already have
coverage in ``test_dodo_payments.py`` / ``test_dodo_reversals.py``, but no
test exercised what happens when a personal plan's renewal charge fails).

Real SQLite ledger + real billing service; only Dodo HTTP is faked. Reuses
the same webhook endpoint, fixtures and signing helpers as
``test_dodo_payments.py`` so this suite exercises the real handler stack
(FastAPI route -> ``dodo_billing.handle_webhook`` -> ``creator_dodo.parse_event``
-> ``creator_subscriptions.apply_update``), not a mock of it.

Dodo's own event names and what we do with each (see
``app/services/billing/dodo_client.py:subscription_view`` and
``creator_subscriptions.py:apply_update``):

* ``subscription.failed`` / ``.cancelled`` / ``.expired`` -> terminal:
  local status becomes ``canceled``, no credits are granted, the plan does
  not come back from a later stale "active" for the same subscription id.
* ``subscription.past_due`` / ``.on_hold`` -> non-terminal "the card
  declined but Dodo is retrying it": local status becomes ``past_due``, no
  credits are granted, but a later ``subscription.active`` for the same
  subscription id still recovers it and grants the period (dunning
  recovery).
* Every event calls ``lifecycle_mail.on_plan_status`` (documented to never
  raise), so a mail-sender outage must not turn a failed-payment webhook
  into a 500 that makes Dodo retry forever.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.db.creator_subscription import CreatorSubscription
from tests.reelforge.test_dodo_payments import (  # noqa: F401 - fixture import
    PLAN_CREATOR_M,
    _balance,
    _signed,
    env,
)

WEBHOOK = "/api/v1/billing/webhook/dodo"


def _sub_event(event_type: str, user_id: str, *, sub_id="sub_fail1", status="", period_end=None):
    """A Dodo ``subscription.*`` event shaped like the real payload (see
    ``test_subscription_active_activates_dodo_plan`` for the ``.active`` shape
    this mirrors)."""
    data = {
        "payload_type": "Subscription",
        "subscription_id": sub_id,
        "status": status or event_type.rsplit(".", 1)[-1],
        "product_id": PLAN_CREATOR_M,
        "customer": {"customer_id": "cus_9", "email": "buyer@example.com"},
        "cancel_at_next_billing_date": False,
        "metadata": {"kind": "creator_plan", "user_id": user_id, "plan_key": "creator", "interval": "month"},
    }
    if period_end is not None:
        data["next_billing_date"] = period_end.isoformat()
    return {
        "type": event_type,
        "business_id": "bus_1",
        "timestamp": "2026-10-14T10:00:00Z",
        "data": data,
    }


def _activate(client, user_id: str, *, sub_id="sub_fail1", msg="msg_active", period_end=None):
    """Bring the plan live first (the same event shape the happy-path test uses)."""
    period_end = period_end or datetime.now(timezone.utc) + timedelta(days=30)
    event = _sub_event("subscription.active", user_id, sub_id=sub_id, status="active", period_end=period_end)
    body, headers = _signed(event, msg_id=msg)
    resp = client.post(WEBHOOK, content=body, headers=headers)
    assert resp.status_code == 200
    return period_end


def _row(Factory, user_id: str):
    with Factory() as s:
        return s.execute(
            select(CreatorSubscription).where(CreatorSubscription.user_id == user_id)
        ).scalar_one()


def test_subscription_failed_cancels_the_plan_grants_nothing(env):
    client, Factory, (user_id, _), _ = env
    _activate(client, user_id)
    balance_before = _balance(Factory, user_id)

    event = _sub_event("subscription.failed", user_id)
    body, headers = _signed(event, msg_id="msg_failed_1")
    resp = client.post(WEBHOOK, content=body, headers=headers)

    assert resp.status_code == 200
    assert resp.json()["data"]["handled"] == "subscription"
    row = _row(Factory, user_id)
    assert row.status == "canceled"
    assert _balance(Factory, user_id) == balance_before  # the failed renewal grants nothing


def test_subscription_failed_redelivery_is_idempotent(env):
    """Dodo retries undelivered webhooks; a second ``subscription.failed`` for
    the same event must not grant, alert, or error twice."""
    client, Factory, (user_id, _), _ = env
    _activate(client, user_id)

    event = _sub_event("subscription.failed", user_id)
    for msg in ("msg_failed_a", "msg_failed_b"):
        body, headers = _signed(event, msg_id=msg)
        assert client.post(WEBHOOK, content=body, headers=headers).status_code == 200

    row = _row(Factory, user_id)
    assert row.status == "canceled"
    assert _balance(Factory, user_id) == 35  # only the one activation grant ever landed


def test_subscription_failed_is_terminal_a_stale_active_replay_does_not_revive_it(env):
    """A late-arriving ``subscription.active`` for the *same* subscription id
    (redelivered out of order after the failure already applied) must not
    resurrect a canceled plan or grant credits for it."""
    client, Factory, (user_id, _), _ = env
    period_end = _activate(client, user_id)

    failed_body, failed_headers = _signed(_sub_event("subscription.failed", user_id), msg_id="msg_failed_x")
    assert client.post(WEBHOOK, content=failed_body, headers=failed_headers).status_code == 200
    balance_after_fail = _balance(Factory, user_id)

    stale = _sub_event("subscription.active", user_id, status="active", period_end=period_end)
    stale_body, stale_headers = _signed(stale, msg_id="msg_stale_active")
    resp = client.post(WEBHOOK, content=stale_body, headers=stale_headers)

    assert resp.status_code == 200
    row = _row(Factory, user_id)
    assert row.status == "canceled"
    assert _balance(Factory, user_id) == balance_after_fail


@pytest.mark.parametrize("event_type", ["subscription.past_due", "subscription.on_hold"])
def test_subscription_past_due_marks_the_plan_without_canceling_or_granting(env, event_type):
    """The card declined and Dodo is retrying it (not yet a cancellation):
    local status moves to ``past_due``, no credits are granted."""
    client, Factory, (user_id, _), _ = env
    _activate(client, user_id)
    balance_before = _balance(Factory, user_id)

    event = _sub_event(event_type, user_id)
    body, headers = _signed(event, msg_id=f"msg_{event_type}")
    resp = client.post(WEBHOOK, content=body, headers=headers)

    assert resp.status_code == 200
    row = _row(Factory, user_id)
    assert row.status == "past_due"
    assert _balance(Factory, user_id) == balance_before


def test_past_due_then_active_is_dunning_recovery_and_grants_the_new_period(env):
    """Dodo's own retry succeeds later: the next ``subscription.active`` for
    the same subscription id recovers the plan and grants that period's
    reels, because ``past_due`` (unlike ``failed``/``cancelled``) is not
    terminal."""
    client, Factory, (user_id, _), _ = env
    _activate(client, user_id, period_end=datetime.now(timezone.utc) + timedelta(days=30))

    past_due_body, past_due_headers = _signed(_sub_event("subscription.past_due", user_id), msg_id="msg_pd")
    assert client.post(WEBHOOK, content=past_due_body, headers=past_due_headers).status_code == 200
    assert _row(Factory, user_id).status == "past_due"

    recovered_period_end = datetime.now(timezone.utc) + timedelta(days=60)
    recovered = _sub_event(
        "subscription.active", user_id, status="active", period_end=recovered_period_end
    )
    body, headers = _signed(recovered, msg_id="msg_recovered")
    resp = client.post(WEBHOOK, content=body, headers=headers)

    assert resp.status_code == 200
    row = _row(Factory, user_id)
    assert row.status == "active"
    # No rollover (documented module invariant): the first period's unused
    # included reels are expired before the recovered period's 35 are granted,
    # so the balance is 35, not 70.
    assert _balance(Factory, user_id) == 35


def test_forged_signature_on_a_failed_payment_event_is_rejected_and_grants_nothing(env):
    """The failure path is exactly where a forged "your plan is fine" replay
    would be most valuable to an attacker trying to suppress a cancellation
    signal; the signature check must reject it before any DB write."""
    client, Factory, (user_id, _), _ = env
    _activate(client, user_id)

    event = _sub_event("subscription.failed", user_id)
    body = json.dumps(event).encode()
    bad_headers = {
        "webhook-id": "msg_forged",
        "webhook-timestamp": str(int(time.time())),
        "webhook-signature": "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    }

    resp = client.post(WEBHOOK, content=body, headers=bad_headers)

    assert resp.status_code == 400
    row = _row(Factory, user_id)
    assert row.status == "active"  # unchanged: the forged cancellation never applied


def test_mail_outage_does_not_fail_the_failed_payment_webhook(env, monkeypatch):
    """``subscription.past_due`` (a declined renewal charge Dodo is retrying)
    is the one status that makes ``lifecycle_mail.on_plan_status`` actually
    try to send a "payment failed" notice. Its ``notify`` wraps the whole
    send in a bare ``except Exception`` so a mailer outage never breaks
    billing; prove that end to end: the webhook must still return 200 (so
    Dodo does not retry forever) and the plan's status still moves to
    ``past_due`` even when the SMTP send raises."""
    from app.services import mailer

    client, Factory, (user_id, _), _ = env
    _activate(client, user_id)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("smtp outage")

    monkeypatch.setattr(mailer, "send_email", _boom)

    event = _sub_event("subscription.past_due", user_id)
    body, headers = _signed(event, msg_id="msg_mail_outage")
    resp = client.post(WEBHOOK, content=body, headers=headers)

    assert resp.status_code == 200
    assert _row(Factory, user_id).status == "past_due"
