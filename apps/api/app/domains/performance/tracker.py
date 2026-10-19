"""Track posted reels and read their numbers on a schedule.

Flow per beat tick (:func:`tick`):

1. **Discover** - every publish in the append-only ``JobEvent`` trail
   (``stage=publish``, ``status=native_published``; native and extended
   connectors both write it) becomes a :class:`TrackedPost`.
2. **Claim** due posts (``next_check_at <= now``), oldest first, pushed forward
   by a lease so overlapping ticks never read the same post twice. A per-creator
   cap keeps one account from using the whole tick; a platform that answers
   429 is skipped for the rest of the tick.
3. **Read** each post through the creator's connection (no DB session held
   during the network call), append a :class:`PostSnapshot`, keep the latest
   numbers on the post and schedule the next read (every 2h on day one, down to
   every 3 days, stopping after 60 days).
4. **Feed the hook ranking** - a post linked to a Menivor reel mirrors its
   job's summed numbers into ``JobPerformance`` so the idea engine and the
   winner loop learn from them.

Pasted links (:func:`track_link`) and typed numbers (:func:`add_numbers`) use
the same rows. Everything is owner-scoped.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator

from loguru import logger
from sqlalchemy import delete, select

from . import fetchers
from .fetchers import Access, Stats
from .links import LinkError, PostLink, resolve_post_link
from .models import (
    COUNTERS,
    SOURCE_LINK,
    SOURCE_PUBLISHED,
    STATE_DONE,
    STATE_NEEDS_ACCESS,
    STATE_NO_STATS,
    STATE_TRACKING,
    STATE_WAITING,
    PostSnapshot,
    TrackedPost,
)

DISCOVERY_DAYS = 60
LEASE = timedelta(minutes=10)
MAX_POSTS_PER_TICK = 60
MAX_POSTS_PER_USER_PER_TICK = 8
TICK_BUDGET_S = 240.0
SYNC_LIMIT = 15
SYNC_BUDGET_S = 25.0
SYNC_FRESH = timedelta(minutes=30)
MAX_LINK_POSTS_PER_USER = 500
MAX_TYPED_COUNT = 10_000_000_000
_MAX_BACKOFF = timedelta(hours=24)
_NEEDS_ACCESS_RETRY = timedelta(hours=24)
_NO_STATS_RETRY = timedelta(days=7)
_RATE_LIMIT_RETRY = timedelta(hours=1)
_MATCH_MIN_SCORE = 0.5
_MATCH_MIN_WORDS = 3
_MATCH_CANDIDATES = 300
_PLATFORM_ALIASES = {"youtube_shorts": "youtube", "yt": "youtube"}


class PostNotFound(LookupError):
    """The tracked post does not exist or is not the caller's."""


class TrackingLimit(RuntimeError):
    """The creator is tracking the maximum number of pasted links."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalize_platform(platform: str) -> str:
    plat = str(platform or "").strip().lower()
    return _PLATFORM_ALIASES.get(plat, plat)


def cadence(posted_at: datetime | None, now: datetime) -> timedelta | None:
    """How long until the next read for a post of this age (``None`` = stop)."""
    age = now - (aware(posted_at) or now)
    if age < timedelta(days=1):
        return timedelta(hours=2)
    if age < timedelta(days=3):
        return timedelta(hours=6)
    if age < timedelta(days=14):
        return timedelta(hours=24)
    if age < timedelta(days=DISCOVERY_DAYS):
        return timedelta(hours=72)
    return None


# --------------------------------------------------------------------------- #
# Dependencies (injectable for tests)
# --------------------------------------------------------------------------- #
AccessFn = Callable[[str, str], Access]


def _default_session_factory() -> Callable[[], Any]:
    from app.models.db.base import get_session

    return get_session


def default_access(user_id: str, platform: str) -> Access:
    """The creator's usable connection for ``platform`` (never raises)."""
    plat = normalize_platform(platform)
    if plat == "bluesky":
        return fetchers.NO_ACCESS  # public numbers; no account needed
    try:
        from app.domains.social_inbox.sync import connected_platforms, resolve_account
        from app.models.db.base import get_session

        with get_session() as session:
            scopes = connected_platforms(session, user_id)
            if plat not in scopes:
                return fetchers.NO_ACCESS
            account = resolve_account(session, user_id, plat)
        if not account.connected:
            return Access(connected=False, note=account.note)
        return Access(connected=True, token=account.token, account_id=account.external_account_id,
                      scopes=scopes.get(plat, ""))
    except Exception as exc:  # noqa: BLE001 - treated as not connected for this read
        logger.info(f"performance: {plat} connection unavailable for {user_id}: {exc}")
        return fetchers.NO_ACCESS


