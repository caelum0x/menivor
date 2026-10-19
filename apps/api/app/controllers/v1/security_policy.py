"""Enterprise workspace security-policy v1 API controller (Identity & SSO, Epic 2).

Exposes a workspace's enterprise login policy under ``/api/v1`` — force SSO, bound
session lifetime, restrict email domains, require MFA, restrict source IPs. Both
routes are gated by RBAC ``workspace.settings`` (owner/admin only); the write path
records an Epic-1 audit row.

Routes
------
* ``GET /me/workspaces/{id}/security`` — the current policy (``data: null`` when
  unset), gated by ``workspace.settings``.
* ``PUT /me/workspaces/{id}/security`` — partial update (only supplied fields are
  applied). Authorization is enforced INSIDE
  :func:`app.services.security_policy.set_policy` (which calls
  ``rbac.require_permission`` before any write) and the change is audited there.

Design notes
------------
* **Auth reused.** The canonical ``_resolve_user`` resolver from
  :mod:`app.controllers.v1.jobs` (Clerk JWT / ``x-api-key`` / per-user key) gates
  both routes; a missing DB layer degrades to a clean ``503``.
* **Tenant isolation.** ``rbac.require_permission`` verifies the caller is a
  member of THIS workspace before granting access — a member of one tenant can
  never read/write another tenant's policy.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from fastapi import Path, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    SecurityPolicyRequest,
    SecurityPolicyResponse,
)
from app.utils import utils

# Guarded imports of the security-policy service + persistence. A partial
# environment degrades to a 503 rather than crashing at import time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.repositories import WorkspaceRepository
    from app.services import rbac
    from app.services import security_policy as policy_service

    _POLICY_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    rbac = None  # type: ignore[assignment]
    policy_service = None  # type: ignore[assignment]
    _POLICY_IMPORT_ERROR = exc

router = new_router()


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when the DB layer or the security-policy service is unavailable."""
    _require_db(request_id)
    if policy_service is None or rbac is None or WorkspaceRepository is None:
        logger.error(
            f"security-policy service unavailable, request_id: {request_id}, "
            f"error: {_POLICY_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: security-policy service is not available",
        )


@contextmanager
def _map_service_errors(request_id: str) -> Iterator[None]:
    """Translate service-layer exceptions to HTTP errors.

    ``PermissionError`` (not a member / lacks ``workspace.settings``) -> ``403``;
    ``ValueError`` -> ``400``. :class:`HttpException` passes through untouched.
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
    """Return the workspace row, or raise a clean ``404`` when it does not exist."""
    workspace = WorkspaceRepository(session).get(workspace_id)
    if workspace is None:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: workspace not found",
        )
    return workspace


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
    except Exception:  # noqa: BLE001 - defensive
        return str(value)


def _policy_data(policy: Any, workspace_id: str) -> dict[str, Any]:
    """Serialise a :class:`SecurityPolicy` row into its public descriptor."""
    return {
        "workspace_id": workspace_id,
        "require_sso": bool(getattr(policy, "require_sso", False)),
        "session_timeout_min": int(getattr(policy, "session_timeout_min", 0) or 0),
        "allowed_email_domains": list(
            getattr(policy, "allowed_email_domains", None) or []
        ),
        "mfa_required": bool(getattr(policy, "mfa_required", False)),
        "ip_allowlist": list(getattr(policy, "ip_allowlist", None) or []),
        "created_at": _isoformat(getattr(policy, "created_at", None)),
        "updated_at": _isoformat(getattr(policy, "updated_at", None)),
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get(
    "/me/workspaces/{workspace_id}/security",
    response_model=SecurityPolicyResponse,
    summary="Read a workspace's security policy (requires workspace.settings)",
)
def get_security_policy(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return the workspace's security policy (``data: null`` when unset).

    Gated by ``workspace.settings`` (admin/owner) — a non-member or viewer gets a
    ``403`` (real workspace) / ``404`` (unknown id). Never mutates anything.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            rbac.require_permission(
                session, user.id, workspace_id, rbac.PERM_WORKSPACE_SETTINGS
            )
        policy = policy_service.get_policy(session, workspace_id)
        data = _policy_data(policy, workspace_id) if policy is not None else None

    return utils.get_response(200, data)


@router.put(
    "/me/workspaces/{workspace_id}/security",
    response_model=SecurityPolicyResponse,
    summary="Update a workspace's security policy (workspace.settings; audited)",
)
def put_security_policy(
    request: Request,
    body: SecurityPolicyRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Apply a partial security-policy update (only supplied fields are changed).

    Authorization (``workspace.settings``) is enforced inside
    :func:`app.services.security_policy.set_policy` BEFORE any write (a non-member
    or under-privileged member -> ``403``), and the change is audited there.
    Returns the persisted policy.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    # Only forward fields the caller actually supplied so a partial update never
    # clobbers an unrelated rule with a default.
    fields = {k: v for k, v in body.model_dump().items() if v is not None}

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            policy = policy_service.set_policy(
                session,
                workspace_id,
                user.id,
                actor_ip=_client_ip(request),
                **fields,
            )
        data = _policy_data(policy, workspace_id)

    return utils.get_response(200, data)
