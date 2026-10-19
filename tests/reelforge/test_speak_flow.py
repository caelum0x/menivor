"""Wave 4 SPEAK — end-to-end flow: the controller composes an image+audio job,
the service delegate drives the lipsync adapter submit->poll->rehost, and the
failure path (idempotent refund) is exercised.

No external I/O: an in-memory SQLite DB + FastAPI ``TestClient`` back the
controller (mirrors ``test_broll_api.py``); the service seams (presign, adapter,
download, persist) are monkeypatched so the composition logic runs without a
network or broker.
"""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.domains.speak.router as speak_router
import app.domains.speak.service as speak_service
from app.domains.media.service import MediaDomainError
from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    NormalizedUsage,
    ProviderRun,
)
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository, JobRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "speak-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

_OTHER_API_KEY = "speak-other-key"
_OTHER_KEY_HASH = hashlib.sha256(_OTHER_API_KEY.encode("utf-8")).hexdigest()
_OTHER_HEADERS = {"x-api-key": _OTHER_API_KEY}


# =========================================================================== #
# Fakes
# =========================================================================== #
class FakeLipsyncAdapter:
    """Fake ProviderAdapter: submit records the request, poll -> terminal."""

    def __init__(self, *, final_state=RUN_COMPLETED, seconds=6):
        self.provider_key = "musetalk"
        self.submitted: dict | None = None
        self._final_state = final_state
        self._seconds = seconds

    def submit(self, request, snapshot, correlation_id):
        self.submitted = dict(request)
        return ProviderRun(provider_key="musetalk", run_id="run-1", state=RUN_QUEUED)

    def poll(self, run):
        usage = None
        result_ref = ""
        if self._final_state == RUN_COMPLETED:
            usage = NormalizedUsage(
                unit="seconds", quantity_units=self._seconds, cost_micros=0
            )
            result_ref = "https://cdn.example.com/talk.mp4"
        return ProviderRun(
            provider_key="musetalk",
            run_id=run.run_id,
            state=self._final_state,
            result_ref=result_ref,
            usage=usage,
        )


class _FakeR2:
    def __init__(self):
        self.uploaded: list[tuple[str, bytes, str]] = []

    def upload_bytes(self, key, data, content_type="application/octet-stream"):
        self.uploaded.append((key, data, content_type))
        return key


# =========================================================================== #
# Service: run_speak_generation composes image+audio -> job
# =========================================================================== #
def test_run_speak_generation_composes_image_and_audio(monkeypatch):
    presigned: list[str] = []

    monkeypatch.setattr(
        speak_service,
        "_load_job_context",
        lambda job_id: (
            "u-1",
            {
                "image_key": "uploads/img.png",
                "audio_key": "uploads/narr.wav",
                "provider": "musetalk",
                "license_class": "open_commercial",
                "_correlation_id": "corr-9",
            },
        ),
    )

    def _fake_presign(key):
        presigned.append(key)
        return f"signed://{key}"

    monkeypatch.setattr(speak_service, "_presign_owned", _fake_presign)
    fake = FakeLipsyncAdapter(seconds=6)
    monkeypatch.setattr(speak_service, "_resolve_adapter", lambda pk: fake)
    monkeypatch.setattr(speak_service, "_set_progress", lambda *a, **k: None)
    monkeypatch.setattr(speak_service, "_download_bytes", lambda url: b"mp4-bytes")
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    fake_r2 = _FakeR2()
    monkeypatch.setattr(
        "app.platform.storage.r2.get_r2_client", lambda: fake_r2
    )

    persisted: dict = {}

    def _fake_persist(**kwargs):
        persisted.update(kwargs)

    monkeypatch.setattr(speak_service, "_persist_and_complete", _fake_persist)

    out = speak_service.run_speak_generation("job-1")

    # BOTH owned inputs were presigned (never a raw client URL) and forwarded.
    assert presigned == ["uploads/img.png", "uploads/narr.wav"]
    assert fake.submitted == {
        "image_url": "signed://uploads/img.png",
        "audio_url": "signed://uploads/narr.wav",
    }
    # Result mp4 was re-hosted under this job's speak prefix, server-side key.
    assert fake_r2.uploaded and fake_r2.uploaded[0][0].startswith("jobs/job-1/speak/")
    assert fake_r2.uploaded[0][2] == "video/mp4"
    assert out["talking_video_key"].startswith("jobs/job-1/speak/")
    assert out["duration"] == 6.0
    # The Asset provenance + completion carried the rehosted key + provider.
    assert persisted["talking_video_key"].startswith("jobs/job-1/speak/")
    assert persisted["meta"]["provider"] == "musetalk"


