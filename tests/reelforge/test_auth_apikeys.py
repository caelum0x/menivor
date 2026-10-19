"""Auth tests for PUBLIC API KEYS caller resolution.

Exercises the per-user ``x-api-key`` extension added to
``app.controllers.v1.base`` against an in-memory SQLite DB (no Postgres):

* a valid, live per-user key resolves to its owning ``User`` (and stamps
  ``last_used_at``);
* a revoked key is rejected (resolves to ``None``);
* the static app key and a random/unknown key behave as before (``None`` — they
  are not per-user identities, so the caller's existing paths handle them);
* ``matches_static_app_key`` stays constant-time-correct and never grants
  blanket access for an empty configured key / empty header.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.controllers.v1.base as base_mod
from app.models.db.base import Base
from app.models.db.models import User, UserApiKey
from app.models.db.repositories import UserApiKeyRepository

_RAW_KEY = "rf_live_secret_key_value"
_KEY_HASH = hashlib.sha256(_RAW_KEY.encode("utf-8")).hexdigest()
_STATIC_APP_KEY = "static-app-key-xyz"


@pytest.fixture()
def factory() -> Iterator[sessionmaker]:
    """In-memory SQLite session factory with the ORM schema created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    engine.dispose()


@contextmanager
def _session(factory: sessionmaker) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _seed_user_with_key(
    factory: sessionmaker, *, revoked: bool = False
) -> tuple[str, str]:
    """Create a ``User`` + one ``UserApiKey`` (optionally revoked); return ids."""
    with _session(factory) as s:
        user = User(email="power@example.com", credits=0)
        s.add(user)
        s.flush()
        user_id = user.id
        repo = UserApiKeyRepository(s)
        key = repo.create(
            user_id=user_id, name="CI", key_hash=_KEY_HASH, prefix="rf_live"
        )
        key_id = key.id
        if revoked:
            assert repo.revoke(key_id, user_id) is True
    return user_id, key_id


@pytest.fixture(autouse=True)
def _fixed_static_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the static app key so static-vs-per-user behavior is deterministic."""
    monkeypatch.setattr(base_mod, "_static_app_key", lambda: _STATIC_APP_KEY)


# --------------------------------------------------------------------------- #
# Per-user key resolution
# --------------------------------------------------------------------------- #
def test_valid_per_user_key_resolves_to_owner(factory: sessionmaker) -> None:
    user_id, key_id = _seed_user_with_key(factory)
    with _session(factory) as s:
        user = base_mod.resolve_user_by_api_key(s, _RAW_KEY, "req-1")
        assert user is not None
        assert user.id == user_id

    # last_used_at is stamped best-effort on a successful resolution.
    with _session(factory) as s:
        refreshed = s.get(UserApiKey, key_id)
        assert refreshed is not None
        assert refreshed.last_used_at is not None


def test_resolve_from_request_reads_x_api_key_header(factory: sessionmaker) -> None:
    user_id, _ = _seed_user_with_key(factory)

    class _Req:
        headers = {"x-api-key": _RAW_KEY}

    with _session(factory) as s:
        user = base_mod.resolve_user_from_request(_Req(), s, "req-hdr")
        assert user is not None
        assert user.id == user_id


def test_revoked_key_is_rejected(factory: sessionmaker) -> None:
    _seed_user_with_key(factory, revoked=True)
    with _session(factory) as s:
        assert base_mod.resolve_user_by_api_key(s, _RAW_KEY, "req-2") is None


def test_static_app_key_resolves_to_no_user(factory: sessionmaker) -> None:
    # The static app key authenticates via verify_token, not as a per-user
    # identity, so per-user resolution must yield None (behavior unchanged).
    _seed_user_with_key(factory)
    with _session(factory) as s:
        assert base_mod.resolve_user_by_api_key(s, _STATIC_APP_KEY, "req-3") is None


def test_random_unknown_key_resolves_to_no_user(factory: sessionmaker) -> None:
    _seed_user_with_key(factory)
    with _session(factory) as s:
        assert (
            base_mod.resolve_user_by_api_key(s, "totally-bogus-key", "req-4") is None
        )


@pytest.mark.parametrize("empty", [None, ""])
def test_missing_key_resolves_to_no_user(
    factory: sessionmaker, empty: str | None
) -> None:
    with _session(factory) as s:
        assert base_mod.resolve_user_by_api_key(s, empty, "req-5") is None


def test_dangling_key_without_owner_resolves_to_none(
    factory: sessionmaker,
) -> None:
    # A key row whose user no longer exists must not crash — it resolves to None.
    with _session(factory) as s:
        UserApiKeyRepository(s).create(
            user_id="missing-user-id",
            name="orphan",
            key_hash=_KEY_HASH,
            prefix="rf_live",
        )
    with _session(factory) as s:
        assert base_mod.resolve_user_by_api_key(s, _RAW_KEY, "req-6") is None


# --------------------------------------------------------------------------- #
# Static-key constant-time comparison
# --------------------------------------------------------------------------- #
def test_matches_static_app_key_true_only_for_exact_match() -> None:
    assert base_mod.matches_static_app_key(_STATIC_APP_KEY) is True
    assert base_mod.matches_static_app_key("wrong") is False


@pytest.mark.parametrize("value", [None, ""])
def test_matches_static_app_key_rejects_empty(value: str | None) -> None:
    assert base_mod.matches_static_app_key(value) is False


def test_empty_configured_static_key_never_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured (empty) app key must never match an empty header and grant
    # blanket access.
    monkeypatch.setattr(base_mod, "_static_app_key", lambda: "")
    assert base_mod.matches_static_app_key("") is False
    assert base_mod.matches_static_app_key("anything") is False


def test_hash_api_key_is_sha256_hex() -> None:
    assert base_mod.hash_api_key(_RAW_KEY) == _KEY_HASH
    assert len(base_mod.hash_api_key("x")) == 64
