"""Marketplace usage-analytics HTTP surface.

* ``GET /insights/usage?days=30[&workspace_id=…]`` — cost attribution by
  model / provider / stage / day for the caller (or a workspace they belong to).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

try:
    from app.core.auth import resolve_principal
    from app.domains.insights.usage import UsageAnalyticsService
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    UsageAnalyticsService = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


def _require_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None or UsageAnalyticsService is None:
        logger.error(f"usage insights unavailable ({request_id}): {_DB_IMPORT_ERROR}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


@router.get("/insights/usage", summary="Usage cost attribution (model/provider/stage/day)")
def usage_summary(request: Request, days: int = 30, workspace_id: str | None = None):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    workspace_id = (workspace_id or "").strip() or None
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if workspace_id:
            _require_workspace_member(session, workspace_id, user.id, request_id)
        data = UsageAnalyticsService(session).summary(
            user.id, workspace_id=workspace_id, days=days
        )
    return utils.get_response(200, data)


def _require_workspace_member(
    session: Any, workspace_id: str, user_id: str, request_id: str
) -> None:
    try:
        from app.services import workspaces as ws_service
    except Exception as exc:  # noqa: BLE001 - workspaces layer optional
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: workspaces service is not available",
        ) from exc
    if ws_service.get_membership(session, workspace_id, user_id) is None:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: not a member of this workspace",
        )
