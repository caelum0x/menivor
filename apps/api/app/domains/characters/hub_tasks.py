"""Refund sweep for My characters (MH4): failed LoRA trainings paid in AI-video credits.

The worker's own failure hook refunds the standard-credit field
(``credits_cost``), which is 0 for hub trainings; this sweep returns the
AI-video credits still held by a failed hub training, once per job, from the
ledger. Every 10 minutes on the housekeeping queue; never raises.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

REFUND_TASK = "app.domains.characters.hub_tasks.refund_failed_trainings_task"

BEAT_SCHEDULE: dict[str, dict] = {
    "menivor-character-lora-refund": {"task": REFUND_TASK, "schedule": 10 * 60.0},
}


def sweep() -> int:
    from app.domains.characters import hub
    from app.models.db.base import get_session

    with get_session() as session:
        return hub.refund_failed_trainings(session)


@celery_app.task(name=REFUND_TASK)
def refund_failed_trainings_task() -> int:
    try:
        return sweep()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"character lora refund sweep failed: {exc}")
        return 0


__all__ = ["BEAT_SCHEDULE", "refund_failed_trainings_task", "sweep"]
