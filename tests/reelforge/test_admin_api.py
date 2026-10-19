"""Platform-admin v1 API tests (Access & Governance, Epic 1).

Exercises ``app.controllers.v1.admin`` end-to-end over a FastAPI ``TestClient``
with in-memory SQLite. No external I/O.

Scenarios covered
-----------------
* every ``/admin/*`` route is HARD-GATED on ``User.is_staff``: a non-staff caller
  gets ``403`` for listing AND impersonation
* a staff caller lists users / workspaces / jobs across every tenant (``200``)
* a workspace owner is NOT a platform admin (``403``)
* ``POST /admin/impersonate`` mints a time-boxed token AND writes an append-only
  ``admin.impersonated`` audit row
* impersonating an unknown target -> ``400``
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

import app.controllers.v1.admin as admin_mod
from app.models.db.base import Base
from app.models.db.models import AuditLog, Job, User, Workspace
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
def admin_client(monkeypatch, db_factory):
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

    monkeypatch.setattr(admin_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(admin_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(db_factory):
    """Seed a staff operator, a civilian, a workspace owner, and some data.

    Returns ``label -> (user_id, raw_key)`` plus a couple of ids.
    """
    Factory = db_factory
    out: dict[str, object] = {}
    with Factory() as s:
        staff = User(
            email="staff@ex.com", api_key_hash=_key_hash("staff-key"), is_staff=True
        )
        civilian = User(
            email="civ@ex.com", api_key_hash=_key_hash("civ-key"), is_staff=False
        )
        owner = User(
            email="owner@ex.com", api_key_hash=_key_hash("owner-key"), is_staff=False
        )
        target = User(email="target@ex.com", is_staff=False)
        s.add_all([staff, civilian, owner, target])
        s.flush()
        ws = Workspace(owner_id=owner.id, name="Acme")
        s.add(ws)
        s.flush()
        job = Job(user_id=owner.id, kind="avatar_reel", params={})
        s.add(job)
        s.flush()
        out["staff"] = (staff.id, "staff-key")
        out["civilian"] = (civilian.id, "civ-key")
        out["owner"] = (owner.id, "owner-key")
        out["target"] = (target.id, None)
        out["workspace_id"] = ws.id
        out["job_id"] = job.id
        s.commit()
    return out


# =========================================================================== #
# Staff gate — non-staff rejected everywhere
# =========================================================================== #
@pytest.mark.parametrize("path", ["/admin/users", "/admin/workspaces", "/admin/jobs"])
def test_non_staff_listing_forbidden_403(admin_client, seeded, path):
    c, _ = admin_client
    _civ_id, civ_key = seeded["civilian"]
    resp = c.get(f"/api/v1{path}", headers=_headers(civ_key))
    assert resp.status_code == 403, resp.text


def test_workspace_owner_is_not_platform_admin_403(admin_client, seeded):
    """Platform-admin is separate from workspace roles: an owner is not staff."""
    c, _ = admin_client
    _owner_id, owner_key = seeded["owner"]
    resp = c.get("/api/v1/admin/users", headers=_headers(owner_key))
    assert resp.status_code == 403, resp.text


def test_non_staff_impersonate_forbidden_403(admin_client, seeded):
    c, _ = admin_client
    _civ_id, civ_key = seeded["civilian"]
    target_id, _ = seeded["target"]
    resp = c.post(
        "/api/v1/admin/impersonate",
        json={"user_id": target_id},
        headers=_headers(civ_key),
    )
    assert resp.status_code == 403, resp.text


# =========================================================================== #
# Staff — cross-tenant listing
# =========================================================================== #
def test_staff_lists_users(admin_client, seeded):
    c, _ = admin_client
    _staff_id, staff_key = seeded["staff"]
    resp = c.get("/api/v1/admin/users?limit=100", headers=_headers(staff_key))
    assert resp.status_code == 200, resp.text
    emails = {u["email"] for u in resp.json()["data"]}
    assert {"staff@ex.com", "civ@ex.com", "owner@ex.com"} <= emails
    staff_row = next(u for u in resp.json()["data"] if u["email"] == "staff@ex.com")
    assert staff_row["is_staff"] is True


def test_staff_lists_workspaces(admin_client, seeded):
    c, _ = admin_client
    _staff_id, staff_key = seeded["staff"]
    wid = seeded["workspace_id"]
    resp = c.get("/api/v1/admin/workspaces?limit=100", headers=_headers(staff_key))
    assert resp.status_code == 200, resp.text
    assert wid in {w["id"] for w in resp.json()["data"]}


def test_staff_lists_jobs(admin_client, seeded):
    c, _ = admin_client
    _staff_id, staff_key = seeded["staff"]
    jid = seeded["job_id"]
    resp = c.get("/api/v1/admin/jobs?limit=100", headers=_headers(staff_key))
    assert resp.status_code == 200, resp.text
    assert jid in {j["id"] for j in resp.json()["data"]}


# =========================================================================== #
# Impersonation — audited + time-boxed
# =========================================================================== #
def test_staff_impersonate_mints_token_and_audits(admin_client, seeded):
    c, Factory = admin_client
    staff_id, staff_key = seeded["staff"]
    target_id, _ = seeded["target"]

    resp = c.post(
        "/api/v1/admin/impersonate",
        json={"user_id": target_id},
        headers=_headers(staff_key),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["token"]
    assert data["admin_user_id"] == staff_id
    assert data["target_user_id"] == target_id
    assert data["scope"] == f"impersonate:{target_id}"
    assert data["expires_in"] > 0

    # Exactly one append-only audit row for the impersonation.
    with Factory() as s:
        rows = s.execute(select(AuditLog)).scalars().all()
        imp = [r for r in rows if r.action == "admin.impersonated"]
        assert len(imp) == 1
        assert imp[0].actor_user_id == staff_id
        assert imp[0].target_id == target_id


def test_impersonate_unknown_target_400(admin_client, seeded):
    c, Factory = admin_client
    _staff_id, staff_key = seeded["staff"]
    resp = c.post(
        "/api/v1/admin/impersonate",
        json={"user_id": "ghost-user"},
        headers=_headers(staff_key),
    )
    assert resp.status_code == 400, resp.text
    # A rejected impersonation writes no audit row.
    with Factory() as s:
        rows = s.execute(select(AuditLog)).scalars().all()
        assert [r for r in rows if r.action == "admin.impersonated"] == []


def test_non_staff_impersonate_writes_no_audit(admin_client, seeded):
    c, Factory = admin_client
    _civ_id, civ_key = seeded["civilian"]
    target_id, _ = seeded["target"]
    resp = c.post(
        "/api/v1/admin/impersonate",
        json={"user_id": target_id},
        headers=_headers(civ_key),
    )
    assert resp.status_code == 403, resp.text
    with Factory() as s:
        rows = s.execute(select(AuditLog)).scalars().all()
        assert [r for r in rows if r.action == "admin.impersonated"] == []


# =========================================================================== #
# Auth
# =========================================================================== #
def test_admin_listing_requires_auth_401(admin_client, seeded):
    c, _ = admin_client
    resp = c.get("/api/v1/admin/users")
    assert resp.status_code == 401, resp.text


def test_admin_impersonate_requires_auth_401(admin_client, seeded):
    c, _ = admin_client
    target_id, _ = seeded["target"]
    resp = c.post("/api/v1/admin/impersonate", json={"user_id": target_id})
    assert resp.status_code == 401, resp.text
