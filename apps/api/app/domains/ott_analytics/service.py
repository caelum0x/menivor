"""QoE analytics (MV12): first-party beacons in, hourly rollups, a dashboard whose totals match the raw counts.

* The player sends small batches of events (start with startup time,
  heartbeat with watched seconds, stall with its length, bitrate changes,
  errors, end). Values are clamped; unknown titles and events are dropped.
* A viewer is a salted hash of the channel session, account or device id
  (``OTT_ANALYTICS_SALT``): no email, IP or account id is stored.
* :func:`rollup` recomputes an hour from the raw rows (idempotent upsert), and
  :func:`dashboard` sums the rollups; :func:`raw_totals` is the check that the
  dashboard totals equal the raw beacon counts for the same window.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from app.domains.ott.models import STATUS_PUBLISHED, OttChannel, OttTitle

from .models import EVENTS, OttBeacon, OttQoeHourly

MAX_BATCH = 50
RAW_DAYS = 30
DEVICES = ("web", "ios", "android", "tv")
_SESSION = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
LIMITS = {"watched_s": (0.0, 60.0), "startup_ms": (0, 120_000), "stall_ms": (0, 600_000),
          "bitrate_kbps": (0, 100_000)}


def now() -> datetime:
    return datetime.now(timezone.utc)


def hour_key(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")


def _salt() -> bytes:
    value = (os.getenv("OTT_ANALYTICS_SALT") or "").strip()
    if not value:
        from app.domains.ott_access import tokens

        value = hashlib.sha256(b"ott-analytics:" + tokens._secret()).hexdigest()
    return value.encode()


def viewer_hash(identity: str) -> str:
    return hashlib.sha256(_salt() + str(identity).encode()).hexdigest()[:32]


def _clamp(name: str, raw: Any) -> float:
    low, high = LIMITS[name]
    try:
        value = float(raw or 0)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, value))


def ingest(session: Session, events: Iterable[Mapping[str, Any]], *, identity: str, country: str = "XX",
           at: Optional[datetime] = None) -> int:
    """Store a batch of beacons; returns how many were accepted."""
    moment = at or now()
    hour = hour_key(moment)
    who = viewer_hash(identity)
    titles: dict[str, Optional[OttTitle]] = {}
    accepted = 0
    for raw in list(events)[:MAX_BATCH]:
        event = str(raw.get("event") or "")
        session_id = str(raw.get("session_id") or "")
        title_id = str(raw.get("title_id") or "")[:32]
        if event not in EVENTS or not _SESSION.match(session_id):
            continue
        if title_id not in titles:
            titles[title_id] = session.get(OttTitle, title_id)
        title = titles[title_id]
        if title is None or title.status != STATUS_PUBLISHED:
            continue
        device = str(raw.get("device") or "web")
        session.add(OttBeacon(
            channel_id=title.channel_id, title_id=title.id, session_id=session_id, viewer_hash=who, event=event,
            hour=hour, watched_s=_clamp("watched_s", raw.get("watched_s")),
            startup_ms=int(_clamp("startup_ms", raw.get("startup_ms"))),
            stall_ms=int(_clamp("stall_ms", raw.get("stall_ms"))),
            bitrate_kbps=int(_clamp("bitrate_kbps", raw.get("bitrate_kbps"))),
            error_code=re.sub(r"[^A-Za-z0-9_.-]", "", str(raw.get("error_code") or ""))[:40],
            device=device if device in DEVICES else "web", country=(country or "XX")[:2].upper(),
            received_at=moment))
        accepted += 1
    session.flush()
    return accepted


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return int(ordered[index])


def rollup(session: Session, hour: str) -> int:
    """Recompute every title's row for ``hour`` from the raw beacons; returns rows written."""
    by_title: dict[str, list[OttBeacon]] = defaultdict(list)
    for beacon in session.execute(select(OttBeacon).where(OttBeacon.hour == hour)).scalars():
        by_title[beacon.title_id].append(beacon)
    for title_id, rows in by_title.items():
        starts = [b for b in rows if b.event == "start"]
        stalls = [b for b in rows if b.event == "stall"]
        startup = [b.startup_ms for b in starts if b.startup_ms > 0]
        row = session.execute(select(OttQoeHourly).where(OttQoeHourly.title_id == title_id,
                                                         OttQoeHourly.hour == hour)).scalar_one_or_none()
        if row is None:
            row = OttQoeHourly(channel_id=rows[0].channel_id, title_id=title_id, hour=hour)
            session.add(row)
        row.plays = len(starts)
        row.viewers = len({b.viewer_hash for b in rows})
        row.watch_s = round(sum(b.watched_s for b in rows), 3)
        row.startup_p50_ms = _percentile(startup, 0.5)
        row.startup_p95_ms = _percentile(startup, 0.95)
        row.stalls = len(stalls)
        row.stall_ms = sum(b.stall_ms for b in stalls)
        row.errors = sum(1 for b in rows if b.event == "error")
        row.beacons = len(rows)
    session.flush()
    return len(by_title)


def _window(days: int, at: Optional[datetime]) -> str:
    return hour_key((at or now()) - timedelta(days=max(1, min(days, 90))))


