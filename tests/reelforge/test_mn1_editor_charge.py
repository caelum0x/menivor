"""MN1: editor exports pay one credit; failures refund exactly once."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.reels import charge
from app.models import const
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.db.repositories import CreditRepository, JobRepository
from app.models.exception import HttpException
from app.utils import utils

editor_router = import_module("app.domains.editor.router")
tasks_mod = import_module("app.workers.tasks")


class _Task:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def apply_async(self, *args, **kwargs):
        self.calls += 1
        if self.fail:
            raise ConnectionError("broker down")
        return SimpleNamespace(id="celery-1")


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
    monkeypatch.setattr(editor_router, "get_session", _session)
    monkeypatch.setattr(editor_router, "read_idempotency_key", lambda *_a: None)
    monkeypatch.setattr(editor_router, "require_pro_action", lambda *a, **k: None)
    task = _Task()
    monkeypatch.setattr(tasks_mod, "export_editor_cut_task", task)

    with maker() as s:
        user = User(email="a@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest())
        s.add(user)
        s.flush()
        source = JobRepository(s).create(user_id=user.id, kind="avatar_reel", params={})
        source.state = const.TASK_STATE_COMPLETE
        source.result_key = "jobs/src/final.mp4"
        s.commit()
        user_id, source_id = user.id, source.id

    monkeypatch.setattr(
        editor_router, "resolve_principal", lambda *_a: SimpleNamespace(id=user_id)
    )
    app = FastAPI()
    app.include_router(editor_router.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, _handler)
    return TestClient(app), maker, user_id, source_id, task


def _grant(maker, user_id, n):
    with maker() as s:
        CreditRepository(s).grant(user_id, n, "purchase")
        s.commit()


def _balance(maker, user_id):
    with maker() as s:
        return CreditRepository(s).balance(user_id)


def _exports(maker):
    with maker() as s:
        return list(s.execute(select(Job).where(Job.kind.in_(charge.EDITOR_EXPORT_KINDS))).scalars())


def _export(client, source_id):
    return client.post(f"/api/v1/jobs/{source_id}/exports", json={"in_point": 0, "out_point": 3})


def _timeline(client, source_id):
    return client.post(
        f"/api/v1/jobs/{source_id}/timeline-exports",
        json={"segments": [{"source_in": 0, "source_out": 3}], "overlays": []},
    )


@pytest.mark.parametrize("call", [_export, _timeline])
def test_zero_balance_is_402_and_nothing_queued(env, call):
    client, maker, _, source_id, task = env
    resp = call(client, source_id)
    assert resp.status_code == 402, resp.text
    assert resp.json()["data"]["code"] == "credits_required"
    assert task.calls == 0 and _exports(maker) == []


@pytest.mark.parametrize("call", [_export, _timeline])
def test_export_debits_one_credit(env, call):
    client, maker, user_id, source_id, task = env
    _grant(maker, user_id, 1)
    assert call(client, source_id).status_code == 200
    assert task.calls == 1 and _balance(maker, user_id) == 0
    assert call(client, source_id).status_code == 402
    assert task.calls == 1


def test_queue_outage_refunds(env):
    client, maker, user_id, source_id, task = env
    _grant(maker, user_id, 1)
    task.fail = True
    assert _export(client, source_id).status_code == 503
    assert _balance(maker, user_id) == 1
    assert _exports(maker)[0].state == const.TASK_STATE_FAILED


def test_failed_render_refunds_exactly_once(env):
    client, maker, user_id, source_id, _ = env
    _grant(maker, user_id, 1)
    _export(client, source_id)
    job_id = _exports(maker)[0].id
    assert charge.refund_failed_job_once(job_id) == 0  # still processing: nothing to refund
    with maker() as s:
        JobRepository(s).mark_failed(job_id, "export", "ffmpeg failed")
        s.commit()
    assert charge.refund_failed_job_once(job_id) == 1
    assert charge.refund_failed_job_once(job_id) == 0
    assert _balance(maker, user_id) == 1


def test_unrefunded_failure_is_settled_by_the_next_export(env):
    client, maker, user_id, source_id, _ = env
    _grant(maker, user_id, 1)
    _export(client, source_id)
    job_id = _exports(maker)[0].id
    with maker() as s:  # the worker failed and its hook never refunded
        JobRepository(s).mark_failed(job_id, "export", "worker lost")
        s.commit()
    assert _export(client, source_id).status_code == 200  # the refund pays for this one
    assert _balance(maker, user_id) == 0
    assert charge.refund_failed_job_once(job_id) == 0
    with maker() as s:
        exports = s.execute(
            select(func.count()).select_from(Job).where(Job.kind == "editor_export")
        ).scalar()
    assert exports == 2
