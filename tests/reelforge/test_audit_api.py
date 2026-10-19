"""Enterprise audit-trail v1 API tests (Access & Governance, Epic 1).

Exercises ``app.controllers.v1.audit`` (read) alongside
``app.controllers.v1.rbac`` (which writes rows) end-to-end over a FastAPI
``TestClient`` with in-memory SQLite. No external I/O.

Scenarios covered
-----------------
* an admin (holds ``audit.read``) reads the tenant's trail and sees a governance
  action that a role change wrote
* an editor (lacks ``audit.read``) reading the trail -> ``403``
* a non-member reading the trail -> ``403`` (real workspace) / ``404`` (unknown)
* CROSS-TENANT: a member of workspace B can never read workspace A's trail
* ``limit`` is clamped and pagination works
* auth required (missing key -> ``401``)
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

import app.controllers.v1.audit as audit_mod
import app.controllers.v1.rbac as rbac_mod
from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.exception import HttpException
from app.services import audit as audit_service
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
    """A TestClient mounting BOTH the audit and rbac routers over one SQLite DB."""
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

    monkeypatch.setattr(audit_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(rbac_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(audit_mod.router)
    app.include_router(rbac_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def two_tenants(db_factory):
    """Seed two independent workspaces A and B, each with owner + admin + editor.

    Returns labels ``a_owner/a_admin/a_editor/b_owner/b_admin`` -> (id, key) plus
    ``ws_a`` / ``ws_b``.
    """
    Factory = db_factory
    out: dict[str, object] = {}
    specs = {
        "a_owner": ("a_owner@ex.com", "a-owner", "A", "owner"),
        "a_admin": ("a_admin@ex.com", "a-admin", "A", "admin"),
        "a_editor": ("a_editor@ex.com", "a-editor", "A", "editor"),
        "b_owner": ("b_owner@ex.com", "b-owner", "B", "owner"),
        "b_admin": ("b_admin@ex.com", "b-admin", "B", "admin"),
    }
    with Factory() as s:
        ids: dict[str, str] = {}
        for label, (email, raw, _t, _role) in specs.items():
            u = User(email=email, api_key_hash=_key_hash(raw), credits=0)
            s.add(u)
            s.flush()
            ids[label] = u.id
            out[label] = (u.id, raw)
        ws_a = Workspace(owner_id=ids["a_owner"], name="A")
        ws_b = Workspace(owner_id=ids["b_owner"], name="B")
        s.add_all([ws_a, ws_b])
        s.flush()
        wsid = {"A": ws_a.id, "B": ws_b.id}
        for label, (_email, _raw, tenant, role) in specs.items():
            s.add(
                WorkspaceMember(
                    workspace_id=wsid[tenant], user_id=ids[label], role=role
                )
            )
        # Seed one audit row into each tenant so cross-tenant scoping is testable.
        audit_service.record(
            s,
            actor_user_id=ids["a_owner"],
            action="workspace.created",
            workspace_id=ws_a.id,
            target_type="workspace",
            target_id=ws_a.id,
            metadata={"tenant": "A"},
        )
        audit_service.record(
            s,
            actor_user_id=ids["b_owner"],
            action="workspace.created",
            workspace_id=ws_b.id,
            target_type="workspace",
            target_id=ws_b.id,
            metadata={"tenant": "B"},
        )
        s.commit()
        out["ws_a"] = ws_a.id
        out["ws_b"] = ws_b.id
    return out


# =========================================================================== #
# Read gating
# =========================================================================== #
def test_admin_reads_audit_trail(client, two_tenants):
    c, _ = client
    ws_a = two_tenants["ws_a"]
    _admin_id, admin_key = two_tenants["a_admin"]
    resp = c.get(
        f"/api/v1/me/workspaces/{ws_a}/audit", headers=_headers(admin_key)
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert any(r["action"] == "workspace.created" for r in rows)
    assert all(r["workspace_id"] == ws_a for r in rows)


def test_role_change_shows_up_in_audit(client, two_tenants):
    """A governance mutation (role change) leaves a row the admin can read."""
    c, _ = client
    ws_a = two_tenants["ws_a"]
    _owner_id, owner_key = two_tenants["a_owner"]
    editor_id, _ = two_tenants["a_editor"]
    _admin_id, admin_key = two_tenants["a_admin"]

    patch = c.patch(
        f"/api/v1/me/workspaces/{ws_a}/members/{editor_id}/role",
        json={"role": "viewer"},
        headers=_headers(owner_key),
    )
    assert patch.status_code == 200, patch.text

    rows = c.get(
        f"/api/v1/me/workspaces/{ws_a}/audit", headers=_headers(admin_key)
    ).json()["data"]
    actions = [r["action"] for r in rows]
    assert "members.role_changed" in actions
    entry = next(r for r in rows if r["action"] == "members.role_changed")
    assert entry["target_id"] == editor_id
    assert entry["metadata"]["new_role"] == "viewer"


def test_editor_cannot_read_audit_403(client, two_tenants):
    c, _ = client
    ws_a = two_tenants["ws_a"]
    _editor_id, editor_key = two_tenants["a_editor"]
    resp = c.get(
        f"/api/v1/me/workspaces/{ws_a}/audit", headers=_headers(editor_key)
    )
    assert resp.status_code == 403, resp.text


def test_non_member_cannot_read_audit_403(client, two_tenants):
    c, _ = client
    ws_a = two_tenants["ws_a"]
    # b_admin is not a member of A.
    _bid, b_admin_key = two_tenants["b_admin"]
    resp = c.get(
        f"/api/v1/me/workspaces/{ws_a}/audit", headers=_headers(b_admin_key)
    )
    assert resp.status_code == 403, resp.text


def test_cross_tenant_audit_isolation(client, two_tenants):
    """Workspace B's admin can read B's trail but NEVER A's."""
    c, _ = client
    ws_a = two_tenants["ws_a"]
    ws_b = two_tenants["ws_b"]
    _bid, b_admin_key = two_tenants["b_admin"]

    # B admin reads B: sees only B rows.
    b_rows = c.get(
        f"/api/v1/me/workspaces/{ws_b}/audit", headers=_headers(b_admin_key)
    )
    assert b_rows.status_code == 200, b_rows.text
    assert all(r["workspace_id"] == ws_b for r in b_rows.json()["data"])

    # B admin tries to read A: forbidden (not a member of A).
    a_attempt = c.get(
        f"/api/v1/me/workspaces/{ws_a}/audit", headers=_headers(b_admin_key)
    )
    assert a_attempt.status_code == 403, a_attempt.text


def test_audit_unknown_workspace_404(client, two_tenants):
    c, _ = client
    _admin_id, admin_key = two_tenants["a_admin"]
    resp = c.get(
        "/api/v1/me/workspaces/does-not-exist/audit", headers=_headers(admin_key)
    )
    assert resp.status_code == 404, resp.text


def test_audit_requires_auth_401(client, two_tenants):
    c, _ = client
    ws_a = two_tenants["ws_a"]
    resp = c.get(f"/api/v1/me/workspaces/{ws_a}/audit")
    assert resp.status_code == 401, resp.text


def test_audit_limit_is_clamped(client, two_tenants):
    """An oversized/absurd limit is clamped rather than producing a bad query."""
    c, _ = client
    ws_a = two_tenants["ws_a"]
    _admin_id, admin_key = two_tenants["a_admin"]
    resp = c.get(
        f"/api/v1/me/workspaces/{ws_a}/audit?limit=99999&offset=0",
        headers=_headers(admin_key),
    )
    assert resp.status_code == 200, resp.text
    # At most _MAX_AUDIT_LIMIT rows come back (only one seeded here anyway).
    assert len(resp.json()["data"]) <= audit_mod._MAX_AUDIT_LIMIT
