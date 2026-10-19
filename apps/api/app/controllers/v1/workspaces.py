"""Team Workspaces v1 API controller.

Exposes the additive multi-seat *membership* layer under ``/api/v1``. A user
creates a workspace and invites existing teammates (by email) with a role of
``owner | admin | member``; owners/admins can invite + remove members and change
roles, while members can view + leave.

Routes
------
* ``POST   /workspaces``                                   — create (caller = owner)
* ``GET    /me/workspaces``                                — caller's workspaces (+ role)
* ``GET    /workspaces/{id}/members``                      — roster (member only)
* ``POST   /workspaces/{id}/invite``                       — invite an existing user (admin+)
* ``POST   /workspaces/{id}/members/{user_id}/role``       — change a member's role (admin+)
* ``DELETE /workspaces/{id}/members/{user_id}``            — remove a member (admin+ or self)
* ``POST   /workspaces/{id}/leave``                        — leave the workspace
* ``POST   /workspaces/{id}/invites``                      — create a pending invite link (admin+)
* ``GET    /workspaces/{id}/invites``                      — pending invites (admin+)
* ``DELETE /workspaces/{id}/invites/{invite_id}``          — revoke an invite (admin+)
* ``GET    /invites/{token}``                              — public invite preview
* ``POST   /invites/{token}/accept``                       — accept (signed-in, email must match)
* ``GET    /me/invites``                                   — invitations addressed to the caller
* ``POST   /me/invites/{invite_id}/accept``                — accept from the inbox

Invites for people without an account produce a shareable ``accept_url`` (no
transactional email provider is configured in the API; the link is the delivery
channel, plus an in-app notification when the invitee already has an account).

Design notes
------------
* **Auth is reused, not reinvented.** Every route runs behind the global
  ``base.verify_token`` gate (applied at router construction) and resolves the
  caller to a ``User`` row via the canonical get-or-create resolver
  (``_resolve_user``) borrowed from :mod:`app.controllers.v1.jobs` — the module
  that owns the guarded persistence import. A missing DB layer degrades to a
  clean ``503`` rather than an import crash.
* **All authorization lives in the service.** This controller is a thin HTTP
  adapter: it resolves the caller, confirms the target workspace exists (``404``
  otherwise, so a non-existent workspace never leaks as a bare ``403``), delegates
  every membership decision to :mod:`app.services.workspaces`, and maps the
  service's exceptions to HTTP status codes (``PermissionError`` -> ``403``,
  ``ValueError`` -> ``400``; a duplicate-member invite -> ``409``).
* **Additive only.** Nothing here touches per-user job/credit ownership.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from fastapi import Path, Request
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
    BaseResponse,
    InviteRequest,
    MembersResponse,
    RoleRequest,
    WorkspaceCreateRequest,
    WorkspaceCreditsResponse,
    WorkspaceGrantRequest,
    WorkspaceResponse,
)
from app.utils import utils

# Guarded import of the workspaces service + models. Coupled to the same
# sqlalchemy/ORM dependencies as the jobs DB import; guarded independently so a
# partial environment degrades to a 503 instead of crashing at import time.
try:  # pragma: no cover - exercised implicitly by the API tests
    from app.models.db.models import User, WorkspaceMember
    from app.models.db.repositories import CreditRepository
    from app.services import workspace_invites as invites_service
    from app.services import workspaces as ws_service
    from app.services.workspaces import WorkspaceRepository

    _WS_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # noqa: BLE001 - import-safe: never crash the module
    User = None  # type: ignore[assignment,misc]
    WorkspaceMember = None  # type: ignore[assignment,misc]
    CreditRepository = None  # type: ignore[assignment,misc]
    ws_service = None  # type: ignore[assignment]
    invites_service = None  # type: ignore[assignment]
    WorkspaceRepository = None  # type: ignore[assignment,misc]
    _WS_IMPORT_ERROR = exc

class _NeverRaised(Exception):
    """Sentinel so ``except IntegrityError`` is always a valid handler.

    When the guarded import below fails (no DB layer), ``IntegrityError`` is
    bound to this class, which is never raised — keeping the module import-safe
    while still allowing the invite handler to reference it unconditionally.
    """


# Guarded import of the concrete DBAPI integrity error. A duplicate-member
# invite that survives the service's read-time pre-check (concurrent requests)
# is rejected by the ``(workspace_id, user_id)`` UNIQUE constraint at flush time
# as an ``IntegrityError``; the invite handler maps it to 409 Conflict.
try:  # pragma: no cover - exercised implicitly by the API tests
    from sqlalchemy.exc import IntegrityError
except Exception:  # noqa: BLE001 - import-safe: never crash the module
    IntegrityError = _NeverRaised  # type: ignore[assignment,misc]

router = new_router()

# Substring used to distinguish the service's duplicate-member ``ValueError``
# (-> HTTP 409) from every other ``ValueError`` (-> HTTP 400) on invite.
_ALREADY_MEMBER_MARKER: str = "already a member"
# The service's "unknown email" ``ValueError`` -> fall back to a pending invite.
_NO_ACCOUNT_MARKER: str = "must have an account"


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_backend(request_id: str) -> None:
    """Raise 503 when either the DB layer or the workspaces service is absent."""
    _require_db(request_id)
    if ws_service is None or _WS_IMPORT_ERROR is not None:
        logger.error(
            f"workspaces service unavailable, request_id: {request_id}, "
            f"error: {_WS_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: workspaces service is not available",
        )


@contextmanager
def _map_service_errors(request_id: str) -> Iterator[None]:
    """Translate service-layer exceptions to HTTP errors.

    ``PermissionError`` (under-privileged / not a member / protected owner) maps
    to ``403``; ``ValueError`` (invalid role, unknown email, non-member target)
    maps to ``400``. :class:`HttpException` (e.g. a pre-checked ``404``) passes
    through untouched.
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
    gets a ``403`` from the service, while any request against an unknown
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


