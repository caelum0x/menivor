"""Honest queue position + ETA for a job that has not finished yet.

``ahead`` is a real count: unfinished jobs (any creator) created before this
one in the last few hours. ``eta_s`` is derived ONLY from measured work: the
median of the summed stage ``duration_ms`` of recently completed reels, times
how many reels must pass through the render slots before this one is done.
With too little history ``eta_s`` is ``None`` and the UI shows only the
position, never an invented number.

The median is cached per process for a minute because every open results page
polls ``GET /jobs/{id}`` for three variants every few seconds.

M1.3 adds the lanes and admission control on top:

* :func:`resolve_lane` picks a job's render lane (paid > first reel > free >
  variants 2-3 > bulk) and ``start_pipeline`` routes the render stages to that
  lane's queue. With lanes on, ``ahead`` counts only the renders that really
  run first: higher lanes, and earlier jobs of the same lane.
* :func:`admission` is the create-time gate: a per-user and per-API-key cap on
  unfinished renders and a daily cap tied to the plan (fair share), plus a
  global queue cap. A refusal is an honest 429 with ``Retry-After`` and, when
  measured, an ETA (:class:`QueueFull`).
"""

from __future__ import annotations

import math
import os
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from dataclasses import dataclass

from loguru import logger
from sqlalchemy import func, select

from app.domains.reels import policy
from app.models.const import TASK_STATE_COMPLETE, TASK_STATE_PROCESSING
from app.models.db.models import Job, JobEvent
from app.models.exception import HttpException

# Unfinished jobs older than this are treated as stuck/orphaned, not "ahead".
ACTIVE_WINDOW = timedelta(hours=3)
# Completed reels sampled for the per-reel service time.
SAMPLE_JOBS = 12  # recent enough to follow speed-ups quickly
SAMPLE_WINDOW = timedelta(days=7)
MIN_SAMPLES = 3
CACHE_TTL_S = 60.0
_STAGE_COMPLETE = "complete"

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "value": None}


def render_slots() -> int:
    """How many reels render at once across all render workers (ops env)."""
    try:
        return max(1, int(os.environ.get("MENIVOR_RENDER_SLOTS", "1") or 1))
    except ValueError:
        return 1


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def measured_reel_seconds(session: Any, *, now: float | None = None) -> float | None:
    """Median measured work seconds per completed reel, or ``None`` if unknown."""
    clock = time.monotonic() if now is None else now
    with _cache_lock:
        if _cache["at"] and clock - _cache["at"] < CACHE_TTL_S:
            return _cache["value"]
    value: float | None = None
    try:
        since = datetime.now(timezone.utc) - SAMPLE_WINDOW
        recent = (
            select(Job.id)
            .where(Job.state == TASK_STATE_COMPLETE, Job.updated_at >= since)
            .order_by(Job.updated_at.desc())
            .limit(SAMPLE_JOBS)
            .subquery()
        )
        rows = session.execute(
            select(JobEvent.job_id, func.sum(JobEvent.duration_ms))
            .where(
                JobEvent.job_id.in_(select(recent.c.id)),
                JobEvent.status == _STAGE_COMPLETE,
            )
            .group_by(JobEvent.job_id)
        ).all()
        totals = [float(total) / 1000.0 for _, total in rows if total and total > 0]
        if len(totals) >= MIN_SAMPLES:
            value = round(statistics.median(totals), 1)
    except Exception as exc:  # noqa: BLE001 - an ETA must never break a status read
        logger.warning(f"queue eta: could not measure reel time: {exc}")
        value = None
    with _cache_lock:
        _cache["at"] = clock
        _cache["value"] = value
    return value


LANE_PARAM = "_lane"


def job_lane(job: Any) -> str:
    """The lane ``start_pipeline`` stamped on ``job`` (``""`` if none)."""
    params = getattr(job, "params", None)
    return str(params.get(LANE_PARAM) or "") if isinstance(params, dict) else ""


def _lane_aware_ahead(session: Any, job: Any, created: datetime, floor: datetime) -> int:
    """Renders that run before ``job``: higher lanes, then earlier same-lane jobs."""
    rank = policy.lane_rank(job_lane(job))
    rows = session.execute(
        select(Job.id, Job.created_at, Job.params).where(
            Job.state == TASK_STATE_PROCESSING,
            Job.deleted_at.is_(None),
            Job.created_at >= floor,
            Job.id != job.id,
        )
    ).all()
    ahead = 0
    for _job_id, other_created, params in rows:
        other_rank = policy.lane_rank(
            str(params.get(LANE_PARAM) or "") if isinstance(params, dict) else ""
        )
        if other_rank < rank or (other_rank == rank and _aware(other_created) < created):
            ahead += 1
    return ahead


