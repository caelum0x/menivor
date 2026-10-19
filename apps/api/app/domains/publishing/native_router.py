"""Native multi-platform publish HTTP surface.

``POST /jobs/{job_id}/publish/native`` posts a completed reel to a *connected*
platform via its **native API** (YouTube/TikTok/Instagram), using the OAuth token
stored by the connections domain. Auth + owner-scoping + rate-limit reuse the same
helpers as the connections controller (single ``base.verify_token`` gate).
"""

from __future__ import annotations

from fastapi import Path, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import (
    get_session,
    require_database as _require_db,
    resolve_principal as _resolve_user,
)
from app.core.launch import require_publishing_enabled
from app.models.exception import HttpException
from app.services.billing.pro_access import require_pro_action
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

from .connectors import available_platforms
from .native_service import (
    NativePublishError,
    public_trace_result,
    publish_reel_native,
    track_processing_publish,
)

router = new_router()

_DEFAULT_RATE_LIMIT = 20
_DEFAULT_RATE_WINDOW_S = 3600


class NativePublishBody(BaseModel):
    """Request body for a native publish."""

    platform: str = Field(..., description="youtube | tiktok | instagram")
    title: str = Field(default="", max_length=200)
    caption: str = Field(default="", max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    privacy: str = Field(default="public", max_length=20)


@router.get("/publishing/native/platforms", summary="List natively-supported publish platforms")
def native_platforms(request: Request):
    """Platforms with a native (non-aggregator) publish connector."""
    _ = base.get_task_id(request)
    return utils.get_response(200, {"platforms": list(available_platforms())})


@router.post("/jobs/{job_id}/publish/native", summary="Publish a reel to a connected platform natively")
def publish_native(request: Request, body: NativePublishBody, job_id: str = Path(...)):
    """Post a completed job's reel to a connected platform's native API.

    Order: publishing gate → DB → auth (owner) → per-caller rate limit → dispatch
    (token refresh + resolve output + native API call). Errors are mapped to the
    right HTTP status via :class:`NativePublishError.status_code`.
    """
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    _require_db(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)  # auth gate
        require_pro_action(str(user.id), request_id, action="native publish")
        enforce_rate_limit(
            request,
            f"native_publish:{user.id}",
            limit=_DEFAULT_RATE_LIMIT,
            window_s=_DEFAULT_RATE_WINDOW_S,
        )
        user_id = user.id

    try:
        result = publish_reel_native(
            user_id,
            job_id,
            body.platform,
            title=body.title,
            caption=body.caption,
            hashtags=tuple(body.hashtags),
            privacy=body.privacy,
        )
    except NativePublishError as exc:
        raise HttpException(
            task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}"
        ) from exc

    # Instagram/TikTok ingest asynchronously: a "processing" post is tracked so
    # the publish-status sweep finishes it (and it appears on the calendar).
    track_processing_publish(str(user_id), job_id, result)

    return utils.get_response(
        200,
        {
            "platform": result.platform,
            "status": result.status,
            "external_id": result.external_id,
            "url": result.url,
            **public_trace_result(result),
        },
    )


# --------------------------------------------------------------------------- #
# Publishing calendar: unified entries, policy-checked drag-to-reschedule,
# best-time hints and the per-platform tone preview (Wave L, M-2).
# --------------------------------------------------------------------------- #
from datetime import datetime as _dt  # noqa: E402

from fastapi import Query  # noqa: E402

from . import calendar_tools, tone  # noqa: E402

_CAL_MOVE_LIMIT = 240
_CAL_PREVIEW_LIMIT = 600
_SOURCE = Path(..., pattern=r"^(native|post)$")
_ENTRY_ID = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


def _cal_caller(request: Request, request_id: str, *, bucket: str = "", limit: int = 0) -> str:
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if bucket:
            enforce_rate_limit(request, f"{bucket}:{user.id}", limit=limit, window_s=_DEFAULT_RATE_WINDOW_S)
        return str(user.id)


def _cal_error(request_id: str, exc: calendar_tools.CalendarToolError) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}",
                         data=exc.details or None)


@router.get("/publishing/calendar/entries", summary="Every scheduled and published post in a window")
def calendar_entries(
    request: Request,
    start: _dt = Query(..., description="Inclusive ISO-8601 lower bound (UTC when naive)"),
    end: _dt = Query(..., description="Inclusive ISO-8601 upper bound (UTC when naive)"),
):
    request_id = base.get_task_id(request)
    user_id = _cal_caller(request, request_id)
    with get_session() as session:
        try:
            data = calendar_tools.entries(session, user_id, start, end)
        except calendar_tools.CalendarToolError as exc:
            raise _cal_error(request_id, exc) from exc
    return utils.get_response(200, data)


class SlotBody(BaseModel):
    source: str = Field(..., pattern=r"^(native|post)$")
    id: str = Field(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    scheduled_at: _dt


@router.post("/publishing/calendar/check", summary="Would this slot pass the posting policy?")
def calendar_check(request: Request, body: SlotBody):
    request_id = base.get_task_id(request)
    user_id = _cal_caller(request, request_id, bucket="cal_move", limit=_CAL_MOVE_LIMIT)
    with get_session() as session:
        try:
            check = calendar_tools.check_slot(session, user_id, body.source, body.id, body.scheduled_at)
        except calendar_tools.CalendarToolError as exc:
            raise _cal_error(request_id, exc) from exc
    return utils.get_response(200, check.to_record())


class MoveBody(BaseModel):
    scheduled_at: _dt
    force: bool = Field(default=False, description="Keep a slot that breaks the daily cap / minimum gap")


@router.patch("/publishing/calendar/entries/{source}/{entry_id}", summary="Reschedule a calendar entry")
def calendar_move(request: Request, body: MoveBody, source: str = _SOURCE, entry_id: str = _ENTRY_ID):
    """Move a not-yet-started entry. ``409`` with ``data.check`` (reason + suggested slot) on a policy clash."""
    request_id = base.get_task_id(request)
    user_id = _cal_caller(request, request_id, bucket="cal_move", limit=_CAL_MOVE_LIMIT)
    with get_session() as session:
        try:
            data = calendar_tools.move(session, user_id, source, entry_id, body.scheduled_at, force=body.force)
        except calendar_tools.CalendarToolError as exc:
            raise _cal_error(request_id, exc) from exc
    return utils.get_response(200, data)


class TonePreviewBody(BaseModel):
    caption: str = Field(default="", max_length=6000)
    title: str = Field(default="", max_length=300)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    tone: str = Field(default="as_written", pattern=r"^(as_written|professional|casual|concise)$")
    platforms: list[str] = Field(..., min_length=1, max_length=16)


@router.post("/publishing/calendar/preview", summary="Caption in a tone, fitted to each platform")
def calendar_preview(request: Request, body: TonePreviewBody):
    request_id = base.get_task_id(request)
    _cal_caller(request, request_id, bucket="cal_preview", limit=_CAL_PREVIEW_LIMIT)
    try:
        toned, previews = tone.preview(
            [p for p in body.platforms if isinstance(p, str)], caption=body.caption, tone=body.tone,
            title=body.title, hashtags=tuple(t for t in body.hashtags if isinstance(t, str)),
        )
    except ValueError as exc:
        raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: {exc}") from exc
    return utils.get_response(200, {
        "tone": body.tone,
        "tones": [{"id": t, "label": tone.TONE_LABELS[t]} for t in tone.TONES],
        "caption": toned,
        "previews": [p.to_record() for p in previews],
    })
