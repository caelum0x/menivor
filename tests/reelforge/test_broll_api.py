"""API-level tests for the AI B-roll cutaways surface (§ b-roll).

Covers the two ReelForge controller touch-points authored in
``app/controllers/v1/jobs.py``:

* ``POST /jobs/{job_id}/broll/suggest`` — auth + OWNERSHIP on the job, per-user
  rate limit, then a best-effort call into ``broll.suggest_broll`` using the
  *job's own* subject/script. Returns ``{clips: [...]}``.
* ``POST /jobs`` threading ``broll_intro_key`` / ``broll_outro_key`` into the
  persisted ``Job.params`` for the compose stage.

No external I/O: ``broll.suggest_broll`` is monkeypatched (via a fake B-roll
module) and ``start_pipeline`` is a fake that records its calls, all behind an
in-memory SQLite DB + FastAPI ``TestClient`` — mirroring ``test_api.py``.
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
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository, JobRepository
from app.models.exception import HttpException
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


_API_KEY = "broll-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

_OTHER_API_KEY = "broll-other-key"
_OTHER_KEY_HASH = hashlib.sha256(_OTHER_API_KEY.encode("utf-8")).hexdigest()
_OTHER_HEADERS = {"x-api-key": _OTHER_API_KEY}

_PARAMS = {"video_subject": "morning coffee routine", "video_script": "manual copy"}


# =========================================================================== #
# Fakes
# =========================================================================== #
class _FakePipeline:
    """Records ``start_pipeline`` calls so a create can be inspected."""

    def __init__(self) -> None:
        self.start_calls: list = []

    def start_pipeline(self, job_id, params):
        self.start_calls.append((job_id, params))
        return "celery-start-id"


class _FakeBroll:
    """Fake ``app.services.broll`` module: records ``suggest_broll`` calls.

    ``result`` is what each call returns; set ``raise_exc`` to simulate a truly
    unexpected failure (the service contract is best-effort, but the controller
    also guards the call).
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.result: list[dict] = []
        self.raise_exc: Exception | None = None

    def suggest_broll(self, job_id, subject, script="", source="pexels", amount=6):
        self.calls.append(
            {
                "job_id": job_id,
                "subject": subject,
                "script": script,
                "source": source,
                "amount": amount,
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
    """Wire the jobs controller to an in-memory SQLite DB + fake pipeline/broll."""
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
    fake_broll = _FakeBroll()

    monkeypatch.setattr(jobs_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(jobs_mod, "_import_pipeline", lambda rid: fake_pipeline)
    monkeypatch.setattr(jobs_mod, "_import_broll", lambda rid: fake_broll)
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

    return client, Factory, fake_pipeline, fake_broll


def _make_user(Factory, email, key_hash, credits=0) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        if credits:
            CreditRepository(s).grant(uid, credits, reason="signup")
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
# POST /jobs/{job_id}/broll/suggest
# =========================================================================== #
def test_suggest_returns_clips_for_owned_job(env):
    client, Factory, _pipeline, fake_broll = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    jid = _make_job(Factory, uid)
    fake_broll.result = [
        {
            "broll_key": f"jobs/{jid}/broll/aaa.mp4",
            "duration": 5.0,
            "source": "pexels",
            "term": "coffee",
        },
        {
            "broll_key": f"jobs/{jid}/broll/bbb.mp4",
            "duration": 4.5,
            "source": "pexels",
            "term": "morning",
        },
    ]

    resp = client.post(
        f"/api/v1/jobs/{jid}/broll/suggest",
        json={"source": "pexels", "amount": 2},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    clips = resp.json()["data"]["clips"]
    assert [c["broll_key"] for c in clips] == [
        f"jobs/{jid}/broll/aaa.mp4",
        f"jobs/{jid}/broll/bbb.mp4",
    ]
    # The service was called with the job's own subject + source/amount.
    assert len(fake_broll.calls) == 1
    call = fake_broll.calls[0]
    assert call["job_id"] == jid
    assert call["subject"] == "morning coffee routine"
    assert call["source"] == "pexels"
    assert call["amount"] == 2


def test_suggest_uses_persisted_script_over_manual_params(env):
    client, Factory, _pipeline, fake_broll = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    # A job with BOTH a manual params.video_script and a finalized Job.script:
    # the persisted narration wins.
    jid = _make_job(Factory, uid, script="the finalized narration script")

    resp = client.post(
        f"/api/v1/jobs/{jid}/broll/suggest", json={}, headers=_HEADERS
    )

    assert resp.status_code == 200, resp.text
    call = fake_broll.calls[0]
    assert call["script"] == "the finalized narration script"
    # Bare body -> service default source; amount not forwarded (service default).
    assert call["source"] == "pexels"
    assert call["amount"] == 6


def test_suggest_foreign_job_returns_404_and_does_not_call_service(env):
    client, Factory, _pipeline, fake_broll = env
    owner = _make_user(Factory, "owner@example.com", _KEY_HASH)
    _make_user(Factory, "other@example.com", _OTHER_KEY_HASH)
    jid = _make_job(Factory, owner)

    # A DIFFERENT user tries to suggest B-roll for the owner's job.
    resp = client.post(
        f"/api/v1/jobs/{jid}/broll/suggest",
        json={"source": "pexels"},
        headers=_OTHER_HEADERS,
    )

    assert resp.status_code == 404, resp.text
    # No existence leak + the external/LLM service is never reached.
    assert fake_broll.calls == []


def test_suggest_unknown_job_returns_404(env):
    client, Factory, _pipeline, fake_broll = env
    _make_user(Factory, "owner@example.com", _KEY_HASH)

    resp = client.post(
        "/api/v1/jobs/does-not-exist/broll/suggest", json={}, headers=_HEADERS
    )

    assert resp.status_code == 404, resp.text
    assert fake_broll.calls == []


def test_suggest_missing_api_key_returns_401(env):
    client, Factory, _pipeline, fake_broll = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    jid = _make_job(Factory, uid)

    resp = client.post(f"/api/v1/jobs/{jid}/broll/suggest", json={})

    assert resp.status_code == 401, resp.text
    assert fake_broll.calls == []


def test_suggest_is_best_effort_on_service_failure(env):
    client, Factory, _pipeline, fake_broll = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    jid = _make_job(Factory, uid)
    fake_broll.raise_exc = RuntimeError("provider exploded")

    resp = client.post(
        f"/api/v1/jobs/{jid}/broll/suggest", json={}, headers=_HEADERS
    )

    # A B-roll failure never surfaces as a hard error: 200 with an empty list.
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["clips"] == []


def test_suggest_amount_out_of_range_rejected_by_schema(env):
    client, Factory, _pipeline, fake_broll = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH)
    jid = _make_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/broll/suggest",
        json={"amount": 999},
        headers=_HEADERS,
    )

    assert resp.status_code == 422, resp.text
    assert fake_broll.calls == []


# =========================================================================== #
# POST /jobs threading broll_intro_key / broll_outro_key
# =========================================================================== #
def test_create_job_threads_broll_keys_into_params(env):
    client, Factory, pipeline, _broll = env
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH, credits=5)

    intro = "jobs/some-prev-job/broll/intro.mp4"
    outro = "jobs/some-prev-job/broll/outro.mp4"
    resp = client.post(
        "/api/v1/jobs",
        json={
            "params": {"video_subject": "cats"},
            "broll_intro_key": intro,
            "broll_outro_key": outro,
        },
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    # Enqueued exactly once, and the render DTO carries the B-roll keys.
    assert len(pipeline.start_calls) == 1
    _, called_params = pipeline.start_calls[0]
    assert called_params.broll_intro_key == intro
    assert called_params.broll_outro_key == outro
    # They are real ReelForgeParams fields, so they also land in Job.params.
    with Factory() as s:
        job = JobRepository(s).list_for_user(uid)[0]
    assert job.params.get("broll_intro_key") == intro
    assert job.params.get("broll_outro_key") == outro


def test_create_job_without_broll_keys_defaults_to_empty(env):
    client, Factory, pipeline, _broll = env
    _make_user(Factory, "owner@example.com", _KEY_HASH, credits=5)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": {"video_subject": "cats"}},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    # An omitted key is the DTO default (empty string => no cutaway spliced),
    # never a foreign value.
    _, called_params = pipeline.start_calls[0]
    assert called_params.broll_intro_key == ""
    assert called_params.broll_outro_key == ""
