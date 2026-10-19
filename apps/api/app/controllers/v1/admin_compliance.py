"""Platform-admin compliance controller (Compliance, Epic 5).

The ReelForge *staff* compliance surface, mounted under ``/api/v1/admin`` — a
cross-tenant view of erasure requests + retention posture, plus operator-initiated
erasure. It is HARD-GATED on ``User.is_staff`` (Epic 1) and is deliberately
SEPARATE from per-workspace RBAC: a workspace ``owner`` is NOT a platform admin.

Routes
------
* ``GET  /admin/erasure-requests`` — every right-to-erasure request across every
  tenant (staff-only), newest first.
* ``POST /admin/erasure/{user_id}`` — operator-initiated erasure of a target user
  (staff-only, audited with the operator as actor).
* ``GET  /admin/retention``        — every configured workspace retention policy
  (staff-only), an operator's retention-posture overview.

Design notes
------------
* **Staff gate.** Every route resolves the caller and then requires
  ``user.is_staff`` (:func:`_require_staff`), raising ``403`` otherwise — the same
  hard gate as :mod:`app.controllers.v1.admin`. A missing/blank auth yields ``401``
  from ``_resolve_user`` before that check runs, so a non-staff caller can never
  reach the cross-tenant data.
* **Import-safe.** The persistence + compliance layers are imported optionally;
  a partial environment degrades to a clean ``503`` instead of an ImportError.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Request
from loguru import logger
from sqlalchemy import select

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    AdminErasureRequestsResponse,
    AdminRetentionResponse,
    ErasureRequestResponse,
)
from app.utils import utils

# Guarded import of the persistence models/repositories + compliance erasure
# service. A partial environment degrades to a clean 503 at request time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.models import ErasureRequest
    from app.models.db.repositories import RetentionPolicyRepository
    from app.services.compliance import erasure as erasure_service

    _ADMIN_COMPLIANCE_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    ErasureRequest = None  # type: ignore[assignment,misc]
    RetentionPolicyRepository = None  # type: ignore[assignment,misc]
    erasure_service = None  # type: ignore[assignment]
    _ADMIN_COMPLIANCE_IMPORT_ERROR = exc

router = new_router()

_DEFAULT_LIMIT: int = 50
_MAX_LIMIT: int = 200


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when the DB layer or the compliance erasure service is absent."""
    _require_db(request_id)
    if _ADMIN_COMPLIANCE_IMPORT_ERROR is not None or erasure_service is None:
        logger.error(
            f"admin compliance service unavailable, request_id: {request_id}, "
            f"error: {_ADMIN_COMPLIANCE_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: compliance service is not available",
        )


def _require_staff(user: Any, request_id: str) -> None:
    """Raise 403 unless ``user`` is platform staff (the single hard gate).

    Platform-admin is SEPARATE from per-workspace RBAC — a workspace owner is not
    staff. A non-staff caller can never reach the cross-tenant compliance data.
    """
    if not bool(getattr(user, "is_staff", False)):
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: platform-admin (is_staff) access required",
        )


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    """Clamp pagination to ``1..200`` / ``>= 0`` so a hostile page is always valid."""
    return max(1, min(_MAX_LIMIT, int(limit))), max(0, int(offset))


def _isoformat(value: Any) -> Optional[str]:
    """Best-effort ISO-8601 rendering of a timestamp; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001 - never fail a response on a timestamp
        return str(value)


def _erasure_data(row: Any) -> dict[str, Any]:
    """Serialize an :class:`ErasureRequest` row for the cross-tenant listing."""
    return {
        "id": row.id,
        "user_id": row.user_id,
        "status": row.status,
        "scope": row.scope,
        "requested_at": _isoformat(getattr(row, "requested_at", None)),
        "completed_at": _isoformat(getattr(row, "completed_at", None)),
    }


def _policy_data(policy: Any) -> dict[str, Any]:
    """Serialize a :class:`RetentionPolicy` row for the overview."""
    return {
        "workspace_id": policy.workspace_id,
        "jobs_retention_days": policy.jobs_retention_days,
        "assets_retention_days": policy.assets_retention_days,
        "created_at": _isoformat(getattr(policy, "created_at", None)),
        "updated_at": _isoformat(getattr(policy, "updated_at", None)),
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get(
    "/admin/erasure-requests",
    response_model=AdminErasureRequestsResponse,
    summary="List all erasure requests across every tenant (platform-admin only)",
)
def list_erasure_requests(
    request: Request, limit: int = _DEFAULT_LIMIT, offset: int = 0
):
    """Cross-tenant erasure-request listing (newest first). ``is_staff`` required."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    limit, offset = _clamp(limit, offset)

    with get_session() as session:
        admin_user = _resolve_user(request, session, request_id)
        _require_staff(admin_user, request_id)
        rows = list(
            session.execute(
                select(ErasureRequest)
                .order_by(
                    ErasureRequest.requested_at.desc(),
                    ErasureRequest.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            ).scalars().all()
        )
        items = [_erasure_data(r) for r in rows]
    return utils.get_response(200, items)


@router.post(
    "/admin/erasure/{user_id}",
    response_model=ErasureRequestResponse,
    summary="Operator-initiated erasure of a target user (platform-admin only)",
)
def admin_erase_user(
    request: Request,
    user_id: str = Path(..., description="Target user id to erase"),
):
    """Anonymize ``user_id``'s PII in place (staff-only, audited with the operator).

    Staff-gated: a non-staff caller gets ``403`` and nothing is erased. An unknown
    target is a ``400``. On success the target's PII is tombstoned, credentials
    revoked and job scripts/prompts blanked — while preserving financial/audit
    records — and an append-only audit row records that THIS operator ran it.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    target_user_id = (user_id or "").strip()

    with get_session() as session:
        admin_user = _resolve_user(request, session, request_id)
        _require_staff(admin_user, request_id)
        try:
            erased = erasure_service.erase_user(
                session, target_user_id, actor_user_id=admin_user.id
            )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id, status_code=400, message=f"{request_id}: {exc}"
            )
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - anonymization failure -> 502
            logger.error(
                f"admin erasure failed for {target_user_id}, "
                f"request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to erase target user",
            )
        data = _erasure_data(erased)
    return utils.get_response(200, data)


@router.get(
    "/admin/retention",
    response_model=AdminRetentionResponse,
    summary="Cross-tenant retention-policy overview (platform-admin only)",
)
def retention_overview(request: Request):
    """Every configured workspace retention policy (staff-only overview)."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        admin_user = _resolve_user(request, session, request_id)
        _require_staff(admin_user, request_id)
        policies = RetentionPolicyRepository(session).list_all()
        items = [_policy_data(p) for p in policies]
    return utils.get_response(200, items)
