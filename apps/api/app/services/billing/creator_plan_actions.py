"""User-facing actions for personal monthly plans.

Subscribe, change plan, cancel renewal (one click), open the Creem customer
portal, confirm the signed checkout redirect, and the status/upsell view the
web shows on /create, /billing and /pricing. State changes go through
:mod:`creator_subscriptions` (idempotent grants + no-rollover expiry); provider
calls through :mod:`creator_creem`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.services.billing import creator_creem as creem
from app.services.billing import creator_plans as cp
from app.services.billing import payments_mode
from app.services.billing import creator_subscriptions as subs

#: Upsell when a user's balance is at or below this many reels.
LOW_CREDITS_THRESHOLD: int = 1
#: Grace before we ask Creem whether a period that should have renewed did.
_RENEWAL_GRACE = timedelta(minutes=10)
_USAGE_WINDOW = timedelta(days=30)


class PaymentsPaused(RuntimeError):
    """New plan checkouts are paused (MENIVOR_PAYMENTS_PROVIDER=none)."""


def _transport(provider: str | None):
    """Provider transport module (``creator_creem`` or ``creator_dodo``)."""
    if (provider or "").strip().lower() == payments_mode.DODO:
        from app.services.billing import creator_dodo

        return creator_dodo
    return creem


def _fetch_view(provider: str | None, subscription_id: str) -> dict[str, Any]:
    transport = _transport(provider)
    if transport is creem:
        return subs._subscription_view(creem.fetch_subscription(subscription_id), event_type="")
    return transport.fetch_subscription_view(subscription_id)


def _session():
    from app.models.db.base import get_session

    return get_session()


def _row_snapshot(user_id: str) -> dict[str, Any] | None:
    with _session() as session:
        row = subs._row(session, user_id)
        if row is None:
            return None
        return {
            "plan_key": row.plan_key,
            "provider": row.provider or payments_mode.CREEM,
            "interval": row.interval or cp.MONTH,
            "status": row.status,
            "provider_ref": row.provider_ref,
            "customer_ref": row.customer_ref,
            "cancel_at_period_end": bool(row.cancel_at_period_end),
            "current_period_end": subs._aware(row.current_period_end),
            "period_key": row.period_key,
        }


# --------------------------------------------------------------------------- #
# Subscribe / change / cancel / portal
# --------------------------------------------------------------------------- #
def start_checkout(*, user_id: str, user_email: str, plan_key: str, interval: str) -> dict:
    plan = cp.get_plan(plan_key)
    if plan is None:
        raise ValueError(f"unknown plan {plan_key!r}; choose creator, pro or agency")
    normalized = cp.normalize_interval(interval)
    snapshot = _row_snapshot(user_id)
    if snapshot and snapshot["status"] in subs.LIVE_STATUSES and snapshot["provider_ref"]:
        raise subs.AlreadySubscribed("You already have a monthly plan. Change it instead.")
    provider = payments_mode.active_provider()
    if provider not in (payments_mode.CREEM, payments_mode.DODO):
        raise PaymentsPaused("Paid plans are paused while we move to a new payment partner.")
    result = _transport(provider).open_checkout(
        user_id=user_id, user_email=user_email, plan=plan, interval=normalized
    )
    return {
        "checkout_url": result["checkout_url"],
        "checkout_id": result["session_id"],
        "plan_key": plan.key,
        "interval": normalized,
    }


def _require_live(user_id: str) -> dict[str, Any]:
    snapshot = _row_snapshot(user_id)
    if not snapshot or snapshot["status"] not in subs.LIVE_STATUSES or not snapshot["provider_ref"]:
        raise subs.NoSubscription("You do not have an active monthly plan.")
    return snapshot


def cancel(user_id: str) -> dict:
    """Turn renewal off at Creem first, then locally. Included reels stay until period end."""
    snapshot = _require_live(user_id)
    mode = _transport(snapshot["provider"]).cancel(snapshot["provider_ref"])
    with _session() as session:
        row = subs._row(session, user_id)
        if row is not None:
            row.cancel_at_period_end = True
            if mode == "immediate":
                row.status = "canceled"
    logger.info(f"creator plans: renewal off user={user_id} mode={mode}")
    return status(user_id, refresh=False)


def change_plan(user_id: str, plan_key: str) -> dict:
    """Switch a live plan. Upgrades are charged pro rata now and add the reel difference."""
    target = cp.get_plan(plan_key)
    if target is None:
        raise ValueError(f"unknown plan {plan_key!r}")
    snapshot = _require_live(user_id)
    if snapshot["plan_key"] == target.key:
        return status(user_id, refresh=False)
    interval = snapshot["interval"]
    product = cp.product_id(target.key, interval, snapshot["provider"])
    if not product:
        raise RuntimeError(f"{target.display_name} ({interval}ly) is not on sale yet.")
    current = cp.get_plan(snapshot["plan_key"])
    upgrade = current is None or target.rank > current.rank
    _transport(snapshot["provider"]).change_product(snapshot["provider_ref"], product, upgrade=upgrade)
    delta = target.period_credits(interval) - (current.period_credits(interval) if current else 0)
    with _session() as session:
        row = subs._row(session, user_id)
        if row is not None:
            row.plan_key = target.key
            row.cancel_at_period_end = False
    if upgrade and delta > 0 and snapshot["period_key"]:
        _grant_upgrade(user_id, snapshot, target.key, delta)
    return status(user_id, refresh=False)


def _grant_upgrade(user_id: str, snapshot: dict, plan_key: str, delta: int) -> None:
    from app.services.billing import service

    ref = f"{subs._REASON_PREFIX}:{snapshot['provider_ref']}:{snapshot['period_key']}:up:{plan_key}"
    try:
        service.fulfill_purchase(
            provider=snapshot.get("provider") or subs.CREEM, external_event_id=ref, user_id=user_id, credits=delta, reason_ref=ref
        )
    except Exception as exc:  # noqa: BLE001 - the plan change itself stands
        logger.error(f"creator plans: upgrade top-up failed user={user_id}: {exc}")
        return
    with _session() as session:
        row = subs._row(session, user_id)
        if row is not None and row.period_key == snapshot["period_key"]:
            row.period_credits = int(row.period_credits or 0) + int(delta)


def portal(user_id: str) -> str:
    snapshot = _row_snapshot(user_id)
    if not snapshot or not snapshot["customer_ref"]:
        raise subs.NoSubscription("There is no billing account on file yet.")
    return _transport(snapshot["provider"]).portal_link(snapshot["customer_ref"])


# --------------------------------------------------------------------------- #
# Signed redirect + self-healing renewals
# --------------------------------------------------------------------------- #
def confirm_redirect(purchase: dict[str, Any], plan: cp.CreatorPlan, interval: str) -> dict:
    """Activate a plan from Creem's SIGNED success redirect (webhook-independent)."""
    from app.services.billing.creator_subscriptions import apply_update

    sub_id = str(purchase.get("subscription_id", "") or "").strip()
    update: dict[str, Any] = {
        "user_id": purchase["user_id"],
        "provider_ref": sub_id,
        "customer_ref": str(purchase.get("customer_id", "") or ""),
        "plan_key": plan.key,
        "interval": interval,
        "status": "active",
        "cancel_at_period_end": False,
        "period_end": None,
        "grant_allowed": True,
        "expire_now": False,
        "provider": purchase.get("provider") or payments_mode.CREEM,
    }
    if sub_id:
        try:
            live = _fetch_view(purchase.get("provider"), sub_id)
            update.update(
                status=live["status"],
                cancel_at_period_end=live["cancel_at_period_end"],
                period_end=live["period_end"],
                customer_ref=update["customer_ref"] or live["customer_ref"],
            )
        except Exception as exc:  # noqa: BLE001 - the webhook grants instead
            logger.warning(f"creator plans: could not read subscription {sub_id}: {exc}")
    result = apply_update(update) or {}
    from app.services.billing.service import _current_balance

    return {
        "plan_key": plan.key,
        "credits": int(result.get("granted", 0) or 0),
        "balance": int(_current_balance(purchase["user_id"])),
        "checkout_id": purchase["checkout_id"],
        "workspace_id": None,
        "unlocked": True,
        "subscription": {"plan_key": plan.key, "interval": interval},
    }


