"""Workspace subscription lifecycle + IDEMPOTENT subscription webhooks.

The choke point between the payment rails (Stripe, Creem, Polar — see
:mod:`app.services.billing.subscription_providers`) and the workspace's
:class:`~app.models.db.models.Subscription` row + shared credit pool.

Money-correctness invariants:

* **Provider first.** Cancel and plan changes mutate the LIVE provider
  subscription before the local row, so entitlements never differ from what the
  card is billed for (a provider error leaves the row untouched).
* **Recurring ids only.** Checkout uses the workspace plan's recurring
  Price/Product for the chosen interval (:mod:`app.services.billing.workspace_plans`),
  never the one-time pack id.
* **Idempotent fulfilment per billing PERIOD.** The credit grant is keyed on
  ``(workspace, provider subscription id, period end)`` — Redis ``SETNX`` *and*
  the durable ledger reason — so all of a period's overlapping events and every
  redelivery collapse to exactly one grant.
* **Tenant-scoped.** The workspace comes from provider metadata (or the provider
  id recorded at activation); grants go to that workspace's pool only.
* **Lapsed = base plan.** A canceled / past_due row falls back to the free
  entitlements; a canceled provider subscription is terminal (late "active"
  events for it are ignored).

RBAC: :func:`create_subscription` / :func:`change_plan` / :func:`cancel_subscription`
are gated by ``billing.manage`` at the API layer (Epic 1 RBAC).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.services import entitlements

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
STRIPE: str = "stripe"

#: The reason-ref namespace so a subscription grant's durable ledger reason
#: (``purchase:stripe:sub:<workspace>:<provider_ref>:<period>``) can never collide
#: with a one-time credit-pack purchase (``purchase:stripe:<session_id>``).
_REASON_PREFIX: str = "sub"


# --------------------------------------------------------------------------- #
# Command API (RBAC billing.manage gated at the API layer)
# --------------------------------------------------------------------------- #
class ProviderUnavailableError(RuntimeError):
    """The requested rail cannot sell this plan/interval (not configured)."""


def create_subscription(
    *,
    workspace_id: str,
    user_id: str,
    plan_key: str,
    user_email: str = "",
    provider: str = STRIPE,
    interval: str = "month",
    seats: int = 1,
) -> dict[str, Any]:
    """Open a RECURRING provider checkout for a workspace plan.

    Uses the workspace plan's own recurring Price/Product id for the chosen
    ``interval`` (never the one-time pack id), threads ``kind=subscription`` +
    workspace/plan/interval/seats/period-credits into provider metadata, and
    returns ``{provider, plan_key, interval, seats, credits, checkout_url,
    reference, workspace_id}``. Nothing is granted here — the verified webhook
    activates the row and grants the period's credits idempotently.

    Raises ``ValueError`` for a blank workspace, a non-self-serve plan (free /
    enterprise), a bad interval or a seat count above the plan limit, and
    :class:`ProviderUnavailableError` when the rail is not configured for it.
    """
    if not (workspace_id or "").strip():
        raise ValueError("create_subscription requires a non-empty workspace_id")

    from app.services.billing import subscription_providers
    from app.services.billing import workspace_plans as wp

    plan = wp.get_workspace_plan(plan_key)
    if plan is None:
        raise ValueError(
            f"plan {plan_key!r} is not self-serve (Enterprise is arranged with sales)"
        )
    normalized_interval = wp.normalize_interval(interval)
    seat_count = int(seats or 1)
    if seat_count < 1 or seat_count > plan.max_seats:
        raise ValueError(
            f"{plan.display_name} includes up to {plan.max_seats} seat(s); "
            f"requested {seat_count}"
        )
    normalized_provider = (provider or "").strip().lower()
    if normalized_provider not in wp.SUBSCRIPTION_PROVIDERS:
        raise ValueError(
            f"subscriptions are available via {', '.join(wp.SUBSCRIPTION_PROVIDERS)}"
        )
    if normalized_provider not in wp.available_providers(plan.key, normalized_interval):
        raise ProviderUnavailableError(
            f"{normalized_provider} is not set up to sell {plan.display_name} "
            f"({normalized_interval}ly) yet"
        )

    result = subscription_providers.open_checkout(
        normalized_provider,
        user_id=str(user_id or "").strip(),
        user_email=user_email or "",
        workspace_id=workspace_id.strip(),
        plan=plan,
        interval=normalized_interval,
        seats=seat_count,
    )
    logger.info(
        f"subscriptions: opened {normalized_provider} checkout workspace={workspace_id} "
        f"plan={plan.key} interval={normalized_interval} seats={seat_count}"
    )
    return {
        "provider": normalized_provider,
        "plan_key": plan.key,
        "interval": normalized_interval,
        "seats": seat_count,
        "credits": plan.period_credits(normalized_interval),
        "checkout_url": result["checkout_url"],
        "reference": result["session_id"],
        "workspace_id": workspace_id.strip(),
    }


def _is_live(row: Any) -> bool:
    from app.models.db.repositories import SUBSCRIPTION_LIVE_STATUSES

    status = str(getattr(row, "status", "") or "").strip().lower()
    return row is not None and status in SUBSCRIPTION_LIVE_STATUSES


def change_plan(
    session: Any,
    *,
    workspace_id: str,
    plan_key: str,
    actor_user_id: str | None = None,
) -> Any:
    """Switch a workspace's LIVE subscription to another plan + audit it.

    * ``free``: cancels the provider subscription (no further charges) and drops
      the workspace to the base plan.
    * another self-serve paid plan: moves the PROVIDER subscription to the new
      recurring price first (prorated and charged now), and only then updates
      the local row, so entitlements always match what is billed. An upgrade
      tops the pool up by the credit difference for the current period (once
      per period + plan, idempotently).
    * ``enterprise`` / unknown: ``ValueError`` (sales-led / invalid).

    A paid switch without a live provider-backed subscription raises
    :class:`PermissionError` (surfaced as ``402``) — paid tiers are earned by
    checkout, never by a direct DB write. Provider failures propagate as
    ``RuntimeError`` and leave the local row untouched.
    """
    normalized_plan = (plan_key or "").strip().lower()
    if normalized_plan not in entitlements.PLAN_ENTITLEMENTS:
        raise ValueError(f"unknown plan {plan_key!r}")

    from app.models.db.repositories import SubscriptionRepository
    from app.services.billing import subscription_providers
    from app.services.billing import workspace_plans as wp

    repo = SubscriptionRepository(session)
    existing = repo.get_for_workspace(workspace_id)
    provider_ref = str(getattr(existing, "provider_ref", "") or "").strip()

    if normalized_plan == entitlements.FREE_PLAN:
        if existing is not None and provider_ref and _is_live(existing):
            # Stepping down to Free ends the paid subscription AT THE PROVIDER
            # (no further charges). The row stays ``canceled`` so a late provider
            # event for that subscription can never revive the paid tier.
            cancel_subscription(
                session, workspace_id=workspace_id, actor_user_id=actor_user_id
            )
            return repo.upsert(workspace_id, plan_key=normalized_plan, status="canceled")
        row = repo.upsert(workspace_id, plan_key=normalized_plan, status="active")
        _audit(
            session,
            actor_user_id=actor_user_id,
            action="subscription.plan_changed",
            workspace_id=workspace_id,
            metadata={"plan_key": normalized_plan},
        )
        return row

    if not (existing is not None and provider_ref and _is_live(existing)):
        raise PermissionError(
            f"cannot switch workspace to paid plan {normalized_plan!r} without a "
            "verified active subscription; subscribe first"
        )
    target = wp.get_workspace_plan(normalized_plan)
    if target is None:
        raise ValueError(
            f"plan {normalized_plan!r} is not self-serve; contact sales to switch"
        )
    if str(existing.plan_key or "").lower() == normalized_plan:
        return existing

    provider = str(existing.provider or STRIPE).strip().lower()
    interval = str(existing.interval or "month").strip().lower()
    current = wp.get_workspace_plan(existing.plan_key)
    subscription_providers.change_plan(
        provider,
        provider_ref,
        plan=target,
        interval=interval,
        metadata={
            "kind": subscription_providers.KIND_SUBSCRIPTION,
            "user_id": str(actor_user_id or ""),
            "workspace_id": workspace_id,
            "plan_key": target.key,
            "interval": interval,
            "seats": str(int(existing.seats or 1)),
            "credits": str(target.period_credits(interval)),
        },
    )

    row = repo.upsert(workspace_id, plan_key=target.key, status="active")
    _audit(
        session,
        actor_user_id=actor_user_id,
        action="subscription.plan_changed",
        workspace_id=workspace_id,
        metadata={"plan_key": target.key, "from": getattr(current, "key", "")},
    )

    delta = target.period_credits(interval) - (
        current.period_credits(interval) if current else 0
    )
    period = getattr(existing, "current_period_end", None)
    if delta > 0 and period is not None:
        from datetime import timezone

        from app.services.billing import service as billing_service

        if getattr(period, "tzinfo", None) is None:
            period = period.replace(tzinfo=timezone.utc)  # stored as UTC

        period_ref = (
            f"{_REASON_PREFIX}:{workspace_id}:{provider_ref}:"
            f"{int(period.timestamp())}:up:{target.key}"
        )
        try:
            billing_service.fulfill_purchase(
                provider=provider,
                external_event_id=period_ref,
                user_id=str(actor_user_id or ""),
                credits=int(delta),
                reason_ref=period_ref,
                workspace_id=workspace_id,
            )
        except Exception as exc:  # noqa: BLE001 - the plan switch itself stands
            logger.error(
                f"subscriptions: upgrade top-up failed workspace={workspace_id}: {exc}"
            )
    return row


def cancel_subscription(
    session: Any,
    *,
    workspace_id: str,
    actor_user_id: str | None = None,
) -> Any:
    """Cancel the workspace subscription AT THE PROVIDER, then locally.

    The provider subscription is canceled first (immediately, so no renewal is
    ever charged again); only after that succeeds is the row flipped to
    ``canceled`` so entitlements fall back to the base plan. Credits already
    granted to the pool stay usable. A provider failure propagates as
    ``RuntimeError`` and leaves the row live (never "canceled" locally while the
    card keeps being billed). Returns the row, or ``None`` when there is none.
    """
    from app.models.db.repositories import SubscriptionRepository
    from app.services.billing import subscription_providers

    repo = SubscriptionRepository(session)
    row = repo.get_for_workspace(workspace_id)
    if row is None:
        return None
    if str(row.status or "").lower() == "canceled":
        return row

    provider_ref = str(row.provider_ref or "").strip()
    if provider_ref:
        subscription_providers.cancel(
            str(row.provider or STRIPE).strip().lower(), provider_ref
        )

    row = repo.set_status(workspace_id, "canceled")
    if row is not None:
        _audit(
            session,
            actor_user_id=actor_user_id,
            action="subscription.canceled",
            workspace_id=workspace_id,
            metadata={"plan_key": row.plan_key},
        )
    return row


def get_subscription(session: Any, workspace_id: str) -> Any:
    """Return the workspace's subscription row (tenant-scoped), or ``None``."""
    from app.models.db.repositories import SubscriptionRepository

    return SubscriptionRepository(session).get_for_workspace(workspace_id)


