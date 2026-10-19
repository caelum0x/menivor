"""Per-network evidence from data Menivor already has (plus optional manual rows).

Paid networks (Meta, TikTok) come from the lifetime stats each campaign's
last sync stored under ``AdVariant.spec['paid_ads']``. Networks with no API
(``organic_boost``: boosted posts paid for by hand, and later Google /
LinkedIn until those apps are approved) can be entered by the user; they are
labelled ``manual`` everywhere so a reader never mistakes them for measured
data.

The *result* compared across networks must be the same event everywhere:
leads when every network with spend reports lead events, otherwise clicks.
Campaigns in a currency other than the dominant one are excluded (and
listed) rather than silently mixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domains.ads import store
from app.domains.ads.allocation_models import NETWORKS
from app.domains.ads.allocator.engine import NetworkStats

METRIC_LEADS = "leads"
METRIC_CLICKS = "clicks"
MANUAL_NETWORKS = frozenset(NETWORKS - {"meta", "tiktok"})


@dataclass(frozen=True)
class ManualNetwork:
    """User-entered results for a network Menivor cannot measure itself."""

    network: str
    spend_minor: int
    results: int
    current_daily_minor: int = 0
    impressions: int = 0

    def to_record(self) -> dict:
        return {"network": self.network, "spend_minor": self.spend_minor, "results": self.results,
                "current_daily_minor": self.current_daily_minor, "impressions": self.impressions}


@dataclass(frozen=True)
class Collected:
    currency: str
    metric: str
    networks: list[NetworkStats]
    campaigns: dict[str, list[str]]  # network -> active campaign keys in ``currency``
    excluded: list[dict] = field(default_factory=list)


def _campaign_totals(rows: list[tuple[Any, dict]]) -> dict:
    total = {"spend_minor": 0, "impressions": 0, "clicks": 0, "leads": None}
    for _, item in rows:
        stats = item.get("stats") or {}
        total["spend_minor"] += int(stats.get("spend_minor") or 0)
        total["impressions"] += int(stats.get("impressions") or 0)
        total["clicks"] += int(stats.get("clicks") or 0)
        if stats.get("leads") is not None:
            total["leads"] = int(total["leads"] or 0) + int(stats["leads"])
    return total


def _dominant_currency(camps: list[dict]) -> str:
    spend: dict[str, int] = {}
    for camp in camps:
        spend[camp["currency"]] = spend.get(camp["currency"], 0) + camp["totals"]["spend_minor"] + camp["daily"]
    if not spend:
        return "USD"
    return max(sorted(spend), key=lambda c: spend[c])


def paid_campaigns(session: Any, user_id: str) -> list[dict]:
    """One flat record per non-archived-or-spent paid campaign."""
    out = []
    for key, rows in store.campaigns(session, user_id).items():
        camp = (rows[0][1].get("campaign") or {}) if rows else {}
        platform = str(camp.get("platform") or "")
        if platform not in ("meta", "tiktok"):
            continue
        status = str(camp.get("status") or "")
        totals = _campaign_totals(rows)
        active = status == store.STATUS_ACTIVE
        if status == store.STATUS_ARCHIVED and totals["spend_minor"] <= 0:
            continue
        out.append({
            "key": key, "platform": platform, "name": str(camp.get("name") or ""), "status": status,
            "currency": str(camp.get("currency") or "USD").upper(),
            "daily": int(camp.get("daily_budget_minor") or 0) if active else 0,
            "totals": totals, "active": active, "synced_at": camp.get("synced_at"),
        })
    return out


def collect(session: Any, user_id: str, manual: list[ManualNetwork] | None = None) -> Collected:
    camps = paid_campaigns(session, user_id)
    currency = _dominant_currency(camps)
    kept = [c for c in camps if c["currency"] == currency]
    excluded = [{"key": c["key"], "platform": c["platform"], "name": c["name"], "currency": c["currency"],
                 "reason": f"Campaign currency {c['currency']} differs from {currency}; not mixed into the comparison."}
                for c in camps if c["currency"] != currency]

    per: dict[str, dict] = {}
    for c in kept:
        agg = per.setdefault(c["platform"], {"spend_minor": 0, "impressions": 0, "clicks": 0, "leads": None,
                                             "daily": 0, "campaigns": 0, "keys": []})
        t = c["totals"]
        agg["spend_minor"] += t["spend_minor"]
        agg["impressions"] += t["impressions"]
        agg["clicks"] += t["clicks"]
        if t["leads"] is not None:
            agg["leads"] = int(agg["leads"] or 0) + t["leads"]
        agg["daily"] += c["daily"]
        agg["campaigns"] += 1
        if c["active"]:
            agg["keys"].append(c["key"])

    spenders = [a for a in per.values() if a["spend_minor"] > 0]
    metric = METRIC_LEADS if spenders and all(a["leads"] is not None for a in spenders) else METRIC_CLICKS

    networks: list[NetworkStats] = []
    for platform in ("meta", "tiktok"):
        agg = per.get(platform)
        if agg is None:
            continue
        results = int(agg["leads"] or 0) if metric == METRIC_LEADS else agg["clicks"]
        networks.append(NetworkStats(
            network=platform, spend_minor=agg["spend_minor"], results=results, impressions=agg["impressions"],
            clicks=agg["clicks"], leads=agg["leads"], current_daily_minor=agg["daily"], campaigns=agg["campaigns"],
        ))
    seen = {n.network for n in networks}
    for row in manual or []:
        if row.network in seen or row.network not in MANUAL_NETWORKS:
            continue
        seen.add(row.network)
        networks.append(NetworkStats(
            network=row.network, spend_minor=max(0, row.spend_minor), results=max(0, row.results),
            impressions=max(0, row.impressions), current_daily_minor=max(0, row.current_daily_minor),
            source="manual",
        ))
    return Collected(currency=currency, metric=metric, networks=networks,
                     campaigns={p: a["keys"] for p, a in per.items()}, excluded=excluded)


def manual_from_records(records: Any) -> list[ManualNetwork]:
    """Rebuild manual rows from a stored proposal's ``network_stats``."""
    out = []
    items = records.items() if isinstance(records, dict) else []
    for name, rec in items:
        if not isinstance(rec, dict) or rec.get("source") != "manual" or name not in MANUAL_NETWORKS:
            continue
        out.append(ManualNetwork(network=name, spend_minor=int(rec.get("spend_minor") or 0),
                                 results=int(rec.get("results") or 0),
                                 current_daily_minor=int(rec.get("current_daily_minor") or 0),
                                 impressions=int(rec.get("impressions") or 0)))
    return out


__all__ = ["Collected", "MANUAL_NETWORKS", "METRIC_CLICKS", "METRIC_LEADS", "ManualNetwork", "collect",
           "manual_from_records", "paid_campaigns"]
