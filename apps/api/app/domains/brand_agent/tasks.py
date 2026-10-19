"""Celery beat: queue due Brand Agent routines as pending approval actions.

Registered through ``_OPTIONAL_TASK_MODULES`` in ``app/workers/celery_app.py``;
``BEAT_SCHEDULE`` is picked up there and routed to the housekeeping queue. The
tick never spends or publishes: it only creates ``pending`` actions.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

TICK_SECONDS = 900.0
TASK_NAME = "app.domains.brand_agent.tasks.brand_agent_routines_tick"

BEAT_SCHEDULE = {
    "brand-agent-routines": {"task": TASK_NAME, "schedule": TICK_SECONDS},
}


@celery_app.task(name=TASK_NAME)
def brand_agent_routines_tick() -> int:
    from app.domains.brand_agent import models as _models  # noqa: F401  (registers tables)
    from app.domains.brand_agent import routines
    from app.models.db.base import get_session

    with get_session() as session:
        ran = routines.run_due(session)
    if ran:
        logger.info(f"brand agent routines queued {ran} batch(es) for approval")
    return ran


__all__ = ["BEAT_SCHEDULE", "TASK_NAME", "brand_agent_routines_tick"]
