"""Fatigue math for one creative's daily rows (pure; no DB).

Window = the days given. ``recent`` = the last 3 days with delivery, ``early`` = the
days before them. Metrics a platform did not report stay ``None`` (never a 0):

* frequency = recent impressions / recent reach (people see it again and again);
* CTR decay = how far CTR fell from the early days to the recent days;
* CPA drift = how far CPA rose from the early days to the recent days.

Score 0-100 = weighted components (frequency 35, CTR decay 35, CPA drift 30), with
the weights re-normalised over the metrics that exist. ``fatigued`` >= 65,
``watch`` >= 35, else ``fresh``; ``not_enough_data`` below 4 delivery days or
1,000 impressions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

RECENT_DAYS = 3
MIN_DAYS = 4
MIN_IMPRESSIONS = 1000
WEIGHTS = {"frequency": 35, "ctr_decay": 35, "cpa_drift": 30}
FREQ_LOW, FREQ_HIGH = 1.5, 4.0
CTR_DECAY_FULL = 0.40
CPA_DRIFT_FULL = 0.50
FATIGUED, WATCH = 65, 35


@dataclass(frozen=True)
class Day:
    day: str
    impressions: int = 0
    clicks: int = 0
    spend: float = 0.0
    conversions: float | None = None
    reach: int | None = None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _sum(days: list[Day], field: str) -> float | None:
    values = [getattr(d, field) for d in days if getattr(d, field) is not None]
    return float(sum(values)) if values else None


def _ctr(days: list[Day]) -> float | None:
    impressions = _sum(days, "impressions") or 0
    return (_sum(days, "clicks") or 0) / impressions if impressions else None


def frequency(recent: list[Day]) -> float | None:
    reach = _sum([d for d in recent if d.reach], "reach")
    impressions = sum(d.impressions for d in recent if d.reach)
    return round(impressions / reach, 2) if reach else None


def ctr_decay(early: list[Day], recent: list[Day]) -> float | None:
    before, now = _ctr(early), _ctr(recent)
    if before is None or now is None or before <= 0:
        return None
    return round(max(0.0, (before - now) / before), 4)


def cpa_drift(early: list[Day], recent: list[Day]) -> float | None:
    conv_before, spend_before = _sum(early, "conversions"), float(_sum(early, "spend") or 0.0)
    conv_now, spend_now = _sum(recent, "conversions"), float(_sum(recent, "spend") or 0.0)
    if conv_before is None or conv_now is None or conv_before <= 0 or spend_before <= 0:
        return None
    cpa_before = spend_before / conv_before
    if conv_now <= 0:
        return 1.0 if spend_now >= cpa_before else None  # spent a whole CPA and converted nothing
    return round(max(0.0, (spend_now / conv_now - cpa_before) / cpa_before), 4)


def status_for(score: int | None) -> str:
    if score is None:
        return "not_enough_data"
    return "fatigued" if score >= FATIGUED else "watch" if score >= WATCH else "fresh"


def _reasons(freq: float | None, decay: float | None, drift: float | None) -> list[str]:
    out = []
    if freq is not None and freq >= FREQ_LOW:
        out.append(f"Frequency {freq:.1f}: the same people see it again and again")
    if decay:
        out.append(f"CTR down {round(decay * 100)}% from the first days")
    if drift:
        out.append(f"CPA up {round(drift * 100)}% from the first days")
    return out


def analyze(rows: Iterable[Day]) -> dict[str, Any]:
    days = sorted((d for d in rows if d.impressions > 0), key=lambda d: d.day)
    total = sum(d.impressions for d in days)
    series = [{"day": d.day, "ctr": round(d.clicks / d.impressions, 4) if d.impressions else None,
               "frequency": round(d.impressions / d.reach, 2) if d.reach else None} for d in days]
    base = {"days": len(days), "impressions": total, "series": series, "frequency": None, "ctr_decay": None,
            "cpa_drift": None, "score": None, "status": "not_enough_data", "reasons": [], "reported": []}
    if len(days) < MIN_DAYS or total < MIN_IMPRESSIONS:
        return base
    recent, early = days[-RECENT_DAYS:], days[:-RECENT_DAYS]
    metrics = {"frequency": frequency(recent), "ctr_decay": ctr_decay(early, recent),
               "cpa_drift": cpa_drift(early, recent)}
    parts = {
        "frequency": None if metrics["frequency"] is None else
        _clamp((metrics["frequency"] - FREQ_LOW) / (FREQ_HIGH - FREQ_LOW)),
        "ctr_decay": None if metrics["ctr_decay"] is None else _clamp(metrics["ctr_decay"] / CTR_DECAY_FULL),
        "cpa_drift": None if metrics["cpa_drift"] is None else _clamp(metrics["cpa_drift"] / CPA_DRIFT_FULL),
    }
    used = {k: v for k, v in parts.items() if v is not None}
    score = round(100 * sum(WEIGHTS[k] * v for k, v in used.items()) / sum(WEIGHTS[k] for k in used)) if used else None
    return {**base, **metrics, "score": score, "status": status_for(score), "reported": sorted(used),
            "reasons": _reasons(metrics["frequency"], metrics["ctr_decay"], metrics["cpa_drift"])}


__all__ = ["Day", "MIN_DAYS", "MIN_IMPRESSIONS", "analyze", "cpa_drift", "ctr_decay", "frequency", "status_for"]
