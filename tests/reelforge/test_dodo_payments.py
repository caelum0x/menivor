"""Dodo Payments adapter + payments-paused mode.

Real SQLite ledger + real billing service; only Dodo HTTP and Redis are faked.

* Standard Webhooks verification (v1 HMAC, whsec_ secret, tolerance, rotation).
* Paused mode: no card check (monthly free reels once per month), no checkout,
  no providers, launch status advertises it; webhooks still settle.
* Dodo active: card check / pack checkout open Dodo sessions with string
  metadata, a User-Agent and the right return URL.
* payment.succeeded grants a pack / card check once (webhook + return share
  the ledger reason); a forged signature is rejected; refunds claw back.
* subscription.active activates a personal plan with provider "dodo".
* Paddle signature scaffold.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.billing as billing_mod
import app.models.db.base as db_base
from app.config import config
from app.core.launch import policy
from app.models.db.base import Base
from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.models import CreditLedger, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services.billing import (
    card_check,
    dodo_billing,
    dodo_client,
    paddle_client,
    payments_mode,
    service,
    standard_webhooks,
)
from app.services.billing.plans import SIGNUP_GRANT
from app.utils import utils

SECRET = "whsec_" + base64.b64encode(b"dodo-test-signing-key-0123456789").decode()
CARD = "pdt_card"
STARTER = "pdt_starter"
PRO = "pdt_pro"
PLAN_CREATOR_M = "pdt_plan_creator_m"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FakeDodo:
    """Records Dodo HTTP calls; answers from canned payments/subscriptions."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.payments: dict[str, dict] = {}
        self.subscriptions: dict[str, dict] = {}

    def request(self, method, path, *, body=None, params=None):
        self.calls.append({"method": method, "path": path, "body": body, "params": params})
        if method == "POST" and path == "/checkouts":
            n = len([c for c in self.calls if c["path"] == "/checkouts"])
            return {"session_id": f"cks_{n}", "checkout_url": f"https://checkout.dodopayments.com/session/cks_{n}"}
        if method == "GET" and path.startswith("/payments/"):
            return self.payments[path.split("/")[-1]]
        if method == "GET" and path.startswith("/subscriptions/"):
            return self.subscriptions[path.split("/")[-1]]
        return {}


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

    monkeypatch.setattr(billing_mod, "get_session", _session)
    monkeypatch.setattr(billing_mod, "_DB_IMPORT_ERROR", None)
    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(service, "_get_redis", lambda: None)
    monkeypatch.setattr(
        config,
        "dodo",
        {
            "api_key": "dodo_test_key",
            "webhook_secret": SECRET,
            "environment": "live_mode",
            "card_check_product_id": CARD,
            "starter_product_id": STARTER,
            "pro_product_id": PRO,
            "plan_creator_month_product_id": PLAN_CREATOR_M,
        },
        raising=False,
    )
    monkeypatch.setattr(config, "creem", {"web_base_url": "https://menivor.com"}, raising=False)
    monkeypatch.setenv("MENIVOR_PAYMENTS_PROVIDER", "dodo")
    monkeypatch.delenv("MENIVOR_PAYMENTS_PAUSED", raising=False)
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "public")
    monkeypatch.setenv("REELFORGE_PUBLIC_LAUNCH_APPROVED", "true")
    monkeypatch.setenv("REELFORGE_CHECKOUT_ENABLED", "true")
    fake = FakeDodo()
    monkeypatch.setattr(dodo_client, "request", fake.request)

    app = FastAPI()
    app.include_router(billing_mod.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _handler)
    with _session() as s:
        user = User(email="buyer@example.com", display_name="Buyer", api_key_hash=_hash("rk_buyer"))
        other = User(email="other@example.com", display_name="Other", api_key_hash=_hash("rk_other"))
        s.add_all([user, other])
        s.flush()
        ids = (user.id, other.id)
    return TestClient(app), Factory, ids, fake


H = {"x-api-key": "rk_buyer"}


def _balance(Factory, user_id: str) -> int:
    with Factory() as s:
        return CreditRepository(s).balance(user_id)


def _signed(event: dict, *, msg_id: str = "msg_1", ts: int | None = None, secret: str = SECRET):
    body = json.dumps(event).encode()
    stamp = str(int(time.time()) if ts is None else ts)
    sig = standard_webhooks.sign(secret, msg_id, stamp, body)
    headers = {"webhook-id": msg_id, "webhook-timestamp": stamp, "webhook-signature": f"v1,{sig}"}
    return body, headers


