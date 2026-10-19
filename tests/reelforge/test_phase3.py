"""Phase 3 tests: LatentSync avatar provider, on-demand publish, studio API.

Covers the three Phase-3 surfaces with no external I/O (RunPod, R2, upload-post,
Postgres, Celery all monkeypatched / faked):

* ``app.services.avatar.latentsync_runpod`` — registry membership + a full
  ``generate_avatar`` happy path (RunPod ``run`` -> ``status COMPLETED`` ->
  download -> re-host to R2) and the ±0.25s duration-drift warning path.
* ``app.services.publish.publish_job_output`` — reuses ``upload_post`` and
  appends ``JobEvent`` telemetry rows for the ``publish`` stage.
* ``app.controllers.v1.studio`` — ``POST /jobs/{id}/publish`` and ``POST /avatars``
  happy + authz paths via a FastAPI ``TestClient`` over in-memory SQLite.
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

import app.controllers.v1.studio as studio_mod
import app.services.avatar as avatar_pkg
import app.services.avatar.base as avatar_base
import app.services.avatar.latentsync_runpod as latentsync
import app.services.publish as publish_mod
from app.models import const
from app.models.db.base import Base
from app.models.db.models import Asset, AvatarPreset, JobEvent, User
from app.models.db.repositories import JobRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "phase3-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


@pytest.fixture(autouse=True)
def _grant_pro_entitlement(monkeypatch):
    """Grant RevenueCat Pro so the publish-endpoint tests exercise publish logic
    rather than the orthogonal paid-entitlement gate (covered on its own in
    test_revenuecat_export_gate). ``require_pro_action`` resolves
    ``revenuecat_client.require_pro_entitlement`` at call time, so patching it
    here neutralizes the fail-closed gate for every call site without a live
    RevenueCat secret.
    """
    from app.services.billing import revenuecat_client

    monkeypatch.setattr(
        revenuecat_client, "require_pro_entitlement", lambda *a, **k: None
    )


# =========================================================================== #
# Fake HTTP + storage doubles for the LatentSync provider
# =========================================================================== #
class _FakeResp:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(self, *, json_body: dict | None = None, chunks=None) -> None:
        self._json = json_body or {}
        self._chunks = chunks or []

    def raise_for_status(self) -> None:  # never raises in the happy path
        return None

    def json(self) -> dict:
        return self._json

    def iter_content(self, chunk_size: int = 1 << 16):
        yield from self._chunks


class _FakeRequests:
    """Routes ``post``/``get`` by URL to emulate a RunPod worker + CDN download.

    ``status_output`` is the worker ``output`` dict returned on ``COMPLETED``.
    """

    def __init__(self, status_output: dict) -> None:
        self.status_output = status_output
        self.calls: list[tuple[str, str]] = []

    def post(self, url, **kwargs):  # noqa: D401 - test double
        self.calls.append(("POST", url))
        assert url.endswith("/run")
        return _FakeResp(json_body={"id": "job-123", "status": "IN_QUEUE"})

    def get(self, url, **kwargs):  # noqa: D401 - test double
        self.calls.append(("GET", url))
        if "/status/" in url:
            return _FakeResp(
                json_body={"status": "COMPLETED", "output": self.status_output}
            )
        # Otherwise it is the video download of the worker's output URL.
        return _FakeResp(chunks=[b"fake-mp4-bytes"])


class _FakeR2:
    """Captures ``upload_file`` calls and returns a stable public URL."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str | None]] = []

    def upload_file(self, local_path: str, key: str, content_type=None) -> str:
        self.uploads.append((local_path, key, content_type))
        return f"https://cdn.example.com/{key}"


def _enabled_provider() -> latentsync.LatentSyncProvider:
    """A LatentSync provider wired with dummy credentials (so ``is_enabled``)."""
    provider = latentsync.LatentSyncProvider()
    provider._api_key = "k"
    provider._endpoint_id = "ep"
    provider._client.api_key = "k"
    provider._client.endpoint_id = "ep"
    return provider


