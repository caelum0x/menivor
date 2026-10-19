"""ReelForge billing plan catalog.

Pure, config-driven definitions of the purchasable credit plans. There is no
network access here: the module only reads the already-loaded application
config for provider identifiers (Stripe price ids, iyzico amounts). All
secrets/ids come from ``config`` — nothing is hardcoded.

Locked plans (contract):

    * Free    -> 3 credits   (granted once at signup; not sold)
    * Starter -> 30 credits
    * Pro     -> 120 credits

1 credit == 1 rendered reel up to 60 s; longer videos use 1 credit per started
minute and presenter reels 5 (M3.1, MD8; see ``app.domains.reels.pricing``).
Packs are top-ups next to the monthly plans. Default USD prices match the public /pricing page
(Starter pack $19, Pro pack $59) so the catalog served by ``GET /billing/plans``
never contradicts the marketing copy. Credit counts are locked; USD prices and
provider ids may be overridden via config ``[billing] <key>_price_usd`` without
touching this file — the provider-side Price/Product must charge the same amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.config import config

# Credits handed to every new user exactly once at signup (see CreditRepository
# .grant with reason "signup"). Kept here so billing has a single source.
SIGNUP_GRANT: int = 3

FREE_KEY: str = "free"
STARTER_KEY: str = "starter"
PRO_KEY: str = "pro"


@dataclass(frozen=True)
class Plan:
    """Immutable description of a credit plan.

    Attributes:
        key: Stable machine identifier ("free" | "starter" | "pro").
        display_name: Human-facing label.
        credits: Rendered-video credits granted on purchase (locked per plan).
        price_usd: Retail price in USD (0.0 for the free signup grant).
        stripe_price_id: Stripe Price id for Checkout; "" when not configured.
        iyzico_amount: iyzico ``price`` string (decimal, e.g. "49.00").
        creem_product_id: Creem (creem.io) Product id for Checkout; "" when
            not configured.
        polar_price_id: Polar (polar.sh) Price id for Checkout; "" when not
            configured.
    """

    key: str
    display_name: str
    credits: int
    price_usd: float
    stripe_price_id: str
    iyzico_amount: str
    creem_product_id: str
    polar_price_id: str
    dodo_product_id: str = ""
    paddle_price_id: str = ""

    @property
    def is_purchasable(self) -> bool:
        """Paid packs are purchasable; the free signup grant is not."""
        return self.credits > 0 and self.price_usd > 0.0


# (key, display_name, locked_credits, default_price_usd)
# Credits are locked by the contract. Default prices are the published /pricing
# prices and can be overridden via config [billing].
_PLAN_BASELINES: tuple[tuple[str, str, int, float], ...] = (
    (FREE_KEY, "Free", SIGNUP_GRANT, 0.0),
    (STARTER_KEY, "Starter", 30, 19.00),
    (PRO_KEY, "Pro", 120, 59.00),
)


def _section(name: str) -> Mapping:
    """Return a config section as a mapping, or an empty mapping if absent.

    Guarded so the catalog builds even before the stripe/iyzico/billing config
    sections are wired up by the config builder.
    """
    section = getattr(config, name, None)
    if isinstance(section, Mapping):
        return section
    return {}


def _price_usd(key: str, default_usd: float) -> float:
    """Resolve the USD price for a plan, allowing a [billing] override."""
    raw = _section("billing").get(f"{key}_price_usd")
    if raw is None:
        return float(default_usd)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default_usd)


def _stripe_price_id(key: str) -> str:
    """Stripe Price id for a plan from config [stripe]; "" when unset."""
    return str(_section("stripe").get(f"{key}_price_id", "") or "")


def _creem_product_id(key: str) -> str:
    """Creem (creem.io) Product id for a plan from config [creem]; "" when unset."""
    return str(_section("creem").get(f"{key}_product_id", "") or "")


def _polar_price_id(key: str) -> str:
    """Polar (polar.sh) Price id for a plan from config [polar]; "" when unset."""
    return str(_section("polar").get(f"{key}_price_id", "") or "")


def _dodo_product_id(key: str) -> str:
    """Dodo Payments product id for a pack from config [dodo]; "" when unset."""
    return str(_section("dodo").get(f"{key}_product_id", "") or "")


def _paddle_price_id(key: str) -> str:
    """Paddle Billing price id for a pack from config [paddle]; "" when unset."""
    return str(_section("paddle").get(f"{key}_price_id", "") or "")


def _iyzico_amount(key: str, price_usd: float) -> str:
    """iyzico decimal amount string for a plan.

    Prefers an explicit config [iyzico] per-plan amount (local currency);
    otherwise falls back to the USD price formatted to 2 decimals.
    """
    raw = _section("iyzico").get(f"{key}_amount")
    if raw is None or raw == "":
        return f"{price_usd:.2f}"
    return str(raw)


def _build_plan(key: str, display_name: str, credits: int, default_price: float) -> Plan:
    """Construct one immutable Plan from its locked baseline + config."""
    price_usd = _price_usd(key, default_price)
    return Plan(
        key=key,
        display_name=display_name,
        credits=credits,
        price_usd=price_usd,
        stripe_price_id=_stripe_price_id(key),
        iyzico_amount=_iyzico_amount(key, price_usd),
        creem_product_id=_creem_product_id(key),
        polar_price_id=_polar_price_id(key),
        dodo_product_id=_dodo_product_id(key),
        paddle_price_id=_paddle_price_id(key),
    )


# Frozen catalog. Built once at import from the locked baselines + config.
_CATALOG: Mapping[str, Plan] = MappingProxyType(
    {
        key: _build_plan(key, display_name, credits, default_price)
        for key, display_name, credits, default_price in _PLAN_BASELINES
    }
)


def get_plan(key: str) -> Plan | None:
    """Return the Plan for ``key`` (case/space-insensitive), or None if unknown."""
    if not key:
        return None
    return _CATALOG.get(key.strip().lower())


def list_plans(purchasable_only: bool = False) -> list[Plan]:
    """Return all plans in catalog order.

    Args:
        purchasable_only: When True, exclude the free (non-sold) signup grant.
    """
    plans = list(_CATALOG.values())
    if purchasable_only:
        return [plan for plan in plans if plan.is_purchasable]
    return plans
