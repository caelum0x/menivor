"""Pending workspace invites — invite people who do not have an account yet.

Complements :func:`app.services.workspaces.invite_member` (which adds an
*existing* account directly). An admin+ creates an invite for any email; the
response carries a one-time ``accept_url`` the admin shares (copy link). When the
email already belongs to an account, that user also gets an in-app
``workspace_invite`` notification pointing at the same link.

Email delivery is NOT wired: the API has no transactional email provider
configured, so the shareable link is the delivery channel (owner-gated: plug a
provider in and send ``accept_url`` from :func:`create_invite`).

Security
--------
* The raw token is ``secrets.token_urlsafe(32)``; only its SHA-256 is stored, so
  a DB read never yields a usable link.
* Accepting requires an authenticated user whose account email equals the
  invite email (case-insensitive) — a leaked link cannot be redeemed by someone
  else. Expired / revoked / used invites are rejected.
* Role rules mirror ``invite_member``: admin+ to invite, never at/above your own
  role (no second owner).
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db.models import User, Workspace, WorkspaceInvite
from app.services import workspaces as ws

INVITE_TTL_DAYS = 14
MAX_PENDING_PER_WORKSPACE = 200
DEFAULT_WEB_BASE_URL = "https://menivor.com"


class InviteNotFound(LookupError):
    """Unknown / foreign invite (mapped to 404 without leaking existence)."""


class InviteGone(ValueError):
    """Invite exists but is expired, revoked or already used (410)."""


def web_base_url() -> str:
    """Public web origin used to build accept links (config, env, default)."""
    try:
        from app.config import config

        configured = str(config.app.get("web_base_url", "") or "").strip()
    except Exception:  # noqa: BLE001 - config optional in tests
        configured = ""
    base = configured or os.environ.get("MENIVOR_WEB_URL", "").strip() or DEFAULT_WEB_BASE_URL
    return base.rstrip("/")


def accept_url(token: str) -> str:
    return f"{web_base_url()}/invite/{token}"


def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def invite_status(invite: WorkspaceInvite) -> str:
    if invite.accepted_at is not None:
        return "accepted"
    if invite.revoked_at is not None:
        return "revoked"
    expires = _aware(invite.expires_at)
    if expires is not None and expires <= _now():
        return "expired"
    return "pending"


def invite_view(invite: WorkspaceInvite, *, token: str | None = None) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": invite.id,
        "workspace_id": invite.workspace_id,
        "email": invite.email,
        "role": invite.role,
        "status": invite_status(invite),
        "invited_by": invite.invited_by,
        "expires_at": _aware(invite.expires_at).isoformat() if invite.expires_at else None,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
        "accepted_at": invite.accepted_at.isoformat() if invite.accepted_at else None,
    }
    if token:
        view["token"] = token
        view["accept_url"] = accept_url(token)
    return view


def _validate_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    local, _, domain = normalized.partition("@")
    if not local or "." not in domain or " " in normalized or len(normalized) > 320:
        raise ValueError("a valid email address is required")
    return normalized


def create_invite(
    session: Session,
    workspace_id: str,
    actor_user_id: str,
    email: str,
    role: str = ws.ROLE_MEMBER,
) -> tuple[WorkspaceInvite, str, User | None]:
    """Create (or refresh) a pending invite; returns ``(invite, raw_token, user)``.

    ``user`` is the existing account for ``email`` (for the in-app notification),
    or ``None``. Re-inviting the same email revokes the previous pending invite
    so exactly one live link exists per email.
    """
    actor = ws.require_role(session, workspace_id, actor_user_id, ws.ROLE_ADMIN)
    granted_role = ws._validate_role(role)  # noqa: SLF001 - shared validation
    if ws.ROLE_RANK[granted_role] >= ws.ROLE_RANK.get(actor.role, -1):
        raise PermissionError(
            f"cannot grant role '{granted_role}' at or above your own role '{actor.role}'"
        )
    normalized = _validate_email(email)
    repo = ws.WorkspaceRepository(session)
    existing_user = repo.find_user_by_email(normalized)
    if existing_user is not None and repo.get_membership(workspace_id, existing_user.id):
        raise ValueError("user is already a member of this workspace")

    pending = list(
        session.execute(
            select(WorkspaceInvite).where(
                WorkspaceInvite.workspace_id == workspace_id,
                WorkspaceInvite.accepted_at.is_(None),
                WorkspaceInvite.revoked_at.is_(None),
            )
        ).scalars()
    )
    now = _now()
    live = [i for i in pending if (_aware(i.expires_at) or now) > now]
    if len(live) >= MAX_PENDING_PER_WORKSPACE:
        raise ValueError("too many pending invites; revoke some first")
    for previous in pending:
        if previous.email == normalized:
            previous.revoked_at = now

    token = secrets.token_urlsafe(32)
    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=normalized,
        role=granted_role,
        token_hash=_hash(token),
        invited_by=actor_user_id,
        expires_at=now + timedelta(days=INVITE_TTL_DAYS),
    )
    session.add(invite)
    session.flush()
    return invite, token, existing_user


def list_invites(
    session: Session, workspace_id: str, actor_user_id: str, *, include_closed: bool = False
) -> list[WorkspaceInvite]:
    ws.require_role(session, workspace_id, actor_user_id, ws.ROLE_ADMIN)
    stmt = select(WorkspaceInvite).where(WorkspaceInvite.workspace_id == workspace_id)
    if not include_closed:
        stmt = stmt.where(
            WorkspaceInvite.accepted_at.is_(None), WorkspaceInvite.revoked_at.is_(None)
        )
    rows = list(session.execute(stmt.order_by(WorkspaceInvite.created_at.desc())).scalars())
    if include_closed:
        return rows
    return [r for r in rows if invite_status(r) == "pending"]


def revoke_invite(
    session: Session, workspace_id: str, actor_user_id: str, invite_id: str
) -> WorkspaceInvite:
    ws.require_role(session, workspace_id, actor_user_id, ws.ROLE_ADMIN)
    invite = session.get(WorkspaceInvite, invite_id)
    if invite is None or invite.workspace_id != workspace_id:
        raise InviteNotFound("invite not found")
    if invite.accepted_at is not None:
        raise InviteGone("invite was already accepted")
    if invite.revoked_at is None:
        invite.revoked_at = _now()
        session.flush()
    return invite


def find_by_token(session: Session, token: str) -> WorkspaceInvite:
    if not token or len(token) > 200:
        raise InviteNotFound("invite not found")
    invite = session.execute(
        select(WorkspaceInvite).where(WorkspaceInvite.token_hash == _hash(token))
    ).scalars().first()
    if invite is None:
        raise InviteNotFound("invite not found")
    return invite


def preview(session: Session, token: str) -> dict[str, Any]:
    """Public, non-sensitive preview for the accept page (no auth)."""
    invite = find_by_token(session, token)
    workspace = session.get(Workspace, invite.workspace_id)
    inviter = session.get(User, invite.invited_by) if invite.invited_by else None
    local, _, domain = invite.email.partition("@")
    masked = f"{local[:1]}{'*' * max(1, len(local) - 1)}@{domain}"
    return {
        "workspace_id": invite.workspace_id,
        "workspace_name": workspace.name if workspace is not None else "",
        "role": invite.role,
        "status": invite_status(invite),
        "email_hint": masked,
        "invited_by_email": getattr(inviter, "email", None) if inviter is not None else None,
        "expires_at": _aware(invite.expires_at).isoformat() if invite.expires_at else None,
    }


def accept(session: Session, token: str, user: Any) -> tuple[WorkspaceInvite, Any]:
    """Redeem an invite for ``user``; returns ``(invite, membership)``.

    Raises :class:`InviteNotFound` (404), :class:`InviteGone` (410) or
    ``PermissionError`` (403, email mismatch).
    """
    return redeem(session, find_by_token(session, token), user)


def accept_by_id(session: Session, invite_id: str, user: Any) -> tuple[WorkspaceInvite, Any]:
    """Redeem from the signed-in user's invitations inbox (email must match)."""
    invite = session.get(WorkspaceInvite, invite_id)
    user_email = (getattr(user, "email", "") or "").strip().lower()
    if invite is None or not user_email or invite.email != user_email:
        raise InviteNotFound("invite not found")
    return redeem(session, invite, user)


