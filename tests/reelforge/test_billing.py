"""Unit + API tests for the ReelForge billing stack (Sprint 4 monetization).

Coverage:

* **Plan catalogue** (``app.services.billing.plans`` + the ``service.list_plans``
  facade): locked credit counts, purchasable/free split, lookup normalisation.
* **Idempotent fulfilment** (``service.fulfill_purchase``): a second webhook with
  the *same* provider event id grants nothing. Redis ``SETNX`` and the durable
  ledger-reason dedupe are both exercised via fakes (``_get_redis`` +
  ``CreditRepository`` + ``get_session`` monkeypatched).
* **Rate limiter** (``app.services.ratelimit``): allow under budget, deny when
  exhausted, an in-process bucket that still denies on a missing client or a
  Redis error, no limiting on a misconfiguration, plus the FastAPI ``enforce_rate_limit`` 429 helper.
* **Controller happy paths** (``app.controllers.v1.billing``): ``GET
  /billing/plans`` and ``POST /billing/checkout`` for both Stripe and iyzico,
  driven through a FastAPI ``TestClient`` with an in-memory SQLite DB and the
  provider clients monkeypatched (no network, no real SDKs, no Redis).
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "billing-testkey"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


# --------------------------------------------------------------------------- #
# Plan catalogue
# --------------------------------------------------------------------------- #
def test_plan_catalogue_has_locked_credits():
    from app.services.billing.plans import (
        FREE_KEY,
        PRO_KEY,
        SIGNUP_GRANT,
        STARTER_KEY,
        list_plans,
    )

    plans = {p.key: p for p in list_plans()}
    assert set(plans) == {FREE_KEY, STARTER_KEY, PRO_KEY}
    # Credits are contract-locked.
    assert plans[FREE_KEY].credits == SIGNUP_GRANT == 3
    assert plans[STARTER_KEY].credits == 30
    assert plans[PRO_KEY].credits == 120
    # The free signup grant is never sold; paid packs are purchasable.
    assert plans[FREE_KEY].is_purchasable is False
    assert plans[STARTER_KEY].is_purchasable is True
    assert plans[PRO_KEY].is_purchasable is True


def test_list_plans_purchasable_only_excludes_free():
    from app.services.billing.plans import FREE_KEY, list_plans

    keys = {p.key for p in list_plans(purchasable_only=True)}
    assert FREE_KEY not in keys
    assert keys == {"starter", "pro"}


def test_get_plan_normalises_and_rejects_unknown():
    from app.services.billing.plans import get_plan

    assert get_plan("  STARTER ").key == "starter"
    assert get_plan("Pro").key == "pro"
    assert get_plan("does-not-exist") is None
    assert get_plan("") is None


def test_service_list_plans_is_json_safe():
    """The service facade the controller imports returns plain dicts."""
    from app.services.billing import service

    plans = service.list_plans()
    assert isinstance(plans, list)
    assert all(isinstance(p, dict) for p in plans)
    by_key = {p["key"]: p for p in plans}
    assert by_key["pro"]["credits"] == 120
    assert by_key["starter"]["credits"] == 30
    assert by_key["free"]["is_purchasable"] is False
    # Every plan carries the fields the public schema renders.
    for plan in plans:
        assert {"key", "display_name", "credits", "price_usd"} <= set(plan)


# --------------------------------------------------------------------------- #
# Idempotent fulfilment — fakes for Redis + CreditRepository + get_session
# --------------------------------------------------------------------------- #
class _FakeRedis:
    """Minimal Redis stand-in implementing ``SETNX`` semantics for the test."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls = 0
        self.delete_calls = 0

    def set(self, name, value="1", nx=False, ex=None):
        self.set_calls += 1
        if nx and name in self.store:
            return None  # key already claimed -> SETNX fails (duplicate)
        self.store[name] = value
        return True

    def delete(self, name):
        self.delete_calls += 1
        self.store.pop(name, None)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeSession:
    """Shares the ledger state dict across every ``get_session`` in a test."""

    def __init__(self, state):
        self.state = state

    @property
    def grants(self):
        return self.state["grants"]

    @property
    def balances(self):
        return self.state["balances"]

    def execute(self, _stmt):
        # Emulates the ``_ledger_has_reason`` reason lookup.
        return _FakeResult((1,) if self.state.get("reason_exists") else None)


