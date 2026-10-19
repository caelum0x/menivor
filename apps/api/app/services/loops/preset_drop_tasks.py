"""Beat for the weekly preset drop (MH9, Wave P PM3.0): Mondays 09:00 UTC. Idempotent; never raises."""

from __future__ import annotations

from typing import Any

from celery.schedules import crontab
from loguru import logger

from app.workers.celery_app import celery_app

DROP_TASK = "app.services.loops.preset_drop_tasks.publish_weekly_drop_task"
BEAT_SCHEDULE: dict[str, dict] = {
    "menivor-preset-weekly-drop": {"task": DROP_TASK, "schedule": crontab(minute=0, hour=9, day_of_week="mon")},
}


@celery_app.task(name=DROP_TASK)
def publish_weekly_drop_task() -> dict[str, Any]:
    from app.services.loops import preset_drop

    try:
        return preset_drop.run_weekly()
    except Exception as exc:  # noqa: BLE001 - a beat tick never crashes the worker
        logger.error(f"preset drop failed: {exc}")
        return {"published": False, "reason": "error"}


__all__ = ["BEAT_SCHEDULE", "DROP_TASK", "publish_weekly_drop_task"]
