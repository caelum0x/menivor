"""Unified async job envelope (mirror of ``src/contract/envelope.ts``).

The shared state grammar every provider adapter normalizes to — the same one the
desktop ``rf-jobs`` crate mirrors — so poll/webhook status maps consistently.
"""

from __future__ import annotations

STATES: tuple[str, ...] = ("IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED")


def normalize_state(raw: str) -> str:
    """Collapse a provider's raw status string to the canonical state."""
    s = (raw or "").strip().upper()
    if s in ("IN_QUEUE", "QUEUED", "PENDING", "STARTING", "CREATED", "SUBMITTED"):
        return "IN_QUEUE"
    if s in ("IN_PROGRESS", "RUNNING", "PROCESSING", "EXECUTING", "DREAMING", "THROTTLED"):
        return "IN_PROGRESS"
    if s in ("COMPLETED", "COMPLETE", "SUCCEEDED", "SUCCESS", "FINISHED"):
        return "COMPLETED"
    if s in ("FAILED", "ERROR", "TIMED_OUT", "CRASHED"):
        return "FAILED"
    if s in ("CANCELLED", "CANCELED", "ABORTED"):
        return "CANCELLED"
    # Unknown but live → treat as running (safer than done/failed).
    return "IN_PROGRESS"


def is_terminal(state: str) -> bool:
    return state in ("COMPLETED", "FAILED", "CANCELLED")


def normalized_usage(units: float, cost_micros: int, success: bool) -> dict:
    """``NormalizedUsage`` — success-only billing carries cost only when success."""
    return {
        "units": units,
        "cost_micros": int(cost_micros) if success else 0,
        "success": bool(success),
    }
