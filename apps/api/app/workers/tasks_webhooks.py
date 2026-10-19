"""Webhook reliability ticks (MN8).

* ``retry_webhook_deliveries_task`` (every minute): gives every due ``pending``
  delivery one more signed attempt with capped exponential backoff; after
  ``MAX_DELIVERY_ATTEMPTS`` a delivery is marked ``dead`` and never retried.
* ``emit_job_failed_task`` (every minute): sends ``job.failed`` (with the job's
  real ``refunded`` state) to workspaces subscribed to it.

Both are idempotent "process whatever is due now" passes that never raise, so
they run on the ``housekeeping`` queue (routed by
``app.workers.celery_app.housekeeping_beat``). ``MENIVOR_WEBHOOK_TICKS=0``
turns both off.
"""

from __future__ import annotations

import os

from loguru import logger

from app.workers.celery_app import celery_app

RETRY_TASK = "app.workers.tasks_webhooks.retry_webhook_deliveries_task"
JOB_FAILED_TASK = "app.workers.tasks_webhooks.emit_job_failed_task"
#: Deliveries attempted per retry tick.
RETRY_BATCH: int = 100

BEAT_SCHEDULE: dict[str, dict] = {
    "menivor-webhook-retry": {"task": RETRY_TASK, "schedule": 60.0},
    "menivor-webhook-job-failed": {"task": JOB_FAILED_TASK, "schedule": 60.0},
}


def ticks_enabled() -> bool:
    return os.environ.get("MENIVOR_WEBHOOK_TICKS", "1").strip().lower() not in {"0", "false", "off", "no"}


def retry_deliveries() -> dict[str, int]:
    """One retry pass. Returns counts by resulting status."""
    if not ticks_enabled():
        return {"attempted": 0}
    from app.models.db.base import get_session
    from app.services import webhook_subscriptions

    with get_session() as session:
        rows = webhook_subscriptions.retry_pending(session, limit=RETRY_BATCH)
        counts: dict[str, int] = {"attempted": len(rows)}
        for row in rows:
            counts[row.status] = counts.get(row.status, 0) + 1
    return counts


def emit_job_failed() -> dict[str, int]:
    """One ``job.failed`` sweep. Returns the number of jobs examined."""
    if not ticks_enabled():
        return {"jobs": 0}
    from app.models.db.base import get_session
    from app.services.webhook_job_events import emit_failed_jobs

    with get_session() as session:
        return {"jobs": emit_failed_jobs(session)}


@celery_app.task(name=RETRY_TASK)
def retry_webhook_deliveries_task() -> dict[str, int]:
    try:
        return retry_deliveries()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"webhook retry tick failed: {exc}")
        return {"attempted": 0}


@celery_app.task(name=JOB_FAILED_TASK)
def emit_job_failed_task() -> dict[str, int]:
    try:
        return emit_job_failed()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"job.failed webhook tick failed: {exc}")
        return {"jobs": 0}


__all__ = [
    "BEAT_SCHEDULE",
    "emit_job_failed",
    "emit_job_failed_task",
    "retry_deliveries",
    "retry_webhook_deliveries_task",
    "ticks_enabled",
]
