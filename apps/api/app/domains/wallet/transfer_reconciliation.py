"""Leased recovery for durable person-to-person Mint transfer commands.

An API process can die after Mint commits but before Menivor stores the signed
result.  ``WalletTransfer(status="pending")`` is the durable recovery command.
This module claims those commands with short database leases and deliberately
re-enters :meth:`WalletService.transfer`: that path reuses the persisted Mint
accounts/operation, invokes Mint idempotently, verifies the pinned attestation,
and projects activity exactly once under a row lock.

The lease coordinates workers; it is not a money lock.  A normal API retry may
race the reconciler safely because Mint and Menivor finalization are already
idempotent at their respective boundaries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.orm import Session

from app.domains.wallet.service import WalletError, WalletService
from app.models.db.marketplace import WalletTransfer


LEASE_SECONDS = 120
MAX_BATCH = 100
MAX_ERROR_LENGTH = 500


@dataclass(frozen=True)
class TransferLease:
    """Immutable command inputs captured by one successful lease claim."""

    transfer_id: str
    owner: str
    sender_user_id: str
    recipient_handle: str
    amount_micros: int
    idempotency_key: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _eligible(now: datetime):
    return and_(
        WalletTransfer.status == "pending",
        or_(
            WalletTransfer.reconcile_after.is_(None),
            WalletTransfer.reconcile_after <= now,
        ),
        or_(
            WalletTransfer.reconcile_lease_owner.is_(None),
            WalletTransfer.reconcile_lease_expires_at.is_(None),
            WalletTransfer.reconcile_lease_expires_at <= now,
        ),
    )


def claim_pending_transfers(
    session: Session,
    *,
    owner: str,
    limit: int = MAX_BATCH,
    now: datetime | None = None,
) -> list[TransferLease]:
    """Atomically lease a bounded set of eligible pending commands.

    The initial select is only a candidate scan.  The conditional UPDATE is
    the claim authority: concurrent workers can inspect the same candidate,
    but only one can change a row while its lease is absent or expired.
    """

    current = now or _utcnow()
    bounded = max(1, min(int(limit), MAX_BATCH))
    candidate_limit = bounded
    stmt = (
        select(WalletTransfer.id)
        .where(_eligible(current))
        .order_by(WalletTransfer.created_at.asc(), WalletTransfer.id.asc())
    )
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        # PostgreSQL workers skip rows another claimant already locked, so a
        # loser immediately advances to the next pending command.
        stmt = stmt.with_for_update(skip_locked=True)
    else:
        # SQLite has no row-level SKIP LOCKED. Scan a small candidate window and
        # let the conditional UPDATE arbitrate each row instead of giving up
        # after a contested oldest command.
        candidate_limit = min(MAX_BATCH, max(16, bounded * 4))
    candidate_ids = list(
        session.execute(stmt.limit(candidate_limit)).scalars()
    )
    claimed: list[TransferLease] = []
    expires_at = current + timedelta(seconds=LEASE_SECONDS)
    for transfer_id in candidate_ids:
        result = session.execute(
            update(WalletTransfer)
            .where(WalletTransfer.id == transfer_id, _eligible(current))
            .values(
                reconcile_lease_owner=owner,
                reconcile_lease_expires_at=expires_at,
                reconcile_last_attempt_at=current,
                reconcile_attempts=WalletTransfer.reconcile_attempts + 1,
                reconcile_last_error=None,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            continue
        transfer = session.get(WalletTransfer, transfer_id)
        if transfer is None:  # defensive; the UPDATE held the row
            continue
        claimed.append(
            TransferLease(
                transfer_id=transfer.id,
                owner=owner,
                sender_user_id=transfer.sender_user_id,
                recipient_handle=transfer.recipient_handle,
                amount_micros=int(transfer.amount_micros),
                idempotency_key=transfer.idempotency_key,
            )
        )
        if len(claimed) >= bounded:
            break
    session.commit()
    return claimed


def _backoff_seconds(attempts: int) -> int:
    # Retry quickly after the first ambiguous failure, then cap at five minutes.
    return min(300, 15 * (2 ** min(max(0, attempts - 1), 5)))


def finish_transfer_lease(
    session: Session,
    lease: TransferLease,
    *,
    error: str | None,
    now: datetime | None = None,
) -> bool:
    """Release an owned lease and persist bounded retry diagnostics."""

    current = now or _utcnow()
    attempts = session.scalar(
        select(WalletTransfer.reconcile_attempts).where(
            WalletTransfer.id == lease.transfer_id,
            WalletTransfer.reconcile_lease_owner == lease.owner,
        )
    )
    if attempts is None:
        terminal = session.execute(
            select(
                WalletTransfer.status, WalletTransfer.reconcile_lease_owner
            ).where(WalletTransfer.id == lease.transfer_id)
        ).one_or_none()
        # WalletService intentionally clears the lease when a replay receives a
        # proven non-mutating rejection. That is successful cleanup, not lease
        # loss, even though no fenced release remains to perform here.
        return bool(
            terminal is not None
            and terminal[0] in {"completed", "rejected"}
            and terminal[1] is None
        )
    retry_at = current + timedelta(seconds=_backoff_seconds(int(attempts)))
    bounded_error = (error or "reconciliation incomplete")[:MAX_ERROR_LENGTH]
    # The owner predicate is the fencing token.  A stale worker that resumes
    # after lease expiry cannot clear or overwrite a newer worker's lease.
    result = session.execute(
        update(WalletTransfer)
        .where(
            WalletTransfer.id == lease.transfer_id,
            WalletTransfer.reconcile_lease_owner == lease.owner,
        )
        .values(
            reconcile_after=case(
                (WalletTransfer.status == "completed", None), else_=retry_at
            ),
            reconcile_last_error=case(
                (WalletTransfer.status == "completed", None), else_=bounded_error
            ),
            reconcile_lease_owner=None,
            reconcile_lease_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return result.rowcount == 1


def reconcile_pending_transfers(
    *, limit: int = MAX_BATCH, owner: str | None = None
) -> dict[str, int]:
    """Run one bounded recovery pass using fresh sessions per external call."""

    from app.models.db.base import get_session

    worker = owner or f"wallet-reconcile-{uuid.uuid4().hex}"
    summary = {
        "claimed": 0,
        "completed": 0,
        "rejected": 0,
        "pending": 0,
        "errored": 0,
        "lost_lease": 0,
    }
    bounded = max(1, min(int(limit), MAX_BATCH))
    for _ in range(bounded):
        # Claim just in time.  A large up-front batch could leave later leases
        # sitting idle until they expire while earlier network calls run.
        with get_session() as session:
            leases = claim_pending_transfers(session, owner=worker, limit=1)
        if not leases:
            break
        lease = leases[0]
        summary["claimed"] += 1
        error: str | None = None
        try:
            # This is the only permitted finalization path. It consumes only
            # the already-authorized durable command: no current RBAC, expired
            # challenge, mutable handle, rollout decision or new Mint operation.
            with get_session() as session:
                result = WalletService(session).execute_persisted_transfer(
                    lease.transfer_id
                )
            if result.get("status") == "completed":
                summary["completed"] += 1
            else:  # defensive: transfer currently returns or raises
                summary["pending"] += 1
                error = "transfer replay returned pending"
        except WalletError as exc:
            error = f"wallet error {exc.status_code}: {exc.message}"
            with get_session() as session:
                status = session.scalar(
                    select(WalletTransfer.status).where(
                        WalletTransfer.id == lease.transfer_id
                    )
                )
            if status == "rejected":
                summary["rejected"] += 1
            else:
                summary["errored"] += 1
                logger.warning(
                    "wallet transfer reconciliation retained pending command {}: {}",
                    lease.transfer_id,
                    error,
                )
        except Exception as exc:  # noqa: BLE001 - isolate one command per pass
            summary["errored"] += 1
            error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "wallet transfer reconciliation failed for {}: {}",
                lease.transfer_id,
                error,
            )

        try:
            with get_session() as session:
                if not finish_transfer_lease(session, lease, error=error):
                    summary["lost_lease"] += 1
        except Exception as exc:  # noqa: BLE001 - retain the completed pass summary
            summary["lost_lease"] += 1
            logger.error(
                "wallet transfer lease cleanup failed for {}: {}",
                lease.transfer_id,
                exc,
            )
    return summary
