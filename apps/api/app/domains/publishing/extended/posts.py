"""Schedule, run and track posts of a rendered reel to the extended platforms.

Lifecycle of a :class:`~.models.PlatformPost`:

``scheduled`` -> (due-runner claims it) -> ``publishing`` ->
``published`` | ``processing`` (platform still ingesting; re-polled) |
``held`` (content gate) | ``failed`` (with the platform's own reason) ;
``scheduled`` -> ``canceled`` by the creator before it starts.

"Post now" is just a post scheduled for now: it is handed to a worker
immediately when Celery is reachable and otherwise picked up by the
one-minute due-runner. Retryable platform errors back off and retry up to
:data:`MAX_ATTEMPTS` times; every failure keeps the platform's reason.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select

from . import repository as repo
from .catalog import (
    AVAILABLE,
    BYTE_UPLOAD,
    URL_INGEST,
    X,
    is_channel,
    server_availability,
    spec_for,
    x_monthly_post_cap,
)
from .connections import ConnectError, connection_state, credentials
from . import images as image_media
from .connectors import PublishContext, PublishError, Step, get, get_for_images
from .connectors.base import Transport, new_default_transport
from .formats import FittedPost, check_video, fit
from .models import (
    CONN_CONNECTED,
    POST_CANCELED,
    POST_FAILED,
    POST_HELD,
    POST_PROCESSING,
    POST_PUBLISHED,
    POST_PUBLISHING,
    POST_SCHEDULED,
    PlatformPost,
)

try:
    from app.models.db.base import get_session

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    get_session = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

MAX_ATTEMPTS = 3
MAX_POSTS_PER_REQUEST = 6
MAX_SCHEDULE_AHEAD = timedelta(days=365)
PROCESSING_TIMEOUT = timedelta(hours=3)
LEASE = timedelta(minutes=10)
TICK_LIMIT = 20
TICK_BUDGET_S = 45.0


class PostError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, details: list | None = None) -> None:
        self.status_code = status_code
        self.details = details or []
        super().__init__(message)


@dataclass(frozen=True)
class PostDraft:
    platform: str
    caption: str = ""
    title: str = ""
    hashtags: tuple[str, ...] = field(default_factory=tuple)


def _require_ready() -> None:
    if get_session is None:
        raise PostError(f"publishing persistence unavailable: {_IMPORT_ERROR}", status_code=503)


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
def post_record(row: PlatformPost) -> dict:
    spec = spec_for(row.platform)
    iso = lambda v: repo.aware(v).isoformat() if v else None  # noqa: E731
    return {
        "id": row.id,
        "job_id": row.job_id,
        "platform": row.platform,
        "platform_label": spec.label if spec else row.platform,
        "target_id": row.target_id or "",
        "status": row.status,
        "scheduled_at": iso(row.scheduled_at),
        "published_at": iso(row.published_at),
        "attempts": int(row.attempts or 0),
        "title": row.title or "",
        "text": row.text or "",
        "hashtags": list(row.hashtags or []),
        "external_id": row.external_id or "",
        "url": row.url or "",
        "error": row.error or "",
        "note": str((row.progress or {}).get("note") or ""),
        "can_cancel": row.status == POST_SCHEDULED and int(row.attempts or 0) == 0,
        "can_retry": row.status in (POST_FAILED, POST_HELD),
        "media_kind": "image" if image_media.is_image_post(row.progress) else ("video" if row.job_id else "text"),
        "image_count": len(image_media.image_keys(row.progress)),
        "created_at": iso(row.created_at),
    }


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def preview(drafts: list[PostDraft]) -> list[FittedPost]:
    return [fit(d.platform, caption=d.caption, title=d.title, hashtags=d.hashtags) for d in drafts]


def create_posts(user_id: str, job_id: str, drafts: list[PostDraft], *,
                 scheduled_at: datetime | None = None, now: datetime | None = None) -> list[dict]:
    """Validate everything first, then queue one post per platform (all or nothing)."""
    _require_ready()
    moment = now or repo.utcnow()
    if not drafts:
        raise PostError("choose at least one platform")
    if len(drafts) > MAX_POSTS_PER_REQUEST:
        raise PostError(f"at most {MAX_POSTS_PER_REQUEST} platforms per post")
    platforms = [str(d.platform or "").strip().lower() for d in drafts]
    if len(set(platforms)) != len(platforms):
        raise PostError("each platform can appear once")
    when = repo.aware(scheduled_at) or moment
    if when < moment - timedelta(minutes=1):
        raise PostError("the scheduled time is in the past")
    if when > moment + MAX_SCHEDULE_AHEAD:
        raise PostError("schedule at most a year ahead")

    from app.domains.publishing.native_service import NativePublishError, _resolve_final_key

    try:
        _resolve_final_key(user_id, job_id)  # owner-scoped; must be a complete render
    except NativePublishError as exc:
        raise PostError(str(exc), status_code=exc.status_code) from exc

    problems: list[dict] = []
    fitted: list[tuple[PostDraft, FittedPost, str]] = []
    with get_session() as session:  # type: ignore[misc]
        for draft, plat in zip(drafts, platforms):
            spec = spec_for(plat)
            if spec is None:
                problems.append({"platform": plat, "message": "unsupported platform"})
                continue
            server_state, note = server_availability(plat)
            if server_state != AVAILABLE:
                problems.append({"platform": plat, "message": note})
                continue
            row = repo.get_connection(session, user_id, plat)
            state = connection_state(plat, row)
            if state != CONN_CONNECTED:
                problems.append({"platform": plat, "message": _state_message(spec.label, state)})
                continue
            if plat == X and x_monthly_post_cap():
                used = repo.published_count_since(session, X, _month_start(moment))
                if used >= x_monthly_post_cap():
                    problems.append({"platform": plat, "message": "This server's monthly X posting budget is "
                                                                  "used up. Try again next month."})
                    continue
            result = fit(plat, caption=draft.caption, title=draft.title, hashtags=draft.hashtags)
            if not result.ok:
                problems.append({"platform": plat, "message": "; ".join(i.message for i in result.issues)})
                continue
            fitted.append((draft, result, row.target_id if row else ""))
    if problems:
        raise PostError("some platforms can't take this post yet", status_code=409, details=problems)

    records: list[dict] = []
    with get_session() as session:  # type: ignore[misc]
        for _draft, result, target_id in fitted:
            row = repo.add_post(
                session, user_id=user_id, job_id=job_id, platform=result.platform, status=POST_SCHEDULED,
                scheduled_at=when, next_attempt_at=when, title=result.title[:300], text=result.text,
                hashtags=list(result.hashtags), target_id=target_id or "",
            )
            records.append(post_record(row))
    if when <= moment + timedelta(seconds=5):
        for record in records:
            _enqueue(record["id"])
    return records


def _state_message(label: str, state: str) -> str:
    return {
        "not_connected": f"Connect {label} first.",
        "needs_target": f"Choose where to post on {label}.",
        "needs_reauth": f"Reconnect {label}; the connection expired.",
    }.get(state, f"{label} is not ready.")


def _enqueue(post_id: str) -> None:
    try:
        from app.workers.tasks_engagement import run_platform_post_task

        run_platform_post_task.delay(post_id)
    except Exception as exc:  # noqa: BLE001 - the due-runner picks it up within a minute
        logger.info(f"extended publish: could not enqueue {post_id} now ({exc}); due-runner will run it")


# --------------------------------------------------------------------------- #
# Cancel / retry / list
# --------------------------------------------------------------------------- #
def cancel(user_id: str, post_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_post(session, user_id, post_id)
        if row is None:
            raise PostError("post not found", status_code=404)
        if row.status != POST_SCHEDULED or int(row.attempts or 0) > 0:
            raise PostError("only posts that have not started can be canceled", status_code=409)
        row.status = POST_CANCELED
        row.next_attempt_at = None
        session.flush()
        return post_record(row)


def retry(user_id: str, post_id: str, *, now: datetime | None = None) -> dict:
    _require_ready()
    moment = now or repo.utcnow()
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_post(session, user_id, post_id)
        if row is None:
            raise PostError("post not found", status_code=404)
        if row.status not in (POST_FAILED, POST_HELD):
            raise PostError("only failed or held posts can be retried", status_code=409)
        row.status = POST_SCHEDULED
        row.attempts = 0
        row.error = ""
        row.progress = image_media.keep_media(row.progress)  # an image post keeps its pages
        row.scheduled_at = moment
        row.next_attempt_at = moment
        session.flush()
        record = post_record(row)
    _enqueue(record["id"])
    return record


def list_for_user(user_id: str, *, statuses: tuple[str, ...] = (), job_id: str = "",
                  limit: int = 50, offset: int = 0) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        rows, total = repo.list_posts(session, user_id, statuses=statuses, job_id=job_id, limit=limit, offset=offset)
        return {"posts": [post_record(r) for r in rows], "total": total, "limit": limit, "offset": offset}


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Snapshot:
    id: str
    user_id: str
    job_id: str
    platform: str
    status: str
    attempts: int
    title: str
    text: str
    hashtags: tuple[str, ...]
    progress: dict
    target_id: str = ""


def _claim(post_id: str, moment: datetime) -> _Snapshot | None:
    with get_session() as session:  # type: ignore[misc]
        # Row lock: a "post now" worker and the due-runner may race for the same row.
        row = session.execute(
            select(PlatformPost).where(PlatformPost.id == post_id).with_for_update()
        ).scalar_one_or_none()
        if row is None or row.status not in (POST_SCHEDULED, POST_PROCESSING):
            return None
        starting = row.status == POST_SCHEDULED
        snap = _Snapshot(
            id=row.id, user_id=row.user_id, job_id=row.job_id, platform=row.platform,
            status=row.status, attempts=int(row.attempts or 0) + (1 if starting else 0),
            title=row.title or "", text=row.text or "", hashtags=tuple(row.hashtags or []),
            progress=dict(row.progress or {}), target_id=row.target_id or "",
        )
        if starting:
            row.status = POST_PUBLISHING
            row.attempts = snap.attempts
            row.progress = {**snap.progress, "started_at": moment.isoformat()}
        row.next_attempt_at = moment + LEASE
        session.flush()
        return snap


def _finish(post_id: str, **values: Any) -> None:
    with get_session() as session:  # type: ignore[misc]
        row = session.get(PlatformPost, post_id)
        if row is None:
            return
        for key, value in values.items():
            setattr(row, key, value)


def run_post(post_id: str, *, transport: Transport | None = None, now: datetime | None = None) -> dict:
    """Advance one post by one step. Never raises; returns ``{"id","status"}``."""
    _require_ready()
    moment = now or repo.utcnow()
    snap = _claim(post_id, moment)
    if snap is None:
        return {"id": post_id, "status": "skipped"}
    tx = transport or new_default_transport()
    video_path = ""
    prepared: image_media.PreparedImages | None = None
    image_post = image_media.is_image_post(snap.progress)
    try:
        creds = _credentials_for(snap, tx)
        connector = get_for_images(snap.platform) if image_post else get(snap.platform)
        if connector is None:
            raise PublishError(snap.platform, "no connector for this platform")
        ctx = PublishContext(
            platform=snap.platform, access_token=creds.access_token, text=snap.text, title=snap.title,
            hashtags=snap.hashtags, external_account_id=creds.external_account_id,
            target_id=creds.target_id, target_token=creds.target_token, meta=creds.meta, progress=snap.progress,
        )
        if snap.status == POST_SCHEDULED:
            # A human approved this held post (approvals feed): skip the gate once.
            held = "" if snap.progress.get("gate_override") else _content_gate(snap)
            if held:
                _finish(post_id, status=POST_HELD, error=held, next_attempt_at=None)
                return {"id": post_id, "status": POST_HELD}
            if image_post:
                ctx, prepared = _with_images(ctx, snap)
            else:
                ctx, video_path = _with_media(ctx, snap)
            step = connector.publish(ctx, transport=tx)
        else:
            step = connector.resume(ctx, transport=tx)
        return _apply_step(snap, step, moment)
    except ConnectError as exc:
        _finish(post_id, status=POST_FAILED, error=str(exc)[:1000], next_attempt_at=None)
        _audit(snap, "failed", str(exc))
        return {"id": post_id, "status": POST_FAILED}
    except PublishError as exc:
        return _apply_failure(snap, exc, moment)
    except Exception as exc:  # noqa: BLE001 - network/storage failure: retry with backoff
        logger.warning(f"extended publish {post_id} ({snap.platform}) failed: {exc}")
        return _apply_failure(snap, PublishError(snap.platform, "the platform could not be reached", retryable=True),
                              moment)
    finally:
        if prepared is not None:
            prepared.remove()
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except OSError:  # pragma: no cover
                pass


def _credentials_for(snap: _Snapshot, tx: Transport):
    """OAuth connection credentials, or the chosen Telegram/Discord/Mastodon channel's."""
    if snap.platform == image_media.INSTAGRAM:
        return _instagram_credentials(snap.user_id)
    if is_channel(snap.platform):
        from dataclasses import replace

        from .channels import post_credentials

        creds = post_credentials(snap.user_id, snap.platform, snap.target_id)
        return replace(creds, meta={**creds.meta, "post_id": snap.id})
    return credentials(snap.user_id, snap.platform, transport=tx)


