"""Celery beat: refresh tracked competitor brands about once a day (official APIs only)."""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

TICK_SECONDS = 3600.0
TASK_NAME = "app.domains.competitors.tasks.competitor_refresh_tick"

BEAT_SCHEDULE = {"competitor-refresh": {"task": TASK_NAME, "schedule": TICK_SECONDS}}


@celery_app.task(name=TASK_NAME)
def competitor_refresh_tick() -> int:
    from app.domains.competitors import models as _models  # noqa: F401  (registers tables)
    from app.domains.competitors import service
    from app.models.db.base import get_session

    with get_session() as session:
        done = service.refresh_due(session)
    if done:
        logger.info(f"competitor tracker refreshed {done} brand(s)")
    return done


__all__ = ["BEAT_SCHEDULE", "TASK_NAME", "competitor_refresh_tick"]
