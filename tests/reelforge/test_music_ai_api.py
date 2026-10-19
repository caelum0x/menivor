"""API-level tests for AI background music (Phase: AI-BGM).

Covers the API surface that exposes the vendored MPT music-generation
integrations (``app/services/elevenlabs_music.py`` + ``app/services/sonilo.py``)
to clients:

* ``POST /api/v1/jobs`` accepts a top-level ``music_prompt`` / ``bgm_provider``
  and threads them into the validated ``ReelForgeParams`` that reaches the
  Celery pipeline (captured via a fake ``start_pipeline``).
* An unknown ``bgm_provider`` is rejected with a clean ``422`` at the request
  boundary (before any credit is debited).
* ``GET /api/v1/catalog/music-generators`` lists only the providers whose
  ``is_enabled()`` guard is truthy, each as ``{id, name, max_prompt_length}``.

All exercised via a FastAPI ``TestClient`` over in-memory SQLite with a
monkeypatched ``get_session`` and a fake pipeline — no network, no Postgres,
no Celery. The provider modules' ``is_enabled()`` are monkeypatched so the
catalog test never touches real credentials.
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

import app.controllers.v1.catalog as catalog_mod
import app.controllers.v1.jobs as jobs_mod
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services import elevenlabs_music, sonilo
from app.utils import utils


@pytest.fixture(autouse=True)
def _presenter_ai_video_priced_elsewhere(monkeypatch):
    """These tests cover standard-credit plumbing on the default presenter layout.

    The AI-video price a presenter reel reserves (3x provider cost, never
    standard credits) is covered by ``test_premium_credits.py``; here it is 0.
    """
    from app.domains.reels import premium

    monkeypatch.setattr(premium, "ai_video_credits_needed", lambda params: 0)
    # M3.1 presenter plan rules (Pro+, 5 credits, monthly cap) are covered by
    # test_reel_pricing.py; here a presenter reel is a plain 1-credit reel.
    from app.domains.reels import policy as _reel_policy

    monkeypatch.setattr(_reel_policy, "require_presenter_allowed", lambda *a, **k: None)
    monkeypatch.setenv("MENIVOR_PRESENTER_CREDITS", "1")


_API_KEY = "musickey"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}
_PARAMS = {"video_subject": "cats"}


class _FakePipeline:
    """Records ``start_pipeline`` calls so tests can inspect the params passed."""

    def __init__(self) -> None:
        self.start_calls: list = []

    def start_pipeline(self, job_id, params):
        self.start_calls.append((job_id, params))
        return "celery-start-id"


@pytest.fixture()
def env(monkeypatch):
    """Wire the jobs + catalog controllers to SQLite and a fake pipeline."""
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

    fake_pipeline = _FakePipeline()

    monkeypatch.setattr(jobs_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(jobs_mod, "_import_pipeline", lambda rid: fake_pipeline)
    # Isolate the field-threading logic under test from external secret checks.
    monkeypatch.setattr(
        jobs_mod, "_validate_enabled_feature_secrets", lambda params, rid: None
    )

    app = FastAPI()
    app.include_router(jobs_mod.router)
    app.include_router(catalog_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    client = TestClient(app)

    return client, Factory, fake_pipeline


def _make_user(Factory, email="music@example.com", credits=5) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=_KEY_HASH, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        if credits:
            CreditRepository(s).grant(uid, credits, reason="signup")
        s.commit()
    return uid


# --------------------------------------------------------------------------- #
# POST /jobs — music_prompt / bgm_provider threading
# --------------------------------------------------------------------------- #
def test_create_job_threads_music_prompt_to_pipeline(env):
    """A top-level ``music_prompt`` reaches the pipeline as a ReelForgeParams field."""
    client, Factory, fake_pipeline = env
    _make_user(Factory)

    resp = client.post(
        "/api/v1/jobs",
        json={
            "params": _PARAMS,
            "music_prompt": "warm lofi hip-hop beats, mellow",
            "bgm_provider": "elevenlabs",
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text

    # The fake pipeline captured the exact validated params the worker will run.
    assert len(fake_pipeline.start_calls) == 1
    _job_id, params = fake_pipeline.start_calls[0]
    assert params.music_prompt == "warm lofi hip-hop beats, mellow"
    assert params.bgm_provider == "elevenlabs"


def test_create_job_music_prompt_nested_in_params_reaches_pipeline(env):
    """``music_prompt`` nested under ``params`` also flows through (no top-level)."""
    client, Factory, fake_pipeline = env
    _make_user(Factory)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": {**_PARAMS, "music_prompt": "epic cinematic trailer"}},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    _job_id, params = fake_pipeline.start_calls[0]
    assert params.music_prompt == "epic cinematic trailer"
    # Provider omitted => auto-select at pipeline time (empty string default).
    assert params.bgm_provider == ""


def test_create_job_without_music_prompt_is_unaffected(env):
    """Omitting the AI-BGM fields keeps the classic default (no custom track)."""
    client, Factory, fake_pipeline = env
    _make_user(Factory)

    resp = client.post("/api/v1/jobs", json={"params": _PARAMS}, headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    _job_id, params = fake_pipeline.start_calls[0]
    assert params.music_prompt == ""
    assert params.bgm_provider == ""


def test_create_job_invalid_bgm_provider_422(env):
    """An unknown ``bgm_provider`` is rejected at the boundary (no enqueue)."""
    client, Factory, fake_pipeline = env
    _make_user(Factory)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "bgm_provider": "suno"},
        headers=_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    # A rejected request never reaches the pipeline (and never debits credits).
    assert fake_pipeline.start_calls == []


def test_create_job_empty_bgm_provider_is_allowed(env):
    """``bgm_provider == ""`` is the auto-select sentinel and must pass validation."""
    client, Factory, fake_pipeline = env
    _make_user(Factory)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "music_prompt": "ambient", "bgm_provider": ""},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    _job_id, params = fake_pipeline.start_calls[0]
    assert params.bgm_provider == ""


# --------------------------------------------------------------------------- #
# GET /catalog/music-generators — enabled-provider listing
# --------------------------------------------------------------------------- #
def test_music_generators_lists_only_enabled(env, monkeypatch):
    """Only providers whose ``is_enabled()`` is truthy are listed, with metadata."""
    client, _Factory, _fake_pipeline = env
    monkeypatch.setattr(elevenlabs_music, "is_enabled", lambda: True)
    monkeypatch.setattr(sonilo, "is_enabled", lambda: False)

    resp = client.get("/api/v1/catalog/music-generators")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    by_id = {entry["id"]: entry for entry in data}
    assert set(by_id) == {"elevenlabs"}
    assert by_id["elevenlabs"]["name"] == "ElevenLabs"
    assert by_id["elevenlabs"]["max_prompt_length"] == elevenlabs_music.MAX_PROMPT_LENGTH


def test_music_generators_lists_both_when_enabled(env, monkeypatch):
    """Both providers appear when each ``is_enabled()`` guard is truthy."""
    client, _Factory, _fake_pipeline = env
    monkeypatch.setattr(elevenlabs_music, "is_enabled", lambda: True)
    monkeypatch.setattr(sonilo, "is_enabled", lambda: True)

    resp = client.get("/api/v1/catalog/music-generators")
    assert resp.status_code == 200, resp.text
    by_id = {entry["id"]: entry for entry in resp.json()["data"]}
    assert set(by_id) == {"elevenlabs", "sonilo"}
    assert by_id["sonilo"]["max_prompt_length"] == sonilo.MAX_PROMPT_LENGTH


def test_music_generators_empty_when_none_enabled(env, monkeypatch):
    """No configured provider => empty catalog (UI hides "Generate with AI")."""
    client, _Factory, _fake_pipeline = env
    monkeypatch.setattr(elevenlabs_music, "is_enabled", lambda: False)
    monkeypatch.setattr(sonilo, "is_enabled", lambda: False)

    resp = client.get("/api/v1/catalog/music-generators")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []


def test_music_generators_degrades_when_provider_raises(env, monkeypatch):
    """A raising ``is_enabled()`` drops that provider instead of 500-ing."""
    client, _Factory, _fake_pipeline = env

    def _boom():
        raise RuntimeError("config blew up")

    monkeypatch.setattr(elevenlabs_music, "is_enabled", _boom)
    monkeypatch.setattr(sonilo, "is_enabled", lambda: True)

    resp = client.get("/api/v1/catalog/music-generators")
    assert resp.status_code == 200, resp.text
    by_id = {entry["id"]: entry for entry in resp.json()["data"]}
    assert set(by_id) == {"sonilo"}
