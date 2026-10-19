"""Tests for POWER-USER TIER per-API-key rate limits + monthly quotas.

Exercises the three layers of the feature against an in-memory SQLite DB (no
Postgres / Redis):

* :class:`ApiKeyUsageRepository` — the monthly counter upserts in place (no
  duplicate rows), reads back via ``get_month``, and stays per-key isolated.
* :mod:`app.services.apikey_quota` — ``check_and_consume`` raises
  :class:`QuotaExceeded` once a set quota is exceeded, never raises when the
  quota is ``None`` (unlimited), and ``enforce_rate_limit`` keeps limiting without
  Redis.
* ``app.controllers.v1.base.resolve_user_by_api_key`` — a resolved key that
  exceeds its quota surfaces an :class:`HttpException` ``429`` (not a swallowed
  ``None``), while the static-app-key / unknown-key paths are unaffected.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.controllers.v1.base as base_mod
from app.models.db.base import Base
from app.models.db.models import ApiKeyUsage, User, UserApiKey
from app.models.db.repositories import ApiKeyUsageRepository, UserApiKeyRepository
from app.models.exception import HttpException
from app.services import apikey_quota

_RAW_KEY = "rf_live_quota_key_value"
_KEY_HASH = hashlib.sha256(_RAW_KEY.encode("utf-8")).hexdigest()
_STATIC_APP_KEY = "static-app-key-xyz"
_PERIOD = "2026-08"


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


@pytest.fixture(autouse=True)
def _fixed_static_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the static app key so static-vs-per-user behavior is deterministic."""
    monkeypatch.setattr(base_mod, "_static_app_key", lambda: _STATIC_APP_KEY)


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the fixed-window limiter on fresh in-process buckets (no Redis).

    The CI box may run a live Redis; pinning the client to ``None`` keeps these
    tests deterministic and never pollutes a shared limiter bucket.
    """
    import app.services.ratelimit as ratelimit_mod

    ratelimit_mod.reset_local_buckets()
    monkeypatch.setattr(ratelimit_mod, "_get_client", lambda: None)


def _seed_key(
    factory: sessionmaker,
    *,
    key_hash: str = _KEY_HASH,
    prefix: str = "rf_qta",
    monthly_quota: int | None = None,
    rate_limit_per_min: int | None = None,
) -> tuple[str, str]:
    """Create a ``User`` + one ``UserApiKey`` with the given limits; return ids."""
    with _session(factory) as s:
        user = User(email=f"{prefix}@example.com", credits=0)
        s.add(user)
        s.flush()
        user_id = user.id
        row = UserApiKeyRepository(s).create(
            user_id=user_id, name="CI", key_hash=key_hash, prefix=prefix
        )
        row.monthly_quota = monthly_quota
        row.rate_limit_per_min = rate_limit_per_min
        s.flush()
        key_id = row.id
    return user_id, key_id


# --------------------------------------------------------------------------- #
# ApiKeyUsageRepository — monthly counter upsert
# --------------------------------------------------------------------------- #
def test_increment_upserts_single_row_no_duplicates(factory: sessionmaker) -> None:
    _, key_id = _seed_key(factory)
    with _session(factory) as s:
        repo = ApiKeyUsageRepository(s)
        assert repo.increment(key_id, _PERIOD) == 1
        assert repo.increment(key_id, _PERIOD) == 2
        assert repo.increment(key_id, _PERIOD) == 3

    # Exactly ONE row exists for (key, month) — the increment upserts in place.
    with _session(factory) as s:
        rows = (
            s.execute(
                select(func.count())
                .select_from(ApiKeyUsage)
                .where(
                    ApiKeyUsage.api_key_id == key_id,
                    ApiKeyUsage.period_ym == _PERIOD,
                )
            ).scalar_one()
        )
        assert rows == 1
        assert ApiKeyUsageRepository(s).get_month(key_id, _PERIOD) == 3


def test_get_month_is_zero_when_no_row(factory: sessionmaker) -> None:
    _, key_id = _seed_key(factory)
    with _session(factory) as s:
        assert ApiKeyUsageRepository(s).get_month(key_id, _PERIOD) == 0


def test_new_month_inserts_a_fresh_row(factory: sessionmaker) -> None:
    _, key_id = _seed_key(factory)
    with _session(factory) as s:
        repo = ApiKeyUsageRepository(s)
        repo.increment(key_id, "2026-08")
        repo.increment(key_id, "2026-09")
        assert repo.get_month(key_id, "2026-08") == 1
        assert repo.get_month(key_id, "2026-09") == 1


def test_increment_is_per_key_isolated(factory: sessionmaker) -> None:
    _, key_a = _seed_key(factory, prefix="rf_a")
    _, key_b = _seed_key(
        factory,
        key_hash=hashlib.sha256(b"other-key").hexdigest(),
        prefix="rf_b",
    )
    with _session(factory) as s:
        repo = ApiKeyUsageRepository(s)
        repo.increment(key_a, _PERIOD)
        repo.increment(key_a, _PERIOD)
        # key_b must be entirely unaffected by key_a's usage.
        assert repo.get_month(key_a, _PERIOD) == 2
        assert repo.get_month(key_b, _PERIOD) == 0


@pytest.mark.parametrize("bad", ["", "   "])
def test_increment_rejects_blank_ids(factory: sessionmaker, bad: str) -> None:
    with _session(factory) as s:
        repo = ApiKeyUsageRepository(s)
        with pytest.raises(ValueError):
            repo.increment(bad, _PERIOD)
        with pytest.raises(ValueError):
            repo.increment("k", bad)


# --------------------------------------------------------------------------- #
# apikey_quota.check_and_consume — monthly quota policy
# --------------------------------------------------------------------------- #
def test_check_and_consume_raises_quota_exceeded(factory: sessionmaker) -> None:
    _, key_id = _seed_key(factory, monthly_quota=2)
    with _session(factory) as s:
        row = s.get(UserApiKey, key_id)
        assert apikey_quota.check_and_consume(s, row, _PERIOD) == 1
        assert apikey_quota.check_and_consume(s, row, _PERIOD) == 2
        with pytest.raises(apikey_quota.QuotaExceeded) as exc_info:
            apikey_quota.check_and_consume(s, row, _PERIOD)
        err = exc_info.value
        assert err.limit == 2
        assert err.used == 3
        assert err.period_ym == _PERIOD
        # QuotaExceeded is an ApiKeyLimitError (the base the API layer maps to 429).
        assert isinstance(err, apikey_quota.ApiKeyLimitError)


def test_check_and_consume_unlimited_when_quota_none(factory: sessionmaker) -> None:
    _, key_id = _seed_key(factory, monthly_quota=None)
    with _session(factory) as s:
        row = s.get(UserApiKey, key_id)
        # Far beyond any default cap — a None quota never rejects, but still counts.
        for expected in range(1, 51):
            assert apikey_quota.check_and_consume(s, row, _PERIOD) == expected
        assert ApiKeyUsageRepository(s).get_month(key_id, _PERIOD) == 50


def test_check_and_consume_zero_quota_blocks_first_request(
    factory: sessionmaker,
) -> None:
    _, key_id = _seed_key(factory, monthly_quota=0)
    with _session(factory) as s:
        row = s.get(UserApiKey, key_id)
        with pytest.raises(apikey_quota.QuotaExceeded):
            apikey_quota.check_and_consume(s, row, _PERIOD)


# --------------------------------------------------------------------------- #
# apikey_quota.enforce_rate_limit — still limits without Redis
# --------------------------------------------------------------------------- #
def test_enforce_rate_limit_still_limits_without_redis(
    factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate "no Redis" by forcing the limiter's client to None (the CI box may
    # have a live Redis). The in-process bucket must keep enforcing the key's
    # per-minute limit: a cache outage never means unlimited calls.
    import app.services.ratelimit as ratelimit_mod

    ratelimit_mod.reset_local_buckets()
    monkeypatch.setattr(ratelimit_mod, "_get_client", lambda: None)

    _, key_id = _seed_key(factory, rate_limit_per_min=1)
    with _session(factory) as s:
        row = s.get(UserApiKey, key_id)
        apikey_quota.enforce_rate_limit(row)
        with pytest.raises(apikey_quota.RateLimitExceeded):
            apikey_quota.enforce_rate_limit(row)


def test_enforce_rate_limit_disabled_for_nonpositive_limit(
    factory: sessionmaker,
) -> None:
    _, key_id = _seed_key(factory, rate_limit_per_min=0)
    with _session(factory) as s:
        row = s.get(UserApiKey, key_id)
        # A non-positive effective limit disables the control entirely.
        apikey_quota.enforce_rate_limit(row)


# --------------------------------------------------------------------------- #
# current_period_ym — deterministic month token
# --------------------------------------------------------------------------- #
def test_current_period_ym_formats_injected_time() -> None:
    moment = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)
    assert apikey_quota.current_period_ym(moment) == "2026-08"


# --------------------------------------------------------------------------- #
# resolve_user_by_api_key — 429 surfaced end-to-end
# --------------------------------------------------------------------------- #
def test_resolve_surfaces_429_when_quota_exceeded(factory: sessionmaker) -> None:
    user_id, _ = _seed_key(factory, monthly_quota=2)
    with _session(factory) as s:
        # First two resolutions consume the quota and return the owning user.
        u1 = base_mod.resolve_user_by_api_key(s, _RAW_KEY, "req-1")
        u2 = base_mod.resolve_user_by_api_key(s, _RAW_KEY, "req-2")
        assert u1 is not None and u1.id == user_id
        assert u2 is not None and u2.id == user_id
        # The third exceeds the quota — a 429 propagates (not swallowed to None).
        with pytest.raises(HttpException) as exc_info:
            base_mod.resolve_user_by_api_key(s, _RAW_KEY, "req-3")
        assert exc_info.value.status_code == 429


def test_resolve_unlimited_key_never_429(factory: sessionmaker) -> None:
    user_id, _ = _seed_key(factory, monthly_quota=None)
    with _session(factory) as s:
        for _ in range(25):
            user = base_mod.resolve_user_by_api_key(s, _RAW_KEY, "req")
            assert user is not None and user.id == user_id


def test_resolve_static_and_unknown_keys_unaffected(factory: sessionmaker) -> None:
    _seed_key(factory, monthly_quota=1)
    with _session(factory) as s:
        # Static app key is not a per-user identity -> None (no quota touched).
        assert base_mod.resolve_user_by_api_key(s, _STATIC_APP_KEY, "req-s") is None
        # Unknown key -> None (never a 429; there is no key row to meter).
        assert base_mod.resolve_user_by_api_key(s, "bogus-key", "req-u") is None
