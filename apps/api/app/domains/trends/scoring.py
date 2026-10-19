"""Trend + sound scoring — ride the wave before it peaks.

Research: the highest-leverage move is to build to a **rising-but-not-peaked**
sound/hashtag (a saturation score), edit muted, then attach the exact native audio
on upload. This module scores an observed trend from its recent usage-count time
series into an **opportunity score**: high when velocity is strong AND saturation
is still low, decaying to zero once the trend is peaking/declining.

Pure + deterministic (the ingestion probes supply the series). No network/DB.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# EMA smoothing factor for velocity: 0.3 means the most-recent period receives
# ~30% weight; earlier periods decay exponentially.  Raise toward 1.0 for a
# more reactive scorer; lower toward 0.0 for a smoother one.
_EMA_ALPHA: float = 0.3

# Per-kind saturation ceilings (weekly post counts at which the trend is
# considered fully saturated).  Pass ``kind_baselines`` to ``score_trend`` to
# override per-deployment or per-platform.  "_default" is the fallback for
# unknown kind values.
SATURATION_BASELINES: dict[str, int] = {
    "sound":    500_000,
    "hashtag": 1_000_000,
    "format":   200_000,
    "_default": 100_000,
}


@dataclass(frozen=True)
class TrendSignal:
    """A trend observation: the recent per-period usage counts (oldest→newest)."""

    trend_id: str
    kind: str                      # sound | hashtag | format
    counts: tuple[int, ...]        # e.g. daily post counts, oldest first
    label: str = ""


@dataclass(frozen=True)
class TrendScore:
    """Scored trend with an actionable phase + opportunity 0..1."""

    trend_id: str
    velocity: float                # EMA-weighted recent growth rate
    acceleration: float            # change in velocity (rising vs. flattening)
    saturation: float              # 0 (fresh) .. 1 (peaked/everywhere)
    opportunity: float             # 0..1 — build to this now?
    phase: str                     # emerging | rising | peaking | declining
    recommend: bool


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def _ema_velocity(growths: list[float], alpha: float = _EMA_ALPHA) -> float:
    """EMA of period-over-period growth rates (oldest→newest), clamped 0..1.

    Recent periods receive exponentially more weight:
        ema_t = alpha * g_t + (1 - alpha) * ema_{t-1}
    """
    if not growths:
        return 0.0
    ema = growths[0]
    for g in growths[1:]:
        ema = alpha * g + (1.0 - alpha) * ema
    return max(0.0, min(1.0, ema))


def _gradient_rising(acceleration: float) -> float:
    """Continuous rising-signal multiplier in [0.40, 1.00] based on acceleration.

    Maps via tanh so the transition is smooth rather than a binary 1.0 / 0.5:
    - strong positive acceleration  → ~1.00 (trend accelerating)
    - zero acceleration             → ~0.70 (flat / neutral)
    - strong negative acceleration  → ~0.40 (decelerating penalty)
    """
    t = math.tanh(acceleration * 5.0)   # tanh ∈ (-1, +1)
    return round(0.70 + 0.30 * t, 4)    # maps to [~0.40, ~1.00]


def score_trend(
    signal: TrendSignal,
    *,
    saturation_ceiling: int | None = None,
    kind_baselines: dict[str, int] | None = None,
) -> TrendScore:
    """Score a trend's opportunity from its usage-count series.

    velocity     = EMA-weighted period-over-period growth (recent periods
                   outweigh old ones; clamped 0..1),
    acceleration = late-window EMA minus early-window EMA (rising signal),
    saturation   = latest count / per-kind ceiling (how crowded already),
    opportunity  = velocity * (1 - saturation) * gradient_rising_multiplier.

    ``saturation_ceiling`` overrides everything (backward-compat).
    ``kind_baselines`` is a dict[kind, ceiling] that extends/replaces
    :data:`SATURATION_BASELINES`; unknown kinds fall back to ``_default``.
    """
    counts = [max(0, int(c)) for c in signal.counts]
    if len(counts) < 3:
        return TrendScore(signal.trend_id, 0.0, 0.0, 0.0, 0.0, "emerging", False)

    # Period-over-period growth ratios.
    growths = [
        _safe_div(counts[i] - counts[i - 1], max(1, counts[i - 1]))
        for i in range(1, len(counts))
    ]

    # EMA velocity: recent periods outweigh old ones.
    velocity = _ema_velocity(growths)

    # Acceleration: compare EMA of the late half vs. the early half.
    mid = len(growths) // 2
    early_ema = _ema_velocity(growths[:mid]) if mid else 0.0
    late_ema = _ema_velocity(growths[mid:]) if len(growths) - mid else 0.0
    acceleration = late_ema - early_ema

    # Per-kind saturation ceiling.
    if saturation_ceiling is not None:
        ceiling = saturation_ceiling
    else:
        baselines = {**SATURATION_BASELINES, **(kind_baselines or {})}
        ceiling = baselines.get(signal.kind) or baselines.get("_default", 100_000)
    saturation = max(0.0, min(1.0, _safe_div(counts[-1], ceiling)))

    # Gradient (continuous) rising multiplier instead of binary bonus.
    rising_mult = _gradient_rising(acceleration)
    opportunity = round(velocity * (1.0 - saturation) * rising_mult, 4)

    phase = _phase(velocity, acceleration, saturation)
    recommend = phase in ("emerging", "rising") and opportunity >= 0.15
    return TrendScore(
        trend_id=signal.trend_id,
        velocity=round(velocity, 4),
        acceleration=round(acceleration, 4),
        saturation=round(saturation, 4),
        opportunity=opportunity,
        phase=phase,
        recommend=recommend,
    )


def _phase(velocity: float, acceleration: float, saturation: float) -> str:
    if saturation >= 0.6 and acceleration < 0:
        return "declining"
    if saturation >= 0.5:
        return "peaking"
    if velocity >= 0.2 and acceleration >= 0:
        return "rising"
    if velocity < 0.05 and acceleration < 0:
        return "declining"
    return "emerging"


def rank_trends(
    signals: list[TrendSignal],
    *,
    limit: int = 10,
    kind_baselines: dict[str, int] | None = None,
) -> list[TrendScore]:
    """Score + rank trends by opportunity (recommended first, then score)."""
    scored = [score_trend(s, kind_baselines=kind_baselines) for s in signals]
    scored.sort(key=lambda s: (s.recommend, s.opportunity), reverse=True)
    return scored[:limit]
