"""API-level tests for BRING YOUR OWN VOICEOVER (BYOV) — ``POST /api/v1/jobs``.

A creator uploads their OWN narration audio via the EXISTING
``POST /api/v1/uploads/presign`` flow (``audio/mpeg`` / ``audio/wav``) and passes
the returned R2 ``key`` as the top-level ``voiceover_key`` on job create. The
controller folds it into the validated ``ReelForgeParams`` DTO so ``stage_tts``
uses the uploaded audio as the reel's narration (faster-whisper WORD timings
drive the §8 captions AND the same audio drives the avatar lip-sync + duration).

These tests exercise ONLY the API layer (schema + controller threading) against
an in-memory SQLite DB with a monkeypatched ``get_session`` and a fake Celery
pipeline — no Postgres/Redis/Celery/whisper required:

* A create WITH ``voiceover_key`` threads it into the ``ReelForgeParams`` enqueued
  to the pipeline AND persists it on ``Job.params`` — with NO credit change.
* A create WITHOUT ``voiceover_key`` is unchanged (the DTO default ``""``).
* ``voiceover_key`` nested under ``params`` is honoured too (folding is override,
  not clobber).
* No ``voice_id`` is required for a BYOV job (the uploaded audio is the narration).
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

import app.controllers.v1.jobs as jobs_mod
from app.models import const
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository, JobRepository
from app.services.billing import premium_credits
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "byov-testkey"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}
_PARAMS = {"video_subject": "cats"}
_VOICEOVER_KEY = "uploads/9f8e7d6c5b4a.mp3"


class _FakePipeline:
    """Records enqueue calls; ``start_pipeline`` returns a stub celery task id."""

    def __init__(self) -> None:
        self.start_calls: list = []

    def start_pipeline(self, job_id, params):
        self.start_calls.append((job_id, params))
        return "celery-start-id"

    def retry_pipeline(self, job_id, params, failed_stage):  # pragma: no cover
        return "celery-retry-id"


@pytest.fixture(autouse=True)
def _presenter_plan_rules_covered_elsewhere(monkeypatch):
    """BYOV threading on the default presenter layout, not the M3.1 plan rules.

    Presenter plan rules (Pro+, 5 credits, monthly cap) are covered by
    ``test_m3_1_pricing_model.py``; here a presenter reel is a 1-credit reel.
    """
    from app.domains.reels import policy as _reel_policy

    monkeypatch.setattr(_reel_policy, "require_presenter_allowed", lambda *a, **k: None)
    monkeypatch.setenv("MENIVOR_PRESENTER_CREDITS", "1")


@pytest.fixture()
def env(monkeypatch):
    """Wire the controller to an in-memory SQLite DB + fake pipeline."""
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
    # Skip external feature-secret validation (HeyGen/ElevenLabs keys) so the
    # BYOV threading under test is isolated from provider configuration.
    monkeypatch.setattr(
        jobs_mod, "_validate_enabled_feature_secrets", lambda params, rid: None
    )

    app = FastAPI()
    app.include_router(jobs_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    client = TestClient(app)

    return client, Factory, fake_pipeline


def _make_user(Factory, email="byov@example.com", credits=0) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=_KEY_HASH, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        if credits:
            CreditRepository(s).grant(uid, credits, reason="signup")
        # Avatar-layout reels reserve AI-video credits (never standard credits).
        premium_credits.grant(s, uid, premium_credits.KIND_AI_VIDEO, 100_000, "test_grant")
        s.commit()
    return uid


def _balance(Factory, user_id) -> int:
    with Factory() as s:
        return CreditRepository(s).balance(user_id)


# --------------------------------------------------------------------------- #
# WITH voiceover_key — threaded into the enqueued ReelForgeParams + persisted,
# and NO credit change (a BYOV reel costs the same as a TTS reel).
# --------------------------------------------------------------------------- #
def test_create_job_with_voiceover_key_threads_into_params(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "voiceover_key": _VOICEOVER_KEY},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["state"] == const.TASK_STATE_PROCESSING
    assert len(pipeline.start_calls) == 1

    # Folded into the validated ReelForgeParams DTO enqueued to the pipeline.
    _, enq_params = pipeline.start_calls[0]
    assert enq_params.voiceover_key == _VOICEOVER_KEY
    assert enq_params.video_subject == "cats"          # rest of the DTO intact

    # Persisted on Job.params for the pipeline to read.
    with Factory() as s:
        job = JobRepository(s).list_for_user(uid)[0]
    assert job.params.get("voiceover_key") == _VOICEOVER_KEY

    # No credit change: exactly one credit debited, same as a TTS reel.
    assert _balance(Factory, uid) == 4


def test_create_job_voiceover_key_nested_in_params_is_honoured(env):
    client, Factory, pipeline = env
    _ = _make_user(Factory, credits=5)

    # A client may also nest the key directly under ``params`` (no top-level field).
    resp = client.post(
        "/api/v1/jobs",
        json={"params": {**_PARAMS, "voiceover_key": _VOICEOVER_KEY}},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    _, enq_params = pipeline.start_calls[0]
    assert enq_params.voiceover_key == _VOICEOVER_KEY


def test_create_job_with_voiceover_key_needs_no_voice_id(env):
    client, Factory, pipeline = env
    _make_user(Factory, credits=5)

    # A BYOV job supplies NO voice_id: the uploaded audio is the narration, so the
    # request must succeed and carry an empty voice_name through the DTO.
    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "voiceover_key": _VOICEOVER_KEY},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    _, enq_params = pipeline.start_calls[0]
    assert enq_params.voiceover_key == _VOICEOVER_KEY
    assert enq_params.voice_name == ""                 # no TTS voice needed


# --------------------------------------------------------------------------- #
# WITHOUT voiceover_key — behaviour is unchanged (the DTO default is "").
# --------------------------------------------------------------------------- #
def test_create_job_without_voiceover_key_unchanged(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)

    resp = client.post("/api/v1/jobs", json={"params": _PARAMS}, headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    assert len(pipeline.start_calls) == 1

    # The DTO carries the empty default -> the pipeline uses TTS, not BYOV.
    _, enq_params = pipeline.start_calls[0]
    assert enq_params.voiceover_key == ""

    # Nothing BYOV-specific is persisted; classic single-credit debit is unchanged.
    with Factory() as s:
        job = JobRepository(s).list_for_user(uid)[0]
    assert job.params.get("voiceover_key", "") == ""
    assert _balance(Factory, uid) == 4