def _instagram_credentials(user_id: str):
    """Instagram image posts use the creator's native Instagram connection."""
    from .connections import Credentials

    from app.domains.publishing.native_service import NativePublishError, _valid_token

    try:
        token, account_id = _valid_token(user_id, image_media.INSTAGRAM, None)
    except NativePublishError as exc:
        raise ConnectError(str(exc), status_code=exc.status_code) from exc
    return Credentials(platform=image_media.INSTAGRAM, access_token=token, external_account_id=account_id)


def _with_images(ctx: PublishContext, snap: _Snapshot) -> tuple[PublishContext, image_media.PreparedImages]:
    """Fresh public URLs or local files for an image post's pages."""
    from dataclasses import replace

    prepared = image_media.prepare(snap.platform, image_media.image_keys(snap.progress))
    return replace(ctx, image_urls=prepared.urls, image_paths=prepared.paths), prepared


def _content_gate(snap: _Snapshot) -> str:
    """Run the shared pre-publish gate; returns a hold reason or ``""``."""
    from app.domains.publishing.connectors import PublishRequest
    from app.domains.publishing.native_service import _persist_gate_result, _reasons_summary, _run_content_gate

    gate = _run_content_gate(snap.platform, PublishRequest(
        platform=snap.platform, access_token="", title=snap.title, caption=snap.text,
    ))
    _persist_gate_result(snap.job_id, gate)
    if gate.can_publish:
        return ""
    return f"Held for review before posting ({gate.decision}): {_reasons_summary(gate)}"[:1000]


