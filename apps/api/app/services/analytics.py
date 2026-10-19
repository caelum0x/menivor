"""Per-user BI aggregations for the ReelForge creator dashboard.

A richer, read-only "business intelligence" view of a single creator's activity,
built entirely on the data ReelForge already records (``Job`` / ``JobEvent`` /
``CreditLedger``). It complements the lightweight summary in
:mod:`app.services.insights` with time-series, funnels, percentiles and usage
breakdowns.

Design rules (mirroring :mod:`app.services.insights`):

* **Strictly per-user.** Every query joins back to ``jobs.user_id`` (or filters
  ``credit_ledger.user_id``) so a creator can NEVER observe another creator's
  jobs, spend, render times or credit balance. There is no cross-user code path.
* **Read-only.** No INSERT/UPDATE/DELETE — the caller owns the transaction.
* **Resilient.** Optional / newly-added columns (``cost_usd`` / ``duration_ms``)
  may be absent on older databases and JSON ``params`` fields may be missing;
  any aggregation failure degrades to an empty/zero result rather than raising,
  so the dashboard always renders.
* **DB-portable.** Day-bucketing and percentiles are computed in Python over the
  user's own (modest) row set rather than with DB-specific date/percentile
  functions, so the exact same code runs on SQLite (tests) and Postgres/Neon.

The current credit *balance* is always the live all-time figure; every other
metric is scoped to the trailing ``days`` window (default 30) so the dashboard
reflects "recent" activity.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import const
from app.models.db.models import CreditLedger, Job, JobEvent, JobPerformance
from app.models.db.trends import DiffusionForecastRecord, TrendObservation

# Stages whose ``duration_ms`` we treat as "render time" (the wall-clock cost of
# turning a job into a finished, published reel).
_RENDER_STAGES: tuple[str, ...] = ("compose", "upload")

# The stage whose completion marks a job as "published / uploaded" for the funnel.
_PUBLISH_STAGE = "upload"

# The append-only "stage completed" status string (REELFORGE_STAGE_COMPLETE).
_COMPLETE_STATUS = const.REELFORGE_STAGE_COMPLETE

# Job.params keys we probe (best-effort) for a template hint, in priority order.
_TEMPLATE_KEYS: tuple[str, ...] = ("template", "template_id", "template_name")

# Job.params key holding the creator's subject/hook line.
_HOOK_KEY = "video_subject"

# Default day-window when the caller does not narrow it.
_DEFAULT_DAYS = 30
# Hard cap so a hostile/absurd ``days`` value cannot request an unbounded scan.
_MAX_DAYS = 3650


# --------------------------------------------------------------------------- #
# Small pure helpers
# --------------------------------------------------------------------------- #
def _normalize_days(days: int) -> int:
    """Clamp ``days`` to the supported ``1.._MAX_DAYS`` window.

    A non-positive or non-integer value falls back to the default window rather
    than raising, so the dashboard is resilient to a bad query parameter.
    """
    try:
        value = int(days)
    except (TypeError, ValueError):
        return _DEFAULT_DAYS
    if value <= 0:
        return _DEFAULT_DAYS
    return min(value, _MAX_DAYS)


def _window_start(days: int, *, now: Optional[datetime] = None) -> datetime:
    """Return the (timezone-aware, UTC) start of the trailing ``days`` window."""
    reference = now if now is not None else datetime.now(timezone.utc)
    return reference - timedelta(days=days)


def _day_key(value: Any) -> Optional[str]:
    """Return the ``YYYY-MM-DD`` bucket key for a timestamp, or ``None``.

    Tolerates ``None`` and non-datetime values (returns ``None``) so a malformed
    row never breaks the whole aggregation.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    return None


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile of a pre-sorted, non-empty list.

    ``pct`` is in ``[0, 100]``. Returns ``0.0`` for an empty input.
    """
    if not sorted_values:
        return 0.0
    count = len(sorted_values)
    rank = math.ceil((pct / 100.0) * count)
    index = min(max(rank, 1), count) - 1
    return float(sorted_values[index])


def _bucket_by_day(
    rows: Iterable[tuple[Any, float]],
) -> list[dict[str, Any]]:
    """Sum ``(timestamp, amount)`` rows into ascending ``{date, amount}`` buckets."""
    totals: dict[str, float] = defaultdict(float)
    for created_at, amount in rows:
        key = _day_key(created_at)
        if key is None:
            continue
        try:
            totals[key] += float(amount or 0.0)
        except (TypeError, ValueError):
            continue
    return [{"date": key, "amount": totals[key]} for key in sorted(totals)]


# --------------------------------------------------------------------------- #
# Funnel
# --------------------------------------------------------------------------- #
def _job_count(session: Session, user_id: str, cutoff: datetime, state: Optional[int]) -> int:
    """Count the user's jobs created within the window, optionally by ``state``."""
    stmt = select(func.count(Job.id)).where(
        Job.user_id == user_id, Job.created_at >= cutoff
    )
    if state is not None:
        stmt = stmt.where(Job.state == state)
    return int(session.execute(stmt).scalar_one() or 0)


