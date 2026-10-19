"""Shared Workspace Credits — v1 API tests.

Exercises the SHARED credit pool wiring across
``app.controllers.v1.workspaces`` (grant + read pool) and
``app.controllers.v1.jobs`` (a member creating a job that debits the workspace
pool instead of their personal balance), end-to-end over a FastAPI
``TestClient`` with Postgres replaced by in-memory SQLite. No external I/O.

Both routers are mounted on one app and share a single in-memory engine, so a
grant issued through the workspaces controller is visible to the jobs
controller. Identity is switched per request via the ``x-api-key`` header
(SHA-256 stored as ``User.api_key_hash``), so the same client can act as the
workspace owner, an invited member, or a stranger by swapping the header —
mirroring how the real auth gate resolves the caller.

Scenarios covered
-----------------
* admin grants credits to a workspace pool, then a MEMBER creates a job with
  ``workspace_id`` and the WORKSPACE pool is debited (the member's personal
  balance is untouched, and the job is enqueued exactly once)
* a non-member creating a job against the pool -> ``403`` (no debit, no enqueue)
* an insufficient pool -> ``402`` (no enqueue, no orphan job)
* a plain member cannot grant -> ``403``
* reading the pool balance as a member; a stranger -> ``403``
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

import app.controllers.v1.jobs as jobs_mod
import app.controllers.v1.workspaces as ws_mod
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository, JobRepository
from app.models.exception import HttpException
from app.utils import utils


@pytest.fixture(autouse=True)
def _presenter_ai_video_priced_elsewhere(monkeypatch):
    """These tests cover standard-credit plumbing on the default presenter layout.

    The AI-video price a presenter reel reserves (3x provider cost, never
    standard credits) is covered by ``test_premium_credits.py``; here it is 0.
    """
    from app.domains.reels import premium

    monkeypatch.setattr(premium, "ai_video_credits_needed", lambda params: 0)
    # M3.1 presenter plan rules (Pro+, 5 credits, monthly cap) are covered by
    # test_reel_pricing.py; here a presenter reel is a plain 1-credit reel.
    from app.domains.reels import policy as _reel_policy

    monkeypatch.setattr(_reel_policy, "require_presenter_allowed", lambda *a, **k: None)
    monkeypatch.setenv("MENIVOR_PRESENTER_CREDITS", "1")


_PARAMS = {"video_subject": "cats"}


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


class _FakePipeline:
    """Records enqueue calls; ``start`` / ``retry`` can be made to raise."""

    def __init__(self) -> None:
        self.start_calls: list = []
        self.retry_calls: list = []
        self.raise_on_start = False
        self.raise_on_retry = False

    def start_pipeline(self, job_id, params):
        self.start_calls.append((job_id, params))
        if self.raise_on_start:
            raise RuntimeError("broker down")
        return "celery-start-id"

    def retry_pipeline(self, job_id, params, failed_stage):
        self.retry_calls.append((job_id, params, failed_stage))
        if self.raise_on_retry:
            raise RuntimeError("broker down")
        return "celery-retry-id"


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture()
def env(monkeypatch):
    """One app with BOTH routers wired to a shared in-memory SQLite DB."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )

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

    fake_pipeline = _FakePipeline()

    # Both controllers imported ``get_session`` into their own namespaces.
    monkeypatch.setattr(jobs_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(ws_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(jobs_mod, "_import_pipeline", lambda rid: fake_pipeline)
    # Skip external feature-secret validation so the credit + enqueue logic
    # under test is isolated from HeyGen/ElevenLabs config.
    monkeypatch.setattr(
        jobs_mod, "_validate_enabled_feature_secrets", lambda params, rid: None
    )

    app = FastAPI()
    app.include_router(jobs_mod.router)
    app.include_router(ws_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory, fake_pipeline


@pytest.fixture()
def users(env):
    """Seed three users; return {label: (user_id, raw_key)}."""
    _client, Factory, _pipeline = env
    seeded: dict[str, tuple[str, str]] = {}
    specs = {
        "owner": ("owner@example.com", "owner-key"),
        "member": ("member@example.com", "member-key"),
        "stranger": ("stranger@example.com", "stranger-key"),
    }
    with Factory() as s:
        for label, (email, raw) in specs.items():
            # The owner doubles as platform staff: minting pool credits is a
            # staff-only action (see test_non_staff_owner_cannot_mint_pool_credits).
            u = User(email=email, api_key_hash=_key_hash(raw), credits=0, is_staff=(label == "owner"))
            s.add(u)
            s.flush()
            seeded[label] = (u.id, raw)
        s.commit()
    return seeded


# =========================================================================== #
# Helpers
# =========================================================================== #
def _create_workspace(client, raw_key: str, name: str = "Acme Studio") -> str:
    resp = client.post(
        "/api/v1/workspaces", json={"name": name}, headers=_headers(raw_key)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


def _invite(client, owner_key: str, wid: str, email: str, role: str | None = None):
    body: dict = {"email": email}
    if role is not None:
        body["role"] = role
    return client.post(
        f"/api/v1/workspaces/{wid}/invite", json=body, headers=_headers(owner_key)
    )


def _grant(client, key: str, wid: str, amount: int, reason: str | None = None):
    body: dict = {"amount": amount}
    if reason is not None:
        body["reason"] = reason
    return client.post(
        f"/api/v1/workspaces/{wid}/credits/grant", json=body, headers=_headers(key)
    )


def _personal_balance(Factory, user_id: str) -> int:
    with Factory() as s:
        return CreditRepository(s).balance(user_id)


def _pool_balance(Factory, workspace_id: str) -> int:
    with Factory() as s:
        return CreditRepository(s).workspace_balance(workspace_id)


def _create_job(client, key: str, workspace_id: str | None = None, variants: int = 1):
    body: dict = {"params": _PARAMS, "variants": variants}
    if workspace_id is not None:
        body["workspace_id"] = workspace_id
    return client.post("/api/v1/jobs", json=body, headers=_headers(key))


# =========================================================================== #
# Grant -> read pool
# =========================================================================== #
def test_admin_grant_credits_and_read_pool_balance(env, users):
    client, Factory, _pipeline = env
    _owner_id, owner_key = users["owner"]
    wid = _create_workspace(client, owner_key)

    resp = _grant(client, owner_key, wid, 100, reason="seed")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["balance"] == 100
    assert _pool_balance(Factory, wid) == 100

    # Any member (here the owner) can read the pool.
    read = client.get(
        f"/api/v1/workspaces/{wid}/credits", headers=_headers(owner_key)
    )
    assert read.status_code == 200, read.text
    assert read.json()["data"]["balance"] == 100


def test_plain_member_cannot_grant_403(env, users):
    client, Factory, _pipeline = env
    _owner_id, owner_key = users["owner"]
    _member_id, member_key = users["member"]
    wid = _create_workspace(client, owner_key)
    assert _invite(client, owner_key, wid, "member@example.com").status_code == 200

    resp = _grant(client, member_key, wid, 50)
    assert resp.status_code == 403, resp.text
    assert _pool_balance(Factory, wid) == 0


def test_non_staff_owner_cannot_mint_pool_credits(env, users):
    """Any user can create a workspace and own it; that must not mint credits."""
    client, Factory, _pipeline = env
    _stranger_id, stranger_key = users["stranger"]
    wid = _create_workspace(client, stranger_key, name="Free Credits Inc")

    resp = _grant(client, stranger_key, wid, 1000)
    assert resp.status_code == 403, resp.text
    assert resp.json()["data"]["code"] == "pool_grant_staff_only"
    assert _pool_balance(Factory, wid) == 0


def test_grant_non_positive_amount_400(env, users):
    client, _Factory, _pipeline = env
    _owner_id, owner_key = users["owner"]
    wid = _create_workspace(client, owner_key)

    resp = _grant(client, owner_key, wid, 0)
    assert resp.status_code == 400, resp.text


def test_read_pool_stranger_403(env, users):
    client, _Factory, _pipeline = env
    _owner_id, owner_key = users["owner"]
    _stranger_id, stranger_key = users["stranger"]
    wid = _create_workspace(client, owner_key)

    resp = client.get(
        f"/api/v1/workspaces/{wid}/credits", headers=_headers(stranger_key)
    )
    assert resp.status_code == 403, resp.text


def test_read_pool_unknown_workspace_404(env, users):
    client, _Factory, _pipeline = env
    _owner_id, owner_key = users["owner"]
    resp = client.get(
        "/api/v1/workspaces/does-not-exist/credits", headers=_headers(owner_key)
    )
    assert resp.status_code == 404, resp.text


# =========================================================================== #
# Member creates a job against the shared pool
# =========================================================================== #
def test_member_job_debits_workspace_pool_not_personal(env, users):
    client, Factory, pipeline = env
    _owner_id, owner_key = users["owner"]
    member_id, member_key = users["member"]
    wid = _create_workspace(client, owner_key)
    assert _invite(client, owner_key, wid, "member@example.com").status_code == 200

    # Fund the shared pool; the member has ZERO personal credits.
    assert _grant(client, owner_key, wid, 10).status_code == 200
    assert _personal_balance(Factory, member_id) == 0

    resp = _create_job(client, member_key, workspace_id=wid)
    assert resp.status_code == 200, resp.text

    assert len(pipeline.start_calls) == 1              # enqueued exactly once
    assert _pool_balance(Factory, wid) == 9            # WORKSPACE pool debited
    assert _personal_balance(Factory, member_id) == 0  # personal untouched


def test_member_job_variants_debit_pool_n_times(env, users):
    client, Factory, pipeline = env
    _owner_id, owner_key = users["owner"]
    _member_id, member_key = users["member"]
    wid = _create_workspace(client, owner_key)
    assert _invite(client, owner_key, wid, "member@example.com").status_code == 200
    assert _grant(client, owner_key, wid, 10).status_code == 200

    resp = _create_job(client, member_key, workspace_id=wid, variants=3)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["data"]["job_ids"]) == 3
    assert len(pipeline.start_calls) == 3
    assert _pool_balance(Factory, wid) == 7            # 10 - 3 × 1


def test_non_member_job_against_pool_403_no_debit_no_enqueue(env, users):
    client, Factory, pipeline = env
    _owner_id, owner_key = users["owner"]
    _stranger_id, stranger_key = users["stranger"]
    wid = _create_workspace(client, owner_key)
    assert _grant(client, owner_key, wid, 10).status_code == 200

    resp = _create_job(client, stranger_key, workspace_id=wid)
    assert resp.status_code == 403, resp.text
    assert pipeline.start_calls == []                  # never enqueued
    assert _pool_balance(Factory, wid) == 10           # pool untouched


def test_insufficient_pool_402_no_enqueue(env, users):
    client, Factory, pipeline = env
    _owner_id, owner_key = users["owner"]
    member_id, member_key = users["member"]
    wid = _create_workspace(client, owner_key)
    assert _invite(client, owner_key, wid, "member@example.com").status_code == 200
    # Pool is empty — no grant issued.

    resp = _create_job(client, member_key, workspace_id=wid)
    assert resp.status_code == 402, resp.text
    assert pipeline.start_calls == []                  # never enqueued
    assert _pool_balance(Factory, wid) == 0            # nothing debited

    # No orphan job for the member either.
    from app.models.db.repositories import JobRepository

    with Factory() as s:
        assert JobRepository(s).list_for_user(member_id) == []


def test_pool_debit_refunded_on_enqueue_failure(env, users):
    client, Factory, pipeline = env
    _owner_id, owner_key = users["owner"]
    _member_id, member_key = users["member"]
    wid = _create_workspace(client, owner_key)
    assert _invite(client, owner_key, wid, "member@example.com").status_code == 200
    assert _grant(client, owner_key, wid, 10).status_code == 200

    pipeline.raise_on_start = True
    resp = _create_job(client, member_key, workspace_id=wid)
    assert resp.status_code == 502, resp.text
    # The debit was committed before enqueue, then refunded back to the POOL.
    assert _pool_balance(Factory, wid) == 10


def test_no_workspace_id_uses_personal_balance(env, users):
    """A plain job (no workspace_id) still debits the caller's personal pool."""
    client, Factory, pipeline = env
    member_id, member_key = users["member"]
    with Factory() as s:
        CreditRepository(s).grant(member_id, 5, reason="signup")
        s.commit()

    resp = _create_job(client, member_key)  # no workspace_id
    assert resp.status_code == 200, resp.text
    assert len(pipeline.start_calls) == 1
    assert _personal_balance(Factory, member_id) == 4  # personal debited


# =========================================================================== #
# Retrying a workspace job re-bills the SAME pool (regression: defect [1])
# =========================================================================== #
def _fail_job(Factory, job_id: str, stage: str = "avatar") -> None:
    with Factory() as s:
        JobRepository(s).mark_failed(job_id, stage, "boom")
        s.commit()


def _create_workspace_failed_job(env, users):
    """Owner funds a pool, member creates a workspace job, then it fails.

    Returns ``(job_id, member_id, member_key, wid)`` with the pool debited once
    (by create) and the member's personal balance at zero.
    """
    client, Factory, _pipeline = env
    _owner_id, owner_key = users["owner"]
    member_id, member_key = users["member"]
    wid = _create_workspace(client, owner_key)
    assert _invite(client, owner_key, wid, "member@example.com").status_code == 200
    assert _grant(client, owner_key, wid, 5).status_code == 200

    resp = _create_job(client, member_key, workspace_id=wid)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["data"]["job_id"]
    assert _pool_balance(Factory, wid) == 4            # create debited the pool
    assert _personal_balance(Factory, member_id) == 0

    _fail_job(Factory, job_id)
    return job_id, member_id, member_key, wid


def test_retry_workspace_job_debits_pool_not_personal(env, users):
    """Retrying a workspace job re-bills the SHARED pool, never the personal one.

    Regression for defect [1]: ``retry_job`` used to always debit the caller's
    personal balance, denying retry (402) when the member had 0 personal credits
    despite the workspace holding funds, and short-changing the wrong pool when
    they did. The funding pool is recovered from the credit ledger.
    """
    client, Factory, pipeline = env
    job_id, member_id, member_key, wid = _create_workspace_failed_job(env, users)

    resp = client.post(f"/api/v1/jobs/{job_id}/retry", headers=_headers(member_key))

    assert resp.status_code == 200, resp.text          # NOT 402 despite 0 personal
    assert len(pipeline.retry_calls) == 1              # re-enqueued exactly once
    assert _pool_balance(Factory, wid) == 3            # pool re-debited (4 -> 3)
    assert _personal_balance(Factory, member_id) == 0  # personal untouched


def test_retry_workspace_job_refunds_pool_on_enqueue_failure(env, users):
    """A failed retry enqueue refunds the SHARED pool, not the personal balance."""
    client, Factory, pipeline = env
    job_id, member_id, member_key, wid = _create_workspace_failed_job(env, users)

    pipeline.raise_on_retry = True
    resp = client.post(f"/api/v1/jobs/{job_id}/retry", headers=_headers(member_key))

    assert resp.status_code == 502, resp.text
    # Retry debited the pool (4 -> 3) then refunded it back on the failed enqueue.
    assert _pool_balance(Factory, wid) == 4
    assert _personal_balance(Factory, member_id) == 0  # personal never touched
