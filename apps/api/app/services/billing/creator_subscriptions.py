"""Personal monthly plans: lifecycle, idempotent period grants, no-rollover expiry.

The choke point between Creem recurring products (:mod:`creator_creem`) and the
subscriber's PERSONAL credit balance + :class:`CreatorSubscription` row.

Money-correctness invariants:

* **One grant per paid period.** Included reels are granted through
  :func:`service.fulfill_purchase` keyed on ``msub:<creem sub id>:<period end>``
  (Redis SETNX + durable ledger reason), so the signed redirect, every webhook
  of a period (``subscription.active`` / ``.paid`` / ``.update``) and every
  redelivery collapse to exactly one grant.
* **No rollover, honestly.** Included reels are used first. When the next
  period is granted (or the plan has ended), whatever is left of the previous
  period's included reels is expired once (ledger reason ``plan_expire:...``),
  never more than the current balance, never touching pack credits.
* **Terminal cancel.** A canceled subscription never comes back from a late
  "active" event for the same Creem id.
* **Provider first.** Cancel and plan changes hit Creem before the local row.

Mobile (RevenueCat) and workspace plans are untouched: this module only reads
and writes ``creator_subscriptions`` and the personal ledger.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.services.billing import creator_plans as cp
from app.services.billing import lifecycle_mail

CREEM: str = "creem"
LIVE_STATUSES: frozenset[str] = frozenset({"active", "trialing"})
_REASON_PREFIX: str = "msub"
_EXPIRE_PREFIX: str = "plan_expire"
_SIGNUP_REASONS: tuple[str, ...] = ("signup", "mobile_device_signup", "mobile_identity_signup")

_LIVE_EVENTS = frozenset({"subscription.active", "subscription.paid", "subscription.update"})
_CHECKOUT_EVENTS = frozenset({"checkout.completed", "checkout.paid"})
_STATUS_MAP = {
    "active": "active",
    "paid": "active",
    "scheduled_cancel": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "unpaid": "past_due",
    "paused": "past_due",
    "canceled": "canceled",
    "cancelled": "canceled",
    "expired": "canceled",
}


class AlreadySubscribed(RuntimeError):
    """The user already has a live monthly plan (change it instead)."""


class NoSubscription(RuntimeError):
    """The user has no live monthly plan to change, cancel or manage."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _sp():
    from app.services.billing import subscription_providers

    return subscription_providers


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return _sp()._get(obj, key, default)


def _ref(value: Any) -> str:
    """An id from either an expanded object or a bare id string."""
    if isinstance(value, dict):
        return str(value.get("id", "") or "").strip()
    return str(value or "").strip()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(session: Any, user_id: str):
    from sqlalchemy import select

    from app.models.db.creator_subscription import CreatorSubscription

    stmt = select(CreatorSubscription).where(CreatorSubscription.user_id == user_id)
    return session.execute(stmt).scalars().first()


def _row_by_ref(session: Any, ref: str):
    from sqlalchemy import select

    from app.models.db.creator_subscription import CreatorSubscription

    stmt = select(CreatorSubscription).where(CreatorSubscription.provider_ref == ref)
    return session.execute(stmt).scalars().first()


def _grant_reason(ref: str, provider: str = CREEM) -> str:
    from app.services.billing import service

    return service._fit_reason(f"purchase:{provider}:{ref}", provider, ref)


def is_live(row: Any) -> bool:
    return row is not None and str(row.status or "").lower() in LIVE_STATUSES


# --------------------------------------------------------------------------- #
# Event normalization
# --------------------------------------------------------------------------- #
def _subscription_view(obj: Any, *, event_type: str) -> dict[str, Any]:
    """Normalize a Creem subscription object (webhook or GET) into our shape."""
    raw_status = str(_get(obj, "status", "") or "").strip().lower()
    if event_type == "subscription.expired":
        status = "canceled"
    elif event_type == "subscription.canceled":
        status = "canceled"
    elif event_type in {"subscription.past_due", "subscription.unpaid", "subscription.paused"}:
        status = "past_due"
    else:
        status = _STATUS_MAP.get(raw_status, "active")
    period_end = _sp()._to_datetime(
        _get(obj, "current_period_end_date") or _get(obj, "current_period_end")
    )
    return {
        "provider_ref": _ref(_get(obj, "id")),
        "customer_ref": _ref(_get(obj, "customer")),
        "product_ref": _ref(_get(obj, "product")),
        "metadata": _get(obj, "metadata") or {},
        "status": status,
        "cancel_at_period_end": raw_status == "scheduled_cancel"
        or event_type == "subscription.scheduled_cancel",
        "period_end": period_end,
        "expire_now": event_type == "subscription.expired",
    }


