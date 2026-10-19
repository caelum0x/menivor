"""ReelForge telemetry package (§6 state-reporting).

Exposes append-only event recording and stage-weight progress helpers. Imports
here are kept lightweight and import-safe (the DB layer is loaded lazily inside
``record_event``).
"""

from __future__ import annotations

from app.telemetry.events import record_event
from app.telemetry.progress import (
    active_stages,
    compute_progress,
    stage_weight,
    stage_weights,
    total_active_weight,
)

__all__ = [
    "active_stages",
    "compute_progress",
    "record_event",
    "stage_weight",
    "stage_weights",
    "total_active_weight",
]
