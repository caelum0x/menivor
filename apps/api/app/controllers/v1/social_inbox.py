"""Social inbox HTTP surface (owner-scoped, token-free responses).

    GET  /social-inbox                           platforms (what each allows), tracked posts, totals
    GET  /social-inbox/threads                   filter by platform, post, status, kind; paginated
    GET  /social-inbox/threads/{thread_id}       full conversation + reply mode
    POST /social-inbox/threads/{thread_id}/suggestions   three reply suggestions (LLM or templates)
    POST /social-inbox/threads/{thread_id}/reply         send through the platform API when permitted
    POST /social-inbox/threads/{thread_id}/status        needs_reply | replied (sent in-app) | done
    POST /social-inbox/sync                      pull now for the caller's posts (rate limited)

Reading the inbox is free. Suggestions, replies and manual syncs are rate
limited per creator because they spend LLM tokens or platform API quota.
"""

from __future__ import annotations

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
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

try:
    from app.domains.social_inbox import repository as inbox_repo
    from app.domains.social_inbox import views as inbox_views
    from app.domains.social_inbox.capabilities import PLATFORMS
    from app.domains.social_inbox.models import THREAD_KINDS, THREAD_STATUSES
    from app.domains.social_inbox.replies import ReplyError, send_reply, set_status, thread_context
    from app.domains.social_inbox.suggestions import suggest
    from app.domains.social_inbox.sync import InboxUnavailable, sync_user

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - import-safe degrade to 503
    _IMPORT_ERROR = exc

router = new_router()

_SUGGEST_LIMIT = 60
_REPLY_LIMIT = 60
_SYNC_LIMIT = 6
_WINDOW_S = 3600
_ID = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


class ReplyBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


class StatusBody(BaseModel):
    status: str = Field(..., description="needs_reply | replied | done")
    reply_text: str = Field(default="", max_length=1000)


def _error(request_id: str, status: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}")


def _require_inbox(request_id: str) -> None:
    _require_db(request_id)
    if _IMPORT_ERROR is not None:
        logger.error(f"social inbox unavailable, request_id: {request_id}, error: {_IMPORT_ERROR}")
        raise _error(request_id, 503, "the social inbox is not available")


def _caller_id(request: Request, request_id: str) -> str:
    with get_session() as session:
        return str(_resolve_user(request, session, request_id).id)


def _reply_error(request_id: str, exc: "ReplyError") -> HttpException:
    return HttpException(
        task_id=request_id,
        status_code=exc.status_code,
        message=f"{request_id}: {exc}",
        data={"open_url": exc.open_url} if exc.open_url else None,
    )


