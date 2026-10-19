"""Enterprise audit-trail v1 API controller (Access & Governance, Epic 1).

Exposes the tenant-scoped, APPEND-ONLY audit trail under ``/api/v1``. There is
deliberately only a read endpoint — the trail is written by the governance
services (role changes, impersonation, …) and is tamper-evident by construction:
no create/update/delete API exists here.

Route
-----
* ``GET /me/workspaces/{id}/audit?limit=&offset=`` — a workspace's audit rows,
  newest first, gated by ``audit.read`` and strictly tenant-scoped.

Design notes
------------
* **Authorization first, then read.** :func:`app.services.audit.query` calls
  ``rbac.require_permission(..., audit.read)`` BEFORE reading any row, so a
  non-member or under-privileged member is rejected with ``403`` before a single
  row is touched. The query then filters strictly on ``workspace_id`` — a member
  of one tenant can never read another tenant's trail.
* **Auth is reused.** The canonical ``_resolve_user`` resolver from
  :mod:`app.controllers.v1.jobs` (Clerk JWT / ``x-api-key`` / per-user key) gates
  every route; a missing DB layer degrades to a clean ``503``.
* ``limit`` is clamped to ``1..100`` and ``offset`` to ``>= 0`` so a hostile page
  can never produce an invalid query or an unbounded scan.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from fastapi import Path, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import (
    _require_db,
    _resolve_user,
    get_session,
)
from app.models.exception import HttpException
from app.models.schema import AuditResponse
from app.utils import utils

# Guarded import of the audit service + persistence (see rbac.py for the rationale
# of the import-safety guard). A partial environment degrades to a 503.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.repositories import WorkspaceRepository
    from app.services import audit as audit_service

    _AUDIT_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    audit_service = None  # type: ignore[assignment]
    _AUDIT_IMPORT_ERROR = exc

router = new_router()

_DEFAULT_AUDIT_LIMIT: int = 50
_MAX_AUDIT_LIMIT: int = 100


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when either the DB layer or the audit service is absent."""
    _require_db(request_id)
    if audit_service is None or _AUDIT_IMPORT_ERROR is not None:
        logger.error(
            f"audit service unavailable, request_id: {request_id}, "
            f"error: {_AUDIT_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: audit service is not available",
        )


@contextmanager
def _map_service_errors(request_id: str) -> Iterator[None]:
    """Translate service-layer exceptions to HTTP errors.

    ``PermissionError`` (not a member / lacks ``audit.read``) maps to ``403``;
    ``ValueError`` maps to ``400``. :class:`HttpException` passes through.
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


def _load_workspace_or_404(session: Any, workspace_id: str, request_id: str):
    """Return the workspace row, or raise a ``404`` when it does not exist."""
    workspace = WorkspaceRepository(session).get(workspace_id)
    if workspace is None:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: workspace not found",
        )
    return workspace


def _isoformat(value: Any) -> Optional[str]:
    """Best-effort ISO-8601 rendering of a timestamp; ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001 - defensive: never fail a response on a timestamp
        return str(value)


def _entry_data(entry: Any) -> dict[str, Any]:
    """Serialize an :class:`AuditLog` row into a JSON-safe descriptor.

    The ORM attribute for the opaque per-event JSON is ``meta`` (DB column
    ``metadata``); it is exposed under the ``metadata`` key here.
    """
    return {
        "id": entry.id,
        "workspace_id": entry.workspace_id,
        "actor_user_id": entry.actor_user_id,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "metadata": dict(getattr(entry, "meta", None) or {}),
        "ip": entry.ip,
        "created_at": _isoformat(getattr(entry, "created_at", None)),
    }


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
@router.get(
    "/me/workspaces/{workspace_id}/audit",
    response_model=AuditResponse,
    summary="Read a workspace's audit trail (requires audit.read; tenant-scoped)",
)
def list_audit(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    limit: int = _DEFAULT_AUDIT_LIMIT,
    offset: int = 0,
):
    """Return a workspace's audit rows (newest first), gated by ``audit.read``.

    The caller must be a member holding ``audit.read`` (admin/owner) — a
    non-member or under-privileged member gets a ``403`` before any row is read;
    an unknown workspace id gets a clean ``404``. ``limit`` is clamped to
    ``1..100`` and ``offset`` to ``>= 0``. Strictly tenant-scoped: only rows for
    ``workspace_id`` are ever returned.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    limit = max(1, min(_MAX_AUDIT_LIMIT, int(limit)))
    offset = max(0, int(offset))

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            rows = audit_service.query(
                session, workspace_id, user.id, limit=limit, offset=offset
            )
        items = [_entry_data(entry) for entry in rows]

    return utils.get_response(200, items)
