"""Reply routing, sending and thread status changes.

A thread's **reply mode** is decided in one place (:func:`reply_mode`):

* ``api``    - Menivor posts the reply through the platform API.
* ``manual`` - the platform (or this connection, or the launch phase) does not
               permit it; the UI copies the text and opens the post in the app,
               then the creator marks the thread replied.

Sending is gated by the same launch flag as direct publishing, the connection's
granted scopes and, for Instagram DMs, the 24-hour messaging window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from . import bluesky_client, facebook_client, instagram_client, threads_client, youtube_client
from . import repository as repo
from .capabilities import CHANNEL_INBOX_PLATFORMS, YES, PlatformCapabilities
from .models import (
    KIND_DM,
    MAX_THREAD_MESSAGES,
    STATE_MISSING_PERMISSION,
    STATUS_DONE,
    STATUS_NEEDS_REPLY,
    STATUS_REPLIED,
    THREAD_STATUSES,
    InboxPost,
    InboxThread,
)
from .platform_types import InboxPlatformError, Transport, default_transport
from .sync import AccountAccess, require_ready, resolve_account

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - require_ready() reports the import failure
    get_session = None  # type: ignore[assignment]

MIN_REPLY_CHARS = 1
MAX_REPLY_CHARS = 1_000

_APP_FALLBACK_URLS: dict[str, str] = {
    "youtube": "https://studio.youtube.com/",
    "instagram": "https://www.instagram.com/",
    "tiktok": "https://www.tiktok.com/tiktokstudio",
    "facebook": "https://business.facebook.com/latest/inbox",
    "threads": "https://www.threads.net/",
    "bluesky": "https://bsky.app/notifications",
    "linkedin": "https://www.linkedin.com/notifications/",
    "x": "https://x.com/notifications",
    "pinterest": "https://www.pinterest.com/",
    "telegram": "https://web.telegram.org/",
    "discord": "https://discord.com/channels/@me",
    "mastodon": "https://joinmastodon.org/",
}


class ReplyError(RuntimeError):
    def __init__(self, message: str, *, status_code: int, open_url: str = "") -> None:
        self.status_code = status_code
        self.open_url = open_url
        super().__init__(message)


@dataclass(frozen=True)
class ReplyMode:
    mode: str      # "api" | "manual"
    reason: str
    open_url: str

    def to_record(self) -> dict:
        return {"mode": self.mode, "reason": self.reason, "open_url": self.open_url}


def publishing_open() -> bool:
    try:
        from app.core.launch.policy import publishing_enabled

        return bool(publishing_enabled())
    except Exception:  # noqa: BLE001 - a broken flag reads as closed (fail safe)
        return False


def open_url_for(thread: InboxThread | None, post: InboxPost | None, platform: str) -> str:
    if thread is not None and thread.permalink:
        return thread.permalink
    if post is not None and post.url:
        return post.url
    return _APP_FALLBACK_URLS.get(platform, "")


def reply_mode(
    thread: InboxThread,
    post: InboxPost | None,
    caps: PlatformCapabilities | None,
    *,
    publishing: bool,
    now: datetime | None = None,
) -> ReplyMode:
    url = open_url_for(thread, post, thread.platform)
    if caps is None or not caps.connected:
        return ReplyMode("manual", f"Connect {thread.platform} to reply from Menivor.", url)
    access = caps.dms if thread.kind == KIND_DM else caps.comments
    if access.reply != YES:
        return ReplyMode("manual", access.note or "The platform does not allow replies from apps here.", url)
    if thread.platform == "instagram" and thread.kind == KIND_DM and \
            not instagram_client.within_dm_window(thread.last_inbound_at, now):
        return ReplyMode(
            "manual",
            "Instagram only allows app replies within 24 hours of the person's last message.",
            url,
        )
    if not publishing:
        return ReplyMode("manual", "Sending from Menivor is not enabled for your account yet.", url)
    return ReplyMode("api", "", url)


def _validate_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) < MIN_REPLY_CHARS:
        raise ReplyError("Write a reply first.", status_code=400)
    if len(cleaned) > MAX_REPLY_CHARS:
        raise ReplyError(f"Replies are limited to {MAX_REPLY_CHARS} characters.", status_code=400)
    return cleaned


def _dispatch(thread: InboxThread, access: AccountAccess, text: str, transport: Transport,
              post: InboxPost | None = None) -> str:
    token = access.token
    if thread.platform in CHANNEL_INBOX_PLATFORMS:
        from .channel_inbox import send_reply as send_channel_reply

        return send_channel_reply(thread, post, text, transport)
    if thread.platform == "youtube":
        return youtube_client.reply_to_comment(token, thread.external_thread_id, text, transport=transport)
    if thread.platform == "instagram" and thread.kind == KIND_DM:
        return instagram_client.send_dm(token, thread.author_external_id, text, transport=transport)
    if thread.platform == "instagram":
        return instagram_client.reply_to_comment(token, thread.external_thread_id, text, transport=transport)
    if thread.platform == "facebook":
        return facebook_client.reply_to_comment(token, thread.external_thread_id, text, transport=transport)
    if thread.platform == "threads":
        return threads_client.reply_to_comment(token, access.external_account_id, thread.external_thread_id, text,
                                               transport=transport)
    if thread.platform == "bluesky":
        if post is None:
            raise ReplyError("The original Bluesky post is no longer tracked.", status_code=409)
        session = bluesky_client.session_for(access.external_account_id, token,
                                             str(access.meta.get("pds") or "https://bsky.social"), transport=transport)
        return bluesky_client.reply_to_comment(session, post.external_id, thread.external_thread_id, text,
                                               transport=transport)
    raise ReplyError(f"Replies to {thread.platform} are not supported.", status_code=409)


def _append_own_message(thread: InboxThread, message_id: str, text: str, now: datetime, via: str) -> None:
    messages = [m for m in (thread.messages or []) if isinstance(m, dict)]
    messages.append({
        "id": message_id or f"local-{int(now.timestamp())}",
        "author": "You",
        "author_id": "",
        "text": text,
        "at": now.isoformat(),
        "from_me": True,
        "via": via,
    })
    thread.messages = messages[-MAX_THREAD_MESSAGES:]
    thread.last_message_at = now


def send_reply(
    user_id: str, thread_id: str, text: str, *, transport: Transport | None = None, now: datetime | None = None
) -> InboxThread:
    """Post ``text`` through the platform API and mark the thread replied."""
    require_ready()
    body = _validate_text(text)
    moment = now or datetime.now(timezone.utc)
    with get_session() as session:  # type: ignore[misc]
        thread = repo.get_thread(session, user_id, thread_id)
        if thread is None:
            raise ReplyError("Conversation not found.", status_code=404)
        post = repo.get_post(session, user_id, thread.post_id) if thread.post_id else None
        access = resolve_account(session, user_id, thread.platform)
        mode = reply_mode(thread, post, access.caps, publishing=publishing_open(), now=moment)
        if mode.mode != "api":
            raise ReplyError(mode.reason, status_code=409, open_url=mode.open_url)
        session.expunge(thread)
        if post is not None:
            session.expunge(post)

    try:
        reply_id = _dispatch(thread, access, body, transport or default_transport(), post)
    except InboxPlatformError as exc:
        if exc.permission:
            _mark_post_permission(user_id, thread.post_id, str(exc))
            raise ReplyError(str(exc), status_code=409, open_url=mode.open_url) from exc
        if exc.retryable:
            raise ReplyError(str(exc), status_code=503) from exc
        raise ReplyError(str(exc), status_code=502, open_url=mode.open_url) from exc
    except ReplyError:
        raise
    except Exception as exc:  # noqa: BLE001 - network failure
        logger.warning(f"social inbox reply failed for thread {thread_id}: {exc}")
        raise ReplyError("The platform could not be reached. Try again.", status_code=502) from exc

    with get_session() as session:  # type: ignore[misc]
        row = repo.get_thread(session, user_id, thread_id)
        if row is None:  # deleted while sending; the reply already went out
            raise ReplyError("Conversation not found.", status_code=404)
        _append_own_message(row, reply_id, body, moment, "menivor")
        row.status = STATUS_REPLIED
        row.reply_text = body
        row.reply_external_id = reply_id[:160]
        row.reply_via = "api"
        row.replied_at = moment
        session.flush()
        if row.post_id:
            post = repo.get_post(session, user_id, row.post_id)
            if post is not None:
                repo.refresh_post_counts(session, post)
        session.refresh(row)
        session.expunge(row)
        return row


def _mark_post_permission(user_id: str, post_id: str | None, note: str) -> None:
    if not post_id:
        return
    try:
        with get_session() as session:  # type: ignore[misc]
            post = repo.get_post(session, user_id, post_id)
            if post is not None:
                post.inbox_state = STATE_MISSING_PERMISSION
                post.state_note = note[:1000]
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning(f"social inbox: could not flag post {post_id}: {exc}")


def set_status(
    user_id: str, thread_id: str, status: str, *, reply_text: str = "", now: datetime | None = None
) -> InboxThread:
    """Mark a thread ``needs_reply`` / ``replied`` (sent outside Menivor) / ``done``."""
    require_ready()
    if status not in THREAD_STATUSES:
        raise ReplyError(f"status must be one of {sorted(THREAD_STATUSES)}", status_code=400)
    moment = now or datetime.now(timezone.utc)
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_thread(session, user_id, thread_id)
        if row is None:
            raise ReplyError("Conversation not found.", status_code=404)
        row.status = status
        if status == STATUS_REPLIED:
            row.replied_at = moment
            row.reply_via = row.reply_via or "manual"
            text = str(reply_text or "").strip()[:MAX_REPLY_CHARS]
            if text:
                row.reply_text = text
        elif status == STATUS_DONE:
            row.done_at = moment
        elif status == STATUS_NEEDS_REPLY:
            row.done_at = None
        session.flush()
        if row.post_id:
            post = repo.get_post(session, user_id, row.post_id)
            if post is not None:
                repo.refresh_post_counts(session, post)
        session.refresh(row)
        session.expunge(row)
        return row


def thread_context(session: Any, user_id: str, thread: InboxThread) -> tuple[InboxPost | None, str]:
    """The thread's post (if any) and a title for prompts/UI."""
    post = repo.get_post(session, user_id, thread.post_id) if thread.post_id else None
    return post, (post.title if post is not None else "")