# =========================================================================== #
# 1. Registry
# =========================================================================== #
def test_latentsync_registered_in_avatar_providers():
    # Importing the package self-registers both providers at import time.
    assert "latentsync" in avatar_base.AVATAR_PROVIDERS
    assert "latentsync" in avatar_pkg.AVATAR_PROVIDERS  # same dict, re-exported


def test_get_avatar_provider_resolves_latentsync():
    provider = avatar_base.get_avatar_provider("latentsync")
    assert provider is avatar_base.AVATAR_PROVIDERS["latentsync"]
    assert provider.name == "latentsync"
    # Satisfies the runtime-checkable Protocol.
    assert isinstance(provider, avatar_base.TalkingHeadProvider)


# =========================================================================== #
# 2. generate_avatar happy path
# =========================================================================== #
def test_generate_avatar_happy_path_rehosts_to_r2(monkeypatch):
    fake_requests = _FakeRequests(
        status_output={"id": "job-123", "video_url": "https://cdn/x.mp4", "duration": 5.0}
    )
    fake_r2 = _FakeR2()
    monkeypatch.setattr(latentsync, "requests", fake_requests)
    monkeypatch.setattr(
        "app.services.storage.r2.r2_client", fake_r2, raising=False
    )

    provider = _enabled_provider()
    result = provider.generate_avatar(
        audio_url="https://r2/audio.mp3",
        avatar_id="https://r2/face.png",
        expected_duration_s=5.0,
    )

    assert isinstance(result, dict)
    assert result["duration"] == 5.0
    assert result["provider_video_id"] == "job-123"
    assert result["avatar_video"].endswith(".mp4")
    # Re-hosted to R2: best-effort avatar_url/key merged into the result.
    assert result["avatar_url"] == "https://cdn.example.com/avatars/job-123.mp4"
    assert result["avatar_key"] == "avatars/job-123.mp4"
    assert len(fake_r2.uploads) == 1
    # Exercised the full submit -> poll -> download sequence.
    methods = [m for m, _ in fake_requests.calls]
    assert methods == ["POST", "GET", "GET"]

    # Downloaded temp file exists and holds the streamed bytes.
    import os

    assert os.path.exists(result["avatar_video"])
    with open(result["avatar_video"], "rb") as fh:
        assert fh.read() == b"fake-mp4-bytes"
    os.remove(result["avatar_video"])


def test_generate_avatar_disabled_returns_none(monkeypatch):
    provider = latentsync.LatentSyncProvider()  # no creds -> not enabled
    assert provider.is_enabled() is False
    assert (
        provider.generate_avatar("https://r2/a.mp3", "https://r2/f.png") is None
    )


# =========================================================================== #
# 3. Duration-drift warning path (§8, ±0.25s)
# =========================================================================== #
def test_generate_avatar_duration_drift_warns(monkeypatch):
    # Worker reports 5.0s but the audio authority expects 10.0s -> drift warning.
    fake_requests = _FakeRequests(
        status_output={"id": "job-9", "video_url": "https://cdn/x.mp4", "duration": 5.0}
    )
    monkeypatch.setattr(latentsync, "requests", fake_requests)
    monkeypatch.setattr(
        "app.services.storage.r2.r2_client", _FakeR2(), raising=False
    )

    captured: list[str] = []
    sink_id = latentsync.logger.add(
        lambda m: captured.append(m.record["message"]), level="WARNING"
    )
    try:
        provider = _enabled_provider()
        result = provider.generate_avatar(
            audio_url="https://r2/audio.mp3",
            avatar_id="https://r2/face.png",
            expected_duration_s=10.0,
        )
    finally:
        latentsync.logger.remove(sink_id)

    assert result is not None
    assert result["duration"] == 5.0  # provider does NOT rewrite the render
    assert any("duration drift beyond tolerance" in msg for msg in captured)

    import os

    if result and result.get("avatar_video"):
        try:
            os.remove(result["avatar_video"])
        except OSError:
            pass


