"""API-level tests for the ReelForge v1 controller (INTEGRATION_CONTRACT.md §5).

These exercise the concurrency-safety and authorization fixes in
``app/controllers/v1/jobs.py`` against an in-memory SQLite DB with a monkeypatched
``get_session`` and a fake Celery pipeline — no Postgres/Redis/Celery required:

* Credit TOCTOU (#6): the debit is committed *before* enqueue; an insufficient
  balance yields 402 with no enqueue; an enqueue failure refunds the debit.
* Retry TOCTOU (#7/#8): a FAILED->PROCESSING compare-and-set means a second
  concurrent retry loses with 409; ``pipeline.retry_pipeline`` is called with the
  exact ``(job_id, params, failed_stage)`` signature; retries are charged credits.
* MIME allowlist (#9): ``PresignRequest.content_type`` rejects non-media types.
* GET /jobs list + ownership on read/retry.
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
import app.controllers.v1.me as me_mod
from app.controllers.v1.me import UserPreset
from app.domains.media.router import router as media_router
from app.models import const
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import CreditRepository, JobRepository
from app.models.exception import HttpException
from app.models.schema import PresignRequest
from app.services import referrals
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


_API_KEY = "testkey"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}
_PARAMS = {"video_subject": "cats"}


class _FakePipeline:
    """Records enqueue calls; ``start`` / ``retry`` can be made to raise."""

    def __init__(self) -> None:
        self.start_calls: list = []
        self.retry_calls: list = []
        self.raise_on_start = False
        self.raise_on_retry = False

    def start_pipeline(self, job_id, params):
        self.start_calls.append((job_id, params))
        if self.raise_on_start:
            raise RuntimeError("broker down")
        return "celery-start-id"

    def retry_pipeline(self, job_id, params, failed_stage):
        self.retry_calls.append((job_id, params, failed_stage))
        if self.raise_on_retry:
            raise RuntimeError("broker down")
        return "celery-retry-id"


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
    # credit + enqueue logic under test is isolated.
    monkeypatch.setattr(
        jobs_mod, "_validate_enabled_feature_secrets", lambda params, rid: None
    )

    app = FastAPI()
    app.include_router(jobs_mod.router)
    app.include_router(media_router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    client = TestClient(app)

    return client, Factory, fake_pipeline


def _make_user(Factory, email="tester@example.com", credits=0) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=_KEY_HASH, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        if credits:
            CreditRepository(s).grant(uid, credits, reason="signup")
        s.commit()
    return uid


def _make_failed_job(Factory, user_id, failed_stage="tts") -> str:
    with Factory() as s:
        job = JobRepository(s).create(
            user_id=user_id, kind="avatar_reel", params=_PARAMS
        )
        jid = job.id
        JobRepository(s).mark_failed(jid, failed_stage, "boom")
        s.commit()
    return jid


def _balance(Factory, user_id) -> int:
    with Factory() as s:
        return CreditRepository(s).balance(user_id)


# --------------------------------------------------------------------------- #
# #6 — create_job credit TOCTOU
# --------------------------------------------------------------------------- #
def test_create_job_debits_then_enqueues(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)

    resp = client.post("/api/v1/jobs", json={"params": _PARAMS}, headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["state"] == const.TASK_STATE_PROCESSING
    assert len(pipeline.start_calls) == 1          # enqueued exactly once
    assert _balance(Factory, uid) == 4             # debited before enqueue


def test_create_job_idempotency_key_replays_without_second_debit_or_enqueue(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    headers = {**_HEADERS, "Idempotency-Key": "create-cats-001"}

    first = client.post("/api/v1/jobs", json={"params": _PARAMS}, headers=headers)
    second = client.post("/api/v1/jobs", json={"params": _PARAMS}, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["data"] == first.json()["data"]
    assert len(pipeline.start_calls) == 1
    assert _balance(Factory, uid) == 4
    with Factory() as session:
        assert len(JobRepository(session).list_for_user(uid)) == 1


def test_create_job_idempotency_key_rejects_a_different_payload(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    headers = {**_HEADERS, "Idempotency-Key": "create-once-001"}

    first = client.post("/api/v1/jobs", json={"params": _PARAMS}, headers=headers)
    second = client.post(
        "/api/v1/jobs",
        json={"params": {"video_subject": "dogs"}},
        headers=headers,
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert len(pipeline.start_calls) == 1
    assert _balance(Factory, uid) == 4


def test_create_job_idempotency_key_replays_an_entire_variant_batch(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    headers = {**_HEADERS, "Idempotency-Key": "batch-cats-001"}
    payload = {"params": _PARAMS, "variants": 3}

    first = client.post("/api/v1/jobs", json=payload, headers=headers)
    second = client.post("/api/v1/jobs", json=payload, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["data"] == first.json()["data"]
    assert len(first.json()["data"]["job_ids"]) == 3
    assert len(pipeline.start_calls) == 3
    assert _balance(Factory, uid) == 2


def test_create_job_cost_cap_rejects_before_debit_or_enqueue(env, monkeypatch):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    from app.services import cost_guard

    monkeypatch.setattr(cost_guard, "max_job_cost_usd", lambda: 0.01)

    response = client.post("/api/v1/jobs", json={"params": _PARAMS}, headers=_HEADERS)

    assert response.status_code == 422, response.text
    assert pipeline.start_calls == []
    assert _balance(Factory, uid) == 5
    with Factory() as session:
        assert JobRepository(session).list_for_user(uid) == []


def test_create_job_insufficient_credits_402_no_enqueue(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=0)

    resp = client.post("/api/v1/jobs", json={"params": _PARAMS}, headers=_HEADERS)

    assert resp.status_code == 402, resp.text
    assert pipeline.start_calls == []              # never enqueued
    assert _balance(Factory, uid) == 0
    # The rolled-back transaction leaves no orphan job.
    with Factory() as s:
        assert JobRepository(s).list_for_user(uid) == []


def test_create_job_enqueue_failure_refunds(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=3)
    pipeline.raise_on_start = True

    resp = client.post("/api/v1/jobs", json={"params": _PARAMS}, headers=_HEADERS)

    assert resp.status_code == 502, resp.text
    # Debit reconciled by a refund -> balance restored.
    assert _balance(Factory, uid) == 3
    with Factory() as s:
        job = JobRepository(s).list_for_user(uid)[0]
        assert job.state == const.TASK_STATE_FAILED


# --------------------------------------------------------------------------- #
# #7 / #8 — retry TOCTOU + signature + credits
# --------------------------------------------------------------------------- #
def test_retry_calls_retry_pipeline_with_exact_signature(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_failed_job(Factory, uid, failed_stage="tts")

    resp = client.post(f"/api/v1/jobs/{jid}/retry", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    assert len(pipeline.retry_calls) == 1
    called_job_id, called_params, called_stage = pipeline.retry_calls[0]
    assert called_job_id == jid
    assert called_stage == "tts"
    assert called_params.video_subject == "cats"   # rebuilt ReelForgeParams
    assert _balance(Factory, uid) == 4             # retry charged


def test_second_concurrent_retry_returns_409(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_failed_job(Factory, uid)

    first = client.post(f"/api/v1/jobs/{jid}/retry", headers=_HEADERS)
    second = client.post(f"/api/v1/jobs/{jid}/retry", headers=_HEADERS)

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text   # loser rejected
    assert len(pipeline.retry_calls) == 1           # only one enqueue


def test_retry_enqueue_failure_refunds(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_failed_job(Factory, uid)
    pipeline.raise_on_retry = True

    resp = client.post(f"/api/v1/jobs/{jid}/retry", headers=_HEADERS)

    assert resp.status_code == 502, resp.text
    assert _balance(Factory, uid) == 5              # refunded


def test_retry_insufficient_credits_402(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=0)
    jid = _make_failed_job(Factory, uid)

    resp = client.post(f"/api/v1/jobs/{jid}/retry", headers=_HEADERS)

    assert resp.status_code == 402, resp.text
    assert pipeline.retry_calls == []


def test_retry_enqueue_failure_refund_db_error_does_not_crash(env, monkeypatch):
    """A DB error inside the retry refund must not poison the mark_failed session.

    Defect [1]: mark_failed + grant previously shared ONE session — a failed
    ``grant`` (poisoned transaction) would roll the FAILED transition back and
    surface a 500, leaving the job stuck PROCESSING and the retry credit leaked.
    The fix commits mark_failed on its own session first, then refunds on a
    separate isolated session (matching ``_refund_and_fail_job``).
    """
    from app.models.db.models import CreditLedger

    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_failed_job(Factory, uid)
    pipeline.raise_on_retry = True  # enqueue fails -> refund/fail path runs

    def _poison_grant(self, user_id, amount, reason):
        # A failed flush (NOT NULL violation) deactivates the surrounding
        # transaction under SQLAlchemy 2.0 exactly like a real DB error would.
        self._session.add(
            CreditLedger(user_id=user_id, delta=None, reason=reason, balance_after=0)
        )
        self._session.flush()

    monkeypatch.setattr(jobs_mod.CreditRepository, "grant", _poison_grant)

    resp = client.post(f"/api/v1/jobs/{jid}/retry", headers=_HEADERS)

    # No 500: the poisoned refund session is isolated from mark_failed.
    assert resp.status_code == 502, resp.text
    with Factory() as s:
        job = JobRepository(s).get(jid)
    # mark_failed committed despite the refund failure -> recoverable via retry,
    # NOT stuck in PROCESSING.
    assert job.state == const.TASK_STATE_FAILED


def test_retry_set_task_id_failure_reconciles_and_502(env, monkeypatch):
    """A commit failure while persisting the Celery task id must be reconciled.

    Defect [2]: ``set_celery_task_id`` was unguarded — a commit error surfaced as
    an unhandled 500 for an operation that actually succeeded, stranding the job
    in PROCESSING with no persisted celery_task_id and the credit unrefunded. The
    fix wraps it and reconciles (refund + FAILED) exactly like ``create_job``.
    """
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_failed_job(Factory, uid)

    def _flaky(self, job_id, celery_task_id):
        raise RuntimeError("db connection reset")

    monkeypatch.setattr(jobs_mod.JobRepository, "set_celery_task_id", _flaky)

    resp = client.post(f"/api/v1/jobs/{jid}/retry", headers=_HEADERS)

    assert resp.status_code == 502, resp.text        # handled, not an unhandled 500
    assert len(pipeline.retry_calls) == 1            # the task WAS enqueued
    assert _balance(Factory, uid) == 5               # retry credit refunded
    with Factory() as s:
        job = JobRepository(s).get(jid)
    assert job.state == const.TASK_STATE_FAILED       # reconciled, not stuck PROCESSING


# --------------------------------------------------------------------------- #
# GET /jobs list + ownership
# --------------------------------------------------------------------------- #
def test_list_jobs_scoped_to_user(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, email="a@x.com", credits=0)
    other = _make_user(Factory, email="b@x.com", credits=0)
    with Factory() as s:
        JobRepository(s).create(user_id=uid, kind="avatar_reel", params=_PARAMS)
        JobRepository(s).create(user_id=uid, kind="avatar_reel", params=_PARAMS)
        JobRepository(s).create(user_id=other, kind="avatar_reel", params=_PARAMS)
        s.commit()

    resp = client.get("/api/v1/jobs", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    jobs = resp.json()["data"]["jobs"]
    assert len(jobs) == 2                           # only the caller's jobs
    assert all("job_id" in j for j in jobs)


def test_get_job_foreign_returns_404(env):
    client, Factory, pipeline = env
    # Owner has a DISTINCT api key; the caller (x-api-key) is a different user.
    owner_key_hash = hashlib.sha256(b"ownerkey").hexdigest()
    with Factory() as s:
        owner = User(email="owner@x.com", api_key_hash=owner_key_hash)
        s.add(owner)
        s.flush()
        job = JobRepository(s).create(
            user_id=owner.id, kind="avatar_reel", params=_PARAMS
        )
        jid = job.id
        s.commit()
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.get(f"/api/v1/jobs/{jid}", headers=_HEADERS)

    assert resp.status_code == 404, resp.text  # ownership enforced, no leak


def test_retry_foreign_returns_404(env, monkeypatch):
    client, Factory, pipeline = env
    # Owner has a DISTINCT api key so the caller cannot resolve to them.
    owner_key_hash = hashlib.sha256(b"ownerkey").hexdigest()
    with Factory() as s:
        owner = User(email="owner2@x.com", api_key_hash=owner_key_hash)
        s.add(owner)
        s.flush()
        owner_id = owner.id
        job = JobRepository(s).create(
            user_id=owner_id, kind="avatar_reel", params=_PARAMS
        )
        jid = job.id
        JobRepository(s).mark_failed(jid, "tts", "boom")
        s.commit()
    _make_user(Factory, email="caller2@x.com", credits=5)  # the x-api-key caller

    resp = client.post(f"/api/v1/jobs/{jid}/retry", headers=_HEADERS)

    assert resp.status_code == 404, resp.text       # cannot retry another's job
    assert pipeline.retry_calls == []


def _grant_pro(monkeypatch) -> None:
    from app.services.billing import revenuecat_client

    monkeypatch.setattr(
        revenuecat_client, "require_pro_entitlement", lambda *a, **k: None
    )


# --------------------------------------------------------------------------- #
# result_url must use the 7-day presign (CTO §5.6), not the 15-min default.
# --------------------------------------------------------------------------- #
def test_get_job_result_url_uses_seven_day_presign(env, monkeypatch):
    client, Factory, pipeline = env
    uid = _make_user(Factory)
    with Factory() as s:
        job = JobRepository(s).create(
            user_id=uid, kind="avatar_reel", params=_PARAMS
        )
        jid = job.id
        JobRepository(s).mark_complete(jid, "results/out.mp4")
        s.commit()

    calls: dict[str, str] = {}

    class _FakeR2:
        def presign_get(self, key, *a, **k):  # 15-min default path (must NOT be used)
            calls["presign_get"] = key
            return "https://r2/short-lived"

        def presign_result_get(self, key, *a, **k):  # 7-day path (§5.6)
            calls["presign_result_get"] = key
            return "https://r2/seven-day"

    import app.services.storage.r2 as r2_mod

    monkeypatch.setattr(r2_mod, "get_r2_client", lambda: _FakeR2())
    # The clean MP4 is only presigned for a verified Pro entitlement.
    _grant_pro(monkeypatch)

    resp = client.get(f"/api/v1/jobs/{jid}", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # The 7-day presign helper must produce the surfaced URL, not the default.
    assert data["result_url"] == "https://r2/seven-day"
    assert calls == {"presign_result_get": "results/out.mp4"}


def test_get_job_withholds_clean_result_url_without_pro(env, monkeypatch):
    client, Factory, pipeline = env
    uid = _make_user(Factory)
    with Factory() as s:
        job = JobRepository(s).create(user_id=uid, kind="avatar_reel", params=_PARAMS)
        jid = job.id
        JobRepository(s).mark_complete(jid, "results/out.mp4")
        s.commit()

    calls: list[str] = []

    class _FakeR2:
        def presign_result_get(self, key, *a, **k):
            calls.append(key)
            return "https://r2/seven-day"

    import app.services.storage.r2 as r2_mod
    from app.services.billing import revenuecat_client

    def _deny(*_a, **_k):
        raise revenuecat_client.RevenueCatAccessDenied("Pro required")

    monkeypatch.setattr(r2_mod, "get_r2_client", lambda: _FakeR2())
    monkeypatch.setattr(revenuecat_client, "require_pro_entitlement", _deny)

    resp = client.get(f"/api/v1/jobs/{jid}", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"].get("result_url") is None
    assert "results/out.mp4" not in calls  # the clean MP4 is never signed


# --------------------------------------------------------------------------- #
# GET /voices — curated catalog (CTO §4/§5.2)
# --------------------------------------------------------------------------- #
def test_list_voices_returns_curated_six_with_shape(env):
    client, Factory, pipeline = env
    _make_user(Factory)

    resp = client.get("/api/v1/voices", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    voices = resp.json()["data"]
    assert isinstance(voices, list)
    assert len(voices) == 6                              # curated 3 TR + 3 EN
    required = {"id", "name", "language", "gender", "description"}
    for v in voices:
        assert required.issubset(v.keys())
        assert v["id"]                                   # non-empty voice_id
        assert v["name"]
        assert v["language"] in {"tr", "en", "multi"}
    # 3 English + 3 Turkish-capable (multi) per the curated defaults.
    langs = [v["language"] for v in voices]
    assert langs.count("en") == 3
    assert langs.count("multi") == 3


def test_list_voices_falls_back_when_curated_missing(env, monkeypatch):
    client, Factory, pipeline = env
    _make_user(Factory)
    # Force the curated loader to report "no file" so the live-provider
    # fallback path (previous behaviour) is exercised. Inject a fake provider
    # listing so no network is hit and the legacy shape is asserted.
    monkeypatch.setattr(jobs_mod, "_load_curated_voices", lambda rid: None)
    import app.services.voice as voice_service

    monkeypatch.setattr(
        voice_service,
        "get_elevenlabs_voices",
        lambda api_key: ["elevenlabs:abc123:Sample Voice"],
    )

    resp = client.get("/api/v1/voices", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    voices = resp.json()["data"]
    # Fallback path must return the SAME shape as the curated path so clients
    # that read `.id` keep working when voices.yaml is absent (defect #2).
    assert voices == [
        {
            "id": "abc123",
            "name": "Sample Voice",
            "language": "multi",
            "gender": "",
            "description": "",
            "provider": "elevenlabs",
        }
    ]
    required = {"id", "name", "language", "gender", "description"}
    assert required.issubset(voices[0].keys())


def test_list_voices_requires_auth(env):
    client, Factory, pipeline = env
    _make_user(Factory)

    resp = client.get("/api/v1/voices")  # no x-api-key

    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------- #
# #9 — MIME allowlist on PresignRequest
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "content_type",
    ["video/mp4", "audio/mpeg", "image/png", "VIDEO/MP4", "video/mp4; charset=x"],
)
def test_presign_request_accepts_allowed_mime(content_type):
    req = PresignRequest(filename="a.mp4", content_type=content_type, size=10)
    # Normalised to the bare, lower-cased media type.
    assert req.content_type in {"video/mp4", "audio/mpeg", "image/png"}


@pytest.mark.parametrize(
    "content_type",
    ["text/html", "application/octet-stream", "application/json", "text/plain"],
)
def test_presign_request_rejects_disallowed_mime(content_type):
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        PresignRequest(filename="a.html", content_type=content_type, size=10)


def test_presign_endpoint_rejects_bad_mime_before_storage(env):
    client, Factory, pipeline = env
    _make_user(Factory)
    resp = client.post(
        "/api/v1/uploads/presign",
        json={"filename": "x.html", "content_type": "text/html", "size": 5},
        headers=_HEADERS,
    )
    # Validation rejects it before any storage call (422 by FastAPI default;
    # the production app maps RequestValidationError to 400 — either way != 200).
    assert resp.status_code != 200
    assert resp.status_code in (400, 422)


# --------------------------------------------------------------------------- #
# 5a — batch variants fan-out (CTO §4/§5.2)
# --------------------------------------------------------------------------- #
def test_create_job_variants_three_debits_three_and_returns_three_job_ids(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "variants": 3},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    job_ids = data["job_ids"]
    assert len(job_ids) == 3                       # one Job row per variant
    assert len(set(job_ids)) == 3                  # distinct jobs, not aliases
    assert data["job_id"] == job_ids[0]            # first is the canonical id
    assert data["state"] == const.TASK_STATE_PROCESSING
    assert len(pipeline.start_calls) == 3          # each variant enqueued once
    assert _balance(Factory, uid) == 2             # 5 - 3 debited before enqueue
    with Factory() as s:
        assert len(JobRepository(s).list_for_user(uid)) == 3


def test_create_job_variants_insufficient_for_n_402_no_enqueue(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=2)           # enough for 2, not for 3

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "variants": 3},
        headers=_HEADERS,
    )

    assert resp.status_code == 402, resp.text
    assert pipeline.start_calls == []              # nothing enqueued
    assert _balance(Factory, uid) == 2             # no partial debit
    with Factory() as s:                           # whole batch rolled back
        assert JobRepository(s).list_for_user(uid) == []


def test_create_job_variants_one_keeps_single_job_response(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "variants": 1},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["job_ids"] is None                 # classic single-job envelope
    assert data.get("batch_id") is None            # a lone job belongs to no batch
    assert data["job_id"]
    assert data["state"] == const.TASK_STATE_PROCESSING
    assert len(pipeline.start_calls) == 1
    assert _balance(Factory, uid) == 4
    # The single job's row is batch-less (NULL), preserving classic behavior.
    with Factory() as s:
        assert JobRepository(s).get(data["job_id"]).batch_id is None


# --------------------------------------------------------------------------- #
# Phase 10 — batch variant review: shared batch_id + GET /batches/{batch_id}
# --------------------------------------------------------------------------- #
def test_create_job_variants_three_share_one_batch_id(env):
    client, Factory, pipeline = env
    _make_user(Factory, credits=5)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "variants": 3},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    batch_id = data["batch_id"]
    assert batch_id                                    # a shared batch id is minted
    job_ids = data["job_ids"]
    assert len(job_ids) == 3
    # Every created Job row carries the one shared batch_id.
    with Factory() as s:
        repo = JobRepository(s)
        batch_ids = {repo.get(jid).batch_id for jid in job_ids}
    assert batch_ids == {batch_id}                     # all 3 share exactly one id


def test_get_batch_returns_owner_scoped_three_variants(env):
    client, Factory, pipeline = env
    _make_user(Factory, credits=5)

    created = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "variants": 3},
        headers=_HEADERS,
    )
    assert created.status_code == 200, created.text
    batch_id = created.json()["data"]["batch_id"]

    resp = client.get(f"/api/v1/batches/{batch_id}", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["batch_id"] == batch_id
    jobs = data["jobs"]
    assert len(jobs) == 3                              # every variant of the batch
    for j in jobs:
        assert "job_id" in j
        assert j["state"] == const.TASK_STATE_PROCESSING
        assert "progress" in j
    # The batch envelope's first job matches the create response's canonical id.
    assert jobs[0]["job_id"] == created.json()["data"]["job_id"]


def test_get_batch_unknown_returns_404(env):
    client, Factory, pipeline = env
    _make_user(Factory, credits=5)

    resp = client.get("/api/v1/batches/does-not-exist", headers=_HEADERS)

    assert resp.status_code == 404, resp.text          # unknown batch, no leak


def test_get_batch_foreign_returns_404(env):
    client, Factory, pipeline = env
    # Owner has a DISTINCT api key so the x-api-key caller cannot resolve to them.
    owner_key_hash = hashlib.sha256(b"ownerkey").hexdigest()
    with Factory() as s:
        owner = User(email="owner-batch@x.com", api_key_hash=owner_key_hash)
        s.add(owner)
        s.flush()
        repo = JobRepository(s)
        repo.create(user_id=owner.id, kind="avatar_reel", params=_PARAMS, batch_id="foreignbatch")
        repo.create(user_id=owner.id, kind="avatar_reel", params=_PARAMS, batch_id="foreignbatch")
        s.commit()
    _make_user(Factory, email="caller-batch@x.com", credits=0)  # the x-api-key caller

    resp = client.get("/api/v1/batches/foreignbatch", headers=_HEADERS)

    assert resp.status_code == 404, resp.text          # cannot read another's batch


def test_get_batch_surfaces_result_url_and_poster_for_finished(env, monkeypatch):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    # Two variants: complete one (with a poster) so the batch view surfaces its
    # presigned result_url + poster_key; leave the other processing.
    with Factory() as s:
        repo = JobRepository(s)
        j1 = repo.create(user_id=uid, kind="avatar_reel", params=_PARAMS, batch_id="b10")
        repo.create(user_id=uid, kind="avatar_reel", params=_PARAMS, batch_id="b10")
        repo.mark_complete(j1.id, "results/out.mp4")
        repo.set_artifacts(j1.id, poster_key="posters/p.jpg")
        done_id = j1.id
        s.commit()

    class _FakeR2:
        def presign_result_get(self, key, *a, **k):
            return "https://r2/seven-day"

    import app.services.storage.r2 as r2_mod

    monkeypatch.setattr(r2_mod, "get_r2_client", lambda: _FakeR2())
    _grant_pro(monkeypatch)

    resp = client.get("/api/v1/batches/b10", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    jobs = {j["job_id"]: j for j in resp.json()["data"]["jobs"]}
    finished = jobs[done_id]
    assert finished["result_url"] == "https://r2/seven-day"
    assert finished["poster_key"] == "posters/p.jpg"


def test_create_job_persists_tos_disclosure_flag(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "tos_disclosure": True},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    with Factory() as s:
        job = JobRepository(s).list_for_user(uid)[0]
        assert job.params.get("tos_disclosure") is True


# --------------------------------------------------------------------------- #
# x-api-key path is unchanged when Clerk is not configured
# --------------------------------------------------------------------------- #
def test_x_api_key_still_authenticates_when_clerk_unconfigured(env):
    client, Factory, pipeline = env
    _make_user(Factory, email="apikey@example.com", credits=1)

    # No [clerk] config in the test build -> bridge is inert, x-api-key resolves.
    resp = client.get("/api/v1/me", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["email"] == "apikey@example.com"


# --------------------------------------------------------------------------- #
# 5f — Clerk JWT bridge: a Bearer token maps to a (get-or-created) User
# --------------------------------------------------------------------------- #
def test_clerk_jwt_bearer_maps_to_user(env, monkeypatch):
    client, Factory, pipeline = env
    from app.config import config
    from app.core import clerk

    # Configure Clerk (issuer -> derived JWKS url) so the bridge is active, and
    # stub the signature verification with claims for a brand-new subject.
    monkeypatch.setattr(config, "clerk", {"issuer": "https://test.clerk"}, raising=False)
    monkeypatch.setattr(
        clerk,
        "verify_clerk_jwt",
        lambda token: {"sub": "user_abc", "email": "jwt@example.com", "name": "JWT User"},
    )

    # No x-api-key: only the Bearer JWT should authenticate the caller.
    resp = client.get(
        "/api/v1/me", headers={"Authorization": "Bearer fake.jwt.token"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["email"] == "jwt@example.com"
    # The user was provisioned on first sight (get-or-create).
    with Factory() as s:
        user = s.query(User).filter(User.email == "jwt@example.com").first()
        assert user is not None
        assert user.display_name == "JWT User"


def test_clerk_jwt_bearer_get_or_create_is_idempotent(env, monkeypatch):
    client, Factory, pipeline = env
    from app.config import config
    from app.core import clerk

    monkeypatch.setattr(config, "clerk", {"issuer": "https://test.clerk"}, raising=False)
    monkeypatch.setattr(
        clerk, "verify_clerk_jwt", lambda token: {"sub": "user_xyz", "email": "dup@example.com"}
    )

    h = {"Authorization": "Bearer fake.jwt.token"}
    assert client.get("/api/v1/me", headers=h).status_code == 200
    assert client.get("/api/v1/me", headers=h).status_code == 200

    # Two requests for the same subject must resolve to ONE user row.
    with Factory() as s:
        rows = s.query(User).filter(User.email == "dup@example.com").all()
        assert len(rows) == 1


def test_clerk_invalid_bearer_returns_401(env, monkeypatch):
    client, Factory, pipeline = env
    from app.config import config
    from app.core import clerk

    monkeypatch.setattr(config, "clerk", {"issuer": "https://test.clerk"}, raising=False)

    def _boom(token):
        raise clerk.ClerkAuthError("bad signature")

    monkeypatch.setattr(clerk, "verify_clerk_jwt", _boom)

    # A present-but-invalid Bearer token must NOT silently fall back to x-api-key.
    resp = client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer bad", **_HEADERS},
    )

    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------- #
# Batch enqueue robustness: a per-variant failure while persisting the Celery
# task id, or a DB error during a refund, must not abort the enqueue loop and
# strand the remaining debited variants (money-loss defects).
# --------------------------------------------------------------------------- #
def test_create_job_variants_set_task_id_failure_does_not_strand_batch(env, monkeypatch):
    """A transient DB error in set_celery_task_id for one variant must not
    terminate the loop, leaving later variants debited-but-never-enqueued."""
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=3)

    original = JobRepository.set_celery_task_id
    calls = {"n": 0}

    def _flaky(self, job_id, celery_task_id):
        calls["n"] += 1
        if calls["n"] == 1:  # only the first variant's persist fails
            raise RuntimeError("db connection reset")
        return original(self, job_id, celery_task_id)

    monkeypatch.setattr(jobs_mod.JobRepository, "set_celery_task_id", _flaky)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "variants": 3},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    # The loop enqueued every variant instead of aborting on the first failure.
    assert len(pipeline.start_calls) == 3
    # The one variant whose task-id persist failed is refunded (3 debited, 1 back).
    assert _balance(Factory, uid) == 1
    with Factory() as s:
        states = sorted(j.state for j in JobRepository(s).list_for_user(uid))
    assert states.count(const.TASK_STATE_FAILED) == 1     # the flaky variant
    assert states.count(const.TASK_STATE_PROCESSING) == 2  # the rest still run


def test_create_job_variants_refund_db_error_does_not_crash_batch(env, monkeypatch):
    """A DB error inside the refund must not poison a shared session and crash
    the loop: mark_failed is committed in its own transaction and the refund
    failure is isolated + swallowed."""
    from app.models.db.models import CreditLedger

    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=3)
    pipeline.raise_on_start = True  # every enqueue fails -> refund path runs

    def _poison_grant(self, user_id, amount, reason):
        # A failed flush (NOT NULL violation) deactivates the surrounding
        # transaction under SQLAlchemy 2.0 exactly like a real DB error would.
        # If mark_failed shared this session, its context manager's commit would
        # then raise PendingRollbackError and roll the FAILED transition back.
        self._session.add(
            CreditLedger(user_id=user_id, delta=None, reason=reason, balance_after=0)
        )
        self._session.flush()

    monkeypatch.setattr(jobs_mod.CreditRepository, "grant", _poison_grant)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": _PARAMS, "variants": 3},
        headers=_HEADERS,
    )

    # No 500: the poisoned refund session is isolated from mark_failed and the
    # loop, so all three variants are reconciled and the batch envelope returns.
    assert resp.status_code == 200, resp.text
    assert len(pipeline.start_calls) == 3
    with Factory() as s:
        jobs = JobRepository(s).list_for_user(uid)
    assert len(jobs) == 3
    # mark_failed committed despite the refund failure -> recoverable via retry.
    assert all(j.state == const.TASK_STATE_FAILED for j in jobs)


# --------------------------------------------------------------------------- #
# Phase 6 — creator-studio create extras: caption_style / music_id / webhook_*
# --------------------------------------------------------------------------- #
def test_create_job_threads_caption_music_and_webhook_into_params(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)

    resp = client.post(
        "/api/v1/jobs",
        json={
            "params": _PARAMS,
            "caption_style": "karaoke_green",
            "music_id": "upbeat",
            "webhook_url": "https://example.com/hook",
            "webhook_secret": "s3cr3t",
        },
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    with Factory() as s:
        job = JobRepository(s).list_for_user(uid)[0]
    # caption_style is a ReelForgeParams field -> flows into the strict DTO.
    assert job.params.get("caption_style") == "karaoke_green"
    # music_id / webhook_* are persisted alongside the DTO fields for the
    # compose + notification stages (not ReelForgeParams fields).
    assert job.params.get("music_id") == "upbeat"
    assert job.params.get("webhook_url") == "https://example.com/hook"
    assert job.params.get("webhook_secret") == "s3cr3t"
    # The enqueued render params carry the caption tweak.
    _, called_params = pipeline.start_calls[0]
    assert called_params.caption_style == "karaoke_green"


# --------------------------------------------------------------------------- #
# Phase 6 — re-run with tweaks
# --------------------------------------------------------------------------- #
def _make_source_job(Factory, user_id, params=None) -> str:
    with Factory() as s:
        job = JobRepository(s).create(
            user_id=user_id,
            kind="avatar_reel",
            params=params or dict(_PARAMS),
        )
        jid = job.id
        s.commit()
    return jid


def test_rerun_clones_params_applies_overrides_and_debits_one(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_source_job(
        Factory,
        uid,
        params={"video_subject": "cats", "layout": "pip", "caption_style": "karaoke_yellow"},
    )

    resp = client.post(
        f"/api/v1/jobs/{jid}/rerun",
        json={
            "overrides": {
                "avatar_id": "av-1",
                "voice_id": "abc123",
                "layout": "split",
                "caption_style": "karaoke_green",
                "music_id": "upbeat",
                "language": "en",
            }
        },
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    new_job_id = resp.json()["data"]["job_id"]
    assert new_job_id != jid                          # a brand-new job
    assert _balance(Factory, uid) == 4                # exactly 1 credit debited
    assert len(pipeline.start_calls) == 1

    # The enqueued render params reflect the overrides (cloned + tweaked).
    enq_job_id, enq_params = pipeline.start_calls[0]
    assert enq_job_id == new_job_id
    assert enq_params.video_subject == "cats"         # inherited from source
    assert enq_params.layout == "split"
    assert enq_params.caption_style == "karaoke_green"
    assert enq_params.avatar_id == "av-1"
    assert enq_params.voice_name == "elevenlabs:abc123"
    assert enq_params.language == "en"

    # The persisted Job.params keeps the non-DTO extras (music_id) too, and the
    # SOURCE job is untouched (immutable clone).
    with Factory() as s:
        new_job = JobRepository(s).get(new_job_id)
        source = JobRepository(s).get(jid)
    assert new_job.params.get("music_id") == "upbeat"
    assert new_job.params.get("layout") == "split"
    assert source.params.get("layout") == "pip"       # source not mutated


def test_rerun_without_overrides_reruns_source_params(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_source_job(
        Factory, uid, params={"video_subject": "dogs", "layout": "hook_intro"}
    )

    resp = client.post(f"/api/v1/jobs/{jid}/rerun", json={}, headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    _, enq_params = pipeline.start_calls[0]
    assert enq_params.video_subject == "dogs"
    assert enq_params.layout == "hook_intro"          # cloned unchanged
    assert _balance(Factory, uid) == 4


def test_rerun_unknown_job_returns_404(env):
    client, Factory, pipeline = env
    _make_user(Factory, credits=5)

    resp = client.post(
        "/api/v1/jobs/does-not-exist/rerun", json={}, headers=_HEADERS
    )

    assert resp.status_code == 404, resp.text
    assert pipeline.start_calls == []


def test_rerun_foreign_job_returns_404(env):
    client, Factory, pipeline = env
    # Owner has a DISTINCT api key so the x-api-key caller cannot resolve to them.
    owner_key_hash = hashlib.sha256(b"ownerkey").hexdigest()
    with Factory() as s:
        owner = User(email="owner-rerun@x.com", api_key_hash=owner_key_hash)
        s.add(owner)
        s.flush()
        job = JobRepository(s).create(
            user_id=owner.id, kind="avatar_reel", params=_PARAMS
        )
        jid = job.id
        s.commit()
    _make_user(Factory, email="caller-rerun@x.com", credits=5)  # the caller

    resp = client.post(f"/api/v1/jobs/{jid}/rerun", json={}, headers=_HEADERS)

    assert resp.status_code == 404, resp.text          # no cross-user leak
    assert pipeline.start_calls == []


def test_rerun_insufficient_credits_402_no_enqueue(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=0)
    jid = _make_source_job(Factory, uid)

    resp = client.post(f"/api/v1/jobs/{jid}/rerun", json={}, headers=_HEADERS)

    assert resp.status_code == 402, resp.text
    assert pipeline.start_calls == []
    # Rolled back: no new job created for the caller (only the source remains).
    with Factory() as s:
        assert len(JobRepository(s).list_for_user(uid)) == 1


def test_rerun_enqueue_failure_refunds(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_source_job(Factory, uid)
    pipeline.raise_on_start = True

    resp = client.post(f"/api/v1/jobs/{jid}/rerun", json={}, headers=_HEADERS)

    assert resp.status_code == 502, resp.text
    assert _balance(Factory, uid) == 5                 # debit reconciled by refund
    with Factory() as s:
        # The new (failed) job exists and is FAILED; the source is untouched.
        jobs = JobRepository(s).list_for_user(uid)
    assert any(j.state == const.TASK_STATE_FAILED for j in jobs)


# --------------------------------------------------------------------------- #
# Multi-language dubbing — POST /jobs/{job_id}/dub fans a finished reel out into
# N language-dubbed jobs under ONE shared batch_id (existing batch-review UI).
# --------------------------------------------------------------------------- #
_DUB_SOURCE_PARAMS = {
    "video_subject": "cats",
    "screen_recording_key": "recordings/src.mp4",
    "avatar_id": "av-src",
    "voice_name": "elevenlabs:voice-src",
    "layout": "pip",
    "caption_style": "karaoke_yellow",
}


def _make_dub_source(
    Factory, user_id, script="Hey - watch this, then follow me!", params=None
) -> str:
    """Create a source job WITH a finalized script (dub translates that script)."""
    with Factory() as s:
        repo = JobRepository(s)
        job = repo.create(
            user_id=user_id,
            kind="avatar_reel",
            params=params or dict(_DUB_SOURCE_PARAMS),
        )
        jid = job.id
        repo.set_script(jid, script)
        s.commit()
    return jid


def test_dub_three_languages_debits_three_shares_batch_and_sets_params(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_dub_source(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/dub",
        json={"languages": ["es", "fr", "de"]},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    batch_id = data["batch_id"]
    assert batch_id                                     # one shared batch id minted
    job_ids = data["job_ids"]
    assert len(job_ids) == 3
    assert len(set(job_ids)) == 3                       # distinct jobs, not aliases
    assert data["languages"] == ["es", "fr", "de"]     # echoed in request order
    assert len(pipeline.start_calls) == 3              # each dub enqueued once
    assert _balance(Factory, uid) == 2                 # 5 - 3 debited before enqueue

    # Every dubbed Job shares the one batch_id, sets language + the source script
    # to translate, and reuses the source's recording / avatar / voice / look.
    with Factory() as s:
        repo = JobRepository(s)
        rows = {j: repo.get(j) for j in job_ids}
    assert {r.batch_id for r in rows.values()} == {batch_id}
    assert sorted(r.params.get("language") for r in rows.values()) == ["de", "es", "fr"]
    for r in rows.values():
        assert r.params.get("translate_source_script") == "Hey - watch this, then follow me!"
        assert r.params.get("screen_recording_key") == "recordings/src.mp4"
        assert r.params.get("avatar_id") == "av-src"
        assert r.params.get("voice_name") == "elevenlabs:voice-src"
        assert r.params.get("caption_style") == "karaoke_yellow"

    # The enqueued render params carry the per-language target.
    enq_langs = sorted(p.language for _, p in pipeline.start_calls)
    assert enq_langs == ["de", "es", "fr"]

    # The dubbed jobs are reviewable together via the existing batch endpoint.
    batch = client.get(f"/api/v1/batches/{batch_id}", headers=_HEADERS)
    assert batch.status_code == 200, batch.text
    assert len(batch.json()["data"]["jobs"]) == 3


def test_dub_foreign_source_returns_404(env):
    client, Factory, pipeline = env
    # Owner has a DISTINCT api key so the x-api-key caller cannot resolve to them.
    owner_key_hash = hashlib.sha256(b"ownerkey").hexdigest()
    with Factory() as s:
        owner = User(email="owner-dub@x.com", api_key_hash=owner_key_hash)
        s.add(owner)
        s.flush()
        repo = JobRepository(s)
        job = repo.create(
            user_id=owner.id, kind="avatar_reel", params=dict(_DUB_SOURCE_PARAMS)
        )
        jid = job.id
        repo.set_script(jid, "owner's script")
        s.commit()
    _make_user(Factory, email="caller-dub@x.com", credits=5)  # the x-api-key caller

    resp = client.post(
        f"/api/v1/jobs/{jid}/dub", json={"languages": ["es"]}, headers=_HEADERS
    )

    assert resp.status_code == 404, resp.text          # no cross-user leak
    assert pipeline.start_calls == []


def test_dub_source_without_script_returns_409(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    # A source job that never reached the script stage (no script persisted).
    jid = _make_source_job(Factory, uid, params=dict(_DUB_SOURCE_PARAMS))

    resp = client.post(
        f"/api/v1/jobs/{jid}/dub", json={"languages": ["es"]}, headers=_HEADERS
    )

    assert resp.status_code == 409, resp.text          # script not available yet
    assert pipeline.start_calls == []
    assert _balance(Factory, uid) == 5                 # no credit spent


def test_dub_unknown_language_returns_400_no_enqueue(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_dub_source(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/dub",
        json={"languages": ["es", "ja"]},          # "ja" is unsupported
        headers=_HEADERS,
    )

    assert resp.status_code == 400, resp.text
    assert pipeline.start_calls == []                  # never enqueued
    assert _balance(Factory, uid) == 5                 # no credit spent
    # No dub jobs persisted — only the source remains.
    with Factory() as s:
        assert len(JobRepository(s).list_for_user(uid)) == 1


def test_dub_empty_languages_returns_400(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_dub_source(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/dub", json={"languages": []}, headers=_HEADERS
    )

    assert resp.status_code == 400, resp.text
    assert pipeline.start_calls == []
    assert _balance(Factory, uid) == 5


def test_dub_insufficient_credits_402_no_enqueue(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=2)               # enough for 2, not for 3
    jid = _make_dub_source(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/dub",
        json={"languages": ["es", "fr", "de"]},
        headers=_HEADERS,
    )

    assert resp.status_code == 402, resp.text
    assert pipeline.start_calls == []                  # nothing enqueued
    assert _balance(Factory, uid) == 2                 # no partial debit
    # Whole batch rolled back: only the source job remains for the caller.
    with Factory() as s:
        assert len(JobRepository(s).list_for_user(uid)) == 1


def test_dub_enqueue_failure_refunds(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_dub_source(Factory, uid)
    pipeline.raise_on_start = True                     # every enqueue fails

    resp = client.post(
        f"/api/v1/jobs/{jid}/dub",
        json={"languages": ["es", "fr"]},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text          # batch envelope still returns
    assert len(pipeline.start_calls) == 2
    # Both dubbed jobs' debits are reconciled by a refund -> balance restored.
    assert _balance(Factory, uid) == 5
    with Factory() as s:
        dubbed = [j for j in JobRepository(s).list_for_user(uid) if j.script == ""]
    assert len(dubbed) == 2
    assert all(j.state == const.TASK_STATE_FAILED for j in dubbed)


def test_dub_catalog_lists_supported_languages(catalog_client):
    resp = catalog_client.get("/api/v1/catalog/dub-languages")

    assert resp.status_code == 200, resp.text
    langs = resp.json()["data"]
    assert isinstance(langs, list)
    codes = {entry["code"] for entry in langs}
    assert {"en", "tr", "es", "fr", "de", "pt", "it"}.issubset(codes)
    for entry in langs:
        assert entry.get("code")
        assert entry.get("name")


# --------------------------------------------------------------------------- #
# layout allowlist — an unknown layout must be rejected at the controller
# boundary (400) BEFORE any credit is debited or pipeline enqueued, since the
# compose stage would otherwise fail unrefundably on an unknown layout.
# --------------------------------------------------------------------------- #
def test_create_job_rejects_unknown_layout_before_debit(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": {"video_subject": "cats", "layout": "fullscreen"}},
        headers=_HEADERS,
    )

    assert resp.status_code == 400, resp.text
    assert "layout" in resp.json()["message"].lower()
    assert pipeline.start_calls == []              # never enqueued
    assert _balance(Factory, uid) == 5             # no credit spent
    with Factory() as s:                           # no orphan job persisted
        assert JobRepository(s).list_for_user(uid) == []


@pytest.mark.parametrize("layout", ["pip", "hook_intro", "split"])
def test_create_job_accepts_known_layouts(env, layout):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)

    resp = client.post(
        "/api/v1/jobs",
        json={"params": {"video_subject": "cats", "layout": layout}},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    assert pipeline.start_calls[0][1].layout == layout
    assert _balance(Factory, uid) == 4


def test_rerun_rejects_unknown_layout_override_before_debit(env):
    client, Factory, pipeline = env
    uid = _make_user(Factory, credits=5)
    jid = _make_source_job(
        Factory, uid, params={"video_subject": "cats", "layout": "pip"}
    )

    resp = client.post(
        f"/api/v1/jobs/{jid}/rerun",
        json={"overrides": {"layout": "fullscreen"}},
        headers=_HEADERS,
    )

    assert resp.status_code == 400, resp.text
    assert "layout" in resp.json()["message"].lower()
    assert pipeline.start_calls == []              # never enqueued
    assert _balance(Factory, uid) == 5             # no credit spent
    with Factory() as s:                           # only the source job remains
        assert len(JobRepository(s).list_for_user(uid)) == 1


# --------------------------------------------------------------------------- #
# Phase 6 — read-only catalog endpoints (caption styles / music / layouts)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def catalog_client():
    """A minimal app mounting ONLY the catalog router (no DB / auth needed)."""
    app = FastAPI()
    app.include_router(catalog_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app)


def test_catalog_caption_styles_returns_list(catalog_client):
    resp = catalog_client.get("/api/v1/catalog/caption-styles")

    assert resp.status_code == 200, resp.text
    styles = resp.json()["data"]
    assert isinstance(styles, list)
    assert len(styles) >= 1
    for style in styles:
        assert style.get("id")
        assert style.get("name")


def test_catalog_music_returns_list(catalog_client):
    resp = catalog_client.get("/api/v1/catalog/music")

    assert resp.status_code == 200, resp.text
    tracks = resp.json()["data"]
    assert isinstance(tracks, list)                    # may be empty in CI
    for track in tracks:
        assert track.get("id")
        assert "name" in track


def test_catalog_music_degrades_to_empty_on_error(catalog_client, monkeypatch):
    import app.services.music as music_mod

    def _boom():
        raise RuntimeError("songs dir exploded")

    monkeypatch.setattr(music_mod, "list_music", _boom)

    resp = catalog_client.get("/api/v1/catalog/music")

    assert resp.status_code == 200, resp.text          # never a 500
    assert resp.json()["data"] == []


def test_catalog_layouts_returns_expected_three(catalog_client):
    resp = catalog_client.get("/api/v1/catalog/layouts")

    assert resp.status_code == 200, resp.text
    layouts = resp.json()["data"]
    assert isinstance(layouts, list)
    ids = {layout["id"] for layout in layouts}
    assert ids == {"pip", "hook_intro", "split"}
    for layout in layouts:
        assert layout.get("name")
        assert layout.get("description")


# --------------------------------------------------------------------------- #
# Phase 7 — growth catalogs (job templates / hook browser)
# --------------------------------------------------------------------------- #
def test_catalog_templates_returns_list(catalog_client):
    resp = catalog_client.get("/api/v1/catalog/templates")

    assert resp.status_code == 200, resp.text
    templates = resp.json()["data"]
    assert isinstance(templates, list)
    assert len(templates) >= 1
    for tpl in templates:
        assert tpl.get("id")
        assert tpl.get("name")
        # Each template carries a spreadable job config.
        assert isinstance(tpl.get("config"), dict)


def test_catalog_templates_degrades_to_empty_on_error(catalog_client, monkeypatch):
    import app.services.templates as templates_mod

    monkeypatch.setattr(
        templates_mod,
        "list_templates",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    resp = catalog_client.get("/api/v1/catalog/templates")

    assert resp.status_code == 200, resp.text          # never a 500
    assert resp.json()["data"] == []


def test_catalog_hooks_returns_language_map(catalog_client):
    resp = catalog_client.get("/api/v1/catalog/hooks")

    assert resp.status_code == 200, resp.text
    hooks = resp.json()["data"]
    assert isinstance(hooks, dict)
    # Stable shape: every native language key is present with a list value.
    assert {"tr", "en"}.issubset(hooks.keys())
    for lang, lines in hooks.items():
        assert isinstance(lines, list)


# --------------------------------------------------------------------------- #
# Phase 7 — /me growth surfaces (insights / referral / presets)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def me_env(monkeypatch):
    """Wire the growth ``me`` controller to an in-memory SQLite DB."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)          # includes the user_presets table
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

    # me.py holds its own imported ``get_session`` reference — patch it there.
    monkeypatch.setattr(me_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(me_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


def _make_user_with_key(Factory, email, key_hash, credits=0) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        if credits:
            CreditRepository(s).grant(uid, credits, reason="signup")
        s.commit()
    return uid


def test_me_insights_scoped_to_caller(me_env):
    client, Factory = me_env
    uid = _make_user(Factory, email="caller@x.com", credits=5)
    other = _make_user(Factory, email="other@x.com", credits=9)
    with Factory() as s:
        j1 = JobRepository(s).create(user_id=uid, kind="avatar_reel", params=_PARAMS)
        JobRepository(s).create(user_id=uid, kind="avatar_reel", params=_PARAMS)
        JobRepository(s).mark_complete(j1.id, "results/a.mp4")
        # Another user's job must never leak into the caller's insights.
        JobRepository(s).create(user_id=other, kind="avatar_reel", params=_PARAMS)
        s.commit()

    resp = client.get("/api/v1/me/insights", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["user_id"] == uid                  # scoped to the caller
    assert data["jobs_total"] == 2                 # excludes the other user's job
    assert data["videos_generated"] == 1
    assert data["credits_balance"] == 5            # caller's balance, not other's


def test_me_insights_requires_auth(me_env):
    client, Factory = me_env
    _make_user(Factory)

    resp = client.get("/api/v1/me/insights")       # no x-api-key

    assert resp.status_code == 401, resp.text


def test_me_referral_returns_code_and_stats(me_env):
    client, Factory = me_env
    uid = _make_user(Factory, email="ref@x.com")

    resp = client.get("/api/v1/me/referral", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["code"] == referrals.generate_referral_code(uid)
    assert data["referred_count"] == 0
    assert data["credits_earned"] == 0


def test_me_referral_redeem_grants_both_parties(me_env):
    client, Factory = me_env
    owner_hash = hashlib.sha256(b"referrer-key").hexdigest()
    referrer_id = _make_user_with_key(Factory, "referrer@x.com", owner_hash)
    code = referrals.generate_referral_code(referrer_id)
    # The caller (x-api-key) is the referee.
    referee_id = _make_user(Factory, email="referee@x.com", credits=0)

    resp = client.post(
        "/api/v1/me/referral/redeem", json={"code": code}, headers=_HEADERS
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["ok"] is True
    assert data["referrer_id"] == referrer_id
    assert data["referee_id"] == referee_id
    assert _balance(Factory, referee_id) == 5      # referee granted
    assert _balance(Factory, referrer_id) == 10    # referrer granted


def test_me_referral_redeem_double_returns_409(me_env):
    client, Factory = me_env
    owner_hash = hashlib.sha256(b"referrer-key2").hexdigest()
    referrer_id = _make_user_with_key(Factory, "referrer2@x.com", owner_hash)
    code = referrals.generate_referral_code(referrer_id)
    _make_user(Factory, email="referee2@x.com")

    first = client.post(
        "/api/v1/me/referral/redeem", json={"code": code}, headers=_HEADERS
    )
    second = client.post(
        "/api/v1/me/referral/redeem", json={"code": code}, headers=_HEADERS
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text  # double-redeem rejected


def test_me_referral_redeem_self_returns_400(me_env):
    client, Factory = me_env
    uid = _make_user(Factory, email="selfref@x.com")
    own_code = referrals.generate_referral_code(uid)

    resp = client.post(
        "/api/v1/me/referral/redeem", json={"code": own_code}, headers=_HEADERS
    )

    assert resp.status_code == 400, resp.text       # self-referral rejected
    assert _balance(Factory, uid) == 0              # no credits granted


def test_me_referral_redeem_unknown_code_returns_400(me_env):
    client, Factory = me_env
    _make_user(Factory, email="ref-unknown@x.com")

    resp = client.post(
        "/api/v1/me/referral/redeem", json={"code": "NOSUCHCODE"}, headers=_HEADERS
    )

    assert resp.status_code == 400, resp.text


def test_me_presets_create_and_list(me_env):
    client, Factory = me_env
    _make_user(Factory, email="presets@x.com")

    created = client.post(
        "/api/v1/me/presets",
        json={"name": "My POV", "config": {"layout": "hook_intro"}},
        headers=_HEADERS,
    )
    assert created.status_code == 200, created.text
    body = created.json()["data"]
    assert body["id"]
    assert body["name"] == "My POV"
    assert body["config"] == {"layout": "hook_intro"}

    listing = client.get("/api/v1/me/presets", headers=_HEADERS)
    assert listing.status_code == 200, listing.text
    presets = listing.json()["data"]
    assert len(presets) == 1
    assert presets[0]["id"] == body["id"]


def test_me_presets_list_scoped_to_caller(me_env):
    client, Factory = me_env
    _make_user(Factory, email="caller-p@x.com")
    owner_hash = hashlib.sha256(b"owner-preset-key").hexdigest()
    owner_id = _make_user_with_key(Factory, "owner-p@x.com", owner_hash)
    with Factory() as s:
        s.add(UserPreset(user_id=owner_id, name="secret", config={}))
        s.commit()

    resp = client.get("/api/v1/me/presets", headers=_HEADERS)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []                # owner's preset not visible


def test_me_presets_delete_owner_succeeds(me_env):
    client, Factory = me_env
    _make_user(Factory, email="del-owner@x.com")
    created = client.post(
        "/api/v1/me/presets", json={"name": "tmp", "config": {}}, headers=_HEADERS
    )
    pid = created.json()["data"]["id"]

    deleted = client.delete(f"/api/v1/me/presets/{pid}", headers=_HEADERS)

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["deleted"] is True
    # Gone from the caller's list.
    assert client.get("/api/v1/me/presets", headers=_HEADERS).json()["data"] == []


def test_me_presets_delete_foreign_returns_404(me_env):
    client, Factory = me_env
    _make_user(Factory, email="caller-del@x.com")     # the x-api-key caller
    owner_hash = hashlib.sha256(b"owner-del-key").hexdigest()
    owner_id = _make_user_with_key(Factory, "owner-del@x.com", owner_hash)
    with Factory() as s:
        p = UserPreset(user_id=owner_id, name="foreign", config={})
        s.add(p)
        s.flush()
        pid = p.id
        s.commit()

    resp = client.delete(f"/api/v1/me/presets/{pid}", headers=_HEADERS)

    assert resp.status_code == 404, resp.text          # ownership enforced, no leak
    # The foreign preset still exists (was NOT deleted).
    with Factory() as s:
        assert s.get(UserPreset, pid) is not None


def test_me_presets_requires_auth(me_env):
    client, Factory = me_env
    _make_user(Factory)

    resp = client.get("/api/v1/me/presets")            # no x-api-key

    assert resp.status_code == 401, resp.text


def test_clerk_signup_starts_with_no_credits_until_card_check(env, monkeypatch):
    """A web (Clerk) signup gets its free reels only after the $1 card check
    (see test_card_check.py), never at account creation."""
    client, Factory, pipeline = env
    from app.config import config
    from app.core import clerk
    from app.models.db.repositories import CreditRepository
    from app.services.billing.plans import SIGNUP_GRANT

    monkeypatch.setattr(config, "clerk", {"issuer": "https://test.clerk"}, raising=False)
    monkeypatch.setattr(
        clerk, "verify_clerk_jwt", lambda token: {"sub": "user_grant", "email": "grant@example.com"}
    )

    h = {"Authorization": "Bearer fake.jwt.token"}
    assert client.get("/api/v1/me", headers=h).status_code == 200
    assert client.get("/api/v1/me", headers=h).status_code == 200

    with Factory() as s:
        user = s.query(User).filter(User.email == "grant@example.com").one()
        assert CreditRepository(s).balance(user.id) == 0
        assert SIGNUP_GRANT > 0