def _payment_event(user_id: str, product: str, *, payment_id="pay_1", kind="pack", plan_key="starter"):
    return {
        "business_id": "bus_1",
        "type": "payment.succeeded",
        "timestamp": "2026-09-26T10:00:00Z",
        "data": {
            "payload_type": "Payment",
            "payment_id": payment_id,
            "status": "succeeded",
            "customer": {"customer_id": "cus_1", "email": "buyer@example.com"},
            "subscription_id": None,
            "product_cart": [{"product_id": product, "quantity": 1}],
            "metadata": {"kind": kind, "user_id": user_id, "plan_key": plan_key},
        },
    }


# --------------------------------------------------------------------------- #
# Standard Webhooks
# --------------------------------------------------------------------------- #
def test_standard_webhooks_accepts_valid_and_rotated_signatures():
    body, headers = _signed({"type": "x", "data": {}})
    headers["webhook-signature"] = "v1,bm90LXRoZS1zaWc= " + headers["webhook-signature"]
    event = standard_webhooks.verify(body, headers, SECRET)
    assert event["type"] == "x" and event["_webhook_id"] == "msg_1"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b, h: (b + b" ", h),
        lambda b, h: (b, {**h, "webhook-signature": "v1,AAAA"}),
        lambda b, h: (b, {k: v for k, v in h.items() if k != "webhook-id"}),
        lambda b, h: (b, {**h, "webhook-timestamp": str(int(time.time()) - 3600)}),
    ],
)
def test_standard_webhooks_rejects_forged_or_stale(mutate):
    body, headers = _signed({"type": "x", "data": {}})
    bad_body, bad_headers = mutate(body, headers)
    with pytest.raises(standard_webhooks.SignatureError):
        standard_webhooks.verify(bad_body, bad_headers, SECRET)


def test_dodo_http_sends_bearer_and_user_agent(monkeypatch):
    seen = {}

    class _Resp:
        status_code = 200
        content = b"{}"
        text = "{}"

        def json(self):
            return {"session_id": "cks_x", "checkout_url": "https://checkout.dodopayments.com/x"}

    def _fake(method, url, headers=None, json=None, params=None, timeout=None):
        seen.update(method=method, url=url, headers=headers, json=json)
        return _Resp()

    import requests

    monkeypatch.setattr(requests, "request", _fake)
    monkeypatch.setattr(config, "dodo", {"api_key": "k_live", "environment": "live_mode"}, raising=False)
    monkeypatch.setattr(config, "creem", {"web_base_url": "https://menivor.com"}, raising=False)
    out = dodo_client.create_checkout(
        product_id="pdt_x", metadata={"user_id": "u1", "credits": 30}, return_url="https://m/x"
    )
    assert out == {"session_id": "cks_x", "checkout_url": "https://checkout.dodopayments.com/x"}
    assert seen["url"] == "https://live.dodopayments.com/checkouts"
    assert seen["headers"]["Authorization"] == "Bearer k_live"
    assert seen["headers"]["User-Agent"].startswith("menivor-api/")
    assert seen["json"]["metadata"] == {"user_id": "u1", "credits": "30"}
    assert seen["json"]["product_cart"] == [{"product_id": "pdt_x", "quantity": 1}]


def test_dodo_http_error_is_normalized(monkeypatch):
    class _Resp:
        status_code = 422
        content = b"bad"
        text = "bad request"

    import requests

    monkeypatch.setattr(requests, "request", lambda *a, **k: _Resp())
    monkeypatch.setattr(config, "dodo", {"api_key": "k"}, raising=False)
    with pytest.raises(dodo_client.DodoError) as err:
        dodo_client.get_payment("pay_1")
    assert err.value.status == 422


# --------------------------------------------------------------------------- #
# Paused mode
# --------------------------------------------------------------------------- #
def test_paused_mode_skips_card_check_and_grants_monthly_reels_once(env, monkeypatch):
    client, Factory, (user_id, _), fake = env
    monkeypatch.setenv("MENIVOR_PAYMENTS_PAUSED", "1")
    first = client.get("/api/v1/billing/card-check", headers=H).json()["data"]
    assert first["paused"] is True and first["unlocked"] is True
    assert first["provider"] == "none" and first["free_monthly_reels"] == 3
    assert first["credits"] == 3
    again = client.get("/api/v1/billing/card-check", headers=H).json()["data"]
    assert again["credits"] == 3  # once per month
    post = client.post("/api/v1/billing/card-check", headers=H, json={})
    assert post.status_code == 409 and post.json()["data"]["code"] == "payments_paused"
    assert fake.calls == []  # no provider touched


