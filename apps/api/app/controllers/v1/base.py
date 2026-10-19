"""Shared v1 router factory + caller-resolution helpers.

``new_router`` mounts every ``/api/v1`` route. The auth helpers below extend the
existing caller resolution (the static app key of
``app.controllers.base.verify_token`` and the per-user ``User.api_key_hash``
lookup in ``jobs.py``) with the **PUBLIC API KEYS** feature: a power user mints a
personal ``x-api-key`` whose SHA-256 digest is stored in ``UserApiKey`` and
matched back to the owning ``User`` at request time.

SECURITY
--------
* Only the SHA-256 **digest** of a presented key is ever computed here — the raw
  key is never persisted (it is revealed once at creation by the keys API).
* The static app key is compared in **constant time** (``hmac.compare_digest``)
  so this module never regresses the timing-safety of the existing gate.
* A revoked or unknown key resolves to ``None`` (i.e. still fails auth) exactly
  as before — this path only *adds* a way to authenticate, it never weakens one.

Import-safety
-------------
The persistence layer (SQLAlchemy models / repositories) is authored by sibling
agents and pulled in behind a guarded import (mirroring ``jobs.py``) so merely
importing this module never crashes app startup. When the layer is absent the
per-user resolution simply degrades to "no per-user key matched" (``None``).
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from app.config import config
from app.controllers.base import get_api_key, verify_token
from app.models.exception import HttpException

# --------------------------------------------------------------------------- #
# Guarded persistence-layer import. Keeps this module import-safe: a missing DB
# layer degrades the per-user key path to "no match" instead of an ImportError.
# --------------------------------------------------------------------------- #
try:
    from app.models.db.models import User, UserApiKey
    from app.models.db.repositories import UserApiKeyRepository

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    User = None  # type: ignore[assignment,misc]
    UserApiKey = None  # type: ignore[assignment,misc]
    UserApiKeyRepository = None  # type: ignore[assignment,misc]
    _DB_IMPORT_ERROR = exc


__all__ = [
    "new_router",
    "get_api_key",
    "verify_token",
    "hash_api_key",
    "matches_static_app_key",
    "resolve_user_by_api_key",
]


def new_router(dependencies: list[Any] | None = None) -> APIRouter:
    """Build a ``/api/v1`` router, optionally applying auth dependencies to all routes."""
    router = APIRouter()
    router.tags = ["V1"]
    router.prefix = "/api/v1"
    # Apply the auth dependency (e.g. ``verify_token``) to every mounted route.
    if dependencies:
        router.dependencies = dependencies
    return router


def hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of a raw API key.

    The digest is the only persisted/compared form of a key. ``raw_key`` is
    coerced to ``str`` defensively so a non-string header value can never raise.
    """
    return hashlib.sha256(str(raw_key or "").encode("utf-8")).hexdigest()


def _static_app_key() -> str:
    """The single shared app-level key (``config.app.api_key``); ``""`` when unset."""
    try:
        return str(config.app.get("api_key", "") or "")
    except Exception as exc:  # pragma: no cover - config always bound in practice
        logger.debug(f"unable to read config.app.api_key: {exc}")
        return ""


def matches_static_app_key(raw_key: str | None) -> bool:
    """Constant-time compare a presented key against the static app key.

    Returns ``False`` for a missing header or an unconfigured app key (an empty
    configured key must never match an empty header and grant blanket access).
    Uses ``hmac.compare_digest`` to preserve the timing-safety of the existing
    ``verify_token`` gate.
    """
    expected = _static_app_key()
    if not raw_key or not expected:
        return False
    return hmac.compare_digest(str(raw_key), expected)