@dataclass
class Deps:
    session_factory: Callable[[], Any] | None = None
    transport: Any = None
    access_fn: AccessFn | None = None
    next_location: Callable[[str], str] | None = None
    _access_cache: dict[tuple[str, str], Access] = field(default_factory=dict)

    def session(self) -> Any:
        factory = self.session_factory or _default_session_factory()
        return factory()

    def access(self, user_id: str, platform: str) -> Access:
        key = (user_id, platform)
        if key not in self._access_cache:
            self._access_cache[key] = (self.access_fn or default_access)(user_id, platform)
        return self._access_cache[key]

    def tx(self) -> Any:
        if self.transport is None:
            self.transport = fetchers.default_transport()
        return self.transport


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _job_title(params: Any, script: Any = "") -> str:
    p = params if isinstance(params, dict) else {}
    subject = str(p.get("video_subject") or "").strip()
    if subject:
        return subject[:300]
    text = str(script or p.get("video_script") or "").strip()
    return text.splitlines()[0][:300] if text else ""


def _find(session: Any, user_id: str, platform: str, external_id: str) -> TrackedPost | None:
    return session.execute(
        select(TrackedPost).where(
            TrackedPost.user_id == user_id, TrackedPost.platform == platform,
            TrackedPost.external_id == external_id,
        )
    ).scalars().first()


def discover(session: Any, *, now: datetime, user_id: str | None = None, days: int = DISCOVERY_DAYS) -> int:
    """Track every Menivor publish of the last ``days`` days; returns how many are new."""
    from app.models.db.models import Job, JobEvent

    since = now - timedelta(days=max(1, min(days, DISCOVERY_DAYS)))
    stmt = (
        select(JobEvent, Job.user_id, Job.params, Job.script)
        .join(Job, Job.id == JobEvent.job_id)
        .where(JobEvent.stage == "publish", JobEvent.status == "native_published", JobEvent.created_at >= since)
        .order_by(JobEvent.id.asc())
    )
    if user_id:
        stmt = stmt.where(Job.user_id == user_id)
    rows = session.execute(stmt).all()
    owners = {str(owner) for _, owner, _, _ in rows if owner}
    known: set[tuple[str, str, str]] = set()
    if owners:
        for u, p, e in session.execute(
            select(TrackedPost.user_id, TrackedPost.platform, TrackedPost.external_id)
            .where(TrackedPost.user_id.in_(owners))
        ).all():
            known.add((u, p, e))
    created = 0
    for event, owner, params, script in rows:
        payload = event.payload if isinstance(event.payload, dict) else {}
        platform = normalize_platform(str(payload.get("platform") or ""))
        external_id = str(payload.get("external_id") or "").strip()[:300]
        if not platform or not external_id or not owner:
            continue
        key = (str(owner), platform, external_id)
        if key in known:
            continue
        known.add(key)
        session.add(TrackedPost(
            user_id=str(owner), job_id=str(event.job_id), platform=platform, external_id=external_id,
            url=str(payload.get("url") or "")[:2048], title=_job_title(params, script),
            source=SOURCE_PUBLISHED, state=STATE_WAITING, posted_at=aware(event.created_at), next_check_at=now,
        ))
        created += 1
    if created:
        session.flush()
    return created


# --------------------------------------------------------------------------- #
# Applying a read
# --------------------------------------------------------------------------- #
def _id_kind(platform: str, external_id: str) -> str:
    if platform in ("instagram", "threads") and not external_id.isdigit():
        return "shortcode"
    return "id"


def _duration_s(session: Any, job_id: str | None) -> float:
    if not job_id:
        return 0.0
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None:
        return 0.0
    try:
        from app.domains.insights.winner_loop_service import _final_duration_s

        return _final_duration_s(session, job)
    except Exception:  # noqa: BLE001 - watch-time fraction is optional
        return 0.0


