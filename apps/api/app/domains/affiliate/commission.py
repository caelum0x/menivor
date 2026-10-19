"""Affiliate commission engine — lifetime-recurring referral payouts.

A referrer earns a percentage of every payment their referee makes, for the
lifetime of the account (a strong PLG loop for creator tools). Pure integer-micro
math (matches the wallet money model): given a referral relationship + a payment,
compute the commission, honoring a per-referral lifetime cap and a tier rate.

Deterministic; the ledger + referral graph live in the domain service.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tier rates in basis points (100 bps = 1%). Lifetime-recurring.
TIER_RATES_BPS = {
    "standard": 2000,   # 20%
    "pro": 3000,        # 30% (high-volume affiliates)
    "partner": 4000,    # 40% (negotiated)
}
_DEFAULT_TIER = "standard"


@dataclass(frozen=True)
class Referral:
    """A referrer→referee relationship with a tier + optional lifetime cap."""

    referrer_id: str
    referee_id: str
    tier: str = _DEFAULT_TIER
    lifetime_cap_micros: int = 0     # 0 == uncapped
    earned_micros: int = 0           # already paid out on this referral


@dataclass(frozen=True)
class Commission:
    """A computed commission for one referee payment."""

    payable_micros: int
    rate_bps: int
    capped: bool
    reason: str = ""


class AffiliateError(ValueError):
    """An invalid referral (e.g. self-referral)."""


def rate_bps(tier: str) -> int:
    return TIER_RATES_BPS.get(str(tier or "").strip().lower(), TIER_RATES_BPS[_DEFAULT_TIER])


def compute_commission(referral: Referral, payment_micros: int) -> Commission:
    """Commission = payment × tier_rate, clamped to the remaining lifetime cap.

    Integer floor-division so no fractional micro is minted. A self-referral is
    rejected (fraud guard). A payment ≤ 0 yields zero.
    """
    if referral.referrer_id == referral.referee_id:
        raise AffiliateError("self-referral is not allowed")
    pay = max(0, int(payment_micros))
    bps = rate_bps(referral.tier)
    gross = (pay * bps) // 10000

    if referral.lifetime_cap_micros > 0:
        remaining = max(0, referral.lifetime_cap_micros - max(0, referral.earned_micros))
        payable = min(gross, remaining)
        return Commission(payable, bps, capped=payable < gross,
                          reason="lifetime-cap" if payable < gross else "ok")
    return Commission(gross, bps, capped=False, reason="ok")
