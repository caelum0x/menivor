"""Live housekeeping (MV10, Wave P PM3.4): every 10 minutes close streams whose end hook was lost. Never raises."""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

SWEEP_TASK = "app.domains.ott_live.tasks.sweep_stale_task"
BEAT_SCHEDULE: dict[str, dict] = {"menivor-ott-live-sweep": {"task": SWEEP_TASK, "schedule": 10 * 60.0}}


def run() -> int:
    from app.domains.ott import flags
    from app.models.db.base import get_session

    from . import service

    if not flags.enabled("live"):
        return 0
    with get_session() as session:
        return service.sweep_stale(session)


@celery_app.task(name=SWEEP_TASK)
def sweep_stale_task() -> int:
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - a beat tick never crashes the worker
        logger.error(f"ott live sweep failed: {exc}")
        return 0


__all__ = ["BEAT_SCHEDULE", "SWEEP_TASK", "run", "sweep_stale_task"]