def test_run_speak_generation_requires_both_inputs(monkeypatch):
    monkeypatch.setattr(
        speak_service,
        "_load_job_context",
        lambda job_id: ("u-1", {"image_key": "uploads/i.png", "provider": "musetalk"}),
    )
    monkeypatch.setattr(speak_service, "_set_progress", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        speak_service.run_speak_generation("job-1")


def test_run_speak_generation_raises_on_provider_failure(monkeypatch):
    monkeypatch.setattr(
        speak_service,
        "_load_job_context",
        lambda job_id: (
            "u-1",
            {
                "image_key": "uploads/i.png",
                "audio_key": "uploads/a.wav",
                "provider": "musetalk",
            },
        ),
    )
    monkeypatch.setattr(speak_service, "_presign_owned", lambda key: f"signed://{key}")
    monkeypatch.setattr(
        speak_service, "_resolve_adapter", lambda pk: FakeLipsyncAdapter(final_state=RUN_FAILED)
    )
    monkeypatch.setattr(speak_service, "_set_progress", lambda *a, **k: None)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError):
        speak_service.run_speak_generation("job-1")


# =========================================================================== #
# Service: idempotent refund on failure
# =========================================================================== #
@pytest.fixture()
def db(monkeypatch):
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

    monkeypatch.setattr("app.models.db.base.get_session", _fake_get_session)
    return Factory


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


def test_refund_speak_generation_is_idempotent(db):
    Factory = db
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH, credits=10)
    with Factory() as s:
        job = JobRepository(s).create(
            user_id=uid,
            kind="speak_lipsync",
            params={"credits_cost": 5, "workspace_id": None},
        )
        jid = job.id
        # Simulate the up-front debit committed by the controller.
        CreditRepository(s).debit(uid, 5, jid, "speak_lipsync_debit")
        s.commit()

    with Factory() as s:
        assert CreditRepository(s).balance(uid) == 5  # 10 granted - 5 debited

    speak_service.refund_speak_generation(jid)
    speak_service.refund_speak_generation(jid)  # second call is a no-op

    with Factory() as s:
        assert CreditRepository(s).balance(uid) == 10  # refunded exactly once
        job = JobRepository(s).get(jid)
        assert job.params.get("refunded") is True


