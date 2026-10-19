"""Stage-weight -> progress helpers (§6 state-reporting).

Progress is a weighted completion percentage over the *active* stages of a job:

    progress = round(100 * sum(weights of completed active stages)
                     / sum(weights of all active stages))

The ``upload`` stage is excluded from the denominator (and numerator) when the
job requests no publish platforms, so a compose-only job still reaches 100%.

Weights come from ``app.models.const.REELFORGE_STAGE_WEIGHTS``. That constant is
added by the persistence/const work; this module imports it lazily and falls
back to the contract-defined defaults so it stays import-safe regardless of
import order.
"""

from __future__ import annotations

from collections.abc import Iterable

# Contract §4.0 defaults. Used only as a fallback when the const module has not
# yet been extended with REELFORGE_STAGE_WEIGHTS.
_DEFAULT_STAGE_WEIGHTS: dict[str, int] = {
    "script": 10,
    "tts": 20,
    "avatar": 30,
    "captions": 15,
    "compose": 20,
    "upload": 5,
}

# Stage excluded from progress when the job publishes to no platforms.
UPLOAD_STAGE: str = "upload"


def stage_weights() -> dict[str, int]:
    """Return a fresh copy of the stage->weight map.

    Prefers ``app.models.const.REELFORGE_STAGE_WEIGHTS`` when available; falls
    back to the contract defaults. A copy is returned so callers cannot mutate
    shared state.
    """
    try:
        from app.models.const import REELFORGE_STAGE_WEIGHTS as _weights

        if isinstance(_weights, dict) and _weights:
            return dict(_weights)
    except Exception:  # noqa: BLE001 - import-safe: const may lack the symbol
        pass
    return dict(_DEFAULT_STAGE_WEIGHTS)


def stage_weight(stage: str) -> int:
    """Weight of a single stage (0 for unknown stages)."""
    return stage_weights().get(stage, 0)


def active_stages(has_platforms: bool = True) -> tuple[str, ...]:
    """Stages that count toward progress for this job.

    When ``has_platforms`` is falsy the ``upload`` stage is dropped, since the
    pipeline skips upload entirely for jobs with no publish targets.
    """
    stages = tuple(stage_weights().keys())
    if has_platforms:
        return stages
    return tuple(s for s in stages if s != UPLOAD_STAGE)


def total_active_weight(has_platforms: bool = True) -> int:
    """Sum of weights of the active stages (progress denominator)."""
    weights = stage_weights()
    return sum(weights.get(s, 0) for s in active_stages(has_platforms))


def compute_progress(
    done_stages: Iterable[str],
    has_platforms: bool = True,
) -> int:
    """Weighted percent-complete over active stages, clamped to [0, 100].

    Args:
        done_stages: Iterable of completed stage names. Unknown stages and
            stages inactive for this job (e.g. ``upload`` when no platforms)
            are ignored so they cannot inflate progress.
        has_platforms: Whether the job publishes to at least one platform;
            controls whether ``upload`` is part of the total.

    Returns:
        Integer progress in ``[0, 100]``. Returns ``0`` when there is no active
        weight (defensive; should not happen with the default weights).
    """
    weights = stage_weights()
    active = active_stages(has_platforms)
    total = sum(weights.get(s, 0) for s in active)
    if total <= 0:
        return 0

    active_set = set(active)
    done_weight = sum(
        weights.get(s, 0) for s in set(done_stages) if s in active_set
    )
    progress = round(100 * done_weight / total)
    # Guard against rounding/overflow beyond the expected range.
    return max(0, min(100, progress))