class _FakeCreditRepo:
    def __init__(self, session):
        self.session = session

    def grant(self, user_id, amount, reason):
        self.session.grants.append((user_id, amount, reason))
        self.session.balances[user_id] = (
            self.session.balances.get(user_id, 0) + amount
        )
        return SimpleNamespace(balance_after=self.session.balances[user_id])

    def balance(self, user_id):
        return self.session.balances.get(user_id, 0)

    # --- WF25: workspace shared-pool support -------------------------------- #
    def workspace_grant(self, workspace_id, amount, reason, actor_user_id=None):
        self.session.state.setdefault("ws_grants", []).append(
            (workspace_id, amount, reason, actor_user_id)
        )
        pool = self.session.state.setdefault("ws_balances", {})
        pool[workspace_id] = pool.get(workspace_id, 0) + amount
        return SimpleNamespace(balance_after=pool[workspace_id])

    def workspace_balance(self, workspace_id):
        return self.session.state.get("ws_balances", {}).get(workspace_id, 0)


def _install_billing_fakes(monkeypatch, redis_client, state):
    """Point the billing service at fake Redis / repo / session for one test."""
    import app.models.db.base as db_base
    import app.models.db.repositories as repo_mod
    from app.services.billing import service

    @contextmanager
    def _fake_get_session():
        yield _FakeSession(state)

    monkeypatch.setattr(service, "_get_redis", lambda: redis_client)
    monkeypatch.setattr(db_base, "get_session", _fake_get_session)
    monkeypatch.setattr(repo_mod, "CreditRepository", _FakeCreditRepo)
    return service


@pytest.fixture()
def fulfill_env(monkeypatch):
    state = {"grants": [], "balances": {}, "reason_exists": False}
    fake_redis = _FakeRedis()
    service = _install_billing_fakes(monkeypatch, fake_redis, state)
    return service, state, fake_redis


def test_fulfill_purchase_grants_once(fulfill_env):
    service, state, _ = fulfill_env

    balance = service.fulfill_purchase(
        provider="stripe",
        external_event_id="evt_1",
        user_id="user-1",
        credits=30,
        reason_ref="cs_test_1",
    )

    assert balance == 30
    assert state["grants"] == [("user-1", 30, "purchase:stripe:cs_test_1")]


def test_fulfill_purchase_is_idempotent_on_duplicate_event(fulfill_env):
    service, state, fake_redis = fulfill_env

    first = service.fulfill_purchase("stripe", "evt_dup", "user-1", 30, "cs_1")
    # Same provider event id -> SETNX loses -> grants NOTHING.
    second = service.fulfill_purchase("stripe", "evt_dup", "user-1", 30, "cs_1")

    assert first == 30
    assert second == 30  # balance unchanged
    assert len(state["grants"]) == 1  # exactly one ledger write
    assert fake_redis.set_calls == 2  # SETNX attempted on both deliveries


def test_fulfill_purchase_distinct_events_each_grant(fulfill_env):
    service, state, _ = fulfill_env

    service.fulfill_purchase("stripe", "evt_1", "user-1", 30, "cs_1")
    balance = service.fulfill_purchase("stripe", "evt_2", "user-1", 120, "cs_2")

    assert balance == 150
    assert len(state["grants"]) == 2