def test_generate_avatar_missing_duration_warns_unverifiable(monkeypatch):
    # Worker omits every duration key -> the §8 gate cannot run against a real
    # value, so it must warn (not silently pass by comparing expected to itself).
    fake_requests = _FakeRequests(
        status_output={"id": "job-7", "video_url": "https://cdn/x.mp4"}
    )
    monkeypatch.setattr(latentsync, "requests", fake_requests)
    monkeypatch.setattr(
        "app.services.storage.r2.r2_client", _FakeR2(), raising=False
    )

    captured: list[str] = []
    sink_id = latentsync.logger.add(
        lambda m: captured.append(m.record["message"]), level="WARNING"
    )
    try:
        provider = _enabled_provider()
        result = provider.generate_avatar(
            audio_url="https://r2/audio.mp3",
            avatar_id="https://r2/face.png",
            expected_duration_s=30.0,
        )
    finally:
        latentsync.logger.remove(sink_id)

    assert result is not None
    # Best-effort estimate falls back to the expected authority value...
    assert result["duration"] == 30.0
    # ...but the §8 check is NOT silently bypassed: it warns it is unverifiable.
    assert any("could not be verified against" in msg for msg in captured)
    assert not any("duration drift beyond tolerance" in msg for msg in captured)

    import os

    if result and result.get("avatar_video"):
        try:
            os.remove(result["avatar_video"])
        except OSError:
            pass


# =========================================================================== #
# 4. publish_job_output reuses upload_post + records events
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


def _make_user(Factory, email="pub@example.com") -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=_KEY_HASH, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_complete_job(Factory, user_id, result_key="final/out.mp4") -> str:
    with Factory() as s:
        job = JobRepository(s).create(
            user_id=user_id,
            kind="avatar_reel",
            params={"video_subject": "cats", "video_script": "meow"},
        )
        jid = job.id
        JobRepository(s).mark_complete(jid, result_key)
        s.commit()
    return jid


def test_publish_job_output_reuses_upload_post_and_records_events(
    monkeypatch, db_factory
):
    Factory = db_factory
    uid = _make_user(Factory)
    jid = _make_complete_job(Factory, uid)

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

    monkeypatch.setattr(publish_mod, "get_session", _fake_get_session)
    # Avoid a real R2 presign + download; hand back a local temp path.
    monkeypatch.setattr(
        publish_mod, "_download_final", lambda key, job_id: "/tmp/does-not-matter.mp4"
    )
    # Deterministic social metadata (no LLM call).
    monkeypatch.setattr(
        "app.services.llm.generate_social_metadata",
        lambda **kw: {"title": "Cats!", "caption": "meow", "hashtags": ["cats"]},
    )

    posted: dict = {}

    def _fake_cross_post(video_path, title, platforms=None, youtube_extra=None):
        posted["video_path"] = video_path
        posted["title"] = title
        posted["platforms"] = platforms
        posted["youtube_extra"] = youtube_extra
        return {"success": True, "request_id": "req-42"}

    monkeypatch.setattr(
        "app.services.upload_post.cross_post_video", _fake_cross_post
    )

    events: list[tuple] = []
    monkeypatch.setattr(
        "app.telemetry.events.record_event",
        lambda job_id, stage, status, message="", payload=None: events.append(
            (job_id, stage, status)
        ),
    )
    # os.remove would fail on the fake path; make cleanup a no-op.
    monkeypatch.setattr(publish_mod.os, "remove", lambda p: None)

    result = publish_mod.publish_job_output(
        jid, ["tiktok", "youtube"], youtube_privacy_status="unlisted"
    )

    # upload_post was reused with the presigned/downloaded path + generated title.
    assert posted["title"] == "Cats!"
    assert posted["platforms"] == ["tiktok", "youtube"]
    # YouTube extra is assembled because a youtube target is present.
    assert posted["youtube_extra"]["privacyStatus"] == "unlisted"

    assert result["success"] is True
    assert result["request_id"] == "req-42"
    assert result["platforms"] == ["tiktok", "youtube"]

    # Telemetry: a running then a complete publish-stage event was recorded.
    stages = [(stage, status) for (_, stage, status) in events]
    assert (publish_mod._PUBLISH_STAGE, const.REELFORGE_STAGE_RUNNING) in stages
    assert (publish_mod._PUBLISH_STAGE, const.REELFORGE_STAGE_COMPLETE) in stages