def redeem(session: Session, invite: WorkspaceInvite, user: Any) -> tuple[WorkspaceInvite, Any]:
    status = invite_status(invite)
    repo = ws.WorkspaceRepository(session)
    if status == "accepted":
        # Idempotent for the same user (double-click / refresh).
        if invite.accepted_by and str(invite.accepted_by) == str(user.id):
            membership = repo.get_membership(invite.workspace_id, user.id)
            if membership is not None:
                return invite, membership
        raise InviteGone("invite was already used")
    if status != "pending":
        raise InviteGone(f"invite is {status}")
    user_email = (getattr(user, "email", "") or "").strip().lower()
    if not user_email or user_email != invite.email:
        raise PermissionError(
            "this invite was sent to a different email address; sign in with that account"
        )
    membership = repo.get_membership(invite.workspace_id, user.id)
    if membership is None:
        membership = repo.add_member(invite.workspace_id, user.id, invite.role)
    invite.accepted_at = _now()
    invite.accepted_by = user.id
    session.flush()
    return invite, membership


def pending_for_email(session: Session, email: str) -> list[WorkspaceInvite]:
    """Live invites addressed to ``email`` (for an "invitations" inbox)."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return []
    rows = session.execute(
        select(WorkspaceInvite).where(
            func.lower(WorkspaceInvite.email) == normalized,
            WorkspaceInvite.accepted_at.is_(None),
            WorkspaceInvite.revoked_at.is_(None),
        )
    ).scalars()
    return [r for r in rows if invite_status(r) == "pending"]


__all__ = [
    "INVITE_TTL_DAYS",
    "InviteGone",
    "InviteNotFound",
    "accept",
    "accept_by_id",
    "accept_url",
    "create_invite",
    "find_by_token",
    "invite_status",
    "invite_view",
    "list_invites",
    "pending_for_email",
    "preview",
    "redeem",
    "revoke_invite",
]
