"""Pull comments/DMs for Menivor-published posts and keep the inbox current.

Flow per beat tick (:func:`tick`):

1. **Discover** - every native publish recorded in the append-only ``JobEvent``
   trail (``stage=publish``, ``status=native_published``) in the last
   ``_DISCOVERY_DAYS`` days becomes a tracked :class:`InboxPost`. Creators with a
   tracked Instagram post also get one "Direct messages" channel row.
2. **Claim due posts** - rows whose ``next_poll_at`` has passed, oldest first,
   ``FOR UPDATE SKIP LOCKED`` and pushed forward by a lease so overlapping ticks
   never double-poll. A per-creator cap keeps one account from eating the tick.
3. **Sync one post** - resolve the creator's connection (DB), call the platform
   (no DB connection held), then write threads + counts (DB).
4. **Feed the winner loop** - the comments actually observed for a job are
   raised into ``JobPerformance.comments`` (never lowered, never invented).

Poll cadence decays with post age (15 min for the first 2 days down to daily,
stopping after 90 days); failures back off exponentially. Platform quotas are
respected by bounding pages per poll (YouTube: 1 unit per page).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select

from . import bluesky_client, facebook_client, instagram_client, threads_client, youtube_client
from . import repository as repo
from .capabilities import (
    CHANNEL_INBOX_PLATFORMS,
    EXTENDED_INBOX_PLATFORMS,
    EXTENDED_PLATFORMS,
    NEEDS_PERMISSION,
    NOT_OFFERED,
    PlatformCapabilities,
    capabilities_for,
)
from .models import (
    STATE_ERROR,
    STATE_MISSING_PERMISSION,
    STATE_NOT_CONNECTED,
    STATE_NOT_OFFERED,
    STATE_OK,
    InboxPost,
)
from .platform_types import FetchedThread, InboxPlatformError, Transport, default_transport

try:
    from app.models.db.base import get_session
    from app.services import oauth_connect

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - import-safe; callers get a clear error
    get_session = None  # type: ignore[assignment]
    oauth_connect = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc

_DISCOVERY_DAYS = 90
_TICK_DISCOVERY_DAYS = 2
_LEASE = timedelta(minutes=10)
_MAX_POSTS_PER_TICK = 40
_MAX_POSTS_PER_USER_PER_TICK = 10
_MAX_BACKOFF = timedelta(hours=24)
_TICK_BUDGET_S = 180.0
_SUPPORTED = frozenset({"youtube", "instagram", "tiktok"}) | EXTENDED_PLATFORMS
_PLATFORM_ALIASES = {"youtube_shorts": "youtube", "yt": "youtube"}


class InboxUnavailable(RuntimeError):
    """The persistence layer is not importable (router maps to 503)."""


def require_ready() -> None:
    if get_session is None or oauth_connect is None:
        raise InboxUnavailable(f"social inbox persistence unavailable: {_DB_IMPORT_ERROR}")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalize_platform(platform: str) -> str:
    plat = str(platform or "").strip().lower()
    return _PLATFORM_ALIASES.get(plat, plat)


# --------------------------------------------------------------------------- #
# Schedule
# --------------------------------------------------------------------------- #
def poll_interval(posted_at: datetime | None, now: datetime) -> timedelta | None:
    """How long until the next poll for a post of this age (``None`` = stop)."""
    age = now - (_aware(posted_at) or now)
    if age < timedelta(days=2):
        return timedelta(minutes=15)
    if age < timedelta(days=7):
        return timedelta(hours=1)
    if age < timedelta(days=30):
        return timedelta(hours=6)
    if age < timedelta(days=_DISCOVERY_DAYS):
        return timedelta(hours=24)
    return None


def _next_poll(post: InboxPost, now: datetime, *, failed: bool) -> datetime | None:
    if repo.is_dm_channel(post):
        base = timedelta(minutes=15)
    else:
        base = poll_interval(post.posted_at, now)
        if base is None:
            return None
    if failed:
        factor = 2 ** min(int(post.poll_failures or 0), 6)
        return now + min(base * factor, _MAX_BACKOFF)
    return now + base


# --------------------------------------------------------------------------- #
# Connection resolution
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AccountAccess:
    connected: bool
    token: str = ""
    external_account_id: str = ""
    caps: PlatformCapabilities | None = None
    note: str = ""
    meta: dict = field(default_factory=dict)


def _resolve_extended(user_id: str, plat: str) -> AccountAccess:
    """Credentials from the extended publishing connections (Facebook / Threads / Bluesky ...)."""
    from app.domains.publishing.extended.connections import credentials
    from app.domains.publishing.extended.oauth import ConnectError

    try:
        creds = credentials(user_id, plat, transport=default_transport())
    except ConnectError as exc:
        return AccountAccess(connected=False, caps=capabilities_for(plat, connected=False),
                             note=f"{exc} Reconnect it under Connections." if exc.reauth else str(exc))
    except Exception as exc:  # noqa: BLE001 - provider down while refreshing; treated as not connected now
        logger.info(f"social inbox: {plat} credentials unavailable for {user_id}: {exc}")
        return AccountAccess(connected=False, caps=capabilities_for(plat, connected=False),
                             note=f"The {plat} connection could not be checked right now.")
    caps = capabilities_for(plat, connected=True, scopes=creds.scopes)
    if plat == "facebook":
        # Comments on Page videos are read and answered as the Page.
        return AccountAccess(connected=True, token=creds.target_token, external_account_id=creds.target_id,
                             caps=caps, meta=dict(creds.meta))
    return AccountAccess(connected=True, token=creds.access_token, external_account_id=creds.external_account_id,
                         caps=caps, meta={**creds.meta, "account_name": creds.meta.get("handle", "")})


def resolve_account(session: Any, user_id: str, platform: str) -> AccountAccess:
    """Fresh token + capabilities for the creator's connection (never raises)."""
    plat = normalize_platform(platform)
    if plat in CHANNEL_INBOX_PLATFORMS:
        from .channel_inbox import resolve_access

        return resolve_access(session, user_id, plat)
    if plat in EXTENDED_PLATFORMS:
        return _resolve_extended(user_id, plat)
    try:
        account = oauth_connect.refresh_if_needed(session, user_id, plat)
    except Exception as exc:  # noqa: BLE001 - expired without refresh token, provider down
        logger.info(f"social inbox: {plat} token refresh failed for {user_id}: {exc}")
        return AccountAccess(
            connected=False,
            caps=capabilities_for(plat, connected=False),
            note=f"The {plat} connection expired. Reconnect it under Connections.",
        )
    if account is None:
        return AccountAccess(connected=False, caps=capabilities_for(plat, connected=False),
                             note=f"No connected {plat} account. Connect it under Connections.")
    tokens = oauth_connect._decrypt_account(account)  # noqa: SLF001 - same pattern as native_service
    caps = capabilities_for(plat, connected=True, scopes=tokens.scopes or "")
    return AccountAccess(
        connected=True, token=tokens.access_token, external_account_id=tokens.external_account_id or "", caps=caps
    )


