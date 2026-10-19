"""Loop / beat / hook analyzers feeding the retention gate (P7)."""

from __future__ import annotations

from app.services.loops.beat_cut import (
    SnappedCut,
    preview_beat_fits,
    snap_cuts_to_beats,
)
from app.services.loops.hook_predictor import HookScore, HookSignals, predict_hook
from app.services.loops.hook_suggestions import (
    HookSuggestion,
    needs_suggestions,
    suggest_hooks,
)
from app.services.loops.loop_finder import LoopResult, find_loop_point

__all__ = [
    "HookScore", "HookSignals", "predict_hook",
    "HookSuggestion", "needs_suggestions", "suggest_hooks",
    "LoopResult", "find_loop_point",
    "SnappedCut", "snap_cuts_to_beats", "preview_beat_fits",
]