def _published_count(session: Session, user_id: str, cutoff: datetime) -> int:
    """Count the user's jobs that reached a completed ``upload`` stage in-window.

    A job is "published/uploaded" once it has at least one completed upload-stage
    event; counted DISTINCT so multi-platform uploads do not inflate the number.
    """
    try:
        stmt = (
            select(func.count(func.distinct(JobEvent.job_id)))
            .select_from(JobEvent)
            .join(Job, JobEvent.job_id == Job.id)
            .where(
                Job.user_id == user_id,
                Job.created_at >= cutoff,
                JobEvent.stage == _PUBLISH_STAGE,
                JobEvent.status == _COMPLETE_STATUS,
            )
        )
        return int(session.execute(stmt).scalar_one() or 0)
    except Exception as exc:  # pragma: no cover - defensive (legacy schema)
        logger.warning(f"published_count aggregation failed for {user_id}: {exc}")
        return 0


def _funnel(session: Session, user_id: str, cutoff: datetime) -> dict[str, int]:
    """created -> completed / failed -> published funnel for the window."""
    return {
        "created": _job_count(session, user_id, cutoff, None),
        "completed": _job_count(session, user_id, cutoff, const.TASK_STATE_COMPLETE),
        "failed": _job_count(session, user_id, cutoff, const.TASK_STATE_FAILED),
        "published": _published_count(session, user_id, cutoff),
    }


# --------------------------------------------------------------------------- #
# Cost over time
# --------------------------------------------------------------------------- #
def _cost_by_day(session: Session, user_id: str, cutoff: datetime) -> list[dict[str, Any]]:
    """SUM(``job_events.cost_usd``) per day for the user's events (scoped join)."""
    try:
        stmt = (
            select(JobEvent.created_at, JobEvent.cost_usd)
            .select_from(JobEvent)
            .join(Job, JobEvent.job_id == Job.id)
            .where(Job.user_id == user_id, JobEvent.created_at >= cutoff)
        )
        rows = session.execute(stmt).all()
    except Exception as exc:  # pragma: no cover - defensive (legacy schema)
        logger.warning(f"cost_by_day aggregation failed for {user_id}: {exc}")
        return []
    return [
        {"date": bucket["date"], "cost_usd": bucket["amount"]}
        for bucket in _bucket_by_day(rows)
    ]


def _total_cost_usd(session: Session, user_id: str, cutoff: datetime) -> float:
    """SUM(``job_events.cost_usd``) over the user's in-window events."""
    try:
        stmt = (
            select(func.coalesce(func.sum(JobEvent.cost_usd), 0.0))
            .select_from(JobEvent)
            .join(Job, JobEvent.job_id == Job.id)
            .where(Job.user_id == user_id, JobEvent.created_at >= cutoff)
        )
        return float(session.execute(stmt).scalar_one() or 0.0)
    except Exception as exc:  # pragma: no cover - defensive (legacy schema)
        logger.warning(f"total_cost_usd aggregation failed for {user_id}: {exc}")
        return 0.0


# --------------------------------------------------------------------------- #
# Credits (burn rate + live balance)
# --------------------------------------------------------------------------- #
def _credits_balance(session: Session, user_id: str) -> int:
    """Live personal credit balance (newest ``balance_after`` of a personal row).

    Personal-pool rows carry ``workspace_id IS NULL``; workspace-pool rows are
    excluded so a shared-pool debit never distorts the creator's own balance.
    """
    stmt = (
        select(CreditLedger.balance_after)
        .where(
            CreditLedger.user_id == user_id,
            CreditLedger.workspace_id.is_(None),
        )
        .order_by(CreditLedger.id.desc())
        .limit(1)
    )
    latest = session.execute(stmt).scalars().first()
    return int(latest) if latest is not None else 0


