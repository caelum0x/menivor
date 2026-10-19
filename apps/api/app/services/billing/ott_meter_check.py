"""Check the Dodo OTT meter free thresholds against the plan caps (Wave Q QM1.0, P-M13).

:mod:`ott_usage` sends a Dodo meter the *included* usage of a metered
subscriber as well as any opted-in overage. That is only free when the Dodo
product's ``free_threshold`` for the meter equals the plan's allowance for the
billing cycle; a lower threshold bills creators for usage inside their plan.

Expected threshold per plan product ``plan_<key>_<interval>`` and meter:

* the monthly cap from :data:`ott_plans.PLAN_CAPS`, times 12 on yearly products
  (Dodo applies a free threshold per billing cycle);
* ``gb_stored`` is sent in GB-hours, so its threshold is the GB cap times the
  hours of the longest month (744), which keeps every month's included storage
  free.

Read only: it lists meters and reads products, and never writes to Dodo.

Usage (the owner runs it with the live key before ``OTT_PLANS_LIVE``)::

    DODO_API_KEY=... python -m app.services.billing.ott_meter_check --dodo

Exit status: 0 when every threshold matches, 1 on any mismatch or missing
meter, 2 when no key is configured.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional, Protocol, Sequence

from . import ott_plans
from .ott_usage import DODO_EVENTS

LONGEST_MONTH_HOURS = 31 * 24
INTERVALS = ("month", "year")
SOLD_PLANS = tuple(k for k in ott_plans.PLAN_CAPS if k != "free")
USER_AGENT = "menivor-ott-meter-check/1"


class DodoReader(Protocol):
    def list_all(self, path: str, query: Optional[dict] = None) -> list[dict]: ...
    def call(self, method: str, path: str, body: Any = None, query: Optional[dict] = None) -> Any: ...


def expected_threshold(plan: str, meter: str, interval: str) -> float:
    caps = ott_plans.PLAN_CAPS[plan]
    monthly = float(getattr(caps, meter))
    if meter == "gb_stored":
        monthly *= LONGEST_MONTH_HOURS
    return monthly * (12 if interval == "year" else 1)


def _meters_of(product: dict) -> list[dict]:
    price = product.get("price") or {}
    if isinstance(price, list):
        price = price[0] if price else {}
    return list(price.get("meters") or product.get("meters") or [])


def check(api: DodoReader) -> dict[str, Any]:
    """Compare every sold plan product's OTT meters with the caps; returns a report."""
    meter_ids = {m.get("event_name"): m.get("id") for m in api.list_all("/meters")}
    ids_to_meter = {meter_ids.get(event): meter for meter, event in DODO_EVENTS.items() if meter_ids.get(event)}
    products = {str((p.get("metadata") or {}).get("menivor_key") or ""): p for p in api.list_all("/products")}
    mismatches: list[dict[str, Any]] = []
    checked = 0
    for meter, event in DODO_EVENTS.items():
        if not meter_ids.get(event):
            mismatches.append({"product": "-", "meter": meter, "problem": f"no Dodo meter with event {event}"})
    for plan in SOLD_PLANS:
        for interval in INTERVALS:
            key = f"plan_{plan}_{interval}"
            summary = products.get(key)
            if summary is None:
                mismatches.append({"product": key, "meter": "-", "problem": "product not found"})
                continue
            detail = api.call("GET", f"/products/{summary.get('product_id')}") or {}
            found = {ids_to_meter.get(m.get("meter_id")): m for m in _meters_of(detail)}
            for meter in ott_plans.METERS:
                checked += 1
                want = expected_threshold(plan, meter, interval)
                attached = found.get(meter)
                if attached is None:
                    mismatches.append({"product": key, "meter": meter, "problem": "meter not attached",
                                       "expected": want})
                    continue
                try:
                    have = float(attached.get("free_threshold"))
                except (TypeError, ValueError):
                    have = None
                if have is None or abs(have - want) > 1e-6:
                    mismatches.append({"product": key, "meter": meter, "problem": "free threshold differs",
                                       "expected": want, "found": attached.get("free_threshold")})
    return {"ok": not mismatches, "checked": checked, "mismatches": mismatches}


class HttpDodo:
    """A read-only Dodo client (GET only)."""

    def __init__(self, base: str, key: str) -> None:
        self.base = base.rstrip("/")
        self.key = key

    def call(self, method: str, path: str, body: Any = None, query: Optional[dict] = None) -> Any:
        if method != "GET":
            raise ValueError("the meter check is read only")
        url = f"{self.base}{path}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
        req = urllib.request.Request(url, method="GET", headers={
            "Authorization": f"Bearer {self.key}", "Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https base
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"Dodo GET {path} failed: HTTP {exc.code}") from None
        return json.loads(raw) if raw else {}

    def list_all(self, path: str, query: Optional[dict] = None) -> list[dict]:
        items: list[dict] = []
        page = 0
        while True:
            data = self.call("GET", path, query={**(query or {}), "page_size": 100, "page_number": page})
            batch = data.get("items", []) if isinstance(data, dict) else data
            items.extend(batch or [])
            if not batch or len(batch) < 100:
                return items
            page += 1


def _setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    from . import dodo_client

    return {"DODO_API_KEY": dodo_client._value("api_key"),
            "DODO_BASE_URL": dodo_client.api_base() if dodo_client._value("api_key") else ""}.get(name, "")


def main(argv: Optional[Sequence[str]] = None, *, api: Optional[DodoReader] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--dodo", action="store_true", help="read meters and plan products from Dodo")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    if not args.dodo:
        parser.error("pass --dodo")
    if api is None:
        key = _setting("DODO_API_KEY")
        if not key:
            print("DODO_API_KEY is not set; nothing checked.")
            return 2
        api = HttpDodo(_setting("DODO_BASE_URL") or "https://live.dodopayments.com", key)
    report = check(api)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for row in report["mismatches"]:
            extra = f" (expected {row.get('expected')}, found {row.get('found')})" if "expected" in row else ""
            print(f"MISMATCH {row['product']} {row['meter']}: {row['problem']}{extra}")
        print(f"{'OK' if report['ok'] else 'FAIL'}: {report['checked']} thresholds checked, "
              f"{len(report['mismatches'])} problems")
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
