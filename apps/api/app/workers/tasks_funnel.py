"""Celery beat: activation funnel sync + weekly owner funnel email.

* ``funnel_tick_task`` runs daily at 07:00 UTC and hourly 07:30-11:30 UTC on
  Mondays. Each tick records new first-time funnel steps; on Monday from 07:00
  UTC it sends the week's owner funnel email once (a failed send is retried by
  the next Monday tick). Never raises, so a bad tick cannot crash beat.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

FUNNEL_TASK = "app.workers.tasks_funnel.funnel_tick_task"


@celery_app.task(name=FUNNEL_TASK, soft_time_limit=240, time_limit=270)
def funnel_tick_task() -> dict:
    try:
        from app.services.funnel import weekly

        return weekly.run()
    except Exception as exc:  # noqa: BLE001 - never crash the beat worker
        logger.error(f"funnel_tick_task failed: {type(exc).__name__}: {exc}")
        return {"status": "error"}

# Beat entries and the queue route live in app/workers/celery_app.py.
