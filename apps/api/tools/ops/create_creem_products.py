#!/usr/bin/env python3
"""Create the Menivor Creem products (card check + credit packs).

Dry run by default: prints what it would create and the env lines to add.
``--apply`` calls ``POST /v1/products`` once per product and prints the
``CREEM_PRODUCT_ID_*`` lines for apps/api/.env. Never prints the API key.

The API key comes from ``CREEM_API_KEY`` in the environment, else from
apps/api/.env (read, never modified). A ``creem_test_`` key targets the Creem
test API automatically; ``CREEM_API_BASE_URL`` overrides the host.

Usage:
    python apps/api/tools/ops/create_creem_products.py
    python apps/api/tools/ops/create_creem_products.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _API_ROOT / ".env"

PROD_API = "https://api.creem.io"
TEST_API = "https://test-api.creem.io"
SUCCESS_URL = "https://menivor.com/billing?checkout=return"


@dataclass(frozen=True)
class Product:
    env: str
    name: str
    description: str
    price_cents: int


# Mirrors app/services/billing/plans.py (Starter 30 / $19, Pro 120 / $59) and
# app/services/billing/card_check.py ($1 credited as 1 reel). A unit test keeps
# these in sync.
PRODUCTS: tuple[Product, ...] = (
    Product(
        env="CREEM_PRODUCT_ID_CARD_CHECK",
        name="Menivor card check",
        description=(
            "One-time $1 card check. The $1 is added to your Menivor account as "
            "1 reel credit and unlocks your 3 free reels."
        ),
        price_cents=100,
    ),
    Product(
        env="CREEM_PRODUCT_ID_STARTER",
        name="Menivor Starter pack (30 reels)",
        description="30 reel credits for Menivor. 1 credit renders 1 reel. Credits never expire.",
        price_cents=1900,
    ),
    Product(
        env="CREEM_PRODUCT_ID_PRO",
        name="Menivor Pro pack (120 reels)",
        description="120 reel credits for Menivor. 1 credit renders 1 reel. Credits never expire.",
        price_cents=5900,
    ),
)


def _env_file_value(name: str) -> str:
    if not _ENV_FILE.is_file():
        return ""
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def _setting(name: str) -> str:
    return os.environ.get(name, "").strip() or _env_file_value(name)


def api_base(api_key: str) -> str:
    override = _setting("CREEM_API_BASE_URL").rstrip("/")
    if override:
        return override
    return TEST_API if api_key.startswith("creem_test_") else PROD_API


def product_body(product: Product, success_url: str = SUCCESS_URL) -> dict:
    return {
        "name": product.name,
        "description": product.description,
        "price": product.price_cents,
        "currency": "USD",
        "billing_type": "onetime",
        "tax_category": "saas",
        "default_success_url": success_url,
    }


def create_product(base: str, api_key: str, body: dict) -> str:
    request = urllib.request.Request(
        f"{base}/v1/products",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Creem sits behind Cloudflare, which blocks urllib's default UA (error 1010).
            "User-Agent": "menivor-ops/1.0 (+https://menivor.com)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Creem rejected {body['name']!r} (HTTP {exc.code}): {detail}") from exc
    product_id = str(payload.get("id") or "").strip()
    if not product_id:
        raise RuntimeError(f"Creem returned no product id for {body['name']!r}")
    return product_id


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
            body = product_body(product, args.success_url)
            print(f"[dry-run] would create {product.env}: {body['name']} "
                  f"${product.price_cents / 100:.2f} {body['billing_type']}")
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