def _credits(session: Session, user_id: str, cutoff: datetime) -> dict[str, Any]:
    """Current balance plus the in-window spend and per-day burn."""
    balance = _credits_balance(session, user_id)
    try:
        stmt = (
            select(CreditLedger.created_at, CreditLedger.delta)
            .where(
                CreditLedger.user_id == user_id,
                CreditLedger.workspace_id.is_(None),
                CreditLedger.delta < 0,
                CreditLedger.created_at >= cutoff,
            )
        )
        rows = session.execute(stmt).all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"credits burn aggregation failed for {user_id}: {exc}")
        rows = []

    # Bucket spend as a positive magnitude (negate the debit deltas).
    burn = _bucket_by_day((created_at, -float(delta)) for created_at, delta in rows)
    spent = int(round(sum(bucket["amount"] for bucket in burn)))
    return {
        "balance": balance,
        "spent": spent,
        "burn_by_day": [
            {"date": bucket["date"], "spent": int(round(bucket["amount"]))}
            for bucket in burn
        ],
    }


# --------------------------------------------------------------------------- #
# Render-time distribution
# --------------------------------------------------------------------------- #
def _render_time(session: Session, user_id: str, cutoff: datetime) -> dict[str, Any]:
    """p50 / p90 / avg of the user's completed render-stage ``duration_ms``."""
    try:
        stmt = (
            select(JobEvent.duration_ms)
            .select_from(JobEvent)
            .join(Job, JobEvent.job_id == Job.id)
            .where(
                Job.user_id == user_id,
                JobEvent.created_at >= cutoff,
                JobEvent.stage.in_(_RENDER_STAGES),
                JobEvent.status == _COMPLETE_STATUS,
            )
        )
        durations = [
            float(value)
            for (value,) in session.execute(stmt).all()
            if value is not None
        ]
    except Exception as exc:  # pragma: no cover - defensive (legacy schema)
        logger.warning(f"render_time aggregation failed for {user_id}: {exc}")
        durations = []

    if not durations:
        return {"p50_ms": 0.0, "p90_ms": 0.0, "avg_ms": 0.0, "samples": 0}

    durations.sort()
    samples = len(durations)
    return {
        "p50_ms": _percentile(durations, 50.0),
        "p90_ms": _percentile(durations, 90.0),
        "avg_ms": float(sum(durations) / samples),
        "samples": samples,
    }


# --------------------------------------------------------------------------- #
# Usage breakdowns (over Job.params JSON)
# --------------------------------------------------------------------------- #
def _iter_job_params(
    session: Session, user_id: str, cutoff: datetime
) -> list[dict[str, Any]]:
    """Fetch the user's in-window ``Job.params`` blobs (each coerced to a dict)."""
    stmt = select(Job.params).where(
        Job.user_id == user_id, Job.created_at >= cutoff
    )
    params: list[dict[str, Any]] = []
    for (blob,) in session.execute(stmt).all():
        params.append(blob if isinstance(blob, dict) else {})
    return params


