# ruff: noqa: F811 - pytest fixtures are imported from test_dodo_payments
"""Dodo Payments: the recurring-billing failure path for WORKSPACE (team) plans.

``test_dodo_failed_payment.py`` covers this for a personal ``creator`` plan
(``creator_subscriptions.apply_update``). Team/workspace plans route through a
different applier (``app.services.subscriptions.process_provider_event``, see
``dodo_billing._apply_team_event``) — a gap flagged in plans/menivor.md's
2026-10-14 ship notes ("workspace_plans.py's Dodo team-subscription failure
handling is still untested"). Both appliers share the SAME status mapping
(``dodo_client._STATUS_MAP`` / ``GRANT_EVENTS``), so this suite proves the team
path has the identical dunning invariants, not just the personal one:

* ``subscription.failed`` / ``.cancelled`` / ``.expired`` -> terminal: the
  workspace row becomes ``canceled``, no credits are granted, and a later
  stale ``subscription.active`` for the same provider subscription id cannot
  revive it (``process_provider_event``'s same-ref-canceled-is-terminal guard).
* ``subscription.past_due`` / ``.on_hold`` -> non-terminal: the row becomes
  ``past_due``, no credits are granted, but a later ``subscription.active``
  for the same subscription id is dunning recovery and grants that period.
* A forged signature on a failed-payment event is rejected before any write.

Real SQLite ledger + real billing/subscription services; only Dodo HTTP,
Redis and owner alerts are faked (same seam as ``test_dodo_team_wallet.py``).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.models.db.models import Workspace
from app.models.db.repositories import CreditRepository, SubscriptionRepository
from app.services.billing import dodo_billing, subscription_providers
from app.services.billing import workspace_plans as wp
from tests.reelforge.test_dodo_payments import _signed, env  # noqa: F401

WEBHOOK = "/api/v1/billing/webhook/dodo"
TEAM_M = "pdt_team_starter_m"


@pytest.fixture()
def wired(env, monkeypatch):
    """Dodo team product mapped + the subscription_providers hand-off in place
    (identical wiring to ``test_dodo_team_wallet.py``'s ``wired`` fixture)."""
    monkeypatch.setenv("DODO_PRODUCT_ID_TEAM_STARTER_MONTH", TEAM_M)
    monkeypatch.setattr(
        subscription_providers,
        "SUPPORTED_PROVIDERS",
        ("stripe", "creem", "polar", "dodo"),
        raising=False,
    )
    original = subscription_providers.parse_event
    monkeypatch.setattr(
        subscription_providers,
        "parse_event",
        lambda provider, event: wp.parse_dodo_event(event) if provider == "dodo" else original(provider, event),
    )
    alerts: list[str] = []
    monkeypatch.setattr(dodo_billing, "_alert_owner", alerts.append)
    monkeypatch.setattr(dodo_billing, "_notify_user", lambda *a, **k: None)
    client, Factory, (user_id, other_id), fake = env
    with Factory() as s:
        ws = Workspace(name="Team", owner_id=user_id)
        s.add(ws)
        s.commit()
        ws_id = ws.id
    return client, Factory, user_id, ws_id, fake, alerts


def _post(client, event: dict, msg: str):
    body, headers = _signed(event, msg_id=msg)
    return client.post(WEBHOOK, content=body, headers=headers)


def _team_event(
    event_type: str,
    user_id: str,
    ws_id: str,
    *,
    sub: str = "sub_team_fail1",
    status: str = "",
    period_end=None,
) -> dict:
    data = {
        "payload_type": "Subscription",
        "subscription_id": sub,
        "status": status or event_type.rsplit(".", 1)[-1],
        "product_id": TEAM_M,
        "customer": {"customer_id": "cus_t"},
        "metadata": {
            "kind": "subscription",
            "user_id": user_id,
            "workspace_id": ws_id,
            "plan_key": "starter",
            "interval": "month",
            "seats": "3",
        },
    }
    if period_end is not None:
        data["next_billing_date"] = period_end.isoformat()
    return {"type": event_type, "business_id": "bus_1", "data": data}


def _activate(client, user_id: str, ws_id: str, *, sub="sub_team_fail1", msg="t_active", period_end=None):
    period_end = period_end or datetime.now(timezone.utc) + timedelta(days=30)
    event = _team_event("subscription.active", user_id, ws_id, sub=sub, status="active", period_end=period_end)
    resp = _post(client, event, msg)
    assert resp.status_code == 200
    return period_end


def _status(Factory, ws_id: str) -> str:
    with Factory() as s:
        row = SubscriptionRepository(s).get_for_workspace(ws_id)
        return str(row.status)


def _balance(Factory, ws_id: str) -> int:
    with Factory() as s:
        return int(CreditRepository(s).workspace_balance(ws_id))


def test_team_subscription_failed_cancels_the_plan_grants_nothing(wired):
    client, Factory, user_id, ws_id, _fake, _alerts = wired
    _activate(client, user_id, ws_id)
    balance_before = _balance(Factory, ws_id)

    event = _team_event("subscription.failed", user_id, ws_id)
    resp = _post(client, event, "t_failed_1")

    assert resp.status_code == 200
    assert resp.json()["data"]["handled"] == "team_subscription"
    assert _status(Factory, ws_id) == "canceled"
    assert _balance(Factory, ws_id) == balance_before  # the failed renewal grants nothing


def test_team_subscription_failed_redelivery_is_idempotent(wired):
    """Dodo retries undelivered webhooks; a second ``subscription.failed`` for
    the same workspace subscription must not grant, alert, or error twice."""
    client, Factory, user_id, ws_id, _fake, _alerts = wired
    _activate(client, user_id, ws_id)
    plan = wp.get_workspace_plan("starter")

    event = _team_event("subscription.failed", user_id, ws_id)
    for msg in ("t_failed_a", "t_failed_b"):
        assert _post(client, event, msg).status_code == 200

    assert _status(Factory, ws_id) == "canceled"
    assert _balance(Factory, ws_id) == plan.monthly_credits  # only the one activation grant ever landed


def test_team_subscription_failed_is_terminal_a_stale_active_replay_does_not_revive_it(wired):
    """A late-arriving ``subscription.active`` for the *same* subscription id
    (redelivered out of order after the failure already applied) must not
    resurrect a canceled workspace plan or grant credits for it."""
    client, Factory, user_id, ws_id, _fake, _alerts = wired
    period_end = _activate(client, user_id, ws_id)

    failed = _team_event("subscription.failed", user_id, ws_id)
    assert _post(client, failed, "t_failed_x").status_code == 200
    balance_after_fail = _balance(Factory, ws_id)

    stale = _team_event("subscription.active", user_id, ws_id, status="active", period_end=period_end)
    resp = _post(client, stale, "t_stale_active")

    assert resp.status_code == 200
    assert _status(Factory, ws_id) == "canceled"
    assert _balance(Factory, ws_id) == balance_after_fail


@pytest.mark.parametrize("event_type", ["subscription.past_due", "subscription.on_hold"])
def test_team_subscription_past_due_marks_the_plan_without_canceling_or_granting(wired, event_type):
    """The card declined and Dodo is retrying it (not yet a cancellation):
    the workspace row moves to ``past_due``, no credits are granted."""
    client, Factory, user_id, ws_id, _fake, _alerts = wired
    _activate(client, user_id, ws_id)
    balance_before = _balance(Factory, ws_id)

    event = _team_event(event_type, user_id, ws_id)
    resp = _post(client, event, f"t_{event_type}")

    assert resp.status_code == 200
    assert _status(Factory, ws_id) == "past_due"
    assert _balance(Factory, ws_id) == balance_before


def test_team_past_due_then_active_is_dunning_recovery_and_grants_the_new_period(wired):
    """Dodo's own retry succeeds later: the next ``subscription.active`` for
    the same subscription id recovers the workspace plan and grants that
    period's seat credits, because ``past_due`` (unlike ``failed``/``cancelled``)
    is not terminal."""
    client, Factory, user_id, ws_id, _fake, _alerts = wired
    plan = wp.get_workspace_plan("starter")
    _activate(client, user_id, ws_id, period_end=datetime.now(timezone.utc) + timedelta(days=30))
    balance_after_activation = _balance(Factory, ws_id)

    past_due = _team_event("subscription.past_due", user_id, ws_id)
    assert _post(client, past_due, "t_pd").status_code == 200
    assert _status(Factory, ws_id) == "past_due"

    recovered_period_end = datetime.now(timezone.utc) + timedelta(days=60)
    recovered = _team_event(
        "subscription.active", user_id, ws_id, status="active", period_end=recovered_period_end
    )
    resp = _post(client, recovered, "t_recovered")

    assert resp.status_code == 200
    assert _status(Factory, ws_id) == "active"
    # The recovered period is keyed on its own period end, so it grants on top
    # of the pool (workspace pools do not expire unused credits the way a
    # personal plan's included-reels balance does) -- at least one more
    # period's worth of credits landed and the plan is live again.
    assert _balance(Factory, ws_id) >= balance_after_activation + plan.monthly_credits


def test_team_forged_signature_on_a_failed_payment_event_is_rejected_and_grants_nothing(wired):
    """The failure path is exactly where a forged "your plan is fine" replay
    would be most valuable to an attacker trying to suppress a cancellation
    signal; the signature check must reject it before any DB write."""
    client, Factory, user_id, ws_id, _fake, _alerts = wired
    _activate(client, user_id, ws_id)

    event = _team_event("subscription.failed", user_id, ws_id)
    body = json.dumps(event).encode()
    bad_headers = {
        "webhook-id": "t_forged",
        "webhook-timestamp": str(int(time.time())),
        "webhook-signature": "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    }

    resp = client.post(WEBHOOK, content=body, headers=bad_headers)

    assert resp.status_code == 400
    assert _status(Factory, ws_id) == "active"  # unchanged: the forged cancellation never applied
