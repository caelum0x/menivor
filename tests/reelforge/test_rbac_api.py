"""Enterprise RBAC v1 API tests (Access & Governance, Epic 1).

Exercises ``app.controllers.v1.rbac`` end-to-end over a FastAPI ``TestClient``
with Postgres replaced by in-memory SQLite. No external I/O.

Identity is switched per request via the ``x-api-key`` header: several users are
seeded, each with a distinct raw key (whose SHA-256 is stored as
``User.api_key_hash``), so the same client can act as owner, admin, viewer, or a
stranger simply by swapping the header — mirroring how the real auth gate
resolves the caller.

Scenarios covered
-----------------
* member roster lists every member with their Enterprise role
* a non-member roster read -> ``403`` (real workspace) / ``404`` (unknown id)
* ``GET /me/permissions`` returns the caller's effective (direct+inherited) perms
* a viewer PATCHing a role -> ``403`` (lacks ``members.manage``)
* an owner promotes a viewer to editor -> ``200`` + an append-only audit row
* an admin cannot grant a role above their own (owner) -> ``403``
* demoting the last owner -> ``409``
* auth required (missing key -> ``401``)
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

import app.controllers.v1.rbac as rbac_mod
from app.models.db.base import Base
from app.models.db.models import AuditLog, User, Workspace, WorkspaceMember
from app.models.exception import HttpException
from app.utils import utils


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


# =========================================================================== #
# Fixtures
# =========================================================================== #
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
def rbac_client(monkeypatch, db_factory):
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

    monkeypatch.setattr(rbac_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(rbac_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(db_factory):
    """Seed a workspace with owner/admin/editor/viewer members + a stranger.

    Returns a dict of ``label -> (user_id, raw_key)`` plus ``workspace_id``.
    """
    Factory = db_factory
    out: dict[str, object] = {}
    specs = {
        "owner": ("owner@ex.com", "owner-key", "owner"),
        "admin": ("admin@ex.com", "admin-key", "admin"),
        "editor": ("editor@ex.com", "editor-key", "editor"),
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
            s.add(
                WorkspaceMember(
                    workspace_id=ws.id, user_id=ids[label], role=role
                )
            )
        s.commit()
        out["workspace_id"] = ws.id
    return out


# =========================================================================== #
# Roster
# =========================================================================== #
def test_member_roster_lists_roles(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _owner_id, owner_key = seeded["owner"]

    resp = client.get(
        f"/api/v1/me/workspaces/{wid}/members", headers=_headers(owner_key)
    )
    assert resp.status_code == 200, resp.text
    by_email = {m["email"]: m["role"] for m in resp.json()["data"]}
    assert by_email == {
        "owner@ex.com": "owner",
        "admin@ex.com": "admin",
        "editor@ex.com": "editor",
        "viewer@ex.com": "viewer",
    }


def test_viewer_can_read_roster(rbac_client, seeded):
    """A viewer holds jobs.read (the floor perm) so may read the roster."""
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _viewer_id, viewer_key = seeded["viewer"]
    resp = client.get(
        f"/api/v1/me/workspaces/{wid}/members", headers=_headers(viewer_key)
    )
    assert resp.status_code == 200, resp.text


def test_non_member_roster_forbidden_403(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _stranger_id, stranger_key = seeded["stranger"]
    resp = client.get(
        f"/api/v1/me/workspaces/{wid}/members", headers=_headers(stranger_key)
    )
    assert resp.status_code == 403, resp.text


def test_roster_unknown_workspace_404(rbac_client, seeded):
    client, _ = rbac_client
    _owner_id, owner_key = seeded["owner"]
    resp = client.get(
        "/api/v1/me/workspaces/nope/members", headers=_headers(owner_key)
    )
    assert resp.status_code == 404, resp.text


def test_roster_requires_auth_401(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    resp = client.get(f"/api/v1/me/workspaces/{wid}/members")
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# Permissions
# =========================================================================== #
def test_my_permissions_admin(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _admin_id, admin_key = seeded["admin"]
    resp = client.get(
        f"/api/v1/me/permissions?workspace_id={wid}", headers=_headers(admin_key)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["role"] == "admin"
    perms = set(data["permissions"])
    assert {
        "jobs.read",
        "jobs.create",
        "members.manage",
        "workspace.settings",
        "audit.read",
    } <= perms
    assert "billing.manage" not in perms


def test_my_permissions_viewer_minimal(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _viewer_id, viewer_key = seeded["viewer"]
    resp = client.get(
        f"/api/v1/me/permissions?workspace_id={wid}", headers=_headers(viewer_key)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["role"] == "viewer"
    assert set(data["permissions"]) == {"jobs.read"}


def test_my_permissions_non_member_empty(rbac_client, seeded):
    """A non-member leaks nothing: null role, empty permissions."""
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _stranger_id, stranger_key = seeded["stranger"]
    resp = client.get(
        f"/api/v1/me/permissions?workspace_id={wid}",
        headers=_headers(stranger_key),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["role"] is None
    assert data["permissions"] == []


def test_my_permissions_requires_auth_401(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    resp = client.get(f"/api/v1/me/permissions?workspace_id={wid}")
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# Role change (PATCH) — permission-gated, guarded, audited
# =========================================================================== #
def _patch_role(client, wid, target_id, role, key):
    return client.patch(
        f"/api/v1/me/workspaces/{wid}/members/{target_id}/role",
        json={"role": role},
        headers=_headers(key),
    )


def test_viewer_cannot_change_role_403(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _viewer_id, viewer_key = seeded["viewer"]
    editor_id, _ = seeded["editor"]
    resp = _patch_role(client, wid, editor_id, "admin", viewer_key)
    assert resp.status_code == 403, resp.text


def test_editor_cannot_change_role_403(rbac_client, seeded):
    """Editor lacks members.manage -> 403."""
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _editor_id, editor_key = seeded["editor"]
    viewer_id, _ = seeded["viewer"]
    resp = _patch_role(client, wid, viewer_id, "editor", editor_key)
    assert resp.status_code == 403, resp.text


def test_owner_promotes_viewer_and_writes_audit(rbac_client, seeded):
    client, Factory = rbac_client
    wid = seeded["workspace_id"]
    owner_id, owner_key = seeded["owner"]
    viewer_id, viewer_key = seeded["viewer"]

    resp = _patch_role(client, wid, viewer_id, "editor", owner_key)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "editor"

    # The promotion is reflected in the viewer's own effective permissions.
    perms = client.get(
        f"/api/v1/me/permissions?workspace_id={wid}", headers=_headers(viewer_key)
    ).json()["data"]
    assert perms["role"] == "editor"
    assert "jobs.create" in perms["permissions"]

    # Exactly one append-only audit row records the change.
    with Factory() as s:
        rows = s.execute(select(AuditLog)).scalars().all()
        changes = [r for r in rows if r.action == "members.role_changed"]
        assert len(changes) == 1
        entry = changes[0]
        assert entry.workspace_id == wid
        assert entry.actor_user_id == owner_id
        assert entry.target_id == viewer_id
        assert entry.meta.get("old_role") == "viewer"
        assert entry.meta.get("new_role") == "editor"


def test_admin_cannot_grant_role_above_own_403(rbac_client, seeded):
    """An admin cannot promote anyone to owner (out-ranks their own role)."""
    client, Factory = rbac_client
    wid = seeded["workspace_id"]
    _admin_id, admin_key = seeded["admin"]
    editor_id, _ = seeded["editor"]

    resp = _patch_role(client, wid, editor_id, "owner", admin_key)
    assert resp.status_code == 403, resp.text
    # No audit row for a rejected change.
    with Factory() as s:
        rows = s.execute(select(AuditLog)).scalars().all()
        assert [r for r in rows if r.action == "members.role_changed"] == []


def test_admin_can_grant_admin_equal_rank(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _admin_id, admin_key = seeded["admin"]
    editor_id, _ = seeded["editor"]
    resp = _patch_role(client, wid, editor_id, "admin", admin_key)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "admin"


def test_cannot_demote_last_owner_409(rbac_client, seeded):
    client, Factory = rbac_client
    wid = seeded["workspace_id"]
    owner_id, owner_key = seeded["owner"]

    resp = _patch_role(client, wid, owner_id, "admin", owner_key)
    assert resp.status_code == 409, resp.text
    # No audit row, and the owner is unchanged.
    with Factory() as s:
        rows = s.execute(select(AuditLog)).scalars().all()
        assert [r for r in rows if r.action == "members.role_changed"] == []
        m = (
            s.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == wid,
                    WorkspaceMember.user_id == owner_id,
                )
            )
            .scalars()
            .first()
        )
        assert m.role == "owner"


def test_demote_owner_allowed_when_second_owner_exists(rbac_client, seeded):
    """With two owners, demoting one is allowed (the workspace keeps an owner)."""
    client, Factory = rbac_client
    wid = seeded["workspace_id"]
    owner_id, owner_key = seeded["owner"]
    admin_id, _ = seeded["admin"]

    # Promote admin to a second owner first.
    assert _patch_role(client, wid, admin_id, "owner", owner_key).status_code == 200

    # Now the original owner can be demoted (a second owner remains).
    resp = _patch_role(client, wid, owner_id, "admin", owner_key)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "admin"


def test_invalid_role_400(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _owner_id, owner_key = seeded["owner"]
    viewer_id, _ = seeded["viewer"]
    resp = _patch_role(client, wid, viewer_id, "wizard", owner_key)
    assert resp.status_code == 400, resp.text


def test_role_change_target_not_member_404(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    _owner_id, owner_key = seeded["owner"]
    stranger_id, _ = seeded["stranger"]
    resp = _patch_role(client, wid, stranger_id, "editor", owner_key)
    assert resp.status_code == 404, resp.text


def test_role_change_requires_auth_401(rbac_client, seeded):
    client, _ = rbac_client
    wid = seeded["workspace_id"]
    viewer_id, _ = seeded["viewer"]
    resp = client.patch(
        f"/api/v1/me/workspaces/{wid}/members/{viewer_id}/role",
        json={"role": "editor"},
    )
    assert resp.status_code == 401, resp.text
