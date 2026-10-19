"""Approvals feed HTTP surface (owner-scoped; Rally's approvals hub reads it).

    GET  /approvals                     list (default ``status=pending``; ``all`` for history)
    GET  /approvals/count               pending count (cheap; no source sync)
    GET  /approvals/settings            opt-in sources (capture / catalog suggestions; default off)
    PUT  /approvals/settings            turn opt-in sources on or off
    GET  /approvals/{item_id}           one item
    POST /approvals/{item_id}/approve   approve (optionally with edits); delegates to the source
    POST /approvals/{item_id}/reject    reject; never posts, sends or spends

Auth is the normal principal chain: a Clerk/Supabase bearer from the web app,
or the user's own Menivor API key in ``x-api-key`` (what Rally stores when the
user links Menivor). Every read and decision is scoped to that user.

Decisions are idempotent: repeating the same decision returns 200 with the
recorded item; the opposite decision on a decided item returns 409.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, Path, Query, Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.approvals import service
from app.domains.approvals import settings as feed_settings
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_ID = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
_DECIDE_LIMIT = 300
_LIST_LIMIT = 600
_WINDOW_S = 3600


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    note: str = Field(default="", max_length=1000)
    #: Who is deciding from where ("web", "rally", "api", "mobile").
    via: str = Field(default="api", max_length=16)
    #: Approve only: edited fields (the item's ``payload.editable_fields``), e.g. ``{"text": "..."}``.
    edits: Optional[dict[str, Any]] = None


def _error(request_id: str, status_code: int, message: str, data: Any = None) -> HttpException:
    return HttpException(task_id=request_id, status_code=status_code, message=f"{request_id}: {message}", data=data)


def _caller(request: Request, request_id: str) -> str:
    require_database(request_id)
    with get_session() as session:
        return str(resolve_principal(request, session, request_id).id)


def _mapped(request_id: str, exc: service.ApprovalError) -> HttpException:
    return _error(request_id, exc.status_code, str(exc), {"item": exc.item} if exc.item else None)


@router.get("/approvals", summary="Pending approvals: social reply drafts, held posts, budget proposals")
def list_approvals(
    request: Request,
    status: str = Query(default="pending", max_length=16),
    source: str = Query(default="", max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"approvals:list:{user_id}", limit=_LIST_LIMIT, window_s=_WINDOW_S)
    try:
        data = service.list_items(user_id, status=status, source=source, limit=limit, offset=offset)
    except service.ApprovalError as exc:
        raise _mapped(request_id, exc) from exc
    return utils.get_response(200, data)


@router.get("/approvals/count", summary="Number of pending approvals")
def count_approvals(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        count = service.pending_count(user_id)
    except service.ApprovalError as exc:
        raise _mapped(request_id, exc) from exc
    return utils.get_response(200, {"pending_count": count})


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    #: Opt-in scanned sources, e.g. ``{"capture_publish": true, "catalog_import": false}``.
    auto_sources: dict[str, bool] = Field(default_factory=dict)


@router.get("/approvals/settings", summary="Which sources may add approval items on their own")
def get_approval_settings(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        return utils.get_response(200, feed_settings.get_settings(user_id))
    except feed_settings.SettingsError as exc:
        raise _error(request_id, exc.status_code, str(exc)) from exc


@router.put("/approvals/settings", summary="Turn capture / catalog suggestions on or off (default off)")
def put_approval_settings(request: Request, body: SettingsBody = Body(...)):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"approvals:settings:{user_id}", limit=_DECIDE_LIMIT, window_s=_WINDOW_S)
    try:
        return utils.get_response(200, feed_settings.update_settings(user_id, body.auto_sources))
    except feed_settings.SettingsError as exc:
        raise _error(request_id, exc.status_code, str(exc)) from exc


@router.get("/approvals/{item_id}", summary="One approval item")
def get_approval(request: Request, item_id: str = _ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        return utils.get_response(200, service.get_item(user_id, item_id))
    except service.ApprovalError as exc:
        raise _mapped(request_id, exc) from exc


def _decide(request: Request, item_id: str, decision: str, body: DecisionBody | None) -> dict:
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"approvals:decide:{user_id}", limit=_DECIDE_LIMIT, window_s=_WINDOW_S)
    body = body or DecisionBody()
    try:
        outcome = service.decide(user_id, item_id, decision, actor=user_id, via=body.via, note=body.note,
                                 edits=body.edits)
    except service.ApprovalError as exc:
        raise _mapped(request_id, exc) from exc
    except Exception as exc:  # noqa: BLE001 - unexpected persistence failure
        logger.error(f"approvals decide failed, request_id: {request_id}: {exc}")
        raise _error(request_id, 500, "could not record the decision") from exc
    return utils.get_response(200, outcome)


@router.post("/approvals/{item_id}/approve", summary="Approve an item (runs the source's own action)")
def approve(request: Request, item_id: str = _ID, body: Optional[DecisionBody] = Body(default=None)):
    return _decide(request, item_id, service.APPROVE, body)


@router.post("/approvals/{item_id}/reject", summary="Reject an item (nothing is posted or spent)")
def reject(request: Request, item_id: str = _ID, body: Optional[DecisionBody] = Body(default=None)):
    return _decide(request, item_id, service.REJECT, body)