def connected_platforms(session: Any, user_id: str) -> dict[str, str]:
    """``{platform: granted_scopes}`` for the creator's stored connections (no tokens)."""
    from app.models.db.repositories import SocialAccountRepository

    out: dict[str, str] = {}
    for row in SocialAccountRepository(session).list_for_user(user_id):
        plat = normalize_platform(getattr(row, "provider", ""))
        if plat in _SUPPORTED:
            out[plat] = str(getattr(row, "scopes", "") or "")
    try:
        from app.domains.publishing.extended import repository as ext_repo
        from app.domains.publishing.extended.models import CONN_CONNECTED

        for conn in ext_repo.list_connections(session, user_id):
            if conn.platform in EXTENDED_PLATFORMS and conn.status == CONN_CONNECTED:
                out[conn.platform] = str(conn.scopes or "")
    except Exception as exc:  # noqa: BLE001 - extended tables missing: the core inbox still works
        logger.info(f"social inbox: extended connections unavailable: {exc}")
    from .channel_inbox import connected_kinds

    out.update(connected_kinds(session, user_id))
    return out


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _title_of(params: Any) -> str:
    p = params if isinstance(params, dict) else {}
    subject = str(p.get("video_subject") or "").strip()
    if subject:
        return subject[:300]
    script = str(p.get("video_script") or "").strip()
    return script.splitlines()[0][:120] if script else ""


