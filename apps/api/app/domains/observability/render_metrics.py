"""Render stage metrics, owner alerts and the owner metrics page (M1.5).

Everything is computed from rows the pipeline already writes:

* ``JobEvent(status="running")`` when a stage task starts,
* ``JobEvent(status="complete", duration_ms=...)`` when it ends,
* ``JobEvent(status="cost", cost_usd=...)`` per stage (provider spend),
* ``Job.created_at`` / ``Job.state`` / ``Job.updated_at``.

Queue wait for a stage is the time from the moment the stage became runnable
(the latest earlier ``complete`` event of the same reel, or the reel's creation
for the first stage) to its ``running`` event. For ``avatar`` and ``compose``
that is the wait for a render slot.

Time to reel is creation to ``compose`` complete: the MP4 exists and plays.

Canary reels (``params["_canary"]``) are excluded from customer metrics; the
canary has its own check in ``app.workers.tasks_canary``.

Alerts go to ntfy (``NTFY_URL_MENIVOR``, else ``NTFY_URL``; ``NTFY_TOKEN``
optional), deduplicated per alert key for ``MENIVOR_ALERT_REALERT_MIN``
minutes (default 120, same as infra-box ``health-alert.sh``).
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping

from loguru import logger

from app.models import const

PIPELINE_STAGES: tuple[str, ...] = ("script", "tts", "avatar", "captions", "compose", "upload")
RENDER_STAGES: tuple[str, ...] = ("avatar", "compose")
PLAYABLE_STAGE = "compose"
CANARY_PARAM = "_canary"
COST_STATUS = "cost"
REEL_KIND = "avatar_reel"


# --------------------------------------------------------------------------- #
# Plain data (no DB) so the maths is testable from fixture events
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EventRow:
    job_id: str
    stage: str
    status: str
    at: datetime
    duration_ms: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class JobRow:
    id: str
    created_at: datetime
    state: int = const.TASK_STATE_PROCESSING
    updated_at: datetime | None = None
    canary: bool = False


@dataclass(frozen=True)
class Dist:
    count: int
    p50: float | None
    p90: float | None

    @staticmethod
    def of(values: Iterable[float]) -> "Dist":
        vals = sorted(float(v) for v in values if v is not None and v >= 0)
        return Dist(len(vals), percentile(vals, 50), percentile(vals, 90))


@dataclass(frozen=True)
class Summary:
    since: datetime
    until: datetime
    stage_seconds: dict[str, Dist]
    queue_wait_seconds: dict[str, Dist]
    render_queue_wait: Dist
    time_to_reel: Dist
    reels_finished: int
    reels_failed: int
    provider_spend_usd: float
    canary_reels: int = 0

    @property
    def failure_rate(self) -> float | None:
        done = self.reels_finished + self.reels_failed
        return None if done == 0 else self.reels_failed / done

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["since"] = self.since.isoformat()
        out["until"] = self.until.isoformat()
        out["failure_rate"] = self.failure_rate
        return out


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (numpy's default); ``None`` when empty."""
    vals = sorted(values)
    if not vals:
        return None
    if len(vals) == 1:
        return float(vals[0])
    rank = (len(vals) - 1) * (q / 100.0)
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return float(vals[lo])
    return float(vals[lo] + (vals[hi] - vals[lo]) * (rank - lo))


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _by_job(events: Iterable[EventRow]) -> dict[str, list[EventRow]]:
    grouped: dict[str, list[EventRow]] = {}
    for ev in events:
        grouped.setdefault(ev.job_id, []).append(ev)
    for rows in grouped.values():
        rows.sort(key=lambda e: _aware(e.at))
    return grouped


