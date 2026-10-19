"""Workspace invoices + platform revenue v1 API controller (Billing, Epic 3).

Two audiences, two isolation rules — both mounted under ``/api/v1``:

* ``GET /me/workspaces/{id}/invoices`` — a workspace's invoices, TENANT-SCOPED and
  RBAC-gated on ``billing.manage``. No endpoint here ever returns another tenant's
  invoices (a caller from another workspace gets ``403``).
* ``GET /admin/revenue``              — the platform-wide revenue summary. This is
  the ONLY cross-tenant read and is HARD-GATED on ``User.is_staff`` (Epic 1); a
  non-staff caller gets ``403`` before any aggregate runs.

Design notes
------------
* **Thin transport.** Listing + the staff-gated revenue aggregate live in
  :mod:`app.services.invoicing`; this controller resolves the caller, gates, and
  envelopes. All money is integer minor units (cents) — never a float.
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
from app.models.schema import InvoicesResponse, RevenueResponse
from app.utils import utils

# Guarded imports of the invoicing service + RBAC + persistence. A partial
# environment degrades to a 503 rather than crashing at import time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.repositories import WorkspaceRepository
    from app.services import invoicing as invoicing_service
    from app.services import rbac

    _INV_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    invoicing_service = None  # type: ignore[assignment]
    rbac = None  # type: ignore[assignment]
    _INV_IMPORT_ERROR = exc

router = new_router()

_DEFAULT_INVOICE_LIMIT: int = 50
_MAX_INVOICE_LIMIT: int = 200


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when the DB layer or the invoicing service is unavailable."""
    _require_db(request_id)
    if (
        invoicing_service is None
        or rbac is None
        or WorkspaceRepository is None
        or _INV_IMPORT_ERROR is not None
    ):
        logger.error(
            f"invoicing service unavailable, request_id: {request_id}, "
            f"error: {_INV_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: invoicing service is not available",
        )


def _load_workspace_or_404(session: Any, workspace_id: str, request_id: str) -> None:
    """Raise a clean ``404`` when the workspace does not exist (never a bare 403)."""
    if WorkspaceRepository(session).get(workspace_id) is None:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: workspace not found",
        )


def _require_billing_manage(
    session: Any, request: Request, workspace_id: str, request_id: str
):
    """Resolve the caller + gate on ``billing.manage`` (403 else; 404 unknown ws).

    Tenant isolation is enforced by :func:`rbac.require_permission` — a non-member
    (including a caller from another workspace) can never read this tenant's
    invoices.
    """
    user = _resolve_user(request, session, request_id)
    _load_workspace_or_404(session, workspace_id, request_id)
    try:
        rbac.require_permission(
            session, user.id, workspace_id, rbac.PERM_BILLING_MANAGE
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
        )
    return user


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    """Clamp pagination to ``1..200`` / ``>= 0`` so a hostile page is always valid."""
    return max(1, min(_MAX_INVOICE_LIMIT, int(limit))), max(0, int(offset))


def _isoformat(value: Any) -> Optional[str]:
    """Best-effort ISO-8601 rendering of a timestamp; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001 - defensive: never fail a response on a timestamp
        return str(value)


def _line_item_data(row: Any) -> dict[str, Any]:
    """Serialize an :class:`InvoiceLineItem` row into a JSON-safe descriptor."""
    return {
        "id": row.id,
        "description": getattr(row, "description", "") or "",
        "quantity": int(getattr(row, "quantity", 0) or 0),
        "amount_cents": int(getattr(row, "amount_cents", 0) or 0),
        "created_at": _isoformat(getattr(row, "created_at", None)),
    }


def _invoice_data(row: Any) -> dict[str, Any]:
    """Serialize an :class:`Invoice` row (+ its lines) into a JSON-safe descriptor.

    Called inside the DB session so the ``line_items`` relationship is loadable;
    amounts are integer minor units (cents), never a float.
    """
    line_items = [_line_item_data(li) for li in (getattr(row, "line_items", None) or [])]
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "provider_ref": getattr(row, "provider_ref", "") or "",
        "amount_cents": int(getattr(row, "amount_cents", 0) or 0),
        "currency": getattr(row, "currency", "usd") or "usd",
        "status": getattr(row, "status", "draft") or "draft",
        "period_start": _isoformat(getattr(row, "period_start", None)),
        "period_end": _isoformat(getattr(row, "period_end", None)),
        "created_at": _isoformat(getattr(row, "created_at", None)),
        "line_items": line_items,
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get(
    "/me/workspaces/{workspace_id}/invoices",
    response_model=InvoicesResponse,
    summary="List a workspace's invoices (billing.manage; tenant-scoped)",
)
def list_invoices(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    limit: int = Query(default=_DEFAULT_INVOICE_LIMIT, ge=1, le=_MAX_INVOICE_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Return the workspace's invoices (newest first), TENANT-SCOPED.

    RBAC-gated on ``billing.manage`` — a ``viewer`` gets ``403`` and a caller from
    another workspace can never receive these invoices.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    limit, offset = _clamp(limit, offset)

    with get_session() as session:
        _require_billing_manage(session, request, workspace_id, request_id)
        rows = invoicing_service.list_invoices(
            session, workspace_id, limit=limit, offset=offset
        )
        items = [_invoice_data(r) for r in rows]

    return utils.get_response(200, items)


@router.get(
    "/admin/revenue",
    response_model=RevenueResponse,
    summary="Platform-wide revenue summary (platform-admin / is_staff only)",
)
def get_revenue(
    request: Request,
    status: str = Query(default="paid", description="Invoice status to sum (realized revenue)"),
):
    """Return the cross-tenant platform revenue summary — ``is_staff`` ONLY.

    HARD-GATED on ``User.is_staff`` (Epic 1) inside the service: a non-staff caller
    gets ``403`` before any aggregate runs. Returns ``{revenue_cents,
    credits_granted, net_cents}`` (integer minor units).
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        admin_user = _resolve_user(request, session, request_id)
        try:
            summary = invoicing_service.revenue_summary(
                session, admin_user.id, status=(status or "paid").strip().lower()
            )
        except PermissionError as exc:
            raise HttpException(
                task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
            )
        data = {
            "revenue_cents": int(summary.get("revenue_cents", 0)),
            "credits_granted": int(summary.get("credits_granted", 0)),
            "net_cents": int(summary.get("net_cents", 0)),
        }

    return utils.get_response(200, data)
