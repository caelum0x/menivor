"""Enterprise workspace security-policy v1 API tests (Identity & SSO, Epic 2).

Exercises ``app.controllers.v1.security_policy`` end-to-end over a FastAPI
``TestClient`` with Postgres replaced by in-memory SQLite. No external I/O.

Covered
-------
* both routes are RBAC-gated (``workspace.settings``) — a viewer -> ``403``;
* an owner PUT persists the policy AND writes an Epic-1 audit row;
* GET reflects the persisted policy; an unset policy is ``data: null``;
* auth is required (missing key -> ``401``).
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.security_policy as policy_mod
from app.models.db.base import Base
from app.models.db.models import AuditLog, User, Workspace, WorkspaceMember
from app.models.exception import HttpException
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
def policy_client(monkeypatch, db_factory):
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

    monkeypatch.setattr(policy_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(policy_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(db_factory):
    Factory = db_factory
    out: dict[str, object] = {}
    specs = {
        "owner": ("owner@ex.com", "owner-key", "owner"),
        "viewer": ("viewer@ex.com", "viewer-key", "viewer"),
        "stranger": ("stranger@ex.com", "stranger-key", None),
    }
    with Factory() as s:
        ids: dict[str, str] = {}
        for label, (email, raw, _role) in specs.items():
            u = User(email=email, api_key_hash=_key_hash(raw), credits=0)
            s.add(u)
            s.flush()
            ids[label] = u.id
            out[label] = (u.id, raw)
        ws = Workspace(owner_id=ids["owner"], name="Acme")
        s.add(ws)
        s.flush()
        for label, (_email, _raw, role) in specs.items():
            if role is None:
                continue
            s.add(WorkspaceMember(workspace_id=ws.id, user_id=ids[label], role=role))
        s.commit()
        out["workspace_id"] = ws.id
    return out


# =========================================================================== #
# Tests
# =========================================================================== #
def test_get_unset_policy_is_null(policy_client, seeded):
    client, _ = policy_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]
    resp = client.get(
        f"/api/v1/me/workspaces/{wid}/security", headers=_headers(owner_key)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] is None


def test_viewer_cannot_read_policy_403(policy_client, seeded):
    client, _ = policy_client
    wid = seeded["workspace_id"]
    _vid, viewer_key = seeded["viewer"]
    resp = client.get(
        f"/api/v1/me/workspaces/{wid}/security", headers=_headers(viewer_key)
    )
    assert resp.status_code == 403, resp.text


def test_viewer_cannot_write_policy_403(policy_client, seeded):
    client, _ = policy_client
    wid = seeded["workspace_id"]
    _vid, viewer_key = seeded["viewer"]
    resp = client.put(
        f"/api/v1/me/workspaces/{wid}/security",
        json={"require_sso": True},
        headers=_headers(viewer_key),
    )
    assert resp.status_code == 403, resp.text


def test_owner_updates_policy_and_writes_audit(policy_client, seeded):
    client, Factory = policy_client
    wid = seeded["workspace_id"]
    owner_id, owner_key = seeded["owner"]

    resp = client.put(
        f"/api/v1/me/workspaces/{wid}/security",
        json={
            "require_sso": True,
            "session_timeout_min": 60,
            "allowed_email_domains": ["acme.com"],
            "mfa_required": True,
            "ip_allowlist": ["10.0.0.1"],
        },
        headers=_headers(owner_key),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["require_sso"] is True
    assert data["session_timeout_min"] == 60
    assert data["allowed_email_domains"] == ["acme.com"]
    assert data["mfa_required"] is True
    assert data["ip_allowlist"] == ["10.0.0.1"]

    got = client.get(
        f"/api/v1/me/workspaces/{wid}/security", headers=_headers(owner_key)
    ).json()["data"]
    assert got["require_sso"] is True
    assert got["allowed_email_domains"] == ["acme.com"]

    with Factory() as s:
        rows = s.execute(select(AuditLog)).scalars().all()
        updates = [r for r in rows if r.action == "security_policy.updated"]
        assert len(updates) == 1
        assert updates[0].workspace_id == wid
        assert updates[0].actor_user_id == owner_id


def test_partial_update_preserves_other_fields(policy_client, seeded):
    client, _ = policy_client
    wid = seeded["workspace_id"]
    _oid, owner_key = seeded["owner"]

    client.put(
        f"/api/v1/me/workspaces/{wid}/security",
        json={"require_sso": True, "session_timeout_min": 30},
        headers=_headers(owner_key),
    )
    # A second partial update toggling only mfa_required must not reset require_sso.
    client.put(
        f"/api/v1/me/workspaces/{wid}/security",
        json={"mfa_required": True},
        headers=_headers(owner_key),
    )
    got = client.get(
        f"/api/v1/me/workspaces/{wid}/security", headers=_headers(owner_key)
    ).json()["data"]
    assert got["require_sso"] is True
    assert got["session_timeout_min"] == 30
    assert got["mfa_required"] is True


def test_requires_auth_401(policy_client, seeded):
    client, _ = policy_client
    wid = seeded["workspace_id"]
    resp = client.get(f"/api/v1/me/workspaces/{wid}/security")
    assert resp.status_code == 401, resp.text
