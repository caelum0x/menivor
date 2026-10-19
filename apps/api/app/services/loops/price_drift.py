"""Weekly provider price drift check for the media catalog (MH0, Wave D).

Every catalog row (``media_catalog.all_rows()``) carries a ``price_source`` and a
``price_date``. Once a week this module reads the live list price for every row
it can read automatically and compares it with ``price_micros``:

* fal.ai rows (``kling-fal`` / ``fal-image``) are read from fal's platform
  pricing API (``GET https://api.fal.ai/v1/models/pricing?endpoint_id=...``,
  ``Authorization: Key $FAL_KEY``). The call is free; it needs ``FAL_KEY``.
* Other vendors publish no pricing API. Their rows are listed as ``manual`` in
  the report with the source URL, so the owner can check them by hand. A
  sellable row among them whose price was never verified is ``unverified`` and
  fails the check (QM1.1), so nothing is sold on an unread price.

A row whose live price differs from the catalog price by more than
``DRIFT_THRESHOLD`` (10%) is flagged ``drift``. A live price in a unit we cannot
convert (for example "per 5 s video") is flagged ``unit_mismatch`` for a human
look instead of being guessed. When anything is flagged, one owner alert goes to
the Menivor ntfy topic (same channel as the M1.5 render alerts).

The check never edits prices: a price change is a reviewed catalog commit that
updates ``price_micros``, ``price_date`` and ``price_verified`` together.

(This file sits in ``services/loops`` because the Wave D dispatch names that
path; the other modules here are about looping video, not scheduled loops.)
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping

from loguru import logger

DRIFT_THRESHOLD = 0.10
FAL_PRICING_URL = "https://api.fal.ai/v1/models/pricing"
FAL_BATCH = 50  # the pricing API accepts 1-50 endpoint ids per call
FAL_PROVIDERS = frozenset({"kling-fal", "fal-image"})
TASK_NAME = "app.services.loops.price_drift.price_drift_weekly_task"

# Live units that convert straight to a catalog unit, with the factor that turns
# one live unit's USD price into USD per catalog unit.
_UNIT_FACTORS: dict[tuple[str, str], float] = {
    ("second", "second"): 1.0,
    ("seconds", "second"): 1.0,
    ("minute", "second"): 1.0 / 60.0,
    ("minutes", "second"): 1.0 / 60.0,
    ("image", "image"): 1.0,
    ("images", "image"): 1.0,
    ("megapixel", "image"): 1.0,  # catalog image rows are priced at the 1 MP default size
    ("megapixels", "image"): 1.0,
    ("megapixel", "megapixel"): 1.0,
    ("megapixels", "megapixel"): 1.0,
}

# Result statuses.
OK = "ok"
DRIFT = "drift"
UNIT_MISMATCH = "unit_mismatch"
MISSING = "missing"          # the source API returned no price for this endpoint
MANUAL = "manual"            # no pricing API for this vendor; check the source URL by hand
UNREADABLE = "unreadable"    # the source API call failed (no key, HTTP error)
UNVERIFIED = "unverified"    # QM1.1: a sellable row whose price nobody has verified at the source


@dataclass(frozen=True)
class LivePrice:
    endpoint_id: str
    unit_price_usd: float
    unit: str
    currency: str = "USD"


@dataclass(frozen=True)
class DriftResult:
    model_id: str
    status: str
    catalog_micros: int
    live_micros: int | None = None
    delta_pct: float | None = None
    unit: str = ""
    live_unit: str = ""
    price_source: str = ""
    note: str = ""


PricingFetch = Callable[[list[str]], dict[str, LivePrice]]


def fal_endpoint(model: Any) -> str:
    """The fal endpoint id for a fal-hosted catalog row (aliases resolved)."""
    from app.domains.gateway.media_catalog import _KLING_ALIAS_PATHS

    return _KLING_ALIAS_PATHS.get(model.model_ref, model.model_ref)


def to_catalog_micros(live: LivePrice, catalog_unit: str) -> int | None:
    """Convert a live price to integer micro-USD per catalog unit, or None when not convertible."""
    if (live.currency or "USD").upper() != "USD":
        return None
    factor = _UNIT_FACTORS.get((str(live.unit or "").strip().lower(), catalog_unit))
    if factor is None:
        return None
    return int(round(float(live.unit_price_usd) * factor * 1_000_000))


def compare(model: Any, live: LivePrice | None) -> DriftResult:
    """Compare one catalog row with its live price (pure)."""
    base = dict(
        model_id=model.id, catalog_micros=int(model.price_micros), unit=model.unit,
        price_source=model.price_source,
    )
    if live is None:
        return DriftResult(status=MISSING, note="no live price returned for this endpoint", **base)
    live_micros = to_catalog_micros(live, model.unit)
    if live_micros is None:
        return DriftResult(
            status=UNIT_MISMATCH, live_unit=live.unit,
            note=f"live price {live.unit_price_usd} {live.currency} per {live.unit}; check by hand",
            **base,
        )
    catalog = int(model.price_micros)
    if catalog <= 0:
        delta = 1.0 if live_micros > 0 else 0.0
    else:
        delta = (live_micros - catalog) / catalog
    status = DRIFT if abs(delta) > DRIFT_THRESHOLD else OK
    return DriftResult(
        status=status, live_micros=live_micros, delta_pct=round(delta * 100.0, 1),
        live_unit=live.unit, **base,
    )


def fal_pricing_fetch(
    *, api_key: str | None = None, get: Callable[..., Any] | None = None, timeout_s: float = 20.0
) -> PricingFetch:
    """A fetcher for fal's pricing API. Raises RuntimeError without ``FAL_KEY``."""
    key = api_key if api_key is not None else os.getenv("FAL_KEY", "")
    if not key:
        raise RuntimeError("FAL_KEY is not set; fal prices cannot be read")

    def _get(url: str, params: list[tuple[str, str]]) -> dict:
        if get is not None:
            return get(url, params)
        import requests

        resp = requests.get(url, params=params, headers={"Authorization": f"Key {key}"}, timeout=timeout_s)
        resp.raise_for_status()
        return resp.json()

    def fetch(endpoint_ids: list[str]) -> dict[str, LivePrice]:
        out: dict[str, LivePrice] = {}
        for i in range(0, len(endpoint_ids), FAL_BATCH):
            batch = endpoint_ids[i:i + FAL_BATCH]
            cursor: str | None = None
            while True:
                params = [("endpoint_id", e) for e in batch]
                if cursor:
                    params.append(("cursor", cursor))
                body = _get(FAL_PRICING_URL, params) or {}
                for row in body.get("prices") or []:
                    try:
                        lp = LivePrice(
                            endpoint_id=str(row["endpoint_id"]),
                            unit_price_usd=float(row["unit_price"]),
                            unit=str(row.get("unit") or ""),
                            currency=str(row.get("currency") or "USD"),
                        )
                    except (KeyError, TypeError, ValueError):
                        logger.warning(f"price drift: skipped malformed fal price row {row!r}")
                        continue
                    out[lp.endpoint_id] = lp
                cursor = body.get("next_cursor") if body.get("has_more") else None
                if not cursor:
                    break
        return out

    return fetch


