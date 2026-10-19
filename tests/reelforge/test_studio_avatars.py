"""Custom avatar from a photo — ``POST /api/v1/avatars`` studio endpoint.

Exercises the completed talking-photo flow end-to-end through a FastAPI
``TestClient`` over in-memory SQLite, with the HeyGen provider and the R2
download fully monkeypatched so **no HTTP socket is ever opened**:

* Creating an avatar from an image the caller OWNS mints a HeyGen
  ``talking_photo_id`` and persists an owner-scoped ``AvatarPreset``
  (``provider='heygen'``, ``config.kind='talking_photo'``) that then appears in
  ``GET /api/v1/avatars`` for the caller (and NOT for another user).
* A foreign/guessed ``image_key`` is rejected with ``403`` and the image is
  never downloaded or sent to HeyGen (BOLA guard).
* A missing/blank ``image_key`` is a ``400``; a missing ``x-api-key`` is ``401``.
* When HeyGen is not configured the endpoint fails clean with ``402 format_locked``.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.jobs as jobs_mod
import app.controllers.v1.studio as studio_mod
import app.services.avatar.base as avatar_base
from app.models.db.base import Base
from app.models.db.models import Asset, AvatarPreset, User
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "studio-avatars-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


# =========================================================================== #
# Test doubles
# =========================================================================== #
class _FakeHeyGenProvider:
    """Enabled ``TalkingHeadProvider`` double that records its inputs.

    ``create_talking_photo`` returns a deterministic ``talking_photo_id`` and
    captures the local image path it was handed, so tests can assert the OWNED
    image (and only that) reached HeyGen.
    """

    name = "heygen"

    def __init__(self, *, enabled: bool = True, talking_photo_id: str = "tp_abc123") -> None:
        self._enabled = enabled
        self._talking_photo_id = talking_photo_id
        self.created_with: list[str] = []

    def is_enabled(self) -> bool:
        return self._enabled

    def list_avatars(self) -> list[dict]:
        return []

    def create_talking_photo(self, image_path: str, *, mime: str | None = None) -> str | None:
        self.created_with.append(image_path)
        return self._talking_photo_id

    def generate_avatar(self, *args: Any, **kwargs: Any) -> dict | None:  # pragma: no cover
        return None


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
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture()
def studio_env(monkeypatch, db_factory):
    """TestClient wired to the studio + jobs routers over in-memory SQLite.

    Both the studio ``POST /avatars`` and the jobs ``GET /avatars`` routes share
    the same in-memory DB (both modules' ``get_session`` are patched). The R2
    image download is stubbed to a dummy path and a fake enabled HeyGen provider
    is injected, so the whole flow is hermetic.
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

    monkeypatch.setattr(studio_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(jobs_mod, "get_session", _fake_get_session)

    # No real R2/network: the download returns a stable dummy path. The fake
    # provider never opens it, and create_avatar's os.remove tolerates a missing
    # file.
    monkeypatch.setattr(
        studio_mod, "_download_image_to_temp", lambda key, rid: "/tmp/heygen_photo_test.jpg"
    )
    # No public bucket configured in tests -> keep the thumbnail derivation inert.
    monkeypatch.setattr(studio_mod, "_safe_thumbnail_url", lambda key, rid: "")

    provider = _FakeHeyGenProvider()
    monkeypatch.setattr(avatar_base, "get_avatar_provider", lambda _id="heygen": provider)

    app = FastAPI()
    app.include_router(studio_mod.router)
    app.include_router(jobs_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory, provider


# =========================================================================== #
# Helpers
# =========================================================================== #
def _make_user(Factory, *, email="creator@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _add_asset(Factory, user_id: str, r2_key: str) -> None:
    with Factory() as s:
        s.add(Asset(user_id=user_id, kind="image", r2_key=r2_key))
        s.commit()


# =========================================================================== #
# Happy path
# =========================================================================== #
def test_create_avatar_from_owned_image_persists_talking_photo_preset(studio_env):
    client, Factory, provider = studio_env
    uid = _make_user(Factory)
    _add_asset(Factory, uid, "uploads/selfie.jpg")

    resp = client.post(
        "/api/v1/avatars",
        json={
            "image_key": "uploads/selfie.jpg",
            "display_name": "My Face",
            "voice_name": "elevenlabs:21m00Tcm4TlvDq8ikWAM",
        },
        headers=_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"]
    assert data["provider"] == "heygen"
    # The provider's talking_photo_id (NOT the raw image key) is the avatar id.
    assert data["provider_avatar_id"] == "tp_abc123"
    assert data["display_name"] == "My Face"
    assert data["kind"] == "talking_photo"
    assert data["is_active"] is True

    # HeyGen received exactly the downloaded (owned) image path.
    assert provider.created_with == ["/tmp/heygen_photo_test.jpg"]

    # Persisted, owner-scoped, with the talking-photo config marker.
    with Factory() as s:
        presets = s.query(AvatarPreset).filter(AvatarPreset.user_id == uid).all()
        assert len(presets) == 1
        preset = presets[0]
        assert preset.provider == "heygen"
        assert preset.provider_avatar_id == "tp_abc123"
        assert preset.voice_name == "elevenlabs:21m00Tcm4TlvDq8ikWAM"
        assert preset.is_active is True
        assert preset.config == {
            "kind": "talking_photo",
            "source_image_key": "uploads/selfie.jpg",
        }


def test_created_avatar_appears_in_list_for_caller_not_others(studio_env):
    client, Factory, provider = studio_env
    caller_id = _make_user(Factory)
    _add_asset(Factory, caller_id, "uploads/mine.png")

    create = client.post(
        "/api/v1/avatars",
        json={"image_key": "uploads/mine.png", "display_name": "Mine"},
        headers=_HEADERS,
    )
    assert create.status_code == 200, create.text
    avatar_id = create.json()["data"]["id"]

    # The caller sees the new preset in GET /avatars.
    mine = client.get("/api/v1/avatars", headers=_HEADERS)
    assert mine.status_code == 200, mine.text
    ids = [row["id"] for row in mine.json()["data"] if row.get("source") == "preset"]
    assert avatar_id in ids

    # A DIFFERENT user (who has their OWN avatar) does NOT see the caller's
    # private preset — presets are strictly owner-scoped.
    other_hash = hashlib.sha256(b"other-user-key").hexdigest()
    other_id = _make_user(Factory, email="other@example.com", key_hash=other_hash)
    _add_asset(Factory, other_id, "uploads/theirs.png")
    other_headers = {"x-api-key": "other-user-key"}
    other_create = client.post(
        "/api/v1/avatars",
        json={"image_key": "uploads/theirs.png", "display_name": "Theirs"},
        headers=other_headers,
    )
    assert other_create.status_code == 200, other_create.text
    other_avatar_id = other_create.json()["data"]["id"]

    other = client.get("/api/v1/avatars", headers=other_headers)
    assert other.status_code == 200, other.text
    other_ids = [
        row["id"] for row in other.json()["data"] if row.get("source") == "preset"
    ]
    assert other_avatar_id in other_ids  # sees their own
    assert avatar_id not in other_ids  # never the caller's


# =========================================================================== #
# Security + validation
# =========================================================================== #
def test_create_avatar_foreign_image_key_403_and_never_calls_heygen(studio_env):
    client, Factory, provider = studio_env
    # The image belongs to a DIFFERENT user; the caller only guessed its key.
    other_hash = hashlib.sha256(b"owner-key").hexdigest()
    owner_id = _make_user(Factory, email="owner@example.com", key_hash=other_hash)
    _add_asset(Factory, owner_id, "uploads/victim.png")
    caller_id = _make_user(Factory, email="caller@example.com")

    resp = client.post(
        "/api/v1/avatars",
        json={"image_key": "uploads/victim.png", "display_name": "Steal"},
        headers=_HEADERS,
    )
    assert resp.status_code == 403, resp.text

    # The foreign image was never downloaded/forwarded to HeyGen...
    assert provider.created_with == []
    # ...and no preset was created for the caller.
    with Factory() as s:
        presets = (
            s.query(AvatarPreset).filter(AvatarPreset.user_id == caller_id).all()
        )
        assert presets == []


def test_create_avatar_missing_image_key_400(studio_env):
    client, Factory, provider = studio_env
    _make_user(Factory)
    resp = client.post(
        "/api/v1/avatars", json={"image_key": "   "}, headers=_HEADERS
    )
    assert resp.status_code == 400, resp.text
    assert provider.created_with == []


def test_create_avatar_requires_auth_401(studio_env):
    client, Factory, provider = studio_env
    resp = client.post(
        "/api/v1/avatars", json={"image_key": "uploads/x.jpg"}
    )  # no x-api-key
    assert resp.status_code == 401, resp.text


def test_create_avatar_heygen_not_configured_503(monkeypatch, studio_env):
    client, Factory, provider = studio_env
    uid = _make_user(Factory)
    _add_asset(Factory, uid, "uploads/selfie.jpg")

    # HeyGen present but not enabled (no api key) -> 402 format_locked, nothing persisted.
    disabled = _FakeHeyGenProvider(enabled=False)
    monkeypatch.setattr(avatar_base, "get_avatar_provider", lambda _id="heygen": disabled)

    resp = client.post(
        "/api/v1/avatars",
        json={"image_key": "uploads/selfie.jpg"},
        headers=_HEADERS,
    )
    assert resp.status_code == 402, resp.text
    assert resp.json()["data"]["code"] == "format_locked"
    assert disabled.created_with == []
    with Factory() as s:
        assert s.query(AvatarPreset).filter(AvatarPreset.user_id == uid).all() == []
