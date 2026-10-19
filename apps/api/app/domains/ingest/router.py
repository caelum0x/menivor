"""URL → reel HTTP domain.

* ``POST /ingest/url`` — turn any URL (website, store listing, social post or
  profile) into a submittable reel draft plus ``source`` facts.
* ``POST /ingest/detect`` — classify a URL instantly (no network).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

try:
    from app.core.auth import resolve_principal
    from app.domains.ingest.service import IngestError, IngestService, detect
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    IngestError = Exception  # type: ignore[assignment,misc]
    IngestService = None  # type: ignore[assignment]
    detect = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


class UrlIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., max_length=2048, description="Any URL to turn into a reel")


class UrlDetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., max_length=2048, description="Any URL pasted into the input box")


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


def _require_available(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None or IngestService is None:
        logger.error(f"ingest unavailable ({request_id}): {_DB_IMPORT_ERROR}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _authenticate(request: Request, request_id: str) -> str | None:
    """Authenticate the caller; returns their user id (None if the principal has none)."""
    _require_available(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = getattr(user, "id", None)
        return str(user_id) if user_id else None


def _record_first_link(user_id: str | None) -> None:
    """Funnel step "first link pasted" (best-effort; never affects the request)."""
    try:
        from app.services.funnel.store import record_step

        record_step(user_id, "first_link", session_factory=get_session)
    except Exception as exc:  # noqa: BLE001 - instrumentation only
        logger.warning(f"ingest: funnel record skipped: {type(exc).__name__}")


@router.post("/ingest/detect", summary="Classify a URL (no network)")
def ingest_detect(request: Request, body: UrlDetectRequest):
    """Return ``{kind, platform, label, url, handle}`` for the pasted URL."""
    request_id = base.get_task_id(request)
    _authenticate(request, request_id)
    try:
        kind = detect(body.url)
    except IngestError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.message}",
        ) from exc
    return utils.get_response(200, kind.to_dict())


@router.post("/ingest/url", summary="Turn a URL into a reel draft")
def ingest_url(request: Request, body: UrlIngestRequest):
    """Fetch a URL, extract content, and return a hook-first reel draft.

    Authenticated (the reel it feeds is caller-owned) but stateless — no job is
    created here; the client submits the returned draft to ``POST /jobs``.
    """
    request_id = base.get_task_id(request)
    user_id = _authenticate(request, request_id)
    try:
        data = IngestService().url_to_reel(body.url)
    except IngestError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.message}",
        ) from exc
    _record_first_link(user_id)
    return utils.get_response(200, data)
