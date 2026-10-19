"""Workspace subscriptions v1 API tests (Enterprise Billing Platform, Epic 3).

Exercises ``app.controllers.v1.subscriptions`` end-to-end over a FastAPI
``TestClient`` with Postgres replaced by in-memory SQLite. No external I/O — the
Stripe checkout call and the webhook signature verification are monkeypatched;
the IDEMPOTENT workspace-pool grant runs for REAL against the SQLite DB (with a
fake Redis) so money-correctness is genuinely asserted.

Covered
-------
* ``subscribe`` is RBAC ``billing.manage``-gated — a ``viewer`` gets ``403`` (and
  the Stripe checkout is never reached); an ``owner`` gets a checkout url.
* the subscription webhook is IDEMPOTENT — a DUPLICATE POST of the same provider
  event funds the workspace pool exactly once and BOTH deliveries return ``200``.
* ``cancel`` flips the subscription to ``canceled`` (``billing.manage``-gated);
  ``get`` is tenant-scoped (a caller from workspace B cannot read A's subscription).
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.subscriptions as sub_mod
from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.db.repositories import CreditRepository, SubscriptionRepository
from app.models.exception import HttpException
from app.utils import utils


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


class _FakeRedis:
    """SETNX-semantics fake so the shared idempotent grant dedupes deterministically."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, name, value="1", nx=False, ex=None):
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    def delete(self, name):
        self.store.pop(name, None)