def _refresh(user_id: str, snapshot: dict[str, Any]) -> None:
    """Ask Creem about a period that should have renewed (missed webhook), then settle."""
    end = snapshot.get("current_period_end")
    if end is None or end + _RENEWAL_GRACE > datetime.now(timezone.utc):
        return
    if snapshot["status"] in subs.LIVE_STATUSES and snapshot["provider_ref"]:
        try:
            live = _fetch_view(snapshot.get("provider"), snapshot["provider_ref"])
            live.update(
                user_id=user_id,
                plan_key="",
                interval="",
                grant_allowed=True,
                provider=snapshot.get("provider") or payments_mode.CREEM,
            )
            subs.apply_update(live)
        except Exception as exc:  # noqa: BLE001 - status must still render
            logger.warning(f"creator plans: renewal refresh failed user={user_id}: {exc}")
            return
        snapshot = _row_snapshot(user_id) or snapshot
    if snapshot["status"] == "canceled":
        subs.expire_leftover(user_id)


# --------------------------------------------------------------------------- #
# Status + upsell
# --------------------------------------------------------------------------- #
def _reels_used_last_30_days(session: Any, user_id: str) -> int:
    from sqlalchemy import func, select

    from app.models.db.models import CreditLedger

    since = datetime.now(timezone.utc) - _USAGE_WINDOW
    total = session.execute(
        select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
            CreditLedger.user_id == user_id,
            CreditLedger.workspace_id.is_(None),
            CreditLedger.delta < 0,
            CreditLedger.created_at >= since,
            ~CreditLedger.reason.like(f"{subs._EXPIRE_PREFIX}:%"),
        )
    ).scalar()
    return max(0, -int(total or 0))


