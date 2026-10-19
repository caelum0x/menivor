"""Spend-controls tests — budget cap enforcement + BYOK consent gate."""

from __future__ import annotations

import hashlib
import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.spend.service import SpendError, SpendPolicyService
from app.domains.wallet.service import WalletService
from app.models.db.base import Base
from app.models.db.marketplace import UsageRecord
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

spend_mod = importlib.import_module("app.domains.spend.router")


@pytest.fixture()
def factory():
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
def uid(factory):
    with factory() as s:
        u = User(email="a@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest())
        s.add(u)
        s.flush()
        out = u.id
        # A wallet account so usage_records can attach.
        WalletService(s)._repo.get_or_create_personal_account(out)
        s.commit()
    return out


def _spend(factory, uid: str, micros: int) -> None:
    with factory() as s:
        account = WalletService(s)._repo.get_personal_account(uid)
        s.add(UsageRecord(account_id=account.id, cost_micros=micros, model_id="m"))
        s.commit()


# --------------------------------------------------------------------------- #
# Budget enforcement
# --------------------------------------------------------------------------- #
def test_unlimited_by_default(factory, uid):
    with factory() as s:
        SpendPolicyService(s).ensure_within_budget(uid, 999_000_000)  # no raise


def test_budget_blocks_when_exceeded(factory, uid):
    with factory() as s:
        SpendPolicyService(s).upsert_policy(uid, monthly_budget_micros=1_000_000)
        s.commit()
    _spend(factory, uid, 800_000)  # already spent $0.80 this month
    with factory() as s:
        svc = SpendPolicyService(s)
        assert svc.period_spend_micros(uid) == 800_000
        svc.ensure_within_budget(uid, 100_000)  # 0.80 + 0.10 <= 1.00 ok
        with pytest.raises(SpendError) as ei:
            svc.ensure_within_budget(uid, 300_000)  # 0.80 + 0.30 > 1.00
        assert ei.value.status_code == 402


def test_reserve_for_job_refused_over_budget(factory, uid):
    # Grant wallet funds so the block is the BUDGET, not the balance.
    from app.models.db.marketplace import PaymentIntent

    with factory() as s:
        svc = WalletService(s)
        acct = svc._repo.get_or_create_personal_account(uid)
        intent = PaymentIntent(
            account_id=acct.id, user_id=uid, idempotency_key="g",
            credit_micros=10_000_000, total_charge_micros=10_000_000, status="pending",
        )
        s.add(intent)
        s.flush()
        svc.confirm_intent(intent.id)
        SpendPolicyService(s).upsert_policy(uid, monthly_budget_micros=500_000)
        s.commit()

    from app.domains.reels.wallet_bridge import WalletBridgeError, WalletIntent, reserve_for_job

    intent = WalletIntent(profile="p", quote={"max_cost_micros": 600_000}, max_cost_micros=600_000)
    with factory() as s:
        with pytest.raises(WalletBridgeError) as ei:
            reserve_for_job(s, user_id=uid, intent=intent, job_id="jobB", request_id="r")
        assert ei.value.status_code == 402  # budget (not balance) blocks it


# --------------------------------------------------------------------------- #
# BYOK consent
# --------------------------------------------------------------------------- #
def test_byok_consent_defaults_off_and_can_enable(factory, uid):
    with factory() as s:
        assert SpendPolicyService(s).byok_allowed(uid) is False
        SpendPolicyService(s).upsert_policy(uid, byok_allowed=True)
        s.commit()
    with factory() as s:
        assert SpendPolicyService(s).byok_allowed(uid) is True


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch, factory):
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

    monkeypatch.setattr(spend_mod, "get_session", _gs)
    monkeypatch.setattr(spend_mod, "_DB_IMPORT_ERROR", None)
    app = FastAPI()
    app.include_router(spend_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app)


# --------------------------------------------------------------------------- #
# BYOK routing fee (pure)
# --------------------------------------------------------------------------- #
def test_byok_fee_math():
    from app.domains.spend import policy as sp

    # Default 10% of the provider cost, with a $0.001 floor.
    assert sp.byok_fee_micros(120_000) == 12_000
    assert sp.byok_fee_micros(0) == 0
    assert sp.byok_fee_micros(1) == sp.byok_min_fee_micros()  # floor applies


def test_byok_fee_disabled(monkeypatch):
    from app.domains.spend import policy as sp

    monkeypatch.setenv("REELFORGE_BYOK_FEE_BPS", "0")
    assert sp.byok_fee_micros(120_000) == 0


# --------------------------------------------------------------------------- #
# Per-workspace budgets
# --------------------------------------------------------------------------- #
def test_workspace_budget_enforced(factory, uid):
    from app.domains.wallet.repository import WalletRepository
    from app.models.db.models import Workspace

    with factory() as s:
        # A workspace wallet account + a $1.00 workspace budget. The workspace
        # principal row must exist first: get_or_create_workspace_account locks
        # the owning Workspace before creating its shared wallet (a wallet can
        # never be minted for a workspace that does not exist).
        s.add(Workspace(id="ws1", name="Acme", owner_id=uid))
        s.flush()
        acct = WalletRepository(s).get_or_create_workspace_account("ws1")
        s.add(UsageRecord(account_id=acct.id, cost_micros=900_000, model_id="m"))
        SpendPolicyService(s).upsert_workspace_policy("ws1", monthly_budget_micros=1_000_000)
        s.commit()
    with factory() as s:
        svc = SpendPolicyService(s)
        view = svc.workspace_policy_view("ws1")
        assert view["scope"] == "workspace"
        assert view["period_spend_micros"] == 900_000
        svc.ensure_within_budget_workspace("ws1", 100_000)  # 0.90 + 0.10 ok
        with pytest.raises(SpendError):
            svc.ensure_within_budget_workspace("ws1", 200_000)  # over $1.00


def test_router_get_and_put(client, uid, factory):
    _ = factory
    headers = {"x-api-key": "k"}
    # Default policy.
    got = client.get("/api/v1/spend/policy", headers=headers)
    assert got.status_code == 200, got.text
    assert got.json()["data"]["monthly_budget_micros"] == 0
    assert got.json()["data"]["byok_allowed"] is False
    # Update.
    put = client.put(
        "/api/v1/spend/policy",
        json={"monthly_budget_micros": 5_000_000, "byok_allowed": True},
        headers=headers,
    )
    assert put.status_code == 200
    assert put.json()["data"]["monthly_budget_micros"] == 5_000_000
    assert put.json()["data"]["byok_allowed"] is True
