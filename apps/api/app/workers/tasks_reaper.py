"""Stuck-reel reaper: retry once, then stop, refund and tell the owner.

A reel is *stalled* when its row has not changed (``Job.updated_at``: every
stage start, stage end and progress write bumps it) for longer than twice the
hard time limit of the stage it is in. A reel that is only waiting for a render
slot is not stalled: the wait for the reels ahead of it (measured per-reel time,
or the compose limit when there is no history) is added to its allowance.

First stall: the job is re-enqueued from that stage (``retry_pipeline``, no new
debit; it is the same paid run) and marked ``stages["_reaper"]``. Second stall:
the job is failed and every credit it holds is returned
(:func:`app.domains.reels.refunds.fail_and_refund_stalled_reel`), the owner
gets the in-app notification, a push and one email.

Runs every minute on the ``housekeeping`` queue (routed by
``app.workers.celery_app.housekeeping_beat``). ``MENIVOR_REAPER=0`` turns it
off. Never raises.
"""

from __future__ import annotations

import dataclasses
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.models import const
from app.workers.celery_app import celery_app

REEL_KIND = "avatar_reel"
REAPER_MARKER = "_reaper"
#: Hard ``time_limit`` of each stage task (app/workers/tasks.py), seconds.
STAGE_LIMITS_S: dict[str, float] = {
    "script": 150.0,
    "tts": 210.0,
    "avatar": 1860.0,
    "captions": 150.0,
    "compose": 660.0,
    "upload": 150.0,
}
STAGE_ORDER: tuple[str, ...] = ("script", "tts", "avatar", "captions", "compose", "upload")
STALL_FACTOR = 2.0
#: Reels examined per tick (oldest first); the rest wait for the next minute.
BATCH_LIMIT = 25
#: Reels older than this are never retried, only stopped and refunded.
MAX_AGE = timedelta(hours=6)
REAP_INTERVAL_S = 60.0


def reaper_enabled() -> bool:
    return str(os.getenv("MENIVOR_REAPER", "1")).strip().lower() not in {"0", "false", "off", "no"}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def current_stage(stages: dict | None) -> tuple[str, bool]:
    """``(stage, running)``: the running stage, else the next one not complete."""
    stages = stages or {}
    for stage in STAGE_ORDER:
        if stages.get(stage) == const.REELFORGE_STAGE_RUNNING:
            return stage, True
    for stage in STAGE_ORDER:
        if stages.get(stage) != const.REELFORGE_STAGE_COMPLETE:
            return stage, False
    return "upload", False


def stall_limit_s(stage: str, *, running: bool, ahead: int, slots: int, per_reel_s: float | None) -> float:
    """Seconds without progress after which a reel in ``stage`` is stalled."""
    base = STALL_FACTOR * STAGE_LIMITS_S.get(stage, STAGE_LIMITS_S["compose"])
    if running or ahead <= 0:
        return base
    per_reel = per_reel_s if per_reel_s and per_reel_s > 0 else STAGE_LIMITS_S["compose"]
    return base + math.ceil(ahead / max(1, slots)) * per_reel


def _params_for_retry(job: Any) -> Any:
    from app.services.reelforge import ReelForgeParams

    stored = dict(job.params) if isinstance(job.params, dict) else {}
    allowed = {field.name for field in dataclasses.fields(ReelForgeParams)}
    data = {key: value for key, value in stored.items() if key in allowed}
    for key in ("platforms", "effects"):
        if isinstance(data.get(key), list):
            data[key] = tuple(data[key])
    return ReelForgeParams(**data)


def _candidates(session: Any, now: datetime) -> list[str]:
    from sqlalchemy import select

    from app.models.db.models import Job

    floor = now - timedelta(seconds=STALL_FACTOR * min(STAGE_LIMITS_S.values()))
    rows = session.execute(
        select(Job.id)
        .where(
            Job.state == const.TASK_STATE_PROCESSING,
            Job.kind == REEL_KIND,
            Job.deleted_at.is_(None),
            Job.updated_at < floor,
        )
        .order_by(Job.updated_at.asc())
        .limit(BATCH_LIMIT)
    ).scalars().all()
    return [str(row) for row in rows]


