"""One charge path for every render surface (MN1: every render pays).

The classic reel create already debits a credit per job. Autopilot channels,
Ad Studio, editor exports and repurpose runs used to render for free; they now
go through this module so each one:

* debits before anything is queued (balance 0 -> 402, nothing queued),
* debits one credit per render, so a balance of N queues at most N renders,
* refunds a failed render exactly once.

Two kinds of charge exist, because the ledger's ``job_id`` column is a foreign
key to ``jobs``:

* **Job charges** (``debit_job`` / ``debit_or_402``) for renders that own a
  ``jobs`` row (Autopilot reels, editor exports). The debit row carries the job
  id, so the once-only refund in :mod:`app.domains.reels.refunds` applies.
* **Ref charges** (``debit_ref`` / ``debit_ref_or_402`` / ``refund_ref_once``)
  for renders that live in their own tables (Ad Studio variants, repurpose
  runs). The debit reason is ``"{kind}_debit:{ref}"`` and the refund reason is
  ``"{kind}_refund:{ref}:{debit_id}"``; the refund check and grant run under the
  user-row lock, so a racing second refund of the same debit is a no-op. A
  retried render debits again (a new debit id), so each attempt is refunded at
  most once.

Every function takes the caller's session and never commits: the caller's
transaction decides whether the debit and the queued render land together.
"""

from __future__ import annotations

from typing import Any, Iterable

from loguru import logger

from app.models import const
from app.models.exception import HttpException

#: Ref-charge kinds (kept short: ``credit_ledger.reason`` is 80 chars).
ADSTUDIO_KIND = "adstudio"
REPURPOSE_KIND = "repurpose"

#: Job kinds charged through :func:`debit_job` that are not the reel DAG.
EDITOR_EXPORT_KINDS = ("editor_export", "editor_timeline_export")
EDITOR_DEBIT_REASON = "editor_export_debit"
EDITOR_REFUND_REASON = "editor_export_refund"

CREDITS_REQUIRED_CODE = "credits_required"
_REFUND_SCAN_LIMIT = 20


class CreditsRequired(HttpException):
    """402 with a stable ``credits_required`` code the web client can route on."""

    def __init__(self, request_id: str, *, needed: int, available: int, what: str = "render") -> None:
        super().__init__(
            task_id=request_id,
            status_code=402,
            message=f"{request_id}: not enough credits for this {what}",
            data={"code": CREDITS_REQUIRED_CODE, "needed": int(needed), "available": int(available)},
        )
        self.needed = int(needed)
        self.available = int(available)


def unit_cost() -> int:
    """Credits per render (the same knob as a classic reel)."""
    from app.domains.reels.policy import job_cost

    return max(1, int(job_cost()))


def balance(session: Any, user_id: str) -> int:
    from app.models.db.repositories import CreditRepository

    return int(CreditRepository(session).balance(str(user_id)))


# --------------------------------------------------------------------------- #
# Job charges
# --------------------------------------------------------------------------- #
def debit_job(
    session: Any, *, user_id: str, job_id: str, reason: str, amount: int | None = None
) -> bool:
    """Debit ``amount`` (default one render) against ``job_id``. False if short.

    ``CreditRepository.debit`` checks the balance under the user-row lock and
    writes nothing when it raises, so a False return leaves the ledger as it was.
    """
    from app.models.db.repositories import CreditRepository

    cost = unit_cost() if amount is None else int(amount)
    try:
        CreditRepository(session).debit(str(user_id), cost, str(job_id), reason)
    except ValueError:
        return False
    return True


def debit_or_402(
    session: Any,
    *,
    user_id: str,
    job_id: str,
    request_id: str,
    reason: str,
    amount: int | None = None,
    what: str = "render",
) -> None:
    """Debit one render against ``job_id`` or raise :class:`CreditsRequired`."""
    cost = unit_cost() if amount is None else int(amount)
    if not debit_job(session, user_id=user_id, job_id=job_id, reason=reason, amount=cost):
        raise CreditsRequired(request_id, needed=cost, available=balance(session, user_id), what=what)


def refund_job_once(job_id: str, reason: str) -> int:
    """Return a job's newest debit once (own session; never raises)."""
    from app.domains.reels.refunds import refund_latest_debit_once

    return refund_latest_debit_once(job_id, reason)


def refund_failed_job_once(job_id: str) -> int:
    """Refund a FAILED editor export once. Safe to call from any failure hook."""
    if not job_id:
        return 0
    try:
        from app.domains.reels.refunds import refund_latest_debit_once_in_session
        from app.models.db.base import get_session
        from app.models.db.models import Job

        with get_session() as session:
            job = session.get(Job, job_id)
            if job is None or str(job.kind or "") not in EDITOR_EXPORT_KINDS:
                return 0
            if job.state != const.TASK_STATE_FAILED:
                return 0
            return refund_latest_debit_once_in_session(session, job_id, EDITOR_REFUND_REASON)
    except Exception as exc:  # noqa: BLE001 - a refund failure must not mask the caller
        logger.error(f"editor export refund failed for job {job_id}: {exc}")
        return 0


