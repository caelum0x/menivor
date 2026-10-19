"""ReelForge trends-schema (Python port) — trend DTOs + pure scoring.

Byte-identical to ``@reelforge/trends-schema`` (golden fixtures) so the trend
feed scores the same on api, web and mobile. Feeds ``app/domains/trends``.
"""

from .scoring import (
    ad_safe,
    clamp01,
    decay,
    opportunity,
    round6,
    saturation,
    score,
    velocity,
)

__all__ = [
    "saturation",
    "velocity",
    "decay",
    "opportunity",
    "score",
    "ad_safe",
    "clamp01",
    "round6",
]
