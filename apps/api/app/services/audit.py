"""Append-only audit trail service (Enterprise Access & Governance, Epic 1).

Two operations, no more:

* :func:`record` — INSERT one immutable audit row. Never updates or deletes.
* :func:`query` — read a workspace's trail, but FIRST enforce that the requester
  holds ``audit.read`` in that workspace (via :mod:`app.services.rbac`). The read
  is then strictly tenant-scoped, so a member of workspace *B* can never read
  workspace *A*'s trail.

The append-only discipline is a hard invariant: there is deliberately no update
or delete function anywhere in this module or in
:class:`~app.models.db.repositories.AuditLogRepository`, so a governance trail is
tamper-evident by construction.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.db.models import AuditLog
from app.models.db.repositories import AuditLogRepository
from app.services import rbac


def record(
    session: Session,
    *,
    actor_user_id: str,
    action: str,
    workspace_id: str | None = None,
    target_type: str = "",
    target_id: str | None = None,
    metadata: dict | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Append one immutable audit row and return it.

    ``actor_user_id`` (who acted) and ``action`` (a stable dotted verb, e.g.
    ``members.role_changed``) are required; the rest describe the target and
    context. ``workspace_id`` is optional so a platform-level action (e.g. a
    staff impersonation not bound to one tenant) can be recorded without a
    tenant. ``metadata`` is copied at the repository boundary so a later mutation
    of the caller's dict cannot bleed into the persisted row. This is an INSERT
    only — the row is never mutated or deleted afterward.
    """
    return AuditLogRepository(session).create(
        actor_user_id=actor_user_id,
        action=action,
        workspace_id=workspace_id,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
        ip=ip,
    )


def query(
    session: Session,
    workspace_id: str,
    requester_user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    """Return a workspace's audit rows (newest first) — ``audit.read`` gated.

    Authorization runs FIRST: :func:`rbac.require_permission` verifies the
    requester is a member of ``workspace_id`` (tenant isolation) AND that their
    role grants ``audit.read`` — a non-member or an under-privileged member
    raises :class:`PermissionError` (mapped to HTTP ``403`` upstream) before any
    row is read. Only then are that workspace's rows returned, paginated. Because
    the query filters strictly on ``workspace_id``, a member of another tenant
    can never receive these rows even if authorized elsewhere.
    """
    rbac.require_permission(
        session, requester_user_id, workspace_id, rbac.PERM_AUDIT_READ
    )
    return AuditLogRepository(session).list_for_workspace(
        workspace_id, limit=limit, offset=offset
    )


__all__ = ["query", "record"]