def stage_durations(events: Iterable[EventRow]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for ev in events:
        if ev.status == const.REELFORGE_STAGE_COMPLETE and ev.duration_ms > 0:
            out.setdefault(ev.stage, []).append(ev.duration_ms / 1000.0)
    return out


def queue_waits(events: Iterable[EventRow], jobs: Mapping[str, JobRow]) -> dict[str, list[float]]:
    """Per stage: seconds from runnable to started (first attempt of each stage)."""
    out: dict[str, list[float]] = {}
    for job_id, rows in _by_job(events).items():
        job = jobs.get(job_id)
        anchor = _aware(job.created_at) if job else None
        started: set[str] = set()
        for ev in rows:
            at = _aware(ev.at)
            if ev.status == const.REELFORGE_STAGE_RUNNING and ev.stage not in started:
                started.add(ev.stage)
                if anchor is not None and at is not None:
                    out.setdefault(ev.stage, []).append(max(0.0, (at - anchor).total_seconds()))
            elif ev.status == const.REELFORGE_STAGE_COMPLETE and at is not None:
                anchor = at if anchor is None else max(anchor, at)
    return out


def times_to_reel(events: Iterable[EventRow], jobs: Mapping[str, JobRow]) -> list[float]:
    out: list[float] = []
    for job_id, rows in _by_job(events).items():
        job = jobs.get(job_id)
        if job is None:
            continue
        done = next(
            (e for e in rows if e.stage == PLAYABLE_STAGE and e.status == const.REELFORGE_STAGE_COMPLETE),
            None,
        )
        if done is not None:
            out.append(max(0.0, (_aware(done.at) - _aware(job.created_at)).total_seconds()))
    return out


def summarize(
    events: Iterable[EventRow], jobs: Mapping[str, JobRow], since: datetime, until: datetime
) -> Summary:
    """Customer render metrics for reels created in ``[since, until)``."""
    since, until = _aware(since), _aware(until)
    customer = {jid: j for jid, j in jobs.items() if not j.canary}
    evs = [e for e in events if e.job_id in customer]
    waits = queue_waits(evs, customer)
    render_waits = [w for stage in RENDER_STAGES for w in waits.get(stage, [])]
    finished = sum(1 for j in customer.values() if j.state == const.TASK_STATE_COMPLETE)
    failed = sum(1 for j in customer.values() if j.state == const.TASK_STATE_FAILED)
    spend = sum(e.cost_usd for e in events if e.status == COST_STATUS and e.job_id in jobs)
    durations = stage_durations(evs)
    return Summary(
        since=since,
        until=until,
        stage_seconds={s: Dist.of(durations.get(s, [])) for s in PIPELINE_STAGES},
        queue_wait_seconds={s: Dist.of(waits.get(s, [])) for s in PIPELINE_STAGES},
        render_queue_wait=Dist.of(render_waits),
        time_to_reel=Dist.of(times_to_reel(evs, customer)),
        reels_finished=finished,
        reels_failed=failed,
        provider_spend_usd=round(spend, 4),
        canary_reels=sum(1 for j in jobs.values() if j.canary),
    )


# --------------------------------------------------------------------------- #
# DB loading
# --------------------------------------------------------------------------- #
def load_window(session: Any, since: datetime, until: datetime) -> tuple[list[EventRow], dict[str, JobRow]]:
    """Reels created in ``[since, until)`` and all their events."""
    from sqlalchemy import select

    from app.models.db.models import Job, JobEvent

    job_rows = session.execute(
        select(Job.id, Job.created_at, Job.state, Job.updated_at, Job.params).where(
            Job.kind == REEL_KIND, Job.created_at >= since, Job.created_at < until
        )
    ).all()
    jobs = {
        r.id: JobRow(
            id=r.id,
            created_at=_aware(r.created_at),
            state=int(r.state),
            updated_at=_aware(r.updated_at),
            canary=bool((r.params or {}).get(CANARY_PARAM)),
        )
        for r in job_rows
    }
    if not jobs:
        return [], {}
    events: list[EventRow] = []
    ids = list(jobs)
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        for r in session.execute(
            select(
                JobEvent.job_id,
                JobEvent.stage,
                JobEvent.status,
                JobEvent.created_at,
                JobEvent.duration_ms,
                JobEvent.cost_usd,
            ).where(JobEvent.job_id.in_(chunk))
        ).all():
            events.append(
                EventRow(
                    r.job_id, r.stage, r.status, _aware(r.created_at), int(r.duration_ms or 0), float(r.cost_usd or 0.0)
                )
            )
    return events, jobs


def summary_for(session: Any, since: datetime, until: datetime) -> Summary:
    events, jobs = load_window(session, since, until)
    return summarize(events, jobs, since, until)


def provider_spend(session: Any, since: datetime, until: datetime) -> float:
    """Provider spend recorded in ``[since, until)`` across every job kind."""
    from sqlalchemy import func, select

    from app.models.db.models import JobEvent

    total = session.execute(
        select(func.coalesce(func.sum(JobEvent.cost_usd), 0.0)).where(
            JobEvent.status == COST_STATUS, JobEvent.created_at >= since, JobEvent.created_at < until
        )
    ).scalar()
    return round(float(total or 0.0), 4)


def stuck_reels(session: Any, now: datetime, minutes: float) -> list[str]:
    """Unfinished customer reels with no progress for ``minutes`` (reaper missed them)."""
    from sqlalchemy import select

    from app.models.db.models import Job

    cutoff = _aware(now) - timedelta(minutes=minutes)
    rows = session.execute(
        select(Job.id, Job.params).where(
            Job.kind == REEL_KIND,
            Job.state == const.TASK_STATE_PROCESSING,
            Job.updated_at < cutoff,
            Job.deleted_at.is_(None),
        ).limit(50)
    ).all()
    return [r.id for r in rows if not (r.params or {}).get(CANARY_PARAM)]


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = str(env.get(name, "") or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Thresholds:
    queue_wait_p90_s: float = 600.0
    failure_rate: float = 0.10
    min_reels_for_rate: int = 5
    stuck_minutes: float = 90.0
    daily_budget_usd: float = 5.0

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> "Thresholds":
        e = env if env is not None else os.environ
        d = Thresholds()
        return Thresholds(
            queue_wait_p90_s=_env_float(e, "MENIVOR_ALERT_QUEUE_WAIT_P90_S", d.queue_wait_p90_s),
            failure_rate=_env_float(e, "MENIVOR_ALERT_FAILURE_RATE", d.failure_rate),
            min_reels_for_rate=int(_env_float(e, "MENIVOR_ALERT_MIN_REELS", d.min_reels_for_rate)),
            stuck_minutes=_env_float(e, "MENIVOR_ALERT_STUCK_MIN", d.stuck_minutes),
            daily_budget_usd=_env_float(e, "MENIVOR_DAILY_PROVIDER_BUDGET_USD", d.daily_budget_usd),
        )


@dataclass(frozen=True)
class Alert:
    key: str
    title: str
    message: str
    priority: str = "high"


def _mins(seconds: float | None) -> str:
    return "n/a" if seconds is None else f"{seconds / 60.0:.1f} min"


def evaluate(
    last_hour: Summary,
    stuck: list[str],
    spend_today_usd: float,
    th: Thresholds,
) -> list[Alert]:
    """The owner alerts that should fire now (empty when all is well)."""
    alerts: list[Alert] = []
    p90 = last_hour.render_queue_wait.p90
    if p90 is not None and p90 > th.queue_wait_p90_s:
        alerts.append(
            Alert(
                "queue_wait",
                "Menivor: renders are waiting too long",
                f"Render queue wait p90 is {_mins(p90)} over the last hour "
                f"(limit {_mins(th.queue_wait_p90_s)}, {last_hour.render_queue_wait.count} renders).",
            )
        )
    done = last_hour.reels_finished + last_hour.reels_failed
    rate = last_hour.failure_rate
    if rate is not None and done >= th.min_reels_for_rate and rate > th.failure_rate:
        alerts.append(
            Alert(
                "failure_rate",
                "Menivor: reels are failing",
                f"{last_hour.reels_failed} of {done} reels failed in the last hour "
                f"({rate:.0%}, limit {th.failure_rate:.0%}).",
            )
        )
    if stuck:
        shown = ", ".join(stuck[:5]) + (" and more" if len(stuck) > 5 else "")
        alerts.append(
            Alert(
                "stuck",
                "Menivor: stuck reels",
                f"{len(stuck)} reel(s) made no progress for {th.stuck_minutes:.0f} min: {shown}.",
            )
        )
    if th.daily_budget_usd > 0 and spend_today_usd > th.daily_budget_usd:
        alerts.append(
            Alert(
                "spend",
                "Menivor: provider spend over budget",
                f"Provider spend today is ${spend_today_usd:.2f} "
                f"(budget ${th.daily_budget_usd:.2f}).",
            )
        )
    return alerts


# --------------------------------------------------------------------------- #
# ntfy delivery with dedup
# --------------------------------------------------------------------------- #
def ntfy_url(env: Mapping[str, str] | None = None) -> str:
    e = env if env is not None else os.environ
    return str(e.get("NTFY_URL_MENIVOR") or e.get("NTFY_URL") or "").strip()


# (url, body, headers) -> status code
PostFn = Callable[[str, bytes, dict], int]


def _http_post(url: str, body: bytes, headers: dict) -> int:
    import requests

    return requests.post(url, data=body, headers=headers, timeout=10).status_code


def send_ntfy(
    alert: Alert, *, env: Mapping[str, str] | None = None, post_fn: PostFn | None = None
) -> bool:
    """Post one alert to the Menivor ntfy topic. False when unset or on failure."""
    e = env if env is not None else os.environ
    url = ntfy_url(e)
    if not url:
        logger.warning(f"render alert not sent (no NTFY_URL_MENIVOR/NTFY_URL): {alert.title}")
        return False
    headers = {"Title": alert.title, "Priority": alert.priority, "Tags": "menivor"}
    token = str(e.get("NTFY_TOKEN", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        status = (post_fn or _http_post)(url, alert.message.encode("utf-8"), headers)
    except Exception as exc:  # noqa: BLE001 - alert delivery never crashes the tick
        logger.error(f"render alert delivery failed: {exc}")
        return False
    if status >= 300:
        logger.error(f"render alert delivery failed with HTTP {status}")
        return False
    return True


@dataclass
class _LocalDedup:
    until: dict[str, float] = field(default_factory=dict)

    def claim(self, key: str, ttl_s: int) -> bool:
        now = time.monotonic()
        if self.until.get(key, 0.0) > now:
            return False
        self.until[key] = now + ttl_s
        return True

    def release(self, key: str) -> None:
        self.until.pop(key, None)


_local_dedup = _LocalDedup()


class _RedisDedup:
    def __init__(self, client: Any) -> None:
        self._client = client

    def claim(self, key: str, ttl_s: int) -> bool:
        return bool(self._client.set(f"menivor:alert:{key}", b"1", nx=True, ex=ttl_s))

    def release(self, key: str) -> None:
        self._client.delete(f"menivor:alert:{key}")


def _dedup_store() -> Any:
    try:
        from app.services import ratelimit

        client = ratelimit._get_client()
        if client is not None:
            client.ping()
            return _RedisDedup(client)
    except Exception as exc:  # noqa: BLE001 - fall back to per-process dedup
        logger.debug(f"alert dedup: redis unavailable ({exc})")
    return _local_dedup


def realert_seconds(env: Mapping[str, str] | None = None) -> int:
    e = env if env is not None else os.environ
    return max(60, int(_env_float(e, "MENIVOR_ALERT_REALERT_MIN", 120.0) * 60))


def notify(
    alerts: list[Alert],
    *,
    store: Any = None,
    sender: Callable[[Alert], bool] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Send each alert not already sent within the re-alert window; returns sent keys."""
    store = store if store is not None else _dedup_store()
    send = sender or (lambda a: send_ntfy(a, env=env))
    ttl = realert_seconds(env)
    sent: list[str] = []
    for alert in alerts:
        if not store.claim(alert.key, ttl):
            continue
        if send(alert):
            sent.append(alert.key)
        else:
            store.release(alert.key)  # retry next tick
    return sent


def run_alerts(now: datetime | None = None, *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """One alert tick: last-hour summary, stuck reels, today's spend -> ntfy."""
    from app.models.db.base import get_session

    now = _aware(now or datetime.now(timezone.utc))
    th = Thresholds.from_env(env)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        last_hour = summary_for(session, now - timedelta(hours=1), now)
        stuck = stuck_reels(session, now, th.stuck_minutes)
        spend = provider_spend(session, day_start, now)
    alerts = evaluate(last_hour, stuck, spend, th)
    sent = notify(alerts, env=env)
    return {"alerts": [a.key for a in alerts], "sent": sent, "spend_today_usd": spend}


# --------------------------------------------------------------------------- #
# Owner page: GET /api/v1/admin/render-metrics (staff only)
# --------------------------------------------------------------------------- #
def _build_router() -> Any:
    from fastapi import Request

    from app.controllers import base
    from app.controllers.v1.base import new_router
    from app.models.exception import HttpException
    from app.utils import utils

    router = new_router()

    @router.get("/admin/render-metrics", include_in_schema=False)
    def render_metrics_page(request: Request, hours: int = 24) -> Any:
        from app.controllers.v1.jobs import _resolve_user, get_session

        request_id = base.get_task_id(request)
        hours = max(1, min(int(hours), 24 * 30))
        now = datetime.now(timezone.utc)
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            if not bool(getattr(user, "is_staff", False)):
                raise HttpException(task_id=request_id, status_code=403, message="Staff only.")
            summary = summary_for(session, now - timedelta(hours=hours), now)
            spend = provider_spend(session, now - timedelta(hours=hours), now)
        data = summary.to_dict()
        data["provider_spend_all_kinds_usd"] = spend
        data["thresholds"] = asdict(Thresholds.from_env())
        return utils.get_response(200, data)

    return router


try:
    router = _build_router()
except Exception as exc:  # noqa: BLE001 - import-safe outside the API process
    logger.debug(f"render metrics router unavailable: {exc}")
    router = None