def _with_media(ctx: PublishContext, snap: _Snapshot) -> tuple[PublishContext, str]:
    from dataclasses import replace

    from app.domains.publishing.native_service import _download_temp, _resolve_final_key
    from app.platform.storage.r2 import get_r2_client

    if not snap.job_id:  # text-only channel post
        return ctx, ""
    final_key, _, _ = _resolve_final_key(snap.user_id, snap.job_id)
    video_url = get_r2_client().presign_get(final_key) if snap.platform in URL_INGEST else ""
    video_path = _download_temp(final_key, snap.job_id) if snap.platform in BYTE_UPLOAD else ""
    if video_path:
        issues = [i for i in check_video(snap.platform, size_bytes=os.path.getsize(video_path), duration_s=None)
                  if i.level == "error"]
        if issues:
            os.remove(video_path)
            raise PublishError(snap.platform, issues[0].message)
    return replace(ctx, video_url=video_url, video_path=video_path), video_path


def _poll_delay(progress: dict, moment: datetime) -> timedelta:
    started = progress.get("processing_since")
    try:
        age = moment - datetime.fromisoformat(started) if started else timedelta(0)
    except ValueError:
        age = timedelta(0)
    if age < timedelta(minutes=5):
        return timedelta(seconds=30)
    if age < timedelta(minutes=30):
        return timedelta(minutes=2)
    return timedelta(minutes=10)