# --------------------------------------------------------------------------- #
# Webhook (IDEMPOTENT)
# --------------------------------------------------------------------------- #
def handle_subscription_webhook(
    payload: bytes, signature: str
) -> dict[str, Any] | None:
    """Verify a STRIPE subscription webhook and apply it IDEMPOTENTLY.

    Verification is delegated to
    :func:`app.services.billing.stripe_client.verify_and_parse_webhook`; a
    failure propagates so the API layer responds 400. See
    :func:`process_provider_event` for the idempotency guarantees.
    """
    from app.services.billing import stripe_client

    event = stripe_client.verify_and_parse_webhook(payload, signature)
    return process_subscription_event(event)


def process_subscription_event(event: Any) -> dict[str, Any] | None:
    """Apply an already-verified STRIPE subscription event idempotently."""
    return process_provider_event(STRIPE, event)


def process_provider_event(provider: str, event: Any) -> dict[str, Any] | None:
    """Apply a verified Stripe/Creem/Polar subscription event idempotently.

    1. Normalize the event (``None`` when it is not a workspace subscription).
    2. Resolve the workspace from metadata, else from the provider id recorded
       at activation.
    3. Drop stale events: a row canceled for this same provider id is terminal
       (an out-of-order "active" can never revive it), and a non-live event for
       a provider id the workspace has since replaced is ignored.
    4. Upsert the row (naturally idempotent) and, for a live period with a
       positive allotment, grant the period credits EXACTLY ONCE keyed on
       ``(workspace, provider id, period end)`` — Redis SETNX plus the durable
       ledger reason — so every overlapping event and redelivery collapses to a
       single grant and a new grant happens only when the period advances.
    """
    from app.services.billing import subscription_providers

    parsed = subscription_providers.parse_event(provider, event)
    if not parsed:
        return None

    from app.models.db.base import get_session
    from app.models.db.repositories import SubscriptionRepository
    from app.services.billing import workspace_plans as wp

    with get_session() as session:
        repo = SubscriptionRepository(session)
        workspace_id = parsed["workspace_id"]
        existing = None
        if not workspace_id and parsed["provider_ref"]:
            existing = repo.get_by_provider_ref(parsed["provider"], parsed["provider_ref"])
            workspace_id = getattr(existing, "workspace_id", "") or ""
        if not workspace_id:
            logger.warning(
                f"subscriptions: {provider} event for {parsed['provider_ref']!r} has no "
                "resolvable workspace; ignoring."
            )
            return None
        existing = existing or repo.get_for_workspace(workspace_id)

        if existing is not None and existing.provider_ref:
            same_ref = existing.provider_ref == parsed["provider_ref"]
            if same_ref and existing.status == "canceled" and parsed["status"] != "canceled":
                logger.info(
                    f"subscriptions: ignoring late {parsed['status']} event for canceled "
                    f"{parsed['provider_ref']} (workspace {workspace_id})"
                )
                return {"workspace_id": workspace_id, "status": "canceled", "ignored": True}
            if not same_ref and parsed["status"] not in ("active", "trialing") and _is_live(existing):
                return {"workspace_id": workspace_id, "status": existing.status, "ignored": True}

        plan_key = parsed["plan_key"]
        if wp.get_workspace_plan(plan_key) is None and existing is not None:
            plan_key = existing.plan_key  # renewal without metadata: keep the plan
        interval = parsed["interval"] or (
            getattr(existing, "interval", None) if existing is not None else None
        ) or wp.MONTH
        plan = wp.get_workspace_plan(plan_key)
        credits = plan.period_credits(interval) if plan else 0
        user_id = parsed["user_id"]

        repo.upsert(
            workspace_id,
            plan_key=plan_key,
            provider=parsed["provider"],
            provider_ref=parsed["provider_ref"],
            status=parsed["status"],
            interval=interval,
            seats=parsed["seats"],
            current_period_end=parsed["current_period_end"],
        )
        _audit(
            session,
            actor_user_id=user_id,
            action=(
                "subscription.canceled"
                if parsed["status"] == "canceled"
                else "subscription.activated"
            ),
            workspace_id=workspace_id,
            metadata={"plan_key": plan_key, "status": parsed["status"]},
        )

    granted = False
    live = parsed["status"] in ("active", "trialing")
    if parsed["grant_allowed"] and live and credits > 0:
        from app.services.billing import service as billing_service

        # A period-less event (never sent by Stripe/Polar/Creem for a live
        # subscription, but tolerated) collapses onto one fixed key, so at most
        # ONE such grant can ever happen per provider subscription.
        period_key = parsed["period_key"] or "None"
        period_ref = (
            f"{_REASON_PREFIX}:{workspace_id}:{parsed['provider_ref']}:{period_key}"
        )
        billing_service.fulfill_purchase(
            provider=parsed["provider"],
            external_event_id=period_ref,
            user_id=user_id,
            credits=int(credits),
            reason_ref=period_ref,
            workspace_id=workspace_id,
        )
        granted = True

    return {
        "workspace_id": workspace_id,
        "plan_key": plan_key,
        "status": parsed["status"],
        "granted": granted,
        "credits": int(credits) if granted else 0,
    }


def _audit(
    session: Any,
    *,
    actor_user_id: str | None,
    action: str,
    workspace_id: str,
    metadata: dict | None = None,
) -> None:
    """Best-effort audit record; a blank actor or any failure is swallowed.

    Governance auditing must never block the money path — if the actor is unknown
    (a pure system webhook with no user metadata) or the audit insert fails, the
    subscription/grant still stands.
    """
    if not (actor_user_id or "").strip():
        return
    try:
        from app.services import audit

        audit.record(
            session,
            actor_user_id=actor_user_id,
            action=action,
            workspace_id=workspace_id,
            target_type="subscription",
            target_id=workspace_id,
            metadata=metadata or {},
        )
    except Exception as exc:  # noqa: BLE001 - auditing never blocks billing
        logger.warning(f"subscriptions: audit record failed for {action}: {exc}")


__all__ = [
    "ProviderUnavailableError",
    "cancel_subscription",
    "change_plan",
    "create_subscription",
    "get_subscription",
    "handle_subscription_webhook",
    "process_provider_event",
    "process_subscription_event",
]
