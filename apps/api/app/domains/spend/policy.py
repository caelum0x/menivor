"""Pure spend policy: BYOK routing-fee math + config (no DB, no IO).

When a customer routes a stage through their OWN provider key (BYOK), ReelForge
does not pay the provider — so instead of the pass-through provider price it
charges a disclosed **routing fee** (PROVIDER_MARKETPLACE_PLAN.md §1.3). The fee
rate is versioned configuration; it is never applied silently (a stage's usage
record shows the fee as its cost).
"""

from __future__ import annotations

import os
from typing import Any

_DEFAULT_BYOK_FEE_BPS = 1000  # 10.00% of the equivalent provider price
_DEFAULT_BYOK_MIN_FEE_MICROS = 1_000  # $0.001 floor per BYOK stage


def _config_value(env_name: str, config_key: str, default: Any) -> Any:
    raw = os.getenv(env_name)
    if raw is not None:
        return raw
    try:
        from app.config import config

        return config.app.get(config_key, default)
    except Exception:
        return default


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def byok_fee_bps() -> int:
    """Platform BYOK routing-fee rate in basis points; bounded [0, 5000]."""
    return _bounded_int(
        _config_value("REELFORGE_BYOK_FEE_BPS", "reelforge_byok_fee_bps", _DEFAULT_BYOK_FEE_BPS),
        _DEFAULT_BYOK_FEE_BPS,
        0,
        5000,
    )


def byok_min_fee_micros() -> int:
    return _bounded_int(
        _config_value("REELFORGE_BYOK_MIN_FEE_MICROS", "reelforge_byok_min_fee_micros", _DEFAULT_BYOK_MIN_FEE_MICROS),
        _DEFAULT_BYOK_MIN_FEE_MICROS,
        0,
        10_000_000,
    )


def byok_fee_micros(provider_cost_micros: int) -> int:
    """The routing fee charged for a BYOK stage, from the equivalent provider cost.

    ``max(min_fee, provider_cost * rate)`` in integer microdollars, HALF_UP on the
    /10_000 division. When the fee rate is 0 the fee is 0 (BYOK is free — the
    customer only pays their own provider).
    """
    base = max(0, int(provider_cost_micros))
    rate = byok_fee_bps()
    # No fee when disabled or when there is no billable work (zero-cost stage).
    if rate <= 0 or base <= 0:
        return 0
    metered = (base * rate + 5_000) // 10_000
    return int(max(byok_min_fee_micros(), metered))