def check(
    rows: Iterable[Any] | None = None,
    *,
    fal_fetch: PricingFetch | None = None,
) -> list[DriftResult]:
    """Check every row. ``fal_fetch`` defaults to the live fal pricing API."""
    from app.domains.gateway.media_catalog import all_rows

    rows = list(all_rows() if rows is None else rows)
    fal_rows = [m for m in rows if m.provider in FAL_PROVIDERS]
    results: list[DriftResult] = []

    live: dict[str, LivePrice] | None = None
    fetch_error = ""
    if fal_rows:
        try:
            fetch = fal_fetch or fal_pricing_fetch()
            live = fetch(sorted({fal_endpoint(m) for m in fal_rows}))
        except Exception as exc:  # noqa: BLE001 - one bad call is reported, never crashes the tick
            fetch_error = str(exc)
            logger.error(f"price drift: fal pricing read failed: {exc}")

    for m in rows:
        if m.provider in FAL_PROVIDERS:
            if live is None:
                results.append(DriftResult(
                    model_id=m.id, status=UNREADABLE, catalog_micros=int(m.price_micros), unit=m.unit,
                    price_source=m.price_source, note=fetch_error,
                ))
            else:
                results.append(compare(m, live.get(fal_endpoint(m))))
        elif not m.price_verified and _sellable(m.id):
            # QM1.1: a row we charge for must have a verified price; no pricing API can confirm this one.
            results.append(DriftResult(
                model_id=m.id, status=UNVERIFIED, catalog_micros=int(m.price_micros), unit=m.unit,
                price_source=m.price_source, note="sellable row without a verified price; read the source",
            ))
        else:
            results.append(DriftResult(
                model_id=m.id, status=MANUAL, catalog_micros=int(m.price_micros), unit=m.unit,
                price_source=m.price_source, note="no vendor pricing API; check the source by hand",
            ))
    return results


