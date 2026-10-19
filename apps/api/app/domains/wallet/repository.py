"""Wallet persistence: accounts + append-only ledger with cached balances.

The ledger is the accounting source of truth; :class:`WalletAccount` caches the
newest ``available``/``reserved`` totals for O(1) reads. Every mutation locks the
account row (``SELECT … FOR UPDATE`` on Postgres; a no-op on SQLite) so
concurrent reserves/settles serialize and can never over-spend. Balance
invariants are enforced here — ``available``/``reserved`` may never go negative.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.db.marketplace import (
    PaymentIntent,
    WalletAccount,
    WalletAccountOwner,
    WalletDestinationProfile,
    WalletLedgerEntry,
    WalletSavedRecipient,
    WalletTransfer,
    WalletTransferChallenge,
    WalletTransferPolicy,
)
from app.models.db.models import User, Workspace, WorkspaceMember

# The set of ledger event types. Kept here so the service and tests share one
# vocabulary and a typo can't silently create an unknown event.
ENTRY_GRANT = "grant"
ENTRY_RESERVE = "reserve"
ENTRY_SETTLE = "settle"
ENTRY_RELEASE = "release"
ENTRY_REFUND = "refund"
ENTRY_ADJUSTMENT = "adjustment"
ENTRY_TRANSFER = "transfer"


class InsufficientFundsError(Exception):
    """Raised when a reserve/settle would drive a balance negative."""

    def __init__(self, *, available: int, required: int) -> None:
        super().__init__(
            f"insufficient funds: available={available}, required={required}"
        )
        self.available = available
        self.required = required


class WalletRepository:
    """Reads + append-only writes over ``wallet_accounts`` / ``wallet_ledger_entries``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Accounts
    # ------------------------------------------------------------------ #
    def get_personal_account(self, user_id: str) -> WalletAccount | None:
        stmt = select(WalletAccount).where(WalletAccount.user_id == user_id)
        return self._session.execute(stmt).scalars().first()

    def get_or_create_personal_account(self, user_id: str) -> WalletAccount:
        """Return the user's wallet, creating an empty one on first use."""
        self._lock_principal(User, user_id)
        account = self.get_personal_account(user_id)
        if account is not None:
            self._ensure_owner_edge(account, "personal", user_id)
            return account
        account = WalletAccount(user_id=user_id, available_micros=0, reserved_micros=0)
        try:
            with self._session.begin_nested():
                self._session.add(account)
                self._session.flush()
        except IntegrityError:
            account = self.get_personal_account(user_id)
            if account is None:
                raise
        self._ensure_owner_edge(account, "personal", user_id)
        return account

    def get_workspace_account(self, workspace_id: str) -> WalletAccount | None:
        stmt = select(WalletAccount).where(WalletAccount.workspace_id == workspace_id)
        return self._session.execute(stmt).scalars().first()

    def get_account_by_mint_id(self, mint_account_id: str) -> WalletAccount | None:
        normalized = (mint_account_id or "").strip()
        if not normalized:
            return None
        return (
            self._session.execute(
                select(WalletAccount).where(WalletAccount.mint_account_id == normalized)
            )
            .scalars()
            .first()
        )

    def get_or_create_workspace_account(self, workspace_id: str) -> WalletAccount:
        """Return the workspace's shared wallet, creating an empty one on first use."""
        self._lock_principal(Workspace, workspace_id)
        account = self.get_workspace_account(workspace_id)
        if account is not None:
            self._ensure_owner_edge(account, "workspace", workspace_id)
            return account
        account = WalletAccount(
            workspace_id=workspace_id, available_micros=0, reserved_micros=0
        )
        try:
            with self._session.begin_nested():
                self._session.add(account)
                self._session.flush()
        except IntegrityError:
            account = self.get_workspace_account(workspace_id)
            if account is None:
                raise
        self._ensure_owner_edge(account, "workspace", workspace_id)
        return account

    def _lock_principal(self, model: type, principal_id: str) -> None:
        """Lock the existing owner before first-account creation.

        Unlike an account-row lock, this serializes the first ever wallet
        creation too.  A savepoint-backed unique fallback covers SQLite tests
        and any database that cannot honor the row lock.
        """
        stmt = select(model).where(model.id == principal_id)
        try:
            stmt = stmt.with_for_update()
        except Exception:  # pragma: no cover - dialect without FOR UPDATE
            pass
        if self._session.execute(stmt).scalars().first() is None:
            raise ValueError(f"wallet principal not found: {principal_id}")

    def _ensure_owner_edge(
        self, account: WalletAccount, principal_kind: str, principal_ref: str
    ) -> WalletAccountOwner:
        edge = (
            self._session.execute(
                select(WalletAccountOwner).where(
                    WalletAccountOwner.account_id == account.id
                )
            )
            .scalars()
            .first()
        )
        if edge is not None:
            if (
                edge.principal_kind != principal_kind
                or edge.principal_ref != principal_ref
            ):
                raise ValueError("wallet account ownership edge is inconsistent")
            return edge
        edge = WalletAccountOwner(
            account_id=account.id,
            principal_kind=principal_kind,
            principal_ref=principal_ref,
        )
        self._session.add(edge)
        self._session.flush()
        return edge

    def get_account_owner(self, account_id: str) -> WalletAccountOwner | None:
        return (
            self._session.execute(
                select(WalletAccountOwner).where(
                    WalletAccountOwner.account_id == account_id
                )
            )
            .scalars()
            .first()
        )

    def get_account_by_source(self, account_id: str) -> WalletAccount | None:
        return self._session.get(WalletAccount, account_id)

    def create_principal_account(
        self, principal_kind: str, principal_ref: str
    ) -> WalletAccount:
        """Create a dedicated balance node for an agent/service principal."""
        account = WalletAccount(available_micros=0, reserved_micros=0)
        self._session.add(account)
        self._session.flush()
        self._ensure_owner_edge(account, principal_kind, principal_ref)
        return account

    def destination_profile_by_handle(
        self, handle: str, *, include_inactive: bool = False
    ) -> WalletDestinationProfile | None:
        stmt = select(WalletDestinationProfile).where(
            WalletDestinationProfile.handle == handle
        )
        if not include_inactive:
            stmt = stmt.where(WalletDestinationProfile.active.is_(True))
        return self._session.execute(stmt).scalars().first()

    def destination_profile(self, profile_id: str) -> WalletDestinationProfile | None:
        return self._session.get(WalletDestinationProfile, profile_id)

    def destination_profiles_for_actor(self, user_id: str) -> list[WalletDestinationProfile]:
        workspace_ids = select(WorkspaceMember.workspace_id).where(
            WorkspaceMember.user_id == user_id
        )
        return list(
            self._session.execute(
                select(WalletDestinationProfile)
                .where(
                    (WalletDestinationProfile.owner_user_id == user_id)
                    | (WalletDestinationProfile.workspace_id.in_(workspace_ids))
                )
                .order_by(WalletDestinationProfile.created_at.asc())
            ).scalars()
        )

    def transfer_policy(self, account_id: str) -> WalletTransferPolicy | None:
        return self._session.get(WalletTransferPolicy, account_id)

    def daily_transfer_total(self, account_id: str, day_start) -> int:
        stmt = select(func.coalesce(func.sum(WalletTransfer.amount_micros), 0)).where(
            WalletTransfer.sender_account_id == account_id,
            WalletTransfer.status.in_(("pending", "completed")),
            WalletTransfer.created_at >= day_start,
        )
        return int(self._session.execute(stmt).scalar_one() or 0)

    def get_challenge(self, challenge_id: str) -> WalletTransferChallenge | None:
        return self._session.get(WalletTransferChallenge, challenge_id)

    def lock_challenge(self, challenge_id: str) -> WalletTransferChallenge | None:
        stmt = select(WalletTransferChallenge).where(
            WalletTransferChallenge.id == challenge_id
        )
        try:
            stmt = stmt.with_for_update()
        except Exception:  # pragma: no cover
            pass
        return self._session.execute(stmt).scalars().first()

    def challenge_by_key(
        self, source_account_id: str, idempotency_key: str
    ) -> WalletTransferChallenge | None:
        return (
            self._session.execute(
                select(WalletTransferChallenge).where(
                    WalletTransferChallenge.source_account_id == source_account_id,
                    WalletTransferChallenge.idempotency_key == idempotency_key,
                )
            )
            .scalars()
            .first()
        )

    def list_saved_recipients(
        self, owner_user_id: str, source_account_id: str
    ) -> list[WalletSavedRecipient]:
        return list(
            self._session.execute(
                select(WalletSavedRecipient)
                .where(
                    WalletSavedRecipient.owner_user_id == owner_user_id,
                    WalletSavedRecipient.source_account_id == source_account_id,
                )
                .order_by(WalletSavedRecipient.created_at.desc())
            ).scalars()
        )

    def get_user_by_handle(self, handle: str) -> User | None:
        """Resolve one public creator handle case-insensitively."""
        normalized = (handle or "").strip()
        if not normalized:
            return None
        stmt = (
            select(User).where(func.lower(User.handle) == normalized.lower()).limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def _lock_account(self, account_id: str) -> WalletAccount | None:
        """Load an account with a row lock so concurrent writers serialize."""
        stmt = select(WalletAccount).where(WalletAccount.id == account_id)
        try:
            stmt = stmt.with_for_update()
        except Exception:  # pragma: no cover - dialect without FOR UPDATE
            pass
        return self._session.execute(stmt).scalars().first()

    def serialize_account_writes(self, account_id: str) -> None:
        """Serialize money operations initiated by one wallet account.

        Transfer idempotency is scoped to the sender. Taking the same account
        lock used by ledger writes before checking the transfer record prevents
        two concurrent requests with one client key from both reaching Mint.
        """
        if self._lock_account(account_id) is None:
            raise ValueError(f"wallet account not found: {account_id}")

    # ------------------------------------------------------------------ #
    # Ledger writes
    # ------------------------------------------------------------------ #
    def append_entry(
        self,
        account_id: str,
        *,
        entry_type: str,
        reason: str,
        available_delta: int = 0,
        reserved_delta: int = 0,
        job_id: str | None = None,
        payment_intent_id: str | None = None,
        usage_record_id: str | None = None,
        price_version_id: str | None = None,
        correlation_id: str = "",
        meta: dict | None = None,
    ) -> WalletLedgerEntry:
        """Append one ledger event and update the account balance cache.

        Recomputes and stores the running ``available_after`` / ``reserved_after``
        from the locked account row, then advances the cache. Raises
        :class:`InsufficientFundsError` if either running total would go
        negative, so the caller can surface a 402 without a partial write.
        """
        account = self._lock_account(account_id)
        if account is None:
            raise ValueError(f"wallet account not found: {account_id}")

        new_available = int(account.available_micros) + int(available_delta)
        new_reserved = int(account.reserved_micros) + int(reserved_delta)
        if new_available < 0:
            raise InsufficientFundsError(
                available=int(account.available_micros), required=-int(available_delta)
            )
        if new_reserved < 0:
            raise InsufficientFundsError(
                available=int(account.reserved_micros), required=-int(reserved_delta)
            )

        entry = WalletLedgerEntry(
            account_id=account_id,
            entry_type=entry_type,
            reason=reason,
            available_delta=int(available_delta),
            reserved_delta=int(reserved_delta),
            available_after=new_available,
            reserved_after=new_reserved,
            job_id=job_id,
            payment_intent_id=payment_intent_id,
            usage_record_id=usage_record_id,
            price_version_id=price_version_id,
            correlation_id=correlation_id or "",
            meta=meta or {},
        )
        self._session.add(entry)
        account.available_micros = new_available
        account.reserved_micros = new_reserved
        self._session.flush()
        return entry

    def get_job_terminal_entry(
        self, account_id: str, job_id: str | None
    ) -> WalletLedgerEntry | None:
        """Return an existing settle/release entry for ``job_id``, or None.

        A job has exactly one terminal money outcome — it is settled *or*
        released, never both and never twice. The reserve/settle/release worker
        hooks can fire more than once (Celery at-least-once delivery, retries),
        so the service uses this lookup to make a duplicate settle/release an
        idempotent no-op instead of re-applying the deltas (which would free the
        hold a second time and corrupt a shared pool's balance).
        """
        if not job_id:
            return None
        stmt = (
            select(WalletLedgerEntry)
            .where(
                WalletLedgerEntry.account_id == account_id,
                WalletLedgerEntry.job_id == job_id,
                WalletLedgerEntry.entry_type.in_((ENTRY_SETTLE, ENTRY_RELEASE)),
            )
            .order_by(WalletLedgerEntry.id.asc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def list_activity(
        self, account_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[WalletLedgerEntry]:
        """Return an account's ledger entries, newest first."""
        stmt = (
            select(WalletLedgerEntry)
            .where(WalletLedgerEntry.account_id == account_id)
            .order_by(WalletLedgerEntry.id.desc())
            .limit(max(1, min(200, limit)))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def ledger_sum(self, account_id: str) -> tuple[int, int]:
        """Return (sum available_delta, sum reserved_delta) — a reconciliation check.

        Used by tests/ops to prove the cached account balances equal the ledger.
        """
        from sqlalchemy import func

        stmt = select(
            func.coalesce(func.sum(WalletLedgerEntry.available_delta), 0),
            func.coalesce(func.sum(WalletLedgerEntry.reserved_delta), 0),
        ).where(WalletLedgerEntry.account_id == account_id)
        available, reserved = self._session.execute(stmt).one()
        return int(available or 0), int(reserved or 0)

    # ------------------------------------------------------------------ #
    # Person-to-person Mint transfers (orchestration, not a balance ledger)
    # ------------------------------------------------------------------ #
    def get_transfer_by_key(
        self, sender_account_id: str, idempotency_key: str
    ) -> WalletTransfer | None:
        stmt = select(WalletTransfer).where(
            WalletTransfer.sender_account_id == sender_account_id,
            WalletTransfer.idempotency_key == idempotency_key,
        )
        return self._session.execute(stmt).scalars().first()

    def get_transfer_for_sender(
        self, transfer_id: str, sender_user_id: str
    ) -> WalletTransfer | None:
        """Read one transfer only through its sender ownership boundary."""
        stmt = select(WalletTransfer).where(
            WalletTransfer.id == transfer_id,
            WalletTransfer.sender_user_id == sender_user_id,
        )
        return self._session.execute(stmt).scalars().first()

    def lock_transfer(self, transfer_id: str) -> WalletTransfer | None:
        """Serialize receipt/activity finalization after the Mint call."""
        stmt = select(WalletTransfer).where(WalletTransfer.id == transfer_id)
        try:
            stmt = stmt.with_for_update()
        except Exception:  # pragma: no cover - dialect without FOR UPDATE
            pass
        return self._session.execute(stmt).scalars().first()

    def add_transfer(self, transfer: WalletTransfer) -> WalletTransfer:
        self._session.add(transfer)
        # Claim the unique (sender, idempotency) key before calling Mint.
        self._session.flush()
        return transfer

    def append_transfer_activity(self, transfer: WalletTransfer) -> None:
        """Append safe, zero-delta mirrors after Mint settles the transfer.

        The sorted pre-lock prevents reverse-direction transfers from acquiring
        sender/recipient wallet rows in opposite order. These rows never move a
        Menivor balance; they only make the Mint operation visible in the
        existing wallet activity feed.
        """
        for account_id in sorted(
            (transfer.sender_account_id, transfer.recipient_account_id)
        ):
            if self._lock_account(account_id) is None:
                raise ValueError(f"wallet account not found: {account_id}")

        common = {
            "transfer_id": transfer.id,
            "amount_micros": int(transfer.amount_micros),
            "status": transfer.status,
            "mint_first_seq": transfer.mint_first_seq,
            "source": {
                "source_account_id": transfer.sender_account_id,
                "kind": getattr(transfer, "sender_source_kind", "personal"),
                "label": getattr(transfer, "sender_source_label", ""),
            },
        }
        self.append_entry(
            transfer.sender_account_id,
            entry_type=ENTRY_TRANSFER,
            reason="transfer_sent",
            correlation_id=transfer.id,
            meta={
                **common,
                "direction": "sent",
                "counterparty_handle": (
                    transfer.recipient_handle
                    if getattr(transfer, "recipient_kind", "personal") == "personal"
                    else (
                        getattr(transfer, "recipient_label", "")
                        or transfer.recipient_handle
                    )
                ),
            },
        )
        self.append_entry(
            transfer.recipient_account_id,
            entry_type=ENTRY_TRANSFER,
            reason="transfer_received",
            correlation_id=transfer.id,
            meta={
                **common,
                "direction": "received",
                "counterparty_handle": (
                    getattr(transfer, "sender_source_label", "")
                    or transfer.sender_handle
                ),
            },
        )

    # ------------------------------------------------------------------ #
    # Payment intents (checkout idempotency)
    # ------------------------------------------------------------------ #
    def get_intent_by_key(
        self, account_id: str, idempotency_key: str
    ) -> PaymentIntent | None:
        stmt = select(PaymentIntent).where(
            PaymentIntent.account_id == account_id,
            PaymentIntent.idempotency_key == idempotency_key,
        )
        return self._session.execute(stmt).scalars().first()

    def get_intent(self, intent_id: str) -> PaymentIntent | None:
        return self._session.get(PaymentIntent, intent_id)

    def add_intent(self, intent: PaymentIntent) -> PaymentIntent:
        self._session.add(intent)
        self._session.flush()
        return intent
