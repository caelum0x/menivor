"""Support ledger actions (MN6): credit adjustments and job refunds by staff.

Both actions:

* are called only after the controller checked the support admin token AND
  platform-staff status (``admin_service._require_staff``);
* write one immutable ledger row whose reason carries the action and the
  caller's idempotency ref, plus one ``support.*`` audit row with the free-text
  reason, the acting admin and the amounts;
* are idempotent per ``(action, ref)``: a replay returns the first result and
  writes nothing.

``adjust_credits`` grants (positive) or removes (negative, never below 0)
personal credits. ``refund_job`` returns the job's newest un-refunded debit
through the same helper the failure refunds use, so a job is never refunded
twice (and a plan-overage share is never turned into free credit).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_ADJUST = 1000
_REF_RE = re.compile(r"^[A-Za-z0-9._:-]{1,40}$")
ACTION_CREDITS = "support.credits_adjusted"
ACTION_REFUND = "support.job_refunded"


class SupportActionError(ValueError):
    """Bad input or a state conflict; ``status`` is the HTTP code to return."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SupportResult:
    action: str
    ref: str
    user_id: str
    delta: int
    balance_after: int
    replayed: bool
    ledger_id: int | None


def _clean_reason(reason: str) -> str:
    text = re.sub(r"\s+", " ", str(reason or "")).strip()
    if len(text) < 3:
        raise SupportActionError("a reason of at least 3 characters is required")
    return text[:500]


def _clean_ref(ref: str) -> str:
    value = str(ref or "").strip()
    if not _REF_RE.match(value):
        raise SupportActionError("ref must be 1-40 characters of letters, digits, . _ : -")
    return value


def _ledger_row(session: Any, reason: str):
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    return session.execute(
        select(CreditLedger).where(CreditLedger.reason == reason).order_by(CreditLedger.id.asc()).limit(1)
    ).scalars().first()


def _audit_replay(session: Any, action: str, target_id: str):
    from sqlalchemy import select

    from app.models.db.models import AuditLog

    return session.execute(
        select(AuditLog).where(AuditLog.action == action, AuditLog.target_id == target_id[:64])
        .order_by(AuditLog.id.asc()).limit(1)
    ).scalars().first()


def adjust_credits(session: Any, *, admin_id: str, user_id: str, amount: int, reason: str, ref: str) -> SupportResult:
    from app.models.db.models import User
    from app.models.db.repositories import CreditRepository
    from app.services import audit

    ref = _clean_ref(ref)
    note = _clean_reason(reason)
    amount = int(amount)
    if amount == 0 or abs(amount) > MAX_ADJUST:
        raise SupportActionError(f"amount must be between -{MAX_ADJUST} and {MAX_ADJUST}, not 0")
    if session.get(User, user_id) is None:
        raise SupportActionError("user not found", status=404)
    ledger_reason = f"support:credits:{ref}"
    existing = _ledger_row(session, ledger_reason)
    repo = CreditRepository(session)
    if existing is not None:
        if str(existing.user_id) != str(user_id) or int(existing.delta) != amount:
            raise SupportActionError("this ref was already used for a different adjustment", status=409)
        return SupportResult("credits", ref, user_id, int(existing.delta), repo.balance(user_id), True, existing.id)
    if amount > 0:
        row = repo.grant(user_id, amount, ledger_reason)
    else:
        current = repo._locked_balance(user_id)
        if current + amount < 0:
            raise SupportActionError(f"the user has {current} credits; cannot remove {-amount}", status=409)
        row = repo._append(user_id=user_id, delta=amount, reason=ledger_reason,
                           balance_after=current + amount, job_id=None)
    audit.record(
        session, actor_user_id=admin_id, action=ACTION_CREDITS, target_type="user", target_id=f"credits:{ref}",
        metadata={"user_id": user_id, "delta": amount, "balance_after": int(row.balance_after),
                  "reason": note, "ledger_id": row.id},
    )
    return SupportResult("credits", ref, user_id, amount, int(row.balance_after), False, row.id)


def refund_job(session: Any, *, admin_id: str, job_id: str, reason: str) -> SupportResult:
    from app.domains.reels import refunds
    from app.models.db.models import Job
    from app.models.db.repositories import CreditRepository
    from app.services import audit

    note = _clean_reason(reason)
    job = session.get(Job, job_id)
    if job is None:
        raise SupportActionError("job not found", status=404)
    target = f"refund:{job_id}"
    prior = _audit_replay(session, ACTION_REFUND, target)
    repo = CreditRepository(session)
    if prior is not None:
        meta = dict(prior.meta or {})
        return SupportResult("job_refund", job_id, str(job.user_id), int(meta.get("delta", 0)),
                             repo.balance(str(job.user_id)), True, meta.get("ledger_id"))
    ledger_reason = f"support:refund:{job_id}"[:80]
    amount = refunds.refund_latest_debit_once_in_session(session, job_id, ledger_reason)
    if amount <= 0:
        raise SupportActionError("nothing to refund: the job has no un-refunded paid debit", status=409)
    row = _ledger_row(session, ledger_reason)
    balance = repo.balance(str(job.user_id))
    audit.record(
        session, actor_user_id=admin_id, action=ACTION_REFUND, target_type="job", target_id=target,
        metadata={"user_id": str(job.user_id), "job_id": job_id, "delta": amount, "reason": note,
                  "ledger_id": getattr(row, "id", None), "workspace_id": getattr(row, "workspace_id", None)},
    )
    return SupportResult("job_refund", job_id, str(job.user_id), amount, balance, False, getattr(row, "id", None))


__all__ = ["MAX_ADJUST", "SupportActionError", "SupportResult", "adjust_credits", "refund_job"]
