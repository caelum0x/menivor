"""Longevity is the winner signal: advertisers keep paying for ads that work.

* ``days_running`` = start -> stop (or now).
* tier: ``winner`` (>= 30 days and still running), ``proven`` (>= 14 days),
  ``testing`` (younger), ``unknown`` (no start date).
* ``scaled``: the same copy runs in 3+ ads of the brand (the advertiser duplicated it).
* ``score`` 0-100: days capped at 90, +10 when still running, +10 when scaled.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

WINNER_DAYS = 30
PROVEN_DAYS = 14
SCALED_COPIES = 3
CAP_DAYS = 90
TIER_ORDER = {"winner": 0, "proven": 1, "testing": 2, "unknown": 3}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def days_running(started: datetime | None, stopped: datetime | None, now: datetime) -> int | None:
    start = _aware(started)
    if start is None:
        return None
    end = _aware(stopped) or _aware(now)
    return max(0, (end - start).days)


def tier(days: int | None, active: bool) -> str:
    if days is None:
        return "unknown"
    if days >= WINNER_DAYS and active:
        return "winner"
    if days >= PROVEN_DAYS:
        return "proven"
    return "testing"


def copy_key(body: str, title: str = "") -> str:
    return re.sub(r"[^a-z0-9]+", " ", f"{body} {title}".lower()).strip()[:200]


def score(days: int | None, active: bool, scaled: bool) -> int:
    if days is None:
        return 0
    base = round(min(days, CAP_DAYS) / CAP_DAYS * 80)
    return int(min(100, base + (10 if active else 0) + (10 if scaled else 0)))


def annotate(ads: Iterable[Any], now: datetime) -> list[dict[str, Any]]:
    """Longevity fields for each ad row (anything with started_at / stopped_at / active / body / title)."""
    rows = list(ads)
    copies = Counter(copy_key(r.body, r.title) for r in rows if copy_key(r.body, r.title))
    out = []
    for r in rows:
        days = days_running(r.started_at, r.stopped_at, now)
        key = copy_key(r.body, r.title)
        scaled = bool(key) and copies[key] >= SCALED_COPIES
        active = bool(r.active)
        out.append({"days_running": days, "tier": tier(days, active), "scaled": scaled,
                    "score": score(days, active, scaled)})
    return out


def rank_key(view: dict[str, Any]) -> tuple:
    return (TIER_ORDER.get(view["tier"], 9), -int(view["score"]), -(view["days_running"] or 0))


__all__ = ["PROVEN_DAYS", "SCALED_COPIES", "WINNER_DAYS", "annotate", "copy_key", "days_running", "rank_key",
           "score", "tier"]
