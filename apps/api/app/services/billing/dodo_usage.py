"""Usage-based billing for Dodo monthly plans: overage grants + ``reel.rendered``.

Who is metered: a user whose :class:`CreatorSubscription` is on Dodo
(``provider == "dodo"``), live (``active``/``trialing``), has a Dodo customer id
(``customer_ref``) and a known period end. Free-tier renders, credit-pack
renders, wallet renders and workspace-pool renders are never metered.

At reel SUCCESS (:func:`record_render`) for a metered user in the current
period (period start = ``current_period_end`` minus one month / year):

* fewer events this period than the plan's included reels -> meter (free under
  the Dodo meter's ``free_threshold``);
* else the job was funded by an overage grant (ledger ``overage:<job_id>``) ->
  meter (billed overage);
* else (pack credits paid) -> not metered.

Overage (:func:`overage_allowance`) is OFF for every user until they opt in
(MG6). The opt-in is an append-only :class:`ConsentRecord` of kind
``plan_overage`` whose ``version`` names the terms shown (:func:`consent_version`,
which embeds the cap, so raising the cap needs a fresh opt-in). Only then, when
a live metered subscriber lacks credits for a reel debit,
:class:`CreditRepository.debit` grants the shortfall as ``overage:<job_id>`` so
the render can run and Dodo bills it at the plan's meter price
(:func:`overage_price_usd`, the same formula ``create_dodo_products.py`` puts on
the meter). Capped per period by ``MENIVOR_PLAN_OVERAGE_CAP`` (default 100
reels, 0 disables), switched off for everyone by ``MENIVOR_PLAN_OVERAGE=0``,
and never granted while a Dodo dispute on the account is open.

Delivery: events are written to the ``dodo_usage_events`` outbox and flushed to
``POST /events/ingest`` in batches of at most 1,000 (immediately, then by the
``menivor-flush-dodo-usage`` beat task). 5xx / 429 / transport errors retry with
exponential backoff; any other 4xx is permanent. ``event_id = reel_<job_id>`` is
Dodo's idempotency key, so a re-sent batch never double-bills.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from loguru import logger

EVENT_NAME: str = "reel.rendered"
OVERAGE_REASON_PREFIX: str = "overage"
MAX_BATCH: int = 1000
#: Dodo only accepts timestamps from the last hour; re-stamp older rows.
RESTAMP_AFTER: timedelta = timedelta(minutes=50)
MAX_ATTEMPTS: int = 30
_BACKOFF_BASE_S: int = 30
_BACKOFF_MAX_S: int = 3600
_DEFAULT_OVERAGE_CAP: int = 100
_LIVE: frozenset[str] = frozenset({"active", "trialing"})
#: Ledger debit reasons of a reel render (see reels.policy / pilot_debit_reason).
REEL_DEBIT_REASONS: frozenset[str] = frozenset({"job_debit", "pilot_reel_debit"})
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}
#: ConsentRecord kind of the per-user overage opt-in (MG6).
OVERAGE_CONSENT_KIND: str = "plan_overage"


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def overage_enabled() -> bool:
    raw = str(os.getenv("MENIVOR_PLAN_OVERAGE", "") or "").strip().lower()
    return raw not in _FALSY


def overage_cap() -> int:
    raw = str(os.getenv("MENIVOR_PLAN_OVERAGE_CAP", "") or "").strip()
    if not raw:
        return _DEFAULT_OVERAGE_CAP
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_OVERAGE_CAP


def consent_version() -> str:
    """The terms a user opts in to: the plan's meter rate, capped at N a period."""
    return f"plan-rate-v1-cap{overage_cap()}"


def overage_price_usd(plan_key: str, interval: str) -> str:
    """Dodo meter price per extra reel, e.g. ``"0.4285"`` ('' for an unknown plan).

    Price / included reels, rounded DOWN to a hundredth of a cent, exactly as
    ``tools/ops/create_dodo_products.py`` sets ``price_per_unit`` on the meter.
    """
    from app.services.billing import creator_plans

    plan = creator_plans.get_plan(plan_key)
    interval = creator_plans.normalize_interval(interval)
    if plan is None or plan.period_credits(interval) <= 0:
        return ""
    cents = int(round(plan.price_usd(interval) * 100))
    value = math.floor(cents * 100 / plan.period_credits(interval)) / 100
    return f"{value / 100:.4f}"


