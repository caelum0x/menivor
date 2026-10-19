"""A/B experiment router — create → ingest → evaluate over the real stack (sqlite)."""

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

from app.models.db import experiments, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

mod = importlib.import_module("app.domains.publishing.experiments_router")


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
    monkeypatch.setattr(mod, "_IMPORT_ERROR", None)

    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(status_code=exc.status_code,
                                    content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app)


def test_create_ingest_evaluate_flow(client):
    created = client.post("/api/v1/experiments", json={
        "experiment_key": "exp-1", "hook_refs": ["hookA", "hookB"],
    })
    assert created.status_code == 200, created.text
    variants = {v["hook_ref"]: v["id"] for v in created.json()["data"]["variants"]}

    client.post(f"/api/v1/experiments/exp-1/variants/{variants['hookA']}/metrics",
                json={"views": 1000, "completion_rate": 0.8, "avg_watch_frac": 0.7, "rewatch_rate": 0.2})
    client.post(f"/api/v1/experiments/exp-1/variants/{variants['hookB']}/metrics",
                json={"views": 1000, "completion_rate": 0.4, "avg_watch_frac": 0.3, "rewatch_rate": 0.05})

    verdict = client.post("/api/v1/experiments/exp-1/evaluate")
    assert verdict.status_code == 200
    data = verdict.json()["data"]
    assert data["status"] == "conclusive" and data["winner_hook_ref"] == "hookA"


def test_create_requires_two_variants(client):
    resp = client.post("/api/v1/experiments", json={"experiment_key": "x", "hook_refs": ["only"]})
    assert resp.status_code == 422


def test_get_unknown_experiment_404(client):
    assert client.get("/api/v1/experiments/nope").status_code == 404
