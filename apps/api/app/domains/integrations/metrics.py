"""Read side of the common metrics table: per-creative and per-account totals (pure math + one query).

Rates are computed from counts: CTR = clicks / impressions, CPC = spend / clicks,
CPA = spend / conversions, ROAS = conversion value / spend. Anything the platform
did not report (no conversions field, no impressions yet) is ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import select

from app.domains.ads.platforms import from_minor
from app.domains.integrations.models import IntegrationAdMetric


@dataclass(frozen=True)
class Totals:
    spend_minor: int = 0
    impressions: int = 0
    clicks: int = 0
    conversions: float | None = None
    conversion_value_minor: int | None = None

    def add(self, row: Any) -> "Totals":
        conv = self.conversions
        if row.conversions is not None:
            conv = (conv or 0.0) + float(row.conversions)
        value = self.conversion_value_minor
        if row.conversion_value_minor is not None:
            value = (value or 0) + int(row.conversion_value_minor)
        return Totals(self.spend_minor + int(row.spend_minor or 0), self.impressions + int(row.impressions or 0),
                      self.clicks + int(row.clicks or 0), conv, value)


def window(days: int, today: date | None = None) -> tuple[date, date]:
    end = today or date.today()
    span = max(1, min(int(days or 7), 90))
    return end - timedelta(days=span - 1), end


def _ratio(num: float | None, den: float | None, digits: int = 4) -> float | None:
    if num is None or not den:
        return None
    return round(float(num) / float(den), digits)


def derive(t: Totals, currency: str) -> dict:
    spend = from_minor(t.spend_minor, currency)
    value = None if t.conversion_value_minor is None else from_minor(t.conversion_value_minor, currency)
    return {
        "currency": currency,
        "spend": spend,
        "impressions": t.impressions,
        "clicks": t.clicks,
        "conversions": t.conversions,
        "conversion_value": value,
        "ctr": _ratio(t.clicks, t.impressions),
        "cpc": _ratio(spend, t.clicks, 2),
        "cpa": _ratio(spend, t.conversions, 2) if t.conversions else None,
        "roas": _ratio(value, spend, 2) if value is not None else None,
    }


def rows_for(session: Any, account_ids: Iterable[str], since: date, until: date) -> list[IntegrationAdMetric]:
    ids = list(account_ids)
    if not ids:
        return []
    return list(session.execute(select(IntegrationAdMetric).where(
        IntegrationAdMetric.ad_account_id.in_(ids), IntegrationAdMetric.day >= since.isoformat(),
        IntegrationAdMetric.day <= until.isoformat())).scalars())


def creatives(rows: list[IntegrationAdMetric]) -> list[dict]:
    """One entry per (account, creative) with totals and derived metrics."""
    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row.ad_account_id, row.entity_id)
        entry = grouped.setdefault(key, {"ad_account_id": row.ad_account_id, "provider": row.provider,
                                         "entity_id": row.entity_id, "entity_name": row.entity_name,
                                         "campaign_id": row.campaign_id, "group_id": row.group_id,
                                         "currency": row.currency, "totals": Totals()})
        entry["totals"] = entry["totals"].add(row)
        entry["entity_name"] = entry["entity_name"] or row.entity_name
    out = []
    for entry in grouped.values():
        totals = entry.pop("totals")
        out.append({**entry, "spend_minor": totals.spend_minor, "metrics": derive(totals, entry["currency"]),
                    "_totals": totals})
    return out


def rank_top(items: list[dict]) -> list[dict]:
    """Best first: ROAS, then conversions, then CTR, then spend (None counts as worst)."""
    def key(item: dict) -> tuple:
        m = item["metrics"]
        return (m["roas"] if m["roas"] is not None else -1.0, m["conversions"] or 0.0,
                m["ctr"] if m["ctr"] is not None else -1.0, item["spend_minor"])
    return sorted(items, key=key, reverse=True)


def account_totals(items: list[dict]) -> Totals:
    total = Totals()
    for item in items:
        t = item["_totals"]
        conv = total.conversions if t.conversions is None else (total.conversions or 0.0) + t.conversions
        value = total.conversion_value_minor if t.conversion_value_minor is None else \
            (total.conversion_value_minor or 0) + t.conversion_value_minor
        total = Totals(total.spend_minor + t.spend_minor, total.impressions + t.impressions,
                       total.clicks + t.clicks, conv, value)
    return total


def public(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


__all__ = ["Totals", "account_totals", "creatives", "derive", "public", "rank_top", "rows_for", "window"]