def _count_field(params: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Count non-empty ``params[key]`` values into ``{value: count}``.

    Missing / empty values are bucketed under ``"unknown"`` so the totals always
    reconcile with the job count without inventing a specific value.
    """
    counts: dict[str, int] = defaultdict(int)
    for blob in params:
        raw = blob.get(key)
        label = str(raw).strip() if raw not in (None, "") else "unknown"
        counts[label] += 1
    return dict(counts)


def _breakdowns(params: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """by_layout / by_language / by_variants counts from the params blobs."""
    return {
        "by_layout": _count_field(params, "layout"),
        "by_language": _count_field(params, "language"),
        "by_variants": _count_field(params, "variants"),
    }


def _trend_funnel(session: Session, user_id: str, cutoff: datetime) -> dict[str, Any]:
    """Discovery trend → generated reel → native publish, caller-scoped."""
    rows = session.execute(
        select(Job.id, Job.state, Job.params).where(
            Job.user_id == user_id, Job.created_at >= cutoff
        )
    ).all()
    attributed: dict[str, dict[str, Any]] = {}
    job_to_trend: dict[str, str] = {}
    for job_id, state, blob in rows:
        params = blob if isinstance(blob, dict) else {}
        source = params.get("source_context")
        if not isinstance(source, dict) or source.get("kind") != "trend":
            continue
        trend_id = str(source.get("id") or "").strip()
        if not trend_id:
            continue
        entry = attributed.setdefault(
            trend_id,
            {
                "key": trend_id,
                "label": str(source.get("label") or trend_id),
                "created": 0,
                "completed": 0,
                "published": 0,
            },
        )
        entry["created"] += 1
        if state == const.TASK_STATE_COMPLETE:
            entry["completed"] += 1
        job_to_trend[str(job_id)] = trend_id

    if job_to_trend:
        events = session.execute(
            select(JobEvent.job_id, JobEvent.status)
            .select_from(JobEvent)
            .join(Job, JobEvent.job_id == Job.id)
            .where(
                Job.user_id == user_id,
                JobEvent.created_at >= cutoff,
                JobEvent.stage == "publish",
            )
        ).all()
        published_jobs = {
            str(job_id)
            for job_id, status in events
            if str(status or "").startswith("native_")
            and str(status or "") != "native_failed"
        }
        for job_id in published_jobs:
            trend_id = job_to_trend.get(job_id)
            if trend_id:
                attributed[trend_id]["published"] += 1

    by_trend = sorted(
        attributed.values(),
        key=lambda item: (-item["published"], -item["completed"], -item["created"], item["key"]),
    )
    return {
        "created": sum(item["created"] for item in by_trend),
        "completed": sum(item["completed"] for item in by_trend),
        "published": sum(item["published"] for item in by_trend),
        "by_trend": by_trend,
    }


def _job_state_label(state: Any) -> str:
    if state == const.TASK_STATE_COMPLETE:
        return "completed"
    if state == const.TASK_STATE_FAILED:
        return "failed"
    return "rendering"


def _forecast_trace(session: Session, user_id: str, cutoff: datetime) -> dict[str, Any]:
    """Trend → forecast → render → native publish → reach, owner-scoped.

    A missing :class:`JobPerformance` row is represented by ``pending`` with
    nullable actual/delta values. It is never coerced to a zero-reach outcome.
    """
    forecast_rows = session.execute(
        select(DiffusionForecastRecord, TrendObservation)
        .join(
            TrendObservation,
            DiffusionForecastRecord.trend_observation_id == TrendObservation.id,
        )
        .where(
            DiffusionForecastRecord.user_id == user_id,
            DiffusionForecastRecord.created_at >= cutoff,
        )
        .order_by(DiffusionForecastRecord.created_at.desc())
    ).all()
    if not forecast_rows:
        return {"status": "available", "traces": [], "by_content_type": []}

    forecast_ids = {str(forecast.id) for forecast, _ in forecast_rows}
    jobs = session.execute(
        select(Job).where(Job.user_id == user_id, Job.created_at >= cutoff)
    ).scalars().all()
    jobs_by_forecast: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        params = job.params if isinstance(job.params, dict) else {}
        source = params.get("source_context")
        if not isinstance(source, dict):
            continue
        forecast_id = str(source.get("forecast_id") or "").strip()
        if forecast_id in forecast_ids:
            jobs_by_forecast[forecast_id].append(job)

    job_ids = [str(job.id) for rows in jobs_by_forecast.values() for job in rows]
    publish_by_job: dict[str, tuple[str, dict, Any]] = {}
    performance_by_job: dict[str, JobPerformance] = {}
    if job_ids:
        event_rows = session.execute(
            select(JobEvent.job_id, JobEvent.status, JobEvent.payload, JobEvent.created_at)
            .select_from(JobEvent)
            .join(Job, JobEvent.job_id == Job.id)
            .where(
                Job.user_id == user_id,
                JobEvent.job_id.in_(job_ids),
                JobEvent.stage == "publish",
            )
            .order_by(JobEvent.created_at.asc())
        ).all()
        for job_id, status, payload, created_at in event_rows:
            if str(status or "").startswith("native_"):
                publish_by_job[str(job_id)] = (
                    str(status)[len("native_"):],
                    payload if isinstance(payload, dict) else {},
                    created_at,
                )
        performances = session.execute(
            select(JobPerformance).where(
                JobPerformance.user_id == user_id,
                JobPerformance.job_id.in_(job_ids),
            )
        ).scalars().all()
        performance_by_job = {str(row.job_id): row for row in performances}

    traces: list[dict[str, Any]] = []
    content_totals: dict[str, dict[str, Any]] = {}
    for forecast, observation in forecast_rows:
        forecast_id = str(forecast.id)
        result = forecast.result if isinstance(forecast.result, dict) else {}
        expected = max(0, int(result.get("expected_reach") or 0))
        content_type = str(forecast.content_type or "short_video")
        linked_jobs: list[Job | None] = jobs_by_forecast.get(forecast_id) or [None]
        for job in linked_jobs:
            job_id = str(job.id) if job is not None else None
            publish = publish_by_job.get(job_id or "")
            performance = performance_by_job.get(job_id or "")
            measured = performance is not None
            actual = max(0, int(performance.views or 0)) if performance is not None else None
            delta = actual - expected if actual is not None else None
            traces.append(
                {
                    "forecast_id": forecast_id,
                    "trend_observation_id": str(observation.id),
                    "trend_id": str(observation.trend_id),
                    "trend_label": str(observation.label or observation.trend_id),
                    "content_type": content_type,
                    "expected_reach": expected,
                    "forecast_created_at": forecast.created_at.isoformat()
                    if forecast.created_at is not None
                    else None,
                    "job_id": job_id,
                    "job_state": _job_state_label(job.state) if job is not None else "not_started",
                    "result_ready": bool(job and job.result_key),
                    "publish_status": publish[0] if publish is not None else "not_started",
                    "publish_platform": str(publish[1].get("platform") or "")
                    if publish is not None
                    else None,
                    "publish_event_at": publish[2].isoformat()
                    if publish is not None and publish[2] is not None
                    else None,
                    "measurement_status": "measured" if measured else "pending",
                    "actual_reach": actual,
                    "delta": delta,
                    "delta_pct": round(delta / expected * 100, 2)
                    if delta is not None and expected > 0
                    else None,
                    "reach_platform": str(performance.platform)
                    if performance is not None
                    else None,
                }
            )
            totals = content_totals.setdefault(
                content_type,
                {
                    "content_type": content_type,
                    "measured": 0,
                    "pending": 0,
                    "expected_reach": 0,
                    "actual_reach": 0,
                },
            )
            if measured and actual is not None:
                totals["measured"] += 1
                totals["expected_reach"] += expected
                totals["actual_reach"] += actual
            else:
                totals["pending"] += 1

    by_content_type: list[dict[str, Any]] = []
    for totals in sorted(content_totals.values(), key=lambda item: item["content_type"]):
        measured = int(totals["measured"])
        if measured:
            delta = int(totals["actual_reach"]) - int(totals["expected_reach"])
            totals["delta"] = delta
            totals["delta_pct"] = (
                round(delta / int(totals["expected_reach"]) * 100, 2)
                if int(totals["expected_reach"]) > 0
                else None
            )
        else:
            totals["expected_reach"] = None
            totals["actual_reach"] = None
            totals["delta"] = None
            totals["delta_pct"] = None
        by_content_type.append(totals)
    return {"status": "available", "traces": traces, "by_content_type": by_content_type}


def _forecast_trace_or_unavailable(
    session: Session, user_id: str, cutoff: datetime
) -> dict[str, Any]:
    """Keep the dashboard honest and usable before the additive migration lands."""
    try:
        return _forecast_trace(session, user_id, cutoff)
    except SQLAlchemyError as exc:
        session.rollback()
        logger.warning(f"forecast trace unavailable for {user_id}: {exc}")
        return {"status": "unavailable", "traces": [], "by_content_type": []}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def creator_analytics(
    session: Session, user_id: str, days: int = _DEFAULT_DAYS
) -> dict[str, Any]:
    """Aggregate a single creator's BI dashboard over the trailing ``days``.

    All figures are strictly scoped to ``user_id`` — there is no cross-user
    aggregation. The current credit balance is the live all-time value; every
    other metric covers the trailing ``days`` window.

    Args:
        session: An active SQLAlchemy session (read-only; not committed here).
        user_id: The creator whose analytics to compute.
        days: Size of the trailing window in days (default 30; clamped to
            ``1.._MAX_DAYS``, with non-positive/invalid values falling back to
            the default).

    Returns:
        A JSON-serializable dict with keys ``user_id``, ``days``, ``funnel``,
        ``cost_by_day``, ``credits``, ``render_time``, ``by_layout``,
        ``by_language``, ``by_variants`` and ``totals``.

    Raises:
        ValueError: If ``user_id`` is empty/blank.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required")

    window_days = _normalize_days(days)
    cutoff = _window_start(window_days)

    params = _iter_job_params(session, user_id, cutoff)
    breakdowns = _breakdowns(params)
    funnel = _funnel(session, user_id, cutoff)
    total_cost = _total_cost_usd(session, user_id, cutoff)

    return {
        "user_id": user_id,
        "days": window_days,
        "funnel": funnel,
        "cost_by_day": _cost_by_day(session, user_id, cutoff),
        "credits": _credits(session, user_id, cutoff),
        "render_time": _render_time(session, user_id, cutoff),
        "by_layout": breakdowns["by_layout"],
        "by_language": breakdowns["by_language"],
        "by_variants": breakdowns["by_variants"],
        "trend_funnel": _trend_funnel(session, user_id, cutoff),
        "forecast_trace": _forecast_trace_or_unavailable(session, user_id, cutoff),
        "totals": {
            "jobs_total": funnel["created"],
            "videos_generated": funnel["completed"],
            "total_cost_usd": total_cost,
        },
    }


def _top_from_counts(counts: dict[str, int], key: str, limit: int) -> list[dict[str, Any]]:
    """Return the ``limit`` most frequent ``{key: value, "count": n}`` entries.

    Ties are broken by the label so the ordering is deterministic.
    """
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{key: label, "count": count} for label, count in ranked[:limit]]


