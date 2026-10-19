"""Who is asking, for which workspace and Brand space, and what they may do.

* Workspace scope (``ws:<id>``): every member may read; owners and admins manage
  connections, Brand-space assignment and approve ad changes.
* Personal scope (``user:<id>``, no workspace): the user does everything.
* Brand space: a brand kit (``user_presets`` row) that belongs to the scope - shared
  to that workspace, or the user's own private kit for a personal scope. When one
  is selected, only the ad accounts assigned to it are visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.domains.integrations.errors import IntegrationError

MANAGING_ROLES = frozenset({"owner", "admin"})


@dataclass(frozen=True)
class Scope:
    user_id: str
    workspace_id: str | None
    role: str
    brand_space_id: str | None = None

    @property
    def owner_scope(self) -> str:
        return f"ws:{self.workspace_id}" if self.workspace_id else f"user:{self.user_id}"

    @property
    def can_manage(self) -> bool:
        return self.role in MANAGING_ROLES

    def require_manage(self) -> None:
        if not self.can_manage:
            raise IntegrationError(403, "Only workspace owners and admins can change integrations.")


def _role(session: Any, workspace_id: str, user_id: str) -> str:
    from app.models.db.models import WorkspaceMember

    role = session.execute(select(WorkspaceMember.role).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)).scalar_one_or_none()
    if role is None:
        raise IntegrationError(403, "You are not a member of this workspace.")
    return str(role or "member")


def brand_space_belongs(session: Any, scope_user: str, workspace_id: str | None, brand_space_id: str) -> bool:
    from app.models.db.models import UserPreset

    kit = session.get(UserPreset, brand_space_id)
    if kit is None:
        return False
    if workspace_id:
        return kit.workspace_id == workspace_id
    return kit.user_id == scope_user and kit.workspace_id is None


def resolve(session: Any, user_id: str, *, workspace_id: str | None = None,
            brand_space_id: str | None = None) -> Scope:
    """Validate membership and the Brand space; raise :class:`IntegrationError` otherwise."""
    uid = str(user_id or "").strip()
    if not uid:
        raise IntegrationError(401, "Sign in first.")
    ws = str(workspace_id or "").strip() or None
    role = _role(session, ws, uid) if ws else "owner"
    brand = str(brand_space_id or "").strip() or None
    if brand and not brand_space_belongs(session, uid, ws, brand):
        raise IntegrationError(404, "Brand space not found.")
    return Scope(user_id=uid, workspace_id=ws, role=role, brand_space_id=brand)


__all__ = ["MANAGING_ROLES", "Scope", "brand_space_belongs", "resolve"]