def parse_creem_event(event: Any) -> dict[str, Any] | None:
    """A verified Creem event as a personal-plan update, or ``None`` if not ours."""
    event_type = str(
        _get(event, "eventType", "") or _get(event, "event_type", "") or _get(event, "type", "")
    ).strip()
    obj = _get(event, "object") or _sp()._path(event, "data", "object") or _get(event, "data") or {}
    if event_type in _CHECKOUT_EVENTS:
        sub = _get(obj, "subscription")
        view = _subscription_view(sub if isinstance(sub, dict) else {"id": sub}, event_type=event_type)
        view["customer_ref"] = view["customer_ref"] or _ref(_get(obj, "customer"))
        view["product_ref"] = view["product_ref"] or _ref(_get(obj, "product"))
        view["metadata"] = _get(obj, "metadata") or view["metadata"]
        view["status"] = "active"
    elif event_type.startswith("subscription."):
        view = _subscription_view(obj, event_type=event_type)
    else:
        return None
    mapped = cp.plan_for_product(view["product_ref"], "creem")
    metadata = view["metadata"]
    if mapped is None and str(_get(metadata, "kind", "") or "") != cp.KIND:
        return None
    plan = mapped[0] if mapped else cp.get_plan(str(_get(metadata, "plan_key", "") or ""))
    interval = mapped[1] if mapped else str(_get(metadata, "interval", "") or "")
    view.update(
        event_type=event_type,
        user_id=str(_get(metadata, "user_id", "") or "").strip(),
        plan_key=plan.key if plan else "",
        interval=interval if interval in cp.INTERVALS else "",
        grant_allowed=event_type in _LIVE_EVENTS or event_type in _CHECKOUT_EVENTS,
    )
    return view


# --------------------------------------------------------------------------- #
# Apply (idempotent)
# --------------------------------------------------------------------------- #
def apply_update(update: dict[str, Any]) -> dict[str, Any] | None:
    """Persist a normalized update, grant the period once, expire leftovers."""
    from app.models.db.base import get_session
    from app.models.db.creator_subscription import CreatorSubscription

    ref = update.get("provider_ref", "")
    with get_session() as session:
        user_id = update.get("user_id", "")
        row = _row(session, user_id) if user_id else None
        if row is None and ref:
            row = _row_by_ref(session, ref)
            user_id = user_id or (row.user_id if row is not None else "")
        if not user_id:
            logger.warning(f"creator plans: event for {ref!r} has no resolvable user; ignoring")
            return None
        if row is not None and row.provider_ref and ref:
            same = row.provider_ref == ref
            if same and row.status == "canceled" and update["status"] != "canceled":
                return {"user_id": user_id, "status": "canceled", "ignored": True}
            if not same and is_live(row) and update["status"] not in LIVE_STATUSES:
                return {"user_id": user_id, "status": row.status, "ignored": True}
        if row is None:
            if not update.get("plan_key"):
                return None
            row = CreatorSubscription(user_id=user_id, plan_key=update["plan_key"])
            session.add(row)
        if update.get("plan_key"):
            row.plan_key = update["plan_key"]
        if update.get("interval"):
            row.interval = update["interval"]
        provider = str(update.get("provider") or CREEM)
        row.provider = provider
        if ref:
            row.provider_ref = ref
        if update.get("customer_ref"):
            row.customer_ref = update["customer_ref"]
        row.status = update["status"]
        row.cancel_at_period_end = bool(update.get("cancel_at_period_end")) or (
            update["status"] == "canceled"
        )
        if update.get("period_end") is not None:
            row.current_period_end = update["period_end"]
        session.flush()
        plan = cp.get_plan(row.plan_key)
        interval = row.interval or cp.MONTH
        ref = row.provider_ref

    granted = 0
    period_end = update.get("period_end")
    if (
        update.get("grant_allowed")
        and update["status"] == "active"
        and plan is not None
        and ref
        and period_end is not None
    ):
        granted = _grant_period(
            user_id, plan.period_credits(interval), ref, period_end, provider=provider
        )
    if update.get("expire_now"):
        expire_leftover(user_id)
    lifecycle_mail.on_plan_status(user_id, update["status"], ref, period_end)  # MG5: never raises
    return {"user_id": user_id, "status": update["status"], "granted": granted}