def resolve_user_by_api_key(
    session: Any,
    raw_key: str | None,
    request_id: str = "",
) -> Any | None:
    """Resolve a presented ``x-api-key`` to its owning :class:`User`, or ``None``.

    This is the PUBLIC API KEYS extension to caller resolution. It is called for
    an ``x-api-key`` that did **not** match the static app key and is not a Clerk
    JWT; callers keep those existing paths ahead of this one.

    Resolution:

    * A blank header, or a header equal to the static app key, resolves to
      ``None`` (the static-app-key path is handled by ``verify_token`` — it is
      not a per-user identity, so there is no ``User`` to return here).
    * Otherwise the key is hashed (SHA-256) and looked up via
      :meth:`UserApiKeyRepository.get_by_hash`, which only matches a **live**
      (non-revoked) row. On a hit the owning ``User`` is loaded and the key's
      ``last_used_at`` is stamped best-effort (a telemetry failure never breaks
      the authenticated request); the ``User`` is returned.
    * A revoked, unknown, or otherwise unresolvable key resolves to ``None`` so
      it still fails auth exactly as before.

    Never raises for auth purposes — any unexpected error (including a missing DB
    layer) is logged and treated as "no per-user key matched" (``None``), so the
    caller's existing failure path (401) runs unchanged.
    """
    if not raw_key:
        return None
    # The static app key is not a per-user identity — defer to verify_token.
    if matches_static_app_key(raw_key):
        return None
    if UserApiKeyRepository is None or User is None:
        logger.debug(
            f"per-user api key resolution unavailable ({request_id}): "
            f"{_DB_IMPORT_ERROR}"
        )
        return None

    try:
        repo = UserApiKeyRepository(session)
        key_row = repo.get_by_hash(hash_api_key(raw_key))
        if key_row is None:
            return None
        user = session.get(User, key_row.user_id)
        if user is None:
            # Dangling key with no owner — treat as unresolved rather than crash.
            logger.warning(
                f"api key {key_row.id} references missing user "
                f"{key_row.user_id} ({request_id})"
            )
            return None
        # POWER-USER TIER: enforce the key's per-minute rate limit + monthly
        # quota now that it has resolved to a live UserApiKey. A breach raises
        # HttpException(429) which propagates (see the re-raise below) rather than
        # degrading to "no match"; the static-app-key and Clerk JWT paths never
        # reach here so they stay unchanged.
        _enforce_key_limits(session, key_row, request_id)
        # Best-effort last-used telemetry; never let it break the request.
        repo.touch_last_used(key_row.id)
        return user
    except HttpException:
        # A 429 (rate-limit / quota) is a real, caller-facing outcome — surface it
        # instead of swallowing it into a "no per-user key matched" (401).
        raise
    except Exception as exc:  # noqa: BLE001 - auth must never 500 on lookup failure
        logger.warning(f"per-user api key resolution failed ({request_id}): {exc}")
        return None


def _enforce_key_limits(session: Any, key_row: Any, request_id: str) -> None:
    """Enforce a resolved key's rate limit + monthly quota, or raise HTTP 429.

    Delegates the policy to :mod:`app.services.apikey_quota` (pure + testable) and
    maps a typed :class:`~app.services.apikey_quota.ApiKeyLimitError` breach to an
    :class:`HttpException` ``429`` carrying a clear message. Import-safe and
    degrade-OPEN: if the quota service is unavailable the request is allowed
    through (mirroring the rate limiter's fail-open stance) rather than blocking
    authenticated traffic.
    """
    try:
        from app.services import apikey_quota
    except Exception as exc:  # pragma: no cover - service is a first-party module
        logger.debug(
            f"api key quota enforcement unavailable ({request_id}): {exc}"
        )
        return

    try:
        apikey_quota.enforce_rate_limit(key_row)
        apikey_quota.check_and_consume(
            session, key_row, apikey_quota.current_period_ym()
        )
    except apikey_quota.ApiKeyLimitError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=429,
            message=f"{request_id}: {exc}",
        ) from exc


def resolve_user_from_request(
    request: Request,
    session: Any,
    request_id: str = "",
) -> Any | None:
    """Convenience wrapper: read ``x-api-key`` off ``request`` and resolve a User.

    Returns the owning :class:`User` for a valid per-user key, else ``None`` (so
    the caller falls through to its existing static-app-key / Clerk / 401 paths).
    """
    return resolve_user_by_api_key(session, get_api_key(request), request_id)
