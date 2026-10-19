"""Trends router — pure rank + persisted observe/recommended feed (sqlite)."""

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

from app.models.db import trends  # noqa: F401 - register table
from app.models.db.base import Base
from app.models.exception import HttpException
from app.utils import utils

mod = importlib.import_module("app.domains.trends.router")
base_mod = importlib.import_module("app.controllers.v1.base")

# The shared feed is operator-written: /trends/observe needs the static app key.
_OPERATOR_KEY = "operator-test-key"
_OPERATOR = {"x-api-key": _OPERATOR_KEY}


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

    monkeypatch.setattr(mod, "get_session", _gs)
    monkeypatch.setattr(mod, "_require_db", lambda rid: None)
    monkeypatch.setattr(mod, "_DB_IMPORT_ERROR", None)
    monkeypatch.setattr(base_mod, "_static_app_key", lambda: _OPERATOR_KEY)

    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(status_code=exc.status_code,
                                    content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app)


def test_rank_is_db_free(client):
    resp = client.post("/api/v1/trends/rank", json={"trends": [
        {"trend_id": "hot", "counts": [100, 400, 1200, 3000]},
    ]})
    assert resp.status_code == 200
    assert resp.json()["data"]["trends"][0]["trend_id"] == "hot"


def test_observe_then_recommended_persists(client):
    obs = client.post("/api/v1/trends/observe", json={"trends": [
        {"trend_id": "rising", "counts": [100, 400, 1200, 3000]},
        {"trend_id": "peaked", "counts": [99000, 99100, 99050, 99000]},
    ]}, headers=_OPERATOR)
    assert obs.status_code == 200
    assert len(obs.json()["data"]["observed"]) == 2

    rec = client.get("/api/v1/trends/recommended")
    assert rec.status_code == 200
    ids = [t["trend_id"] for t in rec.json()["data"]["trends"]]
    assert "rising" in ids and "peaked" not in ids  # only rising surfaces


def test_observe_requires_trends(client):
    resp = client.post("/api/v1/trends/observe", json={"trends": []}, headers=_OPERATOR)
    assert resp.status_code == 422


def test_observe_rejects_non_operator(client):
    body = {"trends": [{"trend_id": "rising", "counts": [100, 400, 1200, 3000]}]}
    assert client.post("/api/v1/trends/observe", json=body).status_code == 403
    wrong = {"x-api-key": "someone-else"}
    assert client.post("/api/v1/trends/observe", json=body, headers=wrong).status_code == 403
