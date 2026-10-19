"""Canary reel, render alerts and the daily economics email (M1.5).

* ``canary_reel_task`` (every 6 h): renders one faceless reel with a fixed
  script and a free voice for the canary account (``MENIVOR_CANARY_USER_ID``).
  No LLM, no paid provider, no credit debit, no publishing. Skipped (with a
  log) when the account is not configured.
* ``canary_check_task`` (every 5 min): alerts when the latest canary has been
  rendering for more than ``MENIVOR_CANARY_MAX_MIN`` (default 10) minutes, or
  when it failed.
* ``render_alerts_task`` (every 5 min): queue wait p90, hourly failure rate,
  stuck reels and provider spend (``domains.observability.render_metrics``).
* ``economics_daily_task`` (daily 07:15 UTC): the owner unit-economics email
  (``services.funnel.weekly.run_daily_economics``).

All four run on the ``housekeeping`` queue (``celery_app.housekeeping_beat``)
except the canary render itself, which goes through the normal pipeline on the
bulk lane like any other reel. ``MENIVOR_CANARY=off`` / ``MENIVOR_RENDER_ALERTS=off``
turn the canary / alerts off. No task ever raises.
"""

from __future__ import annotations

import dataclasses
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from loguru import logger

from app.domains.observability import render_metrics as rm
from app.models import const
from app.workers.celery_app import celery_app

_OFF = {"0", "off", "false", "no", "disabled"}
CANARY_INTERVAL_S = 6 * 60 * 60.0
CHECK_INTERVAL_S = 5 * 60.0
DEFAULT_MAX_MIN = 10.0
CANARY_SCRIPT = (
    "This is the Menivor canary. Every six hours it renders one short reel "
    "to prove that script, voice, captions and compose all still work. "
    "If you can hear this, the render path is healthy."
)
CANARY_BACKGROUND = "voxel-parkour"
_CANARY_DONE = "_canary_alerted"


def _flag_on(name: str) -> bool:
    return str(os.getenv(name, "on")).strip().lower() not in _OFF


def canary_user_id() -> str:
    return str(os.getenv("MENIVOR_CANARY_USER_ID", "") or "").strip()


def canary_max_seconds() -> float:
    raw = str(os.getenv("MENIVOR_CANARY_MAX_MIN", "") or "").strip()
    try:
        minutes = float(raw) if raw else DEFAULT_MAX_MIN
    except ValueError:
        minutes = DEFAULT_MAX_MIN
    return max(1.0, minutes) * 60.0


def canary_params() -> Any:
    """Faceless free-voice reel, fixed script, no upload, no watermark."""
    from app.core.launch.formats import free_voice_for
    from app.services.reelforge import ReelForgeParams

    return ReelForgeParams(
        video_subject="Menivor canary",
        video_script=CANARY_SCRIPT,
        voice_name=free_voice_for("en"),
        language="en",
        layout="captions_only",
        background_id=os.getenv("MENIVOR_CANARY_BACKGROUND", "") or CANARY_BACKGROUND,
        target_duration_s=15,
        platforms=(),
        watermark_enabled=False,
    )