def _apply_step(snap: _Snapshot, step: Step, moment: datetime) -> dict:
    progress = {**snap.progress, **step.progress, "note": step.note}
    if step.done:
        _finish(snap.id, status=POST_PUBLISHED, external_id=step.external_id[:300], url=step.url or "",
                error="", published_at=moment, progress=progress, next_attempt_at=None)
        _audit(snap, "published", f"published to {snap.platform}", external_id=step.external_id, url=step.url)
        return {"id": snap.id, "status": POST_PUBLISHED}
    since = progress.get("processing_since") or moment.isoformat()
    progress["processing_since"] = since
    try:
        waited = moment - datetime.fromisoformat(since)
    except ValueError:
        waited = timedelta(0)
    if waited > PROCESSING_TIMEOUT:
        message = f"{snap.platform} did not finish processing the video within 3 hours"
        _finish(snap.id, status=POST_FAILED, error=message, progress=progress, next_attempt_at=None)
        _audit(snap, "failed", message)
        return {"id": snap.id, "status": POST_FAILED}
    _finish(snap.id, status=POST_PROCESSING, external_id=step.external_id[:300], url=step.url or "",
            progress=progress, next_attempt_at=moment + _poll_delay(progress, moment))
    return {"id": snap.id, "status": POST_PROCESSING}


