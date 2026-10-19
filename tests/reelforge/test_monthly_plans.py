"""Personal monthly plans (Creator / Pro / Agency) on Creem.

Real SQLite ledger + real billing service; only Creem HTTP and Redis are faked.

* Catalog: every plan beats the best pack per reel; annual = 10 months; a plan
  is only offered once its Creem product id is configured.
* Checkout opens the recurring product; 409 while a plan is live.
* The signed redirect activates the plan and grants the first period ONCE; the
  webhooks of the same period grant nothing more.
* Renewal expires the unused included reels of the previous period (never pack
  credits) and grants the new period once. Included reels are used first.
* A canceled subscription is terminal; ``subscription.expired`` expires leftovers.
* One-click cancel (scheduled at Creem), portal link, upgrade tops up once.
* Pack and workspace-subscription webhooks are not captured by this module.
* The create-products script is recurring, dry-run by default, and in sync.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.billing as billing_mod
import app.controllers.v1.monthly_plans as monthly_mod
import app.models.db.base as db_base
from app.config import config
from app.models.db.base import Base
from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.models import CreditLedger, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services.billing import (
    creator_creem,
    creator_plan_actions,
    creator_plans,
    creem_client,
    service,
)
from app.utils import utils

API_KEY = "creem_test_key_for_signing"
WEBHOOK_SECRET = "whsec_plans_test"
PRODUCTS = {
    "plan_creator_month_product_id": "prod_creator_m",
    "plan_creator_year_product_id": "prod_creator_y",
    "plan_pro_month_product_id": "prod_pro_m",
    "plan_pro_year_product_id": "prod_pro_y",
    "plan_agency_month_product_id": "prod_agency_m",
}
STARTER_PRODUCT = "prod_starter_1"
PERIOD_1 = datetime(2026, 10, 25, tzinfo=timezone.utc)
PERIOD_2 = datetime(2026, 11, 25, tzinfo=timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FakeCreem:
    def __init__(self) -> None:
        self.subscriptions: dict[str, dict] = {}
        self.checkouts: list[dict] = []
        self.canceled: list[str] = []
        self.changes: list[tuple[str, str, bool]] = []

    def open_checkout(self, *, user_id, user_email, plan, interval):
        self.checkouts.append(
            {"user_id": user_id, "email": user_email, "plan": plan.key, "interval": interval,
             "product": creator_plans.product_id(plan.key, interval)}
        )
        return {"checkout_url": "https://checkout.creem.io/ch_sub", "session_id": "ch_sub"}

    def fetch_subscription(self, sub_id):
        return self.subscriptions[sub_id]

    def cancel(self, sub_id):
        self.canceled.append(sub_id)
        return "scheduled"

    def change_product(self, sub_id, product_id, *, upgrade):
        self.changes.append((sub_id, product_id, upgrade))

    def portal_link(self, customer_id):
        return f"https://creem.io/portal/{customer_id}"


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
    monkeypatch.setattr(monthly_mod, "require_checkout_enabled", lambda _rid: None)
    monkeypatch.setattr(
        config,
        "creem",
        {
            "api_key": API_KEY,
            "webhook_secret": WEBHOOK_SECRET,
            "starter_product_id": STARTER_PRODUCT,
            "web_base_url": "https://menivor.com",
            **PRODUCTS,
        },
        raising=False,
    )
    fake = FakeCreem()
    for name in ("open_checkout", "fetch_subscription", "cancel", "change_product", "portal_link"):
        monkeypatch.setattr(creator_creem, name, getattr(fake, name))

    app = FastAPI()
    app.include_router(billing_mod.router)
    app.include_router(monthly_mod.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _handler)

    with _session() as s:
        user = User(email="plan@example.com", display_name="Plan", api_key_hash=_hash("rk_plan"))
        s.add(user)
        s.flush()
        user_id = user.id
    return TestClient(app), Factory, user_id, fake


AUTH = {"x-api-key": "rk_plan"}


def _balance(Factory, user_id: str) -> int:
    with Factory() as s:
        return CreditRepository(s).balance(user_id)


def _debit(Factory, user_id: str, amount: int, job: str = "") -> None:
    with Factory() as s:
        CreditRepository(s).debit(user_id, amount, None, "job_debit")
        s.commit()


def _webhook(event: dict) -> None:
    body = json.dumps(event).encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    service.handle_creem_webhook(body, sig)


def _sub_event(event_type: str, user_id: str, *, period_end: datetime, status: str = "active",
               sub_id: str = "sub_1", product: str = "prod_creator_m", event_id: str = "") -> dict:
    return {
        "id": event_id or f"evt_{event_type}_{int(period_end.timestamp())}",
        "eventType": event_type,
        "object": {
            "id": sub_id,
            "object": "subscription",
            "status": status,
            "product": {"id": product},
            "customer": {"id": "cust_1"},
            "current_period_end_date": period_end.isoformat(),
            "metadata": {"kind": "creator_plan", "user_id": user_id, "plan_key": "creator",
                         "interval": "month"},
        },
    }


def _confirm(client, user_id: str, *, product: str = "prod_creator_m", sub_id: str = "sub_1"):
    pairs = [
        ("checkout_id", "ch_sub"),
        ("order_id", "ord_sub"),
        ("customer_id", "cust_1"),
        ("subscription_id", sub_id),
        ("product_id", product),
        ("request_id", user_id),
    ]
    sig = creem_client._redirect_digest(pairs, API_KEY)
    query = urlencode([("checkout", "return"), *pairs, ("signature", sig)])
    return client.post("/api/v1/billing/creem/confirm", json={"query": query})


def _activate(client, fake, user_id: str, period_end: datetime = PERIOD_1):
    fake.subscriptions["sub_1"] = {
        "id": "sub_1", "status": "active", "product": {"id": "prod_creator_m"},
        "customer": {"id": "cust_1"}, "current_period_end_date": period_end.isoformat(),
    }
    resp = _confirm(client, user_id)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def test_every_plan_beats_the_best_pack_per_reel():
    best = creator_plans.best_pack_per_reel_usd()
    assert best == pytest.approx(59 / 120, abs=1e-3)
    for plan in creator_plans.list_plans():
        for interval in creator_plans.INTERVALS:
            assert plan.per_reel_usd(interval) < best, (plan.key, interval)
        assert plan.yearly_usd == pytest.approx(plan.monthly_usd * 10)
        assert plan.period_credits("year") == plan.monthly_reels * 12
    ranks = [p.per_reel_usd("month") for p in creator_plans.list_plans()]
    assert ranks == sorted(ranks, reverse=True)


def test_catalog_offers_only_configured_products(env):
    client, *_ = env
    data = client.get("/api/v1/billing/monthly-plans").json()["data"]
    rows = {row["plan_key"]: row for row in data["plans"]}
    assert set(rows) == {"creator", "pro", "agency"}
    assert rows["creator"]["monthly_cents"] == 1500
    assert rows["creator"]["available"] == {"month": True, "year": True}
    assert rows["agency"]["available"] == {"month": True, "year": False}
    assert data["best_pack_per_reel_cents"] == 49


# --------------------------------------------------------------------------- #
# Checkout + signed redirect
# --------------------------------------------------------------------------- #
def test_checkout_opens_the_recurring_product(env):
    client, _, user_id, fake = env
    resp = client.post(
        "/api/v1/billing/monthly-plan/checkout", json={"plan_key": "pro", "interval": "year"},
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["checkout_url"].startswith("https://checkout.creem.io/")
    assert fake.checkouts[-1] == {
        "user_id": user_id, "email": "plan@example.com", "plan": "pro", "interval": "year",
        "product": "prod_pro_y",
    }


def test_checkout_rejects_bad_input_and_requires_auth(env):
    client, *_ = env
    assert client.post("/api/v1/billing/monthly-plan/checkout", json={"plan_key": "pro"}).status_code == 401
    bad = client.post("/api/v1/billing/monthly-plan/checkout", json={"plan_key": "gold"}, headers=AUTH)
    assert bad.status_code == 400
    bad_interval = client.post(
        "/api/v1/billing/monthly-plan/checkout", json={"plan_key": "pro", "interval": "week"},
        headers=AUTH,
    )
    assert bad_interval.status_code == 400


def test_redirect_activates_and_grants_first_period_once(env):
    client, Factory, user_id, fake = env
    data = _activate(client, fake, user_id)
    assert data["plan_key"] == "creator"
    assert data["credits"] == 35
    assert _balance(Factory, user_id) == 35

    # Refresh of the return page + every webhook of the same period: no double grant.
    assert _confirm(client, user_id).status_code == 200
    for event_type in ("checkout.completed", "subscription.active", "subscription.paid"):
        _webhook(_sub_event(event_type, user_id, period_end=PERIOD_1))
    assert _balance(Factory, user_id) == 35

    status = client.get("/api/v1/billing/monthly-plan", headers=AUTH).json()["data"]
    assert status["plan"]["plan_key"] == "creator"
    assert status["renews"] is True
    assert status["included_left"] == 35
    assert status["current_period_end"].startswith("2026-10-25")
    assert status["recommended_plan"] == "pro"

    again = client.post(
        "/api/v1/billing/monthly-plan/checkout", json={"plan_key": "pro"}, headers=AUTH
    )
    assert again.status_code == 409


def test_webhook_alone_activates_the_plan(env):
    _, Factory, user_id, _ = env
    _webhook(_sub_event("subscription.paid", user_id, period_end=PERIOD_1))
    assert _balance(Factory, user_id) == 35
    with Factory() as s:
        row = s.execute(select(CreatorSubscription)).scalars().one()
        assert (row.plan_key, row.status, row.customer_ref) == ("creator", "active", "cust_1")


# --------------------------------------------------------------------------- #
# Renewal: no rollover, packs untouched
# --------------------------------------------------------------------------- #
def test_renewal_expires_unused_included_reels_but_keeps_pack_credits(env):
    client, Factory, user_id, fake = env
    _activate(client, fake, user_id)
    service.fulfill_purchase(
        provider="creem", external_event_id="pack_1", user_id=user_id, credits=30, reason_ref="pack_1"
    )
    _debit(Factory, user_id, 5)  # 5 reels made: taken from the included reels first
    assert _balance(Factory, user_id) == 60

    _webhook(_sub_event("subscription.paid", user_id, period_end=PERIOD_2))
    # 30 unused included reels expired, 30 pack credits kept, 35 new included reels.
    assert _balance(Factory, user_id) == 30 + 35
    # Redelivery of the renewal: nothing changes.
    _webhook(_sub_event("subscription.paid", user_id, period_end=PERIOD_2, event_id="evt_dup"))
    assert _balance(Factory, user_id) == 65
    with Factory() as s:
        reasons = [r for (r,) in s.execute(select(CreditLedger.reason)).all()]
    assert sum(1 for r in reasons if r.startswith("plan_expire:")) == 1


def test_usage_beyond_included_reels_comes_from_packs_and_nothing_expires(env):
    client, Factory, user_id, fake = env
    _activate(client, fake, user_id)
    service.fulfill_purchase(
        provider="creem", external_event_id="pack_2", user_id=user_id, credits=30, reason_ref="pack_2"
    )
    _debit(Factory, user_id, 40)
    _webhook(_sub_event("subscription.paid", user_id, period_end=PERIOD_2))
    assert _balance(Factory, user_id) == 25 + 35


def test_missed_renewal_webhook_is_self_healed_on_status(env):
    client, Factory, user_id, fake = env
    past = datetime.now(timezone.utc) - timedelta(days=1)
    _activate(client, fake, user_id, period_end=past)
    fake.subscriptions["sub_1"]["current_period_end_date"] = (past + timedelta(days=30)).isoformat()
    status = client.get("/api/v1/billing/monthly-plan", headers=AUTH).json()["data"]
    assert status["credits"] == 35  # old 35 expired, new 35 granted
    with Factory() as s:
        reasons = [r for (r,) in s.execute(select(CreditLedger.reason)).all()]
    assert sum(1 for r in reasons if r.startswith("plan_expire:")) == 1


# --------------------------------------------------------------------------- #
# Cancel, expiry, terminal state
# --------------------------------------------------------------------------- #
def test_one_click_cancel_turns_renewal_off_and_keeps_reels(env):
    client, Factory, user_id, fake = env
    _activate(client, fake, user_id)
    resp = client.post("/api/v1/billing/monthly-plan/cancel", headers=AUTH)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert fake.canceled == ["sub_1"]
    assert data["renews"] is False and data["cancel_at_period_end"] is True
    assert data["plan"]["plan_key"] == "creator"
    assert _balance(Factory, user_id) == 35


def test_expired_subscription_expires_leftover_and_late_active_is_ignored(env):
    client, Factory, user_id, fake = env
    _activate(client, fake, user_id)
    _debit(Factory, user_id, 10)
    _webhook(_sub_event("subscription.expired", user_id, period_end=PERIOD_1, status="expired"))
    assert _balance(Factory, user_id) == 0
    _webhook(_sub_event("subscription.active", user_id, period_end=PERIOD_2, event_id="late"))
    assert _balance(Factory, user_id) == 0
    status = client.get("/api/v1/billing/monthly-plan", headers=AUTH).json()["data"]
    assert status["plan"] is None and status["status"] == "canceled"


def test_cancel_and_portal_without_a_plan(env):
    client, *_ = env
    assert client.post("/api/v1/billing/monthly-plan/cancel", headers=AUTH).status_code == 404
    assert client.post("/api/v1/billing/monthly-plan/portal", headers=AUTH).status_code == 404
    status = client.get("/api/v1/billing/monthly-plan", headers=AUTH).json()["data"]
    assert status["plan"] is None and status["low_credits"] is True
    assert status["recommended_plan"] == "creator"


def test_status_counts_only_finished_renders(env):
    from app.models import const
    from app.models.db.models import Job

    client, Factory, user_id, _ = env
    status = client.get("/api/v1/billing/monthly-plan", headers=AUTH).json()["data"]
    assert status["reels_rendered"] == 0
    with Factory() as s:
        for state in (const.TASK_STATE_COMPLETE, const.TASK_STATE_COMPLETE,
                      const.TASK_STATE_FAILED, const.TASK_STATE_PROCESSING):
            s.add(Job(user_id=user_id, state=state))
        s.commit()
    status = client.get("/api/v1/billing/monthly-plan", headers=AUTH).json()["data"]
    assert status["reels_rendered"] == 2


def test_portal_link(env):
    client, _, user_id, fake = env
    _activate(client, fake, user_id)
    resp = client.post("/api/v1/billing/monthly-plan/portal", headers=AUTH)
    assert resp.json()["data"]["url"] == "https://creem.io/portal/cust_1"


def test_upgrade_charges_at_creem_and_tops_up_once(env):
    client, Factory, user_id, fake = env
    _activate(client, fake, user_id)
    resp = client.post("/api/v1/billing/monthly-plan/change", json={"plan_key": "pro"}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    assert fake.changes == [("sub_1", "prod_pro_m", True)]
    assert _balance(Factory, user_id) == 100
    assert resp.json()["data"]["included_left"] == 100
    # Same change again: no-op.
    client.post("/api/v1/billing/monthly-plan/change", json={"plan_key": "pro"}, headers=AUTH)
    assert _balance(Factory, user_id) == 100


# --------------------------------------------------------------------------- #
# Other flows untouched
# --------------------------------------------------------------------------- #
def test_pack_webhook_still_grants_the_pack(env):
    _, Factory, user_id, _ = env
    _webhook(
        {
            "id": "evt_pack",
            "eventType": "checkout.completed",
            "object": {
                "id": "ch_pack",
                "product": {"id": STARTER_PRODUCT},
                "metadata": {"user_id": user_id, "plan_key": "starter", "credits": "30"},
            },
        }
    )
    assert _balance(Factory, user_id) == 30
    with Factory() as s:
        assert s.execute(select(CreatorSubscription)).first() is None


def test_workspace_subscription_events_are_not_captured():
    from app.services.billing import creator_subscriptions

    event = {
        "eventType": "subscription.paid",
        "object": {"id": "sub_ws", "product": {"id": "prod_team"},
                   "metadata": {"kind": "subscription", "workspace_id": "w1"}},
    }
    assert creator_subscriptions.parse_creem_event(event) is None


@pytest.mark.parametrize(
    ("current", "used", "expected"),
    [(None, 0, "creator"), (None, 60, "pro"), (None, 1000, "agency"), ("pro", 0, "agency"),
     ("agency", 0, None)],
)
def test_recommendation(current, used, expected):
    assert creator_plan_actions.recommend(current, used) == expected


# --------------------------------------------------------------------------- #
# Ops script
# --------------------------------------------------------------------------- #
def _script():
    path = (
        Path(__file__).resolve().parents[2]
        / "apps/api/tools/ops/create_creem_subscription_products.py"
    )
    spec = importlib.util.spec_from_file_location("create_creem_subscription_products", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def test_products_script_matches_catalog_and_is_recurring():
    script = _script()
    by_env = {p.env: p for p in script.PRODUCTS}
    assert len(by_env) == 6
    for plan in creator_plans.list_plans():
        for interval, period in (("month", "every-month"), ("year", "every-year")):
            product = by_env[creator_plans.env_name(plan.key, interval)]
            assert product.price_cents == round(plan.price_usd(interval) * 100)
            body = script.product_body(product)
            assert body["billing_type"] == "recurring"
            assert body["billing_period"] == period
            assert str(plan.period_credits(interval)) in product.description


def test_products_script_dry_run_by_default(monkeypatch, capsys):
    script = _script()
    monkeypatch.setattr(script, "create_product", lambda *a, **k: pytest.fail("must not call Creem"))
    assert script.main([]) == 0
    out = capsys.readouterr().out
    assert out.count("[dry-run]") == 6
    assert "CREEM_PRODUCT_ID_PLAN_AGENCY_YEAR" in out