def _sellable(model_id: str) -> bool:
    from app.domains.routing.license_class import is_model_sellable

    return is_model_sellable(model_id)


def summarize(results: Iterable[DriftResult]) -> dict[str, Any]:
    results = list(results)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    flagged = [asdict(r) for r in results if r.status in (DRIFT, UNIT_MISMATCH, MISSING, UNREADABLE, UNVERIFIED)]
    return {"counts": counts, "flagged": flagged, "rows": len(results)}


def alert_for(summary: Mapping[str, Any]) -> Any | None:
    """The owner alert for a summary, or None when nothing needs a look."""
    from app.domains.observability.render_metrics import Alert

    flagged = summary.get("flagged") or []
    if not flagged:
        return None
    drift = [f for f in flagged if f["status"] == DRIFT]
    lines = [
        f"{f['model_id']}: catalog {f['catalog_micros']} vs live {f['live_micros']} micros/{f['unit']} "
        f"({f['delta_pct']:+.1f}%)"
        for f in drift[:15]
    ]
    others = [f for f in flagged if f["status"] != DRIFT]
    if others:
        lines.append(f"{len(others)} row(s) need a hand check (unit mismatch, missing, unreadable or "
                     "a sellable price never verified).")
    return Alert(
        key="menivor-price-drift",
        title=f"Menivor catalog price drift: {len(drift)} row(s) over {int(DRIFT_THRESHOLD * 100)}%",
        message="\n".join(lines) or "Price check needs a look.",
        priority="default",
    )


def run(*, fal_fetch: PricingFetch | None = None, send: Callable[[Any], Any] | None = None) -> dict[str, Any]:
    """One weekly pass: check, log, and alert the owner when something is flagged."""
    summary = summarize(check(fal_fetch=fal_fetch))
    logger.info(f"price drift: {summary['counts']}")
    alert = alert_for(summary)
    if alert is not None:
        if send is None:
            from app.domains.observability.render_metrics import send_ntfy as send
        summary["alerted"] = bool(send(alert))
    return summary


# --------------------------------------------------------------------------- #
# Celery wiring (registered through celery_app._OPTIONAL_TASK_MODULES)
# --------------------------------------------------------------------------- #
def _celery_task():
    from celery.schedules import crontab

    from app.workers.celery_app import celery_app

    @celery_app.task(name=TASK_NAME)
    def price_drift_weekly_task() -> dict[str, Any]:
        try:
            return run()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"price drift tick failed: {exc}")
            return {"status": "error", "error": str(exc)}

    # Mondays 06:40 UTC, ahead of the owner's weekly funnel email.
    return price_drift_weekly_task, {
        "menivor-price-drift-weekly": {"task": TASK_NAME, "schedule": crontab(minute=40, hour=6, day_of_week="mon")},
    }


price_drift_weekly_task, BEAT_SCHEDULE = _celery_task()


def _ensure_beat() -> None:
    """Add the weekly entry when this module was imported before ``celery_app``.

    ``celery_app`` collects ``BEAT_SCHEDULE`` from its optional modules while it
    loads; if this module started that load, it was still half-imported then.
    """
    from app.workers import celery_app as ca

    missing = {k: v for k, v in BEAT_SCHEDULE.items() if k not in ca.celery_app.conf.beat_schedule}
    if missing:
        ca.celery_app.conf.beat_schedule.update(ca.housekeeping_beat(missing))


_ensure_beat()

__all__ = [
    "BEAT_SCHEDULE", "DRIFT_THRESHOLD", "DriftResult", "LivePrice", "alert_for", "check", "compare",
    "fal_pricing_fetch", "price_drift_weekly_task", "run", "summarize", "to_catalog_micros",
]
