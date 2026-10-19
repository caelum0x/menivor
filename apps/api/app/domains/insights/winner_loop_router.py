"""Remake-winner loop HTTP surface (owner-scoped).

    GET  /insights/loops                      winners board + loops + candidate projects
    GET  /insights/loops/{batch_id}           project detail: ranked variants, why it won, timeline
    PUT  /insights/loops/{batch_id}           set mode (off|manual|auto), platforms, spend cap, window
    POST /insights/loops/{batch_id}/check     read the numbers now (early read before the window)
    POST /insights/loops/{batch_id}/remake    one-click "Remake winner" (3 new variants)

Auto-publishing is gated by the existing publishing launch flag, the creator's
native connections and the Pro entitlement (the same gates as "Publish now");
remakes go through the same generation-access and credit debit rules as
``POST /jobs``.
"""

from __future__ import annotations

from fastapi import Path, Request
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

from .remake import RemakeError, remake_winner
from .winner_loop_service import LoopNotFound, advance, configure
from .winner_loop_state import LoopConfigError, utcnow
from .winner_loop_views import loop_board, loop_detail

router = new_router()

_CHECK_LIMIT = 30
_REMAKE_LIMIT = 10
_WINDOW_S = 3600
_BATCH_ID = Path(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class LoopConfigBody(BaseModel):
    mode: str = Field(..., description="off | manual | auto")
    platforms: list[str] = Field(default_factory=list, max_length=3)
    spend_cap_credits: int | None = Field(default=None, ge=0, le=1000)
    check_after_hours: int | None = Field(default=None, ge=24, le=168)
    min_views: int | None = Field(default=None, ge=0, le=100_000)


class RemakeBody(BaseModel):
    accept_low_confidence: bool = False


def _error(request_id: str, status: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}")


def _caller(request: Request, request_id: str) -> str:
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        return str(user.id)


@router.get("/insights/loops", summary="Winners board and remake-winner loops")
def list_loops(request: Request):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        data = loop_board(session, str(user.id), utcnow())
    return utils.get_response(200, data)


@router.get("/insights/loops/{batch_id}", summary="One project's loop: ranking, why it won, timeline")
def get_loop(request: Request, batch_id: str = _BATCH_ID):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            data = loop_detail(session, str(user.id), batch_id)
        except LoopNotFound as exc:
            raise _error(request_id, 404, "project not found") from exc
    return utils.get_response(200, data)


@router.put("/insights/loops/{batch_id}", summary="Configure a project's remake-winner loop")
def put_loop(request: Request, body: LoopConfigBody, batch_id: str = _BATCH_ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    mode = body.mode.strip().lower()
    if mode != "off" and body.platforms:
        # Auto-publishing uses the native publish path: same launch flag, Pro
        # entitlement and connected-account checks as "Publish now".
        from app.core.launch import require_publishing_enabled
        from app.domains.publishing.native_service import NativePublishError, require_native_connections
        from app.services.billing.pro_access import require_pro_action

        require_publishing_enabled(request_id)
        require_pro_action(user_id, request_id, action="auto-publish")
        try:
            require_native_connections(user_id, body.platforms)
        except NativePublishError as exc:
            raise _error(request_id, exc.status_code, str(exc)) from exc
    try:
        configure(
            user_id, batch_id,
            mode=mode, platforms=body.platforms, spend_cap_credits=body.spend_cap_credits,
            check_after_hours=body.check_after_hours, min_views=body.min_views,
        )
    except LoopNotFound as exc:
        raise _error(request_id, 404, "project not found") from exc
    except LoopConfigError as exc:
        raise _error(request_id, 422, str(exc)) from exc
    if mode != "off":
        try:
            # Queue already-rendered variants right away instead of waiting for the tick.
            advance(user_id, batch_id, allow_auto_remake=False)
        except Exception as exc:  # noqa: BLE001 - config is saved; the beat tick retries
            logger.warning(f"initial loop advance failed for {batch_id}: {exc}")
    with get_session() as session:
        data = loop_detail(session, user_id, batch_id)
    return utils.get_response(200, data)


@router.post("/insights/loops/{batch_id}/check", summary="Read the variants' numbers now")
def check_loop(request: Request, batch_id: str = _BATCH_ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"winner_loop_check:{user_id}", limit=_CHECK_LIMIT, window_s=_WINDOW_S)
    try:
        advance(user_id, batch_id, force_check=True)
    except LoopNotFound as exc:
        raise _error(request_id, 404, "project not found") from exc
    with get_session() as session:
        data = loop_detail(session, user_id, batch_id)
    if not data["configured"]:
        raise _error(request_id, 409, "turn the loop on for this project first")
    return utils.get_response(200, data)


@router.post("/insights/loops/{batch_id}/remake", summary="Remake the winner as 3 new variants")
def remake_loop(request: Request, body: RemakeBody, batch_id: str = _BATCH_ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    enforce_rate_limit(request, f"winner_loop_remake:{user_id}", limit=_REMAKE_LIMIT, window_s=_WINDOW_S)
    from app.core.capabilities import require_generation_access

    def _guard(session, credits: int) -> None:
        require_generation_access(request, session, user_id, "reel", credits, request_id)

    try:
        result = remake_winner(
            user_id, batch_id, source="manual",
            accept_low_confidence=body.accept_low_confidence, generation_guard=_guard,
        )
    except RemakeError as exc:
        raise _error(request_id, exc.status_code, str(exc)) from exc
    return utils.get_response(200, result.to_record())


__all__ = ["router"]
