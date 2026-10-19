"""``job.failed`` webhook events, with the job's real refund state (MN8).

A render can fail in many places (a stage task, the stuck-reel reaper, an
enqueue failure, a user cancel). Each of those paths already refunds the job
through its own idempotent money hooks. Rather than add a webhook call to every
one of them, this module runs as a short beat sweep
(``app.workers.tasks_webhooks.emit_job_failed_task``): it finds jobs that failed
recently and have had time to settle, reads what the money hooks actually did,
and dispatches one ``job.failed`` event per failure cycle through
:func:`app.services.webhook_subscriptions.dispatch`.

``refunded`` is never guessed. It is ``true`` only when every charge the job
carried (standard credits, premium credits, a wallet hold) has been returned,
as read from the ledgers. A job that was never charged reports
``charged: false, refunded: false``.

Idempotency: the event id is ``job.failed:<job_id>:<cycle>``, where ``cycle`` is
the number of standard-credit debits on the job (one per paid run; at least 1).
The delivery table's UNIQUE ``(subscription_id, event_id)`` makes re-running the
sweep harmless, and a retried-then-failed-again paid job emits a second event.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import const

#: Event type emitted for a terminally failed job.
JOB_FAILED_EVENT: str = "job.failed"
#: A failed job is reported only after its refund hooks had time to run.
SETTLE_SECONDS: int = 30
#: Failed jobs older than this are never reported (the sweep stays cheap).
LOOKBACK_HOURS: int = 24
#: Upper bound on jobs examined per sweep.
SWEEP_LIMIT: int = 200


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _standard_credit_state(session: Session, job_id: str) -> tuple[bool, bool, int, int]:
    """``(charged, refunded, credits_refunded, cycles)`` from the credit ledger."""
    from app.models.db.models import CreditLedger

    debits = session.execute(
        select(CreditLedger.id, CreditLedger.delta)
        .where(CreditLedger.job_id == job_id, CreditLedger.delta < 0)
        .order_by(CreditLedger.id.desc())
    ).all()
    if not debits:
        return False, False, 0, 0
    newest, newest_delta = debits[0]
    returned = session.execute(
        select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
            CreditLedger.job_id == job_id,
            CreditLedger.delta > 0,
            CreditLedger.id > newest,
        )
    ).scalar()
    credits = int(returned or 0)
    # A partial return is not a refund: every credit of the latest charge must be back.
    return True, credits >= -int(newest_delta), credits, len(debits)


def _premium_state(session: Session, job_id: str) -> tuple[bool, bool, int]:
    """``(charged, refunded, credits_refunded)`` over premium voice/video credits."""
    try:
        from app.models.db.premium_credit import PremiumCreditLedger
    except Exception:  # noqa: BLE001 - premium credits absent in minimal builds
        return False, False, 0
    rows = session.execute(
        select(PremiumCreditLedger.delta).where(PremiumCreditLedger.job_id == job_id)
    ).scalars().all()
    debited = -sum(int(d) for d in rows if int(d) < 0)
    if debited <= 0:
        return False, False, 0
    returned = sum(int(d) for d in rows if int(d) > 0)
    return True, returned >= debited, returned


def _wallet_state(session: Session, job_id: str, params: dict) -> tuple[bool, bool]:
    """``(charged, released)`` for a wallet-funded job."""
    marker = params.get("_wallet") if isinstance(params, dict) else None
    if not isinstance(marker, dict) or int(marker.get("reserved_micros", 0) or 0) <= 0:
        return False, False
    if marker.get("mint_hold_id"):
        return True, marker.get("settlement_status") == "released"
    try:
        from app.models.db.marketplace import WalletLedgerEntry
    except Exception:  # noqa: BLE001 - wallet absent in minimal builds
        return True, False
    released = session.execute(
        select(WalletLedgerEntry.id)
        .where(WalletLedgerEntry.job_id == job_id, WalletLedgerEntry.entry_type == "release")
        .limit(1)
    ).scalar()
    return True, released is not None


def refund_state(session: Session, job: Any) -> dict[str, Any]:
    """Read what the money hooks did for ``job``; never infers a refund."""
    params = dict(job.params or {}) if isinstance(job.params, dict) else {}
    std_charged, std_refunded, std_credits, cycles = _standard_credit_state(session, job.id)
    prem_charged, prem_refunded, prem_credits = _premium_state(session, job.id)
    wallet_charged, wallet_released = _wallet_state(session, job.id, params)
    flagged = bool(params.get("refunded"))

    # Other job kinds (speak, dub, broll...) mark their own refund on params.
    returned = [
        done
        for was_charged, done in (
            (std_charged, std_refunded),
            (prem_charged, prem_refunded),
            (wallet_charged, wallet_released),
        )
        if was_charged
    ]
    charged = bool(returned) or flagged
    refunded = all(returned) if returned else flagged
    return {
        "charged": charged,
        "refunded": bool(refunded),
        "credits_refunded": std_credits,
        "premium_credits_refunded": prem_credits,
        "cycle": max(1, cycles),
    }


def job_failed_payload(session: Session, job: Any) -> tuple[str, dict[str, Any]]:
    """Return ``(event_id, payload)`` for a failed ``job``."""
    state = refund_state(session, job)
    failed_at = _aware(job.updated_at)
    payload = {
        "event_type": JOB_FAILED_EVENT,
        "job_id": job.id,
        "status": "failed",
        "failed_stage": str(job.failed_stage or ""),
        "error": str(job.error or ""),
        "charged": state["charged"],
        "refunded": state["refunded"],
        "credits_refunded": state["credits_refunded"],
        "premium_credits_refunded": state["premium_credits_refunded"],
        "failed_at": failed_at.isoformat() if failed_at else None,
    }
    return f"{JOB_FAILED_EVENT}:{job.id}:{state['cycle']}", payload


def _subscribed_workspaces(session: Session) -> set[str]:
    """Workspace ids with at least one enabled ``job.failed`` subscription."""
    from app.models.db.models import WebhookSubscription

    rows = session.execute(
        select(WebhookSubscription.workspace_id, WebhookSubscription.event_types).where(
            WebhookSubscription.enabled.is_(True)
        )
    ).all()
    return {
        str(ws) for ws, events in rows if JOB_FAILED_EVENT in list(events or [])
    }


def emit_failed_jobs(
    session: Session, *, now: datetime | None = None, limit: int = SWEEP_LIMIT
) -> int:
    """Dispatch ``job.failed`` for recently failed jobs. Returns jobs examined.

    Only jobs whose owner belongs to a workspace with an enabled ``job.failed``
    subscription are read, so the sweep is a no-op for everyone else.
    """
    from app.models.db.models import Job, WorkspaceMember
    from app.services import webhook_subscriptions

    workspaces = _subscribed_workspaces(session)
    if not workspaces:
        return 0
    members = session.execute(
        select(WorkspaceMember.user_id, WorkspaceMember.workspace_id).where(
            WorkspaceMember.workspace_id.in_(workspaces)
        )
    ).all()
    by_user: dict[str, list[str]] = {}
    for user_id, ws in members:
        by_user.setdefault(str(user_id), []).append(str(ws))
    if not by_user:
        return 0

    at = now or datetime.now(timezone.utc)
    newest = at - timedelta(seconds=SETTLE_SECONDS)
    oldest = at - timedelta(hours=LOOKBACK_HOURS)
    # SQLite stores naive UTC; compare like with like.
    if session.get_bind().dialect.name == "sqlite":
        newest, oldest = newest.replace(tzinfo=None), oldest.replace(tzinfo=None)
    jobs = session.execute(
        select(Job)
        .where(
            Job.state == const.TASK_STATE_FAILED,
            Job.user_id.in_(list(by_user)),
            Job.updated_at <= newest,
            Job.updated_at >= oldest,
        )
        .order_by(Job.updated_at.asc())
        .limit(max(1, int(limit)))
    ).scalars().all()

    for job in jobs:
        try:
            event_id, payload = job_failed_payload(session, job)
            for ws in sorted(set(by_user.get(str(job.user_id), []))):
                webhook_subscriptions.dispatch(
                    session, ws, JOB_FAILED_EVENT, payload, event_id=event_id, now=at
                )
        except Exception as exc:  # noqa: BLE001 - one job never blocks the sweep
            logger.warning(f"job.failed dispatch for {job.id} failed (non-fatal): {exc}")
    return len(jobs)


__all__ = [
    "JOB_FAILED_EVENT",
    "LOOKBACK_HOURS",
    "SETTLE_SECONDS",
    "emit_failed_jobs",
    "job_failed_payload",
    "refund_state",
]
