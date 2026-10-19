"""Workspace-funded reserve/settle + marketplace usage analytics."""

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

from app.domains.insights.usage import UsageAnalyticsService
from app.domains.reels import wallet_bridge as bridge
from app.domains.wallet.service import WalletService
from app.models.db.base import Base
from app.models.db.marketplace import PaymentIntent, UsageRecord
from app.models.db.models import Job, User
from app.models.exception import HttpException
from app.utils import utils

usage_mod = importlib.import_module("app.domains.insights.usage_router")


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture()
def uid(factory):
    with factory() as s:
        u = User(email="a@example.com", api_key_hash="k")
        s.add(u)
        s.flush()
        out = u.id
        s.commit()
    return out


def _make_workspace(factory, owner_id: str, micros: int) -> str:
    """Create a real workspace owned by ``owner_id`` and fund its shared pool."""
    from app.services import workspaces as ws_service

    with factory() as s:
        ws = ws_service.create_workspace(s, owner_id, "Acme")
        wid = ws.id
        svc = WalletService(s)
        acct = svc._repo.get_or_create_workspace_account(wid)
        intent = PaymentIntent(
            account_id=acct.id, user_id=owner_id, idempotency_key=f"ws{micros}",
            credit_micros=micros, total_charge_micros=micros, status="pending",
        )
        s.add(intent)
        s.flush()
        svc.confirm_intent(intent.id)
        s.commit()
    return wid


# --------------------------------------------------------------------------- #
# Workspace-funded reservation lifecycle
# --------------------------------------------------------------------------- #
def test_workspace_reserve_settle_uses_shared_pool(factory, uid):
    wid = _make_workspace(factory, uid, 5_000_000)
    intent = bridge.WalletIntent(
        profile="p", quote={"max_cost_micros": 1_000_000},
        max_cost_micros=1_000_000, workspace_id=wid,
    )
    with factory() as s:
        marker = bridge.reserve_for_job(
            s, user_id=uid, intent=intent, job_id="jobW", request_id="r"
        )
        s.add(Job(id="jobW", user_id=uid, kind="reel", params=marker))
        s.commit()
    assert marker["_wallet"]["workspace_id"] == wid

    with factory() as s:
        wsbal = WalletService(s).balance_view(uid, workspace_id=wid)
        assert wsbal["available_micros"] == 4_000_000
        assert wsbal["reserved_micros"] == 1_000_000
        # The user's personal wallet was NOT touched.
        assert WalletService(s).balance_view(uid)["reserved_micros"] == 0

    # Record actual $0.40 + settle -> workspace pool charged, remainder released.
    with factory() as s:
        bridge.record_actual_micros(s, job_id="jobW", actual_micros=400_000)
        s.commit()
    with factory() as s:
        job = s.get(Job, "jobW")
        bridge.settle_job(s, user_id=uid, job_id="jobW", params=job.params)
        s.commit()
    with factory() as s:
        wsbal = WalletService(s).balance_view(uid, workspace_id=wid)
        assert wsbal["reserved_micros"] == 0
        assert wsbal["available_micros"] == 4_000_000 + (1_000_000 - 400_000)


def test_workspace_reserve_insufficient_pool_402(factory, uid):
    wid = _make_workspace(factory, uid, 100_000)  # only $0.10
    intent = bridge.WalletIntent(
        profile="p", quote={"max_cost_micros": 500_000},
        max_cost_micros=500_000, workspace_id=wid,
    )
    with factory() as s:
        with pytest.raises(bridge.WalletBridgeError) as ei:
            bridge.reserve_for_job(s, user_id=uid, intent=intent, job_id="jx", request_id="r")
        assert ei.value.status_code == 402


def test_extract_intent_captures_workspace():
    intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "p", "quote": {"max_cost_micros": 5}, "workspace_id": "wsX"}
    )
    assert intent.workspace_id == "wsX"


