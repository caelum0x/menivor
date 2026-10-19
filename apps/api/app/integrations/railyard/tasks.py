"""Railyard meter outbox flush (Wave P PM1.5): every 5 minutes on the housekeeping queue.

Sends pending Rago events and Mint mirror entries when ``RAILYARD_LIVE=1``;
a no-op otherwise. Never raises.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

FLUSH_TASK = "app.integrations.railyard.tasks.flush_meter_outbox_task"

BEAT_SCHEDULE: dict[str, dict] = {
    "menivor-railyard-meter-flush": {"task": FLUSH_TASK, "schedule": 5 * 60.0},
}


def flush_all() -> dict[str, int]:
    from app.integrations.railyard import meters
    from app.models.db.base import get_session

    with get_session() as session:
        return {
            "rago": meters.flush(session, channel=meters.CHANNEL_RAGO),
            "mint": meters.flush(session, channel=meters.CHANNEL_MINT),
        }


@celery_app.task(name=FLUSH_TASK)
def flush_meter_outbox_task() -> dict[str, int]:
    try:
        return flush_all()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"railyard meter flush failed: {exc}")
        return {"rago": 0, "mint": 0}


__all__ = ["BEAT_SCHEDULE", "flush_all", "flush_meter_outbox_task"]
