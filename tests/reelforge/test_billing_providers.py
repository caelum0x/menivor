"""Creem + Polar payment-provider wiring tests (WF26).

Covers the *service dispatch* and *webhook fulfilment* paths this agent wired for
the two new merchant-of-record providers (Creem + Polar), alongside the existing
Stripe/iyzico rails. Everything runs over a FastAPI ``TestClient`` with:

* the persistence layer replaced by in-memory SQLite (checkout) or an in-memory
  fake ledger (webhooks) — no real DB,
* the provider *clients* either monkeypatched (checkout dispatch) or driven with
  REAL signed payloads verified by the real client code (webhooks),
* Redis replaced by a ``SETNX``-honouring fake.

No network and no real SDKs are touched.

Scenarios
---------
* ``POST /billing/checkout`` with ``provider="creem"`` / ``"polar"`` dispatches to
  the matching client and returns its hosted ``checkout_url``.
* an unknown provider is rejected at the boundary with ``400`` (client untouched).
* a correctly-signed Creem / Polar webhook fulfils exactly once; a replay of the
  same event grants nothing more (idempotent) and never 500s.
* a workspace-tagged Creem / Polar purchase funds the SHARED pool, not the actor.
* ``GET /billing/providers`` lists only the providers whose secrets are configured.
* a tampered Creem signature is rejected with ``400``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.billing as billing_mod
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "providers-testkey"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

_CREEM_SECRET = "whsec_creem_test_123"
_POLAR_SECRET = "whsec_" + base64.b64encode(b"polar-signing-key").decode("utf-8")


# --------------------------------------------------------------------------- #
# In-memory fakes for the ledger + Redis (shared with the webhook tests)
# --------------------------------------------------------------------------- #
class _FakeRedis:
    """Minimal Redis stand-in implementing ``SETNX`` semantics."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls = 0

    def set(self, name, value="1", nx=False, ex=None):
        self.set_calls += 1
        if nx and name in self.store:
            return None  # key already claimed -> duplicate
        self.store[name] = value
        return True

    def delete(self, name):
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

    def workspace_grant(self, workspace_id, amount, reason, actor_user_id=None):
        self.session.state.setdefault("ws_grants", []).append(
            (workspace_id, amount, reason, actor_user_id)
        )
        pool = self.session.state.setdefault("ws_balances", {})
        pool[workspace_id] = pool.get(workspace_id, 0) + amount
        return SimpleNamespace(balance_after=pool[workspace_id])

    def workspace_balance(self, workspace_id):
        return self.session.state.get("ws_balances", {}).get(workspace_id, 0)


def _install_ledger_fakes(monkeypatch, redis_client, state):
    """Point the billing service at the fake Redis / repo / session."""
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


# --------------------------------------------------------------------------- #
# App / client fixtures
# --------------------------------------------------------------------------- #
def _build_client(monkeypatch):
    """Billing router wired to an in-memory SQLite DB (real ``get_session``)."""
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


@pytest.fixture()
def client(monkeypatch):
    return _build_client(monkeypatch)


def _seed_user(Factory, email="provider-buyer@example.com") -> str:
    with Factory() as s:
        user = User(email=email, api_key_hash=_KEY_HASH, credits=0)
        s.add(user)
        s.flush()
        uid = user.id
        s.commit()
    return uid