def refund_failed_jobs(session: Any, user_id: str, kinds: Iterable[str]) -> int:
    """Refund every recent FAILED job of ``kinds`` for ``user_id`` not yet refunded.

    A safety net for failure hooks that live outside the render surface (worker
    ``on_failure``, owner cancel, stuck-job reaper). Idempotent: the per-job
    refund checks for an existing refund row after the newest debit.
    """
    from sqlalchemy import select

    from app.domains.reels.refunds import refund_latest_debit_once_in_session
    from app.models.db.models import Job

    kind_list = [str(k) for k in kinds]
    if not user_id or not kind_list:
        return 0
    ids = session.execute(
        select(Job.id)
        .where(
            Job.user_id == str(user_id),
            Job.kind.in_(kind_list),
            Job.state == const.TASK_STATE_FAILED,
        )
        .order_by(Job.created_at.desc())
        .limit(_REFUND_SCAN_LIMIT)
    ).scalars().all()
    total = 0
    for job_id in ids:
        total += refund_latest_debit_once_in_session(session, str(job_id), EDITOR_REFUND_REASON)
    return total


# --------------------------------------------------------------------------- #
# Ref charges (renders without a jobs row)
# --------------------------------------------------------------------------- #
def _debit_reason(kind: str, ref: str) -> str:
    return f"{kind}_debit:{ref}"[:80]


def _refund_reason(kind: str, ref: str, debit_id: int) -> str:
    return f"{kind}_refund:{ref}:{int(debit_id)}"[:80]


def debit_ref(
    session: Any, *, user_id: str, kind: str, ref: str, amount: int | None = None
) -> bool:
    """Debit one render for ``(kind, ref)``. False when the balance is short."""
    from app.models.db.repositories import CreditRepository

    cost = unit_cost() if amount is None else int(amount)
    try:
        # job_id=None: the ledger FK only accepts jobs rows; the ref lives in
        # the reason. (No plan-overage top-up applies without a job id.)
        CreditRepository(session).debit(str(user_id), cost, None, _debit_reason(kind, ref))
    except ValueError:
        return False
    return True


def debit_ref_or_402(
    session: Any,
    *,
    user_id: str,
    kind: str,
    ref: str,
    request_id: str,
    amount: int | None = None,
    what: str = "render",
) -> None:
    cost = unit_cost() if amount is None else int(amount)
    if not debit_ref(session, user_id=user_id, kind=kind, ref=ref, amount=cost):
        raise CreditsRequired(request_id, needed=cost, available=balance(session, user_id), what=what)


def debit_refs_or_402(
    session: Any,
    *,
    user_id: str,
    kind: str,
    refs: list[str],
    request_id: str,
    what: str = "render",
) -> None:
    """All-or-nothing batch: one render per ref, or a 402 naming the full need.

    The caller's transaction rolls back on the raise, so a short balance queues
    nothing (never a partial batch the user did not choose).
    """
    cost = unit_cost()
    need = cost * len(refs)
    have = balance(session, user_id)
    if have < need:
        raise CreditsRequired(request_id, needed=need, available=have, what=what)
    for ref in refs:
        debit_ref_or_402(session, user_id=user_id, kind=kind, ref=ref, request_id=request_id, what=what)


def refund_ref_once(session: Any, *, user_id: str, kind: str, ref: str) -> int:
    """Refund the newest debit of ``(kind, ref)`` exactly once. Returns credits."""
    from sqlalchemy import select

    from app.models.db.models import CreditLedger
    from app.models.db.repositories import CreditRepository

    if not user_id or not ref:
        return 0
    credits = CreditRepository(session)
    # Take the user-row lock first so check-then-grant is serialized.
    credits._locked_balance(str(user_id))  # noqa: SLF001 - same lock debit/grant use
    debit = session.execute(
        select(CreditLedger)
        .where(
            CreditLedger.user_id == str(user_id),
            CreditLedger.workspace_id.is_(None),
            CreditLedger.reason == _debit_reason(kind, ref),
            CreditLedger.delta < 0,
        )
        .order_by(CreditLedger.id.desc())
        .limit(1)
    ).scalars().first()
    if debit is None:
        return 0
    refund_reason = _refund_reason(kind, ref, debit.id)
    already = session.execute(
        select(CreditLedger.id)
        .where(CreditLedger.user_id == str(user_id), CreditLedger.reason == refund_reason)
        .limit(1)
    ).scalars().first()
    if already is not None:
        return 0
    amount = -int(debit.delta)
    credits.grant(str(user_id), amount, refund_reason)
    return amount


def safe_refund_ref_once(*, user_id: str, kind: str, ref: str) -> int:
    """Own-session :func:`refund_ref_once`; logs and returns 0 on failure."""
    try:
        from app.models.db.base import get_session

        with get_session() as session:
            return refund_ref_once(session, user_id=user_id, kind=kind, ref=ref)
    except Exception as exc:  # noqa: BLE001 - never mask the caller's failure
        logger.error(f"refund failed for {kind}:{ref}: {exc}")
        return 0


__all__ = [
    "ADSTUDIO_KIND",
    "CREDITS_REQUIRED_CODE",
    "CreditsRequired",
    "EDITOR_DEBIT_REASON",
    "EDITOR_EXPORT_KINDS",
    "EDITOR_REFUND_REASON",
    "REPURPOSE_KIND",
    "balance",
    "debit_job",
    "debit_or_402",
    "debit_ref",
    "debit_ref_or_402",
    "debit_refs_or_402",
    "refund_failed_job_once",
    "refund_failed_jobs",
    "refund_job_once",
    "refund_ref_once",
    "safe_refund_ref_once",
    "unit_cost",
]
