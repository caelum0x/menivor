"""Allocator knobs (env, read on every call so tests and operators can change them)."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MAX_STEP = 0.20       # largest per-network change in one proposal (fraction of total)
DEFAULT_MIN_SHARE = 0.10      # exploration floor per network
DEFAULT_MIN_RESULTS = 30      # below this a network's cost per result is flagged as a small sample
DEFAULT_AUTO_APPLY_DELTA = 0.0  # 0 = never auto-apply; every proposal waits for approval


def _float_env(name: str, default: float, lo: float, hi: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return min(hi, max(lo, value))


@dataclass(frozen=True)
class AllocatorConfig:
    max_step: float
    min_share: float
    min_results: int
    auto_apply_delta: float


def load() -> AllocatorConfig:
    return AllocatorConfig(
        max_step=_float_env("MENIVOR_ALLOCATOR_MAX_STEP", DEFAULT_MAX_STEP, 0.01, 1.0),
        min_share=_float_env("MENIVOR_ALLOCATOR_MIN_SHARE", DEFAULT_MIN_SHARE, 0.0, 0.3),
        min_results=int(_float_env("MENIVOR_ALLOCATOR_MIN_RESULTS", DEFAULT_MIN_RESULTS, 1, 100_000)),
        auto_apply_delta=_float_env("MENIVOR_ALLOCATOR_AUTO_APPLY_DELTA", DEFAULT_AUTO_APPLY_DELTA, 0.0, 0.5),
    )


__all__ = ["AllocatorConfig", "load"]
