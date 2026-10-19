"""Privacy-safe transfer destination resolution over Mint's public addresses."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domains.wallet.repository import WalletRepository
from app.models.db.marketplace import WalletAccount, WalletDestinationProfile
from app.models.db.models import User, Workspace


class WalletDestinationError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ResolvedWalletDestination:
    account: WalletAccount
    kind: str
    principal_ref: str
    destination: str
    label: str
    recipient_user_id: str | None

    @property
    def owner_key(self) -> str:
        return self.principal_ref

    def safe_view(self, *, can_receive: bool = True) -> dict:
        return {
            "handle": self.destination,
            "display_name": self.label,
            "kind": self.kind,
            "can_receive": can_receive,
        }


def _from_account(
    session: Session,
    account: WalletAccount,
    destination: str,
) -> ResolvedWalletDestination:
    edge = WalletRepository(session).get_account_owner(account.id)
    if edge is None:
        raise WalletDestinationError(404, "recipient destination not found")
    if edge.principal_kind == "personal":
        user = session.get(User, edge.principal_ref)
        if user is None or account.user_id != user.id:
            raise WalletDestinationError(404, "recipient destination not found")
        label = user.display_name or user.handle or "Personal wallet"
        return ResolvedWalletDestination(
            account=account,
            kind="personal",
            principal_ref=user.id,
            destination=destination,
            label=label,
            recipient_user_id=user.id,
        )
    if edge.principal_kind == "workspace":
        workspace = session.get(Workspace, edge.principal_ref)
        if workspace is None or account.workspace_id != workspace.id:
            raise WalletDestinationError(404, "recipient destination not found")
        return ResolvedWalletDestination(
            account=account,
            kind="workspace",
            principal_ref=workspace.id,
            destination=destination,
            label=workspace.name or "Workspace wallet",
            recipient_user_id=None,
        )
    if edge.principal_kind in {"agent", "service"}:
        profile = session.get(WalletDestinationProfile, edge.principal_ref)
        if (
            profile is None
            or not profile.active
            or profile.kind != edge.principal_kind
            or profile.account_id != account.id
        ):
            raise WalletDestinationError(404, "recipient destination not found")
        return ResolvedWalletDestination(
            account=account,
            kind=profile.kind,
            principal_ref=profile.id,
            destination=destination,
            label=profile.display_name,
            recipient_user_id=None,
        )
    raise WalletDestinationError(404, "recipient destination not found")


def resolve_destination(
    session: Session,
    raw_destination: str,
    *,
    mint_client: object | None = None,
) -> ResolvedWalletDestination:
    """Resolve an exact public handle or `ait1...` route to one local account."""
    destination = (raw_destination or "").strip().removeprefix("@").strip()
    if not destination or len(destination) > 128:
        raise WalletDestinationError(422, "recipient destination is invalid")
    repo = WalletRepository(session)
    if destination.startswith("ait1"):
        if mint_client is None:
            raise WalletDestinationError(502, "mint client is not configured")
        try:
            mint_account_id = str(mint_client.lookup_address(destination) or "")
        except Exception as exc:  # noqa: BLE001 - normalize Mint's boundary
            status = int(getattr(exc, "status_code", 404) or 404)
            if status >= 500:
                raise WalletDestinationError(
                    502, "mint destination unavailable"
                ) from exc
            raise WalletDestinationError(
                404, "recipient destination not found"
            ) from exc
        account = repo.get_account_by_mint_id(mint_account_id)
        if account is None:
            raise WalletDestinationError(404, "recipient destination not found")
        return _from_account(session, account, destination)

    typed = destination.casefold()
    if typed.startswith(("workspace:", "agent:", "service:")):
        profile = repo.destination_profile_by_handle(typed)
        if profile is None:
            raise WalletDestinationError(404, "recipient destination not found")
        account = repo.get_account_by_source(profile.account_id)
        if account is None:
            raise WalletDestinationError(404, "recipient destination not found")
        resolved = _from_account(session, account, typed)
        if resolved.kind != profile.kind or resolved.principal_ref not in {
            profile.id,
            profile.workspace_id,
        }:
            raise WalletDestinationError(404, "recipient destination not found")
        return resolved

    user = repo.get_user_by_handle(destination)
    if user is None or not user.handle:
        raise WalletDestinationError(404, "recipient handle not found")
    account = repo.get_or_create_personal_account(user.id)
    return ResolvedWalletDestination(
        account=account,
        kind="personal",
        principal_ref=user.id,
        destination=user.handle,
        label=user.display_name or user.handle,
        recipient_user_id=user.id,
    )


__all__ = [
    "ResolvedWalletDestination",
    "WalletDestinationError",
    "resolve_destination",
]
