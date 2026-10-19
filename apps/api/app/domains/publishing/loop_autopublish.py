"""Auto-publish scheduling for remake-winner loop variants.

When a creator turns the winner loop on for a batch, every rendered variant is
queued onto the existing native scheduled-publish path (``ScheduledPublish`` →
the minute due-runner → ``native_service.publish_scheduled_reel_native``, which
re-checks entitlement and runs the pre-publish content gate). Nothing here posts
directly.

Variants of the same batch must not cannibalize each other, so each
``(variant, platform)`` post is given its own slot by the pure
:mod:`scheduling_policy` (daily cap, min-gap, best-hour windows), seeded with the
creator's already-queued/posted times for that platform.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from loguru import logger

from app.domains.publishing.scheduling_policy import decide

# Loop platform name -> scheduled-publish platform name (scheduler vocabulary).
_SCHEDULE_NAME = {"tiktok": "tiktok", "instagram": "instagram", "youtube": "youtube_shorts"}
# Scheduled-publish platform name -> scheduling-policy platform name.
_POLICY_NAME = {"tiktok": "tiktok", "instagram": "instagram", "youtube_shorts": "youtube"}

LOOP_PLATFORMS: tuple[str, ...] = ("tiktok", "instagram", "youtube")
_LIVE_STATUSES = ("pending", "publishing", "processing", "published")
# A failed post (e.g. held by the content gate) is not retried automatically;
# the creator sees it on the loop timeline and can publish it by hand.
_ATTEMPTED_STATUSES = (*_LIVE_STATUSES, "failed")
_FIRST_SLOT_DELAY = timedelta(minutes=5)
_HISTORY_WINDOW = timedelta(days=3)


def normalize_loop_platforms(platforms: Iterable[str]) -> list[str]:
    """Validate + de-duplicate loop platforms (``tiktok|instagram|youtube``)."""
    out: list[str] = []
    for raw in platforms or ():
        plat = str(raw or "").strip().lower()
        plat = "youtube" if plat in ("youtube_shorts", "yt") else plat
        if plat not in LOOP_PLATFORMS:
            raise ValueError(f"unsupported platform {raw!r}; expected one of {list(LOOP_PLATFORMS)}")
        if plat not in out:
            out.append(plat)
    return out


def plan_slots(
    job_ids: list[str],
    platforms: list[str],
    *,
    now: datetime,
    history: dict[str, list[datetime]],
) -> list[tuple[str, str, datetime]]:
    """Pure: assign a publish time to every ``(job_id, schedule_platform)`` pair.

    ``history`` maps a schedule platform name to the creator's recent/queued post
    times on it. Each newly planned slot is appended to that history so the next
    variant is spaced after it (min-gap + daily cap honored across the batch).
    """
    plan: list[tuple[str, str, datetime]] = []
    working = {k: list(v) for k, v in history.items()}
    for platform in platforms:
        sched_name = _SCHEDULE_NAME[platform]
        policy_name = _POLICY_NAME[sched_name]
        for job_id in job_ids:
            recent = working.setdefault(sched_name, [])
            candidate = now + _FIRST_SLOT_DELAY
            verdict = decide(policy_name, candidate, now=now, recent_posts=recent)
            run_at = verdict.run_at if not verdict.allow else candidate
            if run_at <= now:
                run_at = candidate
            plan.append((job_id, sched_name, run_at))
            recent.append(run_at)
    return plan


def _history(session: Any, user_id: str, now: datetime) -> dict[str, list[datetime]]:
    from app.models.db.models import ScheduledPublish

    rows = (
        session.query(ScheduledPublish)
        .filter(
            ScheduledPublish.user_id == user_id,
            ScheduledPublish.status.in_(_LIVE_STATUSES),
            ScheduledPublish.scheduled_at >= now - _HISTORY_WINDOW,
        )
        .all()
    )
    out: dict[str, list[datetime]] = {}
    for row in rows:
        at = row.scheduled_at
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        for plat in row.platforms or []:
            out.setdefault(str(plat), []).append(at)
    return out


def already_queued(session: Any, user_id: str, job_id: str) -> set[str]:
    """Schedule platform names this job was already queued/posted/attempted on (not canceled)."""
    from app.models.db.models import ScheduledPublish

    rows = (
        session.query(ScheduledPublish)
        .filter(
            ScheduledPublish.user_id == user_id,
            ScheduledPublish.job_id == job_id,
            ScheduledPublish.status.in_(_ATTEMPTED_STATUSES),
        )
        .all()
    )
    return {str(p) for row in rows for p in (row.platforms or [])}


def schedule_loop_variants(
    session: Any,
    user_id: str,
    job_ids: list[str],
    platforms: list[str],
    *,
    now: datetime | None = None,
    youtube_privacy_status: str = "public",
) -> list[dict]:
    """Queue every not-yet-queued ``(variant, platform)`` onto the native scheduler.

    Caller guarantees: the publishing launch flag is open, the jobs are the
    caller's COMPLETE variants, and native connections exist. Returns one record
    per created schedule (``{job_id, platform, schedule_id, scheduled_at}``).
    """
    from app.services.scheduler import schedule_publish

    effective_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    loop_platforms = normalize_loop_platforms(platforms)
    pending_pairs: dict[str, list[str]] = {}
    for platform in loop_platforms:
        sched_name = _SCHEDULE_NAME[platform]
        for job_id in job_ids:
            if sched_name not in already_queued(session, user_id, job_id):
                pending_pairs.setdefault(platform, []).append(job_id)
    if not pending_pairs:
        return []

    history = _history(session, user_id, effective_now)
    created: list[dict] = []
    for platform, pair_jobs in pending_pairs.items():
        for job_id, sched_name, run_at in plan_slots(
            pair_jobs, [platform], now=effective_now, history=history
        ):
            row = schedule_publish(
                session,
                user_id,
                job_id,
                [sched_name],
                run_at,
                youtube_privacy_status=youtube_privacy_status,
                now=effective_now,
            )
            history.setdefault(sched_name, []).append(run_at)
            created.append(
                {
                    "job_id": job_id,
                    "platform": sched_name,
                    "schedule_id": row.id,
                    "scheduled_at": run_at.isoformat(),
                }
            )
    logger.info(f"winner loop queued {len(created)} variant post(s) for user {user_id}")
    return created


__all__ = [
    "LOOP_PLATFORMS",
    "already_queued",
    "normalize_loop_platforms",
    "plan_slots",
    "schedule_loop_variants",
]
