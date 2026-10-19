"""Developer portal v1 API tests (Enterprise API Platform, Epic 4).

Exercises ``app.controllers.v1.developer`` end-to-end over a FastAPI
``TestClient`` with Postgres replaced by in-memory SQLite. No external I/O.

Covered
-------
* CALLER-SCOPED — the portal reports the CALLER's own API-key footprint + the
  webhook subscriptions of the workspaces THEY belong to; another user's keys /
  subscriptions never leak into it.
* USAGE — the current-month request usage is summed across the caller's keys
  (reusing the Epic-3 per-key usage counter).
* NO SECRET LEAK — no raw key, hash, or signing secret appears anywhere in the
  response; only counts + static integration links.
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

import app.controllers.v1.developer as developer_mod
from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.db.repositories import (
    ApiKeyUsageRepository,
    UserApiKeyRepository,
    WebhookSubscriptionRepository,
)
from app.models.exception import HttpException
from app.services import apikey_quota
from app.utils import utils


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture()
def client(monkeypatch, db_factory):
    Factory = db_factory

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

    monkeypatch.setattr(developer_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(developer_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(db_factory):
    """User A: 2 keys (1 revoked) + a workspace with 2 subs (1 disabled) + usage.

    User B: their own key + workspace + subscription (must never leak into A).
    """
    Factory = db_factory
    period = apikey_quota.current_period_ym()
    with Factory() as s:
        user_a = User(email="devA@ex.com", api_key_hash=_key_hash("devA-key"))
        user_b = User(email="devB@ex.com", api_key_hash=_key_hash("devB-key"))
        s.add_all([user_a, user_b])
        s.flush()

        key_repo = UserApiKeyRepository(s)
        k1 = key_repo.create(
            user_id=user_a.id, name="CI", key_hash=_key_hash("k1"), prefix="rf_k1"
        )
        k2 = key_repo.create(
            user_id=user_a.id, name="old", key_hash=_key_hash("k2"), prefix="rf_k2"
        )
        s.flush()
        key_repo.revoke(k2.id, user_a.id)  # A has 2 keys, 1 active
        kb = key_repo.create(
            user_id=user_b.id, name="B", key_hash=_key_hash("kb"), prefix="rf_kb"
        )
        s.flush()

        usage = ApiKeyUsageRepository(s)
        usage.increment(k1.id, period, amount=7)
        usage.increment(kb.id, period, amount=99)  # B's usage must not bleed into A

        ws_a = Workspace(owner_id=user_a.id, name="Acme-A")
        ws_b = Workspace(owner_id=user_b.id, name="Beta-B")
        s.add_all([ws_a, ws_b])
        s.flush()
        s.add_all(
            [
                WorkspaceMember(workspace_id=ws_a.id, user_id=user_a.id, role="owner"),
                WorkspaceMember(workspace_id=ws_b.id, user_id=user_b.id, role="owner"),
            ]
        )
        s.flush()

        sub_repo = WebhookSubscriptionRepository(s)
        sub_repo.create(
            workspace_id=ws_a.id,
            url="https://93.184.216.34/a1",
            event_types=["job.completed"],
            secret_enc="enc-a1",
            enabled=True,
        )
        sub_repo.create(
            workspace_id=ws_a.id,
            url="https://93.184.216.34/a2",
            event_types=["job.completed"],
            secret_enc="enc-a2",
            enabled=False,
        )
        sub_repo.create(
            workspace_id=ws_b.id,
            url="https://93.184.216.34/b1",
            event_types=["job.completed"],
            secret_enc="enc-b1",
            enabled=True,
        )
        s.commit()
        out = {"a_key": "devA-key", "b_key": "devB-key", "period": period}
    return out


def test_portal_reports_caller_footprint(client, seeded):
    tc, _ = client
    resp = tc.get("/api/v1/me/developer", headers=_headers(seeded["a_key"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # API keys: A has 2 keys, 1 active, 7 requests this month.
    assert data["api_keys"]["total"] == 2
    assert data["api_keys"]["active"] == 1
    assert data["api_keys"]["period_ym"] == seeded["period"]
    assert data["api_keys"]["requests_this_month"] == 7

    # Webhooks: A's single workspace has 2 subs, 1 enabled.
    assert data["webhooks"]["total"] == 2
    assert data["webhooks"]["active"] == 1

    assert data["workspaces"] == 1
    assert "job.completed" in data["webhook_event_types"]
    # Static integration metadata is present.
    assert data["api_base_url"].endswith("/api/v1")
    assert data["openapi_url"].endswith("/openapi.json")
    assert data["docs_url"].endswith("/docs")


def test_portal_is_caller_scoped(client, seeded):
    """User B sees only their OWN footprint — none of A's keys/subs/usage."""
    tc, _ = client
    resp = tc.get("/api/v1/me/developer", headers=_headers(seeded["b_key"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["api_keys"]["total"] == 1
    assert data["api_keys"]["active"] == 1
    assert data["api_keys"]["requests_this_month"] == 99
    assert data["webhooks"]["total"] == 1
    assert data["webhooks"]["active"] == 1
    assert data["workspaces"] == 1


def test_portal_never_leaks_secret(client, seeded):
    tc, _ = client
    resp = tc.get("/api/v1/me/developer", headers=_headers(seeded["a_key"]))
    assert resp.status_code == 200, resp.text
    blob = resp.text.lower()
    for needle in ("secret", "secret_enc", "enc-a1", "key_hash", "api_key_hash"):
        assert needle not in blob, f"leaked '{needle}' in developer portal response"


def test_portal_requires_auth(client, seeded):
    tc, _ = client
    resp = tc.get("/api/v1/me/developer")  # no x-api-key
    assert resp.status_code == 401, resp.text
