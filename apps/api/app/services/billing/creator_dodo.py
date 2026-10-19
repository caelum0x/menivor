"""Dodo Payments transport for personal monthly plans (no DB writes, no grants).

Same interface as :mod:`creator_creem` so :mod:`creator_plan_actions` can pick
the transport by the subscription row's ``provider``:

* :func:`open_checkout` — hosted checkout for a recurring (usage-based) plan
  product with ``kind=creator_plan`` metadata so every webhook routes back.
* :func:`fetch_subscription_view` — the live subscription, normalized.
* :func:`cancel` / :func:`change_product` / :func:`portal_link`.
* :func:`parse_event` — a verified Dodo webhook as a personal-plan update.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.services.billing import creator_plans as cp
from app.services.billing import dodo_client

PROVIDER: str = "dodo"


def open_checkout(
    *, user_id: str, user_email: str, plan: cp.CreatorPlan, interval: str
) -> dict[str, str]:
    product = cp.product_id(plan.key, interval, PROVIDER)
    if not product:
        raise RuntimeError(
            f"Dodo product for {plan.display_name} ({interval}ly) is not configured: "
            f"set {cp.env_name(plan.key, interval, PROVIDER)}."
        )
    result = dodo_client.create_checkout(
        product_id=product,
        metadata={
            "kind": cp.KIND,
            "user_id": user_id,
            "plan_key": plan.key,
            "interval": interval,
        },
        return_url=dodo_client.return_url("/billing"),
        customer_email=user_email,
    )
    logger.info(f"creator plans (dodo): checkout {result['session_id']} user={user_id} plan={plan.key}/{interval}")
    return result


def fetch_subscription_view(subscription_id: str) -> dict[str, Any]:
    return dodo_client.subscription_view(dodo_client.get_subscription(subscription_id))


def cancel(subscription_id: str) -> str:
    return dodo_client.cancel_subscription(subscription_id)


def change_product(subscription_id: str, product_id: str, *, upgrade: bool) -> None:
    dodo_client.change_plan(subscription_id, product_id, upgrade=upgrade)


def portal_link(customer_id: str) -> str:
    return dodo_client.portal_link(customer_id)


def parse_event(event: Any) -> dict[str, Any] | None:
    """A verified Dodo ``subscription.*`` event as a personal-plan update, or None."""
    etype = dodo_client.event_type(event)
    if etype not in dodo_client.SUBSCRIPTION_EVENTS:
        return None
    view = dodo_client.subscription_view(dodo_client.event_data(event), event=etype)
    metadata = view["metadata"]
    mapped = cp.plan_for_product(view["product_ref"], PROVIDER)
    if mapped is None and str(metadata.get("kind", "") or "") != cp.KIND:
        return None
    plan = mapped[0] if mapped else cp.get_plan(str(metadata.get("plan_key", "") or ""))
    interval = mapped[1] if mapped else str(metadata.get("interval", "") or "")
    view.update(
        provider=PROVIDER,
        event_type=etype,
        user_id=str(metadata.get("user_id", "") or "").strip(),
        plan_key=plan.key if plan else "",
        interval=interval if interval in cp.INTERVALS else "",
        grant_allowed=etype in dodo_client.GRANT_EVENTS,
    )
    return view


__all__ = [
    "PROVIDER",
    "cancel",
    "change_product",
    "fetch_subscription_view",
    "open_checkout",
    "parse_event",
    "portal_link",
]
