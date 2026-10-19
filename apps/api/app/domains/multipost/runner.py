"""The publish queue runner: claim due posts, enforce limits, publish, track status.

* :func:`run_due` - every minute. Claims each due ``scheduled`` post with a
  guarded ``UPDATE ... WHERE status='scheduled'`` committed on its own (so two
  runners never publish the same post, and a crash after the claim never
  re-posts), then publishes it in a fresh transaction.
* :func:`sweep_processing` - every minute. Polls platforms for posts still
  ingesting (TikTok publish_id, Instagram container, YouTube processing).
* :func:`sweep_stale` - a post left in ``publishing`` by a crashed worker is
  failed with a "check the platform" note instead of being retried blindly.

Limits are re-checked at publish time against what actually went out, so a
delayed render or a retry can never push an account over its cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func, select, update

from . import accounts as acct_service
from . import media as media_mod
from . import pacing, settings
from .clients import AuthError, ClientError, PostSpec, PublishOutcome, RateLimited, Transport
from .clients import instagram as ig
from .clients import tiktok as tt
from .clients import youtube as yt
from .clients.base import RequestsTransport
from .models import (
    ACCOUNT_CONNECTED,
    ACCOUNT_PAUSED,
    COUNTED_POST_STATUSES,
    INSTAGRAM,
    POST_FAILED,
    POST_HELD,
    POST_PROCESSING,
    POST_PUBLISHED,
    POST_PUBLISHING,
    POST_SCHEDULED,
    TIKTOK,
    YOUTUBE,
    MultipostAccount,
    MultipostCampaign,
    MultipostPost,
)
from .oauth import ConnectError

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - persistence layer always present in the API image
    get_session = None  # type: ignore[assignment]

MAX_ATTEMPTS = 4
RENDER_WAIT = timedelta(minutes=5)
RENDER_GIVE_UP = timedelta(days=2)
PROCESSING_GIVE_UP = timedelta(hours=24)
STALE_PUBLISHING = timedelta(minutes=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Deps:
    transport: Transport
    media: media_mod.MediaSource


def _deps(transport: Transport | None, media: media_mod.MediaSource | None) -> Deps:
    return Deps(transport or RequestsTransport(timeout_s=300), media or media_mod.JobMedia())


# --------------------------------------------------------------------------- #
# Due runner
# --------------------------------------------------------------------------- #
def run_due(*, now: datetime | None = None, transport: Transport | None = None,
            media: media_mod.MediaSource | None = None, limit: int = 25) -> dict[str, int]:
    now = now or _now()
    deps = _deps(transport, media)
    due_at = func.coalesce(MultipostPost.next_attempt_at, MultipostPost.scheduled_at)
    with get_session() as session:
        ids = [r[0] for r in session.execute(
            select(MultipostPost.id).where(MultipostPost.status == POST_SCHEDULED, due_at <= now)
            .order_by(due_at).limit(limit)
        ).all()]
    tally: dict[str, int] = {}
    for post_id in ids:
        if not _claim(post_id, now):
            continue
        try:
            outcome = _process(post_id, now, deps)
        except Exception as exc:  # noqa: BLE001 - one bad post never stops the queue
            logger.exception(f"multipost {post_id} crashed: {exc}")
            outcome = _finish_error(post_id, ClientError("unknown", f"unexpected error: {exc}", retryable=True),
                                    now)
        tally[outcome] = tally.get(outcome, 0) + 1
    return tally


def _claim(post_id: str, now: datetime) -> bool:
    with get_session() as session:
        result = session.execute(
            update(MultipostPost)
            .where(MultipostPost.id == post_id, MultipostPost.status == POST_SCHEDULED)
            .values(status=POST_PUBLISHING, next_attempt_at=now, updated_at=now)
        )
        return bool(result.rowcount)


def _requeue(post: MultipostPost, at: datetime, provider_status: str) -> str:
    post.status = POST_SCHEDULED
    post.next_attempt_at = at
    post.provider_status = provider_status[:64]
    return "deferred"


def _fail(post: MultipostPost, message: str) -> str:
    post.status = POST_FAILED
    post.error = message[:2000]
    return "failed"


def _youtube_project_used(session: Any, now: datetime, exclude: str) -> int:
    rows = session.execute(select(MultipostPost.id, MultipostPost.status, MultipostPost.next_attempt_at,
                                  MultipostPost.published_at)
                           .where(MultipostPost.provider == YOUTUBE,
                                  MultipostPost.status.in_(list(COUNTED_POST_STATUSES)))).all()
    used = 0
    for post_id, status, attempt_at, published_at in rows:
        when = acct_service.aware(attempt_at or published_at)
        if post_id != exclude and when is not None and now - pacing.DAY < when <= now:
            used += 1
    return used


def _gate_checks(session: Any, post: MultipostPost, account: MultipostAccount, now: datetime,
                 deps: Deps) -> str | None:
    """Everything that can stop or delay a post before any platform call."""
    if account.status == ACCOUNT_PAUSED:
        return _requeue(post, now + timedelta(hours=1), "account_paused")
    if account.status != ACCOUNT_CONNECTED:
        return _fail(post, f"reconnect {account.display_name or account.handle or account.provider} to post")
    if not acct_service.can_post(session, post.user_id, account):
        return _fail(post, "you no longer have permission to post to this account")
    state = deps.media.state(post.user_id, post.job_id)
    if state == media_mod.RENDERING:
        waited = now - (acct_service.aware(post.scheduled_at) or now)
        if waited > RENDER_GIVE_UP:
            return _fail(post, "the video never finished rendering")
        return _requeue(post, now + RENDER_WAIT, "waiting_for_video")
    if state != media_mod.READY:
        return _fail(post, {"failed": "the video failed to render", "missing": "the video no longer exists",
                            "blocked": "the video was taken down after a report"}.get(state, "video unavailable"))
    times = acct_service.counted_times(session, account.id, around=now, exclude_post=post.id)
    verdict = pacing.check(now, times, acct_service.limits_for(account))
    if not verdict.allowed:
        return _requeue(post, verdict.next_at, f"waiting:{verdict.reason}")
    if post.provider == YOUTUBE and _youtube_project_used(session, now, post.id) >= \
            settings.youtube_project_daily_uploads():
        return _requeue(post, now + timedelta(hours=1), "waiting:youtube_project_quota")
    ok, reason = media_mod.content_gate(post.provider, post.title, post.caption)
    if not ok:
        post.status = POST_HELD
        post.error = reason[:2000]
        return "held"
    return None


@dataclass(frozen=True)
class Snapshot:
    """Plain values a platform call needs, so no DB session is held during uploads."""

    post_id: str
    user_id: str
    job_id: str
    provider: str
    title: str
    caption: str
    publish_ref: str
    external_account_id: str
    handle: str
    hashtags: tuple[str, ...] = ()
    visibility: str = "private"
    ai_generated: bool = True
    allow_comments: bool = False
    allow_duet: bool = False
    allow_stitch: bool = False
    brand_content: bool = False
    brand_organic: bool = False
    tiktok_mode: str = "direct"


def _snapshot(post: MultipostPost, account: MultipostAccount, campaign: MultipostCampaign | None) -> Snapshot:
    extra = {}
    if campaign is not None:
        extra = dict(
            hashtags=tuple(campaign.hashtags or []), visibility=campaign.visibility,
            ai_generated=bool(campaign.ai_generated), allow_comments=bool(campaign.allow_comments),
            allow_duet=bool(campaign.allow_duet), allow_stitch=bool(campaign.allow_stitch),
            brand_content=bool(campaign.brand_content), brand_organic=bool(campaign.brand_organic),
            tiktok_mode=campaign.tiktok_mode,
        )
    return Snapshot(post_id=post.id, user_id=post.user_id, job_id=post.job_id, provider=post.provider,
                    title=post.title, caption=post.caption, publish_ref=post.publish_ref,
                    external_account_id=account.external_account_id, handle=account.handle, **extra)


def _spec(snap: Snapshot, *, url: str, path: str) -> PostSpec:
    return PostSpec(
        video_url=url, video_path=path, title=snap.title, caption=snap.caption, hashtags=snap.hashtags,
        visibility=snap.visibility, ai_generated=snap.ai_generated, allow_comments=snap.allow_comments,
        allow_duet=snap.allow_duet, allow_stitch=snap.allow_stitch, brand_content=snap.brand_content,
        brand_organic=snap.brand_organic, tiktok_mode=snap.tiktok_mode,
    )


AMBIGUOUS = ("the platform stopped answering while the post was being sent; check the account "
             "before retrying so it is not posted twice")


def _before_send(provider: str, step):
    """Run a step that happens before anything is sent to the platform: any failure is safe to retry."""
    try:
        return step()
    except ClientError:
        raise
    except Exception as exc:  # noqa: BLE001 - storage/network hiccup before the post started
        raise ClientError(provider, f"could not prepare the post: {exc}", retryable=True) from exc


def _send(provider: str, step) -> PublishOutcome:
    """Run the platform publish call. A transport failure here (timeout, reset) is ambiguous: the
    platform may have accepted the post, so it is failed for a human to check, never retried."""
    try:
        return step()
    except ClientError:
        raise
    except Exception as exc:  # noqa: BLE001 - requests timeout / connection reset mid-call
        logger.warning(f"multipost {provider} publish call broke mid-flight: {exc}")
        raise ClientError(provider, AMBIGUOUS, retryable=False, code="ambiguous") from exc


def _dispatch(snap: Snapshot, token: str, deps: Deps) -> tuple[PublishOutcome, str]:
    """Platform call with no DB session open. Returns the outcome and the TikTok @username if learned."""
    path = ""
    username = ""
    media = deps.media
    try:
        if snap.provider == TIKTOK:
            info = _before_send(TIKTOK, lambda: tt.creator_info(token, transport=deps.transport))
            username = str(info.get("username") or "")
            source = settings.tiktok_source()
            url = _before_send(TIKTOK, lambda: media.video_url(snap.user_id, snap.job_id)) if source == "url" else ""
            path = _before_send(TIKTOK, lambda: media.download(snap.user_id, snap.job_id)) if source == "file" else ""
            spec = _spec(snap, url=url, path=path)
            return _send(TIKTOK, lambda: tt.publish(token, spec, info=info, audited=settings.tiktok_audited(),
                                                    source=source, transport=deps.transport)), username
        if snap.provider == INSTAGRAM:
            url = _before_send(INSTAGRAM, lambda: media.video_url(snap.user_id, snap.job_id))
            spec = _spec(snap, url=url, path="")
            return _send(INSTAGRAM, lambda: ig.publish(token, snap.external_account_id, spec,
                                                       disclosure=settings.instagram_caption_disclosure(),
                                                       transport=deps.transport)), ""
        if snap.provider == YOUTUBE:
            path = _before_send(YOUTUBE, lambda: media.download(snap.user_id, snap.job_id))
            spec = _spec(snap, url="", path=path)
            return _send(YOUTUBE, lambda: yt.publish(token, spec, verified=settings.youtube_verified(),
                                                     transport=deps.transport)), ""
        raise ClientError(snap.provider, f"unsupported platform {snap.provider!r}")
    finally:
        media_mod.cleanup(path)


def _apply(post: MultipostPost, outcome: PublishOutcome, now: datetime, handle: str = "") -> str:
    post.publish_ref = outcome.ref or post.publish_ref
    post.external_id = outcome.external_id or post.external_id
    post.url = outcome.url or post.url
    if post.provider == TIKTOK and outcome.external_id and outcome.external_id != outcome.ref and handle:
        post.url = tt.post_url(outcome.external_id, handle)
    post.provider_status = (outcome.provider_status or "")[:64]
    post.error = ""
    if outcome.status == POST_PUBLISHED:
        post.status = POST_PUBLISHED
        post.published_at = post.published_at or now
        return "published"
    post.status = POST_PROCESSING
    return "processing"


def _prepare(post_id: str, now: datetime, deps: Deps) -> tuple[str | None, Snapshot | None, str]:
    """Phase 1 (short transaction): checks and a fresh token. ``(stopped, snapshot, token)``."""
    with get_session() as session:
        post = session.get(MultipostPost, post_id)
        account = session.get(MultipostAccount, post.account_id)
        campaign = session.get(MultipostCampaign, post.campaign_id)
        if account is None or campaign is None:
            return _fail(post, "the account or batch was removed"), None, ""
        stopped = _gate_checks(session, post, account, now, deps)
        if stopped:
            return stopped, None, ""
        try:
            token = acct_service.valid_token(session, account, transport=deps.transport, now=now)
        except ConnectError as exc:
            return _fail(post, f"reconnect {account.display_name or account.provider}: {exc}"), None, ""
        return None, _snapshot(post, account, campaign), token


def _settle(post_id: str, now: datetime, call) -> str:
    """Phase 3 (short transaction): record what the platform said."""
    outcome: PublishOutcome | None = None
    error: Exception | None = None
    username = ""
    try:
        outcome, username = call()
    except ClientError as exc:
        error = exc
    with get_session() as session:
        post = session.get(MultipostPost, post_id)
        account = session.get(MultipostAccount, post.account_id)
        if username and account is not None and username != account.handle:
            account.handle = username[:200]
        if isinstance(error, AuthError):
            if account is not None:
                acct_service.mark_reauth(account, str(error))
            return _fail(post, str(error))
        if isinstance(error, RateLimited):
            wait = timedelta(seconds=max(60, error.retry_after_s))
            return _requeue(post, now + wait, f"platform_limit:{error.code}"[:64])
        if isinstance(error, ClientError):
            return _error_result(post, error, now)
        result = _apply(post, outcome, now, account.handle if account else "")
        logger.info(f"multipost {post.id} {post.provider} -> {post.status} ref={post.publish_ref}")
        return result


def _process(post_id: str, now: datetime, deps: Deps) -> str:
    stopped, snap, token = _prepare(post_id, now, deps)
    if stopped:
        return stopped
    # Phase 2: the upload runs with no DB connection held.
    return _settle(post_id, now, lambda: _dispatch(snap, token, deps))


def _error_result(post: MultipostPost, exc: ClientError, now: datetime) -> str:
    post.attempts = int(post.attempts or 0) + 1
    if exc.retryable and post.attempts < MAX_ATTEMPTS:
        post.error = str(exc)[:2000]
        return _requeue(post, now + pacing.backoff(post.attempts), "retrying")
    return _fail(post, str(exc))


def _finish_error(post_id: str, exc: ClientError, now: datetime) -> str:
    with get_session() as session:
        post = session.get(MultipostPost, post_id)
        if post is None or post.status != POST_PUBLISHING:
            return "skipped"
        return _error_result(post, exc, now)


# --------------------------------------------------------------------------- #
# Status sweep
# --------------------------------------------------------------------------- #
def sweep_processing(*, now: datetime | None = None, transport: Transport | None = None,
                     limit: int = 50) -> dict[str, int]:
    now = now or _now()
    deps = _deps(transport, None)
    with get_session() as session:
        ids = [r[0] for r in session.execute(
            select(MultipostPost.id).where(MultipostPost.status == POST_PROCESSING)
            .order_by(MultipostPost.updated_at).limit(limit)
        ).all()]
    tally: dict[str, int] = {}
    for post_id in ids:
        try:
            result = _poll_one(post_id, now, deps)
        except Exception as exc:  # noqa: BLE001 - a network hiccup on one post never stops the sweep
            logger.warning(f"multipost status check for {post_id} failed: {exc}")
            result = "waiting"
        tally[result] = tally.get(result, 0) + 1
    return tally


def _poll(snap: Snapshot, token: str, deps: Deps) -> tuple[PublishOutcome, str]:
    if snap.provider == TIKTOK:
        return tt.fetch_status(token, snap.publish_ref, transport=deps.transport), ""
    if snap.provider == INSTAGRAM:
        return ig.advance(token, snap.external_account_id, snap.publish_ref, transport=deps.transport), ""
    return yt.fetch_status(token, snap.publish_ref, transport=deps.transport), ""


def _poll_one(post_id: str, now: datetime, deps: Deps) -> str:
    with get_session() as session:
        post = session.get(MultipostPost, post_id)
        if post is None or post.status != POST_PROCESSING:
            return "skipped"
        account = session.get(MultipostAccount, post.account_id)
        started = acct_service.aware(post.next_attempt_at or post.updated_at) or now
        if account is None:
            return _fail(post, "the account was removed while the platform was processing the video")
        try:
            token = acct_service.valid_token(session, account, transport=deps.transport, now=now)
        except ConnectError as exc:
            return _fail(post, f"reconnect {account.display_name or account.provider}: {exc}")
        snap = _snapshot(post, account, None)
    outcome: PublishOutcome | None = None
    try:
        outcome, _ = _poll(snap, token, deps)
    except AuthError as exc:
        with get_session() as session:
            post = session.get(MultipostPost, post_id)
            account = session.get(MultipostAccount, post.account_id)
            if account is not None:
                acct_service.mark_reauth(account, str(exc))
            return _fail(post, str(exc))
    except RateLimited:
        return "waiting"
    except ClientError as exc:
        if exc.retryable:
            return "waiting"
        with get_session() as session:
            return _fail(session.get(MultipostPost, post_id), str(exc))
    with get_session() as session:
        post = session.get(MultipostPost, post_id)
        if post is None or post.status != POST_PROCESSING:
            return "skipped"
        if outcome.status != POST_PUBLISHED and now - started > PROCESSING_GIVE_UP:
            return _fail(post, "the platform did not finish processing the video within a day")
        return _apply(post, outcome, now, snap.handle)


def sweep_stale(*, now: datetime | None = None) -> int:
    """Fail posts stuck in ``publishing`` (worker died mid-call). Never re-posts blindly."""
    now = now or _now()
    with get_session() as session:
        rows = session.execute(select(MultipostPost).where(
            MultipostPost.status == POST_PUBLISHING,
            MultipostPost.updated_at < now - STALE_PUBLISHING,
        )).scalars().all()
        for post in rows:
            _fail(post, "publishing was interrupted; check the account before retrying so it is not posted twice")
        return len(rows)


def refresh_tokens(*, transport: Transport | None = None) -> int:
    with get_session() as session:
        return acct_service.refresh_expiring(session, transport=transport or RequestsTransport(timeout_s=30))
