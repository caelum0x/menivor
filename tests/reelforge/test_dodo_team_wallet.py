# ruff: noqa: F811 - pytest fixtures are imported from test_dodo_payments
"""MN4: team plans and wallet top-ups on Dodo.

Real SQLite ledger, real subscription applier and wallet service; only Dodo
HTTP, Redis and owner alerts are faked. ``subscription_providers`` gets the
Dodo dispatch it needs through a test double (the one-line hand-off).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domains.wallet.service import WalletService
from app.models.db.marketplace import PaymentIntent
from app.models.db.models import Workspace
from app.models.db.repositories import CreditRepository, SubscriptionRepository
from app.services.billing import dodo_billing, subscription_providers
from app.services.billing import workspace_plans as wp
from tests.reelforge.test_dodo_payments import _signed, env  # noqa: F401

URL = "/api/v1/billing/webhook/dodo"
TEAM_M, TEAM_Y, WALLET = "pdt_team_starter_m", "pdt_team_starter_y", "pdt_wallet"


@pytest.fixture()
def wired(env, monkeypatch):
    """Dodo products mapped + the subscription_providers hand-off in place."""
    monkeypatch.setenv("DODO_PRODUCT_ID_TEAM_STARTER_MONTH", TEAM_M)
    monkeypatch.setenv("DODO_PRODUCT_ID_TEAM_STARTER_YEAR", TEAM_Y)
    monkeypatch.setenv("DODO_PRODUCT_ID_WALLET_TOPUP", WALLET)
    monkeypatch.setattr(subscription_providers, "SUPPORTED_PROVIDERS", ("stripe", "creem", "polar", "dodo"),
                        raising=False)
    original = subscription_providers.parse_event
    monkeypatch.setattr(subscription_providers, "parse_event",
                        lambda provider, event: wp.parse_dodo_event(event) if provider == "dodo"
                        else original(provider, event))
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
    return client.post(URL, content=body, headers=headers)


def _team_event(user_id: str, ws_id: str, product: str, interval: str, *, sub="sub_team") -> dict:
    return {
        "type": "subscription.active", "business_id": "bus_1",
        "data": {"payload_type": "Subscription", "subscription_id": sub, "status": "active",
                 "product_id": product, "customer": {"customer_id": "cus_t"},
                 "next_billing_date": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                 "metadata": {"kind": "subscription", "user_id": user_id, "workspace_id": ws_id,
                              "plan_key": "starter", "interval": interval, "seats": "3"}},
    }


@pytest.mark.parametrize("product,interval,months", [(TEAM_M, "month", 1), (TEAM_Y, "year", 12)])
def test_team_checkout_grants_seat_plan_once(wired, product, interval, months):
    client, Factory, user_id, ws_id, _fake, _alerts = wired
    event = _team_event(user_id, ws_id, product, interval)
    for msg in ("t1", "t2"):
        resp = _post(client, event, msg)
        assert resp.status_code == 200 and resp.json()["data"]["handled"] == "team_subscription"
    plan = wp.get_workspace_plan("starter")
    with Factory() as s:
        row = SubscriptionRepository(s).get_for_workspace(ws_id)
        assert row.provider == "dodo" and row.status == "active" and row.plan_key == "starter"
        assert CreditRepository(s).workspace_balance(ws_id) == plan.monthly_credits * months


def test_team_event_without_wiring_is_retried_and_alerts(env, monkeypatch):
    client, Factory, (user_id, _), _fake = env
    monkeypatch.setenv("DODO_PRODUCT_ID_TEAM_STARTER_MONTH", TEAM_M)
    alerts: list[str] = []
    monkeypatch.setattr(dodo_billing, "_alert_owner", alerts.append)
    resp = _post(client, _team_event(user_id, "ws_x", TEAM_M, "month"), "nw1")
    assert resp.status_code == 500 and alerts


def test_dodo_team_checkout_offered_only_when_mapped_and_wired(env, monkeypatch):
    monkeypatch.setenv("DODO_PRODUCT_ID_TEAM_STARTER_MONTH", TEAM_M)
    assert "dodo" not in wp.available_providers("starter", "month")  # transport not wired
    monkeypatch.setattr(subscription_providers, "SUPPORTED_PROVIDERS", ("dodo",), raising=False)
    status = wp.dodo_checkout_status()
    assert status["starter"] == {"month": True, "year": False}
    assert status["pro"] == {"month": False, "year": False}


def test_open_dodo_team_checkout_threads_workspace(wired):
    _client, _Factory, user_id, ws_id, fake, _alerts = wired
    out = wp.open_dodo_checkout(TEAM_M, {"user_id": user_id, "workspace_id": ws_id}, user_email="a@b.co")
    assert out["checkout_url"].startswith("https://")
    body = fake.calls[-1]["body"]
    assert body["metadata"]["kind"] == "subscription" and body["metadata"]["workspace_id"] == ws_id
    assert body["product_cart"][0]["product_id"] == TEAM_M


def _intent(Factory, user_id: str, *, credit=10_000_000, total=10_500_000) -> str:
    with Factory() as s:
        intent = PaymentIntent(
            account_id=WalletService(s)._repo.get_or_create_personal_account(user_id).id,
            user_id=user_id, idempotency_key="k1", credit_micros=credit, total_charge_micros=total,
            payment_provider="dodo", provider_ref="cks_1", status="pending",
        )
        s.add(intent)
        s.commit()
        return intent.id


def _wallet_event(user_id: str, intent_id: str, *, total=1050, pid="pay_w1") -> dict:
    return {
        "type": "payment.succeeded", "business_id": "bus_1",
        "data": {"payment_id": pid, "status": "succeeded", "total_amount": total, "tax": 0,
                 "currency": "USD", "customer": {"customer_id": "cus_w"}, "subscription_id": None,
                 "product_cart": [{"product_id": WALLET, "quantity": 1}],
                 "metadata": {"kind": "wallet_topup", "payment_intent_id": intent_id, "user_id": user_id,
                              "credit_micros": "10000000", "total_charge_micros": "10500000"}},
    }


def _available(Factory, user_id: str) -> int:
    with Factory() as s:
        return int(WalletService(s).balance_view(user_id)["available_micros"])


def test_wallet_topup_grants_once_and_refund_reverses_once(wired):
    client, Factory, user_id, _ws, fake, alerts = wired
    intent_id = _intent(Factory, user_id)
    event = _wallet_event(user_id, intent_id)
    for msg in ("w1", "w2"):
        resp = _post(client, event, msg)
        assert resp.status_code == 200 and resp.json()["data"]["handled"] == "wallet"
    assert _available(Factory, user_id) == 10_000_000
    fake.payments["pay_w1"] = {**event["data"]}
    refund = {"type": "refund.succeeded", "business_id": "bus_1",
              "data": {"refund_id": "ref_w", "payment_id": "pay_w1", "status": "succeeded"}}
    for msg in ("wr1", "wr2"):
        assert _post(client, refund, msg).status_code == 200
    assert _available(Factory, user_id) == 0
    assert not alerts


def test_wallet_payment_with_wrong_amount_grants_nothing(wired):
    client, Factory, user_id, _ws, _fake, alerts = wired
    intent_id = _intent(Factory, user_id)
    resp = _post(client, _wallet_event(user_id, intent_id, total=100), "bad1")
    assert resp.status_code == 200 and resp.json()["data"]["status"] == "rejected"
    assert _available(Factory, user_id) == 0 and alerts


def test_dodo_wallet_checkout_charges_the_quoted_total(wired):
    _client, Factory, user_id, _ws, fake, _alerts = wired
    from app.domains.wallet import webhooks as wallet_webhooks

    with Factory() as s:
        intent = s.get(PaymentIntent, _intent(Factory, user_id))
    out = wallet_webhooks.create_dodo_wallet_checkout_session(intent)
    assert out["session_id"]
    body = fake.calls[-1]["body"]
    assert body["product_cart"] == [{"product_id": WALLET, "quantity": 1, "amount": 1050}]
    assert body["metadata"]["kind"] == "wallet_topup"
    assert wallet_webhooks.dodo_wallet_available() is True
