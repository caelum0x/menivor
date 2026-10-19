"""Platform-admin v1 API controller (Access & Governance, Epic 1).

The ReelForge *staff* surface, mounted under ``/api/v1/admin`` — cross-tenant
listing of users, workspaces and jobs, plus short-lived, audited impersonation.
It is HARD-GATED on ``User.is_staff`` and is deliberately SEPARATE from the
per-workspace RBAC roles: a workspace ``owner`` is NOT a platform admin.

Routes
------
* ``GET  /admin/users``       — every user across every tenant (staff-only)
* ``GET  /admin/workspaces``  — every workspace across every tenant (staff-only)
* ``GET  /admin/jobs``        — every job across every tenant (staff-only)
* ``POST /admin/users/{id}/credits`` — support credit adjustment (MN6)
* ``POST /admin/jobs/{id}/refund``   — support refund of a job's debit (MN6)
* ``POST /admin/impersonate`` — mint a time-boxed impersonation token (staff-only,
  audited as ``admin.impersonated``)

Design notes
------------
* **Staff gate lives in the service.** Every :mod:`app.services.admin` function
  calls ``_require_staff`` first, raising :class:`PermissionError` for a
  non-staff caller — which this controller maps to ``403``. A missing/blank auth
  yields ``401`` from ``_resolve_user`` before that check runs.
* **No tenant leak to non-staff.** Because the service rejects before any
  cross-tenant read, a non-staff caller can never receive another tenant's data.
* ``limit`` is clamped to ``1..200`` and ``offset`` to ``>= 0``.
"""

from __future__ import annotations

import hmac
import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import (
    _require_db,
    _resolve_user,
    get_session,
)
from app.models.exception import HttpException
from app.models.schema import (
    AdminJobsResponse,
    AdminUsersResponse,
    AdminWorkspacesResponse,
    ImpersonateRequest,
    ImpersonationResponse,
)
from app.utils import utils

# Guarded import of the platform-admin service (see rbac.py for the import-safety
# rationale). A partial environment degrades to a 503.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.services import admin as admin_service

    _ADMIN_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    admin_service = None  # type: ignore[assignment]
    _ADMIN_IMPORT_ERROR = exc

router = new_router()

_DEFAULT_ADMIN_LIMIT: int = 50
_MAX_ADMIN_LIMIT: int = 200


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when either the DB layer or the admin service is absent."""
    _require_db(request_id)
    if admin_service is None or _ADMIN_IMPORT_ERROR is not None:
        logger.error(
            f"admin service unavailable, request_id: {request_id}, "
            f"error: {_ADMIN_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: platform-admin service is not available",
        )


@contextmanager
def _map_service_errors(request_id: str) -> Iterator[None]:
    """Translate service-layer exceptions to HTTP errors.

    ``PermissionError`` (not staff) maps to ``403``; ``ValueError`` (unknown
    impersonation target) maps to ``400``. :class:`HttpException` passes through.
    """
    try:
        yield
    except HttpException:
        raise
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
        )
    except ValueError as exc:
        raise HttpException(
            task_id=request_id, status_code=400, message=f"{request_id}: {exc}"
        )


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    """Clamp pagination to ``1..200`` / ``>= 0`` so a hostile page is always valid."""
    return max(1, min(_MAX_ADMIN_LIMIT, int(limit))), max(0, int(offset))


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort source IP of the caller for the audit row (never raises)."""
    try:
        client = getattr(request, "client", None)
        return getattr(client, "host", None) if client is not None else None
    except Exception:  # noqa: BLE001 - IP is best-effort telemetry
        return None


def _isoformat(value: Any) -> Optional[str]:
    """Best-effort ISO-8601 rendering of a timestamp; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001 - defensive: never fail a response on a timestamp
        return str(value)


def _user_data(user: Any) -> dict[str, Any]:
    """Serialize a :class:`User` row for the cross-tenant admin listing."""
    return {
        "id": user.id,
        "email": getattr(user, "email", None),
        "display_name": getattr(user, "display_name", None),
        "is_staff": bool(getattr(user, "is_staff", False)),
        "credits": int(getattr(user, "credits", 0) or 0),
        "created_at": _isoformat(getattr(user, "created_at", None)),
    }


def _workspace_data(workspace: Any) -> dict[str, Any]:
    """Serialize a :class:`Workspace` row for the cross-tenant admin listing."""
    return {
        "id": workspace.id,
        "name": getattr(workspace, "name", None),
        "owner_id": getattr(workspace, "owner_id", None),
        "created_at": _isoformat(getattr(workspace, "created_at", None)),
    }


def _job_data(job: Any) -> dict[str, Any]:
    """Serialize a :class:`Job` row for the cross-tenant admin listing."""
    return {
        "id": job.id,
        "user_id": getattr(job, "user_id", None),
        "kind": getattr(job, "kind", None),
        "state": getattr(job, "state", None),
        "progress": getattr(job, "progress", None),
        "created_at": _isoformat(getattr(job, "created_at", None)),
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get(
    "/admin/users",
    response_model=AdminUsersResponse,
    summary="List all users across every tenant (platform-admin only)",
)
def list_users(request: Request, limit: int = _DEFAULT_ADMIN_LIMIT, offset: int = 0):
    """Cross-tenant user listing (newest first). ``is_staff`` required -> 403 else."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    limit, offset = _clamp(limit, offset)

    with get_session() as session:
        admin_user = _resolve_user(request, session, request_id)
        with _map_service_errors(request_id):
            rows = admin_service.list_users(
                session, admin_user.id, limit=limit, offset=offset
            )
        items = [_user_data(u) for u in rows]

    return utils.get_response(200, items)