def _examine(job_id: str, now: datetime) -> tuple[str, str] | None:
    """``(action, stage)`` for a stalled job (``retry`` / ``stop``), else None.

    ``retry`` is claimed here: the marker is written and the old chain id read
    under the row lock, so two reaper ticks never both retry the same job.
    """
    from app.domains.reels import queue_eta
    from app.domains.reels.refunds import _locked_job
    from app.models.db.base import get_session

    with get_session() as session:
        job = _locked_job(session, job_id)
        if job is None or job.state != const.TASK_STATE_PROCESSING:
            return None
        updated = _aware(job.updated_at) or now
        stage, running = current_stage(job.stages)
        ahead = 0 if running else queue_eta.jobs_ahead(session, job)
        limit = stall_limit_s(
            stage,
            running=running,
            ahead=ahead,
            slots=queue_eta.render_slots(),
            per_reel_s=None if running else queue_eta.measured_reel_seconds(session),
        )
        if (now - updated).total_seconds() < limit:
            return None
        created = _aware(job.created_at) or now
        if REAPER_MARKER in (job.stages or {}) or now - created > MAX_AGE:
            return "stop", stage
        job.stages = {
            **(job.stages or {}),
            REAPER_MARKER: {"retried_at": now.isoformat(timespec="seconds"), "stage": stage},
        }
        return "retry", stage


def _retry(job_id: str, stage: str) -> bool:
    """Re-enqueue from ``stage``; False when that is impossible (caller stops)."""
    from app.domains.reels.refunds import _revoke_celery
    from app.models.db.base import get_session
    from app.models.db.models import Job
    from app.models.db.repositories import JobRepository
    from app.workers import pipeline

    try:
        with get_session() as session:
            job = session.get(Job, job_id)
            if job is None or job.state != const.TASK_STATE_PROCESSING:
                return True
            params = _params_for_retry(job)
            old_task = str(job.celery_task_id or "")
            # The stalled stage is re-run: clear its "running" mark so the
            # progress view and the next reaper pass see it as pending.
            stages = dict(job.stages or {})
            if stages.get(stage) == const.REELFORGE_STAGE_RUNNING:
                stages[stage] = const.REELFORGE_STAGE_PENDING
            job.stages = stages
        _revoke_celery(old_task)
        new_task = pipeline.retry_pipeline(job_id, params, stage)
        with get_session() as session:
            JobRepository(session).set_celery_task_id(job_id, new_task)
        logger.warning(f"reaper: job {job_id} stalled at {stage!r}; retried once (task {new_task})")
        return True
    except Exception as exc:  # noqa: BLE001 - an impossible retry becomes a refund
        logger.error(f"reaper: retry of stalled job {job_id} failed: {type(exc).__name__}: {exc}")
        return False


def _stop(job_id: str, stage: str) -> dict[str, Any]:
    from app.domains.reels.refunds import STALLED_ERROR, fail_and_refund_stalled_reel

    outcome = fail_and_refund_stalled_reel(job_id, stage)
    if not outcome["failed"]:
        return outcome
    logger.warning(
        f"reaper: job {job_id} stalled again at {stage!r}; stopped, "
        f"refunded {outcome['refunded_credits']} credit(s)"
    )
    try:
        from app.models.db.base import get_session
        from app.models.db.models import Job
        from app.services import notifications

        with get_session() as session:
            job = session.get(Job, job_id)
            user_id = str(job.user_id) if job is not None else ""
        if user_id:
            notifications.notify_job_failed(user_id, job_id, STALLED_ERROR)
    except Exception as exc:  # noqa: BLE001 - notification is best-effort
        logger.warning(f"reaper: notification for job {job_id} failed: {exc}")
    from app.services.job_emails import send_reel_stopped_email

    outcome["emailed"] = send_reel_stopped_email(job_id)
    return outcome


def reap_stalled_reels(now: datetime | None = None) -> dict[str, int]:
    """One reaper pass. Returns ``{"examined", "retried", "stopped"}``."""
    summary = {"examined": 0, "retried": 0, "stopped": 0}
    if not reaper_enabled():
        return summary
    clock = now or datetime.now(timezone.utc)
    try:
        from app.models.db.base import get_session

        with get_session() as session:
            candidates = _candidates(session, clock)
    except Exception as exc:  # noqa: BLE001 - a DB hiccup waits for the next tick
        logger.warning(f"reaper: could not list stalled reels: {exc}")
        return summary
    for job_id in candidates:
        summary["examined"] += 1
        try:
            decision = _examine(job_id, clock)
            if decision is None:
                continue
            action, stage = decision
            if action == "retry" and _retry(job_id, stage):
                summary["retried"] += 1
                continue
            if _stop(job_id, stage)["failed"]:
                summary["stopped"] += 1
        except Exception as exc:  # noqa: BLE001 - one bad job never blocks the rest
            logger.error(f"reaper: job {job_id} could not be handled: {type(exc).__name__}: {exc}")
    return summary


@celery_app.task(name="app.workers.tasks_reaper.reap_stalled_reels_task")
def reap_stalled_reels_task() -> dict[str, int]:
    return reap_stalled_reels()


__all__ = [
    "REAPER_MARKER",
    "STAGE_LIMITS_S",
    "current_stage",
    "reap_stalled_reels",
    "reap_stalled_reels_task",
    "reaper_enabled",
    "stall_limit_s",
]