def _hook_from_job(params: dict[str, Any], script: Any) -> Optional[str]:
    """Best-effort hook line for a job: the subject param, else the script's head.

    Returns ``None`` when neither a subject nor a script line can be recovered.
    """
    subject = params.get(_HOOK_KEY)
    if isinstance(subject, str) and subject.strip():
        return subject.strip()
    if isinstance(script, str) and script.strip():
        # First non-empty line of the finalized narration script.
        for line in script.splitlines():
            if line.strip():
                return line.strip()
    return None


def top_content(
    session: Session, user_id: str, limit: int = 10
) -> dict[str, list[dict[str, Any]]]:
    """Rank the creator's most-used templates and hooks (best-effort, all-time).

    Derived from each of the user's ``Job.params`` (a template hint under
    ``template`` / ``template_id`` / ``template_name``) and their ``video_subject``
    param / ``Job.script`` (the hook). Missing fields are tolerated — a job that
    carries neither simply contributes nothing.

    Args:
        session: An active SQLAlchemy session (read-only).
        user_id: The creator whose content to rank.
        limit: Max entries per list (clamped to ``>= 1``).

    Returns:
        ``{"templates": [{"name", "count"}...], "hooks": [{"hook", "count"}...]}``,
        each ordered most-frequent first.

    Raises:
        ValueError: If ``user_id`` is empty/blank.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required")

    capped = max(1, int(limit) if isinstance(limit, int) else 10)

    template_counts: dict[str, int] = defaultdict(int)
    hook_counts: dict[str, int] = defaultdict(int)

    try:
        stmt = select(Job.params, Job.script).where(Job.user_id == user_id)
        rows = session.execute(stmt).all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"top_content query failed for {user_id}: {exc}")
        return {"templates": [], "hooks": []}

    for blob, script in rows:
        params = blob if isinstance(blob, dict) else {}

        for template_key in _TEMPLATE_KEYS:
            value = params.get(template_key)
            if isinstance(value, str) and value.strip():
                template_counts[value.strip()] += 1
                break

        hook = _hook_from_job(params, script)
        if hook:
            hook_counts[hook] += 1

    return {
        "templates": _top_from_counts(template_counts, "name", capped),
        "hooks": _top_from_counts(hook_counts, "hook", capped),
    }


__all__ = ["creator_analytics", "top_content"]
