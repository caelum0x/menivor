"""Hourly OTT usage beat (MV7, Wave P PM3.1): minute 5 of every hour. Idempotent; never raises."""

from __future__ import annotations

from celery.schedules import crontab
from loguru import logger

from app.workers.celery_app import celery_app

USAGE_TASK = "app.services.billing.ott_usage_tasks.ott_usage_hourly_task"
BEAT_SCHEDULE: dict[str, dict] = {"menivor-ott-usage-hourly": {"task": USAGE_TASK, "schedule": crontab(minute=5)}}


def run() -> dict[str, int]:
    from app.domains.ott import flags
    from app.models.db.base import get_session
    from app.services.billing import ott_usage

    if not flags.enabled("plans"):
        return {"rows": 0, "rago": 0, "dodo": 0}
    try:
        sizer = ott_usage.r2_sizer()
    except Exception as exc:  # noqa: BLE001 - storage sizing is skipped when R2 is not configured
        logger.warning(f"ott usage: storage not sized this hour: {type(exc).__name__}")
        sizer = None
    with get_session() as session:
        result = ott_usage.tick(session, sizer=sizer)
    from app.services.billing import dodo_usage

    dodo_usage.flush_pending()
    return result


@celery_app.task(name=USAGE_TASK)
def ott_usage_hourly_task() -> dict[str, int]:
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - a beat tick never crashes the worker
        logger.error(f"ott usage tick failed: {exc}")
        return {"rows": 0, "rago": 0, "dodo": 0}


__all__ = ["BEAT_SCHEDULE", "USAGE_TASK", "ott_usage_hourly_task", "run"]
