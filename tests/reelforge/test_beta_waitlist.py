"""Private-beta waitlist: request/dedupe, admin-token approval, signup gate."""

from __future__ import annotations

import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.beta import models as beta_models  # noqa: F401 - register table
from app.domains.beta import service
from app.models.db import models  # noqa: F401
from app.models.db.base import Base
from app.models.exception import HttpException
from app.utils import utils

mod = importlib.import_module("app.domains.beta.router")
policy = importlib.import_module("app.core.launch.policy")
ADMIN = "t" * 32


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture
def client(factory, monkeypatch):
    @contextmanager
    def _gs():
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    class _Allowed:
        allowed = True

    monkeypatch.setattr(mod, "get_session", _gs)
    monkeypatch.setattr(mod, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(mod, "rate_limit", lambda *a, **k: _Allowed())
    monkeypatch.setenv("REELFORGE_BETA_ADMIN_TOKEN", ADMIN)
    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(status_code=exc.status_code,
                                    content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app)


def test_request_is_stored_and_deduped(client, factory):
    for _ in range(2):
        r = client.post("/api/v1/beta/request", json={"email": " Maker@Example.com ", "use_case": "ads"})
        assert r.status_code == 200 and r.json()["data"]["status"] == "received"
    with factory() as s:
        rows = s.query(beta_models.BetaAccessRequest).all()
        assert len(rows) == 1
        assert rows[0].email == "maker@example.com" and rows[0].request_count == 2
        assert rows[0].status == "pending"


def test_invalid_email_rejected(client):
    assert client.post("/api/v1/beta/request", json={"email": "not-an-email"}).status_code == 422


def test_admin_endpoints_require_token(client, monkeypatch):
    assert client.get("/api/v1/beta/requests").status_code == 403
    assert client.get("/api/v1/beta/requests", headers={"x-admin-token": "wrong"}).status_code == 403
    monkeypatch.setenv("REELFORGE_BETA_ADMIN_TOKEN", "short")
    assert client.get("/api/v1/beta/requests", headers={"x-admin-token": "short"}).status_code == 503


def test_approve_then_signup_gate_allows_only_that_email(client, factory, monkeypatch):
    client.post("/api/v1/beta/request", json={"email": "maker@example.com"})
    r = client.post("/api/v1/beta/requests/approve", headers={"x-admin-token": ADMIN},
                    json={"email": "MAKER@example.com"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "approved"
    listed = client.get("/api/v1/beta/requests?status=approved", headers={"x-admin-token": ADMIN})
    assert listed.json()["data"]["count"] == 1

    monkeypatch.setattr(policy, "signup_enabled", lambda: False)
    with factory() as s:
        policy.require_signup_enabled("rid", session=s, verified_email="maker@example.com")
        with pytest.raises(HttpException) as exc:
            policy.require_signup_enabled("rid", session=s, verified_email="other@example.com")
        assert exc.value.status_code == 403
        with pytest.raises(HttpException):
            policy.require_signup_enabled("rid")  # no session/email -> closed

    client.post("/api/v1/beta/requests/approve", headers={"x-admin-token": ADMIN},
                json={"email": "maker@example.com", "approved": False})
    with factory() as s:
        with pytest.raises(HttpException):
            policy.require_signup_enabled("rid", session=s, verified_email="maker@example.com")


def test_is_email_approved_fails_closed_on_garbage(factory):
    with factory() as s:
        assert service.is_email_approved(s, "") is False
        assert service.is_email_approved(s, "x@y") is False
        assert service.is_email_approved(None, "a@b.co") is False
