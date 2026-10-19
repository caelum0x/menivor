"""Celery tasks for extended publishing and the engagement autopilot.

* ``extended_publish_due_task`` (every minute) - runs due scheduled posts to
  Facebook / LinkedIn / X / Threads / Pinterest / Bluesky and re-polls posts
  the platform is still processing.
* ``run_platform_post_task`` - "post now": advances one post immediately.
* ``engagement_autopilot_task`` (every 5 minutes) - applies each creator's
  autopilot rules to new inbox comments and DMs.

Registration: this module is imported by ``app.domains.social_inbox.tasks``
(already in the worker's ``include`` list), and it adds its two periodic
entries to the beat schedule at import time. Beat imports the include list
before it builds its schedule, so no edit to ``celery_app.py`` is required;
listing this module there explicitly is still the cleaner long-term home.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import HOUSEKEEPING_QUEUE, celery_app, housekeeping_beat

DUE_TASK = "app.workers.tasks_engagement.extended_publish_due_task"
POST_TASK = "app.workers.tasks_engagement.run_platform_post_task"
AUTOPILOT_TASK = "app.workers.tasks_engagement.engagement_autopilot_task"


@celery_app.task(name=DUE_TASK, soft_time_limit=55, time_limit=60)
def extended_publish_due_task() -> dict:
    try:
        from app.domains.publishing.extended.posts import tick

        return tick()
    except Exception as exc:  # noqa: BLE001 - never crash the beat worker
        logger.error(f"extended_publish_due_task failed: {exc}")
        return {"ok": False, "error": "extended publish tick failed"}


@celery_app.task(name=POST_TASK, soft_time_limit=900, time_limit=960)
def run_platform_post_task(post_id: str) -> dict:
    try:
        from app.domains.publishing.extended.posts import run_post

        return run_post(str(post_id))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"run_platform_post_task failed for {post_id}: {exc}")
        return {"id": str(post_id), "status": "error"}


@celery_app.task(name=AUTOPILOT_TASK, soft_time_limit=240, time_limit=270)
def engagement_autopilot_task() -> dict:
    try:
        from app.domains.social_inbox.autopilot import tick

        return tick()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"engagement_autopilot_task failed: {exc}")
        return {"ok": False, "error": "engagement autopilot tick failed"}


_BEAT_ENTRIES = {
    "reelforge-extended-publish-due": {"task": DUE_TASK, "schedule": 60.0},
    "reelforge-engagement-autopilot": {"task": AUTOPILOT_TASK, "schedule": 5 * 60.0},
}
# Publishing and autopilot are HTTP-only housekeeping: they run on the
# housekeeping worker so a scheduled post never waits behind a reel render.
_ROUTES = {
    POST_TASK: {"queue": HOUSEKEEPING_QUEUE},
}

celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    **housekeeping_beat(_BEAT_ENTRIES),
}
celery_app.conf.task_routes = {**(celery_app.conf.task_routes or {}), **_ROUTES}
