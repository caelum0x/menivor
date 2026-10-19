#!/usr/bin/env python3
"""Create the Menivor Dodo Payments catalog (idempotent, dry run by default).

Creates, under the Menivor brand:

* meters ``reel.rendered`` (count, "reels") and ``video.seconds`` (sum of
  ``seconds``, "seconds");
* one-time products: $1 card check, Starter $19 (30 reels), Pro $59 (120 reels);
* monthly + yearly personal plans (Creator / Pro / Agency) as usage-based
  subscriptions: fixed price + ``reel.rendered`` with the plan's included reels
  as the free threshold and an overage per reel at or below price / included;
* optionally the webhook endpoint (``--webhook-url``), writing its signing
  secret to ``--secret-out`` (mode 600). The secret is never printed.

Existing objects are matched (products by ``metadata.menivor_key``, meters by
``event_name``, webhooks by URL) and reused, so re-running is safe. Prints the
``DODO_PRODUCT_ID_*`` env lines. The API key comes from ``DODO_API_KEY`` (env
or apps/api/.env) and is never printed.

Usage:
    python apps/api/tools/ops/create_dodo_products.py
    DODO_API_KEY=... python apps/api/tools/ops/create_dodo_products.py --apply \
        --webhook-url https://api.menivor.com/api/v1/billing/webhook/dodo \
        --secret-out ~/.rally-secrets/dodo_webhook_secret
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_API_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _API_ROOT / ".env"

LIVE_API = "https://live.dodopayments.com"
TEST_API = "https://test.dodopayments.com"
USER_AGENT = "menivor-ops/1.0 (+https://menivor.com)"
DEFAULT_BRAND = "brnd_0NoS6i9MIPHoJtCHgJWRE"
TAX_CATEGORY = "saas"
REEL_EVENT = "reel.rendered"
SECONDS_EVENT = "video.seconds"
SUBSCRIPTION_YEARS = 10  # total subscription length; renews every period

# Locked catalog (mirrors app/services/billing/plans.py, card_check.py and
# creator_plans.py; tests/reelforge/test_dodo_products_script.py keeps them in sync).
PACKS: tuple[tuple[str, str, str, int, int], ...] = (
    # (menivor_key, env suffix, name, price cents, reels)
    ("card_check", "CARD_CHECK", "Menivor card check", 100, 1),
    ("starter", "STARTER", "Menivor Starter pack (30 reels)", 1900, 30),
    ("pro", "PRO", "Menivor Pro pack (120 reels)", 5900, 120),
)
PLANS: tuple[tuple[str, str, int, int], ...] = (
    # (plan key, display name, monthly price cents, reels per month)
    ("creator", "Creator", 1500, 35),
    ("pro", "Pro", 3900, 100),
    ("agency", "Agency", 9900, 300),
)
YEARLY_MONTHS_CHARGED = 10


@dataclass(frozen=True)
class ProductSpec:
    key: str
    env: str
    name: str
    description: str
    price: dict[str, Any]
    metadata: dict[str, str] = field(default_factory=dict)


def overage_cents_per_reel(price_cents: int, included: int) -> str:
    """Honest overage: price / included reels, rounded DOWN to the cent."""
    value = math.floor(price_cents * 100 / included) / 100
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _dollars(cents: str) -> str:
    return f"{float(cents) / 100:.4f}".rstrip("0").rstrip(".")


def pack_specs() -> list[ProductSpec]:
    specs = []
    for key, suffix, name, cents, reels in PACKS:
        if key == "card_check":
            description = (
                "One-time $1 card check. The $1 is added to your Menivor account as "
                "1 reel credit and unlocks your 3 free reels."
            )
        else:
            description = f"{reels} reel credits for Menivor. 1 credit renders 1 reel. Credits never expire."
        specs.append(
            ProductSpec(
                key=key,
                env=f"DODO_PRODUCT_ID_{suffix}",
                name=name,
                description=description,
                price={"type": "one_time_price", "price": cents, "currency": "USD",
                       "discount": 0, "purchasing_power_parity": False, "tax_inclusive": False},
                metadata={"menivor_key": key, "credits": str(reels)},
            )
        )
    return specs


def plan_specs(reel_meter_id: str) -> list[ProductSpec]:
    specs = []
    for key, display, monthly_cents, reels in PLANS:
        for interval in ("month", "year"):
            cents = monthly_cents if interval == "month" else monthly_cents * YEARLY_MONTHS_CHARGED
            included = reels if interval == "month" else reels * 12
            overage = overage_cents_per_reel(cents, included)
            label = "monthly" if interval == "month" else "yearly"
            specs.append(
                ProductSpec(
                    key=f"plan_{key}_{interval}",
                    env=f"DODO_PRODUCT_ID_PLAN_{key.upper()}_{interval.upper()}",
                    name=f"Menivor {display} plan ({label})",
                    description=(
                        f"{included} reels included per {interval}; extra reels "
                        f"${_dollars(overage)} each. Cancel any time."
                    ),
                    price={
                        "type": "usage_based_price",
                        "fixed_price": cents,
                        "currency": "USD",
                        "discount": 0,
                        "purchasing_power_parity": False,
                        "tax_inclusive": False,
                        "payment_frequency_count": 1,
                        "payment_frequency_interval": "Month" if interval == "month" else "Year",
                        "subscription_period_count": SUBSCRIPTION_YEARS,
                        "subscription_period_interval": "Year",
                        "meters": [
                            {"meter_id": reel_meter_id, "free_threshold": included, "price_per_unit": overage}
                        ],
                    },
                    metadata={"menivor_key": f"plan_{key}_{interval}", "included_reels": str(included)},
                )
            )
    return specs


METERS: tuple[dict[str, Any], ...] = (
    {"name": "Reels rendered", "event_name": REEL_EVENT, "measurement_unit": "reels",
     "aggregation": {"type": "count"}, "description": "One event per successfully rendered reel."},
    {"name": "Video seconds", "event_name": SECONDS_EVENT, "measurement_unit": "seconds",
     "aggregation": {"type": "sum", "key": "seconds"}, "description": "Rendered video length in seconds."},
)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _env_file_value(name: str) -> str:
    if not _ENV_FILE.is_file():
        return ""
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _setting(name: str) -> str:
    return os.environ.get(name, "").strip() or _env_file_value(name)


class Api:
    def __init__(self, base: str, key: str) -> None:
        self.base = base.rstrip("/")
        self.key = key

    def call(self, method: str, path: str, body: Any = None, query: dict | None = None) -> Any:
        url = f"{self.base}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.key}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise SystemExit(f"Dodo {method} {path} failed: HTTP {exc.code}: {detail}") from None
        return json.loads(raw) if raw else {}

    def list_all(self, path: str, query: dict | None = None) -> list[dict]:
        items: list[dict] = []
        page = 0
        while True:
            data = self.call("GET", path, query={**(query or {}), "page_size": 100, "page_number": page})
            batch = data.get("items", []) if isinstance(data, dict) else data
            items.extend(batch or [])
            if not batch or len(batch) < 100:
                return items
            page += 1


def ensure_meters(api: Api | None) -> dict[str, str]:
    existing = {m.get("event_name"): m.get("id") for m in (api.list_all("/meters") if api else [])}
    out = {}
    for meter in METERS:
        name = meter["event_name"]
        if existing.get(name):
            print(f"meter {name}: exists ({existing[name]})")
            out[name] = existing[name]
        elif api is None:
            print(f"meter {name}: would create {json.dumps(meter)}")
            out[name] = "<meter id>"
        else:
            out[name] = api.call("POST", "/meters", meter)["id"]
            print(f"meter {name}: created ({out[name]})")
    return out


def ensure_products(api: Api | None, brand: str, specs: list[ProductSpec]) -> dict[str, str]:
    existing: dict[str, str] = {}
    if api is not None:
        for item in api.list_all("/products", {"brand_id": brand}):
            key = (item.get("metadata") or {}).get("menivor_key")
            if key:
                existing[key] = item["product_id"]
    env: dict[str, str] = {}
    for spec in specs:
        if spec.key in existing:
            env[spec.env] = existing[spec.key]
            print(f"{spec.key}: exists ({existing[spec.key]})")
            continue
        body = {"name": spec.name, "description": spec.description, "tax_category": TAX_CATEGORY,
                "price": spec.price, "brand_id": brand, "metadata": spec.metadata}
        if api is None:
            print(f"{spec.key}: would create {json.dumps(body)}")
            env[spec.env] = "<product id>"
            continue
        product_id = api.call("POST", "/products", body)["product_id"]
        env[spec.env] = product_id
        print(f"{spec.key}: created ({product_id})")
    return env


def ensure_webhook(api: Api, url: str, secret_out: Path) -> str:
    hooks = api.list_all("/webhooks")
    hook = next((h for h in hooks if h.get("url") == url), None)
    if hook is None:
        hook = api.call("POST", "/webhooks", {"url": url, "description": "Menivor API"})
        print(f"webhook: created ({hook['id']}) -> {url}")
    else:
        print(f"webhook: exists ({hook['id']}) -> {url}")
    secret = api.call("GET", f"/webhooks/{hook['id']}/secret")["secret"]
    secret_out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(secret_out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(secret)
    print(f"webhook signing secret written to {secret_out} (not printed)")
    return hook["id"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="create objects (default: dry run)")
    parser.add_argument("--brand-id", default=os.environ.get("DODO_BRAND_ID", DEFAULT_BRAND))
    parser.add_argument("--test", action="store_true", help="use the test-mode API host")
    parser.add_argument("--webhook-url", default="", help="register this webhook endpoint")
    parser.add_argument("--secret-out", default="", help="file for the webhook signing secret")
    args = parser.parse_args(argv)

    base = TEST_API if args.test else (_setting("DODO_API_BASE_URL") or LIVE_API)
    key = _setting("DODO_API_KEY")
    if args.apply and not key:
        print("DODO_API_KEY is not set (env or apps/api/.env).", file=sys.stderr)
        return 2
    api = Api(base, key) if args.apply else None
    print(f"{'APPLY' if api else 'DRY RUN'} against {base} brand={args.brand_id}")

    meters = ensure_meters(api)
    env = ensure_products(api, args.brand_id, pack_specs())
    env.update(ensure_products(api, args.brand_id, plan_specs(meters[REEL_EVENT])))
    if args.webhook_url:
        if api is None:
            print(f"webhook: would register {args.webhook_url}")
        else:
            if not args.secret_out:
                print("--secret-out is required with --webhook-url", file=sys.stderr)
                return 2
            ensure_webhook(api, args.webhook_url, Path(args.secret_out).expanduser())

    print("\n# env lines for /etc/products/menivor.env")
    for name, value in env.items():
        print(f"{name}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
