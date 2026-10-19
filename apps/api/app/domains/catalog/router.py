"""Catalog HTTP domain — reviewed model/profile browse + generation quote.

Routes served under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`.
Every response uses the MPT envelope ``utils.get_response(status, data, message)``
and every error is raised as :class:`HttpException`. The persistence layer is
imported behind a guarded block (mirroring the reels/media domains) so importing
this module never crashes app startup; a clean ``503`` is returned when the DB
layer is absent.

Endpoints (PROVIDER_MARKETPLACE_PLAN.md §4.3):
* ``GET  /catalog/models``             list reviewed model listings
* ``GET  /catalog/models/{model_id}``  one listing + provider + active price
* ``GET  /catalog/profiles``           curated + caller-owned generation profiles
* ``POST /catalog/quotes/generation``  signed, versioned price snapshot
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

from .schemas import GenerationQuoteRequest

# --------------------------------------------------------------------------- #
# Guarded persistence-layer import — a missing DB layer degrades to a clean 503
# at request time instead of an ImportError at startup.
# --------------------------------------------------------------------------- #
try:
    from app.core.auth import resolve_principal
    from app.domains.catalog.service import CatalogError, CatalogService
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    CatalogError = Exception  # type: ignore[assignment,misc]
    CatalogService = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


def _require_db(request_id: str) -> None:
    """Raise 503 when the persistence layer could not be imported."""
    if _DB_IMPORT_ERROR is not None or get_session is None or CatalogService is None:
        logger.error(
            f"catalog persistence unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    """Resolve the authenticated principal (Clerk JWT or ``x-api-key``)."""
    return resolve_principal(request, session, request_id)


def _map_catalog_error(exc: Exception, request_id: str) -> HttpException:
    """Translate a :class:`CatalogError` into the shared HTTP envelope."""
    status_code = int(getattr(exc, "status_code", 400) or 400)
    message = str(getattr(exc, "message", "") or "invalid catalog request")
    return HttpException(
        task_id=request_id, status_code=status_code, message=f"{request_id}: {message}"
    )


@router.get("/catalog/models", summary="Browse reviewed model listings")
def list_catalog_models(
    request: Request,
    capability: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List reviewed model listings, optionally filtered by ``capability``.

    Only live (non-shadow) listings are returned. Public model discovery does
    not require a resolved user, but the shared token gate still applies.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    capability = (capability or "").strip() or None
    with get_session() as session:
        service = CatalogService(session)
        models = service.browse_models(
            capability=capability, limit=limit, offset=offset
        )
    return utils.get_response(200, {"models": models})


@router.get("/catalog/models/compare", summary="Compare models by price + health")
def compare_models(request: Request, capability: str, sort: str = "price"):
    """Model listings for a capability enriched with provider health, sorted.

    Declared BEFORE the ``/catalog/models/{model_id:path}`` route so the greedy
    path converter never captures ``compare``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    capability = (capability or "").strip()
    sort = "latency" if str(sort).strip() == "latency" else "price"
    with get_session() as session:
        service = CatalogService(session)
        rows = service.compare_models(capability=capability, sort=sort)
    return utils.get_response(200, {"models": rows, "sort": sort})


@router.get("/catalog/models/{model_id:path}", summary="Get one model listing")
def get_catalog_model(
    request: Request, model_id: str = Path(..., description="Catalog model_id")
):
    """Return one reviewed listing with provider + active price; 404 if unknown."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        service = CatalogService(session)
        try:
            data = service.get_model_detail(model_id)
        except CatalogError as exc:
            raise _map_catalog_error(exc, request_id) from exc
    return utils.get_response(200, data)


@router.get("/catalog/motion-presets", summary="Camera-motion presets")
def motion_presets(request: Request):
    """List one-click camera-motion presets (dolly/crane/crash-zoom/FPV…)."""
    request_id = base.get_task_id(request)
    from app.domains.catalog.presets import CAMERA_MOTIONS

    _ = request_id
    return utils.get_response(200, {"camera_motions": CAMERA_MOTIONS})


@router.get("/catalog/vfx-presets", summary="VFX presets (Effects Mix)")
def vfx_presets(request: Request):
    """List stackable cinematic VFX presets (Effects Mix)."""
    from app.domains.catalog.presets import MAX_EFFECTS_STACK, VFX_PRESETS

    return utils.get_response(
        200, {"vfx": VFX_PRESETS, "max_stack": MAX_EFFECTS_STACK}
    )


@router.get("/catalog/providers/health", summary="Provider health / uptime status")
def provider_health(request: Request, window_h: int = 24):
    """Public provider status: uptime %, avg latency, and state per provider."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    window_h = max(1, min(720, int(window_h)))
    with get_session() as session:
        from app.domains.catalog.health import ProviderHealthService

        providers = ProviderHealthService(session).status(window_h=window_h)
    return utils.get_response(200, {"providers": providers, "window_h": window_h})


@router.get("/catalog/profiles", summary="List generation profiles")
def list_generation_profiles(request: Request, workspace_id: str | None = None):
    """List curated + caller-owned active generation profiles."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    workspace_id = (workspace_id or "").strip() or None
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        service = CatalogService(session)
        profiles = service.browse_profiles(
            user_id=getattr(user, "id", None), workspace_id=workspace_id
        )
    return utils.get_response(200, {"profiles": profiles})


@router.post("/catalog/quotes/generation", summary="Quote a generation")
def quote_generation(request: Request, body: GenerationQuoteRequest):
    """Resolve a profile/stage map into a signed, versioned price snapshot."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        service = CatalogService(session)
        try:
            quote = service.quote_generation(
                body, user_id=getattr(user, "id", None)
            )
        except CatalogError as exc:
            raise _map_catalog_error(exc, request_id) from exc
    return utils.get_response(200, quote)
