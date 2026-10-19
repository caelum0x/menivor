"""MN6: support ledger actions on the admin API.

POST /admin/users/{id}/credits and /admin/jobs/{id}/refund need the support
admin token AND platform staff; each writes one ledger row plus one audit row
with the reason, and is idempotent per (action, ref). Non-admins get 403.
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
import app.models.db.base as db_base
from app.models import const
from app.models.db.base import Base
from app.models.db.models import AuditLog, CreditLedger, Job, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.utils import utils

TOKEN = "s" * 32


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(admin_mod, "get_session", _session)
    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setenv("MENIVOR_SUPPORT_ADMIN_TOKEN", TOKEN)
    app = FastAPI()
    app.include_router(admin_mod.router)
    app.add_exception_handler(
        HttpException,
        lambda request, exc: JSONResponse(status_code=exc.status_code,
                                          content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    with _session() as s:
        staff = User(email="staff@ex.com", api_key_hash=_hash("staff-key"), is_staff=True)
        civ = User(email="civ@ex.com", api_key_hash=_hash("civ-key"), is_staff=False)
        maker = User(email="maker@ex.com")
        s.add_all([staff, civ, maker])
        s.flush()
        CreditRepository(s).grant(maker.id, 5, "purchase:dodo:pay_1")
        job = Job(user_id=maker.id, kind="avatar_reel", state=const.TASK_STATE_COMPLETE)
        s.add(job)
        s.flush()
        CreditRepository(s).debit(maker.id, 1, job.id, "job_debit")
        ids = {"staff": staff.id, "civ": civ.id, "maker": maker.id, "job": job.id}
    return TestClient(app), Factory, ids


def _h(key: str = "staff-key", token: str | None = TOKEN) -> dict[str, str]:
    headers = {"x-api-key": key}
    if token is not None:
        headers["x-admin-token"] = token
    return headers


def _audit(Factory, action):
    with Factory() as s:
        return list(s.execute(select(AuditLog).where(AuditLog.action == action)).scalars())


def test_grant_writes_one_ledger_and_audit_row_and_replays(env):
    client, Factory, ids = env
    body = {"amount": 3, "reason": "Render bug on ticket 812", "ref": "T-812"}
    first = client.post(f"/api/v1/admin/users/{ids['maker']}/credits", json=body, headers=_h())
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["delta"] == 3 and data["balance_after"] == 7 and data["replayed"] is False
    again = client.post(f"/api/v1/admin/users/{ids['maker']}/credits", json=body, headers=_h())
    assert again.json()["data"]["replayed"] is True
    with Factory() as s:
        rows = list(s.execute(select(CreditLedger).where(CreditLedger.reason == "support:credits:T-812")).scalars())
        assert len(rows) == 1
        assert CreditRepository(s).balance(ids["maker"]) == 7
    audits = _audit(Factory, "support.credits_adjusted")
    assert len(audits) == 1
    assert audits[0].actor_user_id == ids["staff"]
    assert audits[0].meta["reason"] == "Render bug on ticket 812"


def test_ref_reuse_with_other_amount_conflicts(env):
    client, _, ids = env
    url = f"/api/v1/admin/users/{ids['maker']}/credits"
    assert client.post(url, json={"amount": 2, "reason": "goodwill", "ref": "T-1"}, headers=_h()).status_code == 200
    assert client.post(url, json={"amount": 5, "reason": "goodwill", "ref": "T-1"}, headers=_h()).status_code == 409


def test_removal_never_goes_below_zero(env):
    client, Factory, ids = env
    url = f"/api/v1/admin/users/{ids['maker']}/credits"
    assert client.post(url, json={"amount": -9, "reason": "chargeback", "ref": "T-2"}, headers=_h()).status_code == 409
    ok = client.post(url, json={"amount": -4, "reason": "duplicate grant", "ref": "T-3"}, headers=_h())
    assert ok.status_code == 200 and ok.json()["data"]["balance_after"] == 0


def test_bad_input_is_rejected(env):
    client, _, ids = env
    url = f"/api/v1/admin/users/{ids['maker']}/credits"
    assert client.post(url, json={"amount": 0, "reason": "zero", "ref": "T-4"}, headers=_h()).status_code == 400
    assert client.post(url, json={"amount": 1, "reason": "ok ok", "ref": "bad ref!"}, headers=_h()).status_code == 400
    assert client.post(url, json={"amount": 5000, "reason": "big", "ref": "T-5"}, headers=_h()).status_code == 422
    missing = "/api/v1/admin/users/nope/credits"
    assert client.post(missing, json={"amount": 1, "reason": "ghost", "ref": "T-6"}, headers=_h()).status_code == 404


def test_job_refund_once_with_audit(env):
    client, Factory, ids = env
    url = f"/api/v1/admin/jobs/{ids['job']}/refund"
    first = client.post(url, json={"reason": "Voice glitch at 0:12"}, headers=_h())
    assert first.status_code == 200, first.text
    assert first.json()["data"]["delta"] == 1 and first.json()["data"]["balance_after"] == 5
    again = client.post(url, json={"reason": "Voice glitch at 0:12"}, headers=_h())
    assert again.status_code == 200 and again.json()["data"]["replayed"] is True
    with Factory() as s:
        assert CreditRepository(s).balance(ids["maker"]) == 5
    assert len(_audit(Factory, "support.job_refunded")) == 1
    assert client.post("/api/v1/admin/jobs/nope/refund", json={"reason": "ghost"}, headers=_h()).status_code == 404


def test_job_already_refunded_by_the_system_conflicts(env):
    client, Factory, ids = env
    from app.domains.reels import refunds

    assert refunds.refund_latest_debit_once(ids["job"], "reel_failed_refund") == 1
    resp = client.post(f"/api/v1/admin/jobs/{ids['job']}/refund", json={"reason": "double"}, headers=_h())
    assert resp.status_code == 409


@pytest.mark.parametrize("key,token,status", [
    ("civ-key", TOKEN, 403),        # token but not staff
    ("staff-key", None, 403),       # staff but no token
    ("staff-key", "x" * 32, 403),   # wrong token
    ("civ-key", None, 403),
])
def test_non_admins_get_403_and_nothing_changes(env, key, token, status):
    client, Factory, ids = env
    body = {"amount": 50, "reason": "free money", "ref": "hack"}
    assert client.post(f"/api/v1/admin/users/{ids['maker']}/credits", json=body,
                       headers=_h(key, token)).status_code == status
    assert client.post(f"/api/v1/admin/jobs/{ids['job']}/refund", json={"reason": "free"},
                       headers=_h(key, token)).status_code == status
    with Factory() as s:
        assert CreditRepository(s).balance(ids["maker"]) == 4


def test_unconfigured_token_disables_support_actions(env, monkeypatch):
    client, _, ids = env
    monkeypatch.setenv("MENIVOR_SUPPORT_ADMIN_TOKEN", "short")
    resp = client.post(f"/api/v1/admin/users/{ids['maker']}/credits",
                       json={"amount": 1, "reason": "goodwill", "ref": "T-9"}, headers=_h(token="short"))
    assert resp.status_code == 503