def _schedule_after(post: TrackedPost, stats: Stats, now: datetime) -> tuple[str, datetime | None]:
    """(state, next_check_at) after a read with this outcome."""
    base = cadence(post.posted_at or post.created_at, now)
    if stats.outcome == fetchers.OK:
        return (STATE_TRACKING, now + base) if base else (STATE_DONE, None)
    had_numbers = post.last_checked_at is not None
    if stats.outcome == fetchers.RATE_LIMITED:
        return (post.state if had_numbers else STATE_WAITING), now + _RATE_LIMIT_RETRY
    if stats.outcome == fetchers.NEEDS_ACCESS:
        return STATE_NEEDS_ACCESS, now + _NEEDS_ACCESS_RETRY
    if stats.outcome == fetchers.NO_STATS:
        return STATE_NO_STATS, (now + _NO_STATS_RETRY) if base else None
    step = base or timedelta(hours=24)
    factor = 2 ** min(int(post.failures or 0), 6)
    return (STATE_TRACKING if had_numbers else STATE_WAITING), now + min(step * factor, _MAX_BACKOFF)


def _counters(stats: Any) -> dict[str, int | None]:
    return {k: getattr(stats, k) for k in COUNTERS}


def apply_stats(session: Any, post: TrackedPost, stats: Stats, now: datetime) -> None:
    """Record one read on ``post`` (snapshot + latest numbers + next check)."""
    state, next_at = _schedule_after(post, stats, now)
    post.state = state
    post.next_check_at = next_at
    post.note = stats.note[:500]
    if stats.title and not post.title:
        post.title = stats.title[:300]
    if stats.url and not post.url:
        post.url = stats.url[:2048]
    if stats.outcome != fetchers.OK:
        if stats.outcome not in (fetchers.RATE_LIMITED, fetchers.NEEDS_ACCESS, fetchers.NO_STATS):
            post.failures = int(post.failures or 0) + 1
        return
    post.failures = 0
    post.last_checked_at = now
    for key, value in _counters(stats).items():
        if value is not None:
            setattr(post, key, value)
    if stats.avg_watch_frac is not None:
        post.avg_watch_frac = stats.avg_watch_frac
    session.add(PostSnapshot(post_id=post.id, user_id=post.user_id, captured_at=now, origin="platform",
                             avg_watch_frac=stats.avg_watch_frac, **_counters(stats)))
    session.flush()
    if post.job_id:
        mirror_job(session, post.user_id, post.job_id)


def mirror_job(session: Any, user_id: str, job_id: str) -> None:
    """Sum the job's tracked posts into ``JobPerformance`` (feeds the hook ranking)."""
    from app.models.db.models import Job
    from app.models.db.repositories import JobPerformanceRepository

    job = session.get(Job, job_id)
    if job is None or job.user_id != user_id:
        return
    posts = session.execute(
        select(TrackedPost).where(TrackedPost.user_id == user_id, TrackedPost.job_id == job_id,
                                  TrackedPost.last_checked_at.is_not(None))
    ).scalars().all()
    if not posts:
        return
    metrics: dict[str, Any] = {}
    for key in COUNTERS:
        known = [getattr(p, key) for p in posts if getattr(p, key) is not None]
        if known:
            metrics[key] = sum(known)
    by_platform: dict[str, int] = {}
    for p in posts:
        by_platform[p.platform] = by_platform.get(p.platform, 0) + int(p.views or 0)
    metrics["platform"] = max(by_platform, key=by_platform.get)
    watched = [(p.avg_watch_frac, max(int(p.views or 0), 1)) for p in posts if p.avg_watch_frac is not None]
    if watched:
        weight = sum(w for _, w in watched)
        metrics["retention_pct"] = round(100.0 * sum(f * w for f, w in watched) / weight, 2)
    JobPerformanceRepository(session).upsert(job_id=job_id, user_id=user_id, metrics=metrics)


# --------------------------------------------------------------------------- #
# Reading one post
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Claim:
    post_id: str
    user_id: str
    platform: str
    external_id: str
    url: str
    posted_at: datetime | None
    duration_s: float


def _claim(session: Any, post: TrackedPost, now: datetime) -> _Claim:
    post.next_check_at = now + LEASE
    return _Claim(post.id, post.user_id, post.platform, post.external_id, post.url,
                  aware(post.posted_at) or aware(post.created_at), _duration_s(session, post.job_id))


def _read(claim: _Claim, deps: Deps, now: datetime) -> Stats:
    access = deps.access(claim.user_id, claim.platform)
    return fetchers.fetch(
        claim.user_id, claim.platform, claim.external_id, access,
        posted_on=(claim.posted_at or now).date(), duration_s=claim.duration_s, url=claim.url,
        id_kind=_id_kind(claim.platform, claim.external_id), transport=deps.tx(),
    )