def dashboard(session: Session, channel: OttChannel, *, days: int = 7, at: Optional[datetime] = None
              ) -> dict[str, Any]:
    since = _window(days, at)
    rows = session.execute(select(OttQoeHourly).where(OttQoeHourly.channel_id == channel.id,
                                                      OttQoeHourly.hour >= since)).scalars().all()
    titles = {t.id: t.title for t in session.execute(select(OttTitle).where(OttTitle.channel_id == channel.id))
              .scalars()}
    per_title: dict[str, dict[str, Any]] = {}
    per_day: dict[str, dict[str, float]] = defaultdict(lambda: {"plays": 0, "watch_minutes": 0.0})
    for row in rows:
        entry = per_title.setdefault(row.title_id, {"title_id": row.title_id, "title": titles.get(row.title_id, ""),
                                                    "plays": 0, "watch_minutes": 0.0, "stalls": 0, "errors": 0,
                                                    "startup_p95_ms": 0})
        entry["plays"] += row.plays
        entry["watch_minutes"] = round(entry["watch_minutes"] + row.watch_s / 60, 2)
        entry["stalls"] += row.stalls
        entry["errors"] += row.errors
        entry["startup_p95_ms"] = max(entry["startup_p95_ms"], row.startup_p95_ms)
        day = per_day[row.hour[:10]]
        day["plays"] += row.plays
        day["watch_minutes"] = round(day["watch_minutes"] + row.watch_s / 60, 2)
    totals = {"plays": sum(r.plays for r in rows), "watch_minutes": round(sum(r.watch_s for r in rows) / 60, 2),
              "stalls": sum(r.stalls for r in rows), "errors": sum(r.errors for r in rows),
              "beacons": sum(r.beacons for r in rows)}
    viewers = session.execute(select(func.count(distinct(OttBeacon.viewer_hash))).where(
        OttBeacon.channel_id == channel.id, OttBeacon.hour >= since)).scalar_one()
    sales = sales_by_title(session, channel, days=days, at=at)
    return {"days": days, "totals": {**totals, "viewers": int(viewers or 0)},
            "sales": sales, "sales_totals": sales_totals(sales),
            "titles": sorted(per_title.values(), key=lambda t: -t["plays"]),
            "daily": [{"day": d, **v} for d, v in sorted(per_day.items())],
            "source": "first-party player beacons"}


#: Grants that a refund or a dispute took back are not sales.
UNSOLD_REASONS = ("refund", "dispute")


def sales_by_title(session: Session, channel: OttChannel, *, days: int = 30, at: Optional[datetime] = None
                   ) -> list[dict[str, Any]]:
    """Gross sales per title from grant events (QM1.3): each grant counts at the list price it was granted at.

    Only grant rows are read (``ott_entitlements`` written by Mint's
    ``entitlement.granted``). A grant later refunded or disputed is not a sale.
    The numbers are what buyers were charged on the creator's own processor;
    no Menivor ledger holds or forwards those funds.
    """
    from app.domains.ott_commerce.models import KIND_SVOD, REVOKED, OttEntitlement, OttOffer

    since = (at or now()) - timedelta(days=max(1, min(days, 90)))
    titles = session.execute(select(OttTitle).where(OttTitle.channel_id == channel.id)
                             .order_by(OttTitle.position)).scalars().all()
    rows: dict[str, dict[str, Any]] = {t.id: {"title_id": t.id, "title": t.title, "gross_cents": 0, "grants": 0,
                                              "currency": "USD"} for t in titles}
    grants = session.execute(select(OttEntitlement, OttOffer).join(OttOffer, OttOffer.id == OttEntitlement.offer_id)
                             .where(OttEntitlement.channel_id == channel.id, OttEntitlement.kind != KIND_SVOD,
                                    OttEntitlement.granted_at >= since)).all()
    for ent, offer in grants:
        if ent.status == REVOKED and ent.revoked_reason in UNSOLD_REASONS:
            continue
        entry = rows.get(ent.title_id or "")
        if entry is None:
            continue
        # The list price snapshotted at grant time; rows from before the snapshot
        # column fall back to the offer's current price.
        cents = int(ent.list_price_cents if ent.list_price_cents is not None else offer.price_cents)
        currency = ent.list_currency or offer.currency
        entry["gross_cents"] += cents
        entry["grants"] += 1
        by_currency = entry.setdefault("by_currency", {})
        by_currency[currency] = by_currency.get(currency, 0) + cents
        entry["currency"] = currency if len(by_currency) == 1 else "mixed"
    return sorted(rows.values(), key=lambda r: -r["gross_cents"])


def sales_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    currencies = {r["currency"] for r in rows if r["grants"]} or {"USD"}
    return {"gross_cents": sum(r["gross_cents"] for r in rows), "grants": sum(r["grants"] for r in rows),
            "currency": currencies.pop() if len(currencies) == 1 else "mixed"}


def raw_totals(session: Session, channel: OttChannel, *, days: int = 7, at: Optional[datetime] = None
               ) -> dict[str, Any]:
    since = _window(days, at)
    base = select(OttBeacon).where(OttBeacon.channel_id == channel.id, OttBeacon.hour >= since)
    rows = session.execute(base).scalars().all()
    return {"plays": sum(1 for b in rows if b.event == "start"),
            "watch_minutes": round(sum(b.watched_s for b in rows) / 60, 2),
            "stalls": sum(1 for b in rows if b.event == "stall"),
            "errors": sum(1 for b in rows if b.event == "error"), "beacons": len(rows)}


def sweep(session: Session, *, at: Optional[datetime] = None) -> int:
    cutoff = (at or now()) - timedelta(days=RAW_DAYS)
    result = session.execute(delete(OttBeacon).where(OttBeacon.received_at < cutoff))
    return int(result.rowcount or 0)


__all__ = ["MAX_BATCH", "UNSOLD_REASONS", "dashboard", "sales_by_title", "sales_totals", "hour_key", "ingest", "raw_totals", "rollup", "sweep", "viewer_hash"]
