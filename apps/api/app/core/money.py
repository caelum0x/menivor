"""Shared integer-microdollar money helpers.

The pay-as-you-go marketplace stores every amount as **integer microdollars**
(``1 USD = 1_000_000`` units) and never uses floats for money
(PROVIDER_MARKETPLACE_PLAN.md §3). These helpers convert to/from the
human-facing decimal USD string at the system boundary using
:class:`decimal.Decimal` so rounding is explicit and deterministic.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MICRODOLLARS_PER_USD = 1_000_000

# A hard ceiling so a malformed request can never mint an absurd amount; well
# above any realistic single wallet top-up or job cost.
_MAX_USD = Decimal("1000000")  # $1,000,000


def usd_to_micros(value: str | int | float | Decimal | None) -> int:
    """Convert a USD amount to integer microdollars (banker-free HALF_UP).

    Accepts a decimal string (preferred at boundaries), int, or Decimal. A
    float is tolerated but routed through ``str`` first to avoid binary-float
    surprises. Returns ``0`` for ``None``/blank. Raises ``ValueError`` for an
    unparseable or out-of-range amount so callers fail fast at the boundary.
    """
    if value is None:
        return 0
    if isinstance(value, str) and not value.strip():
        return 0
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid USD amount: {value!r}") from exc
    if dec.is_nan() or dec.is_infinite():
        raise ValueError(f"invalid USD amount: {value!r}")
    if dec < 0:
        raise ValueError(f"USD amount must be non-negative: {value!r}")
    if dec > _MAX_USD:
        raise ValueError(f"USD amount exceeds maximum: {value!r}")
    micros = (dec * MICRODOLLARS_PER_USD).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(micros)


def micros_to_usd_str(micros: int | None) -> str:
    """Render integer microdollars as a fixed 2-decimal USD string (display)."""
    amount = Decimal(int(micros or 0)) / MICRODOLLARS_PER_USD
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def micros_to_usd_decimal(micros: int | None) -> Decimal:
    """Exact Decimal USD value of integer microdollars (no display rounding)."""
    return Decimal(int(micros or 0)) / MICRODOLLARS_PER_USD