# --------------------------------------------------------------------------- #
# Checkout dispatch — provider -> matching client
# --------------------------------------------------------------------------- #
def test_checkout_dispatches_to_creem_client(client, monkeypatch):
    api_client, Factory = client
    _seed_user(Factory)

    from app.services.billing import creem_client

    captured: dict[str, Any] = {}

    def _fake_create_session(user, plan, workspace_id=None):
        captured["user"] = user
        captured["plan"] = plan
        captured["workspace_id"] = workspace_id
        return {
            "checkout_url": "https://creem.io/checkout/ch_test_1",
            "session_id": "ch_test_1",
        }

    monkeypatch.setattr(creem_client, "create_checkout_session", _fake_create_session)

    resp = api_client.post(
        "/api/v1/billing/checkout",
        json={"provider": "creem", "plan_key": "starter"},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    assert (
        resp.json()["data"]["checkout_url"]
        == "https://creem.io/checkout/ch_test_1"
    )
    assert captured["user"]["id"]
    assert captured["plan"].key == "starter"
    assert captured["plan"].credits == 30
    assert captured["workspace_id"] is None


def test_checkout_dispatches_to_polar_client(client, monkeypatch):
    api_client, Factory = client
    _seed_user(Factory, email="polar-buyer@example.com")

    from app.services.billing import polar_client

    captured: dict[str, Any] = {}

    def _fake_create_session(user, plan, workspace_id=None):
        captured["plan"] = plan
        captured["workspace_id"] = workspace_id
        return {
            "checkout_url": "https://polar.sh/checkout/co_test_1",
            "session_id": "co_test_1",
        }

    monkeypatch.setattr(polar_client, "create_checkout_session", _fake_create_session)

    resp = api_client.post(
        "/api/v1/billing/checkout",
        json={"provider": "polar", "plan_key": "pro"},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    assert (
        resp.json()["data"]["checkout_url"]
        == "https://polar.sh/checkout/co_test_1"
    )
    assert captured["plan"].key == "pro"
    assert captured["plan"].credits == 120
    assert captured["workspace_id"] is None


def test_checkout_unknown_provider_is_400(client, monkeypatch):
    api_client, Factory = client
    _seed_user(Factory, email="stranger-provider@example.com")

    # Neither new client should ever be reached for an unknown provider.
    from app.services.billing import creem_client, polar_client

    def _must_not_call(*_a, **_k):  # pragma: no cover - defensive
        raise AssertionError("provider client called for an unknown provider")

    monkeypatch.setattr(creem_client, "create_checkout_session", _must_not_call)
    monkeypatch.setattr(polar_client, "create_checkout_session", _must_not_call)

    resp = api_client.post(
        "/api/v1/billing/checkout",
        json={"provider": "paypal", "plan_key": "starter"},
        headers=_HEADERS,
    )

    assert resp.status_code == 400, resp.text


# --------------------------------------------------------------------------- #
# Creem webhook — signed, idempotent, workspace-aware
# --------------------------------------------------------------------------- #
def _creem_sign(body: bytes, secret: str = _CREEM_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post_creem(api_client, body: bytes, signature: str):
    return api_client.post(
        "/api/v1/billing/webhook/creem",
        content=body,
        headers={"creem-signature": signature, "Content-Type": "application/json"},
    )


def _install_creem_secret(monkeypatch):
    from app.services.billing import creem_client

    monkeypatch.setattr(
        creem_client, "_creem_config", lambda: {"webhook_secret": _CREEM_SECRET}
    )


def test_creem_webhook_fulfills_once_then_replay_no_double(client, monkeypatch):
    api_client, _Factory = client
    state = {"grants": [], "balances": {}, "reason_exists": False}
    fake_redis = _FakeRedis()
    _install_ledger_fakes(monkeypatch, fake_redis, state)
    _install_creem_secret(monkeypatch)

    event = {
        "eventType": "checkout.completed",
        "object": {
            "id": "ch_hook_1",
            "metadata": {
                "user_id": "user-1",
                "plan_key": "starter",
                "credits": "30",
            },
        },
    }
    body = json.dumps(event).encode("utf-8")
    sig = _creem_sign(body)

    first = _post_creem(api_client, body, sig)
    second = _post_creem(api_client, body, sig)  # replay

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text  # duplicate never 5xx
    assert state["grants"] == [("user-1", 30, "purchase:creem:ch_hook_1")]
    assert len(state["grants"]) == 1  # granted exactly once
    assert fake_redis.set_calls == 2  # SETNX attempted on both deliveries


def test_creem_webhook_funds_workspace_pool(client, monkeypatch):
    api_client, _Factory = client
    state = {"grants": [], "balances": {}, "ws_grants": [], "ws_balances": {}}
    fake_redis = _FakeRedis()
    _install_ledger_fakes(monkeypatch, fake_redis, state)
    _install_creem_secret(monkeypatch)

    event = {
        "eventType": "checkout.completed",
        "object": {
            "id": "ch_hook_ws",
            "metadata": {
                "user_id": "admin-9",
                "plan_key": "pro",
                "credits": "120",
                "workspace_id": "ws-9",
            },
        },
    }
    body = json.dumps(event).encode("utf-8")

    resp = _post_creem(api_client, body, _creem_sign(body))

    assert resp.status_code == 200, resp.text
    assert state["ws_balances"] == {"ws-9": 120}
    assert state["ws_grants"] == [("ws-9", 120, "purchase:creem:ch_hook_ws", "admin-9")]
    assert state["grants"] == []  # actor's personal balance untouched


def test_creem_webhook_bad_signature_is_400(client, monkeypatch):
    api_client, _Factory = client
    state = {"grants": [], "balances": {}}
    _install_ledger_fakes(monkeypatch, _FakeRedis(), state)
    _install_creem_secret(monkeypatch)

    body = json.dumps({"eventType": "checkout.completed", "object": {}}).encode("utf-8")

    resp = _post_creem(api_client, body, "deadbeef")  # wrong signature

    assert resp.status_code == 400, resp.text
    assert state["grants"] == []  # nothing granted on a forged webhook


# --------------------------------------------------------------------------- #
# Polar webhook — signed (Standard Webhooks), idempotent, workspace-aware
# --------------------------------------------------------------------------- #
def _polar_headers(body: bytes, secret: str = _POLAR_SECRET) -> dict[str, str]:
    from app.services.billing import polar_client

    msg_id = "msg_test_1"
    ts = str(int(time.time()))
    sig = polar_client._sign_content(secret, msg_id, ts, body)
    return {
        "webhook-id": msg_id,
        "webhook-timestamp": ts,
        "webhook-signature": f"v1,{sig}",
        "Content-Type": "application/json",
    }


def _post_polar(api_client, body: bytes, headers: dict[str, str]):
    return api_client.post(
        "/api/v1/billing/webhook/polar", content=body, headers=headers
    )


def _install_polar_secret(monkeypatch):
    from app.services.billing import polar_client

    monkeypatch.setattr(
        polar_client, "_polar_config", lambda: {"webhook_secret": _POLAR_SECRET}
    )


def test_polar_webhook_fulfills_once_then_replay_no_double(client, monkeypatch):
    api_client, _Factory = client
    state = {"grants": [], "balances": {}, "reason_exists": False}
    fake_redis = _FakeRedis()
    _install_ledger_fakes(monkeypatch, fake_redis, state)
    _install_polar_secret(monkeypatch)

    event = {
        "type": "order.created",
        "data": {
            "id": "co_hook_1",
            "metadata": {
                "user_id": "user-2",
                "plan_key": "starter",
                "credits": "30",
            },
        },
    }
    body = json.dumps(event).encode("utf-8")
    headers = _polar_headers(body)

    first = _post_polar(api_client, body, headers)
    second = _post_polar(api_client, body, headers)  # replay

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert state["grants"] == [("user-2", 30, "purchase:polar:co_hook_1")]
    assert len(state["grants"]) == 1
    assert fake_redis.set_calls == 2


def test_polar_webhook_funds_workspace_pool(client, monkeypatch):
    api_client, _Factory = client
    state = {"grants": [], "balances": {}, "ws_grants": [], "ws_balances": {}}
    fake_redis = _FakeRedis()
    _install_ledger_fakes(monkeypatch, fake_redis, state)
    _install_polar_secret(monkeypatch)

    event = {
        "type": "checkout.updated",
        "data": {
            "id": "co_hook_ws",
            "status": "succeeded",
            "metadata": {
                "user_id": "admin-5",
                "plan_key": "pro",
                "credits": "120",
                "workspace_id": "ws-5",
            },
        },
    }
    body = json.dumps(event).encode("utf-8")

    resp = _post_polar(api_client, body, _polar_headers(body))

    assert resp.status_code == 200, resp.text
    assert state["ws_balances"] == {"ws-5": 120}
    assert state["ws_grants"] == [("ws-5", 120, "purchase:polar:co_hook_ws", "admin-5")]
    assert state["grants"] == []


def test_polar_webhook_bad_signature_is_400(client, monkeypatch):
    api_client, _Factory = client
    state = {"grants": [], "balances": {}}
    _install_ledger_fakes(monkeypatch, _FakeRedis(), state)
    _install_polar_secret(monkeypatch)

    body = json.dumps({"type": "order.created", "data": {}}).encode("utf-8")
    headers = _polar_headers(body)
    headers["webhook-signature"] = "v1,not-a-real-signature"

    resp = _post_polar(api_client, body, headers)

    assert resp.status_code == 400, resp.text
    assert state["grants"] == []


# --------------------------------------------------------------------------- #
# GET /billing/providers — enabled set follows configured secrets
# --------------------------------------------------------------------------- #
def test_providers_endpoint_lists_only_configured(client, monkeypatch):
    api_client, _Factory = client
    from app.services.billing import service

    # Only Stripe + Creem carry the required secret in this scenario.
    def _fake_section(name):
        return {
            "stripe": {"secret_key": "sk_live_x"},
            "iyzico": {},  # missing api_key/secret_key -> disabled
            "creem": {"api_key": "creem_live_x"},
            "polar": {},  # missing access_token -> disabled
        }.get(name, {})

    monkeypatch.setattr(service, "_config_section", _fake_section)

    resp = api_client.get("/api/v1/billing/providers")

    assert resp.status_code == 200, resp.text
    providers = resp.json()["data"]["providers"]
    # Only the active merchant of record (MENIVOR_PAYMENTS_PROVIDER, default
    # creem) is offered, so money never routes through a non-selected store.
    assert providers == ["creem"]