def test_paused_mode_next_month_grants_again_and_keeps_paid_credits(env, monkeypatch):
    _, Factory, (user_id, _), _ = env
    monkeypatch.setenv("MENIVOR_PAYMENTS_PROVIDER", "none")
    with Factory() as s:
        CreditRepository(s).grant(user_id, 30, reason="purchase:creem:ch_old")
        s.commit()
    payments_mode.grant_free_monthly(user_id, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
    payments_mode.grant_free_monthly(user_id, now=datetime(2026, 9, 28, tzinfo=timezone.utc))
    payments_mode.grant_free_monthly(user_id, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert _balance(Factory, user_id) == 36


def test_paused_mode_closes_checkout_and_providers_but_not_webhooks(env, monkeypatch):
    client, Factory, (user_id, _), _ = env
    monkeypatch.setenv("MENIVOR_PAYMENTS_PROVIDER", "none")
    assert policy.checkout_enabled() is False
    assert policy.payment_webhooks_enabled() is True
    assert service.list_enabled_providers() == []
    status = policy.launch_status()
    assert status["features"]["checkout"] is False
    assert status["payments"] == {"paused": True, "provider": "none", "free_monthly_reels": 3}
    with pytest.raises(service.PaymentsPaused):
        service.create_checkout(user_id=user_id, plan_key="starter", provider="dodo")
    # An in-flight Dodo payment still settles while paused.
    body, headers = _signed(_payment_event(user_id, STARTER))
    resp = client.post("/api/v1/billing/webhook/dodo", content=body, headers=headers)
    assert resp.status_code == 200, resp.text
    assert _balance(Factory, user_id) == 30


def test_unknown_provider_fails_closed(monkeypatch):
    monkeypatch.setenv("MENIVOR_PAYMENTS_PROVIDER", "stripe-please")
    monkeypatch.delenv("MENIVOR_PAYMENTS_PAUSED", raising=False)
    assert payments_mode.active_provider() == "none"


# --------------------------------------------------------------------------- #
# Dodo active
# --------------------------------------------------------------------------- #
def test_card_check_opens_dodo_checkout_with_onboarding_return(env):
    client, _, (user_id, _), fake = env
    status = client.get("/api/v1/billing/card-check", headers=H).json()["data"]
    assert status["unlocked"] is False and status["available"] is True
    assert status["provider"] == "dodo" and status["paused"] is False
    resp = client.post("/api/v1/billing/card-check", headers=H, json={"next": "/create?auto=1"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["checkout_url"].startswith("https://checkout.dodopayments.com/")
    body = fake.calls[-1]["body"]
    assert body["product_cart"] == [{"product_id": CARD, "quantity": 1}]
    assert body["metadata"]["kind"] == "card_check" and body["metadata"]["user_id"] == user_id
    assert body["customer"] == {"email": "buyer@example.com"}
    parts = urlsplit(body["return_url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://menivor.com/onboarding"
    query = dict(parse_qsl(parts.query))
    assert query == {"checkout": "return", "provider": "dodo", "next": "/create?auto=1"}


def test_only_the_active_provider_is_offered(env, monkeypatch):
    monkeypatch.setattr(
        service,
        "_config_section",
        lambda name: {"creem": {"api_key": "c"}, "dodo": {"api_key": "d"}}.get(name, {}),
    )
    assert service.list_enabled_providers() == ["dodo"]
    with pytest.raises(service.PaymentsPaused):
        service.create_checkout(user_id="u1", plan_key="starter", provider="creem")


def test_pack_checkout_via_dodo(env):
    _, _, (user_id, _), fake = env
    out = service.create_checkout(user_id=user_id, user_email="b@x.com", plan_key="pro", provider="dodo")
    assert out["provider"] == "dodo" and out["credits"] == 120
    body = fake.calls[-1]["body"]
    assert body["product_cart"][0]["product_id"] == PRO
    assert body["metadata"] == {"kind": "pack", "user_id": user_id, "plan_key": "pro", "credits": "120"}
    assert body["return_url"] == "https://menivor.com/billing?checkout=return&provider=dodo"


def test_pack_webhook_grants_once_and_rejects_forgery(env):
    client, Factory, (user_id, _), _ = env
    body, headers = _signed(_payment_event(user_id, STARTER))
    assert client.post("/api/v1/billing/webhook/dodo", content=body, headers=headers).status_code == 200
    assert client.post("/api/v1/billing/webhooks/dodo", content=body, headers=headers).status_code == 200
    assert _balance(Factory, user_id) == 30
    forged, fheaders = _signed(_payment_event(user_id, PRO, payment_id="pay_x"), secret="whsec_" + base64.b64encode(b"wrong").decode())
    resp = client.post("/api/v1/billing/webhook/dodo", content=forged, headers=fheaders)
    assert resp.status_code == 400
    assert _balance(Factory, user_id) == 30


def test_card_check_webhook_unlocks_free_reels(env):
    client, Factory, (user_id, _), _ = env
    event = _payment_event(user_id, CARD, payment_id="pay_card", kind="card_check", plan_key="card_check")
    body, headers = _signed(event)
    assert client.post("/api/v1/billing/webhook/dodo", content=body, headers=headers).status_code == 200
    assert _balance(Factory, user_id) == 1 + SIGNUP_GRANT
    data = client.get("/api/v1/billing/card-check", headers=H).json()["data"]
    assert data["unlocked"] is True


def test_return_confirm_is_verified_server_side_and_idempotent(env):
    client, Factory, (user_id, other_id), fake = env
    fake.payments["pay_7"] = _payment_event(user_id, PRO, payment_id="pay_7", plan_key="pro")["data"]
    resp = client.post("/api/v1/billing/dodo/confirm", headers=H, json={"payment_id": "pay_7"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["credits"] == 120
    # The webhook for the same payment grants nothing more.
    body, headers = _signed(_payment_event(user_id, PRO, payment_id="pay_7", plan_key="pro"), msg_id="msg_7")
    client.post("/api/v1/billing/webhook/dodo", content=body, headers=headers)
    client.post("/api/v1/billing/dodo/confirm", headers=H, json={"payment_id": "pay_7"})
    assert _balance(Factory, user_id) == 120
    # Someone else's payment id cannot be redeemed.
    stolen = client.post("/api/v1/billing/dodo/confirm", headers={"x-api-key": "rk_other"}, json={"payment_id": "pay_7"})
    assert stolen.status_code == 400
    assert _balance(Factory, other_id) == 0


def test_return_confirm_pending_payment(env):
    client, Factory, (user_id, _), fake = env
    data = _payment_event(user_id, STARTER, payment_id="pay_p")["data"]
    fake.payments["pay_p"] = {**data, "status": "processing"}
    resp = client.post("/api/v1/billing/dodo/confirm", headers=H, json={"payment_id": "pay_p"})
    assert resp.status_code == 200 and resp.json()["data"] == {"pending": True}
    assert _balance(Factory, user_id) == 0


def test_refund_claws_back_pack_credits_once(env):
    client, Factory, (user_id, _), _ = env
    body, headers = _signed(_payment_event(user_id, STARTER, payment_id="pay_r"))
    client.post("/api/v1/billing/webhook/dodo", content=body, headers=headers)
    refund = {"type": "refund.succeeded", "business_id": "bus_1", "timestamp": "2026-09-26T11:00:00Z",
              "data": {"refund_id": "ref_1", "payment_id": "pay_r", "status": "succeeded"}}
    for msg in ("msg_r1", "msg_r2"):
        rb, rh = _signed(refund, msg_id=msg)
        assert client.post("/api/v1/billing/webhook/dodo", content=rb, headers=rh).status_code == 200
    assert _balance(Factory, user_id) == 0


def test_subscription_active_activates_dodo_plan(env):
    client, Factory, (user_id, _), _ = env
    period_end = datetime.now(timezone.utc) + timedelta(days=30)
    event = {
        "type": "subscription.active",
        "business_id": "bus_1",
        "timestamp": "2026-09-26T10:00:00Z",
        "data": {
            "payload_type": "Subscription",
            "subscription_id": "sub_d1",
            "status": "active",
            "product_id": PLAN_CREATOR_M,
            "customer": {"customer_id": "cus_9", "email": "buyer@example.com"},
            "next_billing_date": period_end.isoformat(),
            "cancel_at_next_billing_date": False,
            "metadata": {"kind": "creator_plan", "user_id": user_id, "plan_key": "creator", "interval": "month"},
        },
    }
    for msg in ("msg_s1", "msg_s2"):
        body, headers = _signed(event, msg_id=msg)
        assert client.post("/api/v1/billing/webhook/dodo", content=body, headers=headers).status_code == 200
    with Factory() as s:
        row = s.execute(select(CreatorSubscription).where(CreatorSubscription.user_id == user_id)).scalar_one()
        assert (row.provider, row.provider_ref, row.customer_ref, row.plan_key, row.status) == (
            "dodo", "sub_d1", "cus_9", "creator", "active",
        )
        reasons = [r for (r,) in s.execute(select(CreditLedger.reason).where(CreditLedger.user_id == user_id))]
    assert _balance(Factory, user_id) == 35
    assert all(r.startswith("purchase:dodo:msub:sub_d1:") for r in reasons)


def test_dodo_plan_cancel_and_portal_use_dodo(env):
    from app.services.billing import creator_plan_actions

    client, Factory, (user_id, _), fake = env
    with Factory() as s:
        s.add(CreatorSubscription(user_id=user_id, plan_key="creator", provider="dodo",
                                  provider_ref="sub_d2", customer_ref="cus_2", status="active"))
        s.commit()
    creator_plan_actions.cancel(user_id)
    assert fake.calls[-1] == {"method": "PATCH", "path": "/subscriptions/sub_d2",
                              "body": {"cancel_at_next_billing_date": True}, "params": None}
    fake.request = fake.request  # keep the same fake
    with pytest.raises(RuntimeError):
        creator_plan_actions.portal(user_id)  # fake returns no link -> clear error
    assert fake.calls[-1]["path"] == "/customers/cus_2/customer-portal/session"


# --------------------------------------------------------------------------- #
# Paddle scaffold
# --------------------------------------------------------------------------- #
def test_paddle_signature_roundtrip(monkeypatch):
    monkeypatch.setattr(config, "paddle", {"webhook_secret": "pdl_ntfset_secret"}, raising=False)
    body = json.dumps({"event_type": "transaction.completed", "event_id": "evt_1",
                       "data": {"id": "txn_1", "custom_data": {"user_id": "u1", "kind": "pack", "plan_key": "starter"}}}).encode()
    ts = str(int(time.time()))
    sig = f"ts={ts};h1={paddle_client.sign('pdl_ntfset_secret', ts, body)}"
    event = paddle_client.verify_and_parse_webhook(body, sig)
    purchase = paddle_client.extract_completed_purchase(event)
    assert purchase["transaction_id"] == "txn_1" and purchase["plan_key"] == "starter"
    with pytest.raises(ValueError):
        paddle_client.verify_and_parse_webhook(body + b" ", sig)
    with pytest.raises(ValueError):
        paddle_client.verify_and_parse_webhook(body, f"ts={int(ts) - 3600};h1=00")


# --------------------------------------------------------------------------- #
# Catalog script stays in sync with the app catalog
# --------------------------------------------------------------------------- #
def test_create_dodo_products_matches_app_catalog():
    import importlib.util
    from pathlib import Path

    from app.services.billing import creator_plans
    from app.services.billing.plans import get_plan

    path = Path(__file__).resolve().parents[2] / "apps/api/tools/ops/create_dodo_products.py"
    spec = importlib.util.spec_from_file_location("create_dodo_products", path)
    mod = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    for key, _suffix, _name, cents, reels in mod.PACKS:
        if key == "card_check":
            assert (cents, reels) == (int(card_check.CARD_CHECK_PRICE_USD * 100), card_check.CARD_CHECK_CREDITS)
        else:
            plan = get_plan(key)
            assert (cents, reels) == (int(round(plan.price_usd * 100)), plan.credits)
    for key, _display, monthly_cents, reels in mod.PLANS:
        plan = creator_plans.get_plan(key)
        assert monthly_cents == int(round(plan.monthly_usd * 100))
        assert reels == plan.monthly_reels
    assert mod.YEARLY_MONTHS_CHARGED == creator_plans.YEARLY_MONTHS_CHARGED
    for spec_ in mod.plan_specs("mtr_1"):
        meter = spec_.price["meters"][0]
        fixed, included = spec_.price["fixed_price"], meter["free_threshold"]
        assert float(meter["price_per_unit"]) <= fixed / included  # honest overage
        assert spec_.env.startswith("DODO_PRODUCT_ID_PLAN_")


def test_other_brand_events_on_the_shared_business_are_ignored(env, monkeypatch):
    client, Factory, (user_id, _), _ = env
    monkeypatch.setitem(config.dodo, "brand_id", "brnd_menivor")
    event = _payment_event(user_id, "pdt_vcpeer_thing", payment_id="pay_other", plan_key="starter")
    event["data"]["brand_id"] = "brnd_vcpeer"
    body, headers = _signed(event)
    resp = client.post("/api/v1/billing/webhook/dodo", content=body, headers=headers)
    assert resp.status_code == 200 and resp.json()["data"]["handled"] == "other_brand"
    # Same brand but a foreign product with look-alike metadata: still ignored.
    event["data"]["brand_id"] = "brnd_menivor"
    body, headers = _signed(event, msg_id="msg_o2")
    resp = client.post("/api/v1/billing/webhook/dodo", content=body, headers=headers)
    assert resp.json()["data"]["handled"] == "ignored"
    assert _balance(Factory, user_id) == 0
