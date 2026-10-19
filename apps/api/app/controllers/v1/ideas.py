"""SPARK — AI Idea Engine v1 API controller (Phase 18).

Auth-gated endpoints under ``/api/v1`` that let a creator turn an app/niche
description into N ready-to-shoot viral UGC video *concepts* and save the ones
they like for later:

* ``POST /ideas/generate`` — generate ``count`` (1..10) concepts for the
  supplied ``app_context`` via :func:`app.services.ideas.generate_ideas`. This
  spends LLM tokens, so it is rate-limited per caller (reusing
  :func:`app.services.ratelimit.enforce_rate_limit`). An empty ``app_context``
  is a clean ``400``; a generation that yields nothing is a clean ``502``.
* ``POST /me/ideas`` — persist one concept for the caller
  (:meth:`SavedIdeaRepository.create`) and return ``{id}``.
* ``GET /me/ideas`` — list the caller's saved concepts (ownership-scoped).
* ``DELETE /me/ideas/{idea_id}`` — delete a saved concept the caller owns
  (``404`` for a missing/foreign id — ownership enforced in the repository so a
  guessed id can neither delete nor confirm another user's saved idea).

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard block behind the single ``base.verify_token`` gate), so both auth paths
  (Clerk JWT + ``x-api-key``) and the get-or-create behaviour are identical to
  the rest of the API and this module stays import-safe.
* **Import-safe optional deps.** The SPARK generator and the ``SavedIdea``
  repository are imported inside guarded blocks; when they are absent the
  relevant endpoints degrade to a clean ``503`` at request time instead of an
  ``ImportError`` at startup (mirroring ``jobs.py`` / ``voices.py``).
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`. No secrets are hardcoded — the LLM key is
  read by the shared ``llm`` plumbing from config.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
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
    GenerateIdeasRequest,
    IdeasResponse,
    SavedIdeasResponse,
    SaveIdeaRequest,
)
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded optional imports (authored by sibling agents / depend on LLM plumbing;
# may be absent at compile time). Keeping these guarded makes the module
# import-safe: a missing dependency degrades to a clean 503 at request time.
# --------------------------------------------------------------------------- #
try:
    from app.services import ideas as ideas_service

    _IDEAS_SERVICE_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only when llm plumbing absent
    ideas_service = None  # type: ignore[assignment]
    _IDEAS_SERVICE_IMPORT_ERROR = exc

try:
    from app.models.db.models import SavedIdea  # noqa: F401 (re-exported for tests)
    from app.models.db.repositories import SavedIdeaRepository

    _SAVED_IDEA_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    SavedIdea = None  # type: ignore[assignment,misc]
    SavedIdeaRepository = None  # type: ignore[assignment,misc]
    _SAVED_IDEA_IMPORT_ERROR = exc


router = new_router()

# --------------------------------------------------------------------------- #
# Tunables (config-overridable). Idea generation spends LLM tokens, so it is
# rate-limited more tightly than the (already-limited) job pipeline.
# --------------------------------------------------------------------------- #
_DEFAULT_IDEAS_RATE_LIMIT: int = 20
_DEFAULT_IDEAS_RATE_WINDOW_S: int = 3600
# Saving spends no LLM tokens but still writes a DB row, so it is capped more
# loosely than generation to prevent unbounded insert (storage DoS) abuse.
_DEFAULT_SAVE_IDEA_RATE_LIMIT: int = 60
_DEFAULT_SAVE_IDEA_RATE_WINDOW_S: int = 3600
# Cap the number of saved ideas returned by a single list call.
_MAX_SAVED_IDEAS: int = 100


def _ideas_rate_limit() -> int:
    """Max idea generations per window per user (``reelforge_ideas_rate_limit``)."""
    return int(config.app.get("reelforge_ideas_rate_limit", _DEFAULT_IDEAS_RATE_LIMIT))


def _ideas_rate_window_s() -> int:
    """Rate-limit window in seconds (``reelforge_ideas_rate_window_s``)."""
    return int(
        config.app.get("reelforge_ideas_rate_window_s", _DEFAULT_IDEAS_RATE_WINDOW_S)
    )


def _save_idea_rate_limit() -> int:
    """Max idea saves per window per user (``reelforge_save_idea_rate_limit``)."""
    return int(
        config.app.get("reelforge_save_idea_rate_limit", _DEFAULT_SAVE_IDEA_RATE_LIMIT)
    )


def _save_idea_rate_window_s() -> int:
    """Save rate-limit window in seconds (``reelforge_save_idea_rate_window_s``)."""
    return int(
        config.app.get(
            "reelforge_save_idea_rate_window_s", _DEFAULT_SAVE_IDEA_RATE_WINDOW_S
        )
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_ideas_service(request_id: str) -> None:
    """Raise 503 when the SPARK generator could not be imported."""
    if ideas_service is None:
        logger.error(
            f"ideas service unavailable, request_id: {request_id}, "
            f"error: {_IDEAS_SERVICE_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: idea generation service is not available",
        )


def _require_saved_ideas(request_id: str) -> None:
    """Raise 503 when the saved-idea persistence layer is unavailable."""
    if _SAVED_IDEA_IMPORT_ERROR is not None or SavedIdeaRepository is None:
        logger.error(
            f"saved-idea persistence unavailable, request_id: {request_id}, "
            f"error: {_SAVED_IDEA_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: saved-idea storage is not available",
        )


def _saved_idea_public_data(row: Any) -> dict:
    """Serialise a ``SavedIdea`` row to its public, JSON-safe envelope.

    The whole concept is returned under ``idea`` (the stored ``payload``); the
    denormalised ``title``/``hook`` columns are surfaced for cheap list rendering.
    """
    created_at = getattr(row, "created_at", None)
    return {
        "id": row.id,
        "title": row.title,
        "hook": row.hook,
        "idea": dict(getattr(row, "payload", None) or {}),
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


# --------------------------------------------------------------------------- #
# POST /ideas/generate
# --------------------------------------------------------------------------- #
@router.post(
    "/ideas/generate",
    response_model=IdeasResponse,
    summary="Generate viral UGC video concepts for an app/niche",
)
def generate_ideas_endpoint(request: Request, body: GenerateIdeasRequest):
    """Generate ``count`` ready-to-shoot viral UGC concepts for ``app_context``.

    Order: auth -> ``400`` on an empty ``app_context`` -> per-caller rate limit
    (LLM tokens) -> generate. A generator that returns ``None`` (all retries
    failed) surfaces as a clean ``502`` rather than a raw error or empty body.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_ideas_service(request_id)

    app_context = str(getattr(body, "app_context", "") or "").strip()
    if not app_context:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: app_context is required",
        )

    audience = str(getattr(body, "audience", "") or "").strip()
    count = getattr(body, "count", None)
    language = str(getattr(body, "language", "") or "auto").strip() or "auto"

    # Resolve the caller (auth) and enforce the per-user rate limit BEFORE
    # spending any LLM tokens. Fail-open if Redis is unreachable.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        enforce_rate_limit(
            request,
            f"ideas:{user.id}",
            limit=_ideas_rate_limit(),
            window_s=_ideas_rate_window_s(),
        )

    try:
        ideas = ideas_service.generate_ideas(
            app_context=app_context,
            audience=audience,
            count=count if count is not None else ideas_service.DEFAULT_IDEA_COUNT,
            language=language,
        )
    except Exception as exc:  # noqa: BLE001 - never leak a raw generator failure
        logger.error(f"idea generation crashed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to generate ideas",
        )

    if not ideas:
        # The generator returns ``None`` (or an empty list) when every retry
        # failed; surface a clean error instead of an empty success envelope.
        logger.error(f"idea generation produced no ideas, request_id: {request_id}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to generate ideas",
        )

    return utils.get_response(200, ideas)


