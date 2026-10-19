"""Takedown sweep (MN5): soft-block any content report left open for 24 h.

Runs hourly on the housekeeping queue. Never raises.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

SWEEP_TASK = "app.workers.tasks_takedown.takedown_sweep_task"

BEAT_SCHEDULE: dict[str, dict] = {
    "menivor-takedown-sweep": {"task": SWEEP_TASK, "schedule": 3600.0},
}


def sweep() -> int:
    from app.domains.compliance import takedown
    from app.models.db.base import get_session

    with get_session() as session:
        return takedown.auto_block_overdue(session)


@celery_app.task(name=SWEEP_TASK)
def takedown_sweep_task() -> int:
    try:
        return sweep()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"takedown sweep failed: {exc}")
        return 0


__all__ = ["BEAT_SCHEDULE", "sweep", "takedown_sweep_task"]
