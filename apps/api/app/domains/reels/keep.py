"""Charge on keep (M3.1, WP3.1).

With ``MENIVOR_CHARGE_ON_KEEP`` on, a create with several variants debits
variant 1 at create and renders variants 2-3 unpaid. An unpaid variant shows
its preview but not its clean MP4 until the user keeps it:
``POST /jobs/{id}/keep`` debits its standard credits exactly once (the job
row is locked and the marker plus the ledger are the idempotency record),
into the pool the create would have used.

The job params carry the marker ``_keep = {"credits": n, "workspace_id": w,
"kept": bool}``. A variant with no marker was paid at create. A retry of a
failed unpaid variant debits like any retry and marks it kept.

Other surfaces that hand out the clean MP4 (share links, native publishing,
the editor export) call :func:`require_kept` before they use ``result_key``.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

KEEP_KEY: str = "_keep"


class KeepRequired(Exception):
    """The clean MP4 of an unpaid variant was asked for (answer 402)."""

    code: str = "keep_required"
    status_code: int = 402

    def __init__(self, job_id: str, credits: int) -> None:
        super().__init__(f"keep this variant to download or post it ({credits} credits)")
        self.job_id = str(job_id)
        self.credits = int(credits)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "job_id": self.job_id, "credits": self.credits}


class KeepNotReady(Exception):
    """Only a finished render can be kept (answer 409)."""

    status_code: int = 409


def pending_marker(credits: int, workspace_id: str | None) -> dict[str, Any]:
    """The params entry for a variant rendered unpaid."""
    return {KEEP_KEY: {"credits": int(credits), "workspace_id": workspace_id, "kept": False}}


def _marker(params: Any) -> dict[str, Any] | None:
    if not isinstance(params, dict):
        return None
    marker = params.get(KEEP_KEY)
    return marker if isinstance(marker, dict) else None


def is_pending(params: Any) -> bool:
    """Whether this job is an unpaid variant that has not been kept."""
    marker = _marker(params)
    return marker is not None and not bool(marker.get("kept"))


def keep_view(params: Any) -> dict[str, Any] | None:
    """Public ``keep`` block for a job, or ``None`` for a job paid at create."""
    marker = _marker(params)
    if marker is None:
        return None
    return {"required": not bool(marker.get("kept")), "credits": int(marker.get("credits") or 0)}


def mark_kept(params: Any) -> dict[str, Any]:
    """New params with the marker set to kept (no-op for a job paid at create)."""
    base = dict(params) if isinstance(params, dict) else {}
    marker = _marker(base)
    if marker is None:
        return base
    return {**base, KEEP_KEY: {**marker, "kept": True}}


def require_kept(params: Any, job_id: str) -> None:
    """Raise :class:`KeepRequired` for an unpaid variant (other clean-MP4 surfaces)."""
    marker = _marker(params)
    if marker is not None and not marker.get("kept"):
        raise KeepRequired(job_id, int(marker.get("credits") or 0))


def _charged(session: Any, job_id: str) -> bool:
    """The job's newest debit stands (no refund or grant after it)."""
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    latest = session.execute(
        select(CreditLedger.id)
        .where(CreditLedger.job_id == job_id, CreditLedger.delta < 0)
        .order_by(CreditLedger.id.desc())
        .limit(1)
    ).scalar()
    if latest is None:
        return False
    later = session.execute(
        select(CreditLedger.id)
        .where(CreditLedger.job_id == job_id, CreditLedger.delta > 0, CreditLedger.id > latest)
        .limit(1)
    ).scalar()
    return later is None


def keep_job(session: Any, *, job_id: str, user_id: str) -> dict[str, Any]:
    """Keep one variant: debit its credits once and unlock its clean MP4.

    Returns ``{"job_id", "kept": True, "debited": n}``; a second call (or a job
    paid at create) debits nothing. Raises ``LookupError`` for an unknown or
    foreign job, :class:`KeepNotReady` before the render is complete, and
    ``ValueError`` when the pool cannot cover the credits.
    """
    from app.core.capabilities import pilot_debit_reason
    from app.domains.reels.policy import JOB_DEBIT_REASON
    from app.domains.reels.refunds import _locked_job
    from app.models import const
    from app.models.db.repositories import CreditRepository

    job = _locked_job(session, job_id)
    if job is None or str(job.user_id) != str(user_id) or getattr(job, "deleted_at", None):
        raise LookupError("job not found")
    params = dict(job.params or {})
    marker = _marker(params)
    if marker is None or marker.get("kept"):
        return {"job_id": job.id, "kept": True, "debited": 0}
    if job.state != const.TASK_STATE_COMPLETE:
        raise KeepNotReady("only a finished variant can be kept")
    credits = int(marker.get("credits") or 0)
    if credits > 0 and not _charged(session, job.id):
        # Debited as a reel render (same reason as create) so overage metering
        # and the once-only refund rules treat a kept variant like any reel.
        workspace_id = marker.get("workspace_id")
        repo = CreditRepository(session)
        if workspace_id:
            repo.workspace_debit(str(workspace_id), credits, job.id, JOB_DEBIT_REASON)
        else:
            repo.debit(str(user_id), credits, job.id, pilot_debit_reason("reel", JOB_DEBIT_REASON))
    else:
        credits = 0
    job.params = mark_kept(params)
    session.flush()
    logger.info(f"variant {job.id} kept by user {user_id}: {credits} credits")
    return {"job_id": job.id, "kept": True, "debited": credits}


__all__ = [
    "KEEP_KEY",
    "KeepNotReady",
    "KeepRequired",
    "is_pending",
    "keep_job",
    "keep_view",
    "mark_kept",
    "pending_marker",
    "require_kept",
]
