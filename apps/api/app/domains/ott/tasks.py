"""OTT publish sweep (MV1): every minute, hide published titles that now fail the gate.

The takedown hook hides a title in the same transaction as the block; this beat
is the backstop (a later content verdict, or a hook that could not run).
Idempotent; never raises.

Wave Q QM1.2: the upload content check runs as a worker task
(:func:`upload_check_task`); the same minute tick re-queues checks still
pending after 10 minutes.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

SWEEP_TASK = "app.domains.ott.tasks.sweep_gate_task"
UPLOAD_CHECK_TASK = "app.domains.ott.tasks.upload_check_task"
PENDING_RETRY_S = 600
DOWNLOAD_TIMEOUT_S = 600
BEAT_SCHEDULE: dict[str, dict] = {"menivor-ott-gate-sweep": {"task": SWEEP_TASK, "schedule": 60.0}}


def sweep() -> int:
    from app.domains.ott import flags, service
    from app.models.db.base import get_session

    if not flags.enabled("cms"):
        return 0
    with get_session() as session:
        hidden = service.sweep_gate(session)
        stale = stale_checks(session)
    for title_id in stale:
        upload_check_task.apply_async(args=[title_id])
    return hidden


def stale_checks(session, *, now=None, limit: int = 50) -> list[str]:
    """Uploads still pending after :data:`PENDING_RETRY_S` (a lost queue message), oldest first."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from .upload_check import PENDING, OttUploadCheck

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(seconds=PENDING_RETRY_S)
    return list(session.execute(select(OttUploadCheck.title_id).where(
        OttUploadCheck.decision == PENDING, OttUploadCheck.created_at < cutoff)
        .order_by(OttUploadCheck.created_at).limit(limit)).scalars().all())


def download(source_key: str, dest_dir: str) -> str:
    """Fetch an upload from the OTT bucket to ``dest_dir`` through a short-lived presigned URL."""
    import os

    import httpx

    from app.services.ott_transcode.router import storage

    url = storage().presign_get(source_key, 900)
    path = os.path.join(dest_dir, "source")
    with httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT_S) as resp:
        resp.raise_for_status()
        with open(path, "wb") as out:
            for chunk in resp.iter_bytes(1 << 20):
                out.write(chunk)
    return path


def check_upload(title_id: str) -> str:
    from app.models.db.base import get_session
    from app.services.ott_transcode.service import paid_plan

    from . import upload_check

    with get_session() as session:
        row = session.get(upload_check.OttUploadCheck, title_id)
        if row is None:
            return "missing"
        done = upload_check.run_check(session, title_id, fetch=download, paid=paid_plan(row.user_id))
        return done.decision if done is not None else "missing"


@celery_app.task(name=SWEEP_TASK)
def sweep_gate_task() -> int:
    try:
        return sweep()
    except Exception as exc:  # noqa: BLE001 - a beat tick never crashes the worker
        logger.error(f"ott gate sweep failed: {exc}")
        return 0


@celery_app.task(name=UPLOAD_CHECK_TASK)
def upload_check_task(title_id: str) -> str:
    try:
        return check_upload(title_id)
    except Exception as exc:  # noqa: BLE001 - the row stays pending and the sweep retries it
        logger.error(f"ott upload check {title_id} failed: {exc}")
        return "error"


__all__ = ["BEAT_SCHEDULE", "SWEEP_TASK", "UPLOAD_CHECK_TASK", "check_upload", "download", "stale_checks",
           "sweep", "sweep_gate_task", "upload_check_task"]
