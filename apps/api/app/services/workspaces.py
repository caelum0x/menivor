"""Team Workspaces — the shared-seat membership layer (domain logic).

A user creates a :class:`~app.models.db.models.Workspace` and invites existing
teammates (by email) with a role of ``owner``, ``admin`` or ``member``. Roles
are strictly ranked and every mutating operation is guarded by
:func:`require_role`, so authorization lives in exactly one place.

Design invariants
-----------------
* **Additive only.** This module is a pure *membership* layer. It never touches
  the existing per-user job / credit ownership model — jobs, the credit ledger
  and every other table stay keyed on ``users.id``. Workspaces are the
  foundation for future team plans and shared resources, but today they only
  record who the members are and what role each holds.
* **Role ranks.** ``member < admin < owner`` (:data:`ROLE_RANK`). A caller may
  never grant, or elevate a member to, a role higher than their own.
* **Exactly one owner is protected.** The owner's membership row can never be
  demoted or removed and the owner can never *leave*; ownership must be
  transferred or the workspace deleted first (a later feature).
* **Invitees must already have an account.** Inviting is by email and resolves
  to an existing :class:`~app.models.db.models.User`; there is no implicit user
  creation here (that lives behind the auth/get-or-create path).
* **Immutable-friendly persistence.** All writes go through
  :class:`WorkspaceRepository`, which only ever INSERTs membership rows, updates
  a single ``role`` scalar, or DELETEs a row — it never mutates shared JSON in
  place. Transaction boundaries are owned by the caller / ``get_session()``.

The repository is defined locally against the ORM models so this service is
self-contained and testable in isolation; it can be swapped for a shared
repository later without changing the public function API.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db.models import User, Workspace, WorkspaceMember

# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
#: The three workspace roles, ranked. A higher rank strictly implies every
#: capability of the lower ranks (an ``owner`` can do anything an ``admin`` can,
#: and so on). Authorization compares ranks, never role strings directly.
ROLE_MEMBER: str = "member"
ROLE_ADMIN: str = "admin"
ROLE_OWNER: str = "owner"

ROLE_RANK: dict[str, int] = {ROLE_MEMBER: 0, ROLE_ADMIN: 1, ROLE_OWNER: 2}


def _normalize_email(email: str) -> str:
    """Normalize an email for lookup (trim + lowercase). ``None`` -> ``""``."""
    return (email or "").strip().lower()


def _validate_role(role: str) -> str:
    """Return a validated role string, raising ``ValueError`` on an unknown one.

    Callers pass untrusted role values (request bodies); fail fast with a clear
    message rather than silently persisting an out-of-range role that would then
    rank as ``member`` (or blow up) later.
    """
    normalized = (role or "").strip().lower()
    if normalized not in ROLE_RANK:
        valid = ", ".join(sorted(ROLE_RANK))
        raise ValueError(f"invalid role '{role}'; must be one of: {valid}")
    return normalized


# --------------------------------------------------------------------------- #
# Repository (session-scoped; INSERT / single-scalar UPDATE / DELETE only)
# --------------------------------------------------------------------------- #
class WorkspaceRepository:
    """Persistence for :class:`Workspace` + :class:`WorkspaceMember` rows.

    Constructed with an active :class:`Session`; never commits on its own —
    transaction boundaries belong to the caller / ``get_session()``. Reads are
    plain selects; writes are limited to inserting a workspace/membership,
    updating a single ``role`` scalar, or deleting a membership row.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- workspaces ------------------------------------------------------- #
    def create(self, owner_id: str, name: str) -> Workspace:
        """Insert a workspace and its ``owner`` membership row; flush for ids."""
        workspace = Workspace(owner_id=owner_id, name=name)
        self._session.add(workspace)
        self._session.flush()  # populate workspace.id
        self._session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner_id,
                role=ROLE_OWNER,
            )
        )
        self._session.flush()
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        """Return a workspace by id, or ``None``."""
        return self._session.get(Workspace, workspace_id)

    def list_for_user(self, user_id: str) -> list[Workspace]:
        """Return every workspace ``user_id`` is a member of, newest first."""
        stmt = (
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    # -- memberships ------------------------------------------------------ #
    def get_membership(
        self, workspace_id: str, user_id: str
    ) -> WorkspaceMember | None:
        """Return a user's membership of a workspace, or ``None`` if not a member."""
        stmt = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        return self._session.execute(stmt).scalars().first()

    def list_members(self, workspace_id: str) -> list[WorkspaceMember]:
        """Return all members of a workspace, oldest first (owner leads)."""
        stmt = (
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def add_member(
        self, workspace_id: str, user_id: str, role: str
    ) -> WorkspaceMember:
        """Insert a membership row and flush to obtain its id.

        The composite ``(workspace_id, user_id)`` UNIQUE constraint is the
        durable guard against a duplicate membership; callers additionally
        pre-check with :meth:`get_membership` to surface a clean error.
        """
        member = WorkspaceMember(
            workspace_id=workspace_id, user_id=user_id, role=role
        )
        self._session.add(member)
        self._session.flush()
        return member

    def set_role(
        self, workspace_id: str, user_id: str, role: str
    ) -> WorkspaceMember | None:
        """Update a member's ``role`` scalar; return the row, or ``None``."""
        member = self.get_membership(workspace_id, user_id)
        if member is None:
            return None
        member.role = role
        self._session.flush()
        return member

    def remove_member(self, workspace_id: str, user_id: str) -> bool:
        """Delete a membership row; return whether a row was removed."""
        member = self.get_membership(workspace_id, user_id)
        if member is None:
            return False
        self._session.delete(member)
        self._session.flush()
        return True

    # -- users ------------------------------------------------------------ #
    def find_user_by_email(self, email: str) -> User | None:
        """Return the user owning ``email`` (case-insensitive), or ``None``.

        Empty / whitespace-only input never matches.
        """
        normalized = _normalize_email(email)
        if not normalized:
            return None
        stmt = (
            select(User)
            .where(func.lower(User.email) == normalized)
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()


# --------------------------------------------------------------------------- #
# Authorization helper
# --------------------------------------------------------------------------- #
def require_role(
    session: Session,
    workspace_id: str,
    actor_user_id: str,
    min_role: str,
) -> WorkspaceMember:
    """Return the actor's membership, or raise ``PermissionError``.

    The single authorization gate for every mutating operation. Raises
    :class:`PermissionError` when the actor is *not a member* of the workspace,
    or when their role ranks below ``min_role``. On success the actor's
    :class:`WorkspaceMember` row is returned so callers can reuse its role
    without a second query.

    Args:
        session: Active SQLAlchemy session.
        workspace_id: The workspace whose membership is being checked.
        actor_user_id: The acting user's id.
        min_role: The minimum role required (``member`` | ``admin`` | ``owner``).

    Raises:
        ValueError: If ``min_role`` is not a known role.
        PermissionError: If the actor is not a member, or is under-privileged.
    """
    required_rank = ROLE_RANK[_validate_role(min_role)]
    repo = WorkspaceRepository(session)
    membership = repo.get_membership(workspace_id, actor_user_id)
    if membership is None:
        raise PermissionError(
            "actor is not a member of this workspace"
        )
    if ROLE_RANK.get(membership.role, -1) < required_rank:
        raise PermissionError(
            f"role '{membership.role}' is insufficient; '{min_role}' required"
        )
    return membership


def get_membership(
    session: Session, workspace_id: str, user_id: str
) -> WorkspaceMember | None:
    """Return the user's membership of a workspace, or ``None`` if not a member.

    A thin module-level accessor over :meth:`WorkspaceRepository.get_membership`
    so callers outside this module (e.g. the jobs controller deciding whether a
    caller may spend a workspace's shared credit pool) need not construct a
    repository. A ``None`` result is the authorization signal that the user is
    not a member and may neither view the workspace nor spend its pool.
    """
    return WorkspaceRepository(session).get_membership(workspace_id, user_id)


def can_spend(session: Session, workspace_id: str, user_id: str) -> bool:
    """Return whether ``user_id`` may spend a workspace's shared credit pool.

    Every member (any role — ``member`` and up) may debit the shared pool by
    creating jobs against it; only funding the pool (a grant) is admin-gated.
    So this is simply "is the caller a member?". Returns ``False`` for a
    non-member or an unknown workspace, so a caller can never spend a pool they
    do not belong to.
    """
    return get_membership(session, workspace_id, user_id) is not None


def require_membership(
    session: Session, workspace_id: str, user_id: str
) -> WorkspaceMember:
    """Return the caller's membership or raise ``PermissionError`` (member+).

    Convenience wrapper over :func:`require_role` at the lowest rank
    (``member``): the authorization gate for spending a workspace's shared
    credit pool. Raises :class:`PermissionError` when the caller is not a member
    so the controller can map it to a ``403``.
    """
    return require_role(session, workspace_id, user_id, ROLE_MEMBER)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def create_workspace(session: Session, owner_id: str, name: str) -> Workspace:
    """Create a workspace owned by ``owner_id`` (also its first ``owner`` member).

    Args:
        session: Active SQLAlchemy session.
        owner_id: The creating user's id. Must reference an existing user.
        name: A human-readable workspace name. Must be non-empty.

    Returns:
        The newly created :class:`Workspace`.

    Raises:
        ValueError: If ``owner_id``/``name`` are empty, or ``owner_id`` does not
            reference an existing user.
    """
    if not owner_id or not str(owner_id).strip():
        raise ValueError("owner_id is required to create a workspace")
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("workspace name is required")

    if session.get(User, owner_id) is None:
        raise ValueError("owner_id must reference an existing user")

    repo = WorkspaceRepository(session)

    return repo.create(owner_id=owner_id, name=clean_name)


def list_workspaces(session: Session, user_id: str) -> list[Workspace]:
    """Return every workspace the user is a member of (newest first).

    Raises:
        ValueError: If ``user_id`` is empty.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required")
    return WorkspaceRepository(session).list_for_user(user_id)


def list_members(
    session: Session, workspace_id: str, actor_user_id: str
) -> list[WorkspaceMember]:
    """Return a workspace's members. The actor must be a member (any role).

    Raises:
        PermissionError: If the actor is not a member of the workspace.
    """
    require_role(session, workspace_id, actor_user_id, ROLE_MEMBER)
    return WorkspaceRepository(session).list_members(workspace_id)


def invite_member(
    session: Session,
    workspace_id: str,
    actor_user_id: str,
    email: str,
    role: str = ROLE_MEMBER,
) -> WorkspaceMember:
    """Invite an existing user (by email) into the workspace with ``role``.

    Guards, in order:

    * **Authorization** — the actor must be ``admin`` or higher.
    * **Role validity** — ``role`` must be a known role.
    * **Role ceiling** — the granted role may not rank *at or above* the
      *actor's* role. An owner can invite admins/members but never a second
      owner (the single-owner invariant); an admin can invite only members.
    * **Account required** — ``email`` must resolve to an existing user
      (``ValueError`` — "invitee must have an account").
    * **No duplicates** — the invitee must not already be a member.

    Returns:
        The newly created :class:`WorkspaceMember`.

    Raises:
        PermissionError: If the actor is under-privileged, or the granted role
            would exceed the actor's own role.
        ValueError: On an invalid role, an unknown email, or a duplicate member.
    """
    actor = require_role(session, workspace_id, actor_user_id, ROLE_ADMIN)
    granted_role = _validate_role(role)

    if ROLE_RANK[granted_role] >= ROLE_RANK.get(actor.role, -1):
        raise PermissionError(
            f"cannot grant role '{granted_role}' at or above your own "
            f"role '{actor.role}'"
        )

    repo = WorkspaceRepository(session)
    invitee = repo.find_user_by_email(email)
    if invitee is None:
        raise ValueError("invitee must have an account")

    if repo.get_membership(workspace_id, invitee.id) is not None:
        raise ValueError("user is already a member of this workspace")

    return repo.add_member(workspace_id, invitee.id, granted_role)


def set_role(
    session: Session,
    workspace_id: str,
    actor_user_id: str,
    target_user_id: str,
    role: str,
) -> WorkspaceMember:
    """Change ``target_user_id``'s role within the workspace.

    Guards, in order:

    * **Authorization** — the actor must be ``admin`` or higher.
    * **Role validity** — ``role`` must be a known role.
    * **Target exists** — the target must currently be a member.
    * **Owner protected** — the owner's role can never be changed here.
    * **Role ceiling** — the new role may not rank *at or above* the actor's
      own role, so no actor can mint a peer (e.g. a second owner).

    Returns:
        The updated :class:`WorkspaceMember`.

    Raises:
        PermissionError: If the actor is under-privileged, targets the owner, or
            the new role would exceed the actor's own role.
        ValueError: On an invalid role or a target that is not a member.
    """
    actor = require_role(session, workspace_id, actor_user_id, ROLE_ADMIN)
    new_role = _validate_role(role)

    repo = WorkspaceRepository(session)
    target = repo.get_membership(workspace_id, target_user_id)
    if target is None:
        raise ValueError("target user is not a member of this workspace")

    if target.role == ROLE_OWNER:
        raise PermissionError("the owner's role cannot be changed")

    if ROLE_RANK[new_role] >= ROLE_RANK.get(actor.role, -1):
        raise PermissionError(
            f"cannot set role '{new_role}' at or above your own "
            f"role '{actor.role}'"
        )

    updated = repo.set_role(workspace_id, target_user_id, new_role)
    assert updated is not None  # target existence re-checked above
    return updated


def remove_member(
    session: Session,
    workspace_id: str,
    actor_user_id: str,
    target_user_id: str,
) -> bool:
    """Remove ``target_user_id`` from the workspace.

    Removing *yourself* is a **leave** and only requires membership; removing
    *anyone else* requires ``admin`` or higher. The owner can never be removed
    (ownership must be transferred / the workspace deleted first).

    Returns:
        ``True`` when a membership row was removed.

    Raises:
        PermissionError: If a non-admin tries to remove another member, or the
            target is the owner.
        ValueError: If the target is not a member of the workspace.
    """
    is_self = actor_user_id == target_user_id
    if is_self:
        # A leave: the actor need only be a member.
        require_role(session, workspace_id, actor_user_id, ROLE_MEMBER)
    else:
        require_role(session, workspace_id, actor_user_id, ROLE_ADMIN)

    repo = WorkspaceRepository(session)
    target = repo.get_membership(workspace_id, target_user_id)
    if target is None:
        raise ValueError("target user is not a member of this workspace")

    if target.role == ROLE_OWNER:
        raise PermissionError(
            "the owner cannot be removed; transfer ownership or delete the "
            "workspace first"
        )

    return repo.remove_member(workspace_id, target_user_id)


def leave_workspace(
    session: Session, workspace_id: str, user_id: str
) -> bool:
    """Leave a workspace. The owner cannot leave (must transfer / delete first).

    Returns:
        ``True`` when the membership row was removed.

    Raises:
        PermissionError: If the caller is not a member, or is the owner.
    """
    membership = require_role(session, workspace_id, user_id, ROLE_MEMBER)
    if membership.role == ROLE_OWNER:
        raise PermissionError(
            "the owner cannot leave; transfer ownership or delete the "
            "workspace first"
        )
    return WorkspaceRepository(session).remove_member(workspace_id, user_id)


__all__ = [
    "ROLE_ADMIN",
    "ROLE_MEMBER",
    "ROLE_OWNER",
    "ROLE_RANK",
    "WorkspaceRepository",
    "can_spend",
    "create_workspace",
    "get_membership",
    "invite_member",
    "leave_workspace",
    "list_members",
    "list_workspaces",
    "remove_member",
    "require_membership",
    "require_role",
    "set_role",
]
