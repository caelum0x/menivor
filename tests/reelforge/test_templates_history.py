"""Templates router persistence — instantiate records history + popularity analytics."""

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

from app.models.db import models, templates  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

mod = importlib.import_module("app.domains.templates.router")


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

    monkeypatch.setattr(mod, "get_session", _gs)
    monkeypatch.setattr(mod, "_require_db", lambda rid: None)
    monkeypatch.setattr(mod, "_resolve_user", lambda req, s, rid: _U())
    monkeypatch.setattr(mod, "_DB_IMPORT_ERROR", None)

    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(status_code=exc.status_code,
                                    content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app)


def test_history_route_not_shadowed_by_slug(client):
    # /templates/history must hit the history endpoint, not get_template(slug="history").
    resp = client.get("/api/v1/templates/history")
    assert resp.status_code == 200
    assert "history" in resp.json()["data"]


def test_instantiate_records_history_and_popularity(client):
    body = {"inputs": {"story": "my sister read my diary", "gameplay_clip": "jobs/u/p.mp4"}, "duration_s": 45}
    for _ in range(2):
        r = client.post("/api/v1/templates/minecraft-reddit-split/instantiate", json=body)
        assert r.status_code == 200

    hist = client.get("/api/v1/templates/history")
    assert len(hist.json()["data"]["history"]) == 2
    assert hist.json()["data"]["history"][0]["template_slug"] == "story-gameplay-split"

    popular = client.get("/api/v1/templates/analytics/popular")
    top = popular.json()["data"]["popular"]
    assert top[0]["template_slug"] == "story-gameplay-split" and top[0]["count"] == 2


def test_instantiate_still_returns_draft(client):
    r = client.post("/api/v1/templates/asmr-satisfying-loop/instantiate",
                    json={"inputs": {"trigger_clip": "jobs/u/t.mp4"}})
    assert r.status_code == 200 and "reel_draft" in r.json()["data"]
