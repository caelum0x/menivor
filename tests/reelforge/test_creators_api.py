"""Creator Profiles + Follow Graph + Leaderboards API tests.

Covers ``app.controllers.v1.creators``:

* ``GET    /creators/{handle_or_id}`` — PUBLIC safe profile (by id OR handle),
  exposes ONLY safe fields (never email/credits/user_id), 404 unknown.
* ``POST   /creators/{id}/follow``    — auth; idempotent; self-follow → 400;
  unknown followee → 404; 401 without a key.
* ``DELETE /creators/{id}/follow``    — auth; idempotent unfollow.
* ``GET    /me/following``            — auth; safe public profiles the caller follows.
* ``GET    /creators/leaderboard``    — PUBLIC; ``limit`` clamp (never 422); safe
  fields only; ``leaderboard`` is not captured as a handle by the ``{id}`` route.
* ``PATCH  /me/profile``              — auth; set handle/display_name/bio; a taken
  handle → 409.

No external I/O: Postgres is replaced by an in-memory SQLite DB behind a
``TestClient``, mirroring ``tests/reelforge/test_marketplace_api.py``.
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

import app.controllers.v1.creators as creators_mod
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import MarketplaceRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "creator-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

_OTHER_KEY = "other-key"
_OTHER_HASH = hashlib.sha256(_OTHER_KEY.encode("utf-8")).hexdigest()
_OTHER_HEADERS = {"x-api-key": _OTHER_KEY}


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture()
def db_factory():
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


def _make_user(
    Factory,
    email="creator@example.com",
    key_hash=_KEY_HASH,
    handle=None,
    display_name="",
    bio=None,
) -> str:
    with Factory() as s:
        u = User(
            email=email,
            api_key_hash=key_hash,
            credits=99,
            handle=handle,
            display_name=display_name,
            bio=bio,
        )
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _publish(Factory, author_id: str, **kwargs) -> str:
    defaults = dict(
        author_user_id=author_id,
        title="A great template",
        description="d",
        prompt="p",
        params={},
        tags=["saas"],
        language="en",
        layout="split",
    )
    defaults.update(kwargs)
    with Factory() as s:
        row = MarketplaceRepository(s).publish(**defaults)
        tid = row.id
        s.commit()
    return tid


@pytest.fixture()
def creators_client(monkeypatch, db_factory):
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

    monkeypatch.setattr(creators_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(creators_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# =========================================================================== #
# GET /creators/{handle_or_id}  (public safe profile)
# =========================================================================== #
def test_profile_by_id_safe_fields_only(creators_client):
    client, Factory = creators_client
    uid = _make_user(
        Factory, handle="jane-reels", display_name="Jane", bio="I make reels."
    )
    _publish(Factory, uid, title="Kit A")
    _publish(Factory, uid, title="Kit B")

    # Public: no auth header needed.
    resp = client.get(f"/api/v1/creators/{uid}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert set(data.keys()) == {
        "handle",
        "display_name",
        "bio",
        "published_template_count",
        "total_clones_received",
        "avg_rating",
        "follower_count",
        "following_count",
    }
    assert data["handle"] == "jane-reels"
    assert data["display_name"] == "Jane"
    assert data["published_template_count"] == 2
    # No private field leaks into the profile.
    body = resp.text
    assert "creator@example.com" not in body
    assert uid not in body  # the user_id is never exposed
    for leaked in ("credits", "email", "user_id", "cost", "revenue"):
        assert leaked not in body


def test_profile_by_handle_case_insensitive(creators_client):
    client, Factory = creators_client
    _make_user(Factory, handle="jane-reels", display_name="Jane")
    resp = client.get("/api/v1/creators/JANE-REELS")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["handle"] == "jane-reels"


def test_profile_unknown_404(creators_client):
    client, _ = creators_client
    resp = client.get("/api/v1/creators/nobody-here")
    assert resp.status_code == 404, resp.text


# =========================================================================== #
# POST/DELETE /creators/{id}/follow
# =========================================================================== #
def test_follow_requires_auth_401(creators_client):
    client, Factory = creators_client
    followee = _make_user(Factory, email="f@x.com", key_hash=_OTHER_HASH)
    resp = client.post(f"/api/v1/creators/{followee}/follow")
    assert resp.status_code == 401, resp.text


def test_follow_idempotent_and_counts(creators_client):
    client, Factory = creators_client
    caller = _make_user(Factory)  # default key
    followee = _make_user(Factory, email="f@x.com", key_hash=_OTHER_HASH)

    first = client.post(f"/api/v1/creators/{followee}/follow", headers=_HEADERS)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["following"] is True
    assert first.json()["data"]["follower_count"] == 1

    # Double-follow is a harmless no-op — still one follower.
    second = client.post(f"/api/v1/creators/{followee}/follow", headers=_HEADERS)
    assert second.status_code == 200, second.text
    assert second.json()["data"]["follower_count"] == 1
    assert caller  # caller exists


def test_cannot_follow_self_400(creators_client):
    client, Factory = creators_client
    caller = _make_user(Factory)
    resp = client.post(f"/api/v1/creators/{caller}/follow", headers=_HEADERS)
    assert resp.status_code == 400, resp.text


def test_follow_unknown_followee_404(creators_client):
    client, Factory = creators_client
    _make_user(Factory)
    resp = client.post("/api/v1/creators/ghost/follow", headers=_HEADERS)
    assert resp.status_code == 404, resp.text


def test_unfollow_idempotent(creators_client):
    client, Factory = creators_client
    _make_user(Factory)
    followee = _make_user(Factory, email="f@x.com", key_hash=_OTHER_HASH)

    client.post(f"/api/v1/creators/{followee}/follow", headers=_HEADERS)
    first = client.delete(f"/api/v1/creators/{followee}/follow", headers=_HEADERS)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["removed"] is True
    assert first.json()["data"]["following"] is False

    # Unfollowing again is a no-op.
    second = client.delete(f"/api/v1/creators/{followee}/follow", headers=_HEADERS)
    assert second.json()["data"]["removed"] is False


# =========================================================================== #
# GET /me/following
# =========================================================================== #
def test_me_following_lists_safe_profiles(creators_client):
    client, Factory = creators_client
    _make_user(Factory)  # caller
    followee = _make_user(
        Factory,
        email="f@x.com",
        key_hash=_OTHER_HASH,
        handle="followee-one",
        display_name="Followee",
    )
    client.post(f"/api/v1/creators/{followee}/follow", headers=_HEADERS)

    resp = client.get("/api/v1/me/following", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["handle"] == "followee-one"
    # Safe fields only — no user_id / email in the following list.
    assert "email" not in resp.text
    assert followee not in resp.text


def test_me_following_requires_auth_401(creators_client):
    client, _ = creators_client
    resp = client.get("/api/v1/me/following")
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# GET /creators/leaderboard  (public, clamp, safe)
# =========================================================================== #
def test_leaderboard_public_and_safe(creators_client):
    client, Factory = creators_client
    a = _make_user(Factory, handle="alpha", display_name="Alpha")
    _publish(Factory, a, title="A1")
    _publish(Factory, a, title="A2")
    b = _make_user(Factory, email="b@x.com", key_hash=_OTHER_HASH, handle="beta")
    _publish(Factory, b, title="B1")

    # PUBLIC — no auth header.
    resp = client.get("/api/v1/creators/leaderboard")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) >= 2
    # Ranked best-first with 1-based ranks; safe fields present, no financials.
    assert rows[0]["rank"] == 1
    for row in rows:
        assert "reputation_score" in row
        assert "email" not in row
        assert "credits" not in row
    assert "email" not in resp.text


def test_leaderboard_limit_clamped_not_422(creators_client):
    client, Factory = creators_client
    a = _make_user(Factory, handle="alpha")
    _publish(Factory, a, title="A1")

    resp = client.get("/api/v1/creators/leaderboard", params={"limit": 100000})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["data"]) <= 100


def test_leaderboard_metric_unknown_falls_back(creators_client):
    client, Factory = creators_client
    a = _make_user(Factory, handle="alpha")
    _publish(Factory, a, title="A1")

    resp = client.get("/api/v1/creators/leaderboard", params={"metric": "bogus"})
    assert resp.status_code == 200, resp.text


def test_leaderboard_route_not_shadowed_by_handle(creators_client):
    """`/creators/leaderboard` must resolve to the board, not the profile route."""
    client, Factory = creators_client
    _make_user(Factory, handle="alpha")
    resp = client.get("/api/v1/creators/leaderboard")
    assert resp.status_code == 200, resp.text
    # A leaderboard payload is a list; a profile payload would be a dict.
    assert isinstance(resp.json()["data"], list)


# =========================================================================== #
# PATCH /me/profile
# =========================================================================== #
def test_update_profile_sets_handle_bio(creators_client):
    client, Factory = creators_client
    _make_user(Factory)
    resp = client.patch(
        "/api/v1/me/profile",
        json={"handle": "New-Handle", "display_name": "Nx", "bio": "hi"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["handle"] == "new-handle"  # normalised lowercase
    assert data["display_name"] == "Nx"
    assert data["bio"] == "hi"


def test_update_profile_taken_handle_409(creators_client):
    client, Factory = creators_client
    _make_user(Factory, email="owner@x.com", key_hash=_OTHER_HASH, handle="taken")
    _make_user(Factory)  # caller
    resp = client.patch(
        "/api/v1/me/profile", json={"handle": "taken"}, headers=_HEADERS
    )
    assert resp.status_code == 409, resp.text


def test_update_profile_bad_handle_422(creators_client):
    client, Factory = creators_client
    _make_user(Factory)
    resp = client.patch(
        "/api/v1/me/profile", json={"handle": "no spaces!"}, headers=_HEADERS
    )
    assert resp.status_code == 422, resp.text


def test_update_profile_requires_auth_401(creators_client):
    client, _ = creators_client
    resp = client.patch("/api/v1/me/profile", json={"bio": "x"})
    assert resp.status_code == 401, resp.text
