"""Workspace-pool credit purchases — v1 billing API tests.

Exercises the checkout endpoint's workspace-authorization gate in
``app.controllers.v1.billing`` end-to-end over a FastAPI ``TestClient`` with
Postgres replaced by in-memory SQLite. No external I/O: the billing *service*
(which owns the Stripe/iyzico SDK calls) is monkeypatched to a capturing fake,
so these tests assert only the transport + authorization behaviour this agent
owns — never a real provider session.

Identity is switched per request via the ``x-api-key`` header (SHA-256 stored as
``User.api_key_hash``), so the same client acts as the workspace owner, an
invited admin, a plain member, or a stranger by swapping the header — mirroring
how the real auth gate resolves the caller.

Scenarios covered
-----------------
* an ADMIN (and the OWNER) can start a WORKSPACE checkout: ``service.create_checkout``
  is called with the target ``workspace_id`` and a ``checkout_url`` is returned.
* a plain MEMBER buying for the pool -> ``403`` (service never called).
* a non-member (stranger) of an existing workspace -> ``403`` (service never called).
* an unknown workspace -> ``404`` (service never called).
* PERSONAL checkout (no ``workspace_id``) still works and forwards ``workspace_id=None``.
* a missing api key on a workspace checkout -> ``401`` (service never called).
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
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
from app.services import workspaces as ws_service
from app.utils import utils


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


class _CapturingService:
    """Stand-in for ``app.services.billing.service`` used by the checkout route.

    Records every ``create_checkout`` call so tests can assert the workspace id
    that crossed the authorization gate — and, crucially, assert the service was
    NOT reached at all on a rejected (401/403/404) request.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_checkout(
        self,
        user_id: str,
        user_email: str = "",
        plan_key: str = "",
        provider: str = "",
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "user_id": user_id,
                "user_email": user_email,
                "plan_key": plan_key,
                "provider": provider,
                "workspace_id": workspace_id,
            }
        )
        return {
            "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_ws",
            "session_id": "cs_test_ws",
        }


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture()
def env(monkeypatch):
    """Billing router wired to a shared in-memory SQLite DB + a fake service."""
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

    fake_service = _CapturingService()

    # The controller imported ``get_session`` into its own namespace and lazily
    # imports the billing service via ``_import_service``; patch both so no real
    # DB / Stripe SDK is touched.
    monkeypatch.setattr(billing_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(billing_mod, "_DB_IMPORT_ERROR", None)
    monkeypatch.setattr(billing_mod, "_import_service", lambda rid: fake_service)

    app = FastAPI()
    app.include_router(billing_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory, fake_service


@pytest.fixture()
def users(env):
    """Seed four users; return {label: (user_id, raw_key)}."""
    _client, Factory, _service = env
    seeded: dict[str, tuple[str, str]] = {}
    specs = {
        "owner": ("owner@example.com", "owner-key"),
        "admin": ("admin@example.com", "admin-key"),
        "member": ("member@example.com", "member-key"),
        "stranger": ("stranger@example.com", "stranger-key"),
    }
    with Factory() as s:
        for label, (email, raw) in specs.items():
            u = User(email=email, api_key_hash=_key_hash(raw), credits=0)
            s.add(u)
            s.flush()
            seeded[label] = (u.id, raw)
        s.commit()
    return seeded


@pytest.fixture()
def workspace(env, users):
    """Create a workspace owned by ``owner`` with an ``admin`` and a ``member``.

    Uses the real workspaces service so the role hierarchy under test is the
    production one (owner > admin > member); returns the workspace id.
    """
    _client, Factory, _service = env
    owner_id, _ = users["owner"]
    with Factory() as s:
        ws = ws_service.create_workspace(s, owner_id, "Acme Studio")
        wid = ws.id
        ws_service.invite_member(
            s, wid, owner_id, "admin@example.com", role=ws_service.ROLE_ADMIN
        )
        ws_service.invite_member(
            s, wid, owner_id, "member@example.com", role=ws_service.ROLE_MEMBER
        )
        s.commit()
    return wid


# =========================================================================== #
# Helpers
# =========================================================================== #
def _checkout(client, raw_key, plan_key="starter", provider="stripe", workspace_id=None):
    body: dict[str, Any] = {"provider": provider, "plan_key": plan_key}
    if workspace_id is not None:
        body["workspace_id"] = workspace_id
    return client.post("/api/v1/billing/checkout", json=body, headers=_headers(raw_key))


# =========================================================================== #
# Workspace checkout — authorization gate
# =========================================================================== #
def test_admin_can_start_workspace_checkout(env, users, workspace):
    client, _Factory, service = env
    admin_id, admin_key = users["admin"]

    resp = _checkout(client, admin_key, workspace_id=workspace)

    assert resp.status_code == 200, resp.text
    assert (
        resp.json()["data"]["checkout_url"]
        == "https://checkout.stripe.com/c/pay/cs_test_ws"
    )
    # The service was reached exactly once, with the target workspace id.
    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["workspace_id"] == workspace
    assert call["user_id"] == admin_id
    assert call["plan_key"] == "starter"
    assert call["provider"] == "stripe"


def test_owner_can_start_workspace_checkout(env, users, workspace):
    """Owner outranks admin, so an owner may also fund the pool."""
    client, _Factory, service = env
    _owner_id, owner_key = users["owner"]

    resp = _checkout(client, owner_key, workspace_id=workspace)

    assert resp.status_code == 200, resp.text
    assert len(service.calls) == 1
    assert service.calls[0]["workspace_id"] == workspace


def test_plain_member_workspace_checkout_403(env, users, workspace):
    client, _Factory, service = env
    _member_id, member_key = users["member"]

    resp = _checkout(client, member_key, workspace_id=workspace)

    assert resp.status_code == 403, resp.text
    assert service.calls == []  # gate rejected before any provider session


def test_non_member_workspace_checkout_403(env, users, workspace):
    client, _Factory, service = env
    _stranger_id, stranger_key = users["stranger"]

    resp = _checkout(client, stranger_key, workspace_id=workspace)

    assert resp.status_code == 403, resp.text
    assert service.calls == []


def test_unknown_workspace_checkout_404(env, users):
    client, _Factory, service = env
    _owner_id, owner_key = users["owner"]

    resp = _checkout(client, owner_key, workspace_id="does-not-exist")

    assert resp.status_code == 404, resp.text
    assert service.calls == []


def test_workspace_checkout_requires_api_key(env, users, workspace):
    client, _Factory, service = env

    resp = client.post(
        "/api/v1/billing/checkout",
        json={"provider": "stripe", "plan_key": "starter", "workspace_id": workspace},
    )

    assert resp.status_code == 401, resp.text
    assert service.calls == []


# =========================================================================== #
# Personal checkout — unchanged
# =========================================================================== #
def test_personal_checkout_still_works(env, users):
    client, _Factory, service = env
    _member_id, member_key = users["member"]

    resp = _checkout(client, member_key)  # no workspace_id

    assert resp.status_code == 200, resp.text
    assert len(service.calls) == 1
    # Personal purchase forwards no workspace target.
    assert service.calls[0]["workspace_id"] is None


def test_personal_checkout_blank_workspace_id_is_personal(env, users):
    """A blank ``workspace_id`` normalises to ``None`` (personal, no admin gate)."""
    client, _Factory, service = env
    _member_id, member_key = users["member"]

    resp = _checkout(client, member_key, workspace_id="   ")

    assert resp.status_code == 200, resp.text
    assert len(service.calls) == 1
    assert service.calls[0]["workspace_id"] is None