@pytest.fixture()
def env(monkeypatch):
    """Shared SQLite + patched sessions + fake Redis + bypassed Stripe verify."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # The controller's session AND the webhook's internal grant session both point
    # at the SAME SQLite DB so a seeded workspace is visible to both.
    import app.models.db.base as db_base
    from app.services.billing import service as billing_service
    from app.services.billing import stripe_client

    monkeypatch.setattr(sub_mod, "get_session", _fake_get_session)
    # Subscription checkout is launch-gated; these tests exercise the open gate.
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "public")
    monkeypatch.setenv("REELFORGE_PUBLIC_LAUNCH_APPROVED", "true")
    monkeypatch.setenv("REELFORGE_CHECKOUT_ENABLED", "true")
    monkeypatch.setattr(db_base, "get_session", _fake_get_session)
    fake_redis = _FakeRedis()
    monkeypatch.setattr(billing_service, "_get_redis", lambda: fake_redis)

    app = FastAPI()
    app.include_router(sub_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory, fake_redis, monkeypatch, stripe_client


@pytest.fixture()
def seeded(env):
    """Two workspaces A/B: owner (billing.manage), viewer (no billing.manage)."""
    _, Factory, *_ = env
    out: dict[str, str] = {}
    with Factory() as s:
        owner_a = User(email="ownerA@ex.com", api_key_hash=_key_hash("ownerA-key"))
        viewer_a = User(email="viewerA@ex.com", api_key_hash=_key_hash("viewerA-key"))
        owner_b = User(email="ownerB@ex.com", api_key_hash=_key_hash("ownerB-key"))
        s.add_all([owner_a, viewer_a, owner_b])
        s.flush()
        ws_a = Workspace(owner_id=owner_a.id, name="Acme-A")
        ws_b = Workspace(owner_id=owner_b.id, name="Beta-B")
        s.add_all([ws_a, ws_b])
        s.flush()
        s.add_all(
            [
                WorkspaceMember(workspace_id=ws_a.id, user_id=owner_a.id, role="owner"),
                WorkspaceMember(workspace_id=ws_a.id, user_id=viewer_a.id, role="viewer"),
                WorkspaceMember(workspace_id=ws_b.id, user_id=owner_b.id, role="owner"),
            ]
        )
        s.commit()
        out = {
            "ws_a": ws_a.id,
            "ws_b": ws_b.id,
            "owner_a_id": owner_a.id,
            "owner_a_key": "ownerA-key",
            "viewer_a_key": "viewerA-key",
            "owner_b_key": "ownerB-key",
        }
    return out


def _sub_event(event_id: str, ws_id: str, user_id: str, plan_key: str = "pro"):
    return {
        "id": event_id,
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_api_1",
                "status": "active",
                "current_period_end": None,
                "metadata": {
                    "workspace_id": ws_id,
                    "plan_key": plan_key,
                    "user_id": user_id,
                },
            }
        },
    }


# --------------------------------------------------------------------------- #
# subscribe — RBAC billing.manage gated
# --------------------------------------------------------------------------- #
def test_subscribe_viewer_forbidden_403(env, seeded):
    client, *_ = env
    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/subscribe",
        json={"plan_key": "pro", "interval": "month", "seats": 3},
        headers=_headers(seeded["viewer_a_key"]),
    )
    assert resp.status_code == 403, resp.text


def test_subscribe_owner_returns_checkout_url(env, seeded):
    client, _, _, monkeypatch, _ = env

    def _fake_create_subscription(*, workspace_id, user_id, plan_key, user_email="", provider="stripe", **_extra):
        return {
            "provider": provider,
            "plan_key": plan_key,
            "credits": 120,
            "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_api",
            "reference": "cs_test_api",
            "workspace_id": workspace_id,
        }

    monkeypatch.setattr(
        sub_mod.subscriptions_service, "create_subscription", _fake_create_subscription
    )
    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/subscribe",
        json={"plan_key": "pro", "interval": "month", "seats": 5},
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["checkout_url"].startswith("https://checkout.stripe.com/")


def test_subscribe_closed_in_pilot_403(env, seeded):
    """A workspace subscription is a paid checkout: closed during the pilot."""
    client, _, _, monkeypatch, _ = env
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "internal_pilot")
    monkeypatch.delenv("REELFORGE_PILOT_STAFF", raising=False)
    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/subscribe",
        json={"plan_key": "pro", "interval": "month", "seats": 3},
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["data"]["code"] == "checkout_closed"


def test_subscribe_pilot_staff_override_resolves_the_real_principal(env, seeded):
    """Pilot staff (by email) pass the closed checkout gate; others still get 403."""
    from app.core.launch.policy import LaunchRequestScopeMiddleware

    client, _, _, monkeypatch, _ = env
    client.app.add_middleware(LaunchRequestScopeMiddleware)
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "internal_pilot")
    monkeypatch.setenv("REELFORGE_PILOT_STAFF", "ownera@ex.com")

    def _fake_create_subscription(**kwargs):
        return {"provider": "stripe", "plan_key": kwargs["plan_key"], "credits": 120,
                "checkout_url": "https://checkout.stripe.com/c/pay/cs_staff", "reference": "cs_staff",
                "workspace_id": kwargs["workspace_id"]}

    monkeypatch.setattr(sub_mod.subscriptions_service, "create_subscription", _fake_create_subscription)
    body = {"plan_key": "pro", "interval": "month", "seats": 3}
    staff = client.post(f"/api/v1/me/workspaces/{seeded['ws_a']}/subscribe", json=body,
                        headers=_headers(seeded["owner_a_key"]))
    assert staff.status_code == 200, staff.text
    other = client.post(f"/api/v1/me/workspaces/{seeded['ws_b']}/subscribe", json=body,
                        headers=_headers("ownerB-key"))
    assert other.status_code == 403, other.text
    assert other.json()["data"]["code"] == "checkout_closed"


def test_subscribe_requires_auth_401(env, seeded):
    client, *_ = env
    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/subscribe",
        json={"plan_key": "pro"},
    )
    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------- #
# webhook — IDEMPOTENT (duplicate grants once; both 200)
# --------------------------------------------------------------------------- #
def test_webhook_duplicate_grants_once_both_200(env, seeded):
    client, Factory, _, monkeypatch, stripe_client = env
    event = _sub_event("evt_api_dup", seeded["ws_a"], seeded["owner_a_id"], "pro")
    monkeypatch.setattr(
        stripe_client, "verify_and_parse_webhook", lambda payload, sig: event
    )

    first = client.post(
        "/api/v1/webhooks/billing/subscription",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )
    second = client.post(
        "/api/v1/webhooks/billing/subscription",
        content=b"{}",
        headers={"Stripe-Signature": "sig"},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    # Funded EXACTLY once despite two deliveries (pro = 120 monthly credits).
    with Factory() as s:
        assert CreditRepository(s).workspace_balance(seeded["ws_a"]) == 120
        sub = SubscriptionRepository(s).get_for_workspace(seeded["ws_a"])
        assert sub is not None and sub.status == "active" and sub.plan_key == "pro"


def test_webhook_bad_signature_400(env, seeded):
    client, _, _, monkeypatch, stripe_client = env

    def _raise(payload, sig):
        raise ValueError("Stripe webhook signature verification failed")

    monkeypatch.setattr(stripe_client, "verify_and_parse_webhook", _raise)
    resp = client.post(
        "/api/v1/webhooks/billing/subscription",
        content=b"{}",
        headers={"Stripe-Signature": "bad"},
    )
    assert resp.status_code == 400, resp.text


# --------------------------------------------------------------------------- #
# cancel + get (tenant-scoped)
# --------------------------------------------------------------------------- #
def test_cancel_flips_status_to_canceled(env, seeded):
    client, Factory, *_ = env
    # Seed an active subscription for A directly.
    with Factory() as s:
        SubscriptionRepository(s).upsert(
            seeded["ws_a"], plan_key="pro", provider="stripe", status="active"
        )
        s.commit()

    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/cancel",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "canceled"


def test_cancel_viewer_forbidden_403(env, seeded):
    client, Factory, *_ = env
    with Factory() as s:
        SubscriptionRepository(s).upsert(seeded["ws_a"], plan_key="pro", status="active")
        s.commit()
    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/cancel",
        headers=_headers(seeded["viewer_a_key"]),
    )
    assert resp.status_code == 403, resp.text


def test_get_subscription_is_tenant_scoped(env, seeded):
    client, Factory, *_ = env
    with Factory() as s:
        SubscriptionRepository(s).upsert(seeded["ws_a"], plan_key="pro", status="active")
        s.commit()

    # Owner of B cannot read A's subscription (not a member -> 403).
    foreign = client.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/subscription",
        headers=_headers(seeded["owner_b_key"]),
    )
    assert foreign.status_code == 403, foreign.text

    # Owner of A can read it.
    own = client.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/subscription",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert own.status_code == 200, own.text
    assert own.json()["data"]["plan_key"] == "pro"


def test_change_plan_owner_updates(env, seeded):
    client, Factory, _, monkeypatch, _ = env
    # A verified, provider-backed subscription already exists (Stripe confirmed),
    # so switching between paid tiers is a benign proration. The provider-side
    # switch is faked (no live Stripe call).
    from app.services.billing import subscription_providers

    switched: list[tuple] = []
    monkeypatch.setattr(
        subscription_providers, "change_plan",
        lambda provider, ref, **kw: switched.append((provider, ref, kw["plan"].key)),
    )
    with Factory() as s:
        SubscriptionRepository(s).upsert(
            seeded["ws_a"], plan_key="pro", provider="stripe",
            provider_ref="sub_live", status="active",
        )
        s.commit()
    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/change-plan",
        json={"plan_key": "starter"},
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["plan_key"] == "starter"
    assert switched == [("stripe", "sub_live", "starter")]


def test_change_plan_paid_without_subscription_402(env, seeded):
    """Entitlement-bypass guard: an owner cannot self-upgrade a free workspace to a
    paid plan without a verified Stripe subscription — returns 402 (Payment
    Required), and no entitlement is granted."""
    client, Factory, *_ = env
    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/change-plan",
        json={"plan_key": "enterprise"},
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 402, resp.text
    with Factory() as s:
        assert SubscriptionRepository(s).get_for_workspace(seeded["ws_a"]) is None


def test_change_plan_unknown_plan_400(env, seeded):
    client, *_ = env
    resp = client.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/change-plan",
        json={"plan_key": "galaxy"},
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 400, resp.text