def discover(
    session: Any, *, user_id: str | None = None, now: datetime | None = None, days: int = _DISCOVERY_DAYS
) -> int:
    """Track every native publish of the last ``days`` days; returns the number of new posts.

    The beat tick scans a short recent window (new publishes surface within
    minutes); an on-demand "Sync now" rescans the creator's full 90 days.
    """
    from app.models.db.models import Job, JobEvent

    moment = now or utcnow()
    since = moment - timedelta(days=max(1, min(days, _DISCOVERY_DAYS)))
    stmt = (
        select(JobEvent, Job.user_id, Job.params)
        .join(Job, Job.id == JobEvent.job_id)
        .where(JobEvent.stage == "publish", JobEvent.status == "native_published", JobEvent.created_at >= since)
        .order_by(JobEvent.id.asc())
    )
    if user_id:
        stmt = stmt.where(Job.user_id == user_id)
    created = 0
    instagram_users: set[str] = set()
    for event, owner, params in session.execute(stmt).all():
        payload = event.payload if isinstance(event.payload, dict) else {}
        platform = normalize_platform(str(payload.get("platform") or ""))
        external_id = str(payload.get("external_id") or "").strip()
        if platform not in _SUPPORTED or not external_id or not owner:
            continue
        _, was_created = repo.ensure_post(
            session,
            user_id=str(owner),
            platform=platform,
            external_id=external_id[:128],
            job_id=str(event.job_id),
            url=str(payload.get("url") or ""),
            title=_title_of(params),
            posted_at=_aware(event.created_at),
            now=moment,
        )
        created += int(was_created)
        if platform == "instagram":
            instagram_users.add(str(owner))
    for owner in instagram_users:
        _ensure_dm_channel(session, owner, moment)
    return created


def _ensure_dm_channel(session: Any, user_id: str, now: datetime) -> None:
    connected = connected_platforms(session, user_id)
    if "instagram" not in connected:
        return
    repo.ensure_post(
        session,
        user_id=user_id,
        platform="instagram",
        external_id=f"{repo.DM_CHANNEL_PREFIX}instagram",
        job_id=None,
        url=instagram_client.DM_INBOX_URL,
        title="Instagram direct messages",
        posted_at=None,
        now=now,
    )


# --------------------------------------------------------------------------- #
# Sync one post
# --------------------------------------------------------------------------- #
@dataclass
class _Pull:
    state: str = STATE_OK
    note: str = ""
    threads: list[FetchedThread] = field(default_factory=list)
    comment_count: int | None = None
    like_count: int | None = None
    view_count: int | None = None
    url: str = ""
    failed: bool = False


def _pull_counts(user_id: str, platform: str, external_id: str, posted_at: datetime | None,
                 token: str, transport: Transport, pull: _Pull) -> None:
    from app.domains.insights.platform_metrics import fetch_post_metrics

    metrics = fetch_post_metrics(
        user_id, platform, external_id,
        published_on=(_aware(posted_at) or utcnow()).date(), transport=transport, token=token,
    )
    if metrics.available:
        pull.comment_count = metrics.comments
        pull.like_count = metrics.likes
        pull.view_count = metrics.views
        if metrics.url and not pull.url:
            pull.url = metrics.url