def jobs_ahead(session: Any, job: Any) -> int:
    """Unfinished jobs that render before ``job`` within the active window."""
    created = _aware(getattr(job, "created_at", None))
    if created is None:
        return 0
    floor = datetime.now(timezone.utc) - ACTIVE_WINDOW
    if policy.lanes_enabled() and job_lane(job):
        try:
            return _lane_aware_ahead(session, job, created, floor)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"queue eta: could not count lane jobs ahead: {exc}")
            return 0
    try:
        count = session.execute(
            select(func.count(Job.id)).where(
                Job.state == TASK_STATE_PROCESSING,
                Job.deleted_at.is_(None),
                Job.created_at >= floor,
                Job.created_at < created,
                Job.id != job.id,
            )
        ).scalar_one()
        return int(count or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"queue eta: could not count jobs ahead: {exc}")
        return 0


def estimate_eta_s(ahead: int, progress: int, per_reel_s: float | None, slots: int) -> int | None:
    """Seconds until this job is done, from measured per-reel time only."""
    if per_reel_s is None or per_reel_s <= 0:
        return None
    rounds = math.ceil((max(0, ahead) + 1) / max(1, slots))
    remaining_share = 1.0 - max(0, min(100, int(progress or 0))) / 100.0
    # Earlier rounds are full reels; this reel's own round counts what is left.
    seconds = (rounds - 1) * per_reel_s + remaining_share * per_reel_s
    return max(10, int(round(seconds)))


def queue_status(session: Any, job: Any) -> dict[str, Any] | None:
    """``{"ahead", "eta_s", "slots"}`` for an unfinished job, else ``None``."""
    if job is None or getattr(job, "state", None) != TASK_STATE_PROCESSING:
        return None
    slots = render_slots()
    ahead = jobs_ahead(session, job)
    per_reel = measured_reel_seconds(session)
    return {
        "ahead": ahead,
        "eta_s": estimate_eta_s(ahead, int(getattr(job, "progress", 0) or 0), per_reel, slots),
        "slots": slots,
    }


