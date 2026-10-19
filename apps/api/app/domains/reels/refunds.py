"""Once-only credit refunds + owner cancel for reel jobs.

Classic (non-wallet) reels are paid up front with a ``CreditLedger`` debit tagged
with the job id — against the caller's personal balance or a workspace SHARED
pool. Each PROCESSING cycle of a job (create, retry) carries exactly one debit,
so the refund rule is:

    refund the NEWEST debit of the job, unless a positive (refund/grant) row for
    the same job already exists after it.

That makes the refund idempotent across racing callers (the job row is locked
``FOR UPDATE`` while the check + grant run in one transaction), across Celery
firing several terminal hooks, and across cancel-then-failure sequences, while a
cancelled-then-retried-then-cancelled job is correctly refunded once per cycle.
The refund goes back to whichever pool the debit came from.

Wallet-funded jobs (the ``_wallet`` params marker) never debited the ledger:
:func:`cancel_job` releases their reservation through the wallet bridge instead,
and :func:`refund_latest_debit_once` is a harmless no-op for them.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.models import const
from app.models.exception import HttpException

CANCELLED_STAGE = "cancelled"
CANCELLED_ERROR = "cancelled by user"
CANCEL_REFUND_REASON = "cancel_refund"
FAILURE_REFUND_REASON = "failure_refund"
#: Job kind whose terminal failure is auto-refunded (success-only billing for
#: the reel DAG; other kinds own their own refund hooks).
REEL_KIND = "avatar_reel"


def _locked_job(session: Any, job_id: str):
    from sqlalchemy import select
    from sqlalchemy.exc import NotSupportedError

    from app.models.db.models import Job

    try:
        stmt = select(Job).where(Job.id == job_id).with_for_update()
        return session.execute(stmt).scalars().first()
    except NotSupportedError:
        if session.get_bind().dialect.name != "sqlite":
            raise
        return session.get(Job, job_id)


def _overage_in_cycle(session: Any, job_id: str, latest: Any) -> int:
    """Plan-overage credits granted for this PROCESSING cycle of ``job_id``.

    The cycle starts after the job's previous debit (if any); an overage grant
    is written just before its debit, so it sits between the two.
    """
    if latest.workspace_id:
        return 0
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    previous = session.execute(
        select(CreditLedger.id)
        .where(
            CreditLedger.job_id == job_id,
            CreditLedger.delta < 0,
            CreditLedger.id < latest.id,
        )
        .order_by(CreditLedger.id.desc())
        .limit(1)
    ).scalar()
    try:
        from app.services.billing import dodo_usage
    except Exception:  # noqa: BLE001 - billing optional in minimal builds
        return 0
    granted = dodo_usage.overage_granted_for_job(
        session, job_id, after_ledger_id=int(previous or 0)
    )
    return min(int(granted), -int(latest.delta))


def refund_latest_debit_once_in_session(session: Any, job_id: str, reason: str) -> int:
    """Refund the job's newest un-refunded debit inside ``session``. Returns credits."""
    from sqlalchemy import select

    from app.models.db.models import CreditLedger
    from app.models.db.repositories import CreditRepository

    job = _locked_job(session, job_id)
    if job is None:
        return 0
    latest = session.execute(
        select(CreditLedger)
        .where(CreditLedger.job_id == job_id, CreditLedger.delta < 0)
        .order_by(CreditLedger.id.desc())
        .limit(1)
    ).scalars().first()
    if latest is None:
        return 0
    already = session.execute(
        select(CreditLedger.id)
        .where(
            CreditLedger.job_id == job_id,
            CreditLedger.delta > 0,
            CreditLedger.id > latest.id,
        )
        .limit(1)
    ).scalars().first()
    if already is not None:
        return 0
    amount = -int(latest.delta) - _overage_in_cycle(session, job_id, latest)
    if amount <= 0:
        # The whole debit was covered by a plan-overage grant: the failed reel
        # is never metered, so returning it would leave a free credit behind.
        return 0
    credits = CreditRepository(session)
    if latest.workspace_id:
        credits.workspace_grant(
            latest.workspace_id, amount, reason, actor_user_id=job.user_id, job_id=job_id
        )
    else:
        credits.grant(latest.user_id or job.user_id, amount, reason, job_id=job_id)
    return amount


def refund_latest_debit_once(job_id: str, reason: str) -> int:
    """Own-session wrapper; never raises (logs and returns 0 on failure)."""
    if not job_id:
        return 0
    try:
        from app.models.db.base import get_session

        with get_session() as session:
            return refund_latest_debit_once_in_session(session, job_id, reason)
    except Exception as exc:  # noqa: BLE001 - a refund failure must not mask the caller
        logger.error(f"credit refund failed for job {job_id} ({reason}): {exc}")
        return 0


def refund_failed_reel_once(job_id: str) -> int:
    """Success-only billing for the reel DAG: refund a terminally failed reel.

    Only acts on ``avatar_reel`` jobs that are actually FAILED (other kinds own
    their refund hooks). Idempotent via :func:`refund_latest_debit_once`.
    """
    if not job_id:
        return 0
    try:
        from app.models.db.base import get_session
        from app.models.db.models import Job

        with get_session() as session:
            job = session.get(Job, job_id)
            if job is None or str(job.kind or REEL_KIND) != REEL_KIND:
                return 0
            if job.state != const.TASK_STATE_FAILED:
                return 0
            return refund_latest_debit_once_in_session(session, job_id, FAILURE_REFUND_REASON)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"failure refund failed for job {job_id}: {exc}")
        return 0