# =========================================================================== #
# Controller: POST /generation/speak/generate composes a Job(kind='speak_lipsync')
# =========================================================================== #
@pytest.fixture()
def api(monkeypatch):
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

    monkeypatch.setattr(speak_router, "get_session", _fake_get_session)
    # Rate limit + ownership are covered elsewhere; keep the studio test focused
    # on composition (ownership toggled per-test).
    monkeypatch.setattr(speak_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(speak_router, "require_owned_asset", lambda *a, **k: None)

    enqueued: list[str] = []
    monkeypatch.setattr(
        speak_router, "_enqueue_generation", lambda gid, rid: enqueued.append(gid)
    )

    app = FastAPI()
    app.include_router(speak_router.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory, enqueued


def test_generate_composes_speak_job_and_debits(api, monkeypatch):
    from app.services.billing import premium_credits

    client, Factory, enqueued = api
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH, credits=10)
    with Factory() as s:
        premium_credits.grant(s, uid, premium_credits.KIND_AI_VIDEO, 100, "test_grant")
        s.commit()

    resp = client.post(
        "/api/v1/generation/speak/generate",
        json={"image_key": "uploads/face.png", "audio_key": "uploads/vo.wav"},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    gid = data["generation_id"]
    # Provider resolved to a commercial-safe default, license class recorded.
    assert data["provider"] == "musetalk"
    assert data["license_class"] == "open_commercial"

    # A Job(kind='speak_lipsync') was persisted carrying BOTH owned keys.
    with Factory() as s:
        job = JobRepository(s).get(gid)
        assert job.kind == "speak_lipsync"
        assert job.params["image_key"] == "uploads/face.png"
        assert job.params["audio_key"] == "uploads/vo.wav"
        assert job.params["provider"] == "musetalk"
        # A presenter render never touches standard credits: it reserves
        # AI-video credits at 3x the provider estimate (60 s of musetalk).
        assert job.params["credits_cost"] == 0
        needed = job.params["ai_video_credits"]
        assert needed == premium_credits.ai_video_credits_for_usd(job.params["provider_usd_estimate"])
        assert CreditRepository(s).balance(uid) == 10
        assert premium_credits.balance(s, uid, premium_credits.KIND_AI_VIDEO) == 100 - needed
    # Enqueued exactly once after the debit committed.
    assert enqueued == [gid]


def test_generate_without_ai_video_credits_is_402_and_charges_nothing(api):
    client, Factory, enqueued = api
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH, credits=10)
    resp = client.post(
        "/api/v1/generation/speak/generate",
        json={"image_key": "uploads/face.png", "audio_key": "uploads/vo.wav"},
        headers=_HEADERS,
    )
    assert resp.status_code == 402, resp.text
    assert resp.json()["data"]["code"] == "ai_video_credits_required"
    with Factory() as s:
        assert CreditRepository(s).balance(uid) == 10
    assert enqueued == []


def test_generate_requires_audio_key(api):
    client, Factory, enqueued = api
    _make_user(Factory, "owner@example.com", _KEY_HASH, credits=10)

    resp = client.post(
        "/api/v1/generation/speak/generate",
        json={"image_key": "uploads/face.png", "audio_key": ""},
        headers=_HEADERS,
    )
    # Empty audio_key is rejected by the schema (min_length=1) -> 422.
    assert resp.status_code == 422, resp.text
    assert enqueued == []


def test_generate_rejects_foreign_asset_before_debit(api, monkeypatch):
    client, Factory, enqueued = api
    uid = _make_user(Factory, "owner@example.com", _KEY_HASH, credits=10)

    def _deny(session, *, user_id, key):
        raise MediaDomainError(403, "media key does not belong to the caller")

    monkeypatch.setattr(speak_router, "require_owned_asset", _deny)

    resp = client.post(
        "/api/v1/generation/speak/generate",
        json={"image_key": "uploads/not-mine.png", "audio_key": "uploads/vo.wav"},
        headers=_HEADERS,
    )

    assert resp.status_code == 403, resp.text
    # No job created, no debit, no enqueue.
    with Factory() as s:
        assert JobRepository(s).list_for_user_by_kind(uid, "speak_lipsync", limit=10) == []
        assert CreditRepository(s).balance(uid) == 10
    assert enqueued == []


def test_generate_insufficient_credits_returns_402(api):
    client, Factory, enqueued = api
    _make_user(Factory, "poor@example.com", _KEY_HASH, credits=0)

    resp = client.post(
        "/api/v1/generation/speak/generate",
        json={"image_key": "uploads/face.png", "audio_key": "uploads/vo.wav"},
        headers=_HEADERS,
    )
    assert resp.status_code == 402, resp.text
    assert enqueued == []


def test_generate_rejects_unapproved_provider(api):
    client, Factory, enqueued = api
    _make_user(Factory, "owner@example.com", _KEY_HASH, credits=10)

    resp = client.post(
        "/api/v1/generation/speak/generate",
        json={
            "image_key": "uploads/face.png",
            "audio_key": "uploads/vo.wav",
            "provider": "some-comfy-deployment",
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 400, resp.text
    assert enqueued == []


def test_poll_generation_is_owner_scoped(api):
    client, Factory, _enqueued = api
    owner = _make_user(Factory, "owner@example.com", _KEY_HASH, credits=10)
    _make_user(Factory, "other@example.com", _OTHER_KEY_HASH, credits=10)
    with Factory() as s:
        job = JobRepository(s).create(
            user_id=owner, kind="speak_lipsync", params={"provider": "musetalk"}
        )
        jid = job.id
        s.commit()

    # Owner can poll.
    ok = client.get(f"/api/v1/generation/speak/generations/{jid}", headers=_HEADERS)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["generation_id"] == jid

    # A different user gets 404 (no existence leak).
    foreign = client.get(
        f"/api/v1/generation/speak/generations/{jid}", headers=_OTHER_HEADERS
    )
    assert foreign.status_code == 404, foreign.text
