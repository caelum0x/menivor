"""Wallet domain service: balances, purchase quotes, checkout, and the
reserve/settle/release/refund lifecycle that guards every job dispatch.

Owns the money transaction. Enforces the invariants from
PROVIDER_MARKETPLACE_PLAN.md §3:

* credit grants happen **only** from a confirmed payment intent (webhook),
  never a browser redirect;
* a job dispatch reserves the max quoted cost before any provider call;
* settlement charges the actual cost (never above the reservation without a new
  approval) and releases the unused hold;
* duplicate webhooks/settles cannot double-charge or double-grant;
* refunds are append-only compensating entries.

Business failures raise :class:`WalletError` (status + safe message) for the
thin router to map to the shared HTTP envelope.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import usd_to_micros
from app.domains.wallet import policy
from app.domains.wallet.destinations import (
    ResolvedWalletDestination,
    WalletDestinationError,
    resolve_destination,
)
from app.domains.wallet.repository import (
    ENTRY_GRANT,
    ENTRY_REFUND,
    ENTRY_RELEASE,
    ENTRY_RESERVE,
    ENTRY_SETTLE,
    InsufficientFundsError,
    WalletRepository,
)
from app.domains.wallet.schemas import (
    account_view,
    entry_view,
    intent_view,
    transfer_view,
)
from app.domains.wallet.transfer_attestation import (
    TransferAttestationError,
    TransferAttestationExpected,
    load_pinned_public_keys,
    normalize_receipt_operation_hash,
    verify_transfer_attestation,
)
from app.models.db.marketplace import (
    PaymentIntent,
    WalletAccount,
    WalletDestinationProfile,
    WalletSavedRecipient,
    WalletTransfer,
    WalletTransferAttestation,
    WalletTransferChallenge,
    WalletTransferPolicy,
)
from app.models.db.models import User, Workspace, WorkspaceMember
from app.domains.wallet.sources import (
    WalletSourceError,
    list_sources,
    resolve_source,
)


# Mint guarantees these client-error responses did not mutate its ledger.  A
# rejected durable command must never become a surprise transfer later merely
# because funds, account state, or credentials changed before the beat retry.
_DEFINITIVE_MINT_REJECTION_STATUSES = frozenset({400, 401, 402, 403, 404, 409, 422})


class WalletError(Exception):
    """A caller-facing wallet failure carrying an HTTP status + safe message."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _require_p2p_transfers() -> None:
    """M3.3 freeze: refuse a new P2P transfer while the flag is off (status reads still work)."""
    from app.domains.wallet.policy import p2p_transfers_enabled

    if not p2p_transfers_enabled():
        raise WalletError(403, "Sending balance to other users is turned off.")