STALLED_REFUND_REASON = FAILURE_REFUND_REASON
#: What the owner sees on a reel the reaper stopped (no internals).
STALLED_ERROR = "This reel stopped making progress, so we stopped it and returned your credit."


def fail_and_refund_stalled_reel(job_id: str, stage: str) -> dict[str, Any]:
    """Stop a stalled reel: fail it, stop its chain, give every credit back.

    Same money path as a terminal stage failure (``StageTask.on_failure``):
    the FAILED transition is committed first on its own session, then the
    Celery chain is revoked, the wallet reservation released, premium credits
    returned and the newest ledger debit refunded exactly once. Each step is
    idempotent, so a second reaper pass (or a racing stage failure) never
    refunds twice. Returns ``{"failed": bool, "refunded_credits": int}``;
    ``failed`` is False when the job was no longer PROCESSING.
    """
    from app.models.db.base import get_session
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        job = _locked_job(session, job_id)
        if job is None or job.state != const.TASK_STATE_PROCESSING:
            return {"failed": False, "refunded_credits": 0}
        JobRepository(session).mark_failed(job.id, stage or "stalled", STALLED_ERROR)
        celery_task_id = str(job.celery_task_id or "")
        kind = str(job.kind or REEL_KIND)

    _revoke_celery(celery_task_id)
    try:
        from app.domains.reels.wallet_bridge import safe_release_job_by_id

        safe_release_job_by_id(job_id)
    except Exception as exc:  # noqa: BLE001 - release is best-effort
        logger.error(f"wallet release for stalled job {job_id} failed: {exc}")
    try:
        from app.domains.reels.premium import refund_job as refund_premium

        refund_premium(job_id)
    except Exception as exc:  # noqa: BLE001 - preserve the failure
        logger.error(f"premium refund for stalled job {job_id} failed: {exc}")
    refunded = refund_failed_reel_once(job_id) if kind == REEL_KIND else 0
    return {"failed": True, "refunded_credits": refunded}


def _revoke_celery(celery_task_id: str) -> None:
    if not celery_task_id:
        return
    try:
        from app.workers.celery_app import celery_app

        celery_app.control.revoke(celery_task_id)
    except Exception as exc:  # noqa: BLE001 - workers re-check the failed state anyway
        logger.warning(f"celery revoke failed for {celery_task_id}: {exc}")


#: Kinds an owner may cancel through ``POST /jobs/{id}/cancel``: the reel DAG
#: (credit refunded here) and zero-credit editor exports. Other studio kinds own
#: bespoke refund hooks, so they are only cancellable via the legacy route.
CANCELLABLE_KINDS = frozenset({REEL_KIND, "editor_export", "editor_timeline_export"})


def cancel_job(job_id: str, user_id: str, request_id: str, *, any_kind: bool = False) -> dict:
    """Owner cancel of a PROCESSING job: fail it, stop it, give the money back.

    Order matters: the FAILED/``cancelled`` transition is committed first on its
    own session (so nothing later can undo it), then the Celery chain is revoked,
    then the wallet reservation is released (wallet jobs) and the newest ledger
    debit refunded exactly once (credit jobs) — each in isolated transactions.

    Raises ``HttpException`` 404 (unknown / foreign / deleted) or 409 (already
    finished). Returns ``{job_id, state, status, refunded_credits}``.
    """
    from app.models.db.base import get_session
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        job = _locked_job(session, job_id)
        if (
            job is None
            or str(job.user_id) != str(user_id)
            or getattr(job, "deleted_at", None) is not None
        ):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: job not found")
        kind = str(job.kind or REEL_KIND)
        if not any_kind and kind not in CANCELLABLE_KINDS:
            raise HttpException(task_id=request_id, status_code=409,
                                message=f"{request_id}: this job kind cannot be cancelled")
        if job.state != const.TASK_STATE_PROCESSING:
            raise HttpException(task_id=request_id, status_code=409,
                                message=f"{request_id}: job has already finished")
        JobRepository(session).mark_failed(job.id, CANCELLED_STAGE, CANCELLED_ERROR)
        celery_task_id = str(job.celery_task_id or "")

    _revoke_celery(celery_task_id)
    try:
        from app.domains.reels.wallet_bridge import safe_release_job_by_id

        safe_release_job_by_id(job_id)
    except Exception as exc:  # noqa: BLE001 - release is best-effort
        logger.error(f"wallet release on cancel failed for job {job_id}: {exc}")
    # Credit refunds are owned here only for the reel DAG; other kinds keep
    # their bespoke (flag-guarded) refund hooks so nothing is refunded twice.
    refunded = refund_latest_debit_once(job_id, CANCEL_REFUND_REASON) if kind == REEL_KIND else 0
    # Premium voice / AI-video credits held by the job go back too (idempotent).
    from app.domains.reels.premium import refund_job as refund_premium

    refund_premium(job_id)
    logger.info(
        f"job {job_id} cancelled by owner (refunded={refunded}), request_id: {request_id}"
    )
    return {
        "job_id": job_id,
        "state": const.TASK_STATE_FAILED,
        "status": "cancelled",
        "cancelled": True,
        "refunded_credits": refunded,
    }


def is_cancelled(job: Any) -> bool:
    return (
        getattr(job, "state", None) == const.TASK_STATE_FAILED
        and str(getattr(job, "failed_stage", "") or "") == CANCELLED_STAGE
    )
