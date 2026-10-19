"""Map a ReelForge wallet owner (personal user / workspace pool) to a Mint account.

The payer's Mint ``acct_...`` id is provisioned lazily on first use and cached on
the existing ``wallet_accounts`` row (new nullable ``mint_account_id`` column).
Provisioning is guarded by a row lock (``SELECT … FOR UPDATE``) so two concurrent
first-uses can never mint two Mint accounts for the same owner — Mint's
``POST /v1/accounts`` has no idem_key, so Python owns this uniqueness.

Personal wallet -> Mint ``User`` account; workspace shared pool -> Mint ``Org``
account. The capture destination (treasury) is process-level config, never
per-owner, and is read from the :class:`MintClient`.
"""

from __future__ import annotations

from typing import Any

from app.domains.reels.wallet_bridge import WalletBridgeError
from app.domains.wallet.repository import WalletRepository


_MINT_KIND = {
    "personal": "User",
    "workspace": "Org",
    "agent": "Agent",
    "service": "Provider",
}


def resolve_mint_account_for_principal(
    session: Any,
    account: Any,
    principal_kind: str,
    principal_ref: str,
    *,
    client: Any,
) -> str:
    """Provision one exact ownership edge into its matching Mint account kind."""
    kind = (principal_kind or "").strip()
    ref = (principal_ref or "").strip()
    mint_kind = _MINT_KIND.get(kind)
    if mint_kind is None or not ref:
        raise WalletBridgeError(409, "wallet principal is invalid")
    repo = WalletRepository(session)
    edge = repo.get_account_owner(account.id)
    if edge is None or edge.principal_kind != kind or edge.principal_ref != ref:
        raise WalletBridgeError(409, "wallet account ownership is inconsistent")
    locked = repo._lock_account(account.id) or account
    existing = str(getattr(locked, "mint_account_id", "") or "")
    if existing:
        return existing
    mint_account_id = client.create_account(kind=mint_kind, owner_ref=ref)
    locked.mint_account_id = mint_account_id
    session.flush()
    return str(mint_account_id)


def resolve_mint_receive_address_for_principal(
    session: Any,
    account: Any,
    principal_kind: str,
    principal_ref: str,
    *,
    client: Any,
) -> str:
    """Provision and verify a stable receive route for any product principal."""
    mint_account_id = resolve_mint_account_for_principal(
        session,
        account,
        principal_kind,
        principal_ref,
        client=client,
    )
    repo = WalletRepository(session)
    locked = repo._lock_account(account.id) or account
    existing = str(getattr(locked, "mint_receive_address", "") or "").strip()
    if existing:
        if str(client.lookup_address(existing) or "") != mint_account_id:
            raise WalletBridgeError(502, "stored Mint receive address is misbound")
        return existing
    address = str(client.create_address(mint_account_id, purpose="receive") or "").strip()
    if not address.startswith("ait1") or len(address) > 128:
        raise WalletBridgeError(502, "mint returned an invalid receive address")
    if str(client.lookup_address(address) or "") != mint_account_id:
        raise WalletBridgeError(502, "mint receive address is bound to another account")
    locked.mint_receive_address = address
    session.flush()
    return address


def resolve_mint_account(
    session: Any,
    user_id: str,
    workspace_id: str | None,
    *,
    client: Any | None = None,
) -> str:
    """Return the owner's Mint account id, provisioning + persisting it on first use.

    ``workspace_id`` selects the workspace shared pool (Mint ``Org``); otherwise
    the caller's personal wallet (Mint ``User``). Raises :class:`WalletBridgeError`
    (502) when Mint is not configured — callers only reach here on the Mint path.
    """
    if client is None:
        from app.domains.wallet.mint_client import mint_client_from_config

        client = mint_client_from_config()
    if client is None:
        raise WalletBridgeError(502, "mint client is not configured")

    workspace = (workspace_id or "").strip() or None
    repo = WalletRepository(session)
    if workspace:
        account = repo.get_or_create_workspace_account(workspace)
    else:
        account = repo.get_or_create_personal_account(user_id)

    return resolve_mint_account_for_principal(
        session,
        account,
        "workspace" if workspace else "personal",
        workspace or user_id,
        client=client,
    )


def resolve_mint_receive_address(
    session: Any,
    user_id: str,
    workspace_id: str | None,
    *,
    client: Any | None = None,
) -> str:
    """Return one stable public receive address for an authorized owner.

    Provisioning is serialized by the wallet-account row. The address is
    verified through Mint's authoritative lookup before it is persisted, so a
    malformed or misbound provider response can never become a public route.
    """
    if client is None:
        from app.domains.wallet.mint_client import mint_client_from_config

        client = mint_client_from_config()
    if client is None:
        raise WalletBridgeError(502, "mint client is not configured")

    workspace = (workspace_id or "").strip() or None
    repo = WalletRepository(session)
    account = (
        repo.get_or_create_workspace_account(workspace)
        if workspace
        else repo.get_or_create_personal_account(user_id)
    )
    return resolve_mint_receive_address_for_principal(
        session,
        account,
        "workspace" if workspace else "personal",
        workspace or user_id,
        client=client,
    )


__all__ = [
    "resolve_mint_account",
    "resolve_mint_account_for_principal",
    "resolve_mint_receive_address",
    "resolve_mint_receive_address_for_principal",
]
