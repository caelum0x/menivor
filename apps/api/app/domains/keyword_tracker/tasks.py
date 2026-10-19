"""Celery beat: refresh every tracked keyword's App Store rank about once a day.

Mirrors ``app.domains.competitors.tasks``. A single daily tick (not hourly) is
enough here because the rank reading itself goes through
``app.domains.appaudit.visibility``'s 24h cache — a tighter schedule would just
rebuild the same cached results.
"""

from __future__ import annotations

from celery.schedules import crontab
from loguru import logger

from app.workers.celery_app import celery_app

TASK_NAME = "app.domains.keyword_tracker.tasks.keyword_rank_refresh_tick"

# 05:00 UTC — after the appaudit visibility cache from the prior day has fully
# expired (24h TTL) and clear of the other daily crons (funnel 07:00, canary
# economics 07:15).
BEAT_SCHEDULE = {"keyword-tracker-rank-refresh": {"task": TASK_NAME, "schedule": crontab(minute=0, hour=5)}}


@celery_app.task(name=TASK_NAME)
def keyword_rank_refresh_tick() -> int:
    from app.domains.keyword_tracker import models as _models  # noqa: F401  (registers tables)
    from app.domains.keyword_tracker import service
    from app.models.db.base import get_session

    with get_session() as session:
        done = service.refresh_due(session)
    if done:
        logger.info(f"keyword tracker refreshed {done} keyword(s)")
    return done


__all__ = ["BEAT_SCHEDULE", "TASK_NAME", "keyword_rank_refresh_tick"]
