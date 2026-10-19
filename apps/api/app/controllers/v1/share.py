"""Public Watermarked Share Pages v1 API controller.

Endpoints under ``/api/v1`` that let a creator turn one of THEIR OWN completed
reels into a public, unguessable, revocable share link, and let ANYONE (no auth)
view the resulting watermarked share page:

* ``POST   /jobs/{job_id}/share`` — OWNER-SCOPED create: mint (or return the
  existing active) public link for the caller's own reel. A foreign/missing job
  is a clean ``404``. Returns ``{token, url, ...}``.
* ``DELETE /me/shares/{token}``   — OWNER-SCOPED revoke: flip the caller's own
  live link to revoked (idempotent; a foreign/unknown/already-revoked token is a
  no-op ``{"revoked": False}`` so a caller can never revoke another creator's
  link by guessing its token).
* ``GET    /public/r/{token}``    — **PUBLIC** (NO auth): resolve a live token to
  the SAFE public DTO (title + watermarked preview URL + created_at + sharer
  referral code) and count the view. An unknown/revoked token is a ``404``. This
  route deliberately never calls ``_resolve_user`` so it is reachable without an
  api key; the strict ``SharePublicModel`` guarantees no clean result key /
  user id / financial can leak.

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard behind the single ``base.verify_token`` gate), so both auth paths (Clerk
  JWT + ``x-api-key``) match the rest of the API and this module stays
  import-safe. The public endpoint simply skips ``_resolve_user``.
* **Import-safe optional deps.** The share service is imported inside a guarded
  block; when absent the endpoints degrade to a clean ``503`` at request time
  instead of an ``ImportError`` at startup (mirroring ``ideas.py`` / ``jobs.py``).
* **Clean 4xx over 422.** A service ``ValueError`` (blank/missing job) → ``404``;
  a ``PermissionError`` (foreign job) → ``404`` (indistinguishable from missing so
  a caller can never probe another user's job ids); a ``LookupError`` on the
  public read (unknown/revoked) → ``404``.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`. No secrets are hardcoded.
"""

from __future__ import annotations

