"""Engagement autopilot HTTP surface (owner-scoped).

    GET  /social-inbox/autopilot                          rules per platform, what each allows, today's usage
    PUT  /social-inbox/autopilot/{platform}               change rules (every change is audited)
    POST /social-inbox/autopilot/run                      run now for the caller (rate limited)
    GET  /social-inbox/autopilot/approvals                reply drafts waiting for approval
    POST /social-inbox/autopilot/approvals/{id}/approve   send the (optionally edited) draft
    POST /social-inbox/autopilot/approvals/{id}/reject    discard the draft
    GET  /social-inbox/autopilot/activity                 audit log (filter by kind / status / platform)
    GET  /social-inbox/leads                              buying-intent conversations
    POST /social-inbox/leads/{id}                         update a lead's status / note

Mounted through ``app.domains.publishing.router`` (the domain router already
included by the root API router).
"""

from __future__ import annotations

from typing import Any

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
    from app.domains.social_inbox import autopilot

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - import-safe degrade to 503
    autopilot = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

router = new_router()

_RUN_LIMIT = 12
_DECIDE_LIMIT = 120
_SETTINGS_LIMIT = 120
_WINDOW_S = 3600
def _id() -> Any:
    """A fresh ``Path`` per parameter: one shared instance pins its alias to the first name used."""
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
_PLATFORM = Path(..., min_length=1, max_length=20, pattern=r"^[a-z]+$")


def _error(request_id: str, status: int, message: str, data: dict | None = None) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}", data=data)


def _caller(request: Request, request_id: str, *, bucket: str = "", limit: int = 0) -> str:
    _require_db(request_id)
    if _IMPORT_ERROR is not None:
        logger.error(f"autopilot unavailable, request_id: {request_id}, error: {_IMPORT_ERROR}")
        raise _error(request_id, 503, "the engagement autopilot is not available")
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if bucket:
            enforce_rate_limit(request, f"{bucket}:{user.id}", limit=limit, window_s=_WINDOW_S)
        return str(user.id)


def _mapped(request_id: str, exc: Exception) -> HttpException:
    if isinstance(exc, autopilot.AutopilotError):
        data = {"open_url": exc.open_url} if exc.open_url else None
        return _error(request_id, exc.status_code, str(exc), data)
    from app.domains.social_inbox.sync import InboxUnavailable

    if isinstance(exc, InboxUnavailable):
        return _error(request_id, 503, "the social inbox is not available")
    logger.error(f"autopilot request failed, request_id: {request_id}: {exc}")
    return _error(request_id, 500, "something went wrong")


@router.get("/social-inbox/autopilot", summary="Engagement autopilot rules and status")
def get_autopilot(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        with get_session() as session:
            return utils.get_response(200, autopilot.overview(session, user_id))
    except Exception as exc:  # noqa: BLE001
        raise _mapped(request_id, exc) from exc


class SettingsBody(BaseModel):
    enabled: bool | None = None
    auto_like: bool | None = None
    reply_mode: str | None = Field(default=None, max_length=12)
    reply_to_questions: bool | None = None
    hide_spam: bool | None = None
    hide_abuse: bool | None = None
    route_leads: bool | None = None
    daily_cap: int | None = Field(default=None, ge=0, le=500)
    blocked_words: list[str] | None = Field(default=None, max_length=50)


@router.put("/social-inbox/autopilot/{platform}", summary="Change autopilot rules for one platform")
def put_settings(request: Request, body: SettingsBody, platform: str = _PLATFORM):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="autopilot_settings", limit=_SETTINGS_LIMIT)
    try:
        return utils.get_response(200, autopilot.update_settings(user_id, platform, body.model_dump(exclude_none=True)))
    except Exception as exc:  # noqa: BLE001
        raise _mapped(request_id, exc) from exc


@router.post("/social-inbox/autopilot/run", summary="Run the autopilot now for the caller")
def run_now(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="autopilot_run", limit=_RUN_LIMIT)
    try:
        return utils.get_response(200, autopilot.run_for_user(user_id))
    except Exception as exc:  # noqa: BLE001
        raise _mapped(request_id, exc) from exc


@router.get("/social-inbox/autopilot/approvals", summary="Reply drafts waiting for approval")
def approvals(request: Request, limit: int = Query(default=50, ge=1, le=100),
              offset: int = Query(default=0, ge=0, le=10_000)):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        return utils.get_response(200, autopilot.list_actions(
            user_id, statuses=("pending_approval",), kinds=("reply",), limit=limit, offset=offset))
    except Exception as exc:  # noqa: BLE001
        raise _mapped(request_id, exc) from exc


class ApproveBody(BaseModel):
    text: str = Field(default="", max_length=1000)


@router.post("/social-inbox/autopilot/approvals/{action_id}/approve", summary="Send a reply draft")
def approve(request: Request, body: ApproveBody, action_id: str = _id()):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="autopilot_decide", limit=_DECIDE_LIMIT)
    try:
        return utils.get_response(200, autopilot.approve(user_id, action_id, text=body.text))
    except Exception as exc:  # noqa: BLE001
        raise _mapped(request_id, exc) from exc


@router.post("/social-inbox/autopilot/approvals/{action_id}/reject", summary="Discard a reply draft")
def reject(request: Request, action_id: str = _id()):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="autopilot_decide", limit=_DECIDE_LIMIT)
    try:
        return utils.get_response(200, autopilot.reject(user_id, action_id))
    except Exception as exc:  # noqa: BLE001
        raise _mapped(request_id, exc) from exc


@router.get("/social-inbox/autopilot/activity", summary="Autopilot audit log")
def activity(
    request: Request,
    kind: str = Query(default="", max_length=80),
    status: str = Query(default="", max_length=80),
    platform: str = Query(default="", max_length=20, pattern=r"^[a-z]*$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    kinds = tuple(k.strip() for k in kind.split(",") if k.strip())
    statuses = tuple(s.strip() for s in status.split(",") if s.strip())
    try:
        return utils.get_response(200, autopilot.list_actions(
            user_id, statuses=statuses, kinds=kinds, platform=platform, limit=limit, offset=offset))
    except Exception as exc:  # noqa: BLE001
        raise _mapped(request_id, exc) from exc


@router.get("/social-inbox/leads", summary="Conversations with buying intent")
def leads(request: Request, status: str = Query(default="", max_length=12),
          limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10_000)):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        return utils.get_response(200, autopilot.list_leads(user_id, status=status, limit=limit, offset=offset))
    except Exception as exc:  # noqa: BLE001
        raise _mapped(request_id, exc) from exc


class LeadBody(BaseModel):
    status: str | None = Field(default=None, max_length=12)
    note: str | None = Field(default=None, max_length=1000)


@router.post("/social-inbox/leads/{lead_id}", summary="Update a lead")
def update_lead(request: Request, body: LeadBody, lead_id: str = _id()):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="autopilot_decide", limit=_DECIDE_LIMIT)
    try:
        return utils.get_response(200, autopilot.update_lead(user_id, lead_id, status=body.status, note=body.note))
    except Exception as exc:  # noqa: BLE001
        raise _mapped(request_id, exc) from exc
