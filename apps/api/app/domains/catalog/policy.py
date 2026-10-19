"""Pure catalog pricing + quote policy (no DB, no HTTP).

Encapsulates the integer-microdollar arithmetic and quote lifetime rules used
when resolving a generation profile to a price snapshot. Kept side-effect free
so it is exhaustively unit-testable and can never accidentally touch money rows.

Money invariants (PROVIDER_MARKETPLACE_PLAN.md §3):
* All amounts are integer microdollars — never floats.
* A stage charge is ``flat_fee + max(min_charge, unit_price * quantity)``.
* A quote has a bounded lifetime; an expired quote must be re-fetched.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

# Default quote lifetime; an expired quote may not be used to reserve funds.
_DEFAULT_QUOTE_TTL_S = 900
# Absolute bounds so a misconfiguration cannot mint an eternal or useless quote.
_MIN_QUOTE_TTL_S = 60
_MAX_QUOTE_TTL_S = 3600


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def quote_ttl_s() -> int:
    """Resolve the quote lifetime (seconds) from env/config, safely bounded."""
    raw: Any = os.getenv("REELFORGE_QUOTE_TTL_S")
    if raw is None:
        try:
            from app.config import config

            raw = config.app.get("reelforge_quote_ttl_s", _DEFAULT_QUOTE_TTL_S)
        except Exception:
            raw = _DEFAULT_QUOTE_TTL_S
    return _bounded_int(raw, _DEFAULT_QUOTE_TTL_S, _MIN_QUOTE_TTL_S, _MAX_QUOTE_TTL_S)


def quote_expiry(now: datetime | None = None) -> datetime:
    """Return the UTC expiry instant for a quote minted at ``now`` (default now)."""
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(seconds=quote_ttl_s())


def stage_cost_micros(
    *,
    unit_price_micros: int,
    quantity_units: int,
    min_charge_micros: int = 0,
    flat_fee_micros: int = 0,
) -> int:
    """Cost of one stage in microdollars (pure integer arithmetic).

    ``flat_fee + max(min_charge, unit_price * quantity)``. Negative inputs are
    clamped to zero so a malformed catalog row can never produce a credit.
    """
    unit_price = max(0, int(unit_price_micros))
    quantity = max(0, int(quantity_units))
    min_charge = max(0, int(min_charge_micros))
    flat_fee = max(0, int(flat_fee_micros))
    metered = unit_price * quantity
    return flat_fee + max(min_charge, metered)


def estimate_quantity(quote_rules: dict | None, requested: Any = None) -> int:
    """Resolve the billed quantity for a stage estimate.

    A caller-supplied ``requested`` quantity wins; otherwise the price version's
    ``quote_rules.default_units`` is used; otherwise 1. Always a non-negative
    integer so it composes with :func:`stage_cost_micros`.
    """
    if requested is not None:
        return max(0, _bounded_int(requested, 0, 0, 10_000_000))
    rules = quote_rules or {}
    default_units = rules.get("default_units", 1)
    return max(0, _bounded_int(default_units, 1, 0, 10_000_000))


def effective_cap_micros(*caps: int | None) -> int | None:
    """Return the tightest (smallest positive) max-cost cap, or None if unbounded.

    A cap of ``0`` / ``None`` means "no cap at this level"; the tightest positive
    cap across the profile and request governs the reservation ceiling.
    """
    positives = [int(c) for c in caps if c not in (None, 0) and int(c) > 0]
    return min(positives) if positives else None


def within_cap(total_micros: int, cap_micros: int | None) -> bool:
    """True when ``total`` fits under ``cap`` (or there is no cap)."""
    if cap_micros is None:
        return True
    return int(total_micros) <= int(cap_micros)


# --------------------------------------------------------------------------- #
# Tamper-evident quote snapshots
# --------------------------------------------------------------------------- #
# A quote is stateless (there is no quotes table); it is returned to the client
# and later submitted with a job-create. Signing the price-bearing fields lets
# the create path verify the server minted this exact snapshot, so a client can
# never submit an arbitrary price (PROVIDER_MARKETPLACE_PLAN.md §8). The secret
# is server-only; it is never returned to the client.
_SIGNED_FIELDS = (
    "quote_id",
    "currency",
    "total_micros",
    "max_cost_micros",
    "expires_at",
    "stages",
)


def _canonical_quote_bytes(payload: dict) -> bytes:
    """Deterministic byte encoding of the signed subset of a quote payload."""
    subset = {key: payload.get(key) for key in _SIGNED_FIELDS}
    return json.dumps(subset, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_quote(payload: dict, secret: str) -> str:
    """Return the HMAC-SHA256 hex signature of a quote's price-bearing fields."""
    return hmac.new(
        str(secret or "").encode("utf-8"),
        _canonical_quote_bytes(payload),
        hashlib.sha256,
    ).hexdigest()


def verify_quote(payload: dict, signature: str, secret: str) -> bool:
    """Constant-time check that ``signature`` matches ``payload`` under ``secret``."""
    if not signature:
        return False
    expected = sign_quote(payload, secret)
    return hmac.compare_digest(expected, str(signature))
