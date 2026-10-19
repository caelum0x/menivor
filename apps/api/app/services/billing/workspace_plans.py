"""Workspace SUBSCRIPTION plan catalog (recurring team plans).

Distinct from :mod:`app.services.billing.plans`, which prices the ONE-TIME
personal credit packs. A provider price that is recurring can never be used for
a one-time purchase (Stripe rejects a recurring price under ``mode="payment"``
and a one-time price under ``mode="subscription"``), so workspace plans carry
their OWN provider ids — one per billing interval:

* Stripe  -> ``[stripe] team_<plan>_<interval>_price_id``   (recurring Price id)
* Creem   -> ``[creem]  team_<plan>_<interval>_product_id`` (subscription Product id)
* Polar   -> ``[polar]  team_<plan>_<interval>_product_id`` (recurring Product id)
* Dodo    -> ``[dodo]   team_<plan>_<interval>_product_id`` (subscription Product
  id), or env ``DODO_PRODUCT_ID_TEAM_<PLAN>_<INTERVAL>``. The Dodo transport
  lives at the bottom of this module (``open_dodo_checkout`` /
  ``parse_dodo_event``); Dodo is only offered once :mod:`subscription_providers`
  dispatches to it (``transport_ready``).

``<plan>`` is ``starter`` | ``pro`` and ``<interval>`` is ``month`` | ``year``.
Display prices default to the public /billing page ($19/mo, $59/mo; yearly = 10x
monthly, i.e. two months free) and may be overridden via ``[billing]
team_<plan>_<interval>_usd``. The provider-side Price/Product is what actually
charges the card, so the owner must configure matching amounts there.

Credits: a plan grants its monthly allotment (from the entitlement bundle) per
month, so a yearly subscription is granted ``monthly * 12`` once per paid year.
The catalog functions are pure and only read the already-loaded config; the
Dodo transport functions call Dodo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from app.config import config
from app.services import entitlements

MONTH: str = "month"
YEAR: str = "year"
INTERVALS: tuple[str, ...] = (MONTH, YEAR)

STRIPE: str = "stripe"
CREEM: str = "creem"
POLAR: str = "polar"
DODO: str = "dodo"
#: Rails that support recurring workspace plans, in preference order.
SUBSCRIPTION_PROVIDERS: tuple[str, ...] = (STRIPE, CREEM, POLAR, DODO)

# Required secret per provider for it to be offered at all.
_PROVIDER_SECRET_KEY: dict[str, str] = {
    STRIPE: "secret_key",
    CREEM: "api_key",
    POLAR: "access_token",
    DODO: "api_key",
}
# Config key suffix holding the recurring provider id per provider.
_PROVIDER_REF_SUFFIX: dict[str, str] = {
    STRIPE: "price_id",
    CREEM: "product_id",
    POLAR: "product_id",
    DODO: "product_id",
}

# (key, display_name, rank, default monthly USD). Yearly defaults to 10x monthly.
_BASELINES: tuple[tuple[str, str, int, float], ...] = (
    (entitlements.STARTER_PLAN, "Team Starter", 1, 19.00),
    (entitlements.PRO_PLAN, "Team Pro", 2, 59.00),
)
_YEARLY_MONTHS_CHARGED: int = 10


@dataclass(frozen=True)
class WorkspacePlan:
    """Immutable description of one self-serve recurring workspace plan."""

    key: str
    display_name: str
    rank: int
    monthly_usd: float
    yearly_usd: float
    monthly_credits: int
    max_seats: int

    def price_usd(self, interval: str) -> float:
        """Retail price for one billing period of ``interval``."""
        return self.yearly_usd if interval == YEAR else self.monthly_usd

    def period_credits(self, interval: str) -> int:
        """Credits granted per paid period (a year grants 12 months at once)."""
        return self.monthly_credits * (12 if interval == YEAR else 1)


def _section(name: str) -> Mapping:
    section = getattr(config, name, None)
    if isinstance(section, Mapping):
        return section
    try:
        return dict(section or {})
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


def _usd(key: str, interval: str, default: float) -> float:
    raw = _section("billing").get(f"team_{key}_{interval}_usd")
    if raw is None or raw == "":
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _feature_int(plan_key: str, feature: str) -> int:
    try:
        return int(entitlements.resolve(plan_key, feature, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _build(key: str, name: str, rank: int, monthly_default: float) -> WorkspacePlan:
    monthly = _usd(key, MONTH, monthly_default)
    yearly = _usd(key, YEAR, round(monthly * _YEARLY_MONTHS_CHARGED, 2))
    return WorkspacePlan(
        key=key,
        display_name=name,
        rank=rank,
        monthly_usd=monthly,
        yearly_usd=yearly,
        monthly_credits=_feature_int(key, entitlements.FEAT_MONTHLY_CREDITS),
        max_seats=max(1, _feature_int(key, entitlements.FEAT_SEATS)),
    )


def list_workspace_plans() -> list[WorkspacePlan]:
    """All self-serve workspace plans, cheapest first (built from live config)."""
    return [_build(*baseline) for baseline in _BASELINES]


def get_workspace_plan(key: str) -> WorkspacePlan | None:
    """The self-serve plan for ``key`` (case-insensitive), or ``None``.

    ``free`` (the implicit base) and ``enterprise`` (sales-led, custom pricing)
    are deliberately NOT self-serve, so both return ``None``.
    """
    normalized = (key or "").strip().lower()
    for plan in list_workspace_plans():
        if plan.key == normalized:
            return plan
    return None


def normalize_interval(interval: str) -> str:
    """Validate a billing interval; raises ``ValueError`` on anything else."""
    normalized = (interval or MONTH).strip().lower() or MONTH
    if normalized not in INTERVALS:
        raise ValueError(f"invalid interval {interval!r}; expected month or year")
    return normalized


def dodo_env_name(plan_key: str, interval: str) -> str:
    """Env var holding the Dodo subscription product for a team plan."""
    return f"DODO_PRODUCT_ID_TEAM_{plan_key.upper()}_{interval.upper()}"


def provider_ref(provider: str, plan_key: str, interval: str) -> str:
    """The configured recurring Price/Product id, or ``""`` when unset."""
    suffix = _PROVIDER_REF_SUFFIX.get(provider)
    if not suffix:
        return ""
    configured = str(
        _section(provider).get(f"team_{plan_key}_{interval}_{suffix}", "") or ""
    ).strip()
    if configured or provider != DODO:
        return configured
    return (os.environ.get(dodo_env_name(plan_key, interval)) or "").strip()


def transport_ready(provider: str) -> bool:
    """True when :mod:`subscription_providers` can open and parse this rail.

    Stripe, Creem and Polar are built in. Dodo is ready once that module lists
    it in ``SUPPORTED_PROVIDERS`` (so the UI never offers a checkout that would
    fail with "unsupported provider").
    """
    if provider != DODO:
        return True
    from app.services.billing import subscription_providers

    return DODO in tuple(getattr(subscription_providers, "SUPPORTED_PROVIDERS", ()))


def plan_for_provider_ref(provider: str, ref: str) -> tuple[str, str] | None:
    """Reverse-map a provider Price/Product id to ``(plan_key, interval)``."""
    needle = (ref or "").strip()
    if not needle:
        return None
    for plan in list_workspace_plans():
        for interval in INTERVALS:
            if provider_ref(provider, plan.key, interval) == needle:
                return plan.key, interval
    return None


def provider_enabled(provider: str) -> bool:
    """True when the provider's API secret is configured."""
    secret_key = _PROVIDER_SECRET_KEY.get(provider)
    if not secret_key:
        return False
    if str(_section(provider).get(secret_key, "") or "").strip():
        return True
    return provider == DODO and bool((os.environ.get("DODO_API_KEY") or "").strip())


