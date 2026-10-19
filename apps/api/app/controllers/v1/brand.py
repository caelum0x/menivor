"""ReelForge Brand Watermark API (per-user logo overlay settings).

A creator uploads a transparent PNG logo (via the EXISTING
``POST /api/v1/uploads/presign`` image/png flow, stored in R2) which the
pure-FFmpeg compose stage overlays onto their reels at a chosen corner +
opacity. This module exposes the two creator-scoped endpoints that read and
update that per-user :class:`~app.models.db.models.UserBrand` singleton, served
under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`:

* ``GET  /me/brand`` — the caller's brand settings (the model defaults when the
  creator has never configured one) plus a short-lived presigned GET URL for the
  stored logo when a ``logo_key`` is set.
* ``PUT  /me/brand`` — validate + upsert the caller's settings. ``position``
  must be a known corner and ``opacity`` must be in ``[0.0, 1.0]`` (both ``400``
  otherwise). A supplied ``logo_key`` MUST reference an upload the caller owns —
  ownership is verified against the caller-scoped :class:`Asset` registry
  (``403`` for a foreign/unknown key), so one creator can never point their
  watermark at another creator's object. Passing ``logo_key=""`` clears the logo.

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard), so the two auth paths (Clerk JWT + ``x-api-key``) and the get-or-create
  behaviour are identical to the rest of the API and this module stays import-safe.
* **Import-safe DB deps.** The persistence models/repositories authored by the DB
  agent (:class:`UserBrand` / ``UserBrandRepository`` / :class:`Asset`) are
  imported optionally; when absent every endpoint degrades to a clean ``503``.
* **Owner-scoped, fail-closed.** The ownership (BOLA) guard fails closed with a
  ``503`` when the :class:`Asset` model is unavailable rather than skipping the
  check, mirroring ``voices.clone``.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these are ``None`` and
# ``_require_db`` raises a clean 503 at request time.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import BrandRequest, BrandResponse
from app.utils import utils

router = new_router()


# --------------------------------------------------------------------------- #
# Guarded brand persistence layer (authored by the sibling DB agent; may be
# absent at compile time). Keeps this module import-safe — a missing layer
# degrades to a clean 503 at request time (via ``_require_brand``) instead of an
# ImportError at startup, mirroring the guard in ``jobs.py``. The watermark
# validation constants + defaults are re-imported when available and otherwise
# fall back to values matching the ``UserBrand`` column defaults.
# --------------------------------------------------------------------------- #
try:
    from app.models.db.models import Asset, UserBrand  # noqa: F401 (re-exported for tests)
    from app.models.db.repositories import (
        WATERMARK_DEFAULT_POSITION,
        WATERMARK_OPACITY_MAX,
        WATERMARK_OPACITY_MIN,
        WATERMARK_POSITIONS,
        UserBrandRepository,
    )

    _BRAND_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    Asset = None  # type: ignore[assignment,misc]
    UserBrand = None  # type: ignore[assignment,misc]
    UserBrandRepository = None  # type: ignore[assignment,misc]
    WATERMARK_DEFAULT_POSITION = "bottom_right"  # type: ignore[assignment]
    WATERMARK_OPACITY_MIN = 0.0  # type: ignore[assignment]
    WATERMARK_OPACITY_MAX = 1.0  # type: ignore[assignment]
    WATERMARK_POSITIONS = frozenset(  # type: ignore[assignment]
        {"bottom_right", "bottom_left", "top_right", "top_left"}
    )
    _BRAND_IMPORT_ERROR = exc


# Defaults returned by ``GET /me/brand`` when the caller has never configured a
# brand. Kept in sync with the ``UserBrand`` column defaults so an unconfigured
# creator still receives a sensible, enabled watermark shape (a blank
# ``logo_key`` means "no watermark" even while ``enabled`` is True).
_DEFAULT_OPACITY: float = 0.85
_DEFAULT_ENABLED: bool = True


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_brand(request_id: str) -> None:
    """Raise 503 when the brand persistence layer is unavailable."""
    if _BRAND_IMPORT_ERROR is not None or UserBrandRepository is None:
        logger.error(
            f"brand persistence unavailable, request_id: {request_id}, "
            f"error: {_BRAND_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: brand storage is not available",
        )


def _presign_logo(logo_key: str, request_id: str) -> Optional[str]:
    """Return a presigned GET URL for the logo, or ``None`` on any failure.

    Best-effort: a storage/config hiccup must never fail the brand read, so a
    presign error is logged and the URL is simply omitted (mirroring the
    ``result_url`` presign in ``jobs.py``).
    """
    try:
        from app.services.storage.r2 import get_r2_client

        return get_r2_client().presign_get(logo_key)
    except Exception as exc:  # noqa: BLE001 - presign is best-effort
        logger.warning(
            f"failed to presign brand logo {logo_key!r}, "
            f"request_id: {request_id}: {exc}"
        )
        return None


def _brand_public_data(brand: Any, request_id: str) -> dict:
    """Serialise a ``UserBrand`` row (or the defaults when ``None``) to the envelope.

    Adds a presigned ``logo_url`` only when a non-empty ``logo_key`` is set.
    """
    if brand is None:
        logo_key = ""
        position = str(WATERMARK_DEFAULT_POSITION)
        opacity = _DEFAULT_OPACITY
        enabled = _DEFAULT_ENABLED
        updated_at = None
    else:
        logo_key = str(getattr(brand, "logo_key", "") or "")
        position = str(getattr(brand, "position", WATERMARK_DEFAULT_POSITION))
        opacity = float(getattr(brand, "opacity", _DEFAULT_OPACITY))
        enabled = bool(getattr(brand, "enabled", _DEFAULT_ENABLED))
        updated_at = getattr(brand, "updated_at", None)

    data: dict[str, Any] = {
        "logo_key": logo_key,
        "position": position,
        "opacity": opacity,
        "enabled": enabled,
        "logo_url": _presign_logo(logo_key, request_id) if logo_key else None,
        "updated_at": updated_at.isoformat() if updated_at is not None else None,
    }
    return data


def _verify_logo_ownership(
    session: Any, user_id: str, logo_key: str, request_id: str
) -> None:
    """Enforce that ``logo_key`` is an upload owned by the caller (BOLA guard).

    Uploads are registered as caller-scoped :class:`Asset` rows (``r2_key`` +
    ``user_id``); a ``logo_key`` that does not match one the caller owns is a
    ``403`` so a creator can never watermark with another creator's object.

    Fails **closed** with a ``503`` when the :class:`Asset` model is unavailable
    (the ownership check cannot run), rather than silently trusting the key.
    """
    if Asset is None:  # pragma: no cover - exercised only before the DB layer
        logger.error(
            f"asset registry unavailable, cannot verify logo ownership, "
            f"request_id: {request_id}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: upload ownership cannot be verified",
        )

    owned = (
        session.query(Asset)
        .filter(Asset.r2_key == logo_key, Asset.user_id == user_id)
        .first()
    )
    if owned is None:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: logo_key does not belong to the caller",
        )


def _validate_position(position: Optional[str], request_id: str) -> Optional[str]:
    """Normalise + validate an overlay corner (``400`` when unknown)."""
    if position is None:
        return None
    normalized = str(position).strip().lower()
    if normalized not in WATERMARK_POSITIONS:
        allowed = ", ".join(sorted(WATERMARK_POSITIONS))
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: position must be one of: {allowed}",
        )
    return normalized


def _validate_opacity(opacity: Optional[float], request_id: str) -> Optional[float]:
    """Validate an overlay opacity is a number in ``[0.0, 1.0]`` (``400`` otherwise)."""
    if opacity is None:
        return None
    try:
        value = float(opacity)
    except (TypeError, ValueError):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: opacity must be a number in [0.0, 1.0]",
        )
    if value < WATERMARK_OPACITY_MIN or value > WATERMARK_OPACITY_MAX:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: opacity must be in "
                f"[{WATERMARK_OPACITY_MIN}, {WATERMARK_OPACITY_MAX}]"
            ),
        )
    return value


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get(
    "/me/brand",
    response_model=BrandResponse,
    summary="Get the caller's brand watermark settings",
)
def get_brand(request: Request):
    """Return the caller's brand settings (the defaults when none is set).

    When a ``logo_key`` is configured the payload also carries a short-lived
    presigned ``logo_url`` so the client can preview the uploaded logo.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_brand(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        brand = UserBrandRepository(session).get(user.id)
        data = _brand_public_data(brand, request_id)
    return utils.get_response(200, data)


@router.put(
    "/me/brand",
    response_model=BrandResponse,
    summary="Update the caller's brand watermark settings",
)
def put_brand(request: Request, body: BrandRequest):
    """Validate + upsert the caller's brand watermark settings.

    ``position`` must be a known corner and ``opacity`` must be in ``[0.0, 1.0]``
    (both ``400`` otherwise). A supplied non-empty ``logo_key`` must reference an
    upload the caller owns (``403`` otherwise); ``logo_key=""`` clears the logo.
    Omitted (``None``) fields leave the stored value untouched.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_brand(request_id)

    # Validate at the boundary BEFORE any DB work so a bad payload is a clean 400.
    position = _validate_position(body.position, request_id)
    opacity = _validate_opacity(body.opacity, request_id)
    logo_key = None if body.logo_key is None else str(body.logo_key).strip()

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)

            # Ownership is enforced only when a NON-EMPTY key is supplied; an
            # empty string is an explicit "clear the logo" and needs no owner.
            if logo_key:
                _verify_logo_ownership(session, user.id, logo_key, request_id)

            brand = UserBrandRepository(session).upsert(
                user.id,
                logo_key=logo_key,
                position=position,
                opacity=opacity,
                enabled=body.enabled,
            )
            data = _brand_public_data(brand, request_id)
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"upsert brand failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to save brand settings",
        )
    return utils.get_response(200, data)