def test_publish_job_output_requires_platforms(monkeypatch, db_factory):
    Factory = db_factory
    uid = _make_user(Factory)
    jid = _make_complete_job(Factory, uid)

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(publish_mod, "get_session", _fake_get_session)

    with pytest.raises(publish_mod.PublishError):
        publish_mod.publish_job_output(jid, [])


def test_publish_job_output_rejects_incomplete_job(monkeypatch, db_factory):
    Factory = db_factory
    uid = _make_user(Factory)
    # A processing (not complete) job cannot be published.
    with Factory() as s:
        job = JobRepository(s).create(user_id=uid, kind="avatar_reel", params={})
        jid = job.id
        s.commit()

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(publish_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(
        "app.telemetry.events.record_event",
        lambda *a, **k: None,
    )

    with pytest.raises(publish_mod.PublishError):
        publish_mod.publish_job_output(jid, ["tiktok"])


# =========================================================================== #
# 5. Studio controller: POST /jobs/{id}/publish + POST /avatars
# =========================================================================== #
@pytest.fixture()
def studio_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the studio router + in-memory SQLite."""
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

    # The studio module imported get_session into its own namespace.
    monkeypatch.setattr(studio_mod, "get_session", _fake_get_session)
    # Deterministic avatar-preset creation: skip the optional HeyGen probe.
    monkeypatch.setattr(studio_mod, "_try_heygen_talking_photo", lambda key: "")

    app = FastAPI()
    app.include_router(studio_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


def test_publish_endpoint_happy_path(monkeypatch, studio_client):
    client, Factory = studio_client
    uid = _make_user(Factory)
    jid = _make_complete_job(Factory, uid)

    called: dict = {}

    # "Publish now" goes through the caller's own native OAuth connectors,
    # never the operator's shared Upload-Post account.
    def _fake_publish(user_id, job_id, platforms, youtube_privacy_status=None):
        called["user_id"] = user_id
        called["job_id"] = job_id
        called["platforms"] = platforms
        called["privacy"] = youtube_privacy_status
        return {
            "job_id": job_id,
            "results": [{"platform": "tiktok", "status": "published", "url": "https://t/x"}],
        }

    monkeypatch.setattr(
        "app.domains.publishing.native_service.publish_scheduled_reel_native",
        _fake_publish,
    )

    resp = client.post(
        f"/api/v1/jobs/{jid}/publish",
        json={"platforms": ["tiktok"]},
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["request_id"]  # the server's request id is attached
    assert data["results"][0]["status"] == "published"
    assert called == {
        "user_id": uid,
        "job_id": jid,
        "platforms": ["tiktok"],
        "privacy": "private",
    }


def test_publish_endpoint_requires_auth(studio_client):
    client, Factory = studio_client
    uid = _make_user(Factory)
    jid = _make_complete_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/publish", json={"platforms": ["tiktok"]}
    )  # no x-api-key
    assert resp.status_code == 401, resp.text


def test_publish_endpoint_foreign_job_404(studio_client):
    client, Factory = studio_client
    # Job owned by a DIFFERENT user (distinct api key hash).
    other_hash = hashlib.sha256(b"otherkey").hexdigest()
    with Factory() as s:
        owner = User(email="owner@x.com", api_key_hash=other_hash)
        s.add(owner)
        s.flush()
        job = JobRepository(s).create(user_id=owner.id, kind="avatar_reel", params={})
        jid = job.id
        JobRepository(s).mark_complete(jid, "final/o.mp4")
        s.commit()
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.post(
        f"/api/v1/jobs/{jid}/publish",
        json={"platforms": ["tiktok"]},
        headers=_HEADERS,
    )
    assert resp.status_code == 404, resp.text  # ownership enforced, no leak


def test_publish_endpoint_incomplete_job_409(studio_client):
    client, Factory = studio_client
    uid = _make_user(Factory)
    with Factory() as s:
        job = JobRepository(s).create(user_id=uid, kind="avatar_reel", params={})
        jid = job.id  # still PROCESSING
        s.commit()

    resp = client.post(
        f"/api/v1/jobs/{jid}/publish",
        json={"platforms": ["tiktok"]},
        headers=_HEADERS,
    )
    assert resp.status_code == 409, resp.text


def test_publish_endpoint_requires_platforms_400(studio_client):
    client, Factory = studio_client
    uid = _make_user(Factory)
    jid = _make_complete_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/publish", json={"platforms": []}, headers=_HEADERS
    )
    assert resp.status_code == 400, resp.text


def test_create_avatar_requires_heygen_configured(studio_client):
    # POST /avatars now genuinely creates a HeyGen talking-photo (WF33), so with
    # HeyGen unconfigured it must fail cleanly (402 format_locked) rather than
    # persist a stub.
    # The full happy path (with a monkeypatched HeyGen provider) is covered by
    # tests/reelforge/test_studio_avatars.py.
    client, Factory = studio_client
    uid = _make_user(Factory)
    with Factory() as s:
        s.add(Asset(user_id=uid, kind="screen", r2_key="uploads/face.png"))
        s.commit()

    resp = client.post(
        "/api/v1/avatars",
        json={"image_key": "uploads/face.png", "display_name": "Me"},
        headers=_HEADERS,
    )
    assert resp.status_code == 402, resp.text
    assert resp.json()["data"]["code"] == "format_locked"


def test_create_avatar_requires_auth(studio_client):
    client, Factory = studio_client
    resp = client.post(
        "/api/v1/avatars", json={"image_key": "uploads/face.png"}
    )  # no x-api-key
    assert resp.status_code == 401, resp.text


def test_create_avatar_missing_image_key_400(studio_client):
    client, Factory = studio_client
    _make_user(Factory)
    resp = client.post(
        "/api/v1/avatars", json={"image_key": "   "}, headers=_HEADERS
    )
    assert resp.status_code == 400, resp.text


def test_create_avatar_foreign_image_key_403(studio_client):
    client, Factory = studio_client
    # The uploaded image belongs to a DIFFERENT user; the caller only guessed
    # its R2 key. Ownership is enforced -> 403, and nothing is persisted.
    other_hash = hashlib.sha256(b"otherkey").hexdigest()
    with Factory() as s:
        owner = User(email="owner@x.com", api_key_hash=other_hash)
        s.add(owner)
        s.flush()
        s.add(Asset(user_id=owner.id, kind="screen", r2_key="uploads/victim.png"))
        s.commit()
    caller_id = _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.post(
        "/api/v1/avatars",
        json={"image_key": "uploads/victim.png", "display_name": "Steal"},
        headers=_HEADERS,
    )
    assert resp.status_code == 403, resp.text

    # No preset was created for the caller from the foreign key.
    with Factory() as s:
        presets = (
            s.query(AvatarPreset).filter(AvatarPreset.user_id == caller_id).all()
        )
        assert presets == []


def test_publish_endpoint_already_published_409(monkeypatch, studio_client):
    client, Factory = studio_client
    uid = _make_user(Factory)
    jid = _make_complete_job(Factory, uid)
    # A prior successful publish left a completed 'publish' JobEvent behind.
    with Factory() as s:
        s.add(
            JobEvent(
                job_id=jid,
                stage="publish",
                status=const.REELFORGE_STAGE_COMPLETE,
            )
        )
        s.commit()

    def _fail_if_called(*a, **k):  # pragma: no cover - must NOT be reached
        raise AssertionError("publish_job_output must not run for a published job")

    monkeypatch.setattr("app.services.publish.publish_job_output", _fail_if_called)

    resp = client.post(
        f"/api/v1/jobs/{jid}/publish",
        json={"platforms": ["tiktok"]},
        headers=_HEADERS,
    )
    assert resp.status_code == 409, resp.text
