"""Pure trend scoring — saturation / velocity / decay / opportunity.

Shared so the trend feed reads identically on backend, web and mobile. Every
function is pure arithmetic over a usage series; a shared ``round6`` (truncate
after a half-away-from-zero bias) makes the TypeScript and Python ports produce
bit-identical numbers (same IEEE-754 op sequence). Feeds ``trends/scoring.py``.
"""

from __future__ import annotations

from typing import Sequence


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def round6(x: float) -> float:
    """Deterministic 6-dp round (half away from zero) — identical in JS/Python."""
    bias = 0.5 if x >= 0 else -0.5
    return int(x * 1_000_000 + bias) / 1_000_000


def saturation(series: Sequence[float]) -> float:
    """Current usage as a fraction of the peak (1.0 = at peak / over-saturated)."""
    if not series:
        return 0.0
    peak = max(series)
    if peak <= 0:
        return 0.0
    return round6(series[-1] / peak)


def velocity(series: Sequence[float], window: int = 3) -> float:
    """Normalized average adoption step over the last ``window`` intervals."""
    n = len(series)
    if n < 2:
        return 0.0
    k = min(int(window), n - 1)
    peak = max(series)
    denom = peak if peak > 0 else 1.0
    change = series[-1] - series[-1 - k]
    return round6(change / (k * denom))


def decay(series: Sequence[float]) -> float:
    """Fraction fallen from a past peak (0.0 if still at/rising to peak)."""
    if not series:
        return 0.0
    peak = max(series)
    if peak <= 0:
        return 0.0
    peak_idx = list(series).index(peak)
    if peak_idx < len(series) - 1 and series[-1] < peak:
        return round6((peak - series[-1]) / peak)
    return 0.0


def opportunity(series: Sequence[float]) -> float:
    """Composite 'ride it now' score: rising + not saturated + not decaying."""
    sat = saturation(series)
    vel = velocity(series)
    dec = decay(series)
    rising = clamp01(vel * 10.0)
    return round6(clamp01(0.5 * rising + 0.4 * (1.0 - sat) + 0.1 * (1.0 - dec)))


def score(series: Sequence[float]) -> dict:
    """Full ``TrendScore`` DTO for a usage series."""
    return {
        "saturation": saturation(series),
        "velocity": velocity(series),
        "decay": decay(series),
        "opportunity": opportunity(series),
    }


def ad_safe(sound: dict) -> bool:
    """Cross-platform (Meta-compatible) ad-safe rule: licensed + not explicit."""
    return bool(sound.get("licensed", True)) and not bool(sound.get("explicit", False))