def test_fulfill_purchase_ledger_dedupe_when_redis_unavailable(monkeypatch):
    """Redis down -> the durable ledger-reason lookup still blocks a re-grant."""
    state = {"grants": [], "balances": {"user-9": 30}, "reason_exists": True}
    service = _install_billing_fakes(monkeypatch, None, state)

    balance = service.fulfill_purchase("iyzico", "pay_1", "user-9", 30, "pay_1")

    assert balance == 30  # returns current balance
    assert state["grants"] == []  # ledger dedupe prevented a second grant


def test_fulfill_purchase_locks_user_before_ledger_dedupe(monkeypatch):
    """Regression (TOCTOU double-grant): the User row must be locked FOR UPDATE
    *before* the ledger-reason dedupe check, so a concurrent duplicate delivery
    on the Redis-down fallback path cannot double-grant.
    """
    import app.models.db.base as db_base
    import app.models.db.repositories as repo_mod
    from app.services.billing import service

    calls: list[str] = []
    state = {"grants": [], "balances": {"user-7": 0}}

    class _OrderingResult:
        def first(self):
            return None  # no lock row / no existing reason -> proceed to grant

    class _OrderingSession:
        def __init__(self, st):
            self.state = st

        @property
        def grants(self):
            return self.state["grants"]

        @property
        def balances(self):
            return self.state["balances"]

        def execute(self, stmt):
            text = str(stmt).lower()
            if "for update" in text:
                calls.append("lock")
            elif "credit_ledger" in text:
                calls.append("dedupe")
            return _OrderingResult()

    @contextmanager
    def _fake_get_session():
        yield _OrderingSession(state)

    # Redis unavailable -> exercises the durable ledger-only fallback path.
    monkeypatch.setattr(service, "_get_redis", lambda: None)
    monkeypatch.setattr(db_base, "get_session", _fake_get_session)
    monkeypatch.setattr(repo_mod, "CreditRepository", _FakeCreditRepo)

    balance = service.fulfill_purchase("stripe", "evt_race", "user-7", 30, "cs_7")

    assert balance == 30
    assert calls[:2] == ["lock", "dedupe"]  # lock acquired before dedupe check
    assert len(state["grants"]) == 1


def test_fulfill_purchase_rejects_empty_event_id(fulfill_env):
    service, _, _ = fulfill_env
    with pytest.raises(ValueError):
        service.fulfill_purchase("stripe", "", "user-1", 30, "cs_1")


# --------------------------------------------------------------------------- #
# WF25 — workspace shared-pool fulfilment (idempotent)
# --------------------------------------------------------------------------- #
def test_fulfill_purchase_funds_workspace_pool_not_user(fulfill_env):
    """A purchase carrying a workspace_id credits the pool, never the actor."""
    service, state, _ = fulfill_env

    balance = service.fulfill_purchase(
        provider="stripe",
        external_event_id="evt_ws_1",
        user_id="admin-1",  # the funding admin (recorded for audit only)
        credits=120,
        reason_ref="cs_ws_1",
        workspace_id="ws-1",
    )

    assert balance == 120
    # Pool funded exactly once; the admin's personal ledger is untouched.
    assert state["ws_balances"] == {"ws-1": 120}
    assert state["ws_grants"] == [
        ("ws-1", 120, "purchase:stripe:cs_ws_1", "admin-1")
    ]
    assert state["grants"] == []  # no personal grant
    assert state["balances"] == {}


def test_fulfill_workspace_is_idempotent_on_duplicate_event(fulfill_env):
    """Replaying the same event id funds the workspace pool at most once."""
    service, state, fake_redis = fulfill_env

    first = service.fulfill_purchase(
        "stripe", "evt_ws_dup", "admin-1", 30, "cs_ws", workspace_id="ws-7"
    )
    # Same provider event id -> Redis SETNX loses -> grants NOTHING more.
    second = service.fulfill_purchase(
        "stripe", "evt_ws_dup", "admin-1", 30, "cs_ws", workspace_id="ws-7"
    )

    assert first == 30
    assert second == 30  # pool balance unchanged on replay
    assert len(state["ws_grants"]) == 1  # exactly one pool write
    assert fake_redis.set_calls == 2  # SETNX attempted on both deliveries