# --------------------------------------------------------------------------- #
# POST /me/ideas  (save)
# --------------------------------------------------------------------------- #
@router.post(
    "/me/ideas",
    summary="Save a generated idea for later",
)
def save_idea_endpoint(request: Request, body: SaveIdeaRequest):
    """Persist one concept for the caller and return ``{id}``.

    A ``400`` is returned when ``idea`` is missing/empty or not a JSON object.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_saved_ideas(request_id)

    idea = getattr(body, "idea", None)
    if not isinstance(idea, dict) or not idea:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: a non-empty idea object is required",
        )

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            # Cap the per-user save rate BEFORE writing a row so a crafted loop
            # cannot inflate storage / degrade user_id index scans (DoS).
            # Fail-open if Redis is unreachable.
            enforce_rate_limit(
                request,
                f"save_idea:{user.id}",
                limit=_save_idea_rate_limit(),
                window_s=_save_idea_rate_window_s(),
            )
            row = SavedIdeaRepository(session).create(user.id, idea)
            idea_id = row.id
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"failed to save idea, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to save the idea",
        )

    return utils.get_response(200, {"id": idea_id})


# --------------------------------------------------------------------------- #
# GET /me/ideas  (list)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/ideas",
    response_model=SavedIdeasResponse,
    summary="List the caller's saved ideas",
)
def list_ideas_endpoint(request: Request):
    """Return the caller's saved concepts, newest first (scoped to the caller)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_saved_ideas(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = SavedIdeaRepository(session).list_for_user(
            user.id, limit=_MAX_SAVED_IDEAS
        )
        data = [_saved_idea_public_data(r) for r in rows]

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# DELETE /me/ideas/{idea_id}
# --------------------------------------------------------------------------- #
@router.delete(
    "/me/ideas/{idea_id}",
    summary="Delete one of the caller's saved ideas",
)
def delete_idea_endpoint(
    request: Request,
    idea_id: str = Path(..., description="Saved idea ID"),
):
    """Delete the caller's saved idea. Returns ``404`` for an unknown/foreign id.

    Ownership is enforced in the repository (``delete``): a saved idea that does
    not belong to the caller is indistinguishable from a missing one, so a
    guessed id can never delete — or even confirm the existence of — another
    user's saved idea.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_saved_ideas(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        deleted = SavedIdeaRepository(session).delete(idea_id, user.id)
        if not deleted:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: idea not found",
            )

    return utils.get_response(200, {"deleted": True, "id": idea_id})
