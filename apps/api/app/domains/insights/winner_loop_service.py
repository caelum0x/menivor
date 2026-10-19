"""The remake-winner loop: publish variants → wait → measure → rank → remake.

One call, :func:`advance`, moves a single project (batch) forward as far as it
can right now. It is driven by the Celery beat tick (``tasks_insights``) for
every active loop and by the "Check now" API action for one project:

1. **Render** — wait until no variant is still rendering.
2. **Publish** — when the loop has target platforms and the publishing launch
   flag is open, queue every rendered variant onto the native scheduler at
   spaced slots (``publishing.loop_autopublish``). The due-runner posts them
   through the creator's own connections, with the entitlement re-check and the
   pre-publish content gate.
3. **Wait** — ``check_after_hours`` (default 48h) after the last variant went
   live.
4. **Measure** — pull each post's real numbers from the platform APIs
   (``platform_metrics``); a variant with no API data falls back to the metrics
   the creator logged on the reel (``JobPerformance``).
5. **Rank + explain** — ``winner_ranking``; an inconclusive read is re-checked
   every 24h up to ``MAX_CHECKS`` times, then settled as a low-confidence winner.
6. **Remake** — ``auto`` mode remakes a conclusive winner immediately (within
   the spend cap); ``manual`` mode waits for the one-click action.
7. **Sync** — when the batch is a registered run, the measured numbers are
   written onto its ``Experiment`` rows (``experiments.registration.sync_run``)
   on every tick that has measurements.

Network calls happen outside DB transactions; state transitions re-lock the
batch anchor so a beat tick and a user click cannot double-apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from loguru import logger
from sqlalchemy import String, cast, select

from app.models import const

from .platform_metrics import PostMetrics, fetch_post_metrics, normalize_platform
from .winner_loop_state import (
    LOOP_EVENT_STAGE,
    LOOP_KEY,
    MAX_CHECKS,
    RECHECK_HOURS,
    REMAKE_VARIANTS,
    SETTLED_STATUSES,
    LoopConfigError,
    iso,
    new_state,
    parse_iso,
    read_state,
    utcnow,
    validate_config,
    write_state,
)
from .winner_ranking import VariantInput, explain_win, rank_variants

_FORMAT_KEYS = (
    "layout", "caption_style", "voice_name", "avatar_id", "music_id",
    "background_id", "camera_motion", "target_duration_s", "aspect",
)
_TICK_LOOKBACK = timedelta(days=60)
_REMAKE_RETRY_AFTER = timedelta(hours=6)
_PENDING_PUBLISH = ("pending", "publishing", "processing")
_MAX_TICK_BATCHES = 500


class LoopNotFound(LookupError):
    """The batch does not exist or is not the caller's."""


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def find_anchor(session: Any, batch_id: str, user_id: str, *, lock: bool = False) -> Any:
    """The batch's oldest job (holder of the loop state), owner-scoped."""
    from app.models.db.models import Job

    normalized = str(batch_id or "").strip()
    if not normalized:
        return None
    stmt = (
        select(Job)
        .where(Job.batch_id == normalized, Job.user_id == user_id)
        .order_by(Job.created_at.asc(), Job.id.asc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    return session.execute(stmt).scalars().first()


def _batch_jobs(session: Any, batch_id: str, user_id: str) -> list:
    from app.models.db.repositories import JobRepository

    return JobRepository(session).list_by_batch(batch_id, user_id)


def _published_posts(session: Any, job_ids: list[str]) -> dict[str, list[dict]]:
    """Every live native post per job, from the append-only publish audit trail."""
    from app.models.db.models import JobEvent

    if not job_ids:
        return {}
    rows = session.execute(
        select(JobEvent)
        .where(JobEvent.job_id.in_(job_ids), JobEvent.stage == "publish", JobEvent.status == "native_published")
        .order_by(JobEvent.id.asc())
    ).scalars().all()
    out: dict[str, list[dict]] = {}
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        platform = normalize_platform(str(payload.get("platform") or ""))
        external_id = str(payload.get("external_id") or "").strip()
        key = (row.job_id, platform, external_id)
        if not platform or key in seen:
            continue
        seen.add(key)
        posted = row.created_at
        if posted is not None and posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        out.setdefault(row.job_id, []).append(
            {"platform": platform, "external_id": external_id, "url": str(payload.get("url") or ""),
             "posted_at": posted}
        )
    return out


def _pending_publishes(session: Any, user_id: str, job_ids: list[str]) -> set[str]:
    from app.models.db.models import ScheduledPublish

    if not job_ids:
        return set()
    rows = session.execute(
        select(ScheduledPublish.job_id).where(
            ScheduledPublish.user_id == user_id,
            ScheduledPublish.job_id.in_(job_ids),
            ScheduledPublish.status.in_(_PENDING_PUBLISH),
        )
    ).all()
    return {r[0] for r in rows}


def _logged_performance(session: Any, user_id: str, job_ids: list[str]) -> dict[str, Any]:
    from app.models.db.models import JobPerformance

    if not job_ids:
        return {}
    rows = session.execute(
        select(JobPerformance).where(JobPerformance.user_id == user_id, JobPerformance.job_id.in_(job_ids))
    ).scalars().all()
    return {r.job_id: r for r in rows}


def _final_duration_s(session: Any, job: Any) -> float:
    from app.models.db.models import Asset

    asset = session.execute(
        select(Asset).where(Asset.job_id == job.id, Asset.kind == "final").order_by(Asset.created_at.desc()).limit(1)
    ).scalars().first()
    if asset is not None and float(asset.duration_s or 0) > 0:
        return float(asset.duration_s)
    params = job.params if isinstance(job.params, dict) else {}
    try:
        return float(params.get("target_duration_s") or 0)
    except (TypeError, ValueError):
        return 0.0


def _hook_of(job: Any) -> str:
    from .remake import winning_hook

    return winning_hook(job)[0]


def _format_of(job: Any) -> dict:
    params = job.params if isinstance(job.params, dict) else {}
    return {k: params.get(k) for k in _FORMAT_KEYS}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _record(job_id: str, status: str, message: str, payload: dict | None = None) -> None:
    try:
        from app.telemetry import events as telemetry_events

        telemetry_events.record_event(job_id, LOOP_EVENT_STAGE, status, message=message, payload=payload or {})
    except Exception:  # pragma: no cover - telemetry is best-effort
        pass


def _publishing_open() -> bool:
    try:
        from app.core.launch.policy import publishing_enabled

        return bool(publishing_enabled())
    except Exception:  # noqa: BLE001 - a broken flag reads as closed (fail safe)
        return False


# --------------------------------------------------------------------------- #
# Configure
# --------------------------------------------------------------------------- #
def _remake_unit_credits(jobs: list) -> int:
    """Per-render credits a remake of these variants costs (per-SKU, never below the flat knob)."""
    from app.domains.reels.policy import job_cost, render_credits

    prices = [int(job_cost())]
    for job in jobs:
        params = getattr(job, "params", None)
        if isinstance(params, dict):
            try:
                prices.append(render_credits(params))
            except Exception:  # noqa: BLE001 - an unreadable variant keeps the flat floor
                continue
    return max(prices)


def configure(
    user_id: str,
    batch_id: str,
    *,
    mode: str,
    platforms: list[str],
    spend_cap_credits: int | None,
    check_after_hours: int | None,
    min_views: int | None,
) -> dict:
    """Create or update a project's loop config. Returns the new state."""
    from app.domains.publishing.loop_autopublish import normalize_loop_platforms
    from app.models.db.base import get_session

    try:
        normalized_platforms = normalize_loop_platforms(platforms)
    except ValueError as exc:
        raise LoopConfigError(str(exc)) from exc

    with get_session() as session:
        anchor = find_anchor(session, batch_id, user_id, lock=True)
        if anchor is None:
            raise LoopNotFound(batch_id)
        jobs = _batch_jobs(session, batch_id, user_id)
        if len(jobs) < 2:
            raise LoopConfigError("the loop needs a project with at least 2 variants to compare")
        state = read_state(anchor)
        existing_cap = state.get("spend_cap_credits") if state else None
        config = validate_config(
            mode=mode,
            spend_cap_credits=spend_cap_credits if spend_cap_credits is not None else existing_cap,
            check_after_hours=check_after_hours if check_after_hours is not None else state.get("check_after_hours"),
            min_views=min_views if min_views is not None else state.get("min_views"),
            job_cost=_remake_unit_credits(jobs),
        )
        if not state:
            state = new_state(batch_id=batch_id, config=config, platforms=normalized_platforms)
        else:
            state = {**state, **config, "platforms": normalized_platforms}
        root_id = str(state.get("root_batch_id") or batch_id)
        if root_id != batch_id:
            root = find_anchor(session, root_id, user_id, lock=True)
            if root is not None:
                root_state = read_state(root)
                write_state(root, {**root_state, "spend_cap_credits": config["spend_cap_credits"]})
                spent = int(root_state.get("spent_credits", 0) or 0)
            else:
                spent = 0
        else:
            spent = int(state.get("spent_credits", 0) or 0)
        # H3: the remake estimate is priced per SKU from the project's own
        # variants (by length, presenter floor), like the remake debit.
        remake_unit = _remake_unit_credits(jobs)
        if state.get("status") == "cap_reached" and spent + remake_unit * REMAKE_VARIANTS <= config["spend_cap_credits"]:
            state = {**state, "status": "winner_ready", "note": ""}
        state = write_state(anchor, state)
        anchor_id = anchor.id
    _record(anchor_id, "configured",
            f"loop {config['mode']}: platforms {', '.join(normalized_platforms) or 'none (you post)'}; "
            f"check after {config['check_after_hours']}h; cap {config['spend_cap_credits']} credits",
            {"mode": config["mode"], "platforms": normalized_platforms})
    return state


# --------------------------------------------------------------------------- #
# Advance
# --------------------------------------------------------------------------- #
@dataclass
class _Snapshot:
    """What phase 1 learned; phase 2 does the network reads from it."""

    state: dict
    need_check: bool = False
    early: bool = False
    variants: list[dict] = field(default_factory=list)


def _phase_one(user_id: str, batch_id: str, now: datetime, force_check: bool) -> _Snapshot:
    from app.domains.publishing.loop_autopublish import schedule_loop_variants
    from app.models.db.base import get_session
    from app.services.scheduler import ScheduleError

    events: list[tuple[str, str, dict]] = []
    with get_session() as session:
        anchor = find_anchor(session, batch_id, user_id, lock=True)
        if anchor is None:
            raise LoopNotFound(batch_id)
        state = read_state(anchor)
        if not state or state.get("mode") == "off" or state.get("status") in SETTLED_STATUSES:
            return _Snapshot(state=state)

        jobs = _batch_jobs(session, batch_id, user_id)
        rendering = [j for j in jobs if j.state == const.TASK_STATE_PROCESSING]
        complete = [j for j in jobs if j.state == const.TASK_STATE_COMPLETE]
        complete_ids = [j.id for j in complete]
        note = ""

        platforms = list(state.get("platforms") or [])
        if platforms and complete_ids:
            if _publishing_open():
                try:
                    created = schedule_loop_variants(session, user_id, complete_ids, platforms, now=now)
                except (ScheduleError, ValueError) as exc:
                    created = []
                    note = f"Could not queue variants for publishing: {exc}"
                for item in created:
                    events.append(("scheduled", f"variant queued for {item['platform']} at {item['scheduled_at']}", item))
            else:
                note = (
                    "Direct publishing is not enabled yet. Post the variants yourself and log each "
                    "reel's results; the loop will rank them from those numbers."
                )

        posts = _published_posts(session, complete_ids)
        pending = _pending_publishes(session, user_id, complete_ids)
        logged = _logged_performance(session, user_id, complete_ids)
        measurable = [j for j in complete if posts.get(j.id) or logged.get(j.id) is not None]

        status = state.get("status") or "awaiting_render"
        check_due = parse_iso(state.get("check_due_at"))
        last_post = None
        need_check = False
        early = False
        if rendering:
            status = "awaiting_render"
        elif pending and not force_check:
            status = "publishing"
        elif len(measurable) < 2:
            status = "waiting_for_posts"
            note = note or (
                "Waiting for at least 2 variants to be posted. Turn on auto-publish platforms, "
                "or post them yourself and log their results."
            )
        else:
            times = [p["posted_at"] for j in measurable for p in posts.get(j.id, []) if p.get("posted_at")]
            times += [
                _aware(logged[j.id].logged_at)
                for j in measurable if j.id in logged and logged[j.id].logged_at is not None and not posts.get(j.id)
            ]
            last_post = max(times) if times else now
            if check_due is None:
                check_due = last_post + timedelta(hours=int(state.get("check_after_hours") or 48))
            waiting_status = "measuring" if status == "measuring" else "live"
            if now >= check_due:
                need_check, status = True, "measuring"
            elif force_check:
                need_check, early, status = True, True, waiting_status
            else:
                status = waiting_status

        state = write_state(anchor, {
            **state,
            "status": status,
            "note": note,
            "last_post_at": iso(last_post) if last_post else state.get("last_post_at"),
            "check_due_at": iso(check_due) if check_due else state.get("check_due_at"),
        })
        variants = []
        if need_check:
            for job in measurable:
                perf = logged.get(job.id)
                variants.append({
                    "job_id": job.id,
                    "hook": _hook_of(job),
                    "format": _format_of(job),
                    "posts": posts.get(job.id, []),
                    "duration_s": _final_duration_s(session, job),
                    "logged": None if perf is None else {
                        "views": perf.views, "likes": perf.likes, "comments": perf.comments,
                        "shares": perf.shares, "saves": perf.saves, "retention_pct": perf.retention_pct,
                    },
                })
        anchor_id = anchor.id
    for status_name, message, payload in events:
        _record(anchor_id, status_name, message, payload)
    return _Snapshot(state=state, need_check=need_check, early=early, variants=variants)


def _view_weighted(metrics: list[PostMetrics], attr: str) -> float | None:
    """View-weighted mean of a per-post ratio over the posts that report it.

    Posts whose platform did not report the ratio are left out rather than
    counted as 0; ``None`` when no post reported it at all.
    """
    reported = [(m, getattr(m, attr)) for m in metrics if getattr(m, attr) is not None]
    if not reported:
        return None
    weight = sum(max(m.views, 1) for m, _ in reported)
    return sum(float(value) * max(m.views, 1) for m, value in reported) / weight


def _measure(user_id: str, variant: dict, transport: Any) -> tuple[VariantInput, list[dict], str]:
    """Pull every post of one variant; fall back to creator-logged numbers."""
    pulled: list[PostMetrics] = []
    for post in variant["posts"]:
        posted_at = post.get("posted_at") or utcnow()
        pulled.append(fetch_post_metrics(
            user_id, post["platform"], post["external_id"],
            published_on=posted_at.date(), duration_s=variant["duration_s"], url=post.get("url", ""),
            transport=transport,
        ))
    available = [m for m in pulled if m.available]
    posted_times = [p["posted_at"] for p in variant["posts"] if p.get("posted_at")]
    posted_at = min(posted_times) if posted_times else None
    if available:
        views = sum(m.views for m in available)
        return VariantInput(
            job_id=variant["job_id"], hook=variant["hook"], views=views,
            likes=sum(m.likes for m in available), comments=sum(m.comments for m in available),
            shares=sum(m.shares for m in available), saves=sum(m.saves for m in available),
            avg_watch_frac=_view_weighted(available, "avg_watch_frac"),
            completion_rate=_view_weighted(available, "completion_rate"),
            rewatch_rate=_view_weighted(available, "rewatch_rate"),
            posted_at=posted_at, format=variant["format"],
        ), [m.to_record() for m in pulled], "platform"
    logged = variant.get("logged")
    if logged:
        retention = float(logged.get("retention_pct") or 0.0)
        return VariantInput(
            job_id=variant["job_id"], hook=variant["hook"], views=int(logged.get("views") or 0),
            likes=int(logged.get("likes") or 0), comments=int(logged.get("comments") or 0),
            shares=int(logged.get("shares") or 0), saves=int(logged.get("saves") or 0),
            avg_watch_frac=(retention / 100.0) if retention > 0 else None,
            posted_at=posted_at, format=variant["format"],
        ), [m.to_record() for m in pulled], "logged"
    return VariantInput(job_id=variant["job_id"], hook=variant["hook"], posted_at=posted_at,
                        format=variant["format"]), [m.to_record() for m in pulled], "none"


def _persist_platform_metrics(session: Any, user_id: str, measured: list[tuple[VariantInput, list[dict], str]]) -> None:
    """Mirror API-sourced numbers into ``JobPerformance`` so the hook win-score learns from them."""
    from app.models.db.repositories import JobPerformanceRepository

    repo = JobPerformanceRepository(session)
    for inp, posts, source in measured:
        if source != "platform":
            continue
        by_platform: dict[str, int] = {}
        for p in posts:
            if p.get("available"):
                by_platform[p["platform"]] = by_platform.get(p["platform"], 0) + int(p.get("views") or 0)
        metrics: dict[str, Any] = {
            "platform": max(by_platform, key=by_platform.get) if by_platform else "unknown",
            "views": inp.views, "likes": inp.likes, "comments": inp.comments,
            "shares": inp.shares, "saves": inp.saves,
        }
        if inp.avg_watch_frac is not None:
            metrics["retention_pct"] = round(inp.avg_watch_frac * 100.0, 2)
        repo.upsert(job_id=inp.job_id, user_id=user_id, metrics=metrics)


def advance(
    user_id: str,
    batch_id: str,
    *,
    now: datetime | None = None,
    force_check: bool = False,
    allow_auto_remake: bool = True,
    transport: Any = None,
) -> dict:
    """Move one project's loop forward as far as possible. Returns the new state."""
    effective_now = (now or utcnow()).astimezone(timezone.utc)
    snap = _phase_one(user_id, batch_id, effective_now, force_check)
    state = snap.state
    if snap.need_check:
        measured = [_measure(user_id, v, transport) for v in snap.variants]
        state = _apply_measurement(user_id, batch_id, measured, effective_now, early=snap.early)
    if allow_auto_remake and _should_auto_remake(state, effective_now):
        state = _auto_remake(user_id, batch_id, state)
    if state.get("variants"):
        sync_experiment(user_id, batch_id)
    return state


def sync_experiment(user_id: str, batch_id: str) -> bool:
    """Mirror the loop's measured numbers onto the run's Experiment rows.

    A batch registered as a run (``run:<batch_id>``) gets its variants' views,
    watch fraction, engagement rate and, when a platform reported them,
    completion and rewatch rates written back, and the retention-weighted
    verdict re-evaluated. Batches without an experiment are skipped. Never
    raises: a failed sync must not break the loop tick. Returns whether an
    experiment was synced.
    """
    from app.domains.experiments.registration import RunRegistrationError, sync_run
    from app.models.db.base import get_session

    try:
        with get_session() as session:
            sync_run(session, user_id=user_id, batch_id=batch_id)
    except RunRegistrationError:
        return False  # not a registered run (or not this creator's): nothing to sync
    except Exception as exc:  # noqa: BLE001 - one project must never break the tick
        logger.warning(f"experiment sync failed for batch {batch_id}: {exc}")
        return False
    return True


def _apply_measurement(
    user_id: str,
    batch_id: str,
    measured: list[tuple[VariantInput, list[dict], str]],
    now: datetime,
    *,
    early: bool,
) -> dict:
    from app.models.db.base import get_session

    inputs = [m[0] for m in measured]
    with get_session() as session:
        anchor = find_anchor(session, batch_id, user_id, lock=True)
        if anchor is None:
            raise LoopNotFound(batch_id)
        state = read_state(anchor)
        if state.get("status") in SETTLED_STATUSES or state.get("mode") == "off":
            return state  # someone else settled it while we were reading the platforms
        result = rank_variants(inputs, min_views=int(state.get("min_views") or 0))
        explanation = explain_win(result, inputs)
        variants = [
            {"job_id": inp.job_id, "hook": inp.hook, "source": source, "views": inp.views,
             "likes": inp.likes, "comments": inp.comments, "shares": inp.shares, "saves": inp.saves,
             "engagement_rate": round(inp.engagement_rate, 4),
             "avg_watch_frac": None if inp.avg_watch_frac is None else round(inp.avg_watch_frac, 4),
             "completion_rate": None if inp.completion_rate is None else round(inp.completion_rate, 4),
             "rewatch_rate": None if inp.rewatch_rate is None else round(inp.rewatch_rate, 4),
             "posted_at": iso(inp.posted_at), "posts": posts}
            for inp, posts, source in measured
        ]
        _persist_platform_metrics(session, user_id, measured)
        base = {**state, "variants": variants, "ranking": result.to_record(), "last_checked_at": iso(now)}
        event: tuple[str, str, dict]
        if early:
            state = write_state(anchor, {**base, "early_read": True, "explanation": explanation})
            event = ("measured", "early read: numbers pulled before the check window closed",
                     {"leader": result.winner_job_id, "conclusive": result.conclusive})
        else:
            checks = int(state.get("checks", 0) or 0) + 1
            has_leader = bool(result.winner_job_id) and any(i.views > 0 for i in inputs)
            if result.conclusive or (checks >= MAX_CHECKS and has_leader):
                state = write_state(anchor, {
                    **base, "early_read": False, "checks": checks, "status": "winner_ready",
                    "winner_job_id": result.winner_job_id, "conclusive": result.conclusive,
                    "explanation": explanation, "note": "" if result.conclusive else
                    "Low-confidence winner: the numbers never separated clearly. Remake it manually if you agree.",
                })
                event = ("winner", f"winner picked ({'high' if result.conclusive else 'low'} confidence): "
                         f"{explanation['headline']}",
                         {"winner_job_id": result.winner_job_id, "conclusive": result.conclusive})
            elif checks >= MAX_CHECKS:
                state = write_state(anchor, {
                    **base, "early_read": False, "checks": checks, "status": "inconclusive",
                    "explanation": explanation,
                    "note": "No usable numbers after several checks. Check the platform connections and permissions.",
                })
                event = ("inconclusive", "no usable metrics after the final check", {"reason": result.reason})
            else:
                due = now + timedelta(hours=RECHECK_HOURS)
                state = write_state(anchor, {
                    **base, "early_read": False, "checks": checks, "status": "measuring",
                    "check_due_at": iso(due), "explanation": explanation,
                    "note": f"Not decisive yet ({result.reason}). Checking again in {RECHECK_HOURS}h.",
                })
                event = ("extended", f"not decisive yet: {result.reason}; next check {iso(due)}",
                         {"reason": result.reason})
        anchor_id = anchor.id
    _record(anchor_id, *event)
    return state


def _should_auto_remake(state: dict, now: datetime) -> bool:
    if state.get("mode") != "auto" or state.get("status") != "winner_ready":
        return False
    if not state.get("conclusive") or state.get("remake_batch_id"):
        return False
    attempted = parse_iso(state.get("remake_attempted_at"))
    return attempted is None or now - attempted >= _REMAKE_RETRY_AFTER


def _auto_remake(user_id: str, batch_id: str, state: dict) -> dict:
    from app.models.db.base import get_session

    from .remake import RemakeError, remake_winner

    with get_session() as session:
        anchor = find_anchor(session, batch_id, user_id, lock=True)
        if anchor is not None:
            current = read_state(anchor)
            write_state(anchor, {**current, "remake_attempted_at": iso(utcnow())})
    try:
        remake_winner(user_id, batch_id, source="auto")
    except RemakeError as exc:
        with get_session() as session:
            anchor = find_anchor(session, batch_id, user_id, lock=True)
            if anchor is not None:
                current = read_state(anchor)
                if current.get("status") != "cap_reached":
                    write_state(anchor, {**current, "note": f"Automatic remake did not start: {exc}"})
                    _record(anchor.id, "remake_failed", f"automatic remake did not start: {exc}")
    except Exception as exc:  # noqa: BLE001 - one project must never break the tick
        logger.error(f"auto remake failed for batch {batch_id}: {exc}")
    with get_session() as session:
        anchor = find_anchor(session, batch_id, user_id)
        return read_state(anchor) if anchor is not None else state


# --------------------------------------------------------------------------- #
# Beat tick
# --------------------------------------------------------------------------- #
def active_loops(session: Any, now: datetime) -> list[tuple[str, str]]:
    """(user_id, batch_id) for every anchor holding a loop that may need work."""
    from app.models.db.models import Job

    rows = session.execute(
        select(Job.user_id, Job.batch_id, Job.stages)
        .where(
            Job.batch_id.isnot(None),
            Job.created_at >= now - _TICK_LOOKBACK,
            cast(Job.stages, String).contains(LOOP_KEY),
        )
        .order_by(Job.created_at.asc())
        .limit(_MAX_TICK_BATCHES * 3)
    ).all()
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for user_id, batch_id, stages in rows:
        state = stages.get(LOOP_KEY) if isinstance(stages, dict) else None
        if not isinstance(state, dict) or batch_id in seen:
            continue
        if state.get("mode") == "off":
            continue
        status = state.get("status")
        if status in ("remade", "cap_reached", "inconclusive"):
            continue
        if status == "winner_ready" and not _should_auto_remake(state, now):
            continue
        seen.add(batch_id)
        out.append((str(user_id), str(batch_id)))
        if len(out) >= _MAX_TICK_BATCHES:
            break
    return out


def tick(now: datetime | None = None, *, advance_fn: Callable[..., dict] | None = None) -> dict[str, int]:
    """Advance every active loop once. Never raises; returns a summary."""
    from app.models.db.base import get_session

    effective_now = (now or utcnow()).astimezone(timezone.utc)
    step = advance_fn or advance
    with get_session() as session:
        loops = active_loops(session, effective_now)
    summary = {"loops": len(loops), "advanced": 0, "winners": 0, "remade": 0, "errors": 0}
    for user_id, batch_id in loops:
        try:
            state = step(user_id, batch_id, now=effective_now)
        except LoopNotFound:
            continue
        except Exception as exc:  # noqa: BLE001 - one bad project must not stop the rest
            summary["errors"] += 1
            logger.error(f"winner loop advance failed for batch {batch_id}: {exc}")
            continue
        summary["advanced"] += 1
        if state.get("status") == "winner_ready":
            summary["winners"] += 1
        if state.get("status") == "remade":
            summary["remade"] += 1
    return summary


__all__ = [
    "LoopNotFound",
    "active_loops",
    "advance",
    "configure",
    "find_anchor",
    "sync_experiment",
    "tick",
]
