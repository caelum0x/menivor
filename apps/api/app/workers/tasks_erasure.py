"""Erasure follow-up retries (MG1): finish every account delete that is pending.

``erase_user`` runs the follow-up steps inline (cancel billing, stop renders,
delete R2 media, delete the Clerk user, record the forfeited balance, confirm by
email). A step that failed (provider outage, R2 error, SMTP down) is left
pending in the audit log; this task re-runs only the unfinished steps.

Registration (hand-off to M1.5, the sole Wave B owner of ``celery_app.py``): add
``"app.workers.tasks_erasure"`` to ``include`` and a beat entry, for example::

    "erasure-followups": {
        "task": "app.workers.tasks_erasure.retry_erasure_followups_task",
        "schedule": 900.0,
    },

``MENIVOR_ERASURE_RETRY=0`` turns it off. Never raises.
"""

from __future__ import annotations

import os

from loguru import logger

from app.workers.celery_app import celery_app


def retry_enabled() -> bool:
    return (os.environ.get("MENIVOR_ERASURE_RETRY") or "1").strip().lower() not in {"0", "false", "off"}


def retry_erasure_followups() -> dict[str, int]:
    """Re-run unfinished erasure steps. Returns ``{requests, failed_steps}``."""
    if not retry_enabled():
        return {"requests": 0, "failed_steps": 0}
    try:
        from app.services.compliance import erasure_followups

        return erasure_followups.retry_pending()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"erasure follow-up retry failed: {exc}")
        return {"requests": 0, "failed_steps": -1}


#: Picked up by ``celery_app._optional_beat_entries`` (M1.5) once this module is
#: in the tree, and routed to the housekeeping queue there.
BEAT_SCHEDULE: dict[str, dict] = {
    "erasure-followups": {
        "task": "app.workers.tasks_erasure.retry_erasure_followups_task",
        "schedule": 900.0,
    },
}


@celery_app.task(name="app.workers.tasks_erasure.retry_erasure_followups_task")
def retry_erasure_followups_task() -> dict[str, int]:
    return retry_erasure_followups()


__all__ = ["BEAT_SCHEDULE", "retry_enabled", "retry_erasure_followups", "retry_erasure_followups_task"]
