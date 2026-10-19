"""Model lifecycle + sunset registry + migration hints (mirror of ``src/deprecation``).

ISO date strings compare lexicographically = chronologically, so ``today`` is a
param (deterministic, testable) rather than a runtime clock. Feeds
``routing/_deprecation.py``.
"""

from __future__ import annotations

# model_id -> {"sunset": ISO date, "replacement": model_id}
DEPRECATION_REGISTRY: dict[str, dict[str, str]] = {
    "openai/sora-2": {"sunset": "2026-09-24", "replacement": "google/veo-3.1"},
    "runwayml/gen-3a": {"sunset": "2026-07-30", "replacement": "runwayml/gen-4"},
    "kwaivgi/kling-v1.6": {"sunset": "2027-01-01", "replacement": "kwaivgi/kling-v2-master"},
}


def lifecycle(model_id: str, today: str) -> str:
    """``active`` | ``deprecating`` (announced, pre-sunset) | ``sunset`` (>= date)."""
    entry = DEPRECATION_REGISTRY.get(model_id)
    if entry is None:
        return "active"
    return "sunset" if today >= entry["sunset"] else "deprecating"


def replacement_for(model_id: str) -> str | None:
    entry = DEPRECATION_REGISTRY.get(model_id)
    return entry["replacement"] if entry else None


def migrate(model_id: str, today: str) -> dict:
    """Migration hint: whether to move off ``model_id`` and to what."""
    status = lifecycle(model_id, today)
    repl = replacement_for(model_id)
    return {
        "model": model_id,
        "status": status,
        "should_migrate": status in ("deprecating", "sunset"),
        "replacement": repl,
    }
