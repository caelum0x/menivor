"""Celery beat: start due scheduled workflows and advance runs waiting on approvals.

Same scheduler as the Brand Agent routines (15 min tick). Never spends or publishes:
spend and publish steps are pending Brand Agent actions until a person approves them.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

TICK_SECONDS = 900.0
TASK_NAME = "app.domains.workflows.tasks.workflows_tick"

BEAT_SCHEDULE = {"workflows-tick": {"task": TASK_NAME, "schedule": TICK_SECONDS}}


@celery_app.task(name=TASK_NAME)
def workflows_tick() -> int:
    from app.domains.brand_agent import models as _agent  # noqa: F401  (registers tables)
    from app.domains.workflows import models as _models  # noqa: F401
    from app.domains.workflows import service
    from app.models.db.base import get_session

    with get_session() as session:
        started = service.run_due(session)
    if started:
        logger.info(f"workflows: started {started} scheduled run(s)")
    return started


__all__ = ["BEAT_SCHEDULE", "TASK_NAME", "workflows_tick"]
