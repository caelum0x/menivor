"""Workspace usage + entitlements v1 API controller (Billing Platform, Epic 3).

Mounted under ``/api/v1``. Both routes are USER-authenticated and TENANT-SCOPED:
the caller must be a member of the workspace (tenant isolation) — a non-member, or
a caller from another workspace, gets a clean ``403`` and can never read this
tenant's usage or entitlements.

Routes
------
* ``GET /me/workspaces/{id}/usage?period=YYYY-MM`` — the workspace's metered usage
  aggregate + per-metric overage for a billing month (defaults to the current month).
* ``GET /me/workspaces/{id}/entitlements``          — the caller's active-plan
  entitlement bundle for the workspace (falls back to base/free when no live sub).

Design notes
------------
* **Thin transport.** Aggregation + overage live in :mod:`app.services.metering`;
  entitlement resolution in :mod:`app.services.entitlements`. This controller
  resolves the caller, gates on membership, delegates, and envelopes.
* **Import-safe.** The service + persistence layers are pulled in behind guarded
  blocks; a missing layer degrades to a clean ``503`` at request time.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import EntitlementsResponse, UsageResponse
from app.utils import utils

# Guarded imports of the metering/entitlements services + RBAC + persistence. A
# partial environment degrades to a 503 rather than crashing at import time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.repositories import WorkspaceRepository
    from app.services import entitlements as entitlements_service
    from app.services import metering as metering_service
    from app.services import rbac

    _USAGE_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    entitlements_service = None  # type: ignore[assignment]
    metering_service = None  # type: ignore[assignment]
    rbac = None  # type: ignore[assignment]
    _USAGE_IMPORT_ERROR = exc

router = new_router()

# ``'YYYY-MM'`` — a period must be exactly this shape, or a 400 is returned.
_PERIOD_LEN: int = 7


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when the DB layer or the metering/entitlements services are absent."""
    _require_db(request_id)
    if (
        metering_service is None
        or entitlements_service is None
        or rbac is None
        or WorkspaceRepository is None
        or _USAGE_IMPORT_ERROR is not None
    ):
        logger.error(
            f"usage service unavailable, request_id: {request_id}, "
            f"error: {_USAGE_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: usage service is not available",
        )


def _load_workspace_or_404(session: Any, workspace_id: str, request_id: str) -> None:
    """Raise a clean ``404`` when the workspace does not exist (never a bare 403)."""
    if WorkspaceRepository(session).get(workspace_id) is None:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: workspace not found",
        )


def _require_member(session: Any, request: Request, workspace_id: str, request_id: str):
    """Resolve the caller + enforce workspace MEMBERSHIP (tenant isolation).

    Any member (any role) may read the tenant's usage/entitlements — this is the
    ``read`` gate. A caller with no membership row (including a caller from another
    workspace) is not in this tenant and gets a ``403``; an unknown workspace gets
    a ``404`` resolved up front so existence never leaks as a bare ``403``.
    """
    user = _resolve_user(request, session, request_id)
    _load_workspace_or_404(session, workspace_id, request_id)
    if not rbac.is_member(session, user.id, workspace_id):
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=(
                f"{request_id}: user {user.id} is not a member of "
                f"workspace {workspace_id}"
            ),
        )
    return user


def _validate_period(period: str, request_id: str) -> str:
    """Return a validated ``'YYYY-MM'`` period, or default to the current month.

    A blank period defaults to the current billing month; a malformed period is a
    clean ``400`` so a hostile value can never reach the aggregate.
    """
    normalized = (period or "").strip()
    if not normalized:
        return metering_service.current_period_ym()
    if len(normalized) != _PERIOD_LEN or normalized[4] != "-":
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: period must be 'YYYY-MM'",
        )
    year, _, month = normalized.partition("-")
    if not (year.isdigit() and month.isdigit()):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: period must be 'YYYY-MM'",
        )
    return normalized


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get(
    "/me/workspaces/{workspace_id}/usage",
    response_model=UsageResponse,
    summary="Read a workspace's metered usage + overage (tenant-scoped)",
)
def get_usage(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    period: str = Query(default="", description="Billing month 'YYYY-MM' (default: now)"),
):
    """Return the workspace's per-metric usage aggregate + overage for a period.

    Tenant-scoped: only a member of the workspace may read it (a caller from
    another workspace gets ``403``). ``overage`` compares each metric's usage to
    the workspace's plan limit (usage beyond the allotment).
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    resolved_period = _validate_period(period, request_id)

    with get_session() as session:
        _require_member(session, request, workspace_id, request_id)
        usage = metering_service.aggregate_usage(session, workspace_id, resolved_period)
        overages = metering_service.overage_for(session, workspace_id, resolved_period)
        overage_items = [
            {
                "metric": ov.metric,
                "used": int(ov.used),
                "limit": ov.limit,
                "overage": int(ov.overage),
            }
            for _, ov in sorted(overages.items())
        ]
        data = {
            "workspace_id": workspace_id,
            "period": resolved_period,
            "usage": {str(k): int(v) for k, v in usage.items()},
            "overage": overage_items,
        }

    return utils.get_response(200, data)


@router.get(
    "/me/workspaces/{workspace_id}/entitlements",
    response_model=EntitlementsResponse,
    summary="Read the caller's active-plan entitlements for a workspace (tenant-scoped)",
)
def get_entitlements(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return the workspace's LIVE-plan entitlement bundle (base/free when no sub).

    Tenant-scoped: only a member of the workspace may read it. ``entitlements``
    mirrors :data:`app.services.entitlements.PLAN_ENTITLEMENTS` for the resolved
    active plan (numeric limits + boolean capabilities).
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        _require_member(session, request, workspace_id, request_id)
        plan_key = entitlements_service.active_plan_key(session, workspace_id)
        bundle = entitlements_service.plan_entitlements(plan_key)
        data = {
            "workspace_id": workspace_id,
            "plan_key": plan_key,
            "entitlements": bundle,
        }

    return utils.get_response(200, data)