def test_fulfill_workspace_ledger_dedupe_when_redis_unavailable(monkeypatch):
    """Redis down -> the durable pool-reason lookup still blocks a re-grant."""
    state = {
        "grants": [],
        "balances": {},
        "ws_grants": [],
        "ws_balances": {"ws-9": 120},
        "reason_exists": True,  # a pool row with this reason already exists
    }
    service = _install_billing_fakes(monkeypatch, None, state)

    balance = service.fulfill_purchase(
        "stripe", "evt_ws_x", "admin-9", 120, "cs_ws_x", workspace_id="ws-9"
    )

    assert balance == 120  # returns current pool balance
    assert state["ws_grants"] == []  # ledger dedupe prevented a second grant


def test_fulfill_personal_unchanged_when_no_workspace(fulfill_env):
    """With workspace_id omitted the personal path is used, pool untouched."""
    service, state, _ = fulfill_env

    balance = service.fulfill_purchase(
        "stripe", "evt_personal", "user-1", 30, "cs_1"
    )

    assert balance == 30
    assert state["grants"] == [("user-1", 30, "purchase:stripe:cs_1")]
    assert state.get("ws_grants", []) == []
    assert state.get("ws_balances", {}) == {}


def test_handle_stripe_webhook_funds_workspace_pool_once(monkeypatch):
    """End-to-end: a completed checkout with metadata.workspace_id funds the pool
    exactly once even when the webhook is redelivered.
    """
    from app.services.billing import service, stripe_client

    state = {"grants": [], "balances": {}, "ws_grants": [], "ws_balances": {}}
    fake_redis = _FakeRedis()
    _install_billing_fakes(monkeypatch, fake_redis, state)

    event = {
        "id": "evt_hook_ws",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_hook_ws",
                "client_reference_id": "admin-42",
                "metadata": {
                    "user_id": "admin-42",
                    "plan_key": "pro",
                    "credits": "120",
                    "workspace_id": "ws-42",
                },
            }
        },
    }
    # Signature verification is out of scope here; return the parsed event.
    monkeypatch.setattr(
        stripe_client, "verify_and_parse_webhook", lambda payload, sig: event
    )

    first = service.handle_stripe_webhook(b"{}", "sig")
    second = service.handle_stripe_webhook(b"{}", "sig")  # replay

    assert first == 120
    assert second == 120  # pool unchanged on replay
    assert state["ws_balances"] == {"ws-42": 120}
    assert len(state["ws_grants"]) == 1  # granted exactly once
    assert state["grants"] == []  # personal balance never touched


def test_handle_stripe_webhook_personal_purchase_funds_user(monkeypatch):
    """A completed checkout without workspace_id still funds the user personally."""
    from app.services.billing import service, stripe_client

    state = {"grants": [], "balances": {}, "ws_grants": [], "ws_balances": {}}
    fake_redis = _FakeRedis()
    _install_billing_fakes(monkeypatch, fake_redis, state)

    event = {
        "id": "evt_hook_personal",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_hook_personal",
                "client_reference_id": "user-77",
                "metadata": {
                    "user_id": "user-77",
                    "plan_key": "starter",
                    "credits": "30",
                    # no workspace_id -> personal purchase
                },
            }
        },
    }
    monkeypatch.setattr(
        stripe_client, "verify_and_parse_webhook", lambda payload, sig: event
    )

    balance = service.handle_stripe_webhook(b"{}", "sig")

    assert balance == 30
    assert state["grants"] == [("user-77", 30, "purchase:stripe:cs_hook_personal")]
    assert state["ws_grants"] == []  # workspace pool never touched