def _grant_period(
    user_id: str, credits: int, ref: str, period_end: datetime, *, provider: str = CREEM
) -> int:
    """Grant a period's included reels once (after expiring the previous period's)."""
    from sqlalchemy import select

    from app.models.db.base import get_session
    from app.models.db.models import CreditLedger
    from app.services.billing import service

    period_key = str(int(_aware(period_end).timestamp()))
    with get_session() as session:
        row = _row(session, user_id)
        if row is None or row.period_key == period_key or credits <= 0:
            return 0
    expire_leftover(user_id)
    reason_ref = f"{_REASON_PREFIX}:{ref}:{period_key}"
    service.fulfill_purchase(
        provider=provider,
        external_event_id=reason_ref,
        user_id=user_id,
        credits=int(credits),
        reason_ref=reason_ref,
    )
    with get_session() as session:
        ledger_id = session.execute(
            select(CreditLedger.id)
            .where(CreditLedger.user_id == user_id, CreditLedger.reason == _grant_reason(reason_ref, provider))
            .order_by(CreditLedger.id.asc())
            .limit(1)
        ).scalar()
        row = _row(session, user_id)
        if row is not None and row.period_key != period_key:
            row.period_key = period_key
            row.period_credits = int(credits)
            row.period_grant_ledger_id = int(ledger_id) if ledger_id is not None else None
    logger.info(f"creator plans: granted {credits} reels user={user_id} period={period_key}")
    return int(credits)


def _included_left(session: Any, user_id: str, row: Any) -> int:
    """Unused included reels of the row's current period (never above balance)."""
    from sqlalchemy import select

    from app.models.db.models import CreditLedger
    from app.models.db.repositories import CreditRepository

    grant_id = getattr(row, "period_grant_ledger_id", None)
    granted = int(getattr(row, "period_credits", 0) or 0)
    if grant_id is None or granted <= 0:
        return 0
    rows = session.execute(
        select(CreditLedger.delta, CreditLedger.reason).where(
            CreditLedger.user_id == user_id,
            CreditLedger.workspace_id.is_(None),
            CreditLedger.id > grant_id,
        )
    ).all()
    expire_tag = f"{_EXPIRE_PREFIX}:"
    net_use = sum(
        int(delta)
        for delta, reason in rows
        if (int(delta) < 0 and not str(reason).startswith(expire_tag))
        or "refund" in str(reason)
    )
    if any(str(reason).startswith(expire_tag) for _, reason in rows):
        return 0
    consumed = max(0, -net_use)
    balance = CreditRepository(session).balance(user_id)
    return max(0, min(balance, granted - consumed))


def expire_leftover(user_id: str) -> int:
    """Expire the current period's unused included reels once. Returns the count."""
    from app.models.db.base import get_session
    from app.models.db.repositories import CreditRepository
    from app.services.billing import service

    with get_session() as session:
        row = _row(session, user_id)
        if row is None or row.period_grant_ledger_id is None or not row.period_key:
            return 0
        reason = f"{_EXPIRE_PREFIX}:{row.provider_ref or row.id}:{row.period_key}"[:80]
        service._lock_user_row(session, user_id)
        if service._ledger_has_reason(session, user_id, reason):
            return 0
        leftover = _included_left(session, user_id, row)
        if leftover <= 0:
            return 0
        CreditRepository(session).debit(user_id, leftover, None, reason)
    logger.info(f"creator plans: expired {leftover} unused included reels user={user_id}")
    return leftover


__all__ = [
    "AlreadySubscribed",
    "LIVE_STATUSES",
    "NoSubscription",
    "apply_update",
    "expire_leftover",
    "is_live",
    "parse_creem_event",
]
