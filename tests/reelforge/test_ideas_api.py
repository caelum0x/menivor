"""SPARK — AI Idea Engine API tests (Phase 18).

Covers ``app.controllers.v1.ideas`` — the four auth-gated endpoints that
generate and persist viral UGC video concepts:

* ``POST /ideas/generate`` — auth (401), empty ``app_context`` (400), and the
  happy path (returns exactly ``count`` concepts from the monkeypatched
  generator). A generator that returns ``None`` surfaces as a clean 502.
* ``POST /me/ideas`` — save a concept for the caller -> ``{id}``.
* ``GET /me/ideas`` — scoped to the caller only.
* ``DELETE /me/ideas/{id}`` — ownership-checked (404 for a foreign id).

No external I/O: the LLM generator is monkeypatched and Postgres is replaced by
an in-memory SQLite DB behind a ``TestClient``, mirroring
``tests/reelforge/test_voices_api.py``.
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

import app.controllers.v1.ideas as ideas_mod
from app.models.db.base import Base
from app.models.db.models import SavedIdea, User
from app.models.db.repositories import SavedIdeaRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "ideas-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


# =========================================================================== #
# Helpers
# =========================================================================== #
def _make_idea(n: int) -> dict:
    """A minimal, well-formed SPARK concept dict."""
    return {
        "title": f"Idea {n}",
        "hook": f"You will not believe hook number {n}",
        "angle": "relatable pain -> the app is the fix",
        "format": "talking head",
        "script_outline": ["beat one", "beat two", "beat three"],
        "suggested_layout": "hook_intro",
        "suggested_caption_style": "karaoke_yellow",
        "language": "en",
        "est_duration_s": 30,
    }


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture()
def db_factory():
    """In-memory SQLite engine + session factory with the schema created."""
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
    return Factory


def _make_user(Factory, email="idea@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_saved_idea(Factory, user_id: str, n: int = 1) -> str:
    with Factory() as s:
        row = SavedIdeaRepository(s).create(user_id, _make_idea(n))
        rid = row.id
        s.commit()
    return rid


@pytest.fixture()
def ideas_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the ideas router + in-memory SQLite.

    The LLM generator (``ideas_service.generate_ideas``) is monkeypatched by
    default to echo ``count`` well-formed concepts; individual tests override it.
    Returns ``(client, Factory)``.
    """
    Factory = db_factory

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

    monkeypatch.setattr(ideas_mod, "get_session", _fake_get_session)

    def _fake_generate(app_context, audience="", count=6, language="auto", **kwargs):
        return [_make_idea(i) for i in range(1, int(count) + 1)]

    monkeypatch.setattr(ideas_mod.ideas_service, "generate_ideas", _fake_generate)

    app = FastAPI()
    app.include_router(ideas_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# =========================================================================== #
# POST /ideas/generate
# =========================================================================== #
def test_generate_returns_n_ideas(ideas_client):
    client, Factory = ideas_client
    _make_user(Factory)

    resp = client.post(
        "/api/v1/ideas/generate",
        json={"app_context": "A budgeting app for freelancers", "count": 4},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data) == 4
    for item in data:
        assert item["hook"]
        assert item["suggested_layout"] == "hook_intro"
        assert item["suggested_caption_style"] == "karaoke_yellow"
        assert len(item["script_outline"]) == 3


def test_generate_empty_app_context_400(ideas_client):
    client, Factory = ideas_client
    _make_user(Factory)

    resp = client.post(
        "/api/v1/ideas/generate",
        json={"app_context": "   ", "count": 3},
        headers=_HEADERS,
    )
    assert resp.status_code == 400, resp.text


def test_generate_requires_auth_401(ideas_client):
    client, Factory = ideas_client
    resp = client.post(
        "/api/v1/ideas/generate",
        json={"app_context": "A budgeting app", "count": 3},
    )  # no x-api-key
    assert resp.status_code == 401, resp.text


def test_generate_returns_502_when_generator_yields_none(ideas_client, monkeypatch):
    client, Factory = ideas_client
    _make_user(Factory)
    monkeypatch.setattr(
        ideas_mod.ideas_service,
        "generate_ideas",
        lambda *a, **k: None,
    )

    resp = client.post(
        "/api/v1/ideas/generate",
        json={"app_context": "A budgeting app", "count": 3},
        headers=_HEADERS,
    )
    assert resp.status_code == 502, resp.text


# =========================================================================== #
# POST /me/ideas  (save)
# =========================================================================== #
def test_save_idea_persists_and_returns_id(ideas_client):
    client, Factory = ideas_client
    uid = _make_user(Factory)

    resp = client.post(
        "/api/v1/me/ideas",
        json={"idea": _make_idea(7)},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    idea_id = resp.json()["data"]["id"]
    assert idea_id

    with Factory() as s:
        rows = s.query(SavedIdea).filter(SavedIdea.user_id == uid).all()
        assert len(rows) == 1
        assert rows[0].id == idea_id
        assert rows[0].hook == _make_idea(7)["hook"]
        assert rows[0].payload["suggested_caption_style"] == "karaoke_yellow"


def test_save_idea_is_rate_limited(ideas_client, monkeypatch):
    """A crafted save loop must be gated: the endpoint enforces a per-user cap.

    The real limiter degrades OPEN without Redis, so we stub ``enforce_rate_limit``
    to assert the save endpoint (a) calls it with a per-user ``save_idea:`` bucket
    and (b) surfaces the 429 it raises (storage-DoS guard).
    """
    client, Factory = ideas_client
    uid = _make_user(Factory)

    seen_buckets: list[str] = []

    def _deny(request, bucket, limit, window_s):
        seen_buckets.append(bucket)
        raise HttpException(task_id="t", status_code=429, message="rate limited")

    monkeypatch.setattr(ideas_mod, "enforce_rate_limit", _deny)

    resp = client.post(
        "/api/v1/me/ideas",
        json={"idea": _make_idea(1)},
        headers=_HEADERS,
    )
    assert resp.status_code == 429, resp.text
    assert seen_buckets == [f"save_idea:{uid}"]
    # No row was written because the cap tripped before the insert.
    with Factory() as s:
        assert s.query(SavedIdea).filter(SavedIdea.user_id == uid).count() == 0


def test_save_empty_idea_400(ideas_client):
    client, Factory = ideas_client
    _make_user(Factory)

    resp = client.post("/api/v1/me/ideas", json={"idea": {}}, headers=_HEADERS)
    assert resp.status_code == 400, resp.text


def test_save_requires_auth_401(ideas_client):
    client, Factory = ideas_client
    resp = client.post("/api/v1/me/ideas", json={"idea": _make_idea(1)})
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# GET /me/ideas  (list)
# =========================================================================== #
def test_list_ideas_scoped_to_caller(ideas_client):
    client, Factory = ideas_client
    caller_id = _make_user(Factory, email="caller@x.com")
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    _make_saved_idea(Factory, caller_id, n=1)
    _make_saved_idea(Factory, caller_id, n=2)
    _make_saved_idea(Factory, other_id, n=9)  # must NOT appear for the caller

    resp = client.get("/api/v1/me/ideas", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data) == 2
    for item in data:
        assert item["id"]
        assert item["hook"]
        assert "idea" in item
        assert item["idea"]["hook"] == item["hook"]


def test_list_requires_auth_401(ideas_client):
    client, Factory = ideas_client
    resp = client.get("/api/v1/me/ideas")  # no x-api-key
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# DELETE /me/ideas/{id}
# =========================================================================== #
def test_delete_own_idea_happy_path(ideas_client):
    client, Factory = ideas_client
    uid = _make_user(Factory)
    rid = _make_saved_idea(Factory, uid, n=3)

    resp = client.delete(f"/api/v1/me/ideas/{rid}", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["deleted"] is True
    with Factory() as s:
        assert s.get(SavedIdea, rid) is None


def test_delete_foreign_idea_404(ideas_client):
    client, Factory = ideas_client
    # Idea owned by a DIFFERENT user; the caller must not be able to delete it.
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    victim_rid = _make_saved_idea(Factory, other_id, n=5)
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.delete(f"/api/v1/me/ideas/{victim_rid}", headers=_HEADERS)
    assert resp.status_code == 404, resp.text
    # The foreign row survives untouched.
    with Factory() as s:
        assert s.get(SavedIdea, victim_rid) is not None


def test_delete_unknown_idea_404(ideas_client):
    client, Factory = ideas_client
    _make_user(Factory)
    resp = client.delete("/api/v1/me/ideas/does-not-exist", headers=_HEADERS)
    assert resp.status_code == 404, resp.text