def _reels_rendered(session: Any, user_id: str) -> int:
    """Lifetime count of this user's finished renders (real completed jobs only)."""
    from sqlalchemy import func, select

    from app.models import const
    from app.models.db.models import Job

    total = session.execute(
        select(func.count(Job.id)).where(
            Job.user_id == user_id,
            Job.state == const.TASK_STATE_COMPLETE,
        )
    ).scalar()
    return int(total or 0)


def recommend(current_key: str | None, used_30d: int) -> str | None:
    """Smallest plan that covers recent usage; the next tier up for subscribers."""
    plans = cp.list_plans()
    current = cp.get_plan(current_key)
    if current is not None:
        higher = [p for p in plans if p.rank > current.rank]
        return higher[0].key if higher else None
    fitting = [p for p in plans if p.monthly_reels >= used_30d]
    return (fitting[0] if fitting else plans[-1]).key


def status(user_id: str, *, refresh: bool = True) -> dict[str, Any]:
    """The web view: current plan, renewal date, included reels left, upsell hint."""
    from app.models.db.repositories import CreditRepository

    snapshot = _row_snapshot(user_id)
    if refresh and snapshot:
        _refresh(user_id, snapshot)
        snapshot = _row_snapshot(user_id)
    with _session() as session:
        credits = int(CreditRepository(session).balance(user_id))
        used = _reels_used_last_30_days(session, user_id)
        rendered = _reels_rendered(session, user_id)
        row = subs._row(session, user_id)
        included_left = subs._included_left(session, user_id, row) if subs.is_live(row) else 0
    live = bool(snapshot and snapshot["status"] in subs.LIVE_STATUSES)
    plan = cp.get_plan(snapshot["plan_key"]) if live and snapshot else None
    end = snapshot["current_period_end"] if snapshot else None
    renews = bool(live and snapshot and not snapshot["cancel_at_period_end"])
    return {
        "plan": (
            {
                "plan_key": plan.key,
                "name": plan.display_name,
                "interval": snapshot["interval"],
                "price_cents": int(round(plan.price_usd(snapshot["interval"]) * 100)),
                "period_reels": plan.period_credits(snapshot["interval"]),
            }
            if plan and snapshot
            else None
        ),
        "status": snapshot["status"] if snapshot else "none",
        "renews": renews,
        "cancel_at_period_end": bool(snapshot and snapshot["cancel_at_period_end"]),
        "current_period_end": end.isoformat() if end else None,
        "included_left": int(included_left),
        "credits": credits,
        "reels_used_30d": used,
        "reels_rendered": rendered,
        "can_manage": bool(snapshot and snapshot["customer_ref"]),
        "low_credits": credits <= LOW_CREDITS_THRESHOLD,
        "recommended_plan": recommend(plan.key if plan else None, used),
    }


__all__ = [
    "LOW_CREDITS_THRESHOLD",
    "cancel",
    "change_plan",
    "confirm_redirect",
    "portal",
    "recommend",
    "start_checkout",
    "status",
]
