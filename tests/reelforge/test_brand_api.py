"""Brand Watermark API tests (per-user logo overlay settings).

Covers ``app.controllers.v1.brand`` — the two creator-scoped endpoints that read
and update a user's :class:`~app.models.db.models.UserBrand` watermark singleton:

* ``GET  /me/brand`` — returns the caller's settings (the model defaults when
  none exists) plus a presigned ``logo_url`` when a ``logo_key`` is set. Strictly
  caller-scoped: another user's GET returns THEIR own defaults, never the first
  user's row.
* ``PUT  /me/brand`` — validates ``position`` (400) + ``opacity`` (400), enforces
  ownership of a supplied ``logo_key`` against the caller-scoped ``Asset``
  registry (403), and upserts the row.

No external I/O: R2 (logo presign) is faked and Postgres is an in-memory SQLite
DB behind a FastAPI ``TestClient``, mirroring ``tests/reelforge/test_voices_api.py``.
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

import app.controllers.v1.brand as brand_mod
from app.models.db.base import Base
from app.models.db.models import Asset, User, UserBrand
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "brand-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


# =========================================================================== #
# Fixtures + helpers
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


def _make_user(Factory, email="brand@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_asset(Factory, user_id: str, r2_key: str) -> None:
    """Register an uploaded logo as an ``Asset`` owned by ``user_id``."""
    with Factory() as s:
        s.add(Asset(user_id=user_id, kind="upload", r2_key=r2_key))
        s.commit()


class _FakeR2:
    """Deterministic presigned GET URL for a logo key."""

    def presign_get(self, key: str) -> str:
        return f"https://r2.test/{key}?signed=1"


@pytest.fixture()
def brand_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the brand router + in-memory SQLite.

    Fakes the R2 logo presign. Returns ``(client, Factory)``.
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

    monkeypatch.setattr(brand_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(
        "app.services.storage.r2.get_r2_client", lambda: _FakeR2()
    )

    app = FastAPI()
    app.include_router(brand_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# =========================================================================== #
# GET /me/brand
# =========================================================================== #
def test_get_brand_returns_defaults_when_unset(brand_client):
    client, Factory = brand_client
    _make_user(Factory)

    resp = client.get("/api/v1/me/brand", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # The UserBrand column defaults: enabled bottom_right at 0.85, no logo yet.
    assert data["logo_key"] == ""
    assert data["position"] == "bottom_right"
    assert data["opacity"] == 0.85
    assert data["enabled"] is True
    assert data["logo_url"] is None
    # No row is created merely by reading.
    with Factory() as s:
        assert s.query(UserBrand).count() == 0


def test_get_brand_requires_auth_401(brand_client):
    client, Factory = brand_client
    resp = client.get("/api/v1/me/brand")  # no x-api-key
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# PUT /me/brand  (happy path + round-trip)
# =========================================================================== #
def test_put_sets_brand_then_get_returns_it(brand_client):
    client, Factory = brand_client
    uid = _make_user(Factory)
    _make_asset(Factory, uid, "uploads/logo.png")

    resp = client.put(
        "/api/v1/me/brand",
        json={
            "logo_key": "uploads/logo.png",
            "position": "top_left",
            "opacity": 0.5,
            "enabled": True,
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["logo_key"] == "uploads/logo.png"
    assert data["position"] == "top_left"
    assert data["opacity"] == 0.5
    assert data["enabled"] is True
    # A logo is set -> a presigned preview URL is returned.
    assert data["logo_url"] == "https://r2.test/uploads/logo.png?signed=1"

    # Persisted exactly one row scoped to the caller.
    with Factory() as s:
        rows = s.query(UserBrand).filter(UserBrand.user_id == uid).all()
        assert len(rows) == 1
        assert rows[0].logo_key == "uploads/logo.png"
        assert rows[0].position == "top_left"
        assert rows[0].opacity == 0.5

    # GET now returns the persisted settings.
    resp2 = client.get("/api/v1/me/brand", headers=_HEADERS)
    assert resp2.status_code == 200, resp2.text
    got = resp2.json()["data"]
    assert got["logo_key"] == "uploads/logo.png"
    assert got["position"] == "top_left"
    assert got["opacity"] == 0.5
    assert got["logo_url"] == "https://r2.test/uploads/logo.png?signed=1"


def test_put_is_partial_update_and_upserts_in_place(brand_client):
    client, Factory = brand_client
    uid = _make_user(Factory)

    # First: only change the position (no logo needed).
    r1 = client.put(
        "/api/v1/me/brand", json={"position": "bottom_left"}, headers=_HEADERS
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["position"] == "bottom_left"

    # Second: only toggle enabled off -> position must be preserved, one row only.
    r2 = client.put(
        "/api/v1/me/brand", json={"enabled": False}, headers=_HEADERS
    )
    assert r2.status_code == 200, r2.text
    d = r2.json()["data"]
    assert d["enabled"] is False
    assert d["position"] == "bottom_left"  # untouched field preserved
    with Factory() as s:
        assert s.query(UserBrand).filter(UserBrand.user_id == uid).count() == 1


# =========================================================================== #
# PUT /me/brand  (validation -> 400)
# =========================================================================== #
def test_put_invalid_position_400(brand_client):
    client, Factory = brand_client
    _make_user(Factory)
    resp = client.put(
        "/api/v1/me/brand", json={"position": "middle"}, headers=_HEADERS
    )
    assert resp.status_code == 400, resp.text
    with Factory() as s:
        assert s.query(UserBrand).count() == 0


@pytest.mark.parametrize("bad_opacity", [-0.1, 1.5, 2, -3])
def test_put_invalid_opacity_400(brand_client, bad_opacity):
    client, Factory = brand_client
    _make_user(Factory)
    resp = client.put(
        "/api/v1/me/brand", json={"opacity": bad_opacity}, headers=_HEADERS
    )
    assert resp.status_code == 400, resp.text
    with Factory() as s:
        assert s.query(UserBrand).count() == 0


# =========================================================================== #
# PUT /me/brand  (ownership -> 403)
# =========================================================================== #
def test_put_foreign_logo_key_403(brand_client):
    client, Factory = brand_client
    # The logo belongs to a DIFFERENT user; the caller only guessed its key.
    other_hash = hashlib.sha256(b"otherkey").hexdigest()
    owner_id = _make_user(Factory, email="owner@x.com", key_hash=other_hash)
    _make_asset(Factory, owner_id, "uploads/victim.png")
    caller_id = _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.put(
        "/api/v1/me/brand",
        json={"logo_key": "uploads/victim.png"},
        headers=_HEADERS,
    )
    assert resp.status_code == 403, resp.text
    # Nothing persisted for the caller.
    with Factory() as s:
        assert s.query(UserBrand).filter(UserBrand.user_id == caller_id).count() == 0


def test_put_unknown_logo_key_403(brand_client):
    client, Factory = brand_client
    _make_user(Factory)  # caller owns no assets at all
    resp = client.put(
        "/api/v1/me/brand",
        json={"logo_key": "uploads/nope.png"},
        headers=_HEADERS,
    )
    assert resp.status_code == 403, resp.text


def test_put_empty_logo_key_clears_without_ownership_check(brand_client):
    """An explicit ``logo_key=""`` clears the logo and needs no owned asset."""
    client, Factory = brand_client
    uid = _make_user(Factory)
    _make_asset(Factory, uid, "uploads/logo.png")
    # Set a logo first.
    client.put(
        "/api/v1/me/brand",
        json={"logo_key": "uploads/logo.png"},
        headers=_HEADERS,
    )
    # Now clear it — no ownership check applies to the empty string.
    resp = client.put("/api/v1/me/brand", json={"logo_key": ""}, headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["logo_key"] == ""
    assert data["logo_url"] is None


def test_put_fails_closed_503_when_asset_model_missing(brand_client, monkeypatch):
    """The ownership guard MUST fail closed (503) when ``Asset`` is unavailable
    rather than trusting whatever ``logo_key`` the caller supplied."""
    client, Factory = brand_client
    uid = _make_user(Factory)
    _make_asset(Factory, uid, "uploads/logo.png")
    monkeypatch.setattr(brand_mod, "Asset", None)

    resp = client.put(
        "/api/v1/me/brand",
        json={"logo_key": "uploads/logo.png"},
        headers=_HEADERS,
    )
    assert resp.status_code == 503, resp.text
    with Factory() as s:
        assert s.query(UserBrand).count() == 0


# =========================================================================== #
# Per-user isolation
# =========================================================================== #
def test_brand_is_per_user(brand_client):
    client, Factory = brand_client
    # User A configures a distinctive brand.
    a_id = _make_user(Factory, email="a@x.com", key_hash=_KEY_HASH)
    _make_asset(Factory, a_id, "uploads/a.png")
    ra = client.put(
        "/api/v1/me/brand",
        json={"logo_key": "uploads/a.png", "position": "top_right", "opacity": 0.2},
        headers=_HEADERS,
    )
    assert ra.status_code == 200, ra.text

    # User B (different api key) reads their OWN brand -> defaults, never A's row.
    b_key = "brand-key-b"
    b_hash = hashlib.sha256(b_key.encode("utf-8")).hexdigest()
    _make_user(Factory, email="b@x.com", key_hash=b_hash)
    rb = client.get("/api/v1/me/brand", headers={"x-api-key": b_key})
    assert rb.status_code == 200, rb.text
    b_data = rb.json()["data"]
    assert b_data["logo_key"] == ""
    assert b_data["position"] == "bottom_right"
    assert b_data["opacity"] == 0.85
    assert b_data["logo_url"] is None

    # User A still sees their own settings unchanged.
    ra2 = client.get("/api/v1/me/brand", headers=_HEADERS)
    assert ra2.json()["data"]["logo_key"] == "uploads/a.png"
    assert ra2.json()["data"]["position"] == "top_right"
