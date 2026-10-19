"""Shared numeric helpers (bit-identical to `src/*` — same as trends round6)."""

from __future__ import annotations


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def round6(x: float) -> float:
    bias = 0.5 if x >= 0 else -0.5
    return int(x * 1_000_000 + bias) / 1_000_000
