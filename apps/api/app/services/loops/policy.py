"""Shared retention/loop thresholds for the P7 loop + hook services.

Single source of truth for the research-backed gates so the hook predictor, loop
finder, and beat-cutter agree (mirrors ``app.domains.templates.policy``).
"""

from __future__ import annotations

HOOK_WINDOW_S: float = 3.0          # the window that decides ~70% of retention
HOOK_MIN_CLEARANCE: float = 0.70    # viral-reach gate (first-3s completion)
LOOP_MAX_DURATION_S: float = 6.0    # seamless-loop genres cap (ASMR ~5s)
LOOP_MAX_DISCONTINUITY: float = 0.08  # max normalized last≈first frame diff to accept a loop
REWATCH_TARGET: float = 0.15        # rewatch rate that signals a strong loop
