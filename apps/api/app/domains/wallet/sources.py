"""Typed, ownership-checked wallet sources over the single wallet ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.wallet.repository import WalletRepository
from app.models.db.marketplace import WalletAccount
from app.models.db.models import User, Workspace, WorkspaceMember
from app.services import rbac


class WalletSourceError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ResolvedWalletSource:
    account: WalletAccount
    kind: str
    principal_ref: str
    label: str
    role: str
    can_send: bool

    @property
    def owner_key(self) -> str:
        return self.principal_ref

    def safe_view(self, repo: WalletRepository) -> dict:
        policy = repo.transfer_policy(self.account.id)
        daily_limit = int(getattr(policy, "daily_limit_micros", 0) or 0)
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_used = repo.daily_transfer_total(self.account.id, day_start)
        return {
            "source_account_id": self.account.id,
            "kind": self.kind,
            "label": self.label,
            "role": self.role,
            "can_send": self.can_send,
            "limits": {
                "per_transfer_micros": int(
                    getattr(policy, "per_transfer_limit_micros", 1_000_000_000)
                    or 0
                ),
                "daily_micros": int(
                    daily_limit
                ),
                "daily_used_micros": daily_used,
                "daily_remaining_micros": (
                    max(0, daily_limit - daily_used) if daily_limit > 0 else None
                ),
            },
        }


def _workspace_membership(
    session: Session, workspace_id: str, actor_user_id: str
) -> WorkspaceMember | None:
    return session.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == actor_user_id,
        )
    ).scalars().first()


def _personal_label(user: User) -> str:
    if user.handle:
        return user.handle
    if user.display_name:
        return user.display_name
    return "Personal wallet"


def resolve_source(
    session: Session,
    actor_user_id: str,
    source_account_id: str,
    *,
    action: str = "read",
) -> ResolvedWalletSource:
    """Resolve an opaque account id through its typed ownership edge.

    Raw account possession is never authorization.  Agent/service owner edges
    are valid graph data but fail closed until a delegation resolver exists.
    """
    account_id = (source_account_id or "").strip()
    if not account_id:
        raise WalletSourceError(400, "source_account_id is required")
    repo = WalletRepository(session)
    account = repo.get_account_by_source(account_id)
    edge = repo.get_account_owner(account_id)
    if account is None or edge is None:
        raise WalletSourceError(404, "wallet source not found")

    if edge.principal_kind == "personal":
        if edge.principal_ref != actor_user_id or account.user_id != actor_user_id:
            raise WalletSourceError(404, "wallet source not found")
        user = session.get(User, actor_user_id)
        if user is None:
            raise WalletSourceError(404, "wallet source not found")
        return ResolvedWalletSource(
            account=account,
            kind="personal",
            principal_ref=actor_user_id,
            label=_personal_label(user),
            role="owner",
            can_send=True,
        )

    if edge.principal_kind == "workspace":
        workspace = session.get(Workspace, edge.principal_ref)
        membership = _workspace_membership(session, edge.principal_ref, actor_user_id)
        if workspace is None or membership is None or account.workspace_id != workspace.id:
            raise WalletSourceError(404, "wallet source not found")
        can_send = rbac.enforce(membership.role, rbac.PERM_WALLET_TRANSFER)
        if action == "send" and not can_send:
            raise WalletSourceError(
                403, "workspace owner or admin role is required to transfer tokens"
            )
        return ResolvedWalletSource(
            account=account,
            kind="workspace",
            principal_ref=workspace.id,
            label=workspace.name or "Workspace wallet",
            role=membership.role,
            can_send=can_send,
        )

    raise WalletSourceError(403, "this wallet source type is not selectable")


def list_sources(session: Session, actor_user_id: str) -> list[dict]:
    repo = WalletRepository(session)
    personal = repo.get_or_create_personal_account(actor_user_id)
    resolved = [resolve_source(session, actor_user_id, personal.id)]
    workspace_ids = list(
        session.execute(
            select(WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == actor_user_id)
            .order_by(WorkspaceMember.created_at.asc())
        ).scalars()
    )
    for workspace_id in workspace_ids:
        account = repo.get_or_create_workspace_account(workspace_id)
        resolved.append(resolve_source(session, actor_user_id, account.id))
    return [source.safe_view(repo) for source in resolved]


__all__ = [
    "ResolvedWalletSource",
    "WalletSourceError",
    "list_sources",
    "resolve_source",
]