# --------------------------------------------------------------------------- #
# WF25 — stripe_client workspace metadata plumbing
# --------------------------------------------------------------------------- #
def test_extract_completed_purchase_surfaces_workspace_id():
    from app.services.billing import stripe_client

    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_x",
                "metadata": {
                    "user_id": "admin-1",
                    "plan_key": "pro",
                    "credits": "120",
                    "workspace_id": "ws-1",
                },
            }
        },
    }

    purchase = stripe_client.extract_completed_purchase(event)
    assert purchase is not None
    assert purchase["workspace_id"] == "ws-1"
    assert purchase["user_id"] == "admin-1"
    assert purchase["credits"] == 120


def test_extract_completed_purchase_workspace_id_none_for_personal():
    from app.services.billing import stripe_client

    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_y",
                "metadata": {
                    "user_id": "user-1",
                    "plan_key": "starter",
                    "credits": "30",
                },
            }
        },
    }

    purchase = stripe_client.extract_completed_purchase(event)
    assert purchase is not None
    assert purchase["workspace_id"] is None


def test_create_checkout_session_includes_workspace_id_in_metadata(monkeypatch):
    """create_checkout_session threads workspace_id into Stripe session metadata."""
    from app.services.billing import stripe_client

    captured = {}

    class _FakeSessionObj:
        id = "cs_created"
        url = "https://checkout.stripe.com/c/pay/cs_created"

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeSessionObj()

    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(
            Session=SimpleNamespace(create=_fake_create)
        ),
    )
    monkeypatch.setattr(stripe_client, "stripe", fake_stripe)
    monkeypatch.setattr(stripe_client, "_require_secret_key", lambda: "sk_test")
    monkeypatch.setattr(
        stripe_client,
        "_stripe_config",
        lambda: {
            "success_url": "https://app/ok",
            "cancel_url": "https://app/cancel",
        },
    )

    user = {"id": "admin-1"}
    plan = SimpleNamespace(
        stripe_price_id="price_123", key="pro", credits=120
    )

    result = stripe_client.create_checkout_session(user, plan, workspace_id="ws-1")

    assert result["session_id"] == "cs_created"
    assert captured["metadata"]["workspace_id"] == "ws-1"
    assert captured["metadata"]["user_id"] == "admin-1"
    assert captured["metadata"]["credits"] == "120"


def test_create_checkout_session_subscription_mode_and_metadata(monkeypatch):
    """A recurring checkout opens mode="subscription" and threads provenance onto
    subscription_data.metadata (so the subscription webhook can recover it)."""
    from app.services.billing import stripe_client

    captured = {}

    class _FakeSessionObj:
        id = "cs_sub"
        url = "https://checkout.stripe.com/c/pay/cs_sub"

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeSessionObj()

    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=SimpleNamespace(create=_fake_create)),
    )
    monkeypatch.setattr(stripe_client, "stripe", fake_stripe)
    monkeypatch.setattr(stripe_client, "_require_secret_key", lambda: "sk_test")
    monkeypatch.setattr(
        stripe_client,
        "_stripe_config",
        lambda: {"success_url": "https://app/ok", "cancel_url": "https://app/cancel"},
    )

    user = {"id": "admin-1"}
    plan = SimpleNamespace(stripe_price_id="price_rec", key="pro", credits=120)

    stripe_client.create_checkout_session(
        user, plan, workspace_id="ws-1", subscription=True
    )

    assert captured["mode"] == "subscription"
    assert captured["subscription_data"]["metadata"]["workspace_id"] == "ws-1"
    assert captured["subscription_data"]["metadata"]["plan_key"] == "pro"
    assert captured["subscription_data"]["metadata"]["user_id"] == "admin-1"