def overage_terms() -> dict[str, Any]:
    """Public overage terms for the pricing page and the opt-in toggle."""
    from app.services.billing import creator_plans

    cap = overage_cap()
    return {
        "available": overage_enabled() and cap > 0,
        "default_on": False,
        "cap": cap,
        "consent_kind": OVERAGE_CONSENT_KIND,
        "version": consent_version(),
        "per_reel_usd": {
            plan.key: {i: overage_price_usd(plan.key, i) for i in creator_plans.INTERVALS}
            for plan in creator_plans.list_plans()
        },
    }


def overage_consented(session: Any, user_id: str) -> bool:
    """True when the user's newest ``plan_overage`` decision grants the current terms."""
    from app.models.db.repositories import ConsentRepository

    if not user_id:
        return False
    record = ConsentRepository(session).get_latest(user_id, OVERAGE_CONSENT_KIND)
    if record is None or not bool(record.granted):
        return False
    return str(record.version or "") == consent_version()


def _frozen(session: Any, user_id: str) -> bool:
    """True while a Dodo dispute holds this account's spending (MG2)."""
    from app.services.billing import dodo_billing

    return bool(dodo_billing.open_disputes(session, user_id))


def overage_reason(job_id: str) -> str:
    return f"{OVERAGE_REASON_PREFIX}:{job_id}"[:80]


def event_id_for(job_id: str) -> str:
    return f"reel_{job_id}"


# --------------------------------------------------------------------------- #
# Subscription + period
# --------------------------------------------------------------------------- #
def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _minus_months(moment: datetime, months: int) -> datetime:
    month_index = moment.year * 12 + (moment.month - 1) - months
    year, month = divmod(month_index, 12)
    month += 1
    # Clamp the day (e.g. Mar 31 -> Feb 28/29).
    for day in (moment.day, 30, 29, 28):
        try:
            return moment.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    return moment.replace(year=year, month=month, day=28)  # pragma: no cover


def period_bounds(row: Any) -> tuple[datetime, datetime] | None:
    end = _aware(getattr(row, "current_period_end", None))
    if end is None:
        return None
    months = 12 if str(getattr(row, "interval", "") or "month") == "year" else 1
    return _minus_months(end, months), end


def metered_subscription(session: Any, user_id: str):
    """The user's live Dodo plan row when their renders are metered, else ``None``."""
    from sqlalchemy import select

    from app.models.db.creator_subscription import CreatorSubscription

    if not user_id:
        return None
    row = session.execute(
        select(CreatorSubscription).where(CreatorSubscription.user_id == user_id)
    ).scalars().first()
    if row is None:
        return None
    if str(row.provider or "") != "dodo":
        return None
    if str(row.status or "").lower() not in _LIVE:
        return None
    if not str(row.customer_ref or "").strip() or row.current_period_end is None:
        return None
    return row


def included_reels(row: Any) -> int:
    from app.services.billing import creator_plans

    plan = creator_plans.get_plan(row.plan_key)
    if plan is None:
        return 0
    return int(plan.period_credits(row.interval or creator_plans.MONTH))


# --------------------------------------------------------------------------- #
# Overage (called from CreditRepository.debit)
# --------------------------------------------------------------------------- #
def _overage_used(session: Any, user_id: str, start: datetime) -> int:
    from sqlalchemy import func, select

    from app.models.db.models import CreditLedger

    total = session.execute(
        select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
            CreditLedger.user_id == user_id,
            CreditLedger.workspace_id.is_(None),
            CreditLedger.reason.like(f"{OVERAGE_REASON_PREFIX}:%"),
            CreditLedger.delta > 0,
            CreditLedger.created_at >= start,
        )
    ).scalar()
    return int(total or 0)


def overage_allowance(
    session: Any, user_id: str, shortfall: int, job_id: str | None, reason: str
) -> bool:
    """True when the shortfall of a reel debit may be granted as overage."""
    if not job_id or shortfall <= 0 or reason not in REEL_DEBIT_REASONS:
        return False
    if not overage_enabled():
        return False
    cap = overage_cap()
    if cap <= 0:
        return False
    row = metered_subscription(session, user_id)
    if row is None:
        return False
    if not overage_consented(session, user_id) or _frozen(session, user_id):
        return False
    bounds = period_bounds(row)
    if bounds is None:
        return False
    used = _overage_used(session, user_id, bounds[0])
    return used + int(shortfall) <= cap


