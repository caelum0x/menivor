"""Enterprise RBAC v1 API controller (Access & Governance, Epic 1).

Exposes the Casbin-backed role/permission surface under ``/api/v1``. Every
authorization decision is delegated to :mod:`app.services.rbac` (the pycasbin
enforcer) and :mod:`app.services.audit` — this controller is a thin HTTP adapter
that resolves the caller, confirms the workspace exists (``404`` otherwise, so a
non-existent workspace never leaks as a bare ``403``), and maps service-layer
exceptions to HTTP status codes.

Routes
------
* ``GET   /me/workspaces/{id}/members``               — roster + roles (member only)
* ``PATCH /me/workspaces/{id}/members/{user_id}/role``— change a member's role
  (requires ``members.manage``; cannot demote the last owner; cannot grant a role
  above the caller's own) — writes an append-only audit row
* ``GET   /me/permissions?workspace_id=``             — caller's effective perms

Design notes
------------
* **Tenant isolation is the #1 invariant.** Reading the roster requires the
  caller be a *member* of the workspace (``rbac.require_permission`` with
  ``jobs.read`` — the floor permission every role holds), and every mutation is
  gated by ``rbac.require_permission`` before any write. No endpoint returns
  another tenant's data.
* **Auth is reused, not reinvented.** Every route runs the canonical
  ``_resolve_user`` resolver from :mod:`app.controllers.v1.jobs` (Clerk JWT /
  ``x-api-key`` / per-user key). A missing DB layer degrades to a clean ``503``.
* **Append-only audit.** A successful role change records exactly one
  ``members.role_changed`` row via :func:`app.services.audit.record`; there is no
  update/delete path.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from fastapi import Path, Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the guarded persistence import + auth helpers from jobs.py (the module
# that owns the canonical guard block). When the DB layer is absent these are
# ``None`` and ``_require_db`` raises a 503 — this controller stays import-safe.
from app.controllers.v1.jobs import (
    _require_db,
    _resolve_user,
    get_session,
)
from app.models.exception import HttpException
from app.models.schema import (
    MemberRoleResponse,
    MembersResponse,
    PermissionsResponse,
    RoleUpdateRequest,
)
from app.utils import utils

# Guarded import of the RBAC/audit services + persistence. Coupled to the same
# SQLAlchemy/ORM dependencies as the jobs DB import; guarded independently so a
# partial environment degrades to a 503 instead of crashing at import time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.models import User
    from app.models.db.repositories import WorkspaceRepository
    from app.services import audit as audit_service
    from app.services import rbac

    _RBAC_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    User = None  # type: ignore[assignment,misc]
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    audit_service = None  # type: ignore[assignment]
    rbac = None  # type: ignore[assignment]
    _RBAC_IMPORT_ERROR = exc

router = new_router()

# Relative rank of each Enterprise role, used to enforce "a caller may not grant a
# role higher than their own". ``owner > admin > {editor, billing} > viewer``;
# ``billing`` is a standalone finance role ranked alongside ``editor`` (both are
# strictly below ``admin``). An unknown/legacy role ranks 0 (lowest), so it can
# never be used to out-rank a real role.
_ROLE_RANK: dict[str, int] = {
    "viewer": 1,
    "editor": 2,
    "billing": 2,
    "admin": 3,
    "owner": 4,
}


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when either the DB layer or the RBAC/audit services are absent."""
    _require_db(request_id)
    if rbac is None or audit_service is None or _RBAC_IMPORT_ERROR is not None:
        logger.error(
            f"rbac service unavailable, request_id: {request_id}, "
            f"error: {_RBAC_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: access-governance service is not available",
        )


