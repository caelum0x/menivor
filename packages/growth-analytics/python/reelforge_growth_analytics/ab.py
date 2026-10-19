"""Retention-weighted A/B winner selection (mirror of ``src/ab/winner.ts``).

Picks on completion + normalized average watch-time (retention signal), NOT
vanity views. Feeds ``experiments/winner.py``. Deterministic (ties → first).
"""

from __future__ import annotations

from typing import Sequence

from ._util import clamp01, round6


def select_winner(variants: Sequence[dict]) -> dict:
    """``[{id, completion, avg_watch}]`` → winner id + per-variant scores.

    score = 0.6·completion + 0.4·(avg_watch / max_avg_watch).
    """
    if not variants:
        return {"winner": None, "scores": {}}
    max_watch = max((float(v.get("avg_watch", 0.0)) for v in variants), default=0.0)
    denom = max_watch if max_watch > 0 else 1.0
    scores: dict = {}
    best_id = None
    best_score = -1.0
    for v in variants:
        vid = v["id"]
        completion = clamp01(float(v.get("completion", 0.0)))
        watch_norm = clamp01(float(v.get("avg_watch", 0.0)) / denom)
        s = round6(0.6 * completion + 0.4 * watch_norm)
        scores[vid] = s
        if s > best_score:
            best_score = s
            best_id = vid
    return {"winner": best_id, "scores": scores}
