"""Gateway provisioning keys + markup policy (OpenRouter-style resale core).

Turns the wallet into a resellable API platform. Two pure cores:

1. **Provisioning keys** — a reseller/customer gets keys with a per-key spend cap
   that resets at midnight UTC. :func:`check_spend` gates a charge against the
   remaining allowance for the current UTC window; :func:`remaining` reports
   headroom. Deterministic (``now`` + accumulated spend are passed in).

2. **Markup policy** — a reseller marks up the wallet's base cost. :func:`apply_markup`
   computes the customer-facing price in integer microdollars (base_cost +
   markup_bps), never floats, matching the wallet's money model.

No DB/clock here — the key store + ledger live in the domain service; this is the
tested decision core the gateway router and billing bridge call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

_MICROS = 1  # values are already integer microdollars; kept explicit for intent


@dataclass(frozen=True)
class ProvisioningKey:
    """A reseller/customer key with a daily (UTC) spend cap."""

    key_id: str
    owner_id: str
    daily_cap_micros: int          # 0 == unlimited
    label: str = ""
    disabled: bool = False


@dataclass(frozen=True)
class SpendDecision:
    """Whether a charge is allowed under a key's current-window allowance."""

    allow: bool
    remaining_micros: int
    reason: str = ""


class GatewayError(ValueError):
    """An invalid provisioning/markup operation."""


def window_start(now: datetime) -> datetime:
    """The midnight-UTC start of the spend window containing ``now``."""
    n = now.astimezone(timezone.utc)
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def remaining(key: ProvisioningKey, spent_today_micros: int) -> int:
    """Micros left on the key for the current UTC day (``-1`` == unlimited)."""
    if key.daily_cap_micros <= 0:
        return -1
    return max(0, key.daily_cap_micros - max(0, int(spent_today_micros)))


def check_spend(
    key: ProvisioningKey, charge_micros: int, *, spent_today_micros: int
) -> SpendDecision:
    """Gate ``charge_micros`` against the key's remaining daily allowance.

    ``spent_today_micros`` is the sum already spent since the current
    :func:`window_start` (the caller computes it from the ledger). A disabled key
    or an over-cap charge is denied; an unlimited key always allows.
    """
    if key.disabled:
        return SpendDecision(False, 0, "key disabled")
    if charge_micros < 0:
        raise GatewayError("charge_micros must be non-negative")
    if key.daily_cap_micros <= 0:
        return SpendDecision(True, -1, "unlimited")
    left = remaining(key, spent_today_micros)
    if charge_micros > left:
        return SpendDecision(False, left, f"daily cap exceeded: need {charge_micros}, {left} left")
    return SpendDecision(True, left - charge_micros, "ok")


@dataclass(frozen=True)
class MarkupPolicy:
    """A reseller's markup over the wallet's base cost."""

    markup_bps: int = 0            # basis points (100 bps = 1%)
    min_fee_micros: int = 0        # floor added on top (e.g. per-call minimum)

    def __post_init__(self) -> None:
        if self.markup_bps < 0 or self.min_fee_micros < 0:
            raise GatewayError("markup must be non-negative")


def apply_markup(base_cost_micros: int, policy: MarkupPolicy) -> int:
    """Customer-facing price = base + base*bps/10000 + min_fee (integer micros).

    Integer math only (banker-safe floor division) — never floats, matching the
    wallet's microdollar model.
    """
    base = max(0, int(base_cost_micros))
    markup = (base * int(policy.markup_bps)) // 10000
    return base + markup + int(policy.min_fee_micros)


def margin_micros(base_cost_micros: int, policy: MarkupPolicy) -> int:
    """The reseller's margin (customer price − base cost) in micros."""
    return apply_markup(base_cost_micros, policy) - max(0, int(base_cost_micros))
