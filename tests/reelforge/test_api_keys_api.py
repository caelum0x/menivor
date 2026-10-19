"""Personal API keys API tests (PUBLIC API KEYS feature).

Covers ``app.controllers.v1.api_keys`` — the three auth-gated, strictly
owner-scoped endpoints:

* ``POST   /me/api-keys``      — mint a key; the FULL raw secret is revealed
  **once** and only its SHA-256 hash is persisted.
* ``GET    /me/api-keys``      — the caller's keys; never the raw key or hash.
* ``DELETE /me/api-keys/{id}`` — revoke (ownership: a foreign id is a ``404``).

Plus an integration test with the auth-resolution layer
(``app.controllers.v1.base.resolve_user_by_api_key``, the primitive base.py uses
to map an ``x-api-key`` to its owner): a live key resolves to its owner while a
revoked key no longer authenticates.

No external I/O: Postgres is replaced by an in-memory SQLite DB behind a
``TestClient``, mirroring ``tests/reelforge/test_notifications_api.py``.
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

import app.controllers.v1.api_keys as keys_mod
import app.controllers.v1.base as v1_base
from app.models.db.base import Base
from app.models.db.models import User, UserApiKey
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "owner-static-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


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


def _make_user(Factory, email="owner@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


@pytest.fixture()
def keys_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the api_keys router + in-memory SQLite.

    Returns ``(client, Factory)``.
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

    monkeypatch.setattr(keys_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(keys_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


def _create_key(client, name="CI"):
    resp = client.post("/api/v1/me/api-keys", headers=_HEADERS, json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# =========================================================================== #
# POST /me/api-keys  (mint — one-time raw reveal + hash-only persistence)
# =========================================================================== #
def test_create_returns_raw_key_once_and_persists_only_hash(keys_client):
    client, Factory = keys_client
    _make_user(Factory)

    data = _create_key(client, name="CI")

    raw = data["key"]
    assert raw.startswith("rf_"), data
    assert data["name"] == "CI"
    assert data["prefix"] == raw[:12]
    assert data["id"]
    assert data["created_at"]

    # SECURITY: only the SHA-256 hash of the raw key is persisted — never the raw
    # value itself, and the stored hash equals sha256(raw).
    expected_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    with Factory() as s:
        rows = s.query(UserApiKey).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.key_hash == expected_hash
        assert row.key_hash != raw  # the stored digest is not the raw key
        assert raw not in (row.prefix or "")  # prefix leaks no full secret
        assert row.revoked is False
        # No column anywhere holds the raw secret.
        assert raw not in {getattr(row, c.name) for c in row.__table__.columns}


def test_create_requires_name(keys_client):
    client, Factory = keys_client
    _make_user(Factory)

    # Blank name -> validation/400 (empty string fails min_length or _clean_name).
    resp = client.post("/api/v1/me/api-keys", headers=_HEADERS, json={"name": "   "})
    assert resp.status_code in (400, 422), resp.text


def test_create_requires_auth(keys_client):
    client, _ = keys_client
    resp = client.post("/api/v1/me/api-keys", json={"name": "CI"})
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# GET /me/api-keys  (list — never the raw key/hash)
# =========================================================================== #
def test_list_never_exposes_raw_key(keys_client):
    client, Factory = keys_client
    _make_user(Factory)
    created = _create_key(client, name="CI")
    raw = created["key"]

    resp = client.get("/api/v1/me/api-keys", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]
    assert len(items) == 1
    item = items[0]

    # Public envelope only — no raw key, no hash field. The POWER-USER TIER quota
    # fields (per-key limits + current-month usage) are additive and never carry a
    # secret.
    assert set(item.keys()) == {
        "id",
        "name",
        "prefix",
        "last_used_at",
        "revoked",
        "created_at",
        "rate_limit_per_min",
        "monthly_quota",
        "usage_this_month",
    }
    assert "key" not in item
    assert raw not in item.values()
    assert item["prefix"] == raw[:12]
    assert item["revoked"] is False
    assert item["last_used_at"] is None
    # A freshly minted key inherits plan defaults (NULL limits) and has no usage.
    assert item["rate_limit_per_min"] is None
    assert item["monthly_quota"] is None
    assert item["usage_this_month"] == 0

    # The raw key must not appear anywhere in the serialised response body.
    assert raw not in resp.text


def test_second_get_does_not_return_raw_key(keys_client):
    client, Factory = keys_client
    _make_user(Factory)
    raw = _create_key(client, name="CI")["key"]

    first = client.get("/api/v1/me/api-keys", headers=_HEADERS)
    second = client.get("/api/v1/me/api-keys", headers=_HEADERS)
    assert first.status_code == 200 and second.status_code == 200
    assert raw not in first.text
    assert raw not in second.text
    assert "key" not in second.json()["data"][0]


def test_list_is_owner_scoped(keys_client):
    client, Factory = keys_client
    _make_user(Factory)  # caller
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"other").hexdigest()
    )
    # Seed a foreign key directly for the other user.
    with Factory() as s:
        s.add(
            UserApiKey(
                user_id=other_id,
                name="foreign",
                key_hash=hashlib.sha256(b"foreign-raw").hexdigest(),
                prefix="rf_foreign",
                revoked=False,
            )
        )
        s.commit()

    _create_key(client, name="mine")

    resp = client.get("/api/v1/me/api-keys", headers=_HEADERS)
    items = resp.json()["data"]
    assert len(items) == 1
    assert items[0]["name"] == "mine"


# =========================================================================== #
# DELETE /me/api-keys/{id}  (revoke — ownership enforced)
# =========================================================================== #
def test_revoke_own_key(keys_client):
    client, Factory = keys_client
    _make_user(Factory)
    key_id = _create_key(client, name="CI")["id"]

    resp = client.delete(f"/api/v1/me/api-keys/{key_id}", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"id": key_id, "revoked": True}

    with Factory() as s:
        row = s.get(UserApiKey, key_id)
        assert row.revoked is True  # soft-delete: row retained, flagged revoked


def test_revoke_foreign_returns_404(keys_client):
    client, Factory = keys_client
    _make_user(Factory)  # caller
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"other").hexdigest()
    )
    with Factory() as s:
        foreign = UserApiKey(
            user_id=other_id,
            name="foreign",
            key_hash=hashlib.sha256(b"foreign-raw").hexdigest(),
            prefix="rf_foreign",
            revoked=False,
        )
        s.add(foreign)
        s.flush()
        foreign_id = foreign.id
        s.commit()

    resp = client.delete(f"/api/v1/me/api-keys/{foreign_id}", headers=_HEADERS)
    assert resp.status_code == 404, resp.text

    # The foreign key is untouched (never revoked by a non-owner).
    with Factory() as s:
        assert s.get(UserApiKey, foreign_id).revoked is False


def test_revoke_missing_returns_404(keys_client):
    client, Factory = keys_client
    _make_user(Factory)
    resp = client.delete("/api/v1/me/api-keys/does-not-exist", headers=_HEADERS)
    assert resp.status_code == 404, resp.text


# =========================================================================== #
# Integration with base.py auth resolution (revoked key no longer authenticates)
# =========================================================================== #
def test_created_key_authenticates_then_revoked_key_does_not(keys_client):
    """A live personal key resolves to its owner; a revoked one fails auth.

    Exercises ``app.controllers.v1.base.resolve_user_by_api_key`` — the exact
    primitive the auth layer uses to map an ``x-api-key`` to its owning user.
    """
    client, Factory = keys_client
    owner_id = _make_user(Factory)
    created = _create_key(client, name="CI")
    raw = created["key"]

    # Live key -> resolves to the owning user (authenticates).
    with Factory() as s:
        resolved = v1_base.resolve_user_by_api_key(s, raw, request_id="t")
        assert resolved is not None
        assert resolved.id == owner_id
        s.commit()

    # Revoke it via the API.
    del_resp = client.delete(
        f"/api/v1/me/api-keys/{created['id']}", headers=_HEADERS
    )
    assert del_resp.status_code == 200, del_resp.text

    # Revoked key -> no longer authenticates (resolution yields None).
    with Factory() as s:
        assert v1_base.resolve_user_by_api_key(s, raw, request_id="t") is None


def test_unknown_key_does_not_authenticate(keys_client):
    client, Factory = keys_client
    _make_user(Factory)
    with Factory() as s:
        assert (
            v1_base.resolve_user_by_api_key(s, "rf_totally-unknown", request_id="t")
            is None
        )


def test_minted_key_authenticates_via_jobs_resolver(monkeypatch, db_factory):
    """PUBLIC API KEYS end-to-end: a key minted at ``POST /me/api-keys``
    authenticates a SECOND request sent with it as ``x-api-key`` through the
    CANONICAL ``jobs._resolve_user`` path.

    The minted key is stored in ``UserApiKey.key_hash`` — NOT the legacy
    ``User.api_key_hash`` column — so this only succeeds because
    ``_resolve_user`` chains into ``resolve_user_by_api_key`` after the
    ``User.api_key_hash`` miss.
    """
    import app.controllers.v1.jobs as jobs_mod

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

    monkeypatch.setattr(keys_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(jobs_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(keys_mod.router)
    app.include_router(jobs_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    client = TestClient(app)

    owner_id = _make_user(Factory)

    # Mint a personal key (bootstrapped with the owner's legacy static key).
    raw = _create_key(client, name="CI")["key"]
    assert raw.startswith("rf_")

    # SECOND request authenticates with the minted key as x-api-key. It is absent
    # from User.api_key_hash, so a 200 proves the per-user UserApiKey path is wired
    # into the live resolver.
    resp = client.get("/api/v1/me", headers={"x-api-key": raw})
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["user_id"] == owner_id
    assert body["email"] == "owner@example.com"


# =========================================================================== #
# POWER-USER TIER quotas: list surfaces limits + usage; GET /me/api-keys/usage
# =========================================================================== #
def test_list_surfaces_limits_and_current_month_usage(keys_client):
    client, Factory = keys_client
    _make_user(Factory)
    key_id = _create_key(client, name="CI")["id"]

    # Configure per-key limits + seed some current-month usage directly.
    from app.models.db.repositories import ApiKeyUsageRepository
    from app.services import apikey_quota

    period = apikey_quota.current_period_ym()
    with Factory() as s:
        row = s.get(UserApiKey, key_id)
        row.rate_limit_per_min = 120
        row.monthly_quota = 10000
        ApiKeyUsageRepository(s).increment(key_id, period, amount=7)
        s.commit()

    resp = client.get("/api/v1/me/api-keys", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    item = resp.json()["data"][0]
    assert item["rate_limit_per_min"] == 120
    assert item["monthly_quota"] == 10000
    assert item["usage_this_month"] == 7
    # Still never leaks a raw key or hash.
    assert "key" not in item


def test_usage_endpoint_reports_used_and_remaining(keys_client):
    client, Factory = keys_client
    _make_user(Factory)
    key_id = _create_key(client, name="CI")["id"]

    from app.models.db.repositories import ApiKeyUsageRepository
    from app.services import apikey_quota

    period = apikey_quota.current_period_ym()
    with Factory() as s:
        s.get(UserApiKey, key_id).monthly_quota = 100
        ApiKeyUsageRepository(s).increment(key_id, period, amount=30)
        s.commit()

    resp = client.get("/api/v1/me/api-keys/usage", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    row = resp.json()["data"][0]
    assert row["id"] == key_id
    assert row["period_ym"] == period
    assert row["used"] == 30
    assert row["monthly_quota"] == 100
    assert row["remaining"] == 70
    # No secret material anywhere in the usage view.
    assert "key" not in row
    assert "key_hash" not in row


def test_usage_unlimited_key_has_null_remaining(keys_client):
    client, Factory = keys_client
    _make_user(Factory)
    _create_key(client, name="CI")  # NULL monthly_quota => unlimited

    resp = client.get("/api/v1/me/api-keys/usage", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    row = resp.json()["data"][0]
    assert row["monthly_quota"] is None
    assert row["remaining"] is None
    assert row["used"] == 0


def test_usage_is_owner_scoped(keys_client):
    client, Factory = keys_client
    _make_user(Factory)  # caller
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"other").hexdigest()
    )
    with Factory() as s:
        s.add(
            UserApiKey(
                user_id=other_id,
                name="foreign",
                key_hash=hashlib.sha256(b"foreign-raw").hexdigest(),
                prefix="rf_foreign",
                revoked=False,
            )
        )
        s.commit()
    _create_key(client, name="mine")

    resp = client.get("/api/v1/me/api-keys/usage", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    names = {row["name"] for row in resp.json()["data"]}
    assert names == {"mine"}


def test_usage_requires_auth_401(keys_client):
    client, _ = keys_client
    resp = client.get("/api/v1/me/api-keys/usage")
    assert resp.status_code == 401, resp.text
