"""Brand Voice API tests (Phase 11 — ElevenLabs Instant Voice Clone).

Covers ``app.controllers.v1.voices`` — the three creator-scoped endpoints that
turn an uploaded voice sample into a private, reusable "brand voice":

* ``POST /voices/clone`` — CONSENT gate (400), ownership (403), and the happy
  path (persists a ``UserVoice`` row + returns ``elevenlabs:<provider_voice_id>``).
* ``GET /voices/mine`` — scoped to the caller only.
* ``DELETE /voices/mine/{id}`` — ownership-checked (404 for a foreign id;
  happy-path also removes the provider voice).

No external I/O: R2 (sample download), ElevenLabs (``voice_clone``), and Postgres
are monkeypatched / faked. A FastAPI ``TestClient`` runs the router over an
in-memory SQLite DB, exactly mirroring ``tests/reelforge/test_phase3.py``.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.voices as voices_mod
from app.models.db.base import Base
from app.models.db.models import Asset, User, UserVoice
from app.models.db.repositories import UserVoiceRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "voices-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


@pytest.fixture(autouse=True)
def _verification_off(monkeypatch):
    """These tests cover the clone flow itself, with the M7.2 live-phrase check
    switched off (the owner rollback mode). The required mode is covered in
    ``test_voice_clone_verification.py``."""
    monkeypatch.setenv("REELFORGE_VOICE_CLONE_VERIFICATION", "off")


# =========================================================================== #
# Test doubles
# =========================================================================== #
class _FakeVoiceClone:
    """Stand-in for :mod:`app.services.tts.voice_clone`.

    ``clone_voice`` returns a deterministic provider voice id; ``delete_voice``
    records the ids it was asked to remove so the controller's best-effort
    provider cleanup can be asserted.
    """

    def __init__(self, provider_voice_id: str = "vc_abc123") -> None:
        self.provider_voice_id = provider_voice_id
        self.clone_calls: list[tuple] = []
        self.deleted: list[str] = []

    def clone_voice(self, name, sample_paths, description: str = ""):
        self.clone_calls.append((name, list(sample_paths), description))
        return {"voice_id": self.provider_voice_id, "name": name}

    def delete_voice(self, provider_voice_id: str) -> bool:
        self.deleted.append(provider_voice_id)
        return True


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


def _make_user(Factory, email="voice@example.com", key_hash=_KEY_HASH, premium_voice=1) -> str:
    """A user holding ``premium_voice`` premium voice credits (clones need one)."""
    from app.services.billing import premium_credits

    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        if premium_voice:
            premium_credits.grant(s, uid, premium_credits.KIND_PREMIUM_VOICE, premium_voice, "test_grant")
        s.commit()
    return uid


def _make_asset(Factory, user_id: str, r2_key: str) -> None:
    """Register the uploaded sample as an Asset owned by ``user_id``."""
    with Factory() as s:
        s.add(Asset(user_id=user_id, kind="upload", r2_key=r2_key))
        s.commit()


def _make_voice(Factory, user_id: str, name="V", pid="vc_x") -> str:
    with Factory() as s:
        v = UserVoiceRepository(s).create(
            user_id=user_id,
            name=name,
            provider_voice_id=pid,
            sample_key="uploads/s.mp3",
            consent=True,
            status="ready",
        )
        vid = v.id
        s.commit()
    return vid


@pytest.fixture()
def voices_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the voices router + in-memory SQLite.

    Fakes the R2 sample download (returns a real local temp file so the
    controller's cleanup runs) and the ElevenLabs ``voice_clone`` service.
    Returns ``(client, Factory, fake_voice_clone)``.
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

    monkeypatch.setattr(voices_mod, "get_session", _fake_get_session)

    fake_vc = _FakeVoiceClone()
    monkeypatch.setattr(voices_mod, "voice_clone", fake_vc)

    def _fake_download(sample_key: str, request_id: str) -> str:
        fd, path = tempfile.mkstemp(prefix="test_voice_", suffix=".mp3")
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"fake-audio-bytes")
        return path

    monkeypatch.setattr(voices_mod, "_download_sample", _fake_download)

    app = FastAPI()
    app.include_router(voices_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory, fake_vc


# =========================================================================== #
# POST /voices/clone
# =========================================================================== #
def test_clone_requires_consent_400(voices_client):
    client, Factory, fake_vc = voices_client
    uid = _make_user(Factory)
    _make_asset(Factory, uid, "uploads/sample.mp3")

    resp = client.post(
        "/api/v1/voices/clone",
        json={"name": "My Voice", "sample_key": "uploads/sample.mp3", "consent": False},
        headers=_HEADERS,
    )
    assert resp.status_code == 400, resp.text
    # No provider work and nothing persisted when consent is withheld.
    assert fake_vc.clone_calls == []
    with Factory() as s:
        assert s.query(UserVoice).count() == 0


def test_clone_without_premium_voice_credits_is_402_before_any_provider_call(voices_client):
    client, Factory, fake_vc = voices_client
    uid = _make_user(Factory, premium_voice=0)
    _make_asset(Factory, uid, "uploads/sample.mp3")

    resp = client.post(
        "/api/v1/voices/clone",
        json={"name": "Me", "sample_key": "uploads/sample.mp3", "consent": True},
        headers=_HEADERS,
    )
    assert resp.status_code == 402, resp.text
    assert resp.json()["data"]["code"] == "premium_voice_credits_required"
    assert fake_vc.clone_calls == []


def test_clone_persists_and_returns_elevenlabs_id(voices_client):
    client, Factory, fake_vc = voices_client
    uid = _make_user(Factory)
    _make_asset(Factory, uid, "uploads/sample.mp3")

    resp = client.post(
        "/api/v1/voices/clone",
        json={
            "name": "My Brand Voice",
            "sample_key": "uploads/sample.mp3",
            "consent": True,
            "description": "warm narrator",
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # Returns the narrator selector, not the raw provider id.
    assert data["voice_id"] == "elevenlabs:vc_abc123"
    assert data["name"] == "My Brand Voice"
    assert data["status"] == "ready"
    assert data["id"]

    # clone_voice received the downloaded sample path + description.
    assert len(fake_vc.clone_calls) == 1
    name_arg, paths_arg, desc_arg = fake_vc.clone_calls[0]
    assert name_arg == "My Brand Voice"
    assert len(paths_arg) == 1
    assert desc_arg == "warm narrator"

    # Persisted a UserVoice row scoped to the caller with consent recorded.
    with Factory() as s:
        rows = s.query(UserVoice).filter(UserVoice.user_id == uid).all()
        assert len(rows) == 1
        assert rows[0].provider_voice_id == "vc_abc123"
        assert rows[0].consent is True
        assert rows[0].sample_key == "uploads/sample.mp3"
        assert rows[0].status == "ready"


def test_clone_missing_asset_model_fails_closed_503(voices_client, monkeypatch):
    """Fix [1]: if the ``Asset`` model is unavailable the ownership (BOLA) check
    cannot run, so the endpoint MUST fail closed with 503 rather than skip the
    check and clone whatever ``sample_key`` the caller supplied."""
    client, Factory, fake_vc = voices_client
    uid = _make_user(Factory)
    _make_asset(Factory, uid, "uploads/sample.mp3")
    monkeypatch.setattr(voices_mod, "Asset", None)

    resp = client.post(
        "/api/v1/voices/clone",
        json={"name": "V", "sample_key": "uploads/sample.mp3", "consent": True},
        headers=_HEADERS,
    )
    assert resp.status_code == 503, resp.text
    # No provider work happens when the ownership guard cannot be enforced.
    assert fake_vc.clone_calls == []
    with Factory() as s:
        assert s.query(UserVoice).count() == 0


def test_clone_persist_failure_deletes_orphan_provider_voice(voices_client, monkeypatch):
    """Fix [2]: when the DB INSERT fails AFTER a successful provider clone, the
    already-created ElevenLabs voice must be compensatingly deleted (else it is
    orphaned — no DB row, unreachable via DELETE) and the caller gets a 502."""
    client, Factory, fake_vc = voices_client
    uid = _make_user(Factory)
    _make_asset(Factory, uid, "uploads/sample.mp3")

    class _BoomRepo:
        def __init__(self, session) -> None:
            pass

        def create(self, **kwargs):
            raise RuntimeError("db down")

    monkeypatch.setattr(voices_mod, "UserVoiceRepository", _BoomRepo)

    resp = client.post(
        "/api/v1/voices/clone",
        json={"name": "V", "sample_key": "uploads/sample.mp3", "consent": True},
        headers=_HEADERS,
    )
    assert resp.status_code == 502, resp.text
    # Provider voice was created (step 1) then compensatingly removed (step 2 failed).
    assert fake_vc.clone_calls
    assert fake_vc.deleted == ["vc_abc123"]
    with Factory() as s:
        assert s.query(UserVoice).count() == 0


def test_download_sample_closes_fd_when_get_raises(monkeypatch):
    """Fix [3]: a network error from ``requests.get`` before the write loop must
    not leak the raw ``mkstemp`` file descriptor; the temp file is removed and
    the fd is closed (``os.fstat`` on a closed fd raises ``OSError``)."""
    captured: dict = {}
    real_mkstemp = tempfile.mkstemp

    def _tracking_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        captured["fd"] = fd
        captured["path"] = path
        return fd, path

    monkeypatch.setattr(voices_mod.tempfile, "mkstemp", _tracking_mkstemp)

    class _FakeR2:
        def presign_get(self, key: str) -> str:
            return "http://example.invalid/sample"

    monkeypatch.setattr(
        "app.services.storage.r2.get_r2_client", lambda: _FakeR2()
    )

    class _FakeRequests:
        def get(self, *args, **kwargs):
            raise ConnectionError("boom")

    monkeypatch.setattr(voices_mod, "requests", _FakeRequests())

    with pytest.raises(HttpException) as excinfo:
        voices_mod._download_sample("uploads/x.mp3", "req-1")
    assert excinfo.value.status_code == 502

    # Temp file cleaned up and the descriptor is not leaked.
    assert not os.path.exists(captured["path"])
    with pytest.raises(OSError):
        os.fstat(captured["fd"])


def test_clone_requires_auth_401(voices_client):
    client, Factory, fake_vc = voices_client
    resp = client.post(
        "/api/v1/voices/clone",
        json={"name": "V", "sample_key": "uploads/s.mp3", "consent": True},
    )  # no x-api-key
    assert resp.status_code == 401, resp.text


def test_clone_foreign_sample_key_403(voices_client):
    client, Factory, fake_vc = voices_client
    # The sample belongs to a DIFFERENT user; the caller only guessed its key.
    other_hash = hashlib.sha256(b"otherkey").hexdigest()
    owner_id = _make_user(Factory, email="owner@x.com", key_hash=other_hash)
    _make_asset(Factory, owner_id, "uploads/victim.mp3")
    caller_id = _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.post(
        "/api/v1/voices/clone",
        json={"name": "Steal", "sample_key": "uploads/victim.mp3", "consent": True},
        headers=_HEADERS,
    )
    assert resp.status_code == 403, resp.text
    assert fake_vc.clone_calls == []
    with Factory() as s:
        assert s.query(UserVoice).filter(UserVoice.user_id == caller_id).count() == 0


# =========================================================================== #
# GET /voices/mine
# =========================================================================== #
def test_mine_scoped_to_caller(voices_client):
    client, Factory, fake_vc = voices_client
    caller_id = _make_user(Factory, email="caller@x.com")
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    _make_voice(Factory, caller_id, name="Mine A", pid="vc_a")
    _make_voice(Factory, caller_id, name="Mine B", pid="vc_b")
    _make_voice(Factory, other_id, name="Theirs", pid="vc_z")

    resp = client.get("/api/v1/voices/mine", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data) == 2
    names = {item["name"] for item in data}
    assert names == {"Mine A", "Mine B"}
    # Each item exposes the narrator selector + created_at.
    for item in data:
        assert item["voice_id"].startswith("elevenlabs:")
        assert item["status"] == "ready"
        assert "created_at" in item


def test_mine_requires_auth_401(voices_client):
    client, Factory, fake_vc = voices_client
    resp = client.get("/api/v1/voices/mine")  # no x-api-key
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# DELETE /voices/mine/{id}
# =========================================================================== #
def test_delete_foreign_voice_404(voices_client):
    client, Factory, fake_vc = voices_client
    # Voice owned by a DIFFERENT user; the caller must not be able to delete it.
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    victim_vid = _make_voice(Factory, other_id, name="Theirs", pid="vc_victim")
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.delete(f"/api/v1/voices/mine/{victim_vid}", headers=_HEADERS)
    assert resp.status_code == 404, resp.text
    # The foreign row survives and the provider was never asked to delete it.
    assert fake_vc.deleted == []
    with Factory() as s:
        assert s.get(UserVoice, victim_vid) is not None


def test_delete_own_voice_happy_path(voices_client):
    client, Factory, fake_vc = voices_client
    uid = _make_user(Factory)
    vid = _make_voice(Factory, uid, name="Mine", pid="vc_mine")

    resp = client.delete(f"/api/v1/voices/mine/{vid}", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["deleted"] is True
    # Provider voice removed (best-effort) + local row gone.
    assert fake_vc.deleted == ["vc_mine"]
    with Factory() as s:
        assert s.get(UserVoice, vid) is None


def test_delete_unknown_voice_404(voices_client):
    client, Factory, fake_vc = voices_client
    _make_user(Factory)
    resp = client.delete("/api/v1/voices/mine/does-not-exist", headers=_HEADERS)
    assert resp.status_code == 404, resp.text
