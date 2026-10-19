"""ReelForge growth-analytics (Python port) — funnel / retention / hook / A-B.

Pure analytics: takes data, returns verdicts (no I/O), byte-identical to
``@reelforge/growth-analytics`` (golden fixtures) so web/mobile/api agree.
"""

from ._util import clamp01, round6
from .ab import select_winner
from .hook import GATE, hook_score
from .retention import dropoff, normalize_curve, reach_tier

__all__ = [
    "normalize_curve",
    "reach_tier",
    "dropoff",
    "hook_score",
    "GATE",
    "select_winner",
    "clamp01",
    "round6",
]
