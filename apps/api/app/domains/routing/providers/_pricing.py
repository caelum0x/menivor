"""Shared quote helper: every adapter prices from OUR resolved price version.

An adapter never invents a price. Given the ReelForge-resolved ``price_version``
and the request's estimated quantity, it returns a max-cost quote that matches
the catalog quote math (PROVIDER_MARKETPLACE_PLAN.md §5), so a route quote and a
catalog quote always agree.
"""

from __future__ import annotations

from typing import Any

from app.domains.catalog import policy as catalog_policy
from app.domains.routing.base import QuoteResult


def quote_from_price(price_version: Any, estimated_quantity: Any = None) -> QuoteResult:
    quantity = catalog_policy.estimate_quantity(
        getattr(price_version, "quote_rules", {}) or {}, estimated_quantity
    )
    max_cost = catalog_policy.stage_cost_micros(
        unit_price_micros=int(getattr(price_version, "unit_price_micros", 0) or 0),
        quantity_units=quantity,
        min_charge_micros=int(getattr(price_version, "min_charge_micros", 0) or 0),
        flat_fee_micros=int(getattr(price_version, "flat_fee_micros", 0) or 0),
    )
    return QuoteResult(
        max_cost_micros=max_cost,
        expires_at=catalog_policy.quote_expiry(),
        price_version_id=str(getattr(price_version, "id", "") or ""),
    )
