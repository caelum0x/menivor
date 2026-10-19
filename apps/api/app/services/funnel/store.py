"""Funnel storage: record first-time steps into ``funnel_events``.

* :func:`record_step` — inline, best-effort (never raises) for steps that leave
  no other trace, e.g. a pasted link (``POST /ingest/url`` is stateless).
* :func:`sync_events` — derives the other steps from Menivor's own rows
  (users, credit ledger, jobs, creator plans) and inserts each user's first
  occurrence. Idempotent: back-fills history on the first run, then only adds
  new firsts. No third-party tracker is involved.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger
from sqlalchemy import func, select

import app.models.db.base as db_base
from app.models.const import TASK_STATE_COMPLETE
from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.funnel import FunnelEvent, FunnelReport
from app.models.db.models import CreditLedger, Job, User
from app.services.funnel.internal import internal_user_ids
from app.services.funnel.report import STEP_KEYS, STEPS

# Ledger reason written only when a web card check confirms (card_check.py).
# The mobile_*_signup grants are free device/identity grants with NO card
# check, so they must not count as one.
_CARD_CHECK_UNLOCK_REASON = "signup"
_PURCHASE_PREFIX = "purchase:"
_REFUND_PREFIX = "refund:"
# The $1 card check credits exactly this many reels; anything larger is a pack/plan.
_CARD_CHECK_CREDITS = 1


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def record_step(
    user_id: str | None,
    step: str,
    at: datetime | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> bool:
    """Record ``user_id``'s first ``step`` now. True when a new row was added.

    ``session_factory`` lets a router reuse its own ``get_session`` (the one
    its tests replace) instead of the process default.
    """
    if not user_id or step not in STEP_KEYS:
        return False
    try:
        with (session_factory or db_base.get_session)() as session:
            if session.get(FunnelEvent, (str(user_id), step)) is not None:
                return False
            if str(user_id) in internal_user_ids(session):
                return False
            session.add(
                FunnelEvent(user_id=str(user_id), step=step, occurred_at=at or datetime.now(timezone.utc))
            )
        return True
    except Exception as exc:  # noqa: BLE001 - instrumentation must never break a request
        logger.warning(f"funnel: record {step} failed: {type(exc).__name__}")
        return False


def _signup(session: Any) -> list[tuple[str, datetime]]:
    return list(session.execute(select(User.id, User.created_at)).all())


def _refunded_purchase_reasons(session: Any) -> set[str]:
    """``purchase:<provider>:<ref>`` reasons that were refunded (``refund:<provider>:<ref>``)."""
    refunds = session.execute(
        select(CreditLedger.reason).where(CreditLedger.reason.like(f"{_REFUND_PREFIX}%"))
    ).scalars()
    return {_PURCHASE_PREFIX + r[len(_REFUND_PREFIX):] for r in refunds if r}


def _first_per_user(rows: Any) -> list[tuple[str, datetime]]:
    first: dict[str, datetime] = {}
    for user_id, at in rows:
        at = _utc(at)
        if user_id and at and (user_id not in first or at < first[user_id]):
            first[user_id] = at
    return list(first.items())


def _card_check(session: Any) -> list[tuple[str, datetime]]:
    refunded = _refunded_purchase_reasons(session)
    q = (
        select(CreditLedger.user_id, CreditLedger.created_at, CreditLedger.reason)
        .where(CreditLedger.user_id.is_not(None))
        .where(
            (CreditLedger.reason == _CARD_CHECK_UNLOCK_REASON)
            | CreditLedger.reason.like(f"{_PURCHASE_PREFIX}%")
        )
    )
    return _first_per_user(
        (user_id, at) for user_id, at, reason in session.execute(q).all() if reason not in refunded
    )


def _first_reel(session: Any) -> list[tuple[str, datetime]]:
    q = (
        select(Job.user_id, func.min(Job.updated_at))
        .where(Job.state == TASK_STATE_COMPLETE)
        .group_by(Job.user_id)
    )
    return list(session.execute(q).all())


def _paid(session: Any) -> list[tuple[str, datetime]]:
    refunded = _refunded_purchase_reasons(session)
    packs = (
        select(CreditLedger.user_id, CreditLedger.created_at, CreditLedger.reason)
        .where(CreditLedger.user_id.is_not(None))
        .where(CreditLedger.reason.like(f"{_PURCHASE_PREFIX}%"))
        .where(CreditLedger.delta > _CARD_CHECK_CREDITS)
    )
    plans = select(CreatorSubscription.user_id, func.min(CreatorSubscription.created_at)).group_by(
        CreatorSubscription.user_id
    )
    pack_rows = [(u, at) for u, at, reason in session.execute(packs).all() if reason not in refunded]
    return _first_per_user([*pack_rows, *session.execute(plans).all()])


# Steps derivable from existing rows. ``first_link`` is recorded inline only.
_DERIVED: dict[str, Callable[[Any], list[tuple[str, datetime]]]] = {
    "signup": _signup,
    "card_check": _card_check,
    "first_reel": _first_reel,
    "paid": _paid,
}


def sync_events() -> dict[str, Any]:
    """Insert every user's first occurrence of each derivable step."""
    inserted = 0
    failed: list[str] = []
    for step, source in _DERIVED.items():
        try:
            with db_base.get_session() as session:
                seen = set(
                    session.execute(select(FunnelEvent.user_id).where(FunnelEvent.step == step)).scalars()
                )
                internal = internal_user_ids(session)
                for user_id, at in source(session):
                    at = _utc(at)
                    if not user_id or at is None or user_id in seen or str(user_id) in internal:
                        continue
                    session.add(FunnelEvent(user_id=str(user_id), step=step, occurred_at=at))
                    seen.add(user_id)
                    inserted += 1
        except Exception as exc:  # noqa: BLE001 - one failing step must not stop the rest
            failed.append(step)
            logger.error(f"funnel: sync {step} failed: {type(exc).__name__}: {exc}")
    return {"inserted": inserted, "failed_steps": failed}


def load_counts(since: datetime) -> tuple[dict[str, int], dict[str, int]]:
    """All-time and since-``since`` reach per step."""
    since = _utc(since) or since
    totals: dict[str, int] = {key: 0 for key, _ in STEPS}
    week: dict[str, int] = {key: 0 for key, _ in STEPS}
    with db_base.get_session() as session:
        internal = internal_user_ids(session)
        rows = session.execute(
            select(FunnelEvent.user_id, FunnelEvent.step, FunnelEvent.occurred_at)
        ).all()
        for user_id, step, at in rows:
            if step not in totals or str(user_id) in internal:
                continue
            totals[step] += 1
            at = _utc(at)
            if at is not None and at >= since:
                week[step] += 1
    return totals, week


def claim_week(week_start: str, summary: dict[str, Any]) -> bool:
    """Claim this week's report slot. False when it was already sent."""
    try:
        with db_base.get_session() as session:
            if session.get(FunnelReport, week_start) is not None:
                return False
            session.add(FunnelReport(week_start=week_start, summary=summary))
        return True
    except Exception as exc:  # noqa: BLE001 - a concurrent claim won the insert
        logger.info(f"funnel: week {week_start} already claimed ({type(exc).__name__})")
        return False


def release_week(week_start: str) -> None:
    """Give the slot back after a failed send so the next tick retries."""
    with db_base.get_session() as session:
        row = session.get(FunnelReport, week_start)
        if row is not None:
            session.delete(row)
