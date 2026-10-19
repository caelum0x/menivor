#!/usr/bin/env python3
"""Create the Menivor monthly-plan Creem products (Creator / Pro / Agency).

Dry run by default: prints the six recurring products it would create (each plan
monthly and annual) and the env lines to add. ``--apply`` calls
``POST /v1/products`` once per product and prints the
``CREEM_PRODUCT_ID_PLAN_*`` lines for apps/api/.env. Never prints the API key
and never edits any env file.

Prices and reels mirror app/services/billing/creator_plans.py (a unit test keeps
them in sync). Annual = 10x monthly (two months free).

Usage:
    python apps/api/tools/ops/create_creem_subscription_products.py
    python apps/api/tools/ops/create_creem_subscription_products.py --apply
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_creem_products import (  # noqa: E402
    PROD_API,
    _setting,
    api_base,
    create_product,
)

SUCCESS_URL = "https://menivor.com/billing?checkout=return"
YEARLY_MONTHS_CHARGED = 10


@dataclass(frozen=True)
class RecurringProduct:
    env: str
    name: str
    description: str
    price_cents: int
    billing_period: str  # every-month | every-year


# (key, display name, monthly USD cents, reels per month) — mirrors creator_plans.
PLANS: tuple[tuple[str, str, int, int], ...] = (
    ("creator", "Creator", 1500, 35),
    ("pro", "Pro", 3900, 100),
    ("agency", "Agency", 9900, 300),
)


def _products() -> tuple[RecurringProduct, ...]:
    rows: list[RecurringProduct] = []
    for key, name, monthly_cents, reels in PLANS:
        rows.append(
            RecurringProduct(
                env=f"CREEM_PRODUCT_ID_PLAN_{key.upper()}_MONTH",
                name=f"Menivor {name} (monthly)",
                description=(
                    f"{reels} reels every month, renews monthly. Included reels are used "
                    "first and do not roll over. Cancel anytime; you keep your reels "
                    "until the end of the paid month."
                ),
                price_cents=monthly_cents,
                billing_period="every-month",
            )
        )
        rows.append(
            RecurringProduct(
                env=f"CREEM_PRODUCT_ID_PLAN_{key.upper()}_YEAR",
                name=f"Menivor {name} (annual)",
                description=(
                    f"{reels * 12} reels for the year, added at the start of each paid year; "
                    "renews yearly. Two months free versus monthly. Unused reels do not roll "
                    "over to the next year. Cancel anytime."
                ),
                price_cents=monthly_cents * YEARLY_MONTHS_CHARGED,
                billing_period="every-year",
            )
        )
    return tuple(rows)


PRODUCTS: tuple[RecurringProduct, ...] = _products()


def product_body(product: RecurringProduct, success_url: str = SUCCESS_URL) -> dict:
    return {
        "name": product.name,
        "description": product.description,
        "price": product.price_cents,
        "currency": "USD",
        "billing_type": "recurring",
        "billing_period": product.billing_period,
        "tax_category": "saas",
        "default_success_url": success_url,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="create the products (default: dry run)")
    parser.add_argument("--success-url", default=SUCCESS_URL, help="default_success_url for each product")
    args = parser.parse_args(argv)

    api_key = _setting("CREEM_API_KEY")
    base = api_base(api_key) if api_key else PROD_API
    print(f"Creem API: {base} ({'key found' if api_key else 'CREEM_API_KEY not set'})")

    if not args.apply:
        for product in PRODUCTS:
            print(
                f"[dry-run] would create {product.env}: {product.name} "
                f"${product.price_cents / 100:.2f} recurring {product.billing_period}"
            )
        print("Re-run with --apply to create them.")
        return 0

    if not api_key:
        print("CREEM_API_KEY is not set (env or apps/api/.env).", file=sys.stderr)
        return 2

    lines: list[str] = []
    for product in PRODUCTS:
        product_id = create_product(base, api_key, product_body(product, args.success_url))
        print(f"created {product.name}: {product_id}")
        lines.append(f"{product.env}={product_id}")
    print("\nAdd to apps/api/.env:")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
