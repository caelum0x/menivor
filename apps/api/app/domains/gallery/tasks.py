"""Gallery remix settlement (MH3): count kept Recreate remixes every 5 minutes.

Runs on the housekeeping queue (registered as an optional task module in
``app/workers/celery_app.py``). Idempotent; never raises.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

SETTLE_TASK = "app.domains.gallery.tasks.settle_remixes_task"

BEAT_SCHEDULE: dict[str, dict] = {
    "menivor-gallery-remix-settle": {"task": SETTLE_TASK, "schedule": 5 * 60.0},
}


def settle() -> int:
    from app.domains.gallery import service
    from app.models.db.base import get_session

    with get_session() as session:
        return service.settle_remixes(session)


@celery_app.task(name=SETTLE_TASK)
def settle_remixes_task() -> int:
    try:
        return settle()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"gallery remix settle failed: {exc}")
        return 0


__all__ = ["BEAT_SCHEDULE", "settle", "settle_remixes_task"]
