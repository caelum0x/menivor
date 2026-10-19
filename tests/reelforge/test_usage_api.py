"""Workspace usage + entitlements v1 API tests (Billing Platform, Epic 3).

Exercises ``app.controllers.v1.usage`` end-to-end over a FastAPI ``TestClient``
with Postgres replaced by in-memory SQLite. No external I/O.

Covered
-------
* TENANT ISOLATION — usage/entitlements are readable only by a MEMBER of the
  workspace; a caller from another workspace gets ``403`` and can never see this
  tenant's rows.
* usage aggregates the tenant's metered rows for a period and reports overage
  vs the plan limit (a metered render beyond the free allotment shows overage).
* entitlements reflect the workspace's LIVE plan (free by default; the active
  plan after a subscription is present).
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

import app.controllers.v1.usage as usage_mod
from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.db.repositories import MeteredUsageRepository, SubscriptionRepository
from app.models.exception import HttpException
from app.services import metering
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

    monkeypatch.setattr(usage_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(usage_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(db_factory):
    """Workspaces A/B; A has an owner + viewer, B has an owner (foreign caller)."""
    Factory = db_factory
    out: dict[str, str] = {}
    with Factory() as s:
        owner_a = User(email="ownerA@ex.com", api_key_hash=_key_hash("ownerA-key"))
        viewer_a = User(email="viewerA@ex.com", api_key_hash=_key_hash("viewerA-key"))
        owner_b = User(email="ownerB@ex.com", api_key_hash=_key_hash("ownerB-key"))
        s.add_all([owner_a, viewer_a, owner_b])
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
        s.commit()
        out = {
            "ws_a": ws_a.id,
            "ws_b": ws_b.id,
            "owner_a_key": "ownerA-key",
            "viewer_a_key": "viewerA-key",
            "owner_b_key": "ownerB-key",
        }
    return out


# --------------------------------------------------------------------------- #
# usage — tenant-scoped aggregate + overage
# --------------------------------------------------------------------------- #
def test_usage_foreign_workspace_forbidden_403(client, seeded):
    tc, _ = client
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/usage",
        headers=_headers(seeded["owner_b_key"]),
    )
    assert resp.status_code == 403, resp.text


def test_usage_aggregates_and_reports_overage(client, seeded):
    tc, Factory = client
    period = metering.current_period_ym()
    # 5 renders in the current period — free plan allots 3 -> overage 2.
    with Factory() as s:
        repo = MeteredUsageRepository(s)
        for i in range(5):
            repo.record(
                workspace_id=seeded["ws_a"],
                metric=metering.METRIC_RENDER,
                quantity=1,
                period_ym=period,
                idempotency_key=f"render:{i}",
            )
        s.commit()

    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/usage",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["period"] == period
    assert data["usage"][metering.METRIC_RENDER] == 5
    render_overage = next(
        o for o in data["overage"] if o["metric"] == metering.METRIC_RENDER
    )
    assert render_overage["used"] == 5
    assert render_overage["limit"] == 3  # free monthly_credits
    assert render_overage["overage"] == 2


def test_usage_other_tenant_rows_never_leak(client, seeded):
    tc, Factory = client
    period = metering.current_period_ym()
    with Factory() as s:
        MeteredUsageRepository(s).record(
            workspace_id=seeded["ws_b"],
            metric=metering.METRIC_RENDER,
            quantity=9,
            period_ym=period,
            idempotency_key="render:b",
        )
        s.commit()
    # A's owner reads A -> sees none of B's usage.
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/usage",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["usage"] == {}


def test_usage_bad_period_400(client, seeded):
    tc, _ = client
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/usage?period=2026",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 400, resp.text


# --------------------------------------------------------------------------- #
# entitlements — reflect the workspace's active plan
# --------------------------------------------------------------------------- #
def test_entitlements_default_free(client, seeded):
    tc, _ = client
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/entitlements",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["plan_key"] == "free"
    assert data["entitlements"]["max_variants"] == 1
    assert data["entitlements"]["sso"] is False


def test_entitlements_reflect_active_plan(client, seeded):
    tc, Factory = client
    with Factory() as s:
        SubscriptionRepository(s).upsert(
            seeded["ws_a"], plan_key="enterprise", status="active"
        )
        s.commit()
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/entitlements",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["plan_key"] == "enterprise"
    assert data["entitlements"]["sso"] is True
    assert data["entitlements"]["max_variants"] == 20


def test_entitlements_foreign_workspace_403(client, seeded):
    tc, _ = client
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/entitlements",
        headers=_headers(seeded["owner_b_key"]),
    )
    assert resp.status_code == 403, resp.text


def test_entitlements_viewer_allowed(client, seeded):
    """Any member (incl. a viewer) may read the tenant's entitlements (read gate)."""
    tc, _ = client
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/entitlements",
        headers=_headers(seeded["viewer_a_key"]),
    )
    assert resp.status_code == 200, resp.text
