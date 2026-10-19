"""Pure variant ranking + "why it won" explanation for the remake-winner loop.

Given the real post-publish metrics of every variant in a batch (views, likes,
comments, shares, saves and — where the platform exposes it — average watch
fraction), this module:

1. scores each variant on three batch-relative signals —
   **retention** (average share of the video watched), **reach** (views) and
   **engagement rate** (likes + comments + shares + saves per view, the closest
   honest proxy for "CTR" on a short-form feed, where no platform API exposes a
   click-through rate for organic Reels/Shorts/TikToks);
2. decides whether the result is conclusive (every variant cleared a minimum
   view floor and the leader beat the runner-up by a real margin);
3. writes a plain-language explanation that compares the winner to the other
   variants and lists what was actually different between them (hook wording,
   format settings, posting time).

No DB, no clock, no network: everything is passed in so every rule is
deterministically testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Weights when retention is available for every ranked variant. Retention
# dominates (watch time is the ranking-dominant signal on every short-form
# platform); reach and engagement split the rest.
_WEIGHTS_WITH_RETENTION = {"retention": 0.45, "reach": 0.30, "engagement": 0.25}
# Weights when at least one variant has no retention data (e.g. TikTok's public
# API exposes counts but not watch time) — never invent a retention figure.
_WEIGHTS_NO_RETENTION = {"retention": 0.0, "reach": 0.55, "engagement": 0.45}

DEFAULT_MIN_VIEWS = 100
MIN_SCORE_MARGIN = 0.05

# Format settings compared between variants when explaining a win. Only keys a
# creator recognises; internal/underscore params never appear here.
_FORMAT_KEYS: dict[str, str] = {
    "layout": "layout",
    "caption_style": "caption style",
    "voice_name": "voice",
    "avatar_id": "avatar",
    "music_id": "music track",
    "background_id": "background",
    "camera_motion": "camera motion",
    "target_duration_s": "target length",
    "aspect": "aspect ratio",
}


@dataclass(frozen=True)
class VariantInput:
    """Aggregated real metrics for one variant (summed across its platforms)."""

    job_id: str
    hook: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    avg_watch_frac: float | None = None  # None => the platform did not expose it
    completion_rate: float | None = None  # None => no platform reported it
    rewatch_rate: float | None = None     # None => no platform reported it
    posted_at: datetime | None = None
    format: dict[str, Any] = field(default_factory=dict)

    @property
    def engagements(self) -> int:
        return max(0, self.likes) + max(0, self.comments) + max(0, self.shares) + max(0, self.saves)

    @property
    def engagement_rate(self) -> float:
        return self.engagements / self.views if self.views > 0 else 0.0


@dataclass(frozen=True)
class RankedVariant:
    job_id: str
    rank: int
    score: float
    views: int
    engagement_rate: float
    avg_watch_frac: float | None
    signals: dict[str, float]

    def to_record(self) -> dict:
        return {
            "job_id": self.job_id,
            "rank": self.rank,
            "score": self.score,
            "views": self.views,
            "engagement_rate": round(self.engagement_rate, 4),
            "avg_watch_frac": None if self.avg_watch_frac is None else round(self.avg_watch_frac, 4),
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
        }


@dataclass(frozen=True)
class RankingResult:
    ranked: tuple[RankedVariant, ...]
    conclusive: bool
    winner_job_id: str
    uses_retention: bool
    reason: str

    def to_record(self) -> dict:
        return {
            "ranked": [r.to_record() for r in self.ranked],
            "conclusive": self.conclusive,
            "winner_job_id": self.winner_job_id,
            "uses_retention": self.uses_retention,
            "reason": self.reason,
        }


def _ratio(value: float, best: float) -> float:
    return max(0.0, min(1.0, value / best)) if best > 0 else 0.0


def rank_variants(
    variants: list[VariantInput],
    *,
    min_views: int = DEFAULT_MIN_VIEWS,
    min_margin: float = MIN_SCORE_MARGIN,
) -> RankingResult:
    """Rank variants best-first and decide whether the verdict is conclusive."""
    if not variants:
        return RankingResult((), False, "", False, "no variants with metrics")

    uses_retention = all(v.avg_watch_frac is not None for v in variants)
    weights = _WEIGHTS_WITH_RETENTION if uses_retention else _WEIGHTS_NO_RETENTION
    best_views = max(v.views for v in variants)
    best_eng = max(v.engagement_rate for v in variants)
    best_ret = max((v.avg_watch_frac or 0.0) for v in variants) if uses_retention else 0.0

    scored: list[tuple[VariantInput, float, dict[str, float]]] = []
    for v in variants:
        signals = {
            "reach": _ratio(v.views, best_views),
            "engagement": _ratio(v.engagement_rate, best_eng),
            "retention": _ratio(v.avg_watch_frac or 0.0, best_ret) if uses_retention else 0.0,
        }
        score = round(sum(weights[k] * signals[k] for k in weights), 4)
        scored.append((v, score, signals))

    # Deterministic order: score, then raw views, then job id.
    scored.sort(key=lambda item: (-item[1], -item[0].views, item[0].job_id))
    ranked = tuple(
        RankedVariant(
            job_id=v.job_id,
            rank=i + 1,
            score=score,
            views=v.views,
            engagement_rate=v.engagement_rate,
            avg_watch_frac=v.avg_watch_frac,
            signals=signals,
        )
        for i, (v, score, signals) in enumerate(scored)
    )
    leader = ranked[0]
    if len(ranked) < 2:
        return RankingResult(ranked, False, leader.job_id, uses_retention, "need at least 2 published variants")
    if best_views <= 0:
        return RankingResult(ranked, False, "", uses_retention, "no views recorded yet")
    thin = [r.job_id for r in ranked if r.views < min_views]
    if thin:
        return RankingResult(
            ranked, False, leader.job_id, uses_retention,
            f"{len(thin)} variant(s) under {min_views} views — sample too small",
        )
    margin = leader.score - ranked[1].score
    if margin < min_margin:
        return RankingResult(
            ranked, False, leader.job_id, uses_retention,
            f"top two within {margin:.2f} score — too close to call",
        )
    return RankingResult(ranked, True, leader.job_id, uses_retention, f"leader ahead by {margin:.2f} score")


# --------------------------------------------------------------------------- #
# Explanation
# --------------------------------------------------------------------------- #
def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_value(value: Any) -> str:
    text = str(value if value not in (None, "") else "default")
    return text.split(":", 1)[-1] if text.startswith("elevenlabs:") else text


def explain_win(result: RankingResult, variants: list[VariantInput]) -> dict:
    """Build a structured, plain-language "why it won" explanation.

    Only compares real, recorded numbers; when a metric was not available it
    says so instead of guessing. Returns ``{headline, reasons, differences,
    caveats, confidence}``.
    """
    by_id = {v.job_id: v for v in variants}
    winner = by_id.get(result.winner_job_id)
    if winner is None:
        return {
            "headline": "No winner yet.",
            "reasons": [],
            "differences": [],
            "caveats": [result.reason] if result.reason else [],
            "confidence": "none",
        }
    others = [v for v in variants if v.job_id != winner.job_id]
    reasons: list[dict] = []

    if result.uses_retention and others:
        other_ret = _mean([o.avg_watch_frac or 0.0 for o in others])
        win_ret = winner.avg_watch_frac or 0.0
        delta = win_ret - other_ret
        reasons.append({
            "metric": "retention",
            "winner": round(win_ret, 4),
            "others_avg": round(other_ret, 4),
            "text": (
                f"Viewers watched {_pct(win_ret)} of it on average vs "
                f"{_pct(other_ret)} for the other variants "
                f"({'+' if delta >= 0 else ''}{delta * 100:.1f} pts)."
            ),
        })
    if others:
        other_views = _mean([float(o.views) for o in others])
        mult = (winner.views / other_views) if other_views > 0 else None
        reasons.append({
            "metric": "views",
            "winner": winner.views,
            "others_avg": round(other_views, 1),
            "text": (
                f"{winner.views:,} views vs {other_views:,.0f} on average for the others"
                + (f" ({mult:.1f}x)." if mult is not None else ".")
            ),
        })
        other_eng = _mean([o.engagement_rate for o in others])
        reasons.append({
            "metric": "engagement_rate",
            "winner": round(winner.engagement_rate, 4),
            "others_avg": round(other_eng, 4),
            "text": (
                f"{_pct(winner.engagement_rate)} of viewers liked, commented, shared or saved "
                f"vs {_pct(other_eng)} for the others."
            ),
        })

    # Lead with the signal where the winner's advantage is largest (relative).
    def _lift(r: dict) -> float:
        base = float(r.get("others_avg") or 0.0)
        val = float(r.get("winner") or 0.0)
        return (val - base) / base if base > 0 else (1.0 if val > 0 else 0.0)

    reasons.sort(key=_lift, reverse=True)

    differences: list[dict] = []
    other_hooks = [o.hook for o in others if o.hook and o.hook != winner.hook]
    if winner.hook and other_hooks:
        differences.append({
            "aspect": "hook",
            "winner": winner.hook,
            "others": other_hooks,
            "text": "The winner opened with a different line than the other variants.",
        })
    for key, label in _FORMAT_KEYS.items():
        win_val = _format_value(winner.format.get(key))
        other_vals = sorted({_format_value(o.format.get(key)) for o in others} - {win_val})
        if other_vals:
            differences.append({
                "aspect": key,
                "winner": win_val,
                "others": other_vals,
                "text": f"Different {label}: the winner used {win_val}; other variants used {', '.join(other_vals)}.",
            })

    caveats: list[str] = []
    if not result.uses_retention:
        caveats.append(
            "Watch-time data was not available for every variant, so the ranking uses views "
            "and engagement only."
        )
    posted = [v.posted_at for v in variants if v.posted_at is not None]
    if len(posted) >= 2 and (max(posted) - min(posted)).total_seconds() >= 3600:
        caveats.append(
            "Variants were posted at different times to avoid competing with each other; "
            "posting time may account for part of the difference."
        )
    if not result.conclusive:
        caveats.append(f"Low confidence: {result.reason}.")

    headline = reasons[0]["text"] if reasons else "Only one variant has data so far."
    return {
        "headline": headline,
        "reasons": reasons,
        "differences": differences,
        "caveats": caveats,
        "confidence": "high" if result.conclusive else "low",
    }


__all__ = [
    "DEFAULT_MIN_VIEWS",
    "MIN_SCORE_MARGIN",
    "RankedVariant",
    "RankingResult",
    "VariantInput",
    "explain_win",
    "rank_variants",
]
