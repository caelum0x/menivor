"""API-level tests for the AI Social Caption & Hashtags surface.

Covers the two ReelForge touch-points:

* ``POST /jobs/{job_id}/social`` (``app/controllers/v1/social.py``) — auth +
  OWNERSHIP on the job, per-user rate limit, platform validation, then a call
  into ``llm.generate_social_metadata`` using the *job's own* subject/script.
  Returns ``{title, caption, hashtags: [...]}``.
* ``GET /catalog/social-platforms`` (``app/controllers/v1/catalog.py``) — the
  supported platforms ``[{id, name}]``.

No network I/O: ``llm.generate_social_metadata`` is monkeypatched, behind an
in-memory SQLite DB + FastAPI ``TestClient`` — mirroring ``test_broll_api.py``.
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
import app.controllers.v1.social as social_mod
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import JobRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "social-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

_OTHER_API_KEY = "social-other-key"
_OTHER_KEY_HASH = hashlib.sha256(_OTHER_API_KEY.encode("utf-8")).hexdigest()
_OTHER_HEADERS = {"x-api-key": _OTHER_API_KEY}

_PARAMS = {
    "video_subject": "morning coffee routine",
    "video_script": "manual copy",
    "language": "en",
}


# =========================================================================== #
# Fakes
# =========================================================================== #
class _FakeLLM:
    """Fake ``app.services.llm`` module: records ``generate_social_metadata`` calls."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.result: dict = {
            "title": "Best morning coffee routine",
            "caption": "The 3-step routine that changed my mornings. Save this!",
            "hashtags": ["#coffee", "#morningroutine", "#fyp"],
        }
        self.raise_exc: Exception | None = None

    def generate_social_metadata(
        self, video_subject, video_script="", language="auto", platform="tiktok"
    ):
        self.calls.append(
            {
                "video_subject": video_subject,
                "video_script": video_script,
                "language": language,
                "platform": platform,
            }
        )
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


# =========================================================================== #
# Fixtures + helpers
# =========================================================================== #
@pytest.fixture()
def env(monkeypatch):
    """Wire the social + catalog controllers to in-memory SQLite + a fake LLM."""
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

    fake_llm = _FakeLLM()

    # The social controller resolves auth via ``jobs._resolve_user`` and opens its
    # own session, so patch ``get_session`` on BOTH modules to the same DB.
    monkeypatch.setattr(social_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(jobs_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(social_mod, "_import_llm", lambda rid: fake_llm)

    app = FastAPI()
    app.include_router(social_mod.router)
    app.include_router(catalog_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    client = TestClient(app)

    return client, Factory, fake_llm


def _make_user(Factory, email, key_hash) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_job(Factory, user_id, params=None, script="") -> str:
    with Factory() as s:
        job = JobRepository(s).create(
            user_id=user_id, kind="avatar_reel", params=params or dict(_PARAMS)
        )
        jid = job.id
        if script:
            JobRepository(s).set_script(jid, script)
        s.commit()
    return jid


# =========================================================================== #
# POST /jobs/{job_id}/social
# =========================================================================== #
def test_generate_returns_metadata_for_owned_job(env):
    client, Factory, fake_llm = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    jid = _make_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/social",
        json={"platform": "tiktok"},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["title"] == "Best morning coffee routine"
    assert data["caption"].startswith("The 3-step routine")
    assert data["hashtags"] == ["#coffee", "#morningroutine", "#fyp"]

    # The generator saw the job's own subject + tiktok platform + job language.
    assert len(fake_llm.calls) == 1
    call = fake_llm.calls[0]
    assert call["video_subject"] == "morning coffee routine"
    assert call["platform"] == "tiktok"
    assert call["language"] == "en"


def test_generate_maps_instagram_to_llm_platform_and_uses_script(env):
    client, Factory, fake_llm = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    # A finalized narration script wins over the manual params.video_script.
    jid = _make_job(Factory, uid, script="the finalized narration script")

    resp = client.post(
        f"/api/v1/jobs/{jid}/social",
        json={"platform": "instagram", "language": "es"},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    call = fake_llm.calls[0]
    # ``instagram`` maps to the LLM's ``instagram_reels`` spec.
    assert call["platform"] == "instagram_reels"
    # Client-supplied language overrides the job's configured one.
    assert call["language"] == "es"
    # Persisted script wins over the manual params copy.
    assert call["video_script"] == "the finalized narration script"


def test_generate_foreign_job_returns_404_and_does_not_call_llm(env):
    client, Factory, fake_llm = env
    owner = _make_user(Factory, "owner@example.com", _KEY_HASH)
    _make_user(Factory, "other@example.com", _OTHER_KEY_HASH)
    jid = _make_job(Factory, owner)

    resp = client.post(
        f"/api/v1/jobs/{jid}/social",
        json={"platform": "tiktok"},
        headers=_OTHER_HEADERS,
    )

    assert resp.status_code == 404, resp.text
    # No existence leak + the LLM is never reached.
    assert fake_llm.calls == []


def test_generate_unknown_job_returns_404(env):
    client, Factory, fake_llm = env
    _make_user(Factory, "owner@example.com", _KEY_HASH)

    resp = client.post(
        "/api/v1/jobs/does-not-exist/social",
        json={"platform": "tiktok"},
        headers=_HEADERS,
    )

    assert resp.status_code == 404, resp.text
    assert fake_llm.calls == []


def test_generate_invalid_platform_returns_400(env):
    client, Factory, fake_llm = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    jid = _make_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/social",
        json={"platform": "myspace"},
        headers=_HEADERS,
    )

    assert resp.status_code == 400, resp.text
    # Rejected before any LLM token is spent.
    assert fake_llm.calls == []


def test_generate_missing_api_key_returns_401(env):
    client, Factory, fake_llm = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    jid = _make_job(Factory, uid)

    resp = client.post(f"/api/v1/jobs/{jid}/social", json={"platform": "tiktok"})

    assert resp.status_code == 401, resp.text
    assert fake_llm.calls == []


def test_generate_502_on_llm_failure(env):
    client, Factory, fake_llm = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    jid = _make_job(Factory, uid)
    fake_llm.raise_exc = RuntimeError("model exploded")

    resp = client.post(
        f"/api/v1/jobs/{jid}/social",
        json={"platform": "youtube_shorts"},
        headers=_HEADERS,
    )

    # A generation failure surfaces as a clean 502, never a 500 leak.
    assert resp.status_code == 502, resp.text


# =========================================================================== #
# GET /catalog/social-platforms
# =========================================================================== #
def test_catalog_lists_social_platforms(env):
    client, _Factory, _fake_llm = env

    resp = client.get("/api/v1/catalog/social-platforms")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    ids = {entry["id"] for entry in data}
    assert ids == {"tiktok", "instagram", "youtube_shorts"}
    assert all("name" in entry for entry in data)
