"""MN1: Ad Studio renders pay one credit each; failures refund exactly once;
FFmpeg never runs in the API process."""

from __future__ import annotations

import hashlib
import importlib
import inspect
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.domains.adstudio.models  # noqa: F401 - registers the tables
from app.domains.adstudio import worker as worker_mod
from app.domains.adstudio.models import AdVariant
from app.domains.adstudio.repository import AdStudioRepository
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.utils import utils

ctrl = importlib.import_module("app.controllers.v1.adstudio")
RAW_KEY = "alice-key"


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
    monkeypatch.setattr(ctrl, "get_session", _session)
    monkeypatch.setattr(ctrl, "require_database", lambda request_id: None)
    monkeypatch.setattr(ctrl, "enforce_rate_limit", lambda *a, **k: None)
    queued: list[str] = []
    monkeypatch.setattr(ctrl, "dispatch_render", queued.append)

    app = FastAPI()
    app.include_router(ctrl.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, _handler)
    return TestClient(app), maker, queued


def _seed(maker, credits: int) -> tuple[str, str]:
    with maker() as s:
        user = User(email="a@example.com", api_key_hash=hashlib.sha256(RAW_KEY.encode()).hexdigest())
        s.add(user)
        s.flush()
        if credits:
            CreditRepository(s).grant(user.id, credits, "purchase")
        project = AdStudioRepository(s).create_project(
            user_id=user.id, title="Mug", product={"title": "Mug"},
            angles=[{"id": "a1", "hook": "h"}, {"id": "a2", "hook": "h2"}],
            images=[{"key": "uploads/x.jpg"}],
        )
        s.commit()
        return user.id, project.id


def _balance(maker, user_id):
    with maker() as s:
        return CreditRepository(s).balance(user_id)


def _variants(maker):
    with maker() as s:
        return s.query(AdVariant).all()


def _post_variants(client, project_id, angles):
    return client.post(
        f"/api/v1/ad-studio/projects/{project_id}/variants",
        json={"angle_ids": angles, "formats": ["showcase"], "aspects": ["9:16"]},
        headers={"x-api-key": RAW_KEY},
    )


def test_zero_balance_is_402_and_nothing_queued(env):
    client, maker, queued = env
    _, project_id = _seed(maker, 0)
    resp = _post_variants(client, project_id, ["a1"])
    assert resp.status_code == 402
    assert resp.json()["data"]["code"] == "credits_required"
    assert queued == [] and _variants(maker) == []


def test_batch_larger_than_balance_queues_nothing(env):
    client, maker, queued = env
    user_id, project_id = _seed(maker, 1)
    resp = _post_variants(client, project_id, ["a1", "a2"])
    assert resp.status_code == 402
    assert queued == [] and _variants(maker) == []
    assert _balance(maker, user_id) == 1


def test_balance_n_queues_n_and_debits_each(env):
    client, maker, queued = env
    user_id, project_id = _seed(maker, 2)
    resp = _post_variants(client, project_id, ["a1", "a2"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["queued"] == 2 and len(queued) == 2
    assert _balance(maker, user_id) == 0


def test_failed_render_refunds_exactly_once(env):
    client, maker, queued = env
    user_id, project_id = _seed(maker, 1)
    assert _post_variants(client, project_id, ["a1"]).status_code == 200
    variant_id = queued[0]
    assert worker_mod.fail_and_refund(variant_id, "boom") == 1
    assert worker_mod.fail_and_refund(variant_id, "boom") == 0
    # Reading the project (which also settles failed ads) never refunds again.
    got = client.get(f"/api/v1/ad-studio/projects/{project_id}", headers={"x-api-key": RAW_KEY})
    assert got.status_code == 200
    assert _balance(maker, user_id) == 1


def test_retry_charges_again_and_its_failure_refunds_once(env):
    client, maker, queued = env
    user_id, project_id = _seed(maker, 1)
    _post_variants(client, project_id, ["a1"])
    variant_id = queued[0]
    worker_mod.fail_and_refund(variant_id, "boom")
    retry = client.post(
        f"/api/v1/ad-studio/projects/{project_id}/variants/{variant_id}/retry",
        headers={"x-api-key": RAW_KEY},
    )
    assert retry.status_code == 200, retry.text
    assert _balance(maker, user_id) == 0
    worker_mod.fail_and_refund(variant_id, "boom again")
    assert _balance(maker, user_id) == 1


def test_retry_with_zero_balance_is_402(env):
    client, maker, queued = env
    user_id, project_id = _seed(maker, 1)
    _post_variants(client, project_id, ["a1"])
    variant_id = queued[0]
    worker_mod.fail_and_refund(variant_id, "boom")
    with maker() as s:
        CreditRepository(s).debit(user_id, 1, None, "spent_elsewhere")
        s.commit()
    retry = client.post(
        f"/api/v1/ad-studio/projects/{project_id}/variants/{variant_id}/retry",
        headers={"x-api-key": RAW_KEY},
    )
    assert retry.status_code == 402
    assert len(queued) == 1
    assert _variants(maker)[0].status == "failed"


def test_stale_sweep_failure_is_refunded_on_read(env):
    client, maker, queued = env
    user_id, project_id = _seed(maker, 1)
    _post_variants(client, project_id, ["a1"])
    with maker() as s:  # a worker died mid-render; the sweep marked it failed
        s.query(AdVariant).update({"status": "failed", "error": "stale"})
        s.commit()
    client.get(f"/api/v1/ad-studio/projects/{project_id}", headers={"x-api-key": RAW_KEY})
    client.get(f"/api/v1/ad-studio/projects/{project_id}", headers={"x-api-key": RAW_KEY})
    assert _balance(maker, user_id) == 1


def test_deleting_a_queued_ad_returns_its_credit(env):
    client, maker, queued = env
    user_id, project_id = _seed(maker, 1)
    _post_variants(client, project_id, ["a1"])
    resp = client.delete(
        f"/api/v1/ad-studio/projects/{project_id}/variants/{queued[0]}", headers={"x-api-key": RAW_KEY}
    )
    assert resp.status_code == 200
    assert _balance(maker, user_id) == 1


def test_queue_outage_fails_and_refunds(env, monkeypatch):
    client, maker, _ = env
    user_id, project_id = _seed(maker, 1)

    def _down(variant_id):
        raise worker_mod.RenderQueueUnavailable("broker down")

    monkeypatch.setattr(ctrl, "dispatch_render", _down)
    resp = _post_variants(client, project_id, ["a1"])
    assert resp.status_code == 503
    assert _balance(maker, user_id) == 1
    assert _variants(maker)[0].status == "failed"


def test_no_inline_ffmpeg_pool_in_api_process(monkeypatch):
    source = inspect.getsource(worker_mod)
    assert "ThreadPoolExecutor" not in source
    assert "submit(" not in source
    sent: list = []

    class _Task:
        def apply_async(self, args, queue):
            sent.append((args, queue))

    tasks_mod = importlib.import_module("app.domains.adstudio.tasks")
    monkeypatch.setattr(tasks_mod, "render_ad_variant_task", _Task())
    worker_mod.dispatch_render("v1")
    assert sent == [(["v1"], "render")]

    class _Down:
        def apply_async(self, args, queue):
            raise ConnectionError("broker down")

    monkeypatch.setattr(tasks_mod, "render_ad_variant_task", _Down())
    with pytest.raises(worker_mod.RenderQueueUnavailable):
        worker_mod.dispatch_render("v2")
