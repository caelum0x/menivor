"""1-body/N-hooks A/B experiments — retention-weighted winner selection.

The highest-leverage experiment in short-form: hold the body/caption/sound
constant, vary ONLY the first 3 seconds across N hook variants, and let the
platform's own distribution pick the winner. This module is the pure decision
core the event bus calls when variants have accumulated metrics: it scores each
variant, decides whether the sample is conclusive, and emits the winning hook so
generation can bias toward it next time.

Scoring weights **completion/avg-watch** (the ranking-dominant signals) above
raw views, with a minimum-sample guard so an early lucky variant can't win on
noise. Pure + deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

# Metric weights — retention signals dominate (research: watch-time ≈ 40-50% of
# ranking; rewatch weighted above likes; views alone are vanity).
_WEIGHTS = {
    "completion_rate": 0.45,   # % who watched to the end
    "avg_watch_frac": 0.30,    # mean fraction of the video watched
    "rewatch_rate": 0.15,      # loops / replays
    "engagement_rate": 0.10,   # (likes+comments+shares)/views
}
_MIN_VIEWS_PER_VARIANT = 200   # below this a variant is not yet conclusive
_MIN_MARGIN = 0.03             # winner must beat runner-up by this score margin


@dataclass(frozen=True)
class VariantMetrics:
    """Accumulated metrics for one hook variant."""

    variant_id: str
    hook_ref: str                 # the hook slot/spec that varied
    views: int = 0
    # ``None`` = the platform never reported this metric ("not measured"),
    # which is different from a measured 0%. Unmeasured metrics are left out of
    # scoring instead of being counted as zero retention.
    completion_rate: float | None = None
    avg_watch_frac: float = 0.0
    rewatch_rate: float | None = None
    engagement_rate: float = 0.0


@dataclass(frozen=True)
class ExperimentResult:
    """The experiment verdict."""

    conclusive: bool
    winner_id: str = ""
    winner_hook_ref: str = ""
    scores: dict = None  # type: ignore[assignment]
    reason: str = ""


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def measured_metrics(m: VariantMetrics) -> frozenset[str]:
    """The weighted metrics this variant actually has a value for."""
    return frozenset(name for name in _WEIGHTS if getattr(m, name) is not None)


def _common_metrics(variants: list[VariantMetrics]) -> frozenset[str]:
    """Metrics measured for EVERY variant — the only fair basis for comparison."""
    if not variants:
        return frozenset()
    common = measured_metrics(variants[0])
    for m in variants[1:]:
        common = common & measured_metrics(m)
    return common


def score_variant(m: VariantMetrics, metrics: frozenset[str] | None = None) -> float:
    """Retention-weighted score in 0..1 for one variant.

    Only ``metrics`` (default: the ones this variant has measured) contribute,
    and their weights are renormalised to sum to 1, so an unmeasured completion
    or rewatch rate is skipped rather than scored as 0%.
    """
    names = measured_metrics(m) if metrics is None else metrics & measured_metrics(m)
    total_weight = sum(_WEIGHTS[n] for n in names)
    if total_weight <= 0:
        return 0.0
    weighted = sum(_WEIGHTS[n] * _clamp(getattr(m, n)) for n in names)
    return round(weighted / total_weight, 4)


def select_winner(
    variants: list[VariantMetrics],
    *,
    min_views: int = _MIN_VIEWS_PER_VARIANT,
    min_margin: float = _MIN_MARGIN,
) -> ExperimentResult:
    """Pick the retention-weighted winner if the sample is conclusive.

    Inconclusive when: fewer than 2 variants, any variant under ``min_views``, or
    the top two scores are within ``min_margin`` (a near-tie needs more data).
    Variants are scored only on the metrics measured for all of them, so one
    variant with an unreported completion rate is not penalised as 0%.
    """
    basis = _common_metrics(variants)
    scores = {m.variant_id: score_variant(m, basis) for m in variants}
    if len(variants) < 2:
        return ExperimentResult(False, scores=scores, reason="need at least 2 variants")

    underpowered = [m.variant_id for m in variants if m.views < min_views]
    if underpowered:
        return ExperimentResult(
            False, scores=scores,
            reason=f"insufficient sample (<{min_views} views): {underpowered}",
        )

    ranked = sorted(variants, key=lambda m: scores[m.variant_id], reverse=True)
    top, runner = ranked[0], ranked[1]
    margin = scores[top.variant_id] - scores[runner.variant_id]
    if margin < min_margin:
        return ExperimentResult(
            False, scores=scores,
            reason=f"top two within {min_margin} (margin {margin:.3f}) — inconclusive",
        )
    return ExperimentResult(
        True, winner_id=top.variant_id, winner_hook_ref=top.hook_ref, scores=scores,
        reason=f"winner by {margin:.3f} margin",
    )