def _workspace_data(workspace: Any, role: str) -> dict[str, Any]:
    """Serialize a workspace + the caller's role into a JSON-safe descriptor."""
    return {
        "id": workspace.id,
        "name": workspace.name,
        "owner_id": workspace.owner_id,
        "role": role,
        # The mobile client reads the caller's role as ``my_role``; both keys
        # carry the same value so web (``role``) and mobile agree.
        "my_role": role,
        "created_at": _isoformat(getattr(workspace, "created_at", None)),
    }


def _resolve_target_user_id(session: Any, workspace_id: str, member_ref: str) -> str:
    """Map a path ``member_ref`` (a user id OR a membership row id) to a user id.

    The web client addresses members by ``user_id`` while the mobile client
    addresses them by the membership row ``id``; both are accepted. A user-id
    match wins; otherwise a membership row *of this workspace* is resolved to its
    ``user_id``. An unknown reference is returned unchanged so the service layer
    reports its usual "not a member" error.
    """
    repo = WorkspaceRepository(session)
    if repo.get_membership(workspace_id, member_ref) is not None:
        return member_ref
    row = session.get(WorkspaceMember, member_ref) if WorkspaceMember is not None else None
    if row is not None and row.workspace_id == workspace_id:
        return row.user_id
    return member_ref


