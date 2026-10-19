"""Spend-policy HTTP domain — read/update the caller's budget + BYOK consent.

* ``GET /spend/policy``  -> {monthly_budget_micros, byok_allowed, period_spend_micros}
* ``PUT /spend/policy``  -> update budget cap and/or BYOK consent
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
    from app.domains.spend.service import SpendError, SpendPolicyService
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    SpendError = Exception  # type: ignore[assignment,misc]
    SpendPolicyService = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


class SpendPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_budget_micros: int | None = Field(default=None, ge=0)
    byok_allowed: bool | None = None
    spend_min_role: str | None = Field(
        default=None, pattern="^(owner|admin|member)$"
    )


def _require_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None or SpendPolicyService is None:
        logger.error(f"spend persistence unavailable ({request_id}): {_DB_IMPORT_ERROR}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


def _require_workspace_member(
    session: Any, workspace_id: str, user_id: str, request_id: str
) -> None:
    """Gate a workspace spend-policy read/write on membership (403 otherwise)."""
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


@router.get("/spend/policy", summary="Get spend policy + period spend")
def get_spend_policy(request: Request, workspace_id: str | None = None):
    """Return the caller's personal spend policy, or a workspace's (if a member)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    workspace_id = (workspace_id or "").strip() or None
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        svc = SpendPolicyService(session)
        if workspace_id:
            _require_workspace_member(session, workspace_id, user.id, request_id)
            data = svc.workspace_policy_view(workspace_id)
        else:
            data = svc.policy_view(user.id)
    return utils.get_response(200, data)


@router.put("/spend/policy", summary="Update spend policy")
def update_spend_policy(
    request: Request, body: SpendPolicyUpdate, workspace_id: str | None = None
):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    workspace_id = (workspace_id or "").strip() or None
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        svc = SpendPolicyService(session)
        if workspace_id:
            _require_workspace_member(session, workspace_id, user.id, request_id)
            # Managing a workspace's spend policy is an admin/owner action.
            from app.domains.spend.roles import MANAGE_POLICY
            from app.domains.spend.service import SpendError

            try:
                svc.assert_can(MANAGE_POLICY, workspace_id, user.id)
            except SpendError as exc:
                raise HttpException(
                    task_id=request_id,
                    status_code=exc.status_code,
                    message=f"{request_id}: {exc.message}",
                ) from exc
            data = svc.upsert_workspace_policy(
                workspace_id,
                monthly_budget_micros=body.monthly_budget_micros,
                byok_allowed=body.byok_allowed,
                spend_min_role=body.spend_min_role,
            )
        else:
            data = svc.upsert_policy(
                user.id,
                monthly_budget_micros=body.monthly_budget_micros,
                byok_allowed=body.byok_allowed,
            )
    return utils.get_response(200, data)
