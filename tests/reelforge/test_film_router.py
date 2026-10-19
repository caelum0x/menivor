"""Film router — plan (DB-free) + persist project/get project (sqlite)."""

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

from app.models.db import film, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

mod = importlib.import_module("app.domains.film.router")


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


_BODY = {
    "beats": [
        {"scene_id": "sc1", "summary": "hero enters", "weight": 2.0},
        {"scene_id": "sc2", "summary": "the twist", "weight": 1.0},
    ],
    "character": {"character_id": "c1", "name": "Nova", "descriptors": ["red jacket"], "style": "3D"},
    "total_shots": 8,
    "target_runtime_s": 24.0,
}


def test_plan_is_db_free_preview(client):
    resp = client.post("/api/v1/film/plan", json=_BODY)
    assert resp.status_code == 200 and len(resp.json()["data"]["shots"]) == 8


def test_create_and_get_project(client):
    created = client.post("/api/v1/film/projects", json={**_BODY, "title": "Ep1"})
    assert created.status_code == 200, created.text
    pid = created.json()["data"]["id"]
    assert created.json()["data"]["shot_count"] == 8

    got = client.get(f"/api/v1/film/projects/{pid}")
    assert got.status_code == 200
    data = got.json()["data"]
    assert data["title"] == "Ep1" and len(data["shots"]) == 8
    assert all("Nova" in s["prompt"] for s in data["shots"])


def test_get_missing_project_404(client):
    assert client.get("/api/v1/film/projects/nope").status_code == 404
