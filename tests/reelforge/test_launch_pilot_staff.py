"""Pilot staff override for the fail-closed launch gates (W2-G).

While the launch is ``internal_pilot`` publishing and checkout are closed for
everyone, except principals on the ``REELFORGE_PILOT_STAFF`` allow-list. The
gates resolve the caller through the request scope bound by
``LaunchRequestScopeMiddleware``; anything unresolvable fails closed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.core.launch import policy
from app.models.exception import HttpException
from app.utils import utils

STAFF_EMAIL = "staff@menivor.test"


@pytest.fixture(autouse=True)
def _pilot(monkeypatch):
    for name in (
        "REELFORGE_LAUNCH_MODE",
        "REELFORGE_PUBLIC_LAUNCH_APPROVED",
        "REELFORGE_CHECKOUT_ENABLED",
        "REELFORGE_PUBLISHING_ENABLED",
        "REELFORGE_PILOT_STAFF",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "internal_pilot")


def _app(monkeypatch, users_by_key: dict[str, SimpleNamespace]) -> TestClient:
    """A tiny app with gated routes; the principal comes from ``x-api-key``."""

    def _fake_resolve(scope):
        key = dict(scope.get("headers") or []).get(b"x-api-key", b"").decode()
        user = users_by_key.get(key)
        if user is None:
            raise HttpException(task_id="t", status_code=401, message="t: missing key")
        return policy.principal_is_pilot_staff(user)

    monkeypatch.setattr(policy, "_resolve_scope_user", _fake_resolve)

    app = FastAPI()
    app.add_middleware(policy.LaunchRequestScopeMiddleware)

    @app.post("/publish")
    def publish():
        policy.require_publishing_enabled("rid")
        return {"ok": True}

    @app.post("/checkout")
    def checkout():
        policy.require_checkout_enabled("rid")
        return {"ok": True}

    @app.get("/status")
    def status():
        return policy.launch_status()

    def _handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _handler)
    return TestClient(app)


def test_pilot_staff_parses_emails_and_ids(monkeypatch):
    monkeypatch.setenv("REELFORGE_PILOT_STAFF", " Staff@Menivor.test , 42 ,,")
    assert policy.pilot_staff() == frozenset({"staff@menivor.test", "42"})
    assert policy.principal_is_pilot_staff(SimpleNamespace(email="STAFF@menivor.test", id=7))
    assert policy.principal_is_pilot_staff(SimpleNamespace(email="other@x.test", id=42))
    assert not policy.principal_is_pilot_staff(SimpleNamespace(email="other@x.test", id=7))
    assert not policy.principal_is_pilot_staff(None)


def test_empty_allow_list_matches_nobody(monkeypatch):
    assert policy.pilot_staff() == frozenset()
    assert not policy.principal_is_pilot_staff(SimpleNamespace(email=STAFF_EMAIL, id=1))


def test_gates_closed_outside_a_request(monkeypatch):
    monkeypatch.setenv("REELFORGE_PILOT_STAFF", STAFF_EMAIL)
    assert policy.publishing_enabled() is False
    assert policy.checkout_enabled() is False
    with pytest.raises(HttpException) as exc:
        policy.require_publishing_enabled("rid")
    assert exc.value.status_code == 403
    assert exc.value.data["code"] == policy.PUBLISHING_CLOSED_CODE
    assert "private beta" in exc.value.data["reason"]


def test_staff_can_publish_and_checkout_in_pilot(monkeypatch):
    monkeypatch.setenv("REELFORGE_PILOT_STAFF", STAFF_EMAIL)
    client = _app(monkeypatch, {"staff": SimpleNamespace(email=STAFF_EMAIL, id=1)})
    assert client.post("/publish", headers={"x-api-key": "staff"}).status_code == 200
    assert client.post("/checkout", headers={"x-api-key": "staff"}).status_code == 200
    body = client.get("/status", headers={"x-api-key": "staff"}).json()
    assert body["mode"] == "internal_pilot"
    assert body["staff_override"] is True
    assert body["features"]["publishing"] is True
    assert body["features"]["checkout"] is True


def test_non_staff_and_anonymous_stay_blocked(monkeypatch):
    monkeypatch.setenv("REELFORGE_PILOT_STAFF", STAFF_EMAIL)
    client = _app(monkeypatch, {"user": SimpleNamespace(email="user@x.test", id=2)})
    for headers in ({"x-api-key": "user"}, {}):
        resp = client.post("/publish", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["data"]["code"] == "publishing_closed"
        resp = client.post("/checkout", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["data"]["code"] == "checkout_closed"
    body = client.get("/status").json()
    assert body["staff_override"] is False
    assert body["features"]["publishing"] is False
    assert body["features"]["checkout"] is False


def test_staff_list_unset_never_resolves_a_principal(monkeypatch):
    calls: list[int] = []

    def _boom(_scope):
        calls.append(1)
        raise AssertionError("must not resolve without a staff list")

    monkeypatch.setattr(policy, "_resolve_scope_user", _boom)
    app = FastAPI()
    app.add_middleware(policy.LaunchRequestScopeMiddleware)

    @app.get("/status")
    def status():
        return policy.launch_status()

    body = TestClient(app).get("/status").json()
    assert body["features"]["publishing"] is False
    assert calls == []


def test_staff_resolution_is_cached_per_request(monkeypatch):
    monkeypatch.setenv("REELFORGE_PILOT_STAFF", STAFF_EMAIL)
    calls: list[int] = []

    def _resolve(_scope):
        calls.append(1)
        return True

    monkeypatch.setattr(policy, "_resolve_scope_user", _resolve)
    app = FastAPI()
    app.add_middleware(policy.LaunchRequestScopeMiddleware)

    @app.post("/both")
    def both():
        policy.require_publishing_enabled("rid")
        policy.require_checkout_enabled("rid")
        return policy.launch_status()

    assert TestClient(app).post("/both").status_code == 200
    assert calls == [1]


def test_public_flags_still_open_for_everyone(monkeypatch):
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "public")
    monkeypatch.setenv("REELFORGE_PUBLIC_LAUNCH_APPROVED", "true")
    monkeypatch.setenv("REELFORGE_PUBLISHING_ENABLED", "true")
    monkeypatch.setenv("REELFORGE_CHECKOUT_ENABLED", "false")
    assert policy.publishing_enabled() is True
    assert policy.checkout_enabled() is False
    with pytest.raises(HttpException) as exc:
        policy.require_checkout_enabled("rid")
    assert "switched off" in exc.value.data["reason"]


def test_payment_webhooks_open_only_with_public_checkout_or_staff(monkeypatch):
    assert policy.payment_webhooks_enabled() is False
    with pytest.raises(HttpException):
        policy.require_payment_webhooks_enabled("rid")
    monkeypatch.setenv("REELFORGE_PILOT_STAFF", STAFF_EMAIL)
    assert policy.payment_webhooks_enabled() is True
    policy.require_payment_webhooks_enabled("rid")