class WalletService:
    """Transactional wallet operations over one DB session."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = WalletRepository(session)

    # ------------------------------------------------------------------ #
    # Owner resolution (personal vs workspace shared pool)
    # ------------------------------------------------------------------ #
    def _resolve_account(self, user_id: str, workspace_id: str | None, *, create: bool):
        """Resolve the wallet account for the owner (workspace when set)."""
        if workspace_id:
            return (
                self._repo.get_or_create_workspace_account(workspace_id)
                if create
                else self._repo.get_workspace_account(workspace_id)
            )
        return (
            self._repo.get_or_create_personal_account(user_id)
            if create
            else self._repo.get_personal_account(user_id)
        )

    # ------------------------------------------------------------------ #
    # Read surface
    # ------------------------------------------------------------------ #
    def balance_view(self, user_id: str, *, workspace_id: str | None = None) -> dict:
        account = self._resolve_account(user_id, workspace_id, create=True)
        view = account_view(account)
        mint_account_id = str(getattr(account, "mint_account_id", "") or "")
        if not mint_account_id:
            view["settlement_rail"] = "local"
            return view

        owner_key = workspace_id or user_id
        try:
            from app.domains.wallet.mint_client import mint_client_from_config
            from app.domains.wallet.mint_stage import should_use_mint

            if not should_use_mint(owner_key):
                view["settlement_rail"] = "local"
                return view
            client = mint_client_from_config()
            if client is None:
                raise WalletError(502, "mint client is not configured")
            balance = client.read_balance(mint_account_id)
        except WalletError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize the money boundary
            status = int(getattr(exc, "status_code", 502) or 502)
            message = str(getattr(exc, "message", "") or "mint balance unavailable")
            raise WalletError(status, message) from exc

        available = int(balance.get("available_micros", 0) or 0)
        reserved = int(balance.get("held_micros", 0) or 0)
        from app.core.money import micros_to_usd_str

        view.update(
            {
                "settlement_rail": "mint",
                "available_micros": available,
                "reserved_micros": reserved,
                "available_usd": micros_to_usd_str(available),
                "reserved_usd": micros_to_usd_str(reserved),
            }
        )
        return view

    def activity(self, user_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
        account = self._repo.get_personal_account(user_id)
        if account is None:
            return []
        rows = self._repo.list_activity(account.id, limit=limit, offset=offset)
        return [entry_view(r) for r in rows]

    def source_views(self, user_id: str) -> list[dict]:
        """Return selectable account sources without reading Mint balances."""
        try:
            return list_sources(self._session, user_id)
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc

    def set_transfer_policy(
        self,
        user_id: str,
        *,
        source_account_id: str,
        per_transfer_limit_micros: int,
        daily_limit_micros: int,
    ) -> dict:
        """Set send limits through the same fail-closed source authorization."""
        try:
            source = resolve_source(
                self._session, user_id, source_account_id, action="send"
            )
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        per_transfer = int(per_transfer_limit_micros)
        daily = int(daily_limit_micros)
        if not 0 <= per_transfer <= 1_000_000_000:
            raise WalletError(422, "per-transfer limit is outside the supported range")
        if not 0 <= daily <= 1_000_000_000_000:
            raise WalletError(422, "daily limit is outside the supported range")
        self._repo.serialize_account_writes(source.account.id)
        row = self._repo.transfer_policy(source.account.id)
        if row is None:
            row = WalletTransferPolicy(account_id=source.account.id)
            self._session.add(row)
        row.per_transfer_limit_micros = per_transfer
        row.daily_limit_micros = daily
        self._session.flush()
        return {
            "source_account_id": source.account.id,
            "limits": source.safe_view(self._repo)["limits"],
        }

    def balance_for_source(self, user_id: str, source_account_id: str) -> dict:
        try:
            source = resolve_source(self._session, user_id, source_account_id)
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        workspace_id = source.principal_ref if source.kind == "workspace" else None
        view = self.balance_view(user_id, workspace_id=workspace_id)
        view["source"] = source.safe_view(self._repo)
        return view

    def activity_for_source(
        self,
        user_id: str,
        source_account_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        try:
            source = resolve_source(self._session, user_id, source_account_id)
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        rows = self._repo.list_activity(source.account.id, limit=limit, offset=offset)
        return [entry_view(row) for row in rows]

    def receive_address_view(self, user_id: str, source_account_id: str) -> dict:
        """Provision/replay a public destination after source authorization."""
        try:
            source = resolve_source(self._session, user_id, source_account_id)
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        try:
            from app.domains.wallet.mint_accounts import (
                resolve_mint_receive_address,
            )
            from app.domains.wallet.mint_client import mint_client_from_config
            from app.domains.wallet.mint_stage import should_use_mint

            if not should_use_mint(source.owner_key):
                raise WalletError(503, "AI token receiving is not enabled yet")
            client = mint_client_from_config()
            if client is None:
                raise WalletError(502, "mint client is not configured")
            workspace_id = source.principal_ref if source.kind == "workspace" else None
            address = resolve_mint_receive_address(
                self._session,
                user_id,
                workspace_id,
                client=client,
            )
        except WalletError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize the money boundary
            status = int(getattr(exc, "status_code", 502) or 502)
            message = str(
                getattr(exc, "message", "") or "mint receive address unavailable"
            )
            raise WalletError(status, message) from exc
        return {
            "address": address,
            "source": source.safe_view(self._repo),
        }

    def _destination_profile_view(self, profile: WalletDestinationProfile, account) -> dict:
        workspace_source = (
            self._repo.get_workspace_account(profile.workspace_id)
            if profile.workspace_id
            else None
        )
        return {
            "destination_id": profile.id,
            "handle": profile.handle,
            "display_name": profile.display_name,
            "kind": profile.kind,
            "scope": "workspace" if profile.workspace_id else "personal",
            "workspace_source_account_id": (
                workspace_source.id if workspace_source is not None else None
            ),
            "active": bool(profile.active),
            "address": str(getattr(account, "mint_receive_address", "") or ""),
        }

    def _assert_destination_profile_access(
        self, user_id: str, profile: WalletDestinationProfile, *, mutate: bool
    ) -> None:
        if profile.workspace_id:
            membership = (
                self._session.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == profile.workspace_id,
                        WorkspaceMember.user_id == user_id,
                    )
                )
                .scalars()
                .first()
            )
            if membership is None:
                raise WalletError(404, "wallet destination not found")
            if mutate:
                from app.services import rbac

                if not rbac.enforce(membership.role, rbac.PERM_WALLET_TRANSFER):
                    raise WalletError(
                        403,
                        "workspace owner or admin role is required to manage destinations",
                    )
            return
        if profile.owner_user_id != user_id:
            raise WalletError(404, "wallet destination not found")

    def create_destination_profile(
        self,
        user_id: str,
        *,
        kind: str,
        slug: str,
        display_name: str,
        workspace_id: str | None = None,
        workspace_source_account_id: str | None = None,
    ) -> dict:
        """Create a live Mint-backed workspace/agent/service receive identity."""
        normalized_kind = (kind or "").strip().casefold()
        if normalized_kind not in {"workspace", "agent", "service"}:
            raise WalletError(422, "destination kind must be workspace, agent, or service")
        normalized_slug = (slug or "").strip().casefold()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,46}[a-z0-9])?", normalized_slug):
            raise WalletError(
                422, "destination slug must be 3-48 lowercase letters, numbers, or hyphens"
            )
        label = (display_name or "").strip()
        if not label or len(label) > 200:
            raise WalletError(422, "destination display name is required")
        workspace_ref = (workspace_id or "").strip() or None
        workspace_source_id = (workspace_source_account_id or "").strip() or None
        if workspace_source_id:
            try:
                workspace_source = resolve_source(
                    self._session, user_id, workspace_source_id, action="send"
                )
            except WalletSourceError as exc:
                raise WalletError(exc.status_code, exc.message) from exc
            if workspace_source.kind != "workspace":
                raise WalletError(422, "destination scope must use a workspace source")
            if workspace_ref and workspace_ref != workspace_source.principal_ref:
                raise WalletError(409, "workspace destination scope is inconsistent")
            workspace_ref = workspace_source.principal_ref
        if normalized_kind == "workspace" and workspace_ref is None:
            raise WalletError(422, "workspace destinations require workspace_id")
        actor = self._session.get(User, user_id)
        if actor is None:
            raise WalletError(404, "wallet owner not found")

        if workspace_ref:
            workspace = self._session.get(Workspace, workspace_ref)
            if workspace is None:
                raise WalletError(404, "workspace not found")
            probe = WalletDestinationProfile(
                owner_user_id=user_id,
                workspace_id=workspace_ref,
            )
            self._assert_destination_profile_access(user_id, probe, mutate=True)

        handle = f"{normalized_kind}:{normalized_slug}"
        if self._repo.destination_profile_by_handle(handle, include_inactive=True):
            raise WalletError(409, "destination handle is already claimed")

        profile_id = uuid.uuid4().hex
        if normalized_kind == "workspace":
            account = self._repo.get_or_create_workspace_account(workspace_ref)
            principal_ref = workspace_ref
        else:
            account = self._repo.create_principal_account(normalized_kind, profile_id)
            principal_ref = profile_id
        profile = WalletDestinationProfile(
            id=profile_id,
            kind=normalized_kind,
            handle=handle,
            display_name=label,
            account_id=account.id,
            owner_user_id=user_id,
            workspace_id=workspace_ref,
            active=True,
        )
        self._session.add(profile)
        self._session.flush()

        try:
            from app.domains.wallet.mint_accounts import (
                resolve_mint_receive_address_for_principal,
            )
            from app.domains.wallet.mint_client import mint_client_from_config
            from app.domains.wallet.mint_stage import should_use_mint

            if not should_use_mint(principal_ref):
                raise WalletError(503, "AI token receiving is not enabled yet")
            client = mint_client_from_config()
            if client is None:
                raise WalletError(502, "mint client is not configured")
            resolve_mint_receive_address_for_principal(
                self._session,
                account,
                normalized_kind,
                principal_ref,
                client=client,
            )
        except WalletError:
            raise
        except Exception as exc:  # noqa: BLE001
            status = int(getattr(exc, "status_code", 502) or 502)
            message = str(
                getattr(exc, "message", "") or "mint receive address unavailable"
            )
            raise WalletError(status, message) from exc
        return self._destination_profile_view(profile, account)

    def destination_profiles(self, user_id: str) -> list[dict]:
        result = []
        for profile in self._repo.destination_profiles_for_actor(user_id):
            self._assert_destination_profile_access(user_id, profile, mutate=False)
            account = self._repo.get_account_by_source(profile.account_id)
            if account is not None:
                result.append(self._destination_profile_view(profile, account))
        return result

    def destination_profile_balance(self, user_id: str, profile_id: str) -> dict:
        profile = self._repo.destination_profile(profile_id)
        if profile is None:
            raise WalletError(404, "wallet destination not found")
        self._assert_destination_profile_access(user_id, profile, mutate=False)
        account = self._repo.get_account_by_source(profile.account_id)
        if account is None or not account.mint_account_id:
            raise WalletError(503, "wallet destination account is not provisioned")
        try:
            from app.domains.wallet.mint_client import mint_client_from_config

            client = mint_client_from_config()
            if client is None:
                raise WalletError(502, "mint client is not configured")
            balance = client.read_balance(str(account.mint_account_id))
        except WalletError:
            raise
        except Exception as exc:  # noqa: BLE001
            status = int(getattr(exc, "status_code", 502) or 502)
            raise WalletError(status, "mint balance unavailable") from exc
        return {
            "destination": self._destination_profile_view(profile, account),
            "currency": "AIT",
            "available_micros": int(balance.get("available_micros", 0) or 0),
            "held_micros": int(balance.get("held_micros", 0) or 0),
        }

    def destination_profile_activity(
        self, user_id: str, profile_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        profile = self._repo.destination_profile(profile_id)
        if profile is None:
            raise WalletError(404, "wallet destination not found")
        self._assert_destination_profile_access(user_id, profile, mutate=False)
        return [
            entry_view(row)
            for row in self._repo.list_activity(
                profile.account_id, limit=limit, offset=offset
            )
        ]

    def set_destination_profile_active(
        self, user_id: str, profile_id: str, *, active: bool
    ) -> dict:
        profile = self._repo.destination_profile(profile_id)
        if profile is None:
            raise WalletError(404, "wallet destination not found")
        self._assert_destination_profile_access(user_id, profile, mutate=True)
        profile.active = bool(active)
        self._session.flush()
        account = self._repo.get_account_by_source(profile.account_id)
        if account is None:
            raise WalletError(503, "wallet destination account is missing")
        return self._destination_profile_view(profile, account)

    def resolve_recipient(self, user_id: str, handle: str) -> dict:
        """Resolve a public handle/address without exposing internal account ids."""
        normalized = (handle or "").strip().removeprefix("@").strip()
        try:
            client = None
            if normalized.startswith("ait1"):
                from app.domains.wallet.mint_client import mint_client_from_config

                client = mint_client_from_config()
            destination = resolve_destination(
                self._session,
                normalized,
                mint_client=client,
            )
        except WalletDestinationError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        can_receive = not (
            destination.kind == "personal" and destination.recipient_user_id == user_id
        )
        return destination.safe_view(can_receive=can_receive)

    def transfer_status(self, user_id: str, transfer_id: str) -> dict:
        """Return a transfer to its sender; recipients and strangers see 404.

        The persisted Mint proof can contain both post-transfer balances, so it
        deliberately does not share the broader recipient activity boundary.
        """
        transfer = self._repo.get_transfer_for_sender(transfer_id, user_id)
        if transfer is None:
            raise WalletError(404, "transfer not found")
        return transfer_view(transfer)

    @staticmethod
    def _validate_transfer_inputs(
        recipient_handle: str, amount_micros: int, idempotency_key: str
    ) -> tuple[str, str, int]:
        key = (idempotency_key or "").strip()
        if not key:
            raise WalletError(400, "an Idempotency-Key is required for transfer")
        if len(key) > 128:
            raise WalletError(400, "Idempotency-Key must be at most 128 characters")
        amount = int(amount_micros)
        if amount <= 0 or amount > 1_000_000_000:
            raise WalletError(422, "amount_micros must be between 1 and 1000000000")
        destination = (recipient_handle or "").strip().removeprefix("@").strip()
        if not destination:
            raise WalletError(422, "recipient destination is required")
        if len(destination) > 128:
            raise WalletError(
                422, "recipient destination must be at most 128 characters"
            )
        return key, destination, amount

    @staticmethod
    def _destinations_equal(left: str, right: str) -> bool:
        """Handles are case-insensitive; public Mint addresses are exact routes."""
        if left.startswith("ait1") or right.startswith("ait1"):
            return left == right
        return left.casefold() == right.casefold()

    @staticmethod
    def _challenge_digest(challenge: WalletTransferChallenge) -> str:
        expires = challenge.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        version = int(getattr(challenge, "binding_version", 1) or 1)
        payload = {
            "version": version,
            "actor_user_id": challenge.actor_user_id,
            "source_account_id": challenge.source_account_id,
            "recipient_user_id": challenge.recipient_user_id,
            "recipient_account_id": challenge.recipient_account_id,
            "recipient_handle": challenge.recipient_handle,
            "recipient_display_name": challenge.recipient_display_name,
            "amount_micros": int(challenge.amount_micros),
            "idempotency_key": challenge.idempotency_key,
            "expires_at": expires.astimezone(timezone.utc).isoformat(),
        }
        if version >= 2:
            payload.update(
                {
                    "recipient_kind": challenge.recipient_kind,
                    "recipient_ref": challenge.recipient_ref,
                    "recipient_label": challenge.recipient_label,
                }
            )
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        prefix = f"menivor-transfer-challenge-v{version}\0".encode()
        return hashlib.sha256(prefix + raw).hexdigest()

    def _assert_transfer_limits(self, account_id: str, amount_micros: int) -> None:
        policy_row = self._repo.transfer_policy(account_id)
        per_transfer = int(
            getattr(policy_row, "per_transfer_limit_micros", 1_000_000_000) or 0
        )
        daily = int(getattr(policy_row, "daily_limit_micros", 0) or 0)
        if per_transfer > 0 and amount_micros > per_transfer:
            raise WalletError(422, "amount exceeds this source's per-transfer limit")
        if daily > 0:
            now = datetime.now(timezone.utc)
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            used = self._repo.daily_transfer_total(account_id, day_start)
            if used + amount_micros > daily:
                raise WalletError(422, "amount exceeds this source's UTC daily limit")

    def create_transfer_challenge(
        self,
        user_id: str,
        *,
        source_account_id: str,
        recipient_handle: str,
        amount_micros: int,
        idempotency_key: str,
        saved_recipient_id: str | None = None,
    ) -> dict:
        _require_p2p_transfers()
        key, requested_handle, amount = self._validate_transfer_inputs(
            recipient_handle, amount_micros, idempotency_key
        )
        try:
            source = resolve_source(
                self._session, user_id, source_account_id, action="send"
            )
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        if source.kind == "personal":
            actor = self._session.get(User, user_id)
            if actor is None or not actor.handle:
                raise WalletError(409, "claim a public handle before sending AI tokens")
        self._repo.serialize_account_writes(source.account.id)
        existing = self._repo.challenge_by_key(source.account.id, key)
        if existing is not None:
            if (
                existing.actor_user_id != user_id
                or int(existing.amount_micros) != amount
                or not self._destinations_equal(
                    existing.recipient_handle, requested_handle
                )
            ):
                raise WalletError(409, "Idempotency-Key was used for another review")
            return self._challenge_view(existing, source)

        destination: ResolvedWalletDestination
        saved_account: WalletAccount | None = None
        if saved_recipient_id:
            saved = self._session.get(WalletSavedRecipient, saved_recipient_id)
            if (
                saved is None
                or saved.owner_user_id != user_id
                or saved.source_account_id != source.account.id
            ):
                raise WalletError(404, "saved recipient not found")
            saved_user = self._session.get(User, saved.recipient_user_id)
            saved_account = self._session.get(WalletAccount, saved.recipient_account_id)
            if (
                saved_user is None
                or not saved_user.handle
                or saved_account is None
                or not self._destinations_equal(saved_user.handle, requested_handle)
            ):
                raise WalletError(409, "saved recipient does not match this review")
        try:
            client = None
            if requested_handle.startswith("ait1"):
                from app.domains.wallet.mint_client import mint_client_from_config

                client = mint_client_from_config()
            destination = resolve_destination(
                self._session,
                requested_handle,
                mint_client=client,
            )
        except WalletDestinationError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        if saved_recipient_id and destination.account.id != saved_account.id:
            raise WalletError(409, "saved recipient identity is inconsistent")
        if destination.account.id == source.account.id:
            raise WalletError(409, "cannot send AI tokens to the same account")

        self._assert_transfer_limits(source.account.id, amount)
        challenge = WalletTransferChallenge(
            actor_user_id=user_id,
            source_account_id=source.account.id,
            recipient_user_id=destination.recipient_user_id,
            recipient_account_id=destination.account.id,
            recipient_handle=destination.destination,
            recipient_kind=destination.kind,
            recipient_ref=destination.principal_ref,
            recipient_label=destination.label,
            recipient_display_name=destination.label,
            binding_version=2,
            amount_micros=amount,
            idempotency_key=key,
            binding_sha256="",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        challenge.binding_sha256 = self._challenge_digest(challenge)
        self._session.add(challenge)
        self._session.flush()
        return self._challenge_view(challenge, source)

    def _challenge_view(self, challenge, source) -> dict:
        expires = challenge.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return {
            "challenge_id": challenge.id,
            "source": source.safe_view(self._repo),
            "recipient": {
                "handle": challenge.recipient_handle,
                "display_name": challenge.recipient_display_name,
                "kind": getattr(challenge, "recipient_kind", "personal"),
            },
            "amount_micros": int(challenge.amount_micros),
            "binding_sha256": challenge.binding_sha256,
            "expires_at": expires.astimezone(timezone.utc).isoformat(),
        }

    def transfer(
        self,
        user_id: str,
        *,
        source_account_id: str = "",
        challenge_id: str = "",
        recipient_handle: str,
        amount_micros: int,
        idempotency_key: str,
    ) -> dict:
        """Create or replay one source-bound, challenge-reviewed Mint command."""
        _require_p2p_transfers()
        key, requested_handle, amount = self._validate_transfer_inputs(
            recipient_handle, amount_micros, idempotency_key
        )
        # Internal compatibility for pre-account-graph callers. The HTTP body
        # is strict and always requires both fields; this branch still creates
        # and consumes the same durable server-side review binding.
        if not source_account_id or not challenge_id:
            personal = self._repo.get_or_create_personal_account(user_id)
            review = self.create_transfer_challenge(
                user_id,
                source_account_id=personal.id,
                recipient_handle=requested_handle,
                amount_micros=amount,
                idempotency_key=key,
            )
            source_account_id = personal.id
            challenge_id = str(review["challenge_id"])
        source_account = self._session.get(WalletAccount, source_account_id)
        if source_account is None:
            raise WalletError(404, "wallet source not found")
        self._repo.serialize_account_writes(source_account.id)

        # Load an exact durable retry BEFORE current RBAC or challenge expiry.
        # The command was authorized and consumed its challenge at creation.
        existing = self._repo.get_transfer_by_key(source_account.id, key)
        if existing is not None:
            # A caller who somehow learns another opaque source id and client
            # key must not be able to distinguish an existing command from an
            # inaccessible source. Exact retry authorization is the persisted
            # actor binding, not possession of those identifiers.
            if existing.sender_user_id != user_id:
                raise WalletError(404, "wallet source not found")
            if (
                existing.sender_account_id != source_account_id
                or existing.challenge_id != challenge_id
                or not self._destinations_equal(
                    existing.recipient_handle, requested_handle
                )
                or int(existing.amount_micros) != amount
            ):
                raise WalletError(
                    409, "Idempotency-Key was already used for another transfer"
                )
            if existing.status == "completed" and existing.attestation is not None:
                return transfer_view(existing)
            if existing.status == "rejected":
                raise WalletError(
                    409,
                    existing.reconcile_last_error
                    or "this transfer command was rejected; submit a new transfer",
                )
            return self.execute_persisted_transfer(existing.id)

        try:
            source = resolve_source(
                self._session, user_id, source_account_id, action="send"
            )
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        challenge = self._repo.lock_challenge(challenge_id)
        now = datetime.now(timezone.utc)
        if challenge is None:
            raise WalletError(404, "transfer challenge not found")
        expires = challenge.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if (
            challenge.actor_user_id != user_id
            or challenge.source_account_id != source.account.id
            or challenge.idempotency_key != key
            or not self._destinations_equal(
                challenge.recipient_handle, requested_handle
            )
            or int(challenge.amount_micros) != amount
            or challenge.binding_sha256 != self._challenge_digest(challenge)
        ):
            raise WalletError(409, "transfer challenge does not match this request")
        if challenge.consumed_at is not None:
            raise WalletError(409, "transfer challenge was already consumed")
        if expires <= now:
            # No durable command exists on this branch, so 410 is a definitive
            # pre-money outcome and clients may safely create a fresh review.
            raise WalletError(410, "transfer challenge has expired")
        self._assert_transfer_limits(source.account.id, amount)

        recipient_account = self._session.get(
            WalletAccount, challenge.recipient_account_id
        )
        recipient_edge = self._repo.get_account_owner(challenge.recipient_account_id)
        recipient_kind = str(getattr(challenge, "recipient_kind", "personal"))
        recipient_ref = str(
            getattr(challenge, "recipient_ref", "") or challenge.recipient_user_id or ""
        )
        if (
            recipient_account is None
            or recipient_edge is None
            or recipient_edge.principal_kind != recipient_kind
            or recipient_edge.principal_ref != recipient_ref
            or recipient_account.id == source.account.id
        ):
            raise WalletError(409, "transfer challenge identity is inconsistent")
        if recipient_kind == "personal":
            recipient = self._session.get(User, challenge.recipient_user_id)
            if (
                recipient is None
                or recipient.id != recipient_ref
                or recipient_account.user_id != recipient.id
            ):
                raise WalletError(409, "transfer challenge identity is inconsistent")
        elif recipient_kind == "workspace":
            if (
                challenge.recipient_user_id is not None
                or recipient_account.workspace_id != recipient_ref
            ):
                raise WalletError(409, "transfer challenge identity is inconsistent")
            # A typed workspace handle is a managed product identity layered on
            # the workspace account. Revalidate that identity before persisting
            # the money command so disabling it after review fails closed. A
            # direct ait1 workspace address is account-native and intentionally
            # has no profile lifecycle to consult.
            if challenge.recipient_handle.casefold().startswith("workspace:"):
                profile = self._repo.destination_profile_by_handle(
                    challenge.recipient_handle.casefold(), include_inactive=True
                )
                if (
                    profile is None
                    or not profile.active
                    or profile.kind != "workspace"
                    or profile.workspace_id != recipient_ref
                    or profile.account_id != recipient_account.id
                ):
                    raise WalletError(
                        409, "transfer challenge identity is inconsistent"
                    )
        elif recipient_kind in {"agent", "service"}:
            profile = self._session.get(WalletDestinationProfile, recipient_ref)
            if (
                challenge.recipient_user_id is not None
                or profile is None
                or not profile.active
                or profile.kind != recipient_kind
                or profile.account_id != recipient_account.id
            ):
                raise WalletError(409, "transfer challenge identity is inconsistent")
        else:
            raise WalletError(409, "transfer challenge identity is inconsistent")

        try:
            from app.domains.wallet.mint_accounts import resolve_mint_account
            from app.domains.wallet.mint_client import mint_client_from_config
            from app.domains.wallet.mint_stage import should_use_mint

            client = mint_client_from_config()
            if client is None:
                raise WalletError(502, "mint client is not configured")
            if not should_use_mint(source.owner_key) or not should_use_mint(
                recipient_ref
            ):
                raise WalletError(503, "AI token transfers are not enabled yet")
            workspace_id = source.principal_ref if source.kind == "workspace" else None
            resolve_mint_account(self._session, user_id, workspace_id, client=client)
            from app.domains.wallet.mint_accounts import (
                resolve_mint_account_for_principal,
            )

            resolve_mint_account_for_principal(
                self._session,
                recipient_account,
                recipient_kind,
                recipient_ref,
                client=client,
            )
        except WalletError:
            raise
        except Exception as exc:  # noqa: BLE001
            status = int(getattr(exc, "status_code", 502) or 502)
            message = str(getattr(exc, "message", "") or "mint transfer unavailable")
            raise WalletError(status, message) from exc

        operation_hash = hashlib.sha256(
            f"{source.account.id}\0{key}".encode("utf-8")
        ).hexdigest()
        actor = self._session.get(User, user_id)
        transfer = self._repo.add_transfer(
            WalletTransfer(
                sender_account_id=source.account.id,
                recipient_account_id=recipient_account.id,
                sender_user_id=user_id,
                recipient_user_id=challenge.recipient_user_id,
                sender_handle=(actor.handle or "") if actor is not None else "",
                recipient_handle=challenge.recipient_handle,
                recipient_kind=recipient_kind,
                recipient_ref=recipient_ref,
                recipient_label=(
                    getattr(challenge, "recipient_label", "")
                    or challenge.recipient_display_name
                ),
                sender_source_kind=source.kind,
                sender_source_ref=source.principal_ref,
                sender_source_label=source.label,
                challenge_id=challenge.id,
                amount_micros=amount,
                idempotency_key=key,
                status="pending",
                mint_operation=f"menivor:p2p:{operation_hash}",
            )
        )
        challenge.consumed_at = now
        challenge.consumed_transfer_id = transfer.id
        try:
            self._session.commit()
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            raise WalletError(503, "could not persist transfer command") from exc
        return self.execute_persisted_transfer(transfer.id)

    def execute_persisted_transfer(self, transfer_id: str) -> dict:
        """Execute one already-authorized command without mutable auth inputs."""
        transfer = self._repo.lock_transfer(transfer_id)
        if transfer is None:
            raise WalletError(404, "transfer not found")
        if transfer.status == "completed" and transfer.attestation is not None:
            return transfer_view(transfer)
        if transfer.status == "rejected":
            raise WalletError(409, transfer.reconcile_last_error or "transfer rejected")
        sender_account = self._session.get(WalletAccount, transfer.sender_account_id)
        recipient_account = self._session.get(
            WalletAccount, transfer.recipient_account_id
        )
        if sender_account is None or recipient_account is None:
            raise WalletError(503, "persisted transfer ownership is inconsistent")
        sender_mint_id = str(sender_account.mint_account_id or "")
        recipient_mint_id = str(recipient_account.mint_account_id or "")
        if not sender_mint_id or not recipient_mint_id:
            raise WalletError(503, "persisted transfer account mapping is missing")
        mint_operation = str(transfer.mint_operation or "")
        if not mint_operation:
            operation_hash = hashlib.sha256(
                f"{sender_account.id}\0{transfer.idempotency_key}".encode()
            ).hexdigest()
            mint_operation = f"menivor:p2p:{operation_hash}"
            transfer.mint_operation = mint_operation
        try:
            from app.domains.wallet.mint_client import mint_client_from_config

            client = mint_client_from_config()
            if client is None:
                raise WalletError(502, "mint client is not configured")
            receipt = client.transfer(
                sender_mint_id,
                recipient_mint_id,
                int(transfer.amount_micros),
                mint_operation,
                mint_operation,
            )
        except WalletError:
            raise
        except Exception as exc:  # noqa: BLE001
            status = int(getattr(exc, "status_code", 502) or 502)
            message = str(getattr(exc, "message", "") or "mint transfer failed")
            if status in _DEFINITIVE_MINT_REJECTION_STATUSES:
                rejected = self._repo.lock_transfer(transfer.id)
                if rejected is None:
                    raise WalletError(
                        503, "durable transfer command disappeared"
                    ) from exc
                if rejected.status == "pending":
                    rejected.status = "rejected"
                    rejected.reconcile_last_error = message[:500]
                    rejected.reconcile_after = None
                    rejected.reconcile_lease_owner = None
                    rejected.reconcile_lease_expires_at = None
                    self._session.commit()
            raise WalletError(status, message) from exc

        try:
            transfer = self._repo.lock_transfer(transfer.id)
            if transfer is None:
                raise RuntimeError("durable transfer command disappeared")
            if transfer.status == "completed" and transfer.attestation is not None:
                self._session.commit()
                return transfer_view(transfer)
            raw_proof = receipt.get("receipt")
            body = raw_proof.get("body") if isinstance(raw_proof, dict) else None
            first_seq = int(receipt.get("first_seq", 0) or 0)
            if (
                not isinstance(raw_proof, dict)
                or not isinstance(body, dict)
                or int(body.get("journal_seq", 0) or 0) != first_seq
                or str(body.get("account_id", "")) != sender_mint_id
                or str(body.get("from", "")) != sender_mint_id
                or str(body.get("to", "")) != recipient_mint_id
                or str(body.get("op", "")) != "Transfer"
                or int(body.get("amount_micros", 0) or 0) != int(transfer.amount_micros)
                or not str(raw_proof.get("hash", "") or "")
                or not str(raw_proof.get("sig", "") or "")
            ):
                raise RuntimeError("mint transfer returned an invalid signed receipt")
            operation_hash = normalize_receipt_operation_hash(body.get("op_hash"))
            from app.config import config

            verified = verify_transfer_attestation(
                receipt.get("attestation"),
                TransferAttestationExpected(
                    sender_mint_id=sender_mint_id,
                    recipient_mint_id=recipient_mint_id,
                    mint_operation=mint_operation,
                    amount_micros=int(transfer.amount_micros),
                    sequence=first_seq,
                    operation=str(body.get("op", "")),
                    operation_hash=operation_hash,
                    receipt_hash=str(raw_proof.get("hash", "")),
                    timestamp_ms=int(body.get("ts", 0) or 0),
                ),
                load_pinned_public_keys(
                    config.mint.get("attestation_public_keys_json", "")
                ),
            )
            transfer.attestation = WalletTransferAttestation(
                transfer_id=transfer.id,
                format=verified.format,
                signer_key_id=verified.key_id,
                payload_base64url=verified.payload_base64url,
                digest_sha256=verified.digest_sha256,
                signature_hex=verified.signature_hex,
            )
            transfer.status = "completed"
            transfer.mint_receipt = dict(raw_proof)
            transfer.mint_first_seq = first_seq or None
            transfer.mint_idempotent_replay = bool(
                receipt.get("idempotent_replay", False)
            )
            transfer.completed_at = datetime.now(timezone.utc)
            self._repo.append_transfer_activity(transfer)
            self._session.flush()
            self._session.commit()
        except TransferAttestationError as exc:
            self._session.rollback()
            raise WalletError(
                503,
                "transfer result persistence is uncertain; retry with the same Idempotency-Key",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            raise WalletError(
                503,
                "transfer result persistence is uncertain; retry with the same Idempotency-Key",
            ) from exc
        return transfer_view(transfer, receipt)

    def list_saved_recipients(
        self, user_id: str, *, source_account_id: str
    ) -> list[dict]:
        try:
            resolve_source(self._session, user_id, source_account_id)
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        rows = self._repo.list_saved_recipients(user_id, source_account_id)
        result: list[dict] = []
        for row in rows:
            recipient = self._session.get(User, row.recipient_user_id)
            if recipient is None or not recipient.handle:
                continue
            result.append(
                {
                    "saved_recipient_id": row.id,
                    "handle": recipient.handle,
                    "display_name": recipient.display_name or recipient.handle,
                    "label": row.label,
                }
            )
        return result

    def save_recipient(
        self,
        user_id: str,
        *,
        source_account_id: str,
        recipient_handle: str,
        label: str = "",
    ) -> dict:
        try:
            source = resolve_source(self._session, user_id, source_account_id)
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        recipient = self._repo.get_user_by_handle(
            (recipient_handle or "").strip().removeprefix("@").strip()
        )
        if recipient is None or not recipient.handle:
            raise WalletError(404, "recipient handle not found")
        recipient_account = self._repo.get_or_create_personal_account(recipient.id)
        if recipient_account.id == source.account.id:
            raise WalletError(409, "cannot save the same account as a recipient")
        row = (
            self._session.execute(
                select(WalletSavedRecipient).where(
                    WalletSavedRecipient.owner_user_id == user_id,
                    WalletSavedRecipient.source_account_id == source.account.id,
                    WalletSavedRecipient.recipient_account_id == recipient_account.id,
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            row = WalletSavedRecipient(
                owner_user_id=user_id,
                source_account_id=source.account.id,
                recipient_user_id=recipient.id,
                recipient_account_id=recipient_account.id,
                recipient_handle=recipient.handle,
            )
            self._session.add(row)
        row.recipient_handle = recipient.handle
        row.label = (label or "").strip()[:100]
        self._session.flush()
        return {
            "saved_recipient_id": row.id,
            "handle": recipient.handle,
            "display_name": recipient.display_name or recipient.handle,
            "label": row.label,
        }

    def delete_saved_recipient(
        self,
        user_id: str,
        saved_recipient_id: str,
        *,
        source_account_id: str,
    ) -> None:
        try:
            source = resolve_source(self._session, user_id, source_account_id)
        except WalletSourceError as exc:
            raise WalletError(exc.status_code, exc.message) from exc
        row = self._session.get(WalletSavedRecipient, saved_recipient_id)
        if (
            row is None
            or row.owner_user_id != user_id
            or row.source_account_id != source.account.id
        ):
            raise WalletError(404, "saved recipient not found")
        self._session.delete(row)
        self._session.flush()

    # ------------------------------------------------------------------ #
    # Purchase quote + checkout
    # ------------------------------------------------------------------ #
    def purchase_quote(self, amount_usd: str) -> dict:
        """Compute the checkout money breakdown for a top-up (no persistence)."""
        try:
            credit_micros = usd_to_micros(amount_usd)
        except ValueError as exc:
            raise WalletError(400, str(exc)) from exc
        try:
            return policy.build_purchase_quote(credit_micros)
        except policy.TopUpError as exc:
            raise WalletError(422, str(exc)) from exc

    def create_checkout(
        self,
        user_id: str,
        *,
        amount_usd: str,
        provider: str,
        idempotency_key: str,
        session_factory: "Callable[[Any], dict] | None" = None,
        workspace_id: str | None = None,
    ) -> dict:
        """Create (or return the existing) idempotent checkout intent.

        Idempotent per ``(account, idempotency_key)``: a repeated submit returns
        the same intent instead of minting a second charge. When ``workspace_id``
        is set the top-up funds the workspace shared pool (authorization is the
        router's job); otherwise the caller's personal wallet. When a
        ``session_factory`` is supplied (the router injects the Creem one), a
        hosted checkout session is created and its ``checkout_url`` + ``session_id``
        are returned; ``provider_ref`` is stored so the webhook can correlate.
        """
        if not idempotency_key:
            raise WalletError(400, "an Idempotency-Key is required for checkout")
        provider = str(provider or "creem").strip().lower()
        if provider not in {"creem", "stripe"}:
            raise WalletError(422, f"unsupported wallet payment provider: {provider}")
        account = self._resolve_account(user_id, workspace_id, create=True)

        quote = self.purchase_quote(amount_usd)
        existing = self._repo.get_intent_by_key(account.id, idempotency_key)
        if existing is not None:
            if (
                existing.payment_provider != provider
                or int(existing.credit_micros) != int(quote["credit_micros"])
            ):
                raise WalletError(
                    409,
                    "Idempotency-Key is already bound to a different "
                    "wallet amount or payment provider",
                )
            return intent_view(existing)

        owner_key = workspace_id or user_id
        settlement_meta: dict[str, str] = {"settlement_rail": "local"}
        try:
            from app.domains.wallet.mint_stage import should_use_mint

            use_mint = should_use_mint(owner_key)
        except Exception:  # pragma: no cover - optional rail import/config guard
            use_mint = False
        if use_mint:
            try:
                from app.domains.wallet.mint_accounts import resolve_mint_account

                mint_account_id = resolve_mint_account(
                    self._session, user_id, workspace_id
                )
            except Exception as exc:  # noqa: BLE001 - normalize the money boundary
                status = int(getattr(exc, "status_code", 502) or 502)
                message = str(
                    getattr(exc, "message", "") or "could not provision Mint account"
                )
                raise WalletError(status, message) from exc
            settlement_meta = {
                "settlement_rail": "mint",
                "mint_account_id": mint_account_id,
            }
        intent = PaymentIntent(
            account_id=account.id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            currency=quote["currency"],
            credit_micros=quote["credit_micros"],
            fee_micros=quote["fee_micros"],
            tax_micros=quote["tax_micros"],
            processor_micros=quote["processor_micros"],
            total_charge_micros=quote["total_charge_micros"],
            fee_rate_bps=quote["fee_rate_bps"],
            fee_schedule_version=quote["fee_schedule_version"],
            payment_provider=provider,
            status="pending",
            meta=settlement_meta,
        )
        self._repo.add_intent(intent)

        view = intent_view(intent)
        if session_factory is not None:
            try:
                session = session_factory(intent)
            except Exception as exc:  # noqa: BLE001 - surface as a clean 502
                raise WalletError(
                    502, f"could not create a checkout session: {exc}"
                ) from exc
            checkout_url = str(session.get("checkout_url", "") or "").strip()
            session_id = str(session.get("session_id", "") or "").strip()
            if not checkout_url or not session_id:
                raise WalletError(
                    502,
                    f"{provider} returned an incomplete wallet checkout session",
                )
            intent.provider_ref = session_id
            intent.meta = {
                **(intent.meta if isinstance(intent.meta, dict) else {}),
                "checkout_url": checkout_url,
                "checkout_session_id": session_id,
            }
            self._session.flush()
            view = intent_view(intent)
        return view

    # ------------------------------------------------------------------ #
    # Webhook-confirmed grant (the ONLY path that adds spendable credit)
    # ------------------------------------------------------------------ #
    def confirm_intent(
        self,
        intent_id: str,
        *,
        provider_ref: str = "",
        correlation_id: str = "",
        credit_local: bool = True,
        external_receipt: dict | None = None,
    ) -> dict:
        """Confirm a verified payment intent and grant its credit exactly once.

        Idempotent: a second call for an already-confirmed intent is a no-op that
        returns the same view (a duplicate webhook can never double-grant). The
        caller (billing webhook handler) is responsible for verifying the
        provider signature before invoking this.
        """
        intent = self._repo.get_intent(intent_id)
        if intent is None:
            raise WalletError(404, "payment intent not found")
        # Lock the account row BEFORE the status check, then re-read the intent
        # under that lock. Two concurrent duplicate webhook deliveries for the
        # same intent (provider at-least-once retries, or a paired
        # ``checkout.completed`` + ``payment.succeeded``) can each read the intent
        # while it is still ``pending`` before either commits; the in-memory
        # status guard alone would then let BOTH append a GRANT entry — a
        # double-grant of spendable credit. The account lock serializes them so
        # the second delivery blocks until the first grant commits, and the
        # refresh makes it observe the now-``confirmed`` status and no-op. Mirrors
        # the settle/release ``_settled_once`` guard.
        self._repo._lock_account(intent.account_id)
        self._session.refresh(intent)
        if intent.status == "confirmed":
            return intent_view(intent)
        if intent.status in {"failed", "canceled", "expired"}:
            raise WalletError(409, f"payment intent is {intent.status}")

        intent.status = "confirmed"
        intent.confirmed_at = datetime.now(timezone.utc)
        if provider_ref:
            intent.provider_ref = provider_ref
        meta = {"fee_schedule_version": intent.fee_schedule_version}
        if not credit_local:
            meta.update(
                {
                    "settlement_rail": "mint",
                    "mint_account_id": str(
                        (intent.meta or {}).get("mint_account_id", "")
                    ),
                    "external_receipt": external_receipt or {},
                }
            )
        self._repo.append_entry(
            intent.account_id,
            entry_type=ENTRY_GRANT,
            reason="purchase" if credit_local else "purchase_mint",
            available_delta=int(intent.credit_micros) if credit_local else 0,
            payment_intent_id=intent.id,
            correlation_id=correlation_id,
            meta=meta,
        )
        self._session.flush()
        return intent_view(intent)

    def _settled_once(self, account_id: str, job_id: str | None):
        """Return an existing terminal entry for ``job_id`` under the account lock.

        Locks the account row *before* the lookup so two concurrent duplicate
        settle/release calls serialize: the first appends the terminal entry and
        commits; the second sees it here and no-ops. Returns ``None`` (proceed)
        when the job has no terminal entry yet, or when ``job_id`` is absent
        (an internal call with no idempotency key cannot be de-duplicated).
        """
        if not job_id:
            return None
        self._repo._lock_account(account_id)
        return self._repo.get_job_terminal_entry(account_id, job_id)

    # ------------------------------------------------------------------ #
    # Reservation lifecycle (worker/internal — guards job dispatch)
    # ------------------------------------------------------------------ #
    def reserve(
        self,
        user_id: str,
        *,
        amount_micros: int,
        job_id: str | None = None,
        price_version_id: str | None = None,
        correlation_id: str = "",
        workspace_id: str | None = None,
    ) -> dict:
        """Hold ``amount_micros`` against the wallet before dispatching a job.

        Holds against the workspace shared pool when ``workspace_id`` is set,
        otherwise the caller's personal wallet.
        """
        amount = int(amount_micros)
        if amount <= 0:
            raise WalletError(400, "reservation amount must be positive")
        account = self._resolve_account(user_id, workspace_id, create=True)
        try:
            entry = self._repo.append_entry(
                account.id,
                entry_type=ENTRY_RESERVE,
                reason="job_reserve",
                available_delta=-amount,
                reserved_delta=amount,
                job_id=job_id,
                price_version_id=price_version_id,
                correlation_id=correlation_id,
            )
        except InsufficientFundsError as exc:
            raise WalletError(
                402, f"insufficient wallet balance (need {exc.required} micros)"
            ) from exc
        return entry_view(entry)

    def settle(
        self,
        user_id: str,
        *,
        reserved_micros: int,
        actual_micros: int,
        job_id: str | None = None,
        correlation_id: str = "",
        workspace_id: str | None = None,
    ) -> dict:
        """Charge the actual cost and release the unused reservation.

        ``actual`` may never exceed the reserved max without a fresh approval
        (§3 invariant); that raises 409 rather than silently overcharging.
        """
        reserved = int(reserved_micros)
        actual = int(actual_micros)
        if reserved < 0 or actual < 0:
            raise WalletError(400, "settle amounts must be non-negative")
        if actual > reserved:
            raise WalletError(
                409, "actual cost exceeds the reserved maximum; re-approval required"
            )
        account = self._resolve_account(user_id, workspace_id, create=False)
        if account is None:
            raise WalletError(404, "wallet account not found")
        # Idempotent per job: a terminal settle/release hook can fire more than
        # once (Celery at-least-once delivery, retries). Lock the account first
        # so concurrent duplicates serialize, then no-op if this job was already
        # settled/released — re-applying the deltas would free the hold twice.
        existing = self._settled_once(account.id, job_id)
        if existing is not None:
            return entry_view(existing)
        entry = self._repo.append_entry(
            account.id,
            entry_type=ENTRY_SETTLE,
            reason="job_settle",
            # Free the whole hold, charge the actual: net available change = -actual.
            available_delta=(reserved - actual),
            reserved_delta=-reserved,
            job_id=job_id,
            correlation_id=correlation_id,
            meta={"actual_micros": actual, "reserved_micros": reserved},
        )
        return entry_view(entry)

    def release(
        self,
        user_id: str,
        *,
        reserved_micros: int,
        job_id: str | None = None,
        correlation_id: str = "",
        workspace_id: str | None = None,
    ) -> dict:
        """Release a full reservation (job canceled/failed before any charge)."""
        reserved = int(reserved_micros)
        if reserved < 0:
            raise WalletError(400, "release amount must be non-negative")
        account = self._resolve_account(user_id, workspace_id, create=False)
        if account is None:
            raise WalletError(404, "wallet account not found")
        # Idempotent per job (see :meth:`settle`): a duplicate release hook must
        # not return the hold a second time and corrupt a shared pool's balance.
        existing = self._settled_once(account.id, job_id)
        if existing is not None:
            return entry_view(existing)
        entry = self._repo.append_entry(
            account.id,
            entry_type=ENTRY_RELEASE,
            reason="job_release",
            available_delta=reserved,
            reserved_delta=-reserved,
            job_id=job_id,
            correlation_id=correlation_id,
        )
        return entry_view(entry)

    def refund(
        self,
        user_id: str,
        *,
        amount_micros: int,
        reason: str = "provider_refund",
        job_id: str | None = None,
        correlation_id: str = "",
    ) -> dict:
        """Append a compensating credit (never mutate a historical charge row)."""
        amount = int(amount_micros)
        if amount <= 0:
            raise WalletError(400, "refund amount must be positive")
        account = self._repo.get_or_create_personal_account(user_id)
        entry = self._repo.append_entry(
            account.id,
            entry_type=ENTRY_REFUND,
            reason=reason,
            available_delta=amount,
            job_id=job_id,
            correlation_id=correlation_id,
        )
        return entry_view(entry)
