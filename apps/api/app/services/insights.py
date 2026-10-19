"""Per-user analytics aggregations for the ReelForge creator dashboard.

Computes a small, read-only summary of a single creator's activity from the
ReelForge persistence layer (``Job`` / ``JobEvent`` / ``CreditLedger``). Every
query is **strictly scoped to one ``user_id``** — there is no code path that
aggregates across users, so a creator can never observe another creator's jobs,
spend, or credit balance.

Design rules (per CTO plan §0 "unit economics from job #1"):

* **Read-only.** No INSERT/UPDATE/DELETE; the caller owns the transaction.
* **Resilient.** Optional / newly-added cost columns (``cost_usd``,
  ``duration_ms``) may be absent on older databases; any aggregation failure
  degrades to ``0`` rather than raising, so the dashboard always renders.
* **Scoped.** Cost/duration aggregates join ``job_events`` back to ``jobs`` and
  filter on ``jobs.user_id`` so only the target user's events are summed.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import const
from app.models.db.models import CreditLedger, Job, JobEvent

# Human-readable labels for the reused MPT ``TASK_STATE_*`` integers so the
# dashboard payload is self-describing. Unknown states fall back to their
# stringified integer value.
_STATE_LABELS: dict[int, str] = {
    const.TASK_STATE_FAILED: "failed",
    const.TASK_STATE_COMPLETE: "complete",
    const.TASK_STATE_PROCESSING: "processing",
}

# The compose stage is the render step whose wall-clock ``duration_ms`` we
# surface as the headline "render time" metric.
_COMPOSE_STAGE = "compose"


def _state_label(state: int) -> str:
    """Map a numeric job state to a stable, human-readable label."""
    return _STATE_LABELS.get(state, str(state))


def _jobs_total(session: Session, user_id: str) -> int:
    """Count all jobs owned by ``user_id``."""
    stmt = select(func.count(Job.id)).where(Job.user_id == user_id)
    return int(session.execute(stmt).scalar_one() or 0)


def _jobs_by_state(session: Session, user_id: str) -> dict[str, int]:
    """Return ``{state_label: count}`` for the user's jobs (scoped)."""
    stmt = (
        select(Job.state, func.count(Job.id))
        .where(Job.user_id == user_id)
        .group_by(Job.state)
    )
    rows = session.execute(stmt).all()
    return {_state_label(int(state)): int(count) for state, count in rows}


def _videos_generated(session: Session, user_id: str) -> int:
    """Count the user's successfully completed (rendered) jobs."""
    stmt = select(func.count(Job.id)).where(
        Job.user_id == user_id,
        Job.state == const.TASK_STATE_COMPLETE,
    )
    return int(session.execute(stmt).scalar_one() or 0)


def _credits_balance(session: Session, user_id: str) -> int:
    """Latest ledger balance for the user (newest ``balance_after``)."""
    stmt = (
        select(CreditLedger.balance_after)
        .where(CreditLedger.user_id == user_id)
        .order_by(CreditLedger.id.desc())
        .limit(1)
    )
    latest = session.execute(stmt).scalars().first()
    return int(latest) if latest is not None else 0


def _credits_spent(session: Session, user_id: str) -> int:
    """Total credits debited by the user (sum of the negative deltas' magnitude)."""
    stmt = select(func.coalesce(func.sum(-CreditLedger.delta), 0)).where(
        CreditLedger.user_id == user_id,
        CreditLedger.delta < 0,
    )
    return int(session.execute(stmt).scalar_one() or 0)


def _total_cost_usd(session: Session, user_id: str) -> float:
    """SUM(``job_events.cost_usd``) over the user's jobs (scoped via join).

    Degrades to ``0.0`` if the ``cost_usd`` column is missing on an older DB.
    """
    try:
        stmt = (
            select(func.coalesce(func.sum(JobEvent.cost_usd), 0.0))
            .select_from(JobEvent)
            .join(Job, JobEvent.job_id == Job.id)
            .where(Job.user_id == user_id)
        )
        return float(session.execute(stmt).scalar_one() or 0.0)
    except Exception as exc:  # pragma: no cover - defensive (legacy schema)
        logger.warning(f"total_cost_usd aggregation failed for {user_id}: {exc}")
        return 0.0


def _avg_render_ms(session: Session, user_id: str) -> float:
    """AVG(``job_events.duration_ms``) for the user's *compose* stage events.

    Only compose-stage events are averaged (the render step). Returns ``0.0``
    when there are no compose events yet or the ``duration_ms`` column is absent.
    """
    try:
        stmt = (
            select(func.coalesce(func.avg(JobEvent.duration_ms), 0.0))
            .select_from(JobEvent)
            .join(Job, JobEvent.job_id == Job.id)
            .where(
                Job.user_id == user_id,
                JobEvent.stage == _COMPOSE_STAGE,
            )
        )
        return float(session.execute(stmt).scalar_one() or 0.0)
    except Exception as exc:  # pragma: no cover - defensive (legacy schema)
        logger.warning(f"avg_render_ms aggregation failed for {user_id}: {exc}")
        return 0.0


def user_insights(session: Session, user_id: str) -> dict[str, Any]:
    """Aggregate a single creator's dashboard analytics.

    All figures are strictly scoped to ``user_id`` — no cross-user leakage.

    Args:
        session: An active SQLAlchemy session (read-only; not committed here).
        user_id: The creator whose analytics to compute.

    Returns:
        A JSON-serializable summary::

            {
                "user_id": str,
                "jobs_total": int,
                "jobs_by_state": {state_label: count},
                "credits_balance": int,
                "credits_spent": int,
                "total_cost_usd": float,   # SUM(job_events.cost_usd)
                "avg_render_ms": float,    # AVG(duration_ms) for compose stage
                "videos_generated": int,
            }

    Raises:
        ValueError: If ``user_id`` is empty/blank.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required")

    return {
        "user_id": user_id,
        "jobs_total": _jobs_total(session, user_id),
        "jobs_by_state": _jobs_by_state(session, user_id),
        "credits_balance": _credits_balance(session, user_id),
        "credits_spent": _credits_spent(session, user_id),
        "total_cost_usd": _total_cost_usd(session, user_id),
        "avg_render_ms": _avg_render_ms(session, user_id),
        "videos_generated": _videos_generated(session, user_id),
    }


__all__ = ["user_insights"]
