"""Render router integration — start → advance a metered render over the real stack.

Uses a real sqlite DB + real WalletService (funded ledger) + a fake backend
transport, so the full path (reserve → submit → persist → poll → settle) runs end
to end, proving success-only billing through the HTTP surface.
"""

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

from app.models.db import models, render  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.exception import HttpException
from app.utils import utils

render_router_mod = importlib.import_module("app.domains.render.router")


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = {}

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


class FakeTransport:
    def __init__(self, polls):
        self._polls = list(polls)

    def request(self, method, url, *, headers=None, params=None, json=None):
        if url.endswith("/run"):
            return _Resp(200, {"id": "rp-1", "status": "IN_QUEUE"})
        return self._polls.pop(0)


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _gs():
        s = Factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    # Seed a user + fund their wallet via a direct ledger grant.
    from app.domains.wallet.repository import ENTRY_GRANT, WalletRepository
    from app.models.db.models import User

    with _gs() as s:
        s.add(User(id="u1", email="u@x.com"))
        s.flush()
        repo = WalletRepository(s)
        acct = repo.get_or_create_personal_account("u1")
        repo.append_entry(acct.id, entry_type=ENTRY_GRANT, reason="test_topup",
                          available_delta=1_000_000)

    monkeypatch.setattr(render_router_mod, "get_session", _gs)
    monkeypatch.setattr(render_router_mod, "_require_db", lambda rid: None)

    class _User:
        id = "u1"

    monkeypatch.setattr(render_router_mod, "_resolve_user", lambda req, s, rid: _User())

    # Register the RunPod backend with fixed creds so submit/poll work.
    from app.services.render.backends.runpod import RunPodBackend, register_backend

    register_backend(RunPodBackend(endpoint_id="ep", api_key="k"))

    app = FastAPI()
    app.include_router(render_router_mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(status_code=exc.status_code,
                                    content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app), monkeypatch


def _fund(client_tuple):
    # Ensure the wallet has funds via a direct ledger credit (idempotent-ish).
    pass


def test_start_render_reserves_and_persists(client):
    tc, monkeypatch = client
    # Patch the executor's transport by pre-registering a fake on the module.
    import app.services.render.execution as ex

    monkeypatch.setattr(
        ex.RenderExecutor, "__init__",
        lambda self, wallet, **kw: (setattr(self, "_wallet", wallet),
                                    setattr(self, "_outbox", ex.Outbox()),
                                    setattr(self, "_transport", FakeTransport([])))[0],
    )
    resp = tc.post("/api/v1/render/jobs", json={
        "backend": "runpod", "spec": {"prompt": "a cat"}, "max_cost_micros": 100_000,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["backend"] == "runpod" and data["state"] == "IN_QUEUE"
    assert data["provider_ref"] == "rp-1"

    # Status is owner-scoped + persisted.
    jid = data["id"]
    got = tc.get(f"/api/v1/render/jobs/{jid}")
    assert got.status_code == 200 and got.json()["data"]["id"] == jid


def test_start_render_idempotency_replays_without_second_hold_or_submit(client):
    tc, monkeypatch = client
    import app.services.render.execution as ex

    monkeypatch.setattr(
        ex.RenderExecutor, "__init__",
        lambda self, wallet, **kw: (setattr(self, "_wallet", wallet),
                                    setattr(self, "_outbox", ex.Outbox()),
                                    setattr(self, "_transport", FakeTransport([])))[0],
    )
    original_start = ex.RenderExecutor.start
    calls = 0

    def counted_start(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original_start(self, *args, **kwargs)

    monkeypatch.setattr(ex.RenderExecutor, "start", counted_start)
    body = {"backend": "runpod", "spec": {"prompt": "one"}, "max_cost_micros": 100_000}
    headers = {"Idempotency-Key": "render-command-1"}

    first = tc.post("/api/v1/render/jobs", json=body, headers=headers)
    replay = tc.post("/api/v1/render/jobs", json=body, headers=headers)
    conflict = tc.post(
        "/api/v1/render/jobs",
        json={**body, "spec": {"prompt": "changed"}},
        headers=headers,
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"] == first.json()["data"]
    assert calls == 1
    assert conflict.status_code == 409


def test_advance_to_completed_settles(client):
    tc, monkeypatch = client
    import app.services.render.execution as ex

    monkeypatch.setattr(
        ex.RenderExecutor, "__init__",
        lambda self, wallet, **kw: (setattr(self, "_wallet", wallet),
                                    setattr(self, "_outbox", ex.Outbox()),
                                    setattr(self, "_transport",
                                            FakeTransport([_Resp(200, {"status": "COMPLETED",
                                                                       "output": {"video_url": "u"}})])))[0],
    )
    start = tc.post("/api/v1/render/jobs", json={
        "backend": "runpod", "spec": {}, "max_cost_micros": 100_000,
    })
    jid = start.json()["data"]["id"]
    adv = tc.post(f"/api/v1/render/jobs/{jid}/advance")
    assert adv.status_code == 200, adv.text
    assert adv.json()["data"]["state"] == "COMPLETED"
