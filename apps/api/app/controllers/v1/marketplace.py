"""Template Marketplace v1 API controller.

Auth-gated endpoints under ``/api/v1`` that let a creator publish an IMMUTABLE
snapshot of a private job template to a shared, PUBLIC marketplace, and let any
other authenticated user browse/search it, view its detail, CLONE it into their
own private templates, and RATE it (1..5, one rating per user, upserted):

* ``GET  /marketplace``            — browse/search published listings (public
  content, still authed). ``query`` (title/description), ``tag``, ``language``,
  ``sort`` (``top`` | ``new`` | ``clones``), ``limit`` (clamped ``[1, 100]``) and
  ``offset`` (``>= 0``) are all normalized/clamped so an untrusted page request
  can never trigger an unbounded scan.
* ``GET  /marketplace/{id}``       — a single listing (any published state).
* ``POST /marketplace/publish``    — OWNER-SCOPED publish: snapshot the caller's
  own private template (by ``template_id``) or inline fields into a public copy.
* ``POST /marketplace/{id}/clone`` — clone a published listing into the caller's
  private templates (bumps ``clone_count``).
* ``POST /marketplace/{id}/rate``  — upsert the caller's 1..5 rating.
* ``DELETE /marketplace/{id}``     — AUTHOR-ONLY soft unpublish.

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard block behind the single ``base.verify_token`` gate), so both auth paths
  (Clerk JWT + ``x-api-key``) and get-or-create behaviour match the rest of the
  API and this module stays import-safe.
* **Import-safe optional deps.** The marketplace service + repositories are
  imported inside guarded blocks; when absent the endpoints degrade to a clean
  ``503`` at request time instead of an ``ImportError`` at startup (mirroring
  ``ideas.py`` / ``jobs.py``).
* **Clean 4xx over 422.** A service ``ValueError`` (bad/foreign/missing template,
  out-of-range stars, empty title) is mapped to a clean ``400`` / ``404`` so the
  error shape matches the rest of the API.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`. No secrets are hardcoded.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Query, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these are ``None`` and
# ``_require_db`` raises a clean 503 at request time.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    CloneResponse,
    MarketplaceLineageResponse,
    MarketplaceListResponse,
    MarketplaceTemplateResponse,
    PublishTemplateRequest,
    RateRequest,
)
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded optional imports (depend on the DB layer authored by sibling agents;
# may be absent at compile time). Keeping these guarded makes the module
# import-safe: a missing dependency degrades to a clean 503 at request time.
# --------------------------------------------------------------------------- #
try:
    from app.services import marketplace as marketplace_service

    _MARKETPLACE_SERVICE_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    marketplace_service = None  # type: ignore[assignment]
    _MARKETPLACE_SERVICE_IMPORT_ERROR = exc

try:
    from app.models.db.repositories import MarketplaceRepository

    _MARKETPLACE_REPO_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    MarketplaceRepository = None  # type: ignore[assignment,misc]
    _MARKETPLACE_REPO_IMPORT_ERROR = exc


router = new_router()

# --------------------------------------------------------------------------- #
# Tunables (config-overridable). Publish/clone/rate each write a DB row, so they
# are capped per-caller to prevent unbounded insert (storage-DoS) abuse. The
# limiter degrades OPEN when Redis is unreachable, so it never breaks the flow.
# --------------------------------------------------------------------------- #
_DEFAULT_WRITE_RATE_LIMIT: int = 120
_DEFAULT_WRITE_RATE_WINDOW_S: int = 3600


def _write_rate_limit() -> int:
    """Max marketplace writes per window per user (``reelforge_marketplace_rate_limit``)."""
    return int(
        config.app.get("reelforge_marketplace_rate_limit", _DEFAULT_WRITE_RATE_LIMIT)
    )


def _write_rate_window_s() -> int:
    """Write rate-limit window in seconds (``reelforge_marketplace_rate_window_s``)."""
    return int(
        config.app.get(
            "reelforge_marketplace_rate_window_s", _DEFAULT_WRITE_RATE_WINDOW_S
        )
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _is_proven_sort(sort: str) -> bool:
    """Whether the requested ``sort`` normalizes to the ``proven`` win-score order.

    Uses the service's single source of truth (``PROVEN_SORT``) so the controller
    never drifts from the recognized sort names. Case/whitespace-insensitive.
    """
    proven = getattr(marketplace_service, "PROVEN_SORT", "proven")
    return (sort or "").strip().lower() == proven


def _require_marketplace(request_id: str) -> None:
    """Raise 503 when the marketplace service/repository could not be imported."""
    if marketplace_service is None or MarketplaceRepository is None:
        error = _MARKETPLACE_SERVICE_IMPORT_ERROR or _MARKETPLACE_REPO_IMPORT_ERROR
        logger.error(
            f"marketplace layer unavailable, request_id: {request_id}, error: {error}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: template marketplace is not available",
        )


def _listing_public_data(row: Any, win_score: float | None = None) -> dict:
    """Serialise a ``MarketplaceTemplate`` row to its public, JSON-safe envelope.

    Read every attribute while the row is still attached to its session (the
    caller invokes this inside the ``get_session`` block) so a later
    expire-on-commit can never trigger a detached-instance lazy load.

    ``win_score`` is the listing's real-world "proven" performance score, attached
    only for the ``sort='proven'`` browse (``None`` — and omitted from the
    serialised value — otherwise, so the default browse/detail shape is unchanged).
    """
    created_at = getattr(row, "created_at", None)
    updated_at = getattr(row, "updated_at", None)
    data = {
        "id": row.id,
        "author_user_id": row.author_user_id,
        "title": row.title,
        "description": row.description,
        "prompt": row.prompt,
        "params": dict(getattr(row, "params", None) or {}),
        "tags": list(getattr(row, "tags", None) or []),
        "language": row.language,
        "layout": row.layout,
        "rating_avg": float(getattr(row, "rating_avg", 0.0) or 0.0),
        "rating_count": int(getattr(row, "rating_count", 0) or 0),
        "clone_count": int(getattr(row, "clone_count", 0) or 0),
        "published": bool(getattr(row, "published", True)),
        "created_at": created_at.isoformat() if created_at is not None else None,
        "updated_at": updated_at.isoformat() if updated_at is not None else None,
        # REMIX-TREE provenance (safe public fields): the listing this one was
        # remixed from (``None`` for an original), and how many published listings
        # directly descend from it.
        "parent_template_id": getattr(row, "parent_template_id", None),
        "remix_count": int(getattr(row, "remix_count", 0) or 0),
    }
    if win_score is not None:
        data["win_score"] = float(win_score)
    return data


# --------------------------------------------------------------------------- #
# GET /marketplace  (browse / search)
# --------------------------------------------------------------------------- #
@router.get(
    "/marketplace",
    response_model=MarketplaceListResponse,
    summary="Browse/search published marketplace templates",
)
def browse_marketplace_endpoint(
    request: Request,
    query: str = Query(default="", max_length=200, description="Title/description text"),
    tag: str = Query(default="", max_length=60, description="Single discovery tag"),
    language: str = Query(default="", max_length=20, description="Persona/language code"),
    sort: str = Query(
        default="top",
        description="top | new | clones | proven | most_remixed",
    ),
    limit: int = Query(default=20, description="Page size (clamped to 1..100)"),
    offset: int = Query(default=0, description="Row offset (clamped to >= 0)"),
):
    """Return published listings matching the filters, sorted + paginated.

    Public content but still authed like every other ``/v1`` route. ``limit`` is
    clamped to ``[1, 100]`` and ``offset`` to ``>= 0`` in the service so an
    untrusted page request can never trigger an unbounded scan.

    ``sort='proven'`` re-ranks the (already-clamped) page by the real-world
    win-score of the reels made from each listing's clones and annotates each
    listing with its ``win_score`` (``None``/absent for listings with no
    downstream performance data, or with fewer than
    ``WIN_SCORE_PUBLIC_MIN_COHORT`` distinct cloners — a k-anonymity floor that
    keeps a single creator's private metrics from leaking). All existing sorts
    keep their exact shape — the ``win_score`` field is only attached on the
    ``proven`` sort.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_marketplace(request_id)

    with get_session() as session:
        _resolve_user(request, session, request_id)  # auth gate (401 without a key)
        rows = marketplace_service.browse(
            session,
            query=query,
            tag=tag,
            language=language,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        # Only the ``proven`` sort surfaces per-listing win-scores. Compute the
        # bounded page's scores once (a listing absent from the map has no
        # downstream reels yet — its ``win_score`` stays ``None``/omitted).
        if _is_proven_sort(sort):
            # k-anonymity: only surface the numeric win_score for listings with a
            # large-enough distinct-cloner cohort, so a stranger can never read a
            # scalar derived from a single creator's private metrics. Ordering
            # (inside ``browse``) still uses the full, unfloored scores.
            scores = marketplace_service.listing_win_scores(
                session,
                [r.id for r in rows],
                min_cohort=marketplace_service.WIN_SCORE_PUBLIC_MIN_COHORT,
            )
            data = [_listing_public_data(r, scores.get(r.id)) for r in rows]
        else:
            data = [_listing_public_data(r) for r in rows]

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /marketplace/{template_id}  (detail)
# --------------------------------------------------------------------------- #
@router.get(
    "/marketplace/{template_id}",
    response_model=MarketplaceTemplateResponse,
    summary="Get a single marketplace template",
)
def get_marketplace_endpoint(
    request: Request,
    template_id: str = Path(..., description="Marketplace template ID"),
):
    """Return one listing by id. ``404`` for an unknown/unpublished listing."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_marketplace(request_id)

    with get_session() as session:
        _resolve_user(request, session, request_id)  # auth gate
        listing = marketplace_service.get(session, template_id)
        if listing is None or not listing.published:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: template not found",
            )
        data = _listing_public_data(listing)

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /marketplace/{template_id}/lineage  (remix tree: ancestors + children)
# --------------------------------------------------------------------------- #
@router.get(
    "/marketplace/{template_id}/lineage",
    response_model=MarketplaceLineageResponse,
    summary="Get a listing's remix-tree lineage (ancestors + direct children)",
)
def marketplace_lineage_endpoint(
    request: Request,
    template_id: str = Path(..., description="Marketplace template ID"),
):
    """Return the remix-tree lineage of a listing: its ancestors and children.

    ``ancestors`` walks UP the ``parent_template_id`` chain (immediate parent first
    → root, capped at ``LINEAGE_MAX_DEPTH``); ``children`` are the DIRECT,
    still-published remixes (newest first, clamped ``[1, 100]``). An unknown/blank
    id yields two empty lists. Each entry is serialised with only the safe public
    listing fields (never private financials). Public content but still authed like
    every other ``/v1`` route.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_marketplace(request_id)

    with get_session() as session:
        _resolve_user(request, session, request_id)  # auth gate
        tree = marketplace_service.lineage(session, template_id)
        data = {
            "ancestors": [_listing_public_data(row) for row in tree["ancestors"]],
            "children": [_listing_public_data(row) for row in tree["children"]],
        }

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# POST /marketplace/publish  (owner-scoped)
# --------------------------------------------------------------------------- #
@router.post(
    "/marketplace/publish",
    response_model=MarketplaceTemplateResponse,
    summary="Publish a private template to the public marketplace",
)
def publish_marketplace_endpoint(request: Request, body: PublishTemplateRequest):
    """Publish an IMMUTABLE snapshot of the caller's private template.

    Owner-scoped: a referenced ``template_id`` must be a preset OWNED by the
    caller (a foreign/missing id is a clean ``404``). An empty resolved title is a
    ``400``. The snapshot is a COPY, so later edits to the source never mutate the
    public listing.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_marketplace(request_id)

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            enforce_rate_limit(
                request,
                f"marketplace_publish:{user.id}",
                limit=_write_rate_limit(),
                window_s=_write_rate_window_s(),
            )
            listing = marketplace_service.publish_from_template(
                session,
                user.id,
                template_id=body.template_id,
                title=body.title,
                description=body.description,
                prompt=body.prompt,
                params=body.params,
                tags=body.tags,
                language=body.language,
                layout=body.layout,
            )
            data = _listing_public_data(listing)
    except HttpException:
        raise
    except ValueError as exc:
        # Foreign/missing referenced template -> 404; any other bad argument
        # (empty title, etc.) -> 400. Both are clean, API-shaped client errors.
        status = 404 if "not found" in str(exc).lower() else 400
        raise HttpException(task_id=request_id, status_code=status, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"failed to publish template, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to publish the template",
        )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# POST /marketplace/{template_id}/clone
# --------------------------------------------------------------------------- #
@router.post(
    "/marketplace/{template_id}/clone",
    response_model=CloneResponse,
    summary="Clone a marketplace template into your private templates",
)
def clone_marketplace_endpoint(
    request: Request,
    template_id: str = Path(..., description="Marketplace template ID"),
):
    """Clone a PUBLISHED listing into the caller's private templates.

    Allowed for any authenticated user; bumps the listing's ``clone_count``. A
    missing/unpublished listing is a clean ``404``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_marketplace(request_id)

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            enforce_rate_limit(
                request,
                f"marketplace_clone:{user.id}",
                limit=_write_rate_limit(),
                window_s=_write_rate_window_s(),
            )
            preset = marketplace_service.clone_to_user(session, user.id, template_id)
            data = {
                "id": preset.id,
                "name": preset.name,
                "source_marketplace_id": (preset.config or {}).get(
                    "source_marketplace_id", template_id
                ),
            }
    except HttpException:
        raise
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HttpException(task_id=request_id, status_code=status, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"failed to clone template, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to clone the template",
        )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# POST /marketplace/{template_id}/rate  (upsert)
# --------------------------------------------------------------------------- #
@router.post(
    "/marketplace/{template_id}/rate",
    response_model=MarketplaceTemplateResponse,
    summary="Rate a marketplace template (1..5, one rating per user)",
)
def rate_marketplace_endpoint(
    request: Request,
    body: RateRequest,
    template_id: str = Path(..., description="Marketplace template ID"),
):
    """Upsert the caller's 1..5 rating and return the listing with fresh aggregate.

    Allowed for any authenticated user; a re-rate updates the caller's existing
    row (never a duplicate). ``stars`` outside ``[1, 5]`` is a clean ``400``; a
    missing/unpublished listing is a ``404``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_marketplace(request_id)

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            enforce_rate_limit(
                request,
                f"marketplace_rate:{user.id}",
                limit=_write_rate_limit(),
                window_s=_write_rate_window_s(),
            )
            listing = marketplace_service.rate(
                session, user.id, template_id, body.stars
            )
            data = _listing_public_data(listing)
    except HttpException:
        raise
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HttpException(task_id=request_id, status_code=status, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"failed to rate template, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to rate the template",
        )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# DELETE /marketplace/{template_id}  (author-only unpublish)
# --------------------------------------------------------------------------- #
@router.delete(
    "/marketplace/{template_id}",
    summary="Unpublish a marketplace template you authored",
)
def unpublish_marketplace_endpoint(
    request: Request,
    template_id: str = Path(..., description="Marketplace template ID"),
):
    """Soft-unpublish a listing the caller authored. Returns ``404`` otherwise.

    Owner-scoped in the repository (``UPDATE ... WHERE id AND author_user_id AND
    published``): a listing that does not exist, belongs to a different author, or
    is already unpublished is indistinguishable from a missing one, so a caller
    can never unpublish — or even confirm the existence of — another creator's
    listing by guessing its id. The row is retained (soft hide) so its
    clones/ratings survive.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_marketplace(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        unpublished = MarketplaceRepository(session).unpublish(template_id, user.id)
        if not unpublished:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: template not found",
            )

    return utils.get_response(200, {"unpublished": True, "id": template_id})