def _apply_failure(snap: _Snapshot, exc: PublishError, moment: datetime) -> dict:
    message = str(exc).split("] ", 1)[-1][:1000]
    if exc.retryable and snap.attempts < MAX_ATTEMPTS:
        backoff = timedelta(minutes=2 ** snap.attempts)
        status = POST_PROCESSING if snap.status == POST_PROCESSING else POST_SCHEDULED
        _finish(snap.id, status=status, error=message, next_attempt_at=moment + backoff)
        return {"id": snap.id, "status": status}
    _finish(snap.id, status=POST_FAILED, error=message, next_attempt_at=None)
    _audit(snap, "failed", message)
    return {"id": snap.id, "status": POST_FAILED}


def _audit(snap: _Snapshot, status: str, message: str, *, external_id: str = "", url: str = "") -> None:
    """Append a ``JobEvent`` (``native_published`` feeds the social inbox discovery)."""
    try:
        from app.telemetry import events as telemetry_events

        telemetry_events.record_event(
            snap.job_id, "publish", f"native_{status}", message=message[:500],
            payload={"platform": snap.platform, "external_id": external_id, "url": url, "post_id": snap.id},
        )
    except Exception:  # pragma: no cover - telemetry is best effort
        pass


def tick(now: datetime | None = None, *, transport: Transport | None = None) -> dict[str, int]:
    """One due-runner pass: claim due posts and advance each by one step."""
    import time

    _require_ready()
    moment = now or repo.utcnow()
    with get_session() as session:  # type: ignore[misc]
        claimed = repo.claim_due(session, moment, lease=timedelta(seconds=5), limit=TICK_LIMIT)
    started = time.monotonic()
    counts = {"claimed": len(claimed), "published": 0, "processing": 0, "failed": 0}
    tx = transport or new_default_transport()
    for post_id, _owner in claimed:
        if time.monotonic() - started > TICK_BUDGET_S:
            break  # the short lease expires; the next tick continues
        result = run_post(post_id, transport=tx, now=moment)
        key = result.get("status")
        if key in counts:
            counts[key] += 1
    return counts