def test_create_checkout_session_default_is_one_time_payment(monkeypatch):
    """The default (credit-pack) path stays mode="payment" with no subscription_data."""
    from app.services.billing import stripe_client

    captured = {}

    class _FakeSessionObj:
        id = "cs_ot"
        url = "https://checkout.stripe.com/c/pay/cs_ot"

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeSessionObj()

    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=SimpleNamespace(create=_fake_create)),
    )
    monkeypatch.setattr(stripe_client, "stripe", fake_stripe)
    monkeypatch.setattr(stripe_client, "_require_secret_key", lambda: "sk_test")
    monkeypatch.setattr(
        stripe_client,
        "_stripe_config",
        lambda: {"success_url": "https://app/ok", "cancel_url": "https://app/cancel"},
    )

    stripe_client.create_checkout_session(
        {"id": "user-1"}, SimpleNamespace(stripe_price_id="price_1", key="starter", credits=30)
    )

    assert captured["mode"] == "payment"
    assert "subscription_data" not in captured


def test_create_checkout_subscription_flag_reaches_stripe_client(monkeypatch):
    """service.create_checkout forwards subscription=True to the Stripe client."""
    from app.services.billing import service, stripe_client

    captured = {}

    def _fake_create_session(user, plan, workspace_id=None, *, subscription=False):
        captured["subscription"] = subscription
        captured["workspace_id"] = workspace_id
        return {"session_id": "cs_1", "checkout_url": "https://x/pay"}

    monkeypatch.setattr(stripe_client, "create_checkout_session", _fake_create_session)

    service.create_checkout(
        user_id="admin-1",
        plan_key="pro",
        provider="stripe",
        workspace_id="ws-1",
        subscription=True,
    )

    assert captured["subscription"] is True
    assert captured["workspace_id"] == "ws-1"


def test_create_checkout_session_personal_has_no_workspace_key(monkeypatch):
    """A personal checkout's metadata omits workspace_id entirely (unchanged)."""
    from app.services.billing import stripe_client

    captured = {}

    class _FakeSessionObj:
        id = "cs_p"
        url = "https://checkout.stripe.com/c/pay/cs_p"

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeSessionObj()

    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=SimpleNamespace(create=_fake_create)),
    )
    monkeypatch.setattr(stripe_client, "stripe", fake_stripe)
    monkeypatch.setattr(stripe_client, "_require_secret_key", lambda: "sk_test")
    monkeypatch.setattr(
        stripe_client,
        "_stripe_config",
        lambda: {"success_url": "https://app/ok", "cancel_url": "https://app/cancel"},
    )

    stripe_client.create_checkout_session(
        {"id": "user-1"}, SimpleNamespace(stripe_price_id="price_1", key="starter", credits=30)
    )

    assert "workspace_id" not in captured["metadata"]


def test_create_checkout_threads_workspace_id_to_stripe_client(monkeypatch):
    """service.create_checkout forwards workspace_id to the Stripe client."""
    from app.services.billing import service, stripe_client

    captured = {}

    def _fake_create_session(user, plan, workspace_id=None):
        captured["workspace_id"] = workspace_id
        return {"session_id": "cs_1", "checkout_url": "https://x/pay"}

    monkeypatch.setattr(
        stripe_client, "create_checkout_session", _fake_create_session
    )

    envelope = service.create_checkout(
        user_id="admin-1",
        plan_key="pro",
        provider="stripe",
        workspace_id="ws-1",
    )

    assert captured["workspace_id"] == "ws-1"
    assert envelope["workspace_id"] == "ws-1"


def test_create_checkout_rejects_workspace_for_non_stripe(monkeypatch):
    """Workspace-pool funding is Stripe-only; iyzico + workspace_id is rejected."""
    from app.services.billing import service

    with pytest.raises(ValueError):
        service.create_checkout(
            user_id="admin-1",
            plan_key="pro",
            provider="iyzico",
            workspace_id="ws-1",
        )


# --------------------------------------------------------------------------- #
# Rate limiter
# --------------------------------------------------------------------------- #
class _FakeRLRedis:
    def __init__(self, current, ttl=42):
        self.current = current
        self.ttl = ttl

    def eval(self, *_args):
        return [self.current, self.ttl]


