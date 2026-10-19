"""Hook-strength scoring (mirror of ``src/hook/score.ts``).

Weighted first-3s signals vs the 70% gate. Feeds
``services/loops/hook_predictor.py``. Pure + deterministic.
"""

from __future__ import annotations

from ._util import clamp01, round6

GATE = 0.70
_WEIGHTS = {"motion": 0.35, "contrast": 0.20, "text": 0.20, "audio_onset": 0.25}


def hook_score(signals: dict) -> dict:
    """Weighted hook score in [0,1] + whether it clears the 70% gate."""
    total = 0.0
    for key, weight in _WEIGHTS.items():
        total += weight * clamp01(float(signals.get(key, 0.0)))
    s = round6(total)
    return {"score": s, "passes": s >= GATE}
