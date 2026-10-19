"""Personal MONTHLY plans for web creators (Creem recurring products).

Distinct from:

* :mod:`app.services.billing.plans` — ONE-TIME credit packs (Starter 30 / $19,
  Pro 120 / $59). Packs stay on sale as top-ups and their credits never expire.
* :mod:`app.services.billing.workspace_plans` — recurring TEAM workspace plans
  that fund a workspace's shared pool.
* RevenueCat (mobile) — store subscriptions; entitlements stay separate.

The one public pricing model (M3.1, MD8): these three plans are the headline
offer (Pro is the recommended plan, annual is two months free), packs are
top-ups, and workspace plans sit under Agency. A "reel" below is one standard
credit: a reel up to 60 s, one started minute of a longer video; a presenter
reel (Pro and Agency only) uses 5.

A monthly plan grants its included reels to the subscriber's PERSONAL balance
once per paid period. Included reels are used before pack credits and do not
roll over: whatever is left of a period's included reels expires when the next
period starts (or when the plan ends). Annual plans grant all twelve months of
reels at the start of each paid year and are charged ten months (two free).

Pure and side-effect free: prices/reels are locked here (config may override the
USD display price), provider product ids come from config ``[creem]
plan_<key>_<interval>_product_id`` or env ``CREEM_PRODUCT_ID_PLAN_<KEY>_<INTERVAL>``
(created by ``tools/ops/create_creem_subscription_products.py``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from app.config import config

MONTH: str = "month"
YEAR: str = "year"
INTERVALS: tuple[str, ...] = (MONTH, YEAR)
#: Months charged for an annual plan (12 months of reels; two months free).
YEARLY_MONTHS_CHARGED: int = 10

CREATOR_KEY: str = "creator"
PRO_KEY: str = "pro"
AGENCY_KEY: str = "agency"

#: Metadata ``kind`` threaded through checkout so webhooks can be routed here.
KIND: str = "creator_plan"

# (key, display name, monthly USD, reels per month). Every per-reel price is
# below the best credit pack ($59 / 120 = $0.49), so a plan is always the
# cheaper way to make reels every month.
_BASELINES: tuple[tuple[str, str, float, int], ...] = (
    (CREATOR_KEY, "Creator", 15.00, 35),
    (PRO_KEY, "Pro", 39.00, 100),
    (AGENCY_KEY, "Agency", 99.00, 300),
)


@dataclass(frozen=True)
class CreatorPlan:
    """Immutable description of one personal monthly plan."""

    key: str
    display_name: str
    rank: int
    monthly_usd: float
    yearly_usd: float
    monthly_reels: int

    def price_usd(self, interval: str) -> float:
        return self.yearly_usd if interval == YEAR else self.monthly_usd

    def period_credits(self, interval: str) -> int:
        """Reels granted per paid period (a year grants 12 months at once)."""
        return self.monthly_reels * (12 if interval == YEAR else 1)

    def per_reel_usd(self, interval: str) -> float:
        credits = self.period_credits(interval)
        return round(self.price_usd(interval) / credits, 4) if credits else 0.0


def _section(name: str) -> Mapping:
    section = getattr(config, name, None)
    if isinstance(section, Mapping):
        return section
    try:
        return dict(section or {})
    except (TypeError, ValueError):
        return {}


def _usd(key: str, interval: str, default: float) -> float:
    raw = _section("billing").get(f"plan_{key}_{interval}_usd")
    if raw is None or raw == "":
        return float(default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    return value if value > 0 else float(default)


def _build(rank: int, key: str, name: str, monthly_default: float, reels: int) -> CreatorPlan:
    monthly = _usd(key, MONTH, monthly_default)
    yearly = _usd(key, YEAR, round(monthly * YEARLY_MONTHS_CHARGED, 2))
    return CreatorPlan(
        key=key,
        display_name=name,
        rank=rank,
        monthly_usd=monthly,
        yearly_usd=yearly,
        monthly_reels=reels,
    )


def list_plans() -> list[CreatorPlan]:
    """All personal monthly plans, cheapest first (built from live config)."""
    return [_build(rank, *baseline) for rank, baseline in enumerate(_BASELINES, start=1)]


def get_plan(key: str | None) -> CreatorPlan | None:
    normalized = (key or "").strip().lower()
    return next((plan for plan in list_plans() if plan.key == normalized), None)


def normalize_interval(interval: str | None) -> str:
    """Validate a billing interval; raises ``ValueError`` on anything else."""
    normalized = (interval or MONTH).strip().lower() or MONTH
    if normalized not in INTERVALS:
        raise ValueError(f"invalid interval {interval!r}; expected month or year")
    return normalized


def _provider(provider: str | None) -> str:
    if provider:
        return provider
    from app.services.billing import payments_mode

    active = payments_mode.active_provider()
    return active if active in (payments_mode.CREEM, payments_mode.DODO) else payments_mode.CREEM


def env_name(key: str, interval: str, provider: str | None = None) -> str:
    """Env var holding the recurring product id for ``key`` / ``interval``."""
    if _provider(provider) == "dodo":
        return f"DODO_PRODUCT_ID_PLAN_{key.upper()}_{interval.upper()}"
    return f"CREEM_PRODUCT_ID_PLAN_{key.upper()}_{interval.upper()}"


def product_id(key: str, interval: str, provider: str | None = None) -> str:
    """Configured recurring product id (active provider by default), or ``""``."""
    chosen = _provider(provider)
    section = "dodo" if chosen == "dodo" else "creem"
    raw = _section(section).get(f"plan_{key}_{interval}_product_id", "") or ""
    return (str(raw).strip() or os.getenv(env_name(key, interval, chosen), "")).strip()


def plan_for_product(ref: str | None, provider: str | None = None) -> tuple[CreatorPlan, str] | None:
    """Reverse-map a recurring product id (any known provider) to ``(plan, interval)``."""
    needle = (ref or "").strip()
    if not needle:
        return None
    providers = (provider,) if provider else ("creem", "dodo")
    for plan in list_plans():
        for interval in INTERVALS:
            for candidate in providers:
                if product_id(plan.key, interval, candidate) == needle:
                    return plan, interval
    return None


def best_pack_per_reel_usd() -> float:
    """Cheapest per-reel price among the one-time packs (for comparison copy)."""
    from app.services.billing.plans import list_plans as list_packs

    prices = [p.price_usd / p.credits for p in list_packs(purchasable_only=True) if p.credits]
    return round(min(prices), 4) if prices else 0.0


def catalog() -> list[dict]:
    """Public, secret-free catalog for ``GET /billing/monthly-plans``."""
    from app.services.billing import payments_mode

    active = payments_mode.active_provider()
    if active in (payments_mode.CREEM, payments_mode.DODO):
        creem_ready = bool(str(_section(active).get("api_key", "") or "").strip())
    else:
        creem_ready = False
    rows: list[dict] = []
    for plan in list_plans():
        rows.append(
            {
                "plan_key": plan.key,
                "name": plan.display_name,
                "rank": plan.rank,
                "currency": "USD",
                "monthly_cents": int(round(plan.monthly_usd * 100)),
                "yearly_cents": int(round(plan.yearly_usd * 100)),
                "monthly_reels": plan.monthly_reels,
                "yearly_reels": plan.period_credits(YEAR),
                "per_reel_cents": {
                    interval: int(round(plan.per_reel_usd(interval) * 100)) for interval in INTERVALS
                },
                "available": {
                    interval: creem_ready and bool(product_id(plan.key, interval))
                    for interval in INTERVALS
                },
            }
        )
    return rows


__all__ = [
    "AGENCY_KEY",
    "CREATOR_KEY",
    "CreatorPlan",
    "INTERVALS",
    "KIND",
    "MONTH",
    "PRO_KEY",
    "YEAR",
    "YEARLY_MONTHS_CHARGED",
    "best_pack_per_reel_usd",
    "catalog",
    "env_name",
    "get_plan",
    "list_plans",
    "normalize_interval",
    "plan_for_product",
    "product_id",
]