def test_rate_limit_allows_under_budget(monkeypatch):
    from app.services import ratelimit

    monkeypatch.setattr(ratelimit, "_get_client", lambda: _FakeRLRedis(1, ttl=30))
    result = ratelimit.rate_limit("bucket:key", limit=5, window_s=60)

    assert result.allowed is True
    assert result.remaining == 4
    assert result.reset_s == 30


def test_rate_limit_denies_when_exhausted(monkeypatch):
    from app.services import ratelimit

    monkeypatch.setattr(ratelimit, "_get_client", lambda: _FakeRLRedis(6, ttl=15))
    result = ratelimit.rate_limit("bucket:key", limit=5, window_s=60)

    assert result.allowed is False
    assert result.remaining == 0
    assert result.reset_s == 15


def test_rate_limit_boundary_hit_is_allowed(monkeypatch):
    from app.services import ratelimit

    # current == limit is the last permitted request in the window.
    monkeypatch.setattr(ratelimit, "_get_client", lambda: _FakeRLRedis(5, ttl=9))
    result = ratelimit.rate_limit("bucket:key", limit=5, window_s=60)

    assert result.allowed is True
    assert result.remaining == 0


def test_rate_limit_without_redis_uses_in_process_bucket(monkeypatch):
    from app.services import ratelimit

    ratelimit.reset_local_buckets()
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    results = [ratelimit.rate_limit("bucket:nokey", limit=5, window_s=60) for _ in range(6)]

    assert [r.allowed for r in results] == [True] * 5 + [False]
    assert results[0].remaining == 4
    assert results[-1].remaining == 0


def test_rate_limit_denies_on_redis_error_once_budget_is_spent(monkeypatch):
    from app.services import ratelimit

    class _Boom:
        def eval(self, *_args):
            raise RuntimeError("redis exploded")

    ratelimit.reset_local_buckets()
    monkeypatch.setattr(ratelimit, "_get_client", lambda: _Boom())
    results = [ratelimit.rate_limit("bucket:boom", limit=2, window_s=60) for _ in range(3)]

    assert [r.allowed for r in results] == [True, True, False]


def test_rate_limit_in_process_window_resets(monkeypatch):
    from app.services import ratelimit

    clock = {"now": 1000.0}
    ratelimit.reset_local_buckets()
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock["now"])
    assert ratelimit.rate_limit("bucket:win", limit=1, window_s=60).allowed is True
    assert ratelimit.rate_limit("bucket:win", limit=1, window_s=60).allowed is False
    clock["now"] += 61
    assert ratelimit.rate_limit("bucket:win", limit=1, window_s=60).allowed is True


def test_rate_limit_fail_open_on_bad_config(monkeypatch):
    from app.services import ratelimit

    def _must_not_build():
        raise AssertionError("client must not be built for a bad config")

    monkeypatch.setattr(ratelimit, "_get_client", _must_not_build)
    # A non-positive limit/window is a misconfiguration -> allow, never block.
    result = ratelimit.rate_limit("bucket:key", limit=0, window_s=60)

    assert result.allowed is True


def test_enforce_rate_limit_raises_429_when_exhausted(monkeypatch):
    from app.services import ratelimit

    monkeypatch.setattr(ratelimit, "_get_client", lambda: _FakeRLRedis(6, ttl=15))
    request = SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="203.0.113.7"),
        query_params={},
    )

    with pytest.raises(HttpException) as excinfo:
        ratelimit.enforce_rate_limit(
            request, bucket="webhook:stripe", limit=5, window_s=60
        )

    assert excinfo.value.status_code == 429


def test_enforce_rate_limit_returns_result_when_allowed(monkeypatch):
    from app.services import ratelimit

    monkeypatch.setattr(ratelimit, "_get_client", lambda: _FakeRLRedis(1, ttl=30))
    request = SimpleNamespace(
        headers={"x-api-key": "abc"},
        client=SimpleNamespace(host="203.0.113.7"),
        query_params={},
    )

    result = ratelimit.enforce_rate_limit(
        request, bucket="checkout", limit=5, window_s=60
    )
    assert result.allowed is True
    assert result.remaining == 4


