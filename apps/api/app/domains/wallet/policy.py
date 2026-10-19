"""Pure wallet policy: purchase-quote fee/tax + top-up bounds (no DB, no HTTP).

The fee rate, minimum/maximum fee, top-up bounds, and fee-schedule version are
**versioned configuration**, never hard-coded constants
(PROVIDER_MARKETPLACE_PLAN.md §1.2). Tax and processor pass-through are quoted
separately and default to zero here; real jurisdiction/tax handling is a
finance/legal-governed follow-up. All arithmetic is integer microdollars.
"""

from __future__ import annotations

import os
from typing import Any

from app.core.money import MICRODOLLARS_PER_USD

# Defaults chosen to mirror the plan's worked example (5% fee, $0.80 minimum)
# while remaining fully overridable via env/config.
_DEFAULT_FEE_RATE_BPS = 500  # 5.00%
_DEFAULT_MIN_FEE_MICROS = 800_000  # $0.80
_DEFAULT_MAX_FEE_MICROS = 0  # 0 = no cap
_DEFAULT_MIN_TOPUP_MICROS = 5 * MICRODOLLARS_PER_USD  # $5.00
_DEFAULT_MAX_TOPUP_MICROS = 1000 * MICRODOLLARS_PER_USD  # $1,000.00
_DEFAULT_FEE_SCHEDULE_VERSION = "v1"
_MICROS_PER_CENT = 10_000


class TopUpError(Exception):
    """Raised when a requested wallet credit is outside the allowed bounds."""


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


def fee_rate_bps() -> int:
    """Platform fee rate in basis points (500 = 5%); bounded to [0, 5000]."""
    return _bounded_int(
        _config_value("REELFORGE_WALLET_FEE_RATE_BPS", "reelforge_wallet_fee_rate_bps", _DEFAULT_FEE_RATE_BPS),
        _DEFAULT_FEE_RATE_BPS,
        0,
        5000,
    )


def min_fee_micros() -> int:
    return _bounded_int(
        _config_value("REELFORGE_WALLET_MIN_FEE_MICROS", "reelforge_wallet_min_fee_micros", _DEFAULT_MIN_FEE_MICROS),
        _DEFAULT_MIN_FEE_MICROS,
        0,
        100 * MICRODOLLARS_PER_USD,
    )


def max_fee_micros() -> int:
    """Optional fee cap; ``0`` means no cap."""
    return _bounded_int(
        _config_value("REELFORGE_WALLET_MAX_FEE_MICROS", "reelforge_wallet_max_fee_micros", _DEFAULT_MAX_FEE_MICROS),
        _DEFAULT_MAX_FEE_MICROS,
        0,
        1000 * MICRODOLLARS_PER_USD,
    )


def min_topup_micros() -> int:
    return _bounded_int(
        _config_value("REELFORGE_WALLET_MIN_TOPUP_MICROS", "reelforge_wallet_min_topup_micros", _DEFAULT_MIN_TOPUP_MICROS),
        _DEFAULT_MIN_TOPUP_MICROS,
        MICRODOLLARS_PER_USD,  # never below $1
        1000 * MICRODOLLARS_PER_USD,
    )


def max_topup_micros() -> int:
    return _bounded_int(
        _config_value("REELFORGE_WALLET_MAX_TOPUP_MICROS", "reelforge_wallet_max_topup_micros", _DEFAULT_MAX_TOPUP_MICROS),
        _DEFAULT_MAX_TOPUP_MICROS,
        MICRODOLLARS_PER_USD,
        1_000_000 * MICRODOLLARS_PER_USD,
    )


def fee_schedule_version() -> str:
    return str(
        _config_value("REELFORGE_WALLET_FEE_SCHEDULE_VERSION", "reelforge_wallet_fee_schedule_version", _DEFAULT_FEE_SCHEDULE_VERSION)
        or _DEFAULT_FEE_SCHEDULE_VERSION
    )


def compute_fee_micros(credit_micros: int) -> int:
    """Platform fee for a credit amount: ``max(min_fee, credit * rate)``, HALF_UP.

    The fee is charged on top of the wallet credit (never deducted from it), so
    the customer receives the full credit and pays ``credit + fee`` on the card.
    """
    credit = max(0, int(credit_micros))
    rate = fee_rate_bps()
    # Round half up on the integer division by 10_000.
    metered = (credit * rate + 5_000) // 10_000
    fee = max(min_fee_micros(), metered)
    cap = max_fee_micros()
    if cap > 0:
        fee = min(fee, cap)
    # Hosted card rails settle USD in cents. Round the disclosed fee half-up to
    # that same unit so the quoted total is exactly chargeable by every adapter.
    return int(((fee + (_MICROS_PER_CENT // 2)) // _MICROS_PER_CENT) * _MICROS_PER_CENT)


def validate_topup(credit_micros: int) -> None:
    """Raise :class:`TopUpError` when a requested credit is out of bounds."""
    credit = int(credit_micros)
    if credit % _MICROS_PER_CENT != 0:
        raise TopUpError("wallet top-up amount must be a whole number of USD cents")
    if credit < min_topup_micros():
        raise TopUpError(
            f"minimum wallet top-up is {min_topup_micros()} micros"
        )
    if credit > max_topup_micros():
        raise TopUpError(
            f"maximum wallet top-up is {max_topup_micros()} micros"
        )


def build_purchase_quote(credit_micros: int) -> dict:
    """Compute the full checkout money breakdown for a wallet top-up.

    Returns integer-microdollar fields plus the fee-rate/version snapshot. Tax
    and processor pass-through are zero placeholders quoted separately.
    """
    validate_topup(credit_micros)
    credit = int(credit_micros)
    fee = compute_fee_micros(credit)
    tax = 0
    processor = 0
    total = credit + fee + tax + processor
    return {
        "credit_micros": credit,
        "fee_micros": fee,
        "tax_micros": tax,
        "processor_micros": processor,
        "total_charge_micros": total,
        "fee_rate_bps": fee_rate_bps(),
        "fee_schedule_version": fee_schedule_version(),
        "currency": "USD",
    }


# --------------------------------------------------------------------------- #
# M3.3 money-surface freeze: P2P wallet transfers (owner decision O3)
# --------------------------------------------------------------------------- #
P2P_TRANSFERS_ENV = "MENIVOR_WALLET_P2P_TRANSFERS"


def p2p_transfers_enabled(env: dict[str, str] | None = None) -> bool:
    """Whether users may send wallet balance to another user.

    ``MENIVOR_WALLET_P2P_TRANSFERS=on|off`` decides. Unset, transfers are off
    whenever the launch mode is ``public`` (production: frozen, not deleted)
    and stay on in the internal pilot and in development.
    """
    source = os.environ if env is None else env
    raw = str(source.get(P2P_TRANSFERS_ENV, "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    from app.core.launch.policy import launch_mode

    return launch_mode() != "public"
