"""Spend / CTR / CPC / CPL views for paid campaigns (pure).

Every rate is computed from the counts the platform reported. A metric the
platform did not report (no lead events, no impressions yet) is ``None`` —
never an invented 0.
"""

from __future__ import annotations

from typing import Any

from app.domains.ads.platforms import from_minor


def _rate(num: int | None, den: int) -> float | None:
    if num is None or den <= 0:
        return None
    return round(num / den, 6)


def _cost(spend_minor: int, count: int | None, currency: str) -> float | None:
    if count is None or count <= 0:
        return None
    return round(from_minor(spend_minor, currency) / count, 2)


def metrics(stats: dict | None, currency: str) -> dict[str, Any]:
    stats = stats or {}
    spend = int(stats.get("spend_minor") or 0)
    impressions = int(stats.get("impressions") or 0)
    clicks = int(stats.get("clicks") or 0)
    leads = stats.get("leads")
    leads = None if leads is None else int(leads)
    return {
        "spend": from_minor(spend, currency),
        "spend_minor": spend,
        "impressions": impressions,
        "clicks": clicks,
        "leads": leads,
        "ctr": _rate(clicks, impressions),
        "cpc": _cost(spend, clicks, currency),
        "cpl": _cost(spend, leads, currency),
        "lead_rate": _rate(leads, clicks),
    }


def _sum_stats(rows: list[tuple[Any, dict]]) -> dict:
    total = {"spend_minor": 0, "impressions": 0, "clicks": 0, "leads": None}
    for _, item in rows:
        stats = item.get("stats") or {}
        total["spend_minor"] += int(stats.get("spend_minor") or 0)
        total["impressions"] += int(stats.get("impressions") or 0)
        total["clicks"] += int(stats.get("clicks") or 0)
        if stats.get("leads") is not None:
            total["leads"] = int(total["leads"] or 0) + int(stats["leads"])
    return total


def creative_view(variant: Any, item: dict, currency: str, media: dict | None = None) -> dict[str, Any]:
    media = media or {}
    spec = variant.spec or {}
    angle = spec.get("angle") if isinstance(spec.get("angle"), dict) else {}
    return {
        "variant_id": variant.id,
        "project_id": variant.project_id,
        "hook": str(angle.get("hook") or ""),
        "format": variant.format,
        "aspect": variant.aspect,
        "poster_url": media.get("poster_url"),
        "phase": item.get("phase", ""),
        "error": item.get("error") or None,
        "active": bool(item.get("active", True)),
        "budget_minor": int(item.get("budget_minor") or 0),
        "p_best": item.get("p_best"),
        "allocation_reason": item.get("alloc_reason") or "",
        "ad_group_id": item.get("ad_group_id") or "",
        "ad_id": item.get("ad_id") or "",
        "metrics": metrics(item.get("stats"), currency),
    }


def campaign_view(key: str, rows: list[tuple[Any, dict]], media: dict[str, dict] | None = None) -> dict[str, Any]:
    media = media or {}
    camp = dict((rows[0][1].get("campaign") or {}) if rows else {})
    currency = str(camp.get("currency") or "USD")
    creatives = [creative_view(v, item, currency, media.get(v.id)) for v, item in rows]
    live_budget = sum(c["budget_minor"] for c in creatives if c["active"])
    return {
        "key": key,
        "platform": camp.get("platform", ""),
        "name": camp.get("name", ""),
        "status": camp.get("status", ""),
        "error": camp.get("error") or None,
        "external_id": camp.get("external_id", ""),
        "account_id": camp.get("account_id", ""),
        "currency": currency,
        "daily_budget_minor": int(camp.get("daily_budget_minor") or 0),
        "allocated_budget_minor": live_budget,
        "audience": camp.get("audience") or {},
        "optimize_for": camp.get("optimize_for", "ctr"),
        "auto_optimize": bool(camp.get("auto_optimize", True)),
        "landing_url": camp.get("landing_url", ""),
        "created_at": camp.get("created_at"),
        "synced_at": camp.get("synced_at"),
        "optimized_at": camp.get("optimized_at"),
        "allocation": camp.get("allocation") or None,
        "metrics": metrics(_sum_stats(rows), currency),
        "creatives": creatives,
    }


def campaign_summary(key: str, rows: list[tuple[Any, dict]]) -> dict[str, Any]:
    view = campaign_view(key, rows)
    view.pop("creatives")
    view["creative_count"] = len(rows)
    return view


__all__ = ["campaign_summary", "campaign_view", "creative_view", "metrics"]