# --------------------------------------------------------------------------- #
# Controller happy paths (FastAPI TestClient)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def billing_client(monkeypatch):
    """Wire the billing controller to an in-memory SQLite DB (no Redis/SDKs)."""
    import app.controllers.v1.billing as billing_mod

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

    monkeypatch.setattr(billing_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(billing_mod, "_DB_IMPORT_ERROR", None)

    app = FastAPI()
    app.include_router(billing_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


def _seed_user(Factory, email="buyer@example.com") -> str:
    with Factory() as s:
        user = User(email=email, api_key_hash=_KEY_HASH, credits=0)
        s.add(user)
        s.flush()
        uid = user.id
        s.commit()
    return uid


def test_get_billing_plans_endpoint(billing_client):
    client, _ = billing_client

    resp = client.get("/api/v1/billing/plans")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    by_key = {p["key"]: p for p in data}
    assert {"free", "starter", "pro"} <= set(by_key)
    assert by_key["starter"]["credits"] == 30
    assert by_key["pro"]["credits"] == 120


def test_post_checkout_stripe_happy_path(billing_client, monkeypatch):
    client, Factory = billing_client
    _seed_user(Factory)

    from app.services.billing import stripe_client

    captured = {}

    def _fake_create_session(user, plan, workspace_id=None):
        captured["user"] = user
        captured["plan"] = plan
        captured["workspace_id"] = workspace_id
        return {
            "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_123",
            "session_id": "cs_test_123",
        }

    monkeypatch.setattr(stripe_client, "create_checkout_session", _fake_create_session)

    resp = client.post(
        "/api/v1/billing/checkout",
        json={"provider": "stripe", "plan_key": "starter"},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    assert (
        resp.json()["data"]["checkout_url"]
        == "https://checkout.stripe.com/c/pay/cs_test_123"
    )
    # The service passed the resolved buyer + Starter plan into the SDK adapter.
    assert captured["user"]["id"]
    assert captured["plan"].key == "starter"
    assert captured["plan"].credits == 30


def test_post_checkout_iyzico_happy_path(billing_client, monkeypatch):
    client, Factory = billing_client
    _seed_user(Factory, email="tr-buyer@example.com")

    from app.services.billing import iyzico_client

    def _fake_create_form(user, plan):
        return {
            "token": "tok_iyz_1",
            "payment_page_url": "https://sandbox-cpp.iyzipay.com/pay/tok_iyz_1",
            "checkout_url": "https://sandbox-cpp.iyzipay.com/pay/tok_iyz_1",
        }

    monkeypatch.setattr(iyzico_client, "create_checkout_form", _fake_create_form)

    resp = client.post(
        "/api/v1/billing/checkout",
        json={"provider": "iyzico", "plan_key": "pro"},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    assert "iyzipay.com" in resp.json()["data"]["checkout_url"]


def test_post_checkout_requires_api_key(billing_client):
    client, _ = billing_client

    resp = client.post(
        "/api/v1/billing/checkout",
        json={"provider": "stripe", "plan_key": "starter"},
    )

    assert resp.status_code == 401, resp.text


def test_post_checkout_rejects_free_plan(billing_client, monkeypatch):
    client, Factory = billing_client
    _seed_user(Factory, email="free-rejected@example.com")

    from app.services.billing import stripe_client

    # The SDK must never be reached for a non-purchasable plan.
    def _must_not_call(user, plan, workspace_id=None):  # pragma: no cover - defensive
        raise AssertionError("checkout SDK called for a non-purchasable plan")

    monkeypatch.setattr(stripe_client, "create_checkout_session", _must_not_call)

    resp = client.post(
        "/api/v1/billing/checkout",
        json={"provider": "stripe", "plan_key": "free"},
        headers=_HEADERS,
    )

    # Service raises ValueError (not purchasable) -> controller maps to 400.
    assert resp.status_code == 400, resp.text