@router.get(
    "/admin/workspaces",
    response_model=AdminWorkspacesResponse,
    summary="List all workspaces across every tenant (platform-admin only)",
)
def list_workspaces(
    request: Request, limit: int = _DEFAULT_ADMIN_LIMIT, offset: int = 0
):
    """Cross-tenant workspace listing (newest first). ``is_staff`` required."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    limit, offset = _clamp(limit, offset)

    with get_session() as session:
        admin_user = _resolve_user(request, session, request_id)
        with _map_service_errors(request_id):
            rows = admin_service.list_workspaces(
                session, admin_user.id, limit=limit, offset=offset
            )
        items = [_workspace_data(w) for w in rows]

    return utils.get_response(200, items)


@router.get(
    "/admin/jobs",
    response_model=AdminJobsResponse,
    summary="List all jobs across every tenant (platform-admin only)",
)
def list_jobs(request: Request, limit: int = _DEFAULT_ADMIN_LIMIT, offset: int = 0):
    """Cross-tenant job listing (newest first). ``is_staff`` required."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    limit, offset = _clamp(limit, offset)

    with get_session() as session:
        admin_user = _resolve_user(request, session, request_id)
        with _map_service_errors(request_id):
            rows = admin_service.list_jobs(
                session, admin_user.id, limit=limit, offset=offset
            )
        items = [_job_data(j) for j in rows]

    return utils.get_response(200, items)


@router.post(
    "/admin/impersonate",
    response_model=ImpersonationResponse,
    summary="Mint a short-lived impersonation token (platform-admin only, audited)",
)
def impersonate(request: Request, body: ImpersonateRequest):
    """Mint a time-boxed impersonation token for ``body.user_id`` (staff-only).

    A non-staff caller gets ``403``; an unknown target gets ``400``. On success a
    time-boxed :class:`ImpersonationToken` is returned AND an append-only
    ``admin.impersonated`` audit row is written recording who impersonated whom.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    target_user_id = (body.user_id or "").strip()

    with get_session() as session:
        admin_user = _resolve_user(request, session, request_id)
        with _map_service_errors(request_id):
            token = admin_service.mint_impersonation(
                session,
                admin_user.id,
                target_user_id,
                client_ip=_client_ip(request),
            )
        ttl = int(
            (token.expires_at - token.issued_at).total_seconds()
        )
        data = {
            "token": token.token,
            "jti": token.jti,
            "admin_user_id": token.admin_user_id,
            "target_user_id": token.target_user_id,
            "scope": token.scope,
            "issued_at": _isoformat(token.issued_at),
            "expires_at": _isoformat(token.expires_at),
            "expires_in": ttl,
        }

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# Support ledger actions (MN6): support admin token + platform staff, audited,
# idempotent per (action, ref). See app.services.billing.support_actions.
# --------------------------------------------------------------------------- #
_SUPPORT_HEADER = "x-admin-token"
_MIN_SUPPORT_TOKEN_LEN = 24


class SupportCreditsRequest(BaseModel):
    amount: int = Field(..., ge=-1000, le=1000, description="Credits to add (+) or remove (-); not 0.")
    reason: str = Field(..., min_length=3, max_length=500)
    ref: str = Field(..., min_length=1, max_length=40, description="Idempotency key, e.g. the ticket id.")


class SupportRefundRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


def _support_token() -> str:
    return str(os.getenv("MENIVOR_SUPPORT_ADMIN_TOKEN", "") or "").strip()


def _require_support(request: Request, request_id: str) -> None:
    """Both gates: the support admin token header, then (in-session) is_staff."""
    expected = _support_token()
    if len(expected) < _MIN_SUPPORT_TOKEN_LEN:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: support actions are not configured")
    supplied = str(request.headers.get(_SUPPORT_HEADER, "") or "").strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HttpException(task_id=request_id, status_code=403,
                            message=f"{request_id}: admin token required")


def _support_data(result: Any) -> dict[str, Any]:
    return {
        "action": result.action,
        "ref": result.ref,
        "user_id": result.user_id,
        "delta": result.delta,
        "balance_after": result.balance_after,
        "replayed": result.replayed,
        "ledger_id": result.ledger_id,
    }


def _run_support(request: Request, action: Any) -> Any:
    from app.services.billing import support_actions

    request_id = base.get_task_id(request)
    _require_backend(request_id)
    _require_support(request, request_id)
    with get_session() as session:
        admin_user = _resolve_user(request, session, request_id)
        with _map_service_errors(request_id):
            admin_service._require_staff(session, admin_user.id)
        try:
            result = action(session, admin_user.id)
        except support_actions.SupportActionError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status, message=f"{request_id}: {exc}")
        data = _support_data(result)
    logger.info(f"support action {data['action']} ref={data['ref']} by {admin_user.id} replayed={data['replayed']}")
    return utils.get_response(200, data)


@router.post("/admin/users/{user_id}/credits", summary="Support: add or remove a user's credits (audited)")
def support_adjust_credits(request: Request, user_id: str, body: SupportCreditsRequest):
    from app.services.billing import support_actions

    return _run_support(request, lambda session, admin_id: support_actions.adjust_credits(
        session, admin_id=admin_id, user_id=user_id.strip(), amount=body.amount, reason=body.reason, ref=body.ref,
    ))


@router.post("/admin/jobs/{job_id}/refund", summary="Support: refund a job's credit debit (audited, once)")
def support_refund_job(request: Request, job_id: str, body: SupportRefundRequest):
    from app.services.billing import support_actions

    return _run_support(request, lambda session, admin_id: support_actions.refund_job(
        session, admin_id=admin_id, job_id=job_id.strip(), reason=body.reason,
    ))
