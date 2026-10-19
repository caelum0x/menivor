"""QoE rollups (MV12, Wave P PM3.5): minute 7 of every hour for the last two hours; raw beacons and spent ad-event rows swept daily."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from celery.schedules import crontab
from loguru import logger

from app.workers.celery_app import celery_app

ROLLUP_TASK = "app.domains.ott_analytics.tasks.rollup_task"
SWEEP_TASK = "app.domains.ott_analytics.tasks.sweep_task"
BEAT_SCHEDULE: dict[str, dict] = {
    "menivor-ott-qoe-rollup": {"task": ROLLUP_TASK, "schedule": crontab(minute=7)},
    "menivor-ott-qoe-sweep": {"task": SWEEP_TASK, "schedule": crontab(minute=20, hour=4)},
}


def run_rollup(at: datetime | None = None) -> int:
    from app.domains.ott import flags
    from app.models.db.base import get_session

    from . import service

    if not flags.enabled("analytics"):
        return 0
    moment = at or datetime.now(timezone.utc)
    written = 0
    with get_session() as session:
        for back in (1, 0):
            written += service.rollup(session, service.hour_key(moment - timedelta(hours=back)))
    return written


@celery_app.task(name=ROLLUP_TASK)
def rollup_task() -> int:
    try:
        return run_rollup()
    except Exception as exc:  # noqa: BLE001 - a beat tick never crashes the worker
        logger.error(f"ott qoe rollup failed: {exc}")
        return 0


@celery_app.task(name=SWEEP_TASK)
def sweep_task() -> int:
    from app.models.db.base import get_session

    from app.domains.ott_ads import service as ads

    from . import service

    try:
        with get_session() as session:
            return service.sweep(session) + ads.sweep_events(session)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"ott beacon sweep failed: {exc}")
        return 0


__all__ = ["BEAT_SCHEDULE", "ROLLUP_TASK", "SWEEP_TASK", "rollup_task", "run_rollup", "sweep_task"]
