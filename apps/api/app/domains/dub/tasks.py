"""Celery task for "dub any uploaded video" (``generation`` queue).

Thin wrapper over :func:`app.domains.dub.service.run_dub_video`. One dub runs
per host (``sidecar.host_lock``); when the lock is held the task re-queues
itself with a countdown instead of blocking a worker slot. Terminal failure
(including exhausting the busy retries) marks the job failed and refunds its
credits exactly once.
"""

from __future__ import annotations

from celery import Task
from loguru import logger

from app.workers.celery_app import celery_app

BUSY_RETRY_COUNTDOWN_S = 60
BUSY_MAX_RETRIES = 90  # ~90 minutes of waiting for the host's single dub slot


def _job_id(args) -> str:
    ctx = args[0] if args else {}
    return str((ctx or {}).get("job_id", "")) if isinstance(ctx, dict) else ""


def mark_failed_and_refund(job_id: str, exc: BaseException) -> None:
    """Record the failure on the job and refund the debit (never raises)."""
    if not job_id:
        return
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).mark_failed(job_id, "dub", str(exc)[:500] or "dub failed")
    except Exception as mark_exc:  # noqa: BLE001
        logger.error(f"dub_video: mark_failed failed for {job_id}: {mark_exc}")
    from app.domains.dub.service import refund_dub_video

    refund_dub_video(job_id)


class DubVideoTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:  # noqa: D401
        job_id = _job_id(args)
        logger.error(f"dub_video failed for job {job_id}: {exc}")
        mark_failed_and_refund(job_id, exc)


@celery_app.task(
    name="app.domains.dub.tasks.run_dub_video_task",
    base=DubVideoTask,
    bind=True,
    max_retries=BUSY_MAX_RETRIES,
    soft_time_limit=4200,
    time_limit=4320,
)
def run_dub_video_task(self, ctx: dict) -> dict:
    from app.domains.dub.service import run_dub_video
    from app.domains.dub.sidecar import SidecarBusy

    job_id = str((ctx or {}).get("job_id", ""))
    try:
        result = run_dub_video(job_id)
    except SidecarBusy as exc:
        logger.info(f"dub_video: host busy, re-queueing job={job_id!r}")
        raise self.retry(exc=exc, countdown=BUSY_RETRY_COUNTDOWN_S)
    try:
        from app.workers.tasks import _notify_if_complete

        _notify_if_complete(job_id)
    except Exception as exc:  # noqa: BLE001 - notification is best-effort
        logger.debug(f"dub_video: completion notification skipped: {exc}")
    return result