def _store(deps: Deps, claim: _Claim, stats: Stats, now: datetime) -> None:
    with deps.session() as session:
        post = session.get(TrackedPost, claim.post_id)
        if post is None:
            return
        # Pasted links keep the platform's own id once known (fewer lookups next
        # time). Published posts keep the id from the publish trail, which
        # discovery and the winner loop key on.
        if (post.source == SOURCE_LINK and stats.resolved_id and stats.resolved_id != post.external_id
                and len(stats.resolved_id) <= 300):
            if _find(session, post.user_id, post.platform, stats.resolved_id) is None:
                post.external_id = stats.resolved_id
        apply_stats(session, post, stats, now)


def _iter_claims(deps: Deps, stmt: Any, now: datetime, per_user: int, limit: int) -> list[_Claim]:
    claims: list[_Claim] = []
    per: dict[str, int] = {}
    with deps.session() as session:
        for post in session.execute(stmt).scalars().all():
            if per.get(post.user_id, 0) >= per_user:
                continue
            per[post.user_id] = per.get(post.user_id, 0) + 1
            claims.append(_claim(session, post, now))
            if len(claims) >= limit:
                break
    return claims


def _run(claims: list[_Claim], deps: Deps, now: datetime, budget_s: float) -> dict[str, int]:
    started = time.monotonic()
    summary = {"read": 0, "ok": 0, "skipped": 0, "errors": 0}
    throttled: set[str] = set()
    for claim in claims:
        if claim.platform in throttled or time.monotonic() - started > budget_s:
            summary["skipped"] += 1
            continue  # the lease expires and the post is picked up next tick
        try:
            stats = _read(claim, deps, now)
            _store(deps, claim, stats, now)
        except Exception as exc:  # noqa: BLE001 - one post must never break the tick
            summary["errors"] += 1
            logger.error(f"performance: refresh failed for post {claim.post_id}: {exc}")
            continue
        summary["read"] += 1
        summary["ok"] += int(stats.ok)
        if stats.outcome == fetchers.RATE_LIMITED:
            throttled.add(claim.platform)
    return summary


def tick(now: datetime | None = None, *, deps: Deps | None = None) -> dict[str, int]:
    """Discover new publishes and read every due post once (beat entrypoint)."""
    moment = now or utcnow()
    d = deps or Deps()
    with d.session() as session:
        found = discover(session, now=moment)
    stmt = (
        select(TrackedPost)
        .where(TrackedPost.next_check_at.is_not(None), TrackedPost.next_check_at <= moment)
        .order_by(TrackedPost.next_check_at.asc())
        .limit(MAX_POSTS_PER_TICK * 3)
        .with_for_update(skip_locked=True)
    )
    claims = _iter_claims(d, stmt, moment, MAX_POSTS_PER_USER_PER_TICK, MAX_POSTS_PER_TICK)
    return {"discovered": found, **_run(claims, d, moment, TICK_BUDGET_S)}


def sync_user(user_id: str, *, now: datetime | None = None, deps: Deps | None = None) -> dict[str, int]:
    """On-demand refresh for one creator (page open / "check now")."""
    moment = now or utcnow()
    d = deps or Deps()
    with d.session() as session:
        found = discover(session, now=moment, user_id=user_id)
    stale = moment - SYNC_FRESH
    stmt = (
        select(TrackedPost)
        .where(TrackedPost.user_id == user_id, TrackedPost.state != STATE_DONE,
               (TrackedPost.last_checked_at.is_(None)) | (TrackedPost.last_checked_at <= stale))
        .order_by(TrackedPost.created_at.desc())
        .limit(SYNC_LIMIT)
        .with_for_update(skip_locked=True)
    )
    claims = _iter_claims(d, stmt, moment, SYNC_LIMIT, SYNC_LIMIT)
    return {"discovered": found, **_run(claims, d, moment, SYNC_BUDGET_S)}


# --------------------------------------------------------------------------- #
# Pasted links
# --------------------------------------------------------------------------- #
_WORD = re.compile(r"[a-z0-9']{3,}")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(str(text or "").lower()))


def match_job(session: Any, user_id: str, title: str) -> str | None:
    """The creator's reel whose hook/subject matches a post caption, or ``None``."""
    from app.models.db.models import Job

    target = _words(title)
    if len(target) < _MATCH_MIN_WORDS:
        return None
    rows = session.execute(
        select(Job.id, Job.params, Job.script, Job.title)
        .where(Job.user_id == user_id, Job.deleted_at.is_(None))
        .order_by(Job.created_at.desc())
        .limit(_MATCH_CANDIDATES)
    ).all()
    best, best_score = None, 0.0
    for job_id, params, script, job_title in rows:
        for text in (_job_title(params, ""), str(job_title or ""), _job_title({}, script)):
            words = _words(text)
            if len(words) < _MATCH_MIN_WORDS:
                continue
            score = len(target & words) / len(target | words)
            if score > best_score:
                best, best_score = str(job_id), score
    return best if best_score >= _MATCH_MIN_SCORE else None