@router.get("/social-inbox", summary="Social inbox overview: platforms, tracked posts, totals")
def inbox_overview(request: Request):
    request_id = base.get_task_id(request)
    _require_inbox(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        data = inbox_views.overview(session, str(user.id))
    return utils.get_response(200, data)


@router.get("/social-inbox/threads", summary="List inbox conversations with filters")
def list_threads(
    request: Request,
    platform: str = Query(default="", max_length=20),
    post_id: str = Query(default="", max_length=32, pattern=r"^[A-Za-z0-9]*$"),
    status: str = Query(default="needs_reply", max_length=16, description="needs_reply | replied | done | all"),
    kind: str = Query(default="", max_length=12, description="comment | dm"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    request_id = base.get_task_id(request)
    _require_inbox(request_id)
    plat = platform.strip().lower()
    if plat and plat not in PLATFORMS:
        raise _error(request_id, 400, f"platform must be one of {list(PLATFORMS)}")
    wanted_status = status.strip().lower()
    if wanted_status == "all":
        wanted_status = ""
    if wanted_status and wanted_status not in THREAD_STATUSES:
        raise _error(request_id, 400, "status must be needs_reply, replied, done or all")
    wanted_kind = kind.strip().lower()
    if wanted_kind and wanted_kind not in THREAD_KINDS:
        raise _error(request_id, 400, "kind must be comment or dm")
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows, total = inbox_repo.list_threads(
            session, str(user.id), platform=plat, post_id=post_id, status=wanted_status,
            kind=wanted_kind, limit=limit, offset=offset,
        )
        data = inbox_views.thread_list(session, str(user.id), rows, total, limit=limit, offset=offset)
    return utils.get_response(200, data)


@router.get("/social-inbox/threads/{thread_id}", summary="One conversation with its messages")
def get_thread(request: Request, thread_id: str = _ID):
    request_id = base.get_task_id(request)
    _require_inbox(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        thread = inbox_repo.get_thread(session, str(user.id), thread_id)
        if thread is None:
            raise _error(request_id, 404, "conversation not found")
        data = inbox_views.thread_detail(session, str(user.id), thread)
    return utils.get_response(200, data)


@router.post("/social-inbox/threads/{thread_id}/suggestions", summary="Suggest replies for a conversation")
def suggest_replies(request: Request, thread_id: str = _ID):
    request_id = base.get_task_id(request)
    _require_inbox(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = str(user.id)
        enforce_rate_limit(request, f"inbox-suggest:{user_id}", limit=_SUGGEST_LIMIT, window_s=_WINDOW_S)
        thread = inbox_repo.get_thread(session, user_id, thread_id)
        if thread is None:
            raise _error(request_id, 404, "conversation not found")
        _, title = thread_context(session, user_id, thread)
        inbound = [m for m in (thread.messages or []) if isinstance(m, dict) and not m.get("from_me")]
        latest = inbound[-1] if inbound else {}
        prompt_input = {
            "platform": thread.platform,
            "post_title": title,
            "author": str(latest.get("author") or thread.author_name or ""),
            "comment": str(latest.get("text") or thread.text or ""),
            "kind": thread.kind,
        }
    # The LLM call runs outside the DB session so no connection is held while it waits.
    result = suggest(**prompt_input)
    return utils.get_response(200, result.to_record())


@router.post("/social-inbox/threads/{thread_id}/reply", summary="Send a reply through the platform API")
def reply(request: Request, body: ReplyBody, thread_id: str = _ID):
    request_id = base.get_task_id(request)
    _require_inbox(request_id)
    user_id = _caller_id(request, request_id)
    enforce_rate_limit(request, f"inbox-reply:{user_id}", limit=_REPLY_LIMIT, window_s=_WINDOW_S)
    try:
        send_reply(user_id, thread_id, body.text)
    except ReplyError as exc:
        raise _reply_error(request_id, exc) from exc
    except InboxUnavailable as exc:
        raise _error(request_id, 503, "the social inbox is not available") from exc
    with get_session() as session:
        thread = inbox_repo.get_thread(session, user_id, thread_id)
        if thread is None:
            raise _error(request_id, 404, "conversation not found")
        data = inbox_views.thread_detail(session, user_id, thread)
    return utils.get_response(200, data)


@router.post("/social-inbox/threads/{thread_id}/status", summary="Mark a conversation replied, done or open")
def update_status(request: Request, body: StatusBody, thread_id: str = _ID):
    request_id = base.get_task_id(request)
    _require_inbox(request_id)
    user_id = _caller_id(request, request_id)
    try:
        set_status(user_id, thread_id, body.status.strip().lower(), reply_text=body.reply_text)
    except ReplyError as exc:
        raise _reply_error(request_id, exc) from exc
    except InboxUnavailable as exc:
        raise _error(request_id, 503, "the social inbox is not available") from exc
    with get_session() as session:
        thread = inbox_repo.get_thread(session, user_id, thread_id)
        if thread is None:
            raise _error(request_id, 404, "conversation not found")
        data = inbox_views.thread_detail(session, user_id, thread)
    return utils.get_response(200, data)


@router.post("/social-inbox/sync", summary="Pull new comments and messages now")
def sync_now(request: Request):
    request_id = base.get_task_id(request)
    _require_inbox(request_id)
    user_id = _caller_id(request, request_id)
    enforce_rate_limit(request, f"inbox-sync:{user_id}", limit=_SYNC_LIMIT, window_s=_WINDOW_S)
    try:
        summary = sync_user(user_id)
    except InboxUnavailable as exc:
        raise _error(request_id, 503, "the social inbox is not available") from exc
    with get_session() as session:
        data = inbox_views.overview(session, user_id)
    data["sync"] = summary
    return utils.get_response(200, data)