def overage_granted_for_job(session: Any, job_id: str, *, after_ledger_id: int = 0) -> int:
    """Credits granted as overage for ``job_id`` (after ``after_ledger_id``)."""
    from sqlalchemy import func, select

    from app.models.db.models import CreditLedger

    total = session.execute(
        select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
            CreditLedger.job_id == job_id,
            CreditLedger.reason == overage_reason(job_id),
            CreditLedger.delta > 0,
            CreditLedger.id > int(after_ledger_id or 0),
        )
    ).scalar()
    return int(total or 0)


# --------------------------------------------------------------------------- #
# Decision + enqueue
# --------------------------------------------------------------------------- #
def _personal_debit(session: Any, job_id: str, user_id: str) -> bool:
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    row = session.execute(
        select(CreditLedger.id)
        .where(
            CreditLedger.job_id == job_id,
            CreditLedger.user_id == user_id,
            CreditLedger.workspace_id.is_(None),
            CreditLedger.delta < 0,
            CreditLedger.reason.in_(tuple(REEL_DEBIT_REASONS)),
        )
        .limit(1)
    ).first()
    return row is not None


def _events_in_period(session: Any, user_id: str, start: datetime) -> int:
    from sqlalchemy import func, select

    from app.models.db.dodo_usage_event import STATUS_FAILED, DodoUsageEvent

    total = session.execute(
        select(func.count(DodoUsageEvent.id)).where(
            DodoUsageEvent.user_id == user_id,
            DodoUsageEvent.event_name == EVENT_NAME,
            DodoUsageEvent.status != STATUS_FAILED,
            DodoUsageEvent.timestamp >= start,
        )
    ).scalar()
    return int(total or 0)


def decide(session: Any, user_id: str, job_id: str) -> dict[str, Any] | None:
    """``{customer_id, overage, plan_key}`` when this render is metered, else ``None``."""
    row = metered_subscription(session, user_id)
    if row is None:
        return None
    bounds = period_bounds(row)
    if bounds is None or not _personal_debit(session, job_id, user_id):
        return None
    used = _events_in_period(session, user_id, bounds[0])
    if used < included_reels(row):
        overage = False
    elif overage_granted_for_job(session, job_id) > 0:
        overage = True
    else:
        return None
    return {"customer_id": str(row.customer_ref), "overage": overage, "plan_key": row.plan_key}


def record_render(
    job_id: str, *, seconds: float | None = None, now: datetime | None = None, flush: bool = True
) -> bool:
    """Queue ``reel.rendered`` for a successful reel if metered. Never raises."""
    if not job_id:
        return False
    try:
        from sqlalchemy import select

        from app.models.db.base import get_session
        from app.models.db.dodo_usage_event import DodoUsageEvent
        from app.models.db.models import Job

        moment = now or datetime.now(timezone.utc)
        event_id = event_id_for(job_id)
        with get_session() as session:
            job = session.get(Job, job_id)
            if job is None or not job.user_id:
                return False
            exists = session.execute(
                select(DodoUsageEvent.id).where(DodoUsageEvent.event_id == event_id)
            ).first()
            if exists is not None:
                return False
            decision = decide(session, str(job.user_id), job_id)
            if decision is None:
                return False
            meta: dict[str, Any] = {"job_id": job_id, "plan_key": decision["plan_key"]}
            if seconds is not None:
                try:
                    meta["seconds"] = round(float(seconds), 3)
                except (TypeError, ValueError):
                    pass
            if decision["overage"]:
                meta["overage"] = 1
            session.add(
                DodoUsageEvent(
                    event_id=event_id,
                    user_id=str(job.user_id),
                    customer_id=decision["customer_id"],
                    event_name=EVENT_NAME,
                    timestamp=moment,
                    meta=meta,
                    overage=bool(decision["overage"]),
                )
            )
        logger.info(f"dodo usage: queued {event_id} overage={decision['overage']}")
    except Exception as exc:  # noqa: BLE001 - metering never fails a render
        logger.error(f"dodo usage: could not queue render {job_id}: {exc}")
        return False
    _shadow_rago(job_id, decision)
    if flush:
        flush_pending(event_ids=[event_id], now=now)
    return True


