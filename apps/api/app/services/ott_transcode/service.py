"""OTT encode jobs (MV2/MV3): submit a title for packaging, then finish or fail it.

``submit`` picks the lane (``picker.pick``), creates an ``ott_encode_jobs`` row
and, for box 1, enqueues the Celery task; Mac and burst jobs wait for a node to
claim them (``mac_node``). ``finish`` records node, CPU seconds and cost, marks
the title packaged and points it at its master playlist, then lets
``ott.events.maybe_title_published`` announce a title that was published
before it was packaged.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.ott.models import OttTitle

from . import nodes, picker
from .models import CLAIMED, DONE, FAILED, LANE_BOX1, LANE_BURST, LANE_MAC, QUEUED, OttEncodeJob

KEY_PATH = "/api/v1/ott/keys/{title_id}"
#: The longest source any lane accepts (the upload form caps ``seconds`` at 6 hours too).
MAX_SOURCE_S = 6 * 3600.0


class TranscodeError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def now() -> datetime:
    return datetime.now(timezone.utc)


def paid_plan(user_id: str) -> bool:
    try:
        from app.services.user_entitlements import can_access_clean_result

        return bool(can_access_clean_result(str(user_id)))
    except Exception:  # noqa: BLE001 - doubt means not paid (no burst spend)
        return False


def burst_spent_this_month(session: Session) -> float:
    start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if session.get_bind().dialect.name == "sqlite":
        start = start.replace(tzinfo=None)
    return float(session.execute(select(func.coalesce(func.sum(OttEncodeJob.cost_usd), 0.0)).where(
        OttEncodeJob.lane == LANE_BURST, OttEncodeJob.created_at >= start)).scalar() or 0.0)


def output_prefix(title: OttTitle, job_id: str) -> str:
    return f"ott/{title.channel_id}/{title.id}/{job_id}"


def submit(session: Session, title: OttTitle, *, source_key: str, seconds: float, short_side: int,
           user_id: str) -> OttEncodeJob:
    paid = paid_plan(user_id)
    choice = picker.pick(seconds=seconds, short_side=short_side, paid_plan=paid,
                         mac_live=bool(nodes.live_nodes(session, LANE_MAC)),
                         burst_live=bool(nodes.live_nodes(session, LANE_BURST)),
                         burst_spent_usd=burst_spent_this_month(session))
    job = OttEncodeJob(title_id=title.id, user_id=user_id, source_key=source_key, source_seconds=float(seconds),
                       source_height=int(short_side), paid_plan=paid, lane=choice.lane)
    session.add(job)
    session.flush()
    job.output_prefix = output_prefix(title, job.id)
    title.package_status = "queued"
    session.flush()
    return job


def protection_for(session: Session, title: OttTitle, api_base: str):
    """Tier-1 protection for non-free titles (None for free titles)."""
    if title.access_tier == "free":
        return None
    import secrets

    from app.services.ott_package.packager import Protection

    from .keys import ensure_key

    from .keys import version

    _key_id, key_hex = ensure_key(session, title.id)
    # QM1.2 (P-M7): the playlist names the key version, so the key server can refuse a stale one.
    return Protection(key_hex=key_hex, iv_hex=secrets.token_hex(16),
                      key_uri=f"{api_base.rstrip('/')}{KEY_PATH.format(title_id=title.id)}"
                              f"?kv={version(session, title.id)}")


def requeue_protected(session: Session, title: OttTitle, *, user_id: str) -> OttEncodeJob | None:
    """A packaged title moved from free to paid (QM1.2, P-M7): new key, re-encrypt, unwatchable until done.

    Returns the queued job (``None`` when the title was never packaged; its
    first packaging encrypts it anyway).
    """
    if not title.manifest_key and title.package_status in ("none", ""):
        return None
    from app.models.db.models import Job

    from .keys import rotate_key

    source = title.source_key
    if not source and title.source_job_id:
        reel = session.get(Job, title.source_job_id)
        source = f"r2:{reel.result_key}" if reel is not None and reel.result_key else ""
    if not source:
        title.package_status = "failed"
        session.flush()
        return None
    last = session.execute(select(OttEncodeJob).where(OttEncodeJob.title_id == title.id)
                           .order_by(OttEncodeJob.created_at.desc()).limit(1)).scalars().first()
    rotate_key(session, title.id)
    return submit(session, title, source_key=source, seconds=float(title.duration_s or 60.0),
                  short_side=int(getattr(last, "source_height", 0) or 720), user_id=user_id)


def cost_for(job: OttEncodeJob, cpu_seconds: float) -> float:
    if job.lane != LANE_BURST:
        return 0.0
    import os

    rate = float(os.getenv("OTT_BURST_USD_PER_CPU_HOUR") or picker.DEFAULT_BURST_USD_PER_CPU_HOUR)
    return round(cpu_seconds / 3600.0 * rate, 4)


def checked_seconds(job: OttEncodeJob, measured: float | None) -> float | None:
    """The measured source length a lane reported, validated (``None`` keeps the declared length).

    QM verify (h): encode minutes are metered from ``source_seconds`` of the finished job,
    so a lane that reports the probed length must bill on it. A zero, negative, non-finite
    or over-6-hour value is refused (logged) rather than billed.
    """
    if measured is None:
        return None
    try:
        value = float(measured)
    except (TypeError, ValueError):
        value = float("nan")
    if not math.isfinite(value) or value <= 0 or value > MAX_SOURCE_S:
        logger.warning(f"ott job {job.id} ({job.lane}): measured length {measured!r} refused; "
                       f"declared {job.source_seconds}s kept")
        raise TranscodeError(400, "bad_duration", "the measured length must be between 0 and 6 hours")
    return round(value, 3)


def finish(session: Session, job: OttEncodeJob, *, cpu_seconds: float, packager_sha256: str,
           node_id: str | None = None, measured_seconds: float | None = None) -> OttEncodeJob:
    """Mark a job done. Idempotent: a job that is already done is returned unchanged (billed once).

    ``measured_seconds`` (the probed source length, from any lane) replaces the declared
    length before the job is done, so the hourly ``encode_minutes`` meter, the monthly
    upload quota and the plan caps all count the measured length; without it the
    declared length stands.
    """
    if job.status == DONE:
        return job
    measured = checked_seconds(job, measured_seconds)
    if measured is not None:
        job.source_seconds = measured
    job.status, job.finished_at = DONE, now()
    job.cpu_seconds, job.cost_usd = float(cpu_seconds), cost_for(job, cpu_seconds)
    job.packager_sha256 = packager_sha256
    job.node_id = node_id or job.node_id
    job.manifest_key = f"{job.output_prefix}/master.m3u8"
    title = session.get(OttTitle, job.title_id)
    # QM verify (P-M7 race): a job superseded by a newer one (a free-to-paid re-encrypt queued
    # while this one was running) must not point the title at its output, which may be
    # unencrypted or under a rotated key.
    newer = session.execute(select(OttEncodeJob.id).where(
        OttEncodeJob.title_id == job.title_id, OttEncodeJob.id != job.id,
        OttEncodeJob.created_at > job.created_at).limit(1)).first() if job.created_at is not None else None
    ready = title is not None and newer is None
    if ready:
        title.package_status, title.manifest_key = "ready", job.manifest_key
    session.flush()
    if ready:
        # QM verify: a title published before packaging is announced now (ott.title.published + push),
        # once; a re-packaging (free to paid) finds the announcement recorded and sends nothing.
        from app.domains.ott import events

        events.maybe_title_published(session, title)
    return job


def fail(session: Session, job: OttEncodeJob, error: str, *, retry: bool = True) -> OttEncodeJob:
    job.attempts += 1
    if retry and job.attempts < 3:
        job.status, job.node_id, job.claimed_at, job.heartbeat_at = QUEUED, None, None, None
    else:
        job.status, job.finished_at = FAILED, now()
        title = session.get(OttTitle, job.title_id)
        if title is not None:
            title.package_status = "failed"
    job.error = error[:500]
    session.flush()
    return job


#: Box 1 sends no node heartbeats while it encodes; its claim is stale only after the
#: Celery hard time limit of the box 1 task (3660 s) has passed.
BOX1_STALE_S = 3700.0


def reroute_from_box1(session: Session, job: OttEncodeJob, *, seconds: float, short_side: int) -> OttEncodeJob:
    """The real source is over the box 1 limits: record its real size and queue it for the Mac or burst.

    Not a failure (attempts unchanged); the picker runs again on the measured values, so a
    long or large source never encodes on box 1 whatever the upload form said.
    """
    choice = picker.pick(seconds=float(seconds), short_side=int(short_side),
                         paid_plan=bool(job.paid_plan), mac_live=bool(nodes.live_nodes(session, LANE_MAC)),
                         burst_live=bool(nodes.live_nodes(session, LANE_BURST)),
                         burst_spent_usd=burst_spent_this_month(session))
    job.lane = choice.lane if choice.lane != LANE_BOX1 else LANE_MAC
    job.status, job.node_id, job.claimed_at, job.heartbeat_at = QUEUED, None, None, None
    job.source_seconds, job.source_height = float(seconds), int(short_side)
    job.error = "rerouted: the source is over the box 1 limits"
    title = session.get(OttTitle, job.title_id)
    if title is not None:
        title.package_status = "queued"
    session.flush()
    return job


def requeue_stale_jobs(session: Session, *, max_age_s: float = 180.0,
                       box1_max_age_s: float = BOX1_STALE_S) -> list[OttEncodeJob]:
    """Claimed jobs whose node stopped sending progress go back to the queue (never to box 1).

    Box 1 jobs use their own, longer cutoff (box 1 does not heartbeat mid-encode) and
    stay on box 1; the caller re-enqueues them.
    """
    moment = now().timestamp()
    stale: list[OttEncodeJob] = []
    for job in session.execute(select(OttEncodeJob).where(OttEncodeJob.status == CLAIMED)).scalars().all():
        seen = job.heartbeat_at or job.claimed_at
        if seen is None:
            continue
        seen = seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)
        limit = box1_max_age_s if job.lane == LANE_BOX1 else max_age_s
        if seen.timestamp() < moment - limit:
            fail(session, job, "node went quiet", retry=True)
            stale.append(job)
    return stale


def requeue_stale(session: Session, *, max_age_s: float = 180.0) -> int:
    """Claimed jobs whose node stopped sending progress go back to the queue (never to box 1)."""
    return len(requeue_stale_jobs(session, max_age_s=max_age_s))


def job_view(job: OttEncodeJob) -> dict[str, Any]:
    return {"id": job.id, "title_id": job.title_id, "lane": job.lane, "status": job.status, "node_id": job.node_id,
            "cpu_seconds": job.cpu_seconds, "cost_usd": job.cost_usd, "attempts": job.attempts,
            "manifest_key": job.manifest_key, "error": job.error}


__all__ = ["BOX1_STALE_S", "KEY_PATH", "MAX_SOURCE_S", "TranscodeError", "checked_seconds", "fail", "finish", "job_view", "protection_for",
           "requeue_protected", "requeue_stale", "requeue_stale_jobs", "reroute_from_box1", "submit", "LANE_BOX1"]