# --------------------------------------------------------------------------- #
# Lanes
# --------------------------------------------------------------------------- #
def _dogfood_user_ids() -> frozenset[str]:
    raw = os.environ.get("MENIVOR_DOGFOOD_USER_IDS", "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _variant_index(session: Any, job: Any) -> int:
    """0 for a lone job or the first job of its batch; its position otherwise."""
    batch_id = getattr(job, "batch_id", None)
    if not batch_id:
        return 0
    ids = session.execute(
        select(Job.id).where(Job.batch_id == batch_id).order_by(Job.created_at, Job.id)
    ).scalars().all()
    return ids.index(job.id) if job.id in ids else 0


def _is_first_reel(session: Any, job: Any) -> bool:
    """No earlier job of this user outside this job's batch."""
    created = getattr(job, "created_at", None)
    query = select(func.count(Job.id)).where(Job.user_id == job.user_id, Job.id != job.id)
    if created is not None:
        query = query.where(Job.created_at < created)
    if getattr(job, "batch_id", None):
        query = query.where((Job.batch_id.is_(None)) | (Job.batch_id != job.batch_id))
    return int(session.execute(query).scalar_one() or 0) == 0


def user_plan(user_id: str) -> tuple[str, bool]:
    """``(plan_key, paid)`` from the unified entitlements; free on any doubt."""
    try:
        from app.services.user_entitlements import user_entitlements

        ent = user_entitlements(str(user_id))
        return (str(ent.plan or "free"), bool(ent.paid))
    except Exception as exc:  # noqa: BLE001 - lanes must never block a render
        logger.warning(f"queue: entitlements unavailable for {user_id}: {exc}")
        return ("free", False)


def resolve_lane(session: Any, job: Any, *, plan_of: Any = None) -> str:
    """The render lane for ``job`` (see :func:`policy.render_lane`)."""
    params = getattr(job, "params", None) or {}
    bulk = str(getattr(job, "user_id", "")) in _dogfood_user_ids() or (
        isinstance(params, dict) and params.get("_lane_hint") == policy.LANE_BULK
    )
    _plan, paid = (plan_of or user_plan)(getattr(job, "user_id", ""))
    return policy.render_lane(
        paid=paid,
        first_reel=_is_first_reel(session, job),
        variant_index=_variant_index(session, job),
        bulk=bulk,
    )


# --------------------------------------------------------------------------- #
# Admission control and fair share
# --------------------------------------------------------------------------- #
QUEUE_FULL_CODE = "queue_full"
USER_CONCURRENT_CODE = "render_limit"
API_KEY_CONCURRENT_CODE = "api_key_render_limit"
DAILY_CAP_CODE = "daily_render_limit"
API_KEY_PARAM = "_api_key_id"
_DEFAULT_RETRY_S = 60
_MAX_RETRY_S = 24 * 3600


@dataclass(frozen=True)
class Admission:
    """The create-time decision for ``requested`` new renders."""

    allowed: bool
    code: str = ""
    retry_after_s: int = 0
    eta_s: int | None = None
    ahead: int = 0
    message: str = ""


class QueueFull(HttpException):
    """429 with ``Retry-After`` and an honest ETA (``data.eta_s`` null if unmeasured)."""

    def __init__(self, request_id: str, decision: Admission) -> None:
        super().__init__(
            task_id=request_id,
            status_code=429,
            message=f"{request_id}: {decision.message}",
            data={
                "code": decision.code,
                "retry_after_s": decision.retry_after_s,
                "eta_s": decision.eta_s,
                "ahead": decision.ahead,
            },
        )
        self.decision = decision
        self.headers = {"Retry-After": str(max(1, int(decision.retry_after_s)))}


def _active_jobs(session: Any, floor: datetime, user_id: str | None = None) -> list[Any]:
    query = select(Job.id, Job.params).where(
        Job.state == TASK_STATE_PROCESSING,
        Job.deleted_at.is_(None),
        Job.created_at >= floor,
    )
    if user_id is not None:
        query = query.where(Job.user_id == user_id)
    return list(session.execute(query).all())


def _retry_after(per_reel: float | None, rounds: int = 1) -> int:
    if per_reel is None or per_reel <= 0:
        return _DEFAULT_RETRY_S
    return max(10, min(_MAX_RETRY_S, int(round(per_reel * max(1, rounds)))))


def admission(
    session: Any,
    user_id: str,
    *,
    plan: str,
    requested: int = 1,
    api_key_id: str = "",
    now: datetime | None = None,
) -> Admission:
    """Decide whether ``user_id`` may start ``requested`` renders now.

    Checks in order: the user's unfinished renders against the plan's
    concurrent cap, the API key's unfinished renders, the plan's rolling daily
    cap, then the global queue cap. The first refusal wins; nothing is written.
    """
    clock = now or datetime.now(timezone.utc)
    floor = clock - ACTIVE_WINDOW
    need = max(1, int(requested))
    share = policy.fair_share(plan)
    per_reel = measured_reel_seconds(session)
    slots = render_slots()

    mine = _active_jobs(session, floor, str(user_id))
    if len(mine) + need > share.concurrent:
        return Admission(
            False, USER_CONCURRENT_CODE, _retry_after(per_reel), None, len(mine),
            f"{len(mine)} of your reels are still rendering (limit {share.concurrent} at once)",
        )
    if api_key_id:
        by_key = [row for row in mine if isinstance(row[1], dict) and row[1].get(API_KEY_PARAM) == api_key_id]
        cap = policy.api_key_concurrent_cap()
        if len(by_key) + need > cap:
            return Admission(
                False, API_KEY_CONCURRENT_CODE, _retry_after(per_reel), None, len(by_key),
                f"this API key has {len(by_key)} renders running (limit {cap} at once)",
            )

    day_floor = clock - timedelta(hours=24)
    started = session.execute(
        select(Job.created_at).where(Job.user_id == str(user_id), Job.created_at >= day_floor)
        .order_by(Job.created_at)
    ).scalars().all()
    if len(started) + need > share.daily:
        oldest = _aware(started[0]) if started else clock
        wait = int((oldest + timedelta(hours=24) - clock).total_seconds()) if oldest else _DEFAULT_RETRY_S
        return Admission(
            False, DAILY_CAP_CODE, max(60, min(_MAX_RETRY_S, wait)), None, 0,
            f"daily render limit reached ({share.daily} per 24 hours on your plan)",
        )

    total = len(_active_jobs(session, floor))
    cap = policy.global_queue_cap()
    if total + need > cap:
        eta = estimate_eta_s(total, 0, per_reel, slots)
        rounds = math.ceil((total + need - cap) / max(1, slots))
        return Admission(
            False, QUEUE_FULL_CODE, _retry_after(per_reel, rounds), eta, total,
            "the render queue is full right now",
        )
    return Admission(True, ahead=total, eta_s=estimate_eta_s(total, 0, per_reel, slots))


def admit_or_429(
    session: Any, request_id: str, user_id: str, *, requested: int = 1, api_key_id: str = ""
) -> Admission:
    """Resolve the plan and raise :class:`QueueFull` on a refusal.

    Call inside the create transaction BEFORE any debit, so a refused create
    costs nothing. ``MENIVOR_ADMISSION=off`` disables the gate.
    """
    if os.environ.get("MENIVOR_ADMISSION", "on").strip().lower() in ("0", "off", "false", "no"):
        return Admission(True)
    plan, _paid = user_plan(user_id)
    decision = admission(session, user_id, plan=plan, requested=requested, api_key_id=api_key_id)
    if not decision.allowed:
        raise QueueFull(request_id, decision)
    return decision


__all__ = [
    "API_KEY_CONCURRENT_CODE",
    "API_KEY_PARAM",
    "DAILY_CAP_CODE",
    "LANE_PARAM",
    "QUEUE_FULL_CODE",
    "USER_CONCURRENT_CODE",
    "Admission",
    "QueueFull",
    "admission",
    "admit_or_429",
    "job_lane",
    "resolve_lane",
    "user_plan",
    "estimate_eta_s",
    "jobs_ahead",
    "measured_reel_seconds",
    "queue_status",
    "render_slots",
]