def available_providers(plan_key: str, interval: str) -> list[str]:
    """Rails that can sell ``plan_key`` at ``interval`` right now.

    A rail qualifies only when its secret AND the recurring id for that exact
    plan + interval are both configured, so the UI never offers a checkout that
    is guaranteed to fail.
    """
    return [
        provider
        for provider in SUBSCRIPTION_PROVIDERS
        if provider_enabled(provider)
        and provider_ref(provider, plan_key, interval)
        and transport_ready(provider)
    ]


def dodo_checkout_status() -> dict[str, dict[str, bool]]:
    """``{plan_key: {interval: available}}`` for Dodo team checkouts (/launch/status).

    A checkout is available only when its Dodo product is mapped, the Dodo key
    is set and the transport is wired. Secret-free.
    """
    return {
        plan.key: {interval: DODO in available_providers(plan.key, interval) for interval in INTERVALS}
        for plan in list_workspace_plans()
    }


def catalog() -> list[dict]:
    """Public, secret-free catalog for ``GET /billing/workspace-plans``."""
    rows: list[dict] = []
    for plan in list_workspace_plans():
        rows.append(
            {
                "plan_key": plan.key,
                "name": plan.display_name,
                "rank": plan.rank,
                "monthly_cents": int(round(plan.monthly_usd * 100)),
                "yearly_cents": int(round(plan.yearly_usd * 100)),
                "currency": "USD",
                "monthly_credits": plan.monthly_credits,
                "max_seats": plan.max_seats,
                "providers": {
                    interval: available_providers(plan.key, interval)
                    for interval in INTERVALS
                },
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# Dodo transport for team plans (MN4). subscription_providers dispatches here:
# open_checkout -> open_dodo_checkout, cancel -> cancel_dodo,
# change_plan -> change_dodo_plan, parse_event -> parse_dodo_event.
# --------------------------------------------------------------------------- #
#: subscription_providers.KIND_SUBSCRIPTION (kept literal to avoid an import cycle).
KIND_TEAM: str = "subscription"


def open_dodo_checkout(product_id: str, metadata: Mapping[str, Any], *, user_email: str) -> dict:
    """Hosted checkout for a recurring team plan (metadata threads the workspace)."""
    from app.services.billing import dodo_client

    return dodo_client.create_checkout(
        product_id=product_id,
        metadata={**dict(metadata), "kind": KIND_TEAM},
        return_url=dodo_client.return_url("/workspaces", workspace=str(metadata.get("workspace_id", ""))),
        customer_email=user_email,
    )


def cancel_dodo(subscription_id: str) -> None:
    """Cancel a team subscription now (workspace cancel is immediate)."""
    from urllib.parse import quote

    from app.services.billing import dodo_client

    ref = (subscription_id or "").strip()
    if not ref:
        raise ValueError("subscription has no Dodo id to cancel")
    dodo_client.request("PATCH", f"/subscriptions/{quote(ref, safe='')}", body={"status": "cancelled"})


def change_dodo_plan(subscription_id: str, product_id: str) -> None:
    """Move a team subscription to another plan (prorated, charged now)."""
    from app.services.billing import dodo_client

    dodo_client.change_plan(subscription_id, product_id, upgrade=True)


def _team_plan_for(product_id: str) -> tuple[str, str] | None:
    return plan_for_provider_ref(DODO, product_id)


def is_dodo_team_event(event: Any) -> bool:
    """True for a Dodo ``subscription.*`` event that belongs to a workspace plan."""
    from app.services.billing import dodo_client

    etype = dodo_client.event_type(event)
    if etype not in dodo_client.SUBSCRIPTION_EVENTS:
        return False
    data = dodo_client.event_data(event)
    kind = str((data.get("metadata") or {}).get("kind", "") or "")
    return kind == KIND_TEAM or _team_plan_for(str(data.get("product_id", "") or "")) is not None


def parse_dodo_event(event: Any) -> dict[str, Any] | None:
    """A verified Dodo ``subscription.*`` event in the shared workspace shape."""
    from app.services.billing import dodo_client
    from app.services.billing import subscription_providers as sp

    if not is_dodo_team_event(event):
        return None
    etype = dodo_client.event_type(event)
    view = dodo_client.subscription_view(dodo_client.event_data(event), event=etype)
    return sp._normalized(
        provider=DODO,
        event_id=dodo_client.event_id(event),
        metadata=view["metadata"],
        provider_ref=view["provider_ref"],
        status=view["status"],
        period_end=view["period_end"],
        product_ref=view["product_ref"],
        grant_allowed=etype in dodo_client.GRANT_EVENTS,
    )


__all__ = [
    "INTERVALS",
    "MONTH",
    "SUBSCRIPTION_PROVIDERS",
    "WorkspacePlan",
    "YEAR",
    "DODO",
    "KIND_TEAM",
    "available_providers",
    "cancel_dodo",
    "change_dodo_plan",
    "catalog",
    "dodo_checkout_status",
    "dodo_env_name",
    "get_workspace_plan",
    "is_dodo_team_event",
    "list_workspace_plans",
    "normalize_interval",
    "open_dodo_checkout",
    "parse_dodo_event",
    "plan_for_provider_ref",
    "provider_enabled",
    "provider_ref",
    "transport_ready",
]