from fastapi import Path, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    ShareCreateResponse,
    SharePublicResponse,
    ShareRevokeResponse,
)
from app.services.billing.pro_access import require_pro_action
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded optional import (depends on the DB layer authored by sibling agents;
# may be absent at compile time). Keeping this guarded makes the module
# import-safe: a missing dependency degrades to a clean 503 at request time.
# --------------------------------------------------------------------------- #
try:
    from app.services import share as share_service

    _SHARE_SERVICE_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    share_service = None  # type: ignore[assignment]
    _SHARE_SERVICE_IMPORT_ERROR = exc


router = new_router()

# --------------------------------------------------------------------------- #
# Tunables (config-overridable). Creating/revoking writes a DB row and the public
# view increments a counter, so each is capped per-caller (per-IP for the public
# path) to prevent abuse. The limiter degrades OPEN when Redis is unreachable.
# --------------------------------------------------------------------------- #
_DEFAULT_SHARE_WRITE_RATE_LIMIT: int = 120
_DEFAULT_SHARE_WRITE_RATE_WINDOW_S: int = 3600
# The public view path is unauthenticated (keyed by caller IP) so it gets its own,
# generous limit — enough for real social traffic while blunting a view-count
# inflation loop.
_DEFAULT_SHARE_VIEW_RATE_LIMIT: int = 600
_DEFAULT_SHARE_VIEW_RATE_WINDOW_S: int = 3600


def _share_write_rate_limit() -> int:
    return int(
        config.app.get(
            "reelforge_share_write_rate_limit", _DEFAULT_SHARE_WRITE_RATE_LIMIT
        )
    )


def _share_write_rate_window_s() -> int:
    return int(
        config.app.get(
            "reelforge_share_write_rate_window_s", _DEFAULT_SHARE_WRITE_RATE_WINDOW_S
        )
    )


def _share_view_rate_limit() -> int:
    return int(
        config.app.get(
            "reelforge_share_view_rate_limit", _DEFAULT_SHARE_VIEW_RATE_LIMIT
        )
    )


def _share_view_rate_window_s() -> int:
    return int(
        config.app.get(
            "reelforge_share_view_rate_window_s", _DEFAULT_SHARE_VIEW_RATE_WINDOW_S
        )
    )


def _share_base_url() -> str:
    """Public share-page base URL (``reelforge_share_base_url``), no trailing ``/``.

    Empty when unset — the built ``url`` then falls back to a site-relative
    ``/r/<token>`` so the frontend can resolve it against its own origin. No secret
    is read here.
    """
    return str(config.app.get("reelforge_share_base_url", "") or "").rstrip("/")


def _build_share_url(token: str) -> str:
    """Build the public share-page URL for a token (absolute if a base is set)."""
    base_url = _share_base_url()
    return f"{base_url}/r/{token}" if base_url else f"/r/{token}"


def _require_pro_share(user_id: str, request_id: str) -> None:
    require_pro_action(user_id, request_id, action="share")


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_share(request_id: str) -> None:
    """Raise 503 when the share service could not be imported."""
    if share_service is None:
        logger.error(
            f"share service unavailable, request_id: {request_id}, "
            f"error: {_SHARE_SERVICE_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: share links are not available",
        )


def _share_link_data(link) -> dict:
    """Serialise a ``ShareLink`` row to the owner-facing envelope (with built URL).

    Read every attribute while the row is still attached to its session so a later
    expire-on-commit can never trigger a detached-instance lazy load. The clean
    ``result_key`` is never referenced.
    """
    created_at = getattr(link, "created_at", None)
    return {
        "token": link.token,
        "url": _build_share_url(link.token),
        "job_id": link.job_id,
        "view_count": int(getattr(link, "view_count", 0) or 0),
        "revoked": bool(getattr(link, "revoked", False)),
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


# --------------------------------------------------------------------------- #
# POST /jobs/{job_id}/share  (owner-scoped create)
# --------------------------------------------------------------------------- #
@router.post(
    "/jobs/{job_id}/share",
    response_model=ShareCreateResponse,
    summary="Create a public share link for one of your reels",
)
def create_share_endpoint(
    request: Request,
    job_id: str = Path(..., description="The caller's own job/reel id"),
):
    """Create (or return the existing active) public share link for the caller's reel.

    Owner-scoped: the job must belong to the caller. A foreign/missing job is a
    clean ``404`` (indistinguishable so a caller can never probe another user's
    job ids). Idempotent — one live link per job.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_share(request_id)

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            _require_pro_share(str(user.id), request_id)
            enforce_rate_limit(
                request,
                f"share_create:{user.id}",
                limit=_share_write_rate_limit(),
                window_s=_share_write_rate_window_s(),
            )
            link = share_service.create_share(session, user.id, job_id)
            data = _share_link_data(link)
    except HttpException:
        raise
    except PermissionError:
        # Foreign job — indistinguishable from missing so job ids never leak.
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: job not found",
        )
    except ValueError as exc:
        # Blank/missing job id or job not found -> clean 404.
        raise HttpException(
            task_id=request_id, status_code=404, message=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"failed to create share link, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to create the share link",
        )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# DELETE /me/shares/{token}  (owner-scoped revoke)
# --------------------------------------------------------------------------- #
@router.delete(
    "/me/shares/{token}",
    response_model=ShareRevokeResponse,
    summary="Revoke a public share link you created",
)
def revoke_share_endpoint(
    request: Request,
    token: str = Path(..., description="The share token to revoke"),
):
    """Revoke the caller's own live share link (idempotent).

    Owner-scoped in the service/repository: returns ``{"revoked": True}`` only when
    a live link belonging to the caller was flipped to revoked; a foreign /
    unknown / already-revoked token is a harmless ``{"revoked": False}`` (never a
    404-that-confirms-existence), so a caller can never revoke — or probe — another
    creator's link.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_share(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        revoked = share_service.revoke_share(session, user.id, token)

    return utils.get_response(200, {"revoked": bool(revoked), "token": token})


# --------------------------------------------------------------------------- #
# GET /public/r/{token}  (PUBLIC — no auth)
# --------------------------------------------------------------------------- #
@router.get(
    "/public/r/{token}",
    response_model=SharePublicResponse,
    summary="View a public share page (no auth)",
)
def public_share_endpoint(
    request: Request,
    token: str = Path(..., description="The public share token"),
):
    """Resolve a live token to the SAFE public DTO and count the view (NO auth).

    This endpoint deliberately never resolves a caller, so it is reachable without
    an api key. An unknown/revoked token (or a dangling link whose job was deleted)
    is a clean ``404``. The strict ``SharePublicModel`` response contract
    guarantees only the safe public fields are ever serialised — never the clean
    ``result_key``, the owning ``user_id`` or any private financial.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_share(request_id)

    # Per-IP rate limit (no caller identity on this public path) to blunt a
    # view-count inflation loop. Degrades OPEN without Redis.
    enforce_rate_limit(
        request,
        "share_view",
        limit=_share_view_rate_limit(),
        window_s=_share_view_rate_window_s(),
    )

    try:
        with get_session() as session:
            data = share_service.public_view(session, token)
    except LookupError:
        # Unknown or revoked token -> 404 (a revoked link is invisible + no view
        # is counted).
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: share link not found",
        )
    except Exception as exc:  # noqa: BLE001 - never leak a raw failure publicly
        logger.error(f"failed to render share page, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to load the share page",
        )

    return utils.get_response(200, data)