def start_canary(
    *,
    session_factory: Callable[[], Any] | None = None,
    start_fn: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Create and enqueue one canary reel. Never raises."""
    if not _flag_on("MENIVOR_CANARY"):
        return {"status": "disabled"}
    user_id = canary_user_id()
    if not user_id:
        logger.info("canary skipped: MENIVOR_CANARY_USER_ID is not set")
        return {"status": "not_configured"}
    try:
        from app.domains.reels.policy import LANE_BULK, lanes_enabled
        from app.models.db.repositories import JobRepository

        if session_factory is None:
            from app.models.db.base import get_session as session_factory
        if start_fn is None:
            from app.workers.pipeline import start_pipeline as start_fn

        params = canary_params()
        body = {**dataclasses.asdict(params), rm.CANARY_PARAM: True}
        with session_factory() as session:
            job = JobRepository(session).create(user_id=user_id, kind=rm.REEL_KIND, params=body)
            job_id = job.id
        # Bulk lane only once every lane queue has a consumer; until then the
        # historical ``render`` queue (an explicit lane would bypass that switch).
        task_id = start_fn(job_id, params, LANE_BULK if lanes_enabled() else "")
        with session_factory() as session:
            from app.models.db.models import Job

            row = session.get(Job, job_id)
            if row is not None:
                row.celery_task_id = str(task_id or "")
        logger.info(f"canary reel {job_id} enqueued")
        return {"status": "started", "job_id": job_id}
    except Exception as exc:  # noqa: BLE001 - a canary never breaks the beat
        logger.error(f"canary could not start: {exc}")
        rm.notify(
            [rm.Alert("canary_start", "Menivor: canary could not start", f"The canary reel could not be queued: {exc}")]
        )
        return {"status": "error", "error": str(exc)}


def canary_verdict(job: Any, now: datetime, max_s: float) -> rm.Alert | None:
    """The alert for the latest canary reel, or ``None`` when it is fine."""
    if job is None:
        return None
    created = rm._aware(job.created_at)
    age = (rm._aware(now) - created).total_seconds() if created else 0.0
    if job.state == const.TASK_STATE_FAILED:
        stage = getattr(job, "failed_stage", "") or "unknown stage"
        return rm.Alert(
            f"canary_failed:{job.id}",
            "Menivor: canary reel failed",
            f"Canary reel {job.id} failed at {stage}: {(getattr(job, 'error', '') or '')[:200]}",
        )
    if job.state == const.TASK_STATE_PROCESSING and age > max_s:
        return rm.Alert(
            f"canary_slow:{job.id}",
            "Menivor: canary reel is slow",
            f"Canary reel {job.id} is still rendering after {age / 60.0:.1f} min "
            f"(limit {max_s / 60.0:.0f} min).",
        )
    return None


def latest_canary(session: Any, now: datetime) -> Any:
    from sqlalchemy import select

    from app.models.db.models import Job

    user_id = canary_user_id()
    if not user_id:
        return None
    since = rm._aware(now) - timedelta(seconds=CANARY_INTERVAL_S * 2)
    rows = session.execute(
        select(Job)
        .where(Job.user_id == user_id, Job.kind == rm.REEL_KIND, Job.created_at >= since)
        .order_by(Job.created_at.desc())
        .limit(5)
    ).scalars()
    return next((j for j in rows if (j.params or {}).get(rm.CANARY_PARAM)), None)


def check_canary(
    now: datetime | None = None,
    *,
    session_factory: Callable[[], Any] | None = None,
    notify: Callable[[list[rm.Alert]], list[str]] | None = None,
) -> dict[str, Any]:
    """Alert on a slow or failed canary. Never raises."""
    now = rm._aware(now or datetime.now(timezone.utc))
    try:
        if session_factory is None:
            from app.models.db.base import get_session as session_factory
        with session_factory() as session:
            job = latest_canary(session, now)
            alert = canary_verdict(job, now, canary_max_seconds())
            job_id = getattr(job, "id", None)
        if alert is None:
            return {"status": "ok" if job_id else "no_canary", "job_id": job_id}
        sent = (notify or rm.notify)([alert])
        return {"status": "alert", "job_id": job_id, "alert": alert.key, "sent": bool(sent)}
    except Exception as exc:  # noqa: BLE001
        logger.error(f"canary check failed: {exc}")
        return {"status": "error", "error": str(exc)}


@celery_app.task(name="app.workers.tasks_canary.canary_reel_task")
def canary_reel_task() -> dict[str, Any]:
    return start_canary()


@celery_app.task(name="app.workers.tasks_canary.canary_check_task")
def canary_check_task() -> dict[str, Any]:
    return check_canary()


@celery_app.task(name="app.workers.tasks_canary.render_alerts_task")
def render_alerts_task() -> dict[str, Any]:
    if not _flag_on("MENIVOR_RENDER_ALERTS"):
        return {"status": "disabled"}
    try:
        return rm.run_alerts()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"render alerts tick failed: {exc}")
        return {"status": "error", "error": str(exc)}


@celery_app.task(name="app.workers.tasks_canary.economics_daily_task")
def economics_daily_task() -> dict[str, Any]:
    try:
        from app.services.funnel import weekly

        return weekly.run_daily_economics()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"daily economics email failed: {exc}")
        return {"status": "error", "error": str(exc)}