def _shadow_rago(job_id: str, decision: dict[str, Any]) -> None:
    """Best-effort shadow of the Dodo event to Railyard Rago (no-op unless set)."""
    try:
        from app.integrations.railyard.metering import UsageEvent, emit
        from app.integrations.railyard.settings import load_settings

        settings = load_settings()
        if not settings.metering_enabled:
            return
        subscription = settings.subscription_for(None)
        if not subscription:
            return
        emit(
            UsageEvent(
                code="dodo_reel_rendered",
                transaction_id=f"{job_id}:dodo",
                external_subscription_id=subscription,
                properties={"job_id": job_id, "overage": int(bool(decision.get("overage")))},
            ),
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001 - shadow metering is optional
        logger.debug(f"dodo usage: rago shadow skipped for {job_id}: {exc}")


# --------------------------------------------------------------------------- #
# Flush
# --------------------------------------------------------------------------- #
def _iso(moment: datetime) -> str:
    return _aware(moment).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _payload(row: Any, now: datetime) -> dict[str, Any]:
    meta = dict(row.meta or {})
    stamp = _aware(row.timestamp)
    if now - stamp > RESTAMP_AFTER:
        meta["rendered_at"] = _iso(stamp)
        stamp = now
    return {
        "event_id": row.event_id,
        "customer_id": row.customer_id,
        "event_name": row.event_name,
        "timestamp": _iso(stamp),
        "metadata": meta,
    }


def _chunks(items: list, size: int) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _classify(exc: Exception) -> tuple[bool, str]:
    """``(retryable, detail)`` for a failed ingest call."""
    status = int(getattr(exc, "status", 0) or 0)
    if status == 0 or status == 429 or status >= 500:
        return True, f"HTTP {status or 'transport'}: {type(exc).__name__}"
    return False, f"HTTP {status}: {str(exc)[:200]}"


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(_BACKOFF_MAX_S, _BACKOFF_BASE_S * (2 ** max(0, attempts - 1))))


def flush_pending(
    *, event_ids: list[str] | None = None, now: datetime | None = None, limit: int = 5000
) -> dict[str, int]:
    """Send due pending events in ≤1,000-event batches. Never raises."""
    counts = {"sent": 0, "retry": 0, "failed": 0}
    try:
        from app.services.billing import dodo_client

        if not dodo_client.is_configured():
            return counts
        from sqlalchemy import or_, select

        from app.models.db.base import get_session
        from app.models.db.dodo_usage_event import (
            STATUS_FAILED,
            STATUS_PENDING,
            STATUS_SENT,
            DodoUsageEvent,
        )

        moment = now or datetime.now(timezone.utc)
        with get_session() as session:
            stmt = select(DodoUsageEvent).where(
                DodoUsageEvent.status == STATUS_PENDING,
                or_(
                    DodoUsageEvent.next_attempt_at.is_(None),
                    DodoUsageEvent.next_attempt_at <= moment,
                ),
            )
            if event_ids:
                stmt = stmt.where(DodoUsageEvent.event_id.in_(list(event_ids)))
            rows = list(
                session.execute(stmt.order_by(DodoUsageEvent.id.asc()).limit(limit)).scalars()
            )
            for batch in _chunks(rows, MAX_BATCH):
                body = {"events": [_payload(row, moment) for row in batch]}
                try:
                    dodo_client.request("POST", "/events/ingest", body=body)
                except Exception as exc:  # noqa: BLE001 - classify below
                    retryable, detail = _classify(exc)
                    for row in batch:
                        row.attempts = int(row.attempts or 0) + 1
                        row.last_error = detail[:300]
                        if retryable and row.attempts < MAX_ATTEMPTS:
                            row.next_attempt_at = moment + _backoff(row.attempts)
                            counts["retry"] += 1
                        else:
                            row.status = STATUS_FAILED
                            counts["failed"] += 1
                    logger.warning(f"dodo usage: batch of {len(batch)} not sent ({detail})")
                    continue
                for row in batch:
                    row.status = STATUS_SENT
                    row.sent_at = moment
                    row.attempts = int(row.attempts or 0) + 1
                    row.last_error = ""
                counts["sent"] += len(batch)
    except Exception as exc:  # noqa: BLE001 - the beat sweep retries
        logger.error(f"dodo usage: flush failed: {exc}")
    return counts


__all__ = [
    "EVENT_NAME",
    "MAX_BATCH",
    "OVERAGE_CONSENT_KIND",
    "consent_version",
    "REEL_DEBIT_REASONS",
    "decide",
    "event_id_for",
    "flush_pending",
    "included_reels",
    "metered_subscription",
    "overage_allowance",
    "overage_cap",
    "overage_consented",
    "overage_enabled",
    "overage_granted_for_job",
    "overage_price_usd",
    "overage_reason",
    "overage_terms",
    "period_bounds",
    "record_render",
]