def _pull_post(user_id: str, snapshot: dict, access: AccountAccess, transport: Transport) -> _Pull:
    """All network work for one post. Never raises."""
    pull = _Pull()
    platform = snapshot["platform"]
    external_id = snapshot["external_id"]
    caps = access.caps
    if not access.connected or caps is None:
        return _Pull(state=STATE_NOT_CONNECTED, note=access.note)
    try:
        if snapshot["is_dm"]:
            if caps.dms.read == NOT_OFFERED:
                return _Pull(state=STATE_NOT_OFFERED, note=caps.dms.note)
            if caps.dms.read == NEEDS_PERMISSION:
                return _Pull(state=STATE_MISSING_PERMISSION, note=caps.dms.note)
            pull.threads = instagram_client.fetch_dm_threads(
                access.token, access.external_account_id, transport=transport
            )
            return pull

        if platform == "youtube":
            _pull_counts(user_id, platform, external_id, snapshot["posted_at"], access.token, transport, pull)
            if caps.comments.read == NEEDS_PERMISSION:
                return _Pull(state=STATE_MISSING_PERMISSION, note=caps.comments.note,
                             comment_count=pull.comment_count, like_count=pull.like_count,
                             view_count=pull.view_count, url=pull.url)
            pull.threads = youtube_client.fetch_comment_threads(
                access.token, external_id, access.external_account_id, transport=transport
            )
        elif platform == "instagram":
            counts = instagram_client.fetch_media_counts(access.token, external_id, transport=transport)
            pull.comment_count = int(counts.get("comments_count") or 0)
            pull.like_count = int(counts.get("like_count") or 0)
            pull.url = str(counts.get("permalink") or "")
            if caps.comments.read == NEEDS_PERMISSION:
                return _Pull(state=STATE_MISSING_PERMISSION, note=caps.comments.note,
                             comment_count=pull.comment_count, like_count=pull.like_count, url=pull.url)
            pull.threads = instagram_client.fetch_comment_threads(
                access.token, external_id, access.external_account_id,
                post_url=pull.url or snapshot["url"], transport=transport,
            )
        elif platform == "tiktok":
            _pull_counts(user_id, platform, external_id, snapshot["posted_at"], access.token, transport, pull)
            pull.state = STATE_NOT_OFFERED
            pull.note = caps.comments.note
        elif platform in EXTENDED_INBOX_PLATFORMS:
            if caps.comments.read == NEEDS_PERMISSION:
                return _Pull(state=STATE_MISSING_PERMISSION, note=caps.comments.note)
            pull.threads = _pull_extended(platform, external_id, access, transport)
        elif platform in EXTENDED_PLATFORMS:
            pull.state = STATE_NOT_OFFERED
            pull.note = caps.comments.note
        return pull
    except InboxPlatformError as exc:
        if exc.permission:
            return _Pull(state=STATE_MISSING_PERMISSION, note=str(exc), comment_count=pull.comment_count,
                         like_count=pull.like_count, view_count=pull.view_count, url=pull.url)
        if exc.not_available:
            return _Pull(state=STATE_NOT_OFFERED, note=str(exc), comment_count=pull.comment_count,
                         like_count=pull.like_count, view_count=pull.view_count, url=pull.url)
        return _Pull(state=STATE_ERROR, note=str(exc), failed=True, comment_count=pull.comment_count,
                     like_count=pull.like_count, view_count=pull.view_count, url=pull.url)
    except Exception as exc:  # noqa: BLE001 - network/parse failure; retried with backoff
        logger.warning(f"social inbox pull failed for {platform}:{external_id}: {exc}")
        return _Pull(state=STATE_ERROR, note="The platform could not be reached; will retry.", failed=True)


def _pull_extended(platform: str, external_id: str, access: AccountAccess, transport: Transport) -> list[FetchedThread]:
    if platform == "facebook":
        return facebook_client.fetch_comment_threads(access.token, external_id, access.external_account_id,
                                                     transport=transport)
    if platform == "threads":
        return threads_client.fetch_comment_threads(access.token, external_id, str(access.meta.get("username") or ""),
                                                    transport=transport)
    session = bluesky_client.session_for(access.external_account_id, access.token,
                                         str(access.meta.get("pds") or "https://bsky.social"), transport=transport)
    return bluesky_client.fetch_comment_threads(session, external_id, transport=transport)


def sync_post(user_id: str, post_id: str, *, transport: Transport | None = None,
              now: datetime | None = None) -> dict:
    """Sync one tracked post end to end; returns a small summary."""
    require_ready()
    moment = now or utcnow()
    with get_session() as session:  # type: ignore[misc]
        post = repo.get_post(session, user_id, post_id)
        if post is None:
            return {"post_id": post_id, "state": "missing"}
        channel_post = post.platform in CHANNEL_INBOX_PLATFORMS
        snapshot = {
            "platform": post.platform,
            "external_id": post.external_id,
            "url": post.url,
            "posted_at": post.posted_at,
            "is_dm": repo.is_dm_channel(post),
        }
        access = None if channel_post else resolve_account(session, user_id, post.platform)

    if channel_post:  # Telegram / Discord / Mastodon: one tracked row per connected channel
        from .channel_inbox import sync_channel_post

        return sync_channel_post(user_id, post_id, transport=transport, now=moment)

    pull = _pull_post(user_id, snapshot, access, transport or default_transport())

    with get_session() as session:  # type: ignore[misc]
        post = repo.get_post(session, user_id, post_id)
        if post is None:
            return {"post_id": post_id, "state": "missing"}
        for fetched in pull.threads:
            repo.upsert_thread(
                session, user_id=user_id, platform=post.platform,
                post_id=post.id, fetched=fetched, now=moment,
            )
        post.inbox_state = pull.state
        post.state_note = pull.note[:1000]
        if pull.comment_count is not None:
            post.platform_comment_count = max(0, pull.comment_count)
        if pull.like_count is not None:
            post.platform_like_count = max(0, pull.like_count)
        if pull.view_count is not None:
            post.platform_view_count = max(0, pull.view_count)
        if pull.url and (not post.url or post.platform == "instagram"):
            post.url = pull.url
        post.poll_failures = (int(post.poll_failures or 0) + 1) if pull.failed else 0
        post.last_polled_at = moment
        post.next_poll_at = _next_poll(post, moment, failed=pull.failed)
        session.flush()
        repo.refresh_post_counts(session, post)
        if post.job_id:
            _feed_winner_loop(session, user_id, post.job_id)
        return {"post_id": post.id, "state": post.inbox_state, "threads": len(pull.threads)}