def _member_data(member: Any, user: Any) -> dict[str, Any]:
    """Serialize a membership row (joined to its user) into a descriptor."""
    return {
        "id": member.id,
        "user_id": member.user_id,
        "email": getattr(user, "email", None) if user is not None else None,
        "role": member.role,
        "created_at": _isoformat(getattr(member, "created_at", None)),
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post(
    "/workspaces",
    response_model=WorkspaceResponse,
    summary="Create a workspace (caller becomes its owner)",
)
def create_workspace(request: Request, body: WorkspaceCreateRequest):
    """Create a workspace owned by the caller (also its first ``owner`` member)."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        with _map_service_errors(request_id):
            workspace = ws_service.create_workspace(session, user.id, body.name)
        data = _workspace_data(workspace, ws_service.ROLE_OWNER)

    return utils.get_response(200, data)


@router.get(
    "/me/workspaces",
    response_model=WorkspaceResponse,
    summary="List the caller's workspaces (with the caller's role in each)",
)
@router.get(
    "/workspaces",
    response_model=WorkspaceResponse,
    summary="List the caller's workspaces (alias of GET /me/workspaces)",
)
def list_my_workspaces(request: Request):
    """Return every workspace the caller is a member of, each with their role."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        with _map_service_errors(request_id):
            workspaces = ws_service.list_workspaces(session, user.id)
        repo = WorkspaceRepository(session)
        items: list[dict[str, Any]] = []
        for workspace in workspaces:
            membership = repo.get_membership(workspace.id, user.id)
            role = membership.role if membership is not None else ws_service.ROLE_MEMBER
            items.append(_workspace_data(workspace, role))

    return utils.get_response(200, items)


@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=MembersResponse,
    summary="List a workspace's members (caller must be a member)",
)
def list_members(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return the workspace roster. The caller must be a member (any role)."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            members = ws_service.list_members(session, workspace_id, user.id)
        items = [
            _member_data(member, session.get(User, member.user_id))
            for member in members
        ]

    return utils.get_response(200, items)


@router.post(
    "/workspaces/{workspace_id}/invite",
    response_model=BaseResponse,
    summary="Invite an existing user by email (admin+)",
)
@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=BaseResponse,
    summary="Invite an existing user by email (admin+; REST alias of /invite)",
)
def invite_member(
    request: Request,
    body: InviteRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Invite an existing user (by email) with an optional role (default member).

    Unknown email -> ``400``; already a member -> ``409``; under-privileged or a
    role above the caller's own -> ``403``.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    role = (body.role or ws_service.ROLE_MEMBER)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        workspace = _load_workspace_or_404(session, workspace_id, request_id)
        try:
            member = ws_service.invite_member(
                session, workspace_id, user.id, body.email, role
            )
        except PermissionError as exc:
            raise HttpException(
                task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
            )
        except ValueError as exc:
            if _NO_ACCOUNT_MARKER in str(exc).lower():
                # No account yet: create a pending invite with a shareable
                # accept link instead of rejecting the teammate.
                with _invite_errors(request_id):
                    data = _create_invite_response(
                        session, workspace, user.id, body.email, role
                    )
                return utils.get_response(200, data)
            # The service reports a duplicate membership as a ``ValueError``;
            # surface that specific case as 409 Conflict, everything else 400.
            status = 409 if _ALREADY_MEMBER_MARKER in str(exc).lower() else 400
            raise HttpException(
                task_id=request_id, status_code=status, message=f"{request_id}: {exc}"
            )
        except IntegrityError as exc:
            # Concurrent invites can both pass the service's read-time
            # ``get_membership`` pre-check and reach ``add_member``; the second
            # flush is rejected by the ``(workspace_id, user_id)`` UNIQUE
            # constraint. The data stays safe (no duplicate row) — surface it as
            # a clean 409 Conflict rather than letting a DBAPIError become a 500.
            session.rollback()
            logger.info(
                f"duplicate-member invite rejected by unique constraint, "
                f"request_id: {request_id}, error: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: user is already a member of this workspace",
            )
        data = {
            **_member_data(member, session.get(User, member.user_id)),
            "status": "member",
            "pending": False,
        }

    return utils.get_response(200, data)


@router.post(
    "/workspaces/{workspace_id}/members/{user_id}/role",
    response_model=BaseResponse,
    summary="Change a member's role (admin+)",
)
@router.patch(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=BaseResponse,
    summary="Change a member's role (admin+; REST alias of .../role)",
)
def set_member_role(
    request: Request,
    body: RoleRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
    user_id: str = Path(..., description="Target member's user ID"),
):
    """Change ``user_id``'s role within the workspace (admin+; owner protected)."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        actor = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        target_user_id = _resolve_target_user_id(session, workspace_id, user_id)
        with _map_service_errors(request_id):
            member = ws_service.set_role(
                session, workspace_id, actor.id, target_user_id, body.role
            )
        data = _member_data(member, session.get(User, member.user_id))

    return utils.get_response(200, data)


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=BaseResponse,
    summary="Remove a member (admin+, or remove yourself)",
)
def remove_member(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    user_id: str = Path(..., description="Target member's user ID"),
):
    """Remove ``user_id`` from the workspace.

    Removing yourself only requires membership (a *leave*); removing anyone else
    requires admin+. The owner can never be removed.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        actor = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        target_user_id = _resolve_target_user_id(session, workspace_id, user_id)
        with _map_service_errors(request_id):
            ws_service.remove_member(session, workspace_id, actor.id, target_user_id)

    return utils.get_response(200, {"removed": True})


@router.post(
    "/workspaces/{workspace_id}/leave",
    response_model=BaseResponse,
    summary="Leave a workspace (the owner cannot leave)",
)
def leave_workspace(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Leave the workspace. The owner must transfer ownership / delete first."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            ws_service.leave_workspace(session, workspace_id, user.id)

    return utils.get_response(200, {"left": True})


# --------------------------------------------------------------------------- #
# Shared credit pool (SHARED WORKSPACE CREDITS)
# --------------------------------------------------------------------------- #
@router.get(
    "/workspaces/{workspace_id}/credits",
    response_model=WorkspaceCreditsResponse,
    summary="Read a workspace's shared credit pool balance (member+)",
)
def get_workspace_credits(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Return the workspace's SHARED credit pool balance.

    The caller must be a member (any role) — a non-member gets a ``403`` (real
    workspace) or ``404`` (unknown id, resolved up front so existence never
    leaks as a bare ``403``). ``data`` carries ``{"balance": <int>}``.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            # Membership is the gate: any member may read the pool balance.
            ws_service.require_membership(session, workspace_id, user.id)
        balance = CreditRepository(session).workspace_balance(workspace_id)

    return utils.get_response(200, {"balance": int(balance)})


@router.post(
    "/workspaces/{workspace_id}/credits/grant",
    response_model=WorkspaceCreditsResponse,
    summary="Grant credits to a workspace's shared pool (admin+)",
)
def grant_workspace_credits(
    request: Request,
    body: WorkspaceGrantRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Add credits to the workspace's SHARED pool (platform staff; manual/dev grant).

    The caller must be platform staff (``is_staff``) AND ``admin`` or higher in
    the workspace — anyone else gets a ``403``. This
    is the manual / development top-up path; real purchases flow through Stripe
    in a later phase. A non-positive ``amount`` is rejected with ``400`` (mapped
    from the repository's ``ValueError``). Returns the updated pool balance as
    ``{"balance": <int>}``. The acting admin's id is recorded on the ledger row
    for audit only — it never touches any personal balance.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        # Minting pool credits is a platform-staff action (support / dev), never
        # a workspace role: any signed-in user can create a workspace and be its
        # owner, so an admin-only gate let anyone print free renders. Paid pool
        # credit arrives through workspace packs and team plans.
        if not bool(getattr(user, "is_staff", False)):
            raise HttpException(
                task_id=request_id,
                status_code=403,
                message=f"{request_id}: only Menivor staff can add pool credits; buy a team pack instead",
                data={"code": "pool_grant_staff_only"},
            )
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            # Funding the pool is admin-gated (spending it only needs membership).
            ws_service.require_role(
                session, workspace_id, user.id, ws_service.ROLE_ADMIN
            )
            reason = (body.reason or "workspace_grant").strip() or "workspace_grant"
            CreditRepository(session).workspace_grant(
                workspace_id, body.amount, reason, actor_user_id=user.id
            )
        balance = CreditRepository(session).workspace_balance(workspace_id)

    return utils.get_response(200, {"balance": int(balance)})


# --------------------------------------------------------------------------- #
# Pending invites (people without an account; shareable accept link)
# --------------------------------------------------------------------------- #
def _notify_invitee(invitee: Any, workspace: Any, invite: Any, token: str) -> bool:
    """Best-effort in-app notification when the invitee already has an account."""
    if invitee is None:
        return False
    try:
        from app.services.notifications import notify_workspace_invite

        return bool(
            notify_workspace_invite(
                invitee.id,
                workspace_id=workspace.id,
                workspace_name=workspace.name,
                role=invite.role,
                accept_url=invites_service.accept_url(token),
                invite_token=token,
            )
        )
    except Exception as exc:  # noqa: BLE001 - notification is best-effort
        logger.warning(f"workspace invite notification failed: {exc}")
        return False


def _create_invite_response(
    session: Any, workspace: Any, actor_id: str, email: str, role: str
) -> dict[str, Any]:
    invite, token, invitee = invites_service.create_invite(
        session, workspace.id, actor_id, email, role
    )
    notified = _notify_invitee(invitee, workspace, invite, token)
    return {
        **invites_service.invite_view(invite, token=token),
        "pending": True,
        "workspace_name": workspace.name,
        "invitee_has_account": invitee is not None,
        "notified_in_app": notified,
        # No transactional email provider is configured: the admin shares
        # ``accept_url`` directly (copy link).
        "email_sent": False,
    }


@contextmanager
def _invite_errors(request_id: str) -> Iterator[None]:
    """Map invite-service errors: 404 unknown, 410 used/expired/revoked, else generic."""
    try:
        yield
    except HttpException:
        raise
    except LookupError as exc:
        raise HttpException(
            task_id=request_id, status_code=404, message=f"{request_id}: {exc}"
        )
    except invites_service.InviteGone as exc:
        raise HttpException(
            task_id=request_id, status_code=410, message=f"{request_id}: {exc}"
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id, status_code=403, message=f"{request_id}: {exc}"
        )
    except ValueError as exc:
        status = 409 if _ALREADY_MEMBER_MARKER in str(exc).lower() else 400
        raise HttpException(
            task_id=request_id, status_code=status, message=f"{request_id}: {exc}"
        )


@router.post(
    "/workspaces/{workspace_id}/invites",
    response_model=BaseResponse,
    summary="Create a shareable invite link for an email (admin+)",
)
def create_workspace_invite(
    request: Request,
    body: InviteRequest,
    workspace_id: str = Path(..., description="Workspace ID"),
):
    """Create a pending invite (works for people with or without an account).

    Returns the invite with a one-time ``accept_url`` (shown once — only its hash
    is stored). Re-inviting the same email replaces the previous link.
    """
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    role = body.role or ws_service.ROLE_MEMBER
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        workspace = _load_workspace_or_404(session, workspace_id, request_id)
        with _invite_errors(request_id):
            data = _create_invite_response(session, workspace, user.id, body.email, role)
    return utils.get_response(200, data)


@router.get(
    "/workspaces/{workspace_id}/invites",
    response_model=BaseResponse,
    summary="List a workspace's pending invites (admin+)",
)
def list_workspace_invites(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    include_closed: bool = False,
):
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _map_service_errors(request_id):
            rows = invites_service.list_invites(
                session, workspace_id, user.id, include_closed=include_closed
            )
        items = [invites_service.invite_view(row) for row in rows]
    return utils.get_response(200, items)


@router.delete(
    "/workspaces/{workspace_id}/invites/{invite_id}",
    response_model=BaseResponse,
    summary="Revoke a pending invite (admin+)",
)
def revoke_workspace_invite(
    request: Request,
    workspace_id: str = Path(..., description="Workspace ID"),
    invite_id: str = Path(..., description="Invite ID"),
):
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _load_workspace_or_404(session, workspace_id, request_id)
        with _invite_errors(request_id):
            invite = invites_service.revoke_invite(session, workspace_id, user.id, invite_id)
        data = invites_service.invite_view(invite)
    return utils.get_response(200, data)


@router.get(
    "/invites/{token}",
    response_model=BaseResponse,
    summary="Preview an invite link (public)",
)
def preview_invite(request: Request, token: str = Path(..., max_length=200)):
    """Public preview for the accept page: workspace name, role, status."""
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    with get_session() as session:
        with _invite_errors(request_id):
            data = invites_service.preview(session, token)
    return utils.get_response(200, data)


def _accepted_response(session: Any, invite: Any, membership: Any) -> dict[str, Any]:
    workspace = WorkspaceRepository(session).get(invite.workspace_id)
    return {
        "accepted": True,
        "workspace": _workspace_data(workspace, membership.role) if workspace else None,
        "workspace_id": invite.workspace_id,
        "role": membership.role,
    }


def _accept(request: Request, request_id: str, redeem) -> dict[str, Any]:
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            with _invite_errors(request_id):
                invite, membership = redeem(session, user)
        except IntegrityError:
            session.rollback()
            raise HttpException(
                task_id=request_id, status_code=409,
                message=f"{request_id}: you are already a member of this workspace",
            )
        return _accepted_response(session, invite, membership)


@router.post(
    "/invites/{token}/accept",
    response_model=BaseResponse,
    summary="Accept an invite link (signed-in user whose email matches)",
)
def accept_invite(request: Request, token: str = Path(..., max_length=200)):
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    data = _accept(
        request, request_id, lambda session, user: invites_service.accept(session, token, user)
    )
    return utils.get_response(200, data)


@router.get(
    "/me/invites",
    response_model=BaseResponse,
    summary="Pending workspace invitations addressed to the caller's email",
)
def list_my_invites(request: Request):
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = invites_service.pending_for_email(session, getattr(user, "email", "") or "")
        repo = WorkspaceRepository(session)
        items = []
        for row in rows:
            workspace = repo.get(row.workspace_id)
            items.append({
                **invites_service.invite_view(row),
                "workspace_name": workspace.name if workspace is not None else "",
            })
    return utils.get_response(200, items)


@router.post(
    "/me/invites/{invite_id}/accept",
    response_model=BaseResponse,
    summary="Accept a pending invitation from the caller's inbox",
)
def accept_my_invite(request: Request, invite_id: str = Path(..., max_length=64)):
    request_id = base.get_task_id(request)
    _require_backend(request_id)
    data = _accept(
        request, request_id,
        lambda session, user: invites_service.accept_by_id(session, invite_id, user),
    )
    return utils.get_response(200, data)