def _owned(session: Any, user_id: str, post_id: str) -> TrackedPost:
    post = session.get(TrackedPost, str(post_id or ""))
    if post is None or post.user_id != user_id:
        raise PostNotFound("post not found")
    return post


def track_link(user_id: str, raw_url: str, *, now: datetime | None = None, deps: Deps | None = None) -> str:
    """Track a pasted post link and read its numbers now; returns the post id.

    Raises :class:`LinkError` (user-facing) or :class:`TrackingLimit`.
    """
    moment = now or utcnow()
    d = deps or Deps()
    link: PostLink = resolve_post_link(raw_url, next_location=d.next_location)
    with d.session() as session:
        existing = _find(session, user_id, link.platform, link.external_id)
        if existing is not None:
            claim = _claim(session, existing, moment)
        else:
            count = session.execute(
                select(TrackedPost.id).where(TrackedPost.user_id == user_id, TrackedPost.source == SOURCE_LINK)
                .limit(MAX_LINK_POSTS_PER_USER)
            ).all()
            if len(count) >= MAX_LINK_POSTS_PER_USER:
                raise TrackingLimit("You are tracking the most links Menivor can follow. Remove a few first.")
            claim = None
    if claim is not None:
        _store(d, claim, _read(claim, d, moment), moment)
        return claim.post_id

    access = d.access(user_id, link.platform)
    stats = fetchers.fetch(user_id, link.platform, link.external_id, access, posted_on=moment.date(),
                           url=link.url, id_kind=link.id_kind, transport=d.tx())
    title = stats.title or fetchers.public_title(link.platform, link.url, d.tx())
    with d.session() as session:
        if stats.resolved_id:
            merged = _find(session, user_id, link.platform, stats.resolved_id)
            if merged is not None:
                apply_stats(session, merged, stats, moment)
                return merged.id
        post = TrackedPost(
            user_id=user_id, job_id=match_job(session, user_id, title), platform=link.platform,
            external_id=(stats.resolved_id or link.external_id)[:300], url=link.url, title=title[:300],
            source=SOURCE_LINK, state=STATE_WAITING, posted_at=None, next_check_at=moment,
        )
        session.add(post)
        session.flush()
        apply_stats(session, post, stats, moment)
        return post.id


def add_numbers(user_id: str, post_id: str, numbers: dict[str, int | None], *,
                now: datetime | None = None, deps: Deps | None = None) -> None:
    """Record numbers the creator typed for a post the platform does not share."""
    moment = now or utcnow()
    d = deps or Deps()
    clean = {k: (None if numbers.get(k) is None else max(0, min(int(numbers[k] or 0), MAX_TYPED_COUNT)))
             for k in COUNTERS}
    if all(v is None for v in clean.values()):
        raise ValueError("Enter at least one number.")
    with d.session() as session:
        post = _owned(session, user_id, post_id)
        for key, value in clean.items():
            if value is not None:
                setattr(post, key, value)
        post.last_checked_at = moment
        if post.state in (STATE_WAITING, STATE_NO_STATS, STATE_NEEDS_ACCESS):
            post.state = STATE_TRACKING
            post.note = "You entered these numbers."
        session.add(PostSnapshot(post_id=post.id, user_id=user_id, captured_at=moment, origin="typed", **clean))
        session.flush()
        if post.job_id:
            mirror_job(session, user_id, post.job_id)


def stop_tracking(user_id: str, post_id: str, *, deps: Deps | None = None) -> None:
    d = deps or Deps()
    with d.session() as session:
        post = _owned(session, user_id, post_id)
        session.execute(delete(PostSnapshot).where(PostSnapshot.post_id == post.id))
        session.delete(post)


def iter_user_posts(session: Any, user_id: str, limit: int = 200) -> Iterator[TrackedPost]:
    yield from session.execute(
        select(TrackedPost).where(TrackedPost.user_id == user_id)
        .order_by(TrackedPost.created_at.desc()).limit(limit)
    ).scalars().all()


__all__ = [
    "Deps",
    "LinkError",
    "PostNotFound",
    "TrackingLimit",
    "add_numbers",
    "apply_stats",
    "cadence",
    "discover",
    "iter_user_posts",
    "match_job",
    "mirror_job",
    "stop_tracking",
    "sync_user",
    "tick",
    "track_link",
]
