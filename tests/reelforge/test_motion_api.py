"""Motion HTTP surface — list / detail / compile over a FastAPI TestClient.

Mirrors the templates router test harness: an in-memory SQLite session is injected
so the best-effort history record path exercises real persistence, while the pure
catalog/compile endpoints never touch the DB.
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

from app.models.db import models, motion  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

mod = importlib.import_module("app.domains.motion.router")


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
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

    with _gs() as s:
        s.add(User(id="u1", email="u@x.com"))

    class _U:
        id = "u1"

    monkeypatch.setattr(mod, "get_session", _gs, raising=False)
    monkeypatch.setattr(mod, "_require_db", lambda rid: None, raising=False)
    monkeypatch.setattr(mod, "_resolve_user", lambda req, s, rid: _U(), raising=False)
    monkeypatch.setattr(mod, "_DB_IMPORT_ERROR", None, raising=False)

    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(status_code=exc.status_code,
                                    content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app)


def test_list_motion(client):
    r = client.get("/api/v1/motion")
    assert r.status_code == 200
    motions = r.json()["data"]["motions"]
    assert len(motions) >= 50


def test_history_route_not_shadowed_by_preset(client):
    # /motion/history must hit the history endpoint, not detail(preset_id="history").
    r = client.get("/api/v1/motion/history")
    assert r.status_code == 200
    assert "history" in r.json()["data"]


def test_detail_and_unknown(client):
    ok = client.get("/api/v1/motion/orbit_left_360")
    assert ok.status_code == 200
    assert ok.json()["data"]["render_class"] == "model"

    missing = client.get("/api/v1/motion/not_a_real_move")
    assert missing.status_code == 404


def test_compile_endpoint_returns_plan(client):
    r = client.post("/api/v1/motion/dolly_in/compile", json={"intensity": 80})
    assert r.status_code == 200
    plan = r.json()["data"]
    assert plan["motion_class"] == "filter"
    assert plan["filter"]["intensity"] == 80


def test_compile_model_preset(client):
    r = client.post("/api/v1/motion/orbit_left_360/compile", json={"intensity": 50})
    assert r.status_code == 200
    plan = r.json()["data"]
    assert plan["motion_class"] == "model"
    assert plan["model"]["camera_pose"] == "Anti Clockwise"


def test_compile_unknown_is_422(client):
    r = client.post("/api/v1/motion/bogus_move/compile", json={"intensity": 50})
    assert r.status_code == 422
