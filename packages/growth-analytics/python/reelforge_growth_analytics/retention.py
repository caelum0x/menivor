"""Retention-curve normalization + reach-tier mapping + drop-off (mirror of
``src/retention/*``). Pure math; feeds ``publishing/analytics/retention.py``.
"""

from __future__ import annotations

from typing import Sequence

from ._util import clamp01, round6


def normalize_curve(samples: Sequence[float]) -> list[float]:
    """Per-second viewer counts → 0..1 retention curve (relative to the start)."""
    if not samples:
        return []
    base = samples[0] if samples[0] > 0 else (max(samples) or 1.0)
    return [round6(clamp01(s / base)) for s in samples]


def reach_tier(avg_retention: float) -> dict:
    """Map average retention → distribution reach tier + boost multiplier."""
    r = clamp01(avg_retention)
    if r >= 0.85:
        return {"tier": "viral", "multiplier": 3.0}
    if r >= 0.70:
        return {"tier": "boosted", "multiplier": 2.2}
    return {"tier": "minimal", "multiplier": 1.0}


def dropoff(curve: Sequence[float]) -> dict:
    """Biggest consecutive drop + its index, plus the first-3s subscore."""
    max_drop = 0.0
    at = 0
    for i in range(1, len(curve)):
        drop = curve[i - 1] - curve[i]
        if drop > max_drop:
            max_drop = drop
            at = i
    head = curve[:3] if curve else []
    first_3s = round6(sum(head) / len(head)) if head else 0.0
    return {"max_drop": round6(max_drop), "max_drop_at": at, "first_3s": first_3s}
