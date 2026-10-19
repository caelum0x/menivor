"""MN1: repurpose runs (transcribe / LLM rank) pay one credit; failures refund once."""

from __future__ import annotations

import hashlib
import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.repurpose import service as service_mod
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository
from app.models.db.repurpose import RepurposeJob
from app.models.exception import HttpException
from app.utils import utils

router_mod = importlib.import_module("app.domains.repurpose.router")
tasks_mod = importlib.import_module("app.workers.tasks")
KEY = "alice-key"
H = {"x-api-key": KEY}


class _Task:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def delay(self, *_a, **_k):
        self.calls += 1
        if self.fail:
            raise ConnectionError("broker down")


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = maker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    from app.models.db import base as db_base

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(router_mod, "get_session", _session)
    monkeypatch.setattr(router_mod, "_DB_IMPORT_ERROR", None)
    import app.services.ratelimit as ratelimit

    monkeypatch.setattr(ratelimit, "enforce_rate_limit", lambda *a, **k: None)
    task = _Task()
    monkeypatch.setattr(tasks_mod, "run_repurpose_task", task)

    app = FastAPI()
    app.include_router(router_mod.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, _handler)
    with maker() as s:
        user = User(email="a@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest())
        s.add(user)
        s.commit()
        user_id = user.id
    client = TestClient(app)
    job_id = client.post(
        "/api/v1/repurpose", json={"source_kind": "url", "source_ref": "https://youtu.be/abc"}, headers=H
    ).json()["data"]["id"]
    return client, maker, user_id, job_id, task


def _grant(maker, user_id, n):
    with maker() as s:
        CreditRepository(s).grant(user_id, n, "purchase")
        s.commit()


def _balance(maker, user_id):
    with maker() as s:
        return CreditRepository(s).balance(user_id)


def _status(maker, job_id):
    with maker() as s:
        return s.get(RepurposeJob, job_id).status


def _auto(client, job_id):
    return client.post(f"/api/v1/repurpose/{job_id}/rank", json={"segments": []}, headers=H)


def test_auto_rank_zero_balance_is_402_and_nothing_queued(env):
    client, maker, _, job_id, task = env
    resp = _auto(client, job_id)
    assert resp.status_code == 402, resp.text
    assert resp.json()["data"]["code"] == "credits_required"
    assert task.calls == 0
    assert _status(maker, job_id) == "created"


def test_auto_rank_debits_once_and_worker_failure_refunds_once(env):
    client, maker, user_id, job_id, task = env
    _grant(maker, user_id, 1)
    assert _auto(client, job_id).status_code == 200
    assert task.calls == 1 and _balance(maker, user_id) == 0
    assert _auto(client, job_id).status_code == 200  # in flight: not queued or charged again
    assert task.calls == 1 and _balance(maker, user_id) == 0
    service_mod._fail(job_id, "no speech")
    for _ in range(3):
        assert client.get(f"/api/v1/repurpose/{job_id}", headers=H).status_code == 200
    client.get("/api/v1/repurpose", headers=H)
    assert _balance(maker, user_id) == 1


def test_rerun_after_failure_settles_then_charges(env):
    client, maker, user_id, job_id, task = env
    _grant(maker, user_id, 1)
    _auto(client, job_id)
    service_mod._fail(job_id, "no speech")
    assert _auto(client, job_id).status_code == 200  # the refund pays for the retry
    assert task.calls == 2 and _balance(maker, user_id) == 0


def test_queue_outage_refunds(env):
    client, maker, user_id, job_id, task = env
    _grant(maker, user_id, 1)
    task.fail = True
    assert _auto(client, job_id).status_code == 503
    assert _balance(maker, user_id) == 1
    assert _status(maker, job_id) == "failed"


def test_llm_rank_is_charged_and_refunded_on_failure(env, monkeypatch):
    client, maker, user_id, job_id, _ = env
    unscored = {"segments": [{"start_s": 0, "end_s": 30, "text": "x"}]}
    assert client.post(f"/api/v1/repurpose/{job_id}/rank", json=unscored, headers=H).status_code == 402

    _grant(maker, user_id, 1)
    monkeypatch.setattr(service_mod, "_default_ranker", lambda segs, *, language="auto": [{**s, "score": 80} for s in segs])
    ok = client.post(f"/api/v1/repurpose/{job_id}/rank", json=unscored, headers=H)
    assert ok.status_code == 200, ok.text
    assert _balance(maker, user_id) == 0

    _grant(maker, user_id, 1)

    def _boom(segs, *, language="auto"):
        raise RuntimeError("relay down")

    monkeypatch.setattr(service_mod, "_default_ranker", _boom)
    failed = client.post(f"/api/v1/repurpose/{job_id}/rank", json=unscored, headers=H)
    assert failed.status_code == 502
    assert _balance(maker, user_id) == 1
    client.get(f"/api/v1/repurpose/{job_id}", headers=H)
    assert _balance(maker, user_id) == 1


def test_prescored_rank_stays_free(env):
    client, maker, user_id, job_id, _ = env
    body = {"segments": [{"start_s": 0, "end_s": 30, "text": "x", "score": 90}]}
    assert client.post(f"/api/v1/repurpose/{job_id}/rank", json=body, headers=H).status_code == 200
    assert _balance(maker, user_id) == 0
