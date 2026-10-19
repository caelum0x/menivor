"""Celery beat task that polls the social inbox.

Registered in ``app.workers.celery_app`` (``include`` + ``beat_schedule``). Each
run discovers newly published posts and polls the due ones; the per-tick and
per-creator caps in :mod:`.sync` keep platform API usage bounded.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

# Registers the extended-publish and engagement-autopilot tasks (and their beat
# entries) in every process that loads this include-listed module.
from app.workers import tasks_engagement as _tasks_engagement  # noqa: E402,F401

TASK_NAME = "app.domains.social_inbox.tasks.social_inbox_poll_task"


@celery_app.task(name=TASK_NAME, soft_time_limit=240, time_limit=270)
def social_inbox_poll_task() -> dict:
    try:
        from app.domains.social_inbox.sync import tick

        return tick()
    except Exception as exc:  # noqa: BLE001 - never crash the beat worker
        logger.error(f"social_inbox_poll_task failed: {exc}")
        return {"ok": False, "error": "social inbox poll failed"}
