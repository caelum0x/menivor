"""Personal API keys v1 API controller (PUBLIC API KEYS feature).

Auth-gated, strictly owner-scoped endpoints under ``/api/v1`` that let a power
user mint, list, and revoke personal API keys for programmatic access to the
REST API. A minted key is used as the ``x-api-key`` header (in addition to the
Clerk JWT and the static app key) and is resolved back to its owning ``User``
at request time by :func:`app.controllers.v1.base.resolve_user_by_api_key`.

* ``POST   /me/api-keys``      — mint a cryptographically-random key; return the
  FULL raw secret **once** (unrecoverable afterwards).
* ``GET    /me/api-keys``      — list the caller's keys (never the raw key/hash).
* ``DELETE /me/api-keys/{id}`` — soft-revoke one of the caller's keys.

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard block behind the shared ``base.verify_token`` gate), so both auth paths
  (Clerk JWT + ``x-api-key``) and the get-or-create behaviour match the rest of
  the API and this module stays import-safe.
* **SECURITY — hashes only.** The raw key is generated server-side
  (``'rf_' + secrets.token_urlsafe(...)``) and only its SHA-256 digest plus a
  short, non-secret ``prefix`` are persisted. The raw value is revealed exactly
  once at creation and is thereafter unrecoverable. No secrets are hardcoded.
* **Strictly owner-scoped.** Every read/mutation runs through
  :class:`UserApiKeyRepository`, which filters on the caller's ``user_id`` — a
  caller can never list or revoke another user's key, and a guessed id is a
  ``404`` (indistinguishable from a missing row).
* **Import-safe optional deps.** The repository (authored by the sibling DB
  agent) is imported inside a guarded block; when absent the endpoints degrade
  to a clean ``503`` at request time instead of an ``ImportError`` at startup
  (mirroring ``jobs.py`` / ``notifications.py``).
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1 import base as v1_base
from app.controllers.v1.base import new_router

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these are ``None`` and
# ``_require_db`` raises a clean 503 at request time.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyUsageResponse,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded optional import (authored by the sibling DB agent; may be absent at
# compile time). Keeping it guarded makes the module import-safe: a missing
# dependency degrades to a clean 503 at request time.
# --------------------------------------------------------------------------- #
try:
    from app.models.db.repositories import ApiKeyUsageRepository, UserApiKeyRepository

    _API_KEYS_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    ApiKeyUsageRepository = None  # type: ignore[assignment,misc]
    UserApiKeyRepository = None  # type: ignore[assignment,misc]
    _API_KEYS_IMPORT_ERROR = exc


router = new_router()

# --------------------------------------------------------------------------- #
# Tunables (config-overridable).
# --------------------------------------------------------------------------- #
# Raw key layout: a fixed, recognisable prefix + a URL-safe random secret. 32
# random bytes (~256 bits) is comfortably beyond brute-force reach.
_KEY_PREFIX: str = "rf_"
_TOKEN_BYTES: int = 32
# Length (chars) of the non-secret display prefix persisted for a key. Kept well
# under the model's ``prefix`` column width (16) and short enough to leak no
# usable secret material while still letting a user recognise the key.
_PREFIX_LEN: int = 12
# Max label length (matches the model / request schema cap).
_MAX_NAME_LEN: int = 200
# Cap the number of *active* (non-revoked) keys a single user may hold so an
# account cannot mint an unbounded number of live credentials.
_DEFAULT_MAX_ACTIVE_KEYS: int = 20


def _require_api_keys(request_id: str) -> None:
    """Raise 503 when the API-key persistence layer is unavailable."""
    if _API_KEYS_IMPORT_ERROR is not None or UserApiKeyRepository is None:
        logger.error(
            f"api-key persistence unavailable, request_id: {request_id}, "
            f"error: {_API_KEYS_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: api key storage is not available",
        )


def _max_active_keys() -> int:
    """Max active keys per user (config ``reelforge_max_api_keys``)."""
    try:
        return max(1, int(config.app.get("reelforge_max_api_keys", _DEFAULT_MAX_ACTIVE_KEYS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_ACTIVE_KEYS


def _clean_name(raw_name: Any, request_id: str) -> str:
    """Validate + normalise a caller-supplied key name (400 on empty)."""
    name = str(raw_name or "").strip()
    if not name:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: name is required",
        )
    return name[:_MAX_NAME_LEN]


def _generate_raw_key() -> str:
    """Return a fresh cryptographically-random raw API key (never persisted).

    ``secrets.token_urlsafe`` yields a URL-safe, header-safe secret; the fixed
    ``rf_`` prefix makes a leaked key recognisable in logs/config for rotation.
    """
    return f"{_KEY_PREFIX}{secrets.token_urlsafe(_TOKEN_BYTES)}"


def _current_period_ym() -> str:
    """Return the current ``'YYYY-MM'`` month token (delegates to the quota service).

    Import-safe: if the quota service is unavailable it falls back to computing the
    UTC month directly, so a usage read never 500s on a missing optional module.
    """
    try:
        from app.services import apikey_quota

        return apikey_quota.current_period_ym()
    except Exception as exc:  # noqa: BLE001 - degrade to a direct UTC month
        logger.debug(f"apikey_quota unavailable for period token: {exc}")
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).strftime("%Y-%m")


def _month_usage(session: Any, key_id: str, period_ym: str) -> int:
    """Best-effort current-month request count for a key (0 on any failure).

    Reads the ``api_key_usage`` counter via :class:`ApiKeyUsageRepository`. A
    missing repository or read error degrades to ``0`` so the list/usage views
    never fail just because usage telemetry is unavailable.
    """
    if ApiKeyUsageRepository is None:
        return 0
    try:
        return int(ApiKeyUsageRepository(session).get_month(key_id, period_ym))
    except Exception as exc:  # noqa: BLE001 - usage telemetry is best-effort
        logger.debug(f"failed to read month usage for api key {key_id}: {exc}")
        return 0


def _key_public_data(row: Any, usage_this_month: int = 0) -> dict:
    """Serialise a ``UserApiKey`` row to its public, caller-scoped envelope.

    NEVER includes the raw key or the full hash — only the id, label, non-secret
    ``prefix``, lifecycle metadata, the per-key limits (``rate_limit_per_min`` /
    ``monthly_quota``; both nullable) and the ``usage_this_month`` request count
    consumed by the key in the current calendar month.
    """
    created_at = getattr(row, "created_at", None)
    last_used_at = getattr(row, "last_used_at", None)
    return {
        "id": row.id,
        "name": getattr(row, "name", "") or "",
        "prefix": getattr(row, "prefix", "") or "",
        "last_used_at": last_used_at.isoformat() if last_used_at is not None else None,
        "revoked": bool(getattr(row, "revoked", False)),
        "created_at": created_at.isoformat() if created_at is not None else None,
        "rate_limit_per_min": getattr(row, "rate_limit_per_min", None),
        "monthly_quota": getattr(row, "monthly_quota", None),
        "usage_this_month": int(usage_this_month or 0),
    }


# --------------------------------------------------------------------------- #
# POST /me/api-keys  (mint a key — one-time raw reveal)
# --------------------------------------------------------------------------- #
@router.post(
    "/me/api-keys",
    response_model=ApiKeyCreatedResponse,
    summary="Mint a personal API key (the raw key is revealed exactly once)",
)
def create_api_key(request: Request, body: ApiKeyCreateRequest):
    """Generate a personal API key and return the FULL raw secret **once**.

    The raw key is generated server-side and only its SHA-256 digest + a short
    non-secret ``prefix`` are stored — the raw value is unrecoverable afterwards
    (documented in the response schema). Owner-scoped: the key is attributed to
    the resolved caller. A per-user active-key cap prevents unbounded minting.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_api_keys(request_id)

    name = _clean_name(getattr(body, "name", ""), request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = UserApiKeyRepository(session)

        active = [k for k in repo.list_for_user(user.id) if not bool(getattr(k, "revoked", False))]
        if len(active) >= _max_active_keys():
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=(
                    f"{request_id}: active api key limit reached "
                    f"({_max_active_keys()}); revoke an existing key first"
                ),
            )

        raw_key = _generate_raw_key()
        key_hash = v1_base.hash_api_key(raw_key)
        prefix = raw_key[:_PREFIX_LEN]

        row = repo.create(
            user_id=user.id, name=name, key_hash=key_hash, prefix=prefix
        )
        data = {
            "id": row.id,
            "name": row.name,
            # The ONLY time the raw key ever leaves the server. Unrecoverable
            # afterwards — only ``key_hash`` (never returned) is persisted.
            "key": raw_key,
            "prefix": row.prefix,
            "created_at": row.created_at.isoformat()
            if getattr(row, "created_at", None) is not None
            else None,
        }

    logger.info(f"minted api key {data['id']} for user {user.id} ({request_id})")
    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /me/api-keys  (list — never the raw key/hash)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/api-keys",
    response_model=ApiKeyListResponse,
    summary="List the caller's API keys (never the raw key or hash)",
)
def list_api_keys(request: Request):
    """Return the caller's keys (newest first), active and revoked.

    Strictly owner-scoped — only the caller's own keys are returned. The raw key
    and full hash are never included; only the id, label, non-secret ``prefix``,
    and lifecycle metadata are exposed.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_api_keys(request_id)

    period_ym = _current_period_ym()
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = UserApiKeyRepository(session).list_for_user(user.id)
        data = [
            _key_public_data(r, _month_usage(session, r.id, period_ym))
            for r in rows
        ]

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /me/api-keys/usage  (current-month usage + limits, caller-scoped)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/api-keys/usage",
    response_model=ApiKeyUsageResponse,
    summary="Current-month usage + limits for the caller's API keys",
)
def api_keys_usage(request: Request):
    """Return each of the caller's keys with its current-month request usage.

    Strictly owner-scoped — only the caller's own keys are reported. For each key
    the current calendar month's request ``used`` count is read from the
    ``api_key_usage`` counter, alongside the key's ``rate_limit_per_min`` /
    ``monthly_quota`` limits and the ``remaining`` monthly allowance (``null`` for
    an unlimited key). No raw key or hash is ever exposed.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_api_keys(request_id)

    period_ym = _current_period_ym()
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = UserApiKeyRepository(session).list_for_user(user.id)
        data = []
        for row in rows:
            used = _month_usage(session, row.id, period_ym)
            quota = getattr(row, "monthly_quota", None)
            remaining = None if quota is None else max(0, int(quota) - used)
            data.append(
                {
                    "id": row.id,
                    "name": getattr(row, "name", "") or "",
                    "prefix": getattr(row, "prefix", "") or "",
                    "period_ym": period_ym,
                    "used": used,
                    "rate_limit_per_min": getattr(row, "rate_limit_per_min", None),
                    "monthly_quota": quota,
                    "remaining": remaining,
                }
            )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# DELETE /me/api-keys/{key_id}  (revoke — ownership enforced)
# --------------------------------------------------------------------------- #
@router.delete(
    "/me/api-keys/{key_id}",
    summary="Revoke one of the caller's API keys",
)
def revoke_api_key(
    request: Request,
    key_id: str = Path(..., description="API key ID"),
):
    """Soft-revoke one of the caller's keys. Returns ``404`` for a foreign/missing id.

    Ownership is enforced in the repository (``revoke`` filters on the caller's
    ``user_id``): a key that does not belong to the caller is indistinguishable
    from a missing one, so a guessed id can neither revoke — nor confirm the
    existence of — another user's key. A revoked key can no longer authenticate
    (``get_by_hash`` excludes revoked rows). Double-revoke is a ``404`` no-op.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_api_keys(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        revoked = UserApiKeyRepository(session).revoke(key_id, user.id)
        if not revoked:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: api key not found",
            )

    return utils.get_response(200, {"id": key_id, "revoked": True})