def _feed_winner_loop(session: Any, user_id: str, job_id: str) -> None:
    """Raise ``JobPerformance.comments`` to the comments we actually observed.

    Only the ``comments`` key is written (the repository applies present keys
    only), and only upward, so creator-logged or platform-pulled numbers are
    never overwritten with a smaller or invented value.
    """
    try:
        from app.models.db.repositories import JobPerformanceRepository

        observed = repo.observed_comments_for_job(session, user_id, job_id)
        if observed <= 0:
            return
        perf_repo = JobPerformanceRepository(session)
        existing = perf_repo.get_for_job(job_id, user_id)
        if existing is not None and int(existing.comments or 0) >= observed:
            return
        perf_repo.upsert(job_id=job_id, user_id=user_id, metrics={"comments": observed})
    except Exception as exc:  # noqa: BLE001 - the inbox must not fail on the loop feed
        logger.warning(f"social inbox: winner-loop feed skipped for job {job_id}: {exc}")


# --------------------------------------------------------------------------- #
# Batch entry points
# --------------------------------------------------------------------------- #
def sync_user(user_id: str, *, limit: int = 12, transport: Transport | None = None) -> dict:
    """On-demand "Sync now" for one creator: discover, then poll their most urgent posts."""
    require_ready()
    moment = utcnow()
    with get_session() as session:  # type: ignore[misc]
        discovered = discover(session, user_id=user_id, now=moment)
        from .channel_inbox import ensure_all

        discovered += ensure_all(session, user_id, moment)
        rows = session.execute(
            select(InboxPost.id)
            .where(InboxPost.user_id == user_id, InboxPost.next_poll_at.is_not(None))
            .order_by(InboxPost.next_poll_at.asc())
            .limit(max(1, limit))
        ).scalars().all()
        post_ids = [str(r) for r in rows]
    tx = transport or default_transport()
    results = [sync_post(user_id, pid, transport=tx, now=moment) for pid in post_ids]
    return {"discovered": discovered, "synced": len(results)}


def tick(now: datetime | None = None, *, transport: Transport | None = None) -> dict[str, int]:
    """One beat pass: discover new posts, then poll the due ones (bounded)."""
    require_ready()
    moment = now or utcnow()
    with get_session() as session:  # type: ignore[misc]
        discovered = discover(session, now=moment, days=_TICK_DISCOVERY_DAYS)
    with get_session() as session:  # type: ignore[misc]
        claimed = repo.due_post_ids(session, moment, limit=_MAX_POSTS_PER_TICK * 2)
        per_user: dict[str, int] = {}
        selected: list[tuple[str, str]] = []
        for post_id, owner in claimed:
            if per_user.get(owner, 0) >= _MAX_POSTS_PER_USER_PER_TICK or len(selected) >= _MAX_POSTS_PER_TICK:
                continue
            per_user[owner] = per_user.get(owner, 0) + 1
            selected.append((post_id, owner))
        if selected:
            ids = [pid for pid, _ in selected]
            for row in session.execute(select(InboxPost).where(InboxPost.id.in_(ids))).scalars().all():
                row.next_poll_at = moment + _LEASE
    tx = transport or default_transport()
    synced = failed = 0
    started = time.monotonic()
    for post_id, owner in selected:
        if time.monotonic() - started > _TICK_BUDGET_S:
            break  # leased rows fall due again after _LEASE
        try:
            sync_post(owner, post_id, transport=tx, now=moment)
            synced += 1
        except Exception as exc:  # noqa: BLE001 - one bad post must not stop the tick
            failed += 1
            logger.error(f"social inbox: sync failed for post {post_id}: {exc}")
    return {"discovered": discovered, "synced": synced, "failed": failed}