def test_workspace_checkout_funds_shared_pool(factory, uid):
    """A workspace top-up creates a workspace-account intent; confirm grants the pool."""
    from app.services import workspaces as ws_service

    with factory() as s:
        wid = ws_service.create_workspace(s, uid, "Acme").id
        s.commit()

    def _factory(intent):
        return {"checkout_url": "https://creem/ws", "session_id": "cs_ws"}

    with factory() as s:
        view = WalletService(s).create_checkout(
            uid,
            amount_usd="20.00",
            provider="creem",
            idempotency_key="wschk",
            session_factory=_factory,
            workspace_id=wid,
        )
        s.commit()
    assert view["checkout_url"] == "https://creem/ws"

    # The intent is on the WORKSPACE account; confirming it grants the pool.
    with factory() as s:
        from app.models.db.marketplace import PaymentIntent

        acct = WalletService(s)._repo.get_workspace_account(wid)
        intent = (
            s.query(PaymentIntent).filter(PaymentIntent.account_id == acct.id).first()
        )
        assert intent is not None
        WalletService(s).confirm_intent(intent.id)
        s.commit()
    with factory() as s:
        wsbal = WalletService(s).balance_view(uid, workspace_id=wid)
        assert wsbal["available_micros"] == 20_000_000
        # The actor's personal wallet was NOT credited.
        assert WalletService(s).balance_view(uid)["available_micros"] == 0


# --------------------------------------------------------------------------- #
# Usage analytics drill-down
# --------------------------------------------------------------------------- #
def _usage(factory, account_id, model, provider, stage, cost):
    with factory() as s:
        s.add(
            UsageRecord(
                account_id=account_id, model_id=model, provider_key=provider,
                stage=stage, cost_micros=cost, quantity_units=1,
            )
        )
        s.commit()


def test_usage_summary_attribution(factory, uid):
    with factory() as s:
        acct = WalletService(s)._repo.get_or_create_personal_account(uid)
        aid = acct.id
        s.commit()
    _usage(factory, aid, "pixelle/wan-i2v", "pixelle", "broll", 120_000)
    _usage(factory, aid, "pixelle/wan-i2v", "pixelle", "broll", 80_000)
    _usage(factory, aid, "elevenlabs/v2", "elevenlabs", "voice", 30_000)

    with factory() as s:
        summary = UsageAnalyticsService(s).summary(uid, days=30)
    assert summary["total_cost_micros"] == 230_000
    assert summary["total_cost_usd"] == "0.23"
    # by_model, ordered by cost desc.
    assert summary["by_model"][0]["key"] == "pixelle/wan-i2v"
    assert summary["by_model"][0]["cost_micros"] == 200_000
    assert summary["by_model"][0]["runs"] == 2
    by_provider = {r["key"]: r["cost_micros"] for r in summary["by_provider"]}
    assert by_provider == {"pixelle": 200_000, "elevenlabs": 30_000}
    by_stage = {r["key"]: r["cost_micros"] for r in summary["by_stage"]}
    assert by_stage == {"broll": 200_000, "voice": 30_000}
    assert len(summary["by_day"]) == 1


def test_usage_summary_empty_when_no_account(factory, uid):
    with factory() as s:
        summary = UsageAnalyticsService(s).summary(uid, days=7)
    assert summary["total_cost_micros"] == 0
    assert summary["by_model"] == []


# --------------------------------------------------------------------------- #
# Usage router
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch, factory):
    import hashlib

    with factory() as s:
        u = User(email="c@example.com", api_key_hash=hashlib.sha256(b"ck").hexdigest())
        s.add(u)
        s.flush()
        acct = WalletService(s)._repo.get_or_create_personal_account(u.id)
        s.add(UsageRecord(account_id=acct.id, model_id="m", provider_key="p", stage="broll", cost_micros=50_000))
        s.commit()

    @contextmanager
    def _gs():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(usage_mod, "get_session", _gs)
    monkeypatch.setattr(usage_mod, "_DB_IMPORT_ERROR", None)
    app = FastAPI()
    app.include_router(usage_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app)


def test_usage_router_returns_summary(client):
    resp = client.get("/api/v1/insights/usage?days=30", headers={"x-api-key": "ck"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total_cost_micros"] == 50_000
    assert data["by_stage"][0]["key"] == "broll"
