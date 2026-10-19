"""Workspace invoices + platform revenue v1 API tests (Billing Platform, Epic 3).

Exercises ``app.controllers.v1.invoices`` end-to-end over a FastAPI ``TestClient``
with Postgres replaced by in-memory SQLite. No external I/O.

Covered
-------
* invoices are WORKSPACE-SCOPED and ``billing.manage``-gated — a ``viewer`` gets
  ``403``, a caller from another workspace can never receive these invoices, and a
  listing returns only the owning tenant's rows (integer-cent amounts + lines).
* ``GET /admin/revenue`` is HARD-GATED on ``is_staff`` — a non-staff caller gets
  ``403``; a staff caller receives the cross-tenant revenue summary.
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

import app.controllers.v1.invoices as inv_mod
from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.db.repositories import InvoiceRepository
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

    monkeypatch.setattr(inv_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(inv_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(db_factory):
    """Workspaces A/B (+ invoices each), an owner + viewer in A, plus a staff user."""
    Factory = db_factory
    out: dict[str, str] = {}
    with Factory() as s:
        owner_a = User(email="ownerA@ex.com", api_key_hash=_key_hash("ownerA-key"))
        viewer_a = User(email="viewerA@ex.com", api_key_hash=_key_hash("viewerA-key"))
        owner_b = User(email="ownerB@ex.com", api_key_hash=_key_hash("ownerB-key"))
        staff = User(
            email="staff@ex.com", api_key_hash=_key_hash("staff-key"), is_staff=True
        )
        s.add_all([owner_a, viewer_a, owner_b, staff])
        s.flush()
        ws_a = Workspace(owner_id=owner_a.id, name="Acme-A")
        ws_b = Workspace(owner_id=owner_b.id, name="Beta-B")
        s.add_all([ws_a, ws_b])
        s.flush()
        s.add_all(
            [
                WorkspaceMember(workspace_id=ws_a.id, user_id=owner_a.id, role="owner"),
                WorkspaceMember(workspace_id=ws_a.id, user_id=viewer_a.id, role="viewer"),
                WorkspaceMember(workspace_id=ws_b.id, user_id=owner_b.id, role="owner"),
            ]
        )
        s.flush()
        repo = InvoiceRepository(s)
        repo.create(
            workspace_id=ws_a.id,
            line_items=[
                {"description": "render overage", "quantity": 2, "amount_cents": 400},
            ],
            status="paid",
        )
        repo.create(
            workspace_id=ws_b.id,
            line_items=[
                {"description": "render overage", "quantity": 3, "amount_cents": 900},
            ],
            status="paid",
        )
        s.commit()
        out = {
            "ws_a": ws_a.id,
            "ws_b": ws_b.id,
            "owner_a_key": "ownerA-key",
            "viewer_a_key": "viewerA-key",
            "owner_b_key": "ownerB-key",
            "staff_key": "staff-key",
        }
    return out


# --------------------------------------------------------------------------- #
# invoices — workspace-scoped, billing.manage gated
# --------------------------------------------------------------------------- #
def test_invoices_owner_lists_own_only(client, seeded):
    tc, _ = client
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/invoices",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["workspace_id"] == seeded["ws_a"]
    assert rows[0]["amount_cents"] == 400  # exact integer sum of the lines
    assert rows[0]["status"] == "paid"
    assert rows[0]["line_items"][0]["amount_cents"] == 400


def test_invoices_viewer_forbidden_403(client, seeded):
    tc, _ = client
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/invoices",
        headers=_headers(seeded["viewer_a_key"]),
    )
    assert resp.status_code == 403, resp.text


def test_invoices_foreign_workspace_forbidden_403(client, seeded):
    tc, _ = client
    # Owner of B cannot list A's invoices.
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/invoices",
        headers=_headers(seeded["owner_b_key"]),
    )
    assert resp.status_code == 403, resp.text


def test_invoices_requires_auth_401(client, seeded):
    tc, _ = client
    resp = tc.get(f"/api/v1/me/workspaces/{seeded['ws_a']}/invoices")
    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------- #
# /admin/revenue — is_staff ONLY
# --------------------------------------------------------------------------- #
def test_revenue_non_staff_forbidden_403(client, seeded):
    tc, _ = client
    resp = tc.get(
        "/api/v1/admin/revenue", headers=_headers(seeded["owner_a_key"])
    )
    assert resp.status_code == 403, resp.text


def test_revenue_staff_gets_cross_tenant_summary(client, seeded):
    tc, _ = client
    resp = tc.get("/api/v1/admin/revenue", headers=_headers(seeded["staff_key"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # Cross-tenant realized revenue: 400 (A) + 900 (B) = 1300 cents.
    assert data["revenue_cents"] == 1300
    assert data["net_cents"] == 1300


def test_revenue_requires_auth_401(client, seeded):
    tc, _ = client
    resp = tc.get("/api/v1/admin/revenue")
    assert resp.status_code == 401, resp.text