@contextmanager
def _map_service_errors(request_id: str) -> Iterator[None]:
    """Translate service-layer exceptions to HTTP errors.

    ``PermissionError`` (not a member / under-privileged) maps to ``403``;
    ``ValueError`` (invalid role, etc.) maps to ``400``. :class:`HttpException`
    (e.g. a pre-checked ``404`` / ``409``) passes through untouched.
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
    """Return the workspace row, or raise a ``404`` when it does not exist.

    Resolving existence up front means a non-member hitting a *real* workspace
    gets a ``403`` from the enforcer, while any request against an unknown
    workspace id gets a clean ``404`` (never a misleading ``403``).
    """
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


def _member_data(member: Any, user: Any) -> dict[str, Any]:
    """Serialize a membership row (joined to its user) into a descriptor."""
    return {
        "user_id": member.user_id,
        "email": getattr(user, "email", None) if user is not None else None,
        "role": member.role,
        "created_at": _isoformat(getattr(member, "created_at", None)),
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get(
    "/me/workspaces/{workspace_id}/members",
    response_model=MembersResponse,
    summary="List a workspace's members + Enterprise roles (member only)",
)
def list_members(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return the workspace roster with each member's Enterprise role.

    The caller must be a member (any role) — a non-member gets a ``403`` (real
    workspace) or ``404`` (unknown id, resolved up front so existence never leaks
    as a bare ``403``). Membership is verified via the enforcer's floor
    permission ``jobs.read`` (held by every real role).
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            # Any member may read the roster: gate on the floor permission that
            # every real role holds (a non-member has no role -> 403).
            rbac.require_permission(
                session, user.id, workspace_id, rbac.PERM_JOBS_READ
            )
        members = WorkspaceRepository(session).list_members(workspace_id)
        items = [
            _member_data(member, session.get(User, member.user_id))
            for member in members
        ]

    return utils.get_response(200, items)


@router.patch(
    "/me/workspaces/{workspace_id}/members/{user_id}/role",
    response_model=MemberRoleResponse,
    summary="Change a member's Enterprise role (requires members.manage)",
)
def update_member_role(
    request: Request,
    body: RoleUpdateRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
    user_id: str = Path(..., description="Target member's user ID"),
):
    """Change ``user_id``'s Enterprise role within the workspace.

    Gated by ``members.manage`` (admin/owner). The new role must be a known
    Enterprise role (``400`` otherwise). Two guardrails protect the workspace:

    * a caller may not grant a role **higher than their own** (``403``);
    * the workspace's **last ``owner`` cannot be demoted** (``409``) — a
      workspace must always retain an owner.

    On success the target's role is updated and exactly one append-only
    ``members.role_changed`` audit row is written.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    new_role = (body.role or "").strip().lower()

    with get_session() as session:
        actor = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)

        with _map_service_errors(request_id):
            # AUTHZ: caller must hold members.manage in this workspace (a
            # non-member or under-privileged member raises PermissionError -> 403).
            actor_role = rbac.require_permission(
                session, actor.id, workspace_id, rbac.PERM_MEMBERS_MANAGE
            )

        # Validate the requested role against the Enterprise vocabulary.
        if new_role not in rbac.ROLES:
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=(
                    f"{request_id}: invalid role {body.role!r} "
                    f"(expected one of {sorted(rbac.ROLES)})"
                ),
            )

        repo = WorkspaceRepository(session)
        target = repo.get_membership(workspace_id, user_id)
        if target is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: target user is not a member of this workspace",
            )

        # A caller may not grant a role that out-ranks their own.
        if _ROLE_RANK.get(new_role, 0) > _ROLE_RANK.get(actor_role, 0):
            raise HttpException(
                task_id=request_id,
                status_code=403,
                message=(
                    f"{request_id}: cannot grant role {new_role!r} "
                    f"above your own role {actor_role!r}"
                ),
            )

        old_role = target.role
        # A caller may not modify a member who out-ranks them: a lower-privileged
        # admin must never be able to demote/strip a higher-privileged owner.
        if _ROLE_RANK.get(old_role, 0) > _ROLE_RANK.get(actor_role, 0):
            raise HttpException(
                task_id=request_id,
                status_code=403,
                message=(
                    f"{request_id}: cannot modify a member whose role {old_role!r} "
                    f"out-ranks your own role {actor_role!r}"
                ),
            )

        # Guard the last owner: a workspace must always keep an owner, so demoting
        # the sole owner is rejected (409 Conflict).
        if old_role == rbac.ROLE_OWNER and new_role != rbac.ROLE_OWNER:
            owner_count = sum(
                1
                for m in repo.list_members(workspace_id)
                if m.role == rbac.ROLE_OWNER
            )
            if owner_count <= 1:
                raise HttpException(
                    task_id=request_id,
                    status_code=409,
                    message=f"{request_id}: cannot demote the last owner",
                )

        # Apply the change directly (the Enterprise vocabulary is wider than the
        # legacy WorkspaceRepository.set_role validation) then audit it.
        target.role = new_role
        session.flush()

        audit_service.record(
            session,
            actor_user_id=actor.id,
            action="members.role_changed",
            workspace_id=workspace_id,
            target_type="user",
            target_id=user_id,
            metadata={"old_role": old_role, "new_role": new_role},
            ip=_client_ip(request),
        )

        data = _member_data(target, session.get(User, target.user_id))

    return utils.get_response(200, data)


@router.get(
    "/me/permissions",
    response_model=PermissionsResponse,
    summary="The caller's effective permissions in a workspace",
)
def my_permissions(
    request: Request,
    workspace_id: str = Query(..., description="Workspace ID"),
):
    """Return the caller's effective permissions (direct + inherited) in a workspace.

    ``workspace_id`` is required (``400`` when blank). The caller's role is read
    from their membership and fed to :func:`rbac.effective_permissions`; a
    non-member yields ``role: null`` and an empty ``permissions`` list (no tenant
    leak). Never mutates anything.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    normalized_ws = (workspace_id or "").strip()
    if not normalized_ws:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: workspace_id is required",
        )

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        role = rbac.get_role(session, user.id, normalized_ws)
        permissions = sorted(rbac.effective_permissions(role))

    return utils.get_response(
        200,
        {
            "workspace_id": normalized_ws,
            "role": role,
            "permissions": permissions,
        },
    )


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort source IP of the caller for the audit row (never raises)."""
    try:
        client = getattr(request, "client", None)
        return getattr(client, "host", None) if client is not None else None
    except Exception:  # noqa: BLE001 - IP is best-effort telemetry
        return None
