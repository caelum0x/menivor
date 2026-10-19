"""HTTP surface for the extended publish platforms (owner-scoped, token-free).

    GET    /publishing/platforms                         every extended platform: server state, review/cost
                                                         notes, format rules, the caller's connection
    GET    /publishing/connect/{platform}/authorize      begin OAuth (single-use state bound to the caller)
    POST   /publishing/connect/callback                  finish OAuth ({code, state}; platform from the state)
    POST   /publishing/connect/bluesky                   connect Bluesky with handle + app password
    POST   /publishing/connections/{platform}/target     choose the Page / company page / board
    POST   /publishing/connections/{platform}/refresh    re-read Pages / organizations / boards
    DELETE /publishing/connections/{platform}            disconnect
    POST   /publishing/format-check                      per-platform fitted caption + issues
    POST   /publishing/posts                             post now or schedule (one row per platform)
    GET    /publishing/posts                             the caller's posts with status
    POST   /publishing/posts/{post_id}/cancel            cancel a post that has not started
    POST   /publishing/posts/{post_id}/retry             retry a failed / held post
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Path, Query, Request
from loguru import logger
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
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

from . import connections as conn_service
from . import posts as post_service
from .catalog import EXTENDED_PLATFORMS
from .connectors.base import new_default_transport
from .oauth import ConnectError

router = new_router()

_CONNECT_LIMIT = 30
_POST_LIMIT = 60
_CHECK_LIMIT = 240
_WINDOW_S = 3600
_PLATFORM = Path(..., min_length=1, max_length=20, pattern=r"^[a-z]+$")
_POST_ID = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


def _error(request_id: str, status: int, message: str, details: list | None = None) -> HttpException:
    return HttpException(
        task_id=request_id, status_code=status, message=f"{request_id}: {message}",
        data={"problems": details} if details else None,
    )


def _caller(request: Request, request_id: str, *, bucket: str = "", limit: int = 0) -> str:
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if bucket:
            enforce_rate_limit(request, f"{bucket}:{user.id}", limit=limit, window_s=_WINDOW_S)
        return str(user.id)


def _known(platform: str, request_id: str) -> str:
    plat = str(platform or "").strip().lower()
    if plat not in EXTENDED_PLATFORMS:
        raise _error(request_id, 404, "unknown platform")
    return plat


def _connect_error(request_id: str, exc: ConnectError) -> HttpException:
    return _error(request_id, exc.status_code, str(exc))


def _publishing_open() -> bool:
    try:
        from app.core.launch.policy import publishing_enabled

        return bool(publishing_enabled())
    except Exception:  # noqa: BLE001 - fail closed
        return False


# --------------------------------------------------------------------------- #
# Platforms + connections
# --------------------------------------------------------------------------- #
@router.get("/publishing/platforms", summary="Extended publish platforms and the caller's connections")
def list_platforms(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        conn_service.require_ready()
    except ConnectError as exc:
        raise _connect_error(request_id, exc) from exc
    with get_session() as session:
        platforms = conn_service.overview(session, user_id)
    return utils.get_response(200, {"platforms": platforms, "publishing_enabled": _publishing_open()})


@router.get("/publishing/connect/{platform}/authorize", summary="Begin an OAuth connect")
def authorize(request: Request, platform: str = _PLATFORM,
              organization: bool = Query(default=False, description="LinkedIn: ask for company-page access")):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    plat = _known(platform, request_id)
    user_id = _caller(request, request_id, bucket="ext_connect", limit=_CONNECT_LIMIT)
    try:
        return utils.get_response(200, conn_service.start_oauth(user_id, plat, organization=organization))
    except ConnectError as exc:
        raise _connect_error(request_id, exc) from exc


class CallbackBody(BaseModel):
    code: str = Field(..., min_length=1, max_length=2000)
    state: str = Field(..., min_length=10, max_length=200)


@router.post("/publishing/connect/callback", summary="Finish an OAuth connect")
def callback(request: Request, body: CallbackBody):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    user_id = _caller(request, request_id, bucket="ext_connect", limit=_CONNECT_LIMIT)
    try:
        record = conn_service.finish_oauth(user_id, body.code, body.state, transport=new_default_transport())
    except ConnectError as exc:
        raise _connect_error(request_id, exc) from exc
    except Exception as exc:  # noqa: BLE001 - provider down / storage failure
        logger.error(f"extended connect callback failed, request_id: {request_id}: {exc}")
        raise _error(request_id, 502, "the platform could not be reached; try connecting again") from exc
    return utils.get_response(200, record)


class BlueskyBody(BaseModel):
    handle: str = Field(..., min_length=3, max_length=253)
    app_password: str = Field(..., min_length=8, max_length=64)
    pds: str = Field(default="", max_length=200)


@router.post("/publishing/connect/bluesky", summary="Connect Bluesky with an app password")
def connect_bluesky(request: Request, body: BlueskyBody):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    user_id = _caller(request, request_id, bucket="ext_connect", limit=_CONNECT_LIMIT)
    try:
        record = conn_service.connect_bluesky(user_id, body.handle, body.app_password, pds=body.pds,
                                              transport=new_default_transport())
    except ConnectError as exc:
        raise _connect_error(request_id, exc) from exc
    return utils.get_response(200, record)


class TargetBody(BaseModel):
    target_id: str = Field(..., min_length=1, max_length=200)


@router.post("/publishing/connections/{platform}/target", summary="Choose where to post")
def choose_target(request: Request, body: TargetBody, platform: str = _PLATFORM):
    request_id = base.get_task_id(request)
    plat = _known(platform, request_id)
    user_id = _caller(request, request_id, bucket="ext_connect", limit=_CONNECT_LIMIT)
    try:
        record = conn_service.select_target(user_id, plat, body.target_id, transport=new_default_transport())
    except ConnectError as exc:
        raise _connect_error(request_id, exc) from exc
    return utils.get_response(200, record)


@router.post("/publishing/connections/{platform}/refresh", summary="Re-read Pages, organizations or boards")
def refresh_targets(request: Request, platform: str = _PLATFORM):
    request_id = base.get_task_id(request)
    plat = _known(platform, request_id)
    user_id = _caller(request, request_id, bucket="ext_connect", limit=_CONNECT_LIMIT)
    try:
        record = conn_service.refresh_targets(user_id, plat, transport=new_default_transport())
    except ConnectError as exc:
        raise _connect_error(request_id, exc) from exc
    return utils.get_response(200, record)


@router.delete("/publishing/connections/{platform}", summary="Disconnect an extended platform")
def disconnect(request: Request, platform: str = _PLATFORM):
    request_id = base.get_task_id(request)
    plat = _known(platform, request_id)
    user_id = _caller(request, request_id)
    try:
        removed = conn_service.disconnect(user_id, plat)
    except ConnectError as exc:
        raise _connect_error(request_id, exc) from exc
    if not removed:
        raise _error(request_id, 404, "not connected")
    return utils.get_response(200, {"platform": plat, "disconnected": True})


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #
class DraftBody(BaseModel):
    platform: str = Field(..., min_length=1, max_length=20)
    caption: str = Field(default="", max_length=6000)
    title: str = Field(default="", max_length=300)
    hashtags: list[str] = Field(default_factory=list, max_length=30)


class FormatCheckBody(BaseModel):
    drafts: list[DraftBody] = Field(..., min_length=1, max_length=post_service.MAX_POSTS_PER_REQUEST)


def _drafts(items: list[DraftBody]) -> list[post_service.PostDraft]:
    return [
        post_service.PostDraft(platform=d.platform.strip().lower(), caption=d.caption, title=d.title,
                               hashtags=tuple(t for t in d.hashtags if isinstance(t, str)))
        for d in items
    ]


@router.post("/publishing/format-check", summary="Fit a caption to each platform's limits")
def format_check(request: Request, body: FormatCheckBody):
    request_id = base.get_task_id(request)
    _caller(request, request_id, bucket="ext_format", limit=_CHECK_LIMIT)
    for d in body.drafts:
        _known(d.platform, request_id)
    fitted = post_service.preview(_drafts(body.drafts))
    return utils.get_response(200, {"results": [f.to_record() for f in fitted]})


class CreatePostsBody(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    drafts: list[DraftBody] = Field(..., min_length=1, max_length=post_service.MAX_POSTS_PER_REQUEST)
    scheduled_at: datetime | None = Field(default=None, description="UTC; omit to post now")


@router.post("/publishing/posts", summary="Post a reel now or schedule it to extended platforms")
def create_posts(request: Request, body: CreatePostsBody):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    user_id = _caller(request, request_id, bucket="ext_post", limit=_POST_LIMIT)
    for d in body.drafts:
        _known(d.platform, request_id)
    try:
        records = post_service.create_posts(user_id, body.job_id, _drafts(body.drafts),
                                            scheduled_at=body.scheduled_at)
    except post_service.PostError as exc:
        raise _error(request_id, exc.status_code, str(exc), exc.details) from exc
    return utils.get_response(200, {"posts": records})


@router.get("/publishing/posts", summary="The caller's extended-platform posts")
def list_posts(
    request: Request,
    status: str = Query(default="", max_length=80, description="comma-separated statuses"),
    job_id: str = Query(default="", max_length=32, pattern=r"^[A-Za-z0-9]*$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    statuses = tuple(s.strip() for s in status.split(",") if s.strip())
    try:
        data = post_service.list_for_user(user_id, statuses=statuses, job_id=job_id, limit=limit, offset=offset)
    except post_service.PostError as exc:
        raise _error(request_id, exc.status_code, str(exc)) from exc
    return utils.get_response(200, data)


@router.post("/publishing/posts/{post_id}/cancel", summary="Cancel a post that has not started")
def cancel_post(request: Request, post_id: str = _POST_ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="ext_post", limit=_POST_LIMIT)
    try:
        return utils.get_response(200, post_service.cancel(user_id, post_id))
    except post_service.PostError as exc:
        raise _error(request_id, exc.status_code, str(exc)) from exc


@router.post("/publishing/posts/{post_id}/retry", summary="Retry a failed or held post")
def retry_post(request: Request, post_id: str = _POST_ID):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    user_id = _caller(request, request_id, bucket="ext_post", limit=_POST_LIMIT)
    try:
        return utils.get_response(200, post_service.retry(user_id, post_id))
    except post_service.PostError as exc:
        raise _error(request_id, exc.status_code, str(exc)) from exc
