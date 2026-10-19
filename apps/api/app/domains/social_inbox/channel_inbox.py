"""Inbox tracking for Telegram / Discord / Mastodon channels.

These platforms are conversation-shaped rather than post-shaped, so each
connected channel that can be read gets ONE tracked :class:`~.models.InboxPost`
(``external_id = "dm:<kind>:<channel id>"``; the ``dm:`` prefix gives it the
15-minute channel poll cadence). Each sync reads what is new since the
channel's stored cursor (Telegram update offset, Discord message id, Mastodon
notification id), upserts threads, and only then advances the cursor.

Hooks in :mod:`.sync` (account resolution, per-post sync, "Sync now") and
:mod:`.replies` (reply dispatch) delegate here for these three platforms.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import delete, select

from . import discord_client, mastodon_client, telegram_client
from . import repository as repo
from .capabilities import capabilities_for
from .models import KIND_DM, STATE_ERROR, STATE_MISSING_PERMISSION, STATE_NOT_OFFERED, STATE_OK, InboxPost, InboxThread
from .platform_types import FetchedThread, InboxPlatformError, Transport, default_transport

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - sync.require_ready() reports the import failure
    get_session = None  # type: ignore[assignment]

CHANNEL_PLATFORMS: frozenset[str] = frozenset({"telegram", "discord", "mastodon"})
_LABELS = {"telegram": "Telegram", "discord": "Discord", "mastodon": "Mastodon"}


def external_id_for(kind: str, channel_id: str) -> str:
    return f"{repo.DM_CHANNEL_PREFIX}{kind}:{channel_id}"


def channel_id_of(post: InboxPost) -> str:
    prefix = f"{repo.DM_CHANNEL_PREFIX}{post.platform}:"
    ext = str(post.external_id or "")
    return ext[len(prefix):] if ext.startswith(prefix) else ""


def is_channel_post(post: InboxPost) -> bool:
    return post.platform in CHANNEL_PLATFORMS and bool(channel_id_of(post))


def _channel_models():
    from app.domains.publishing.extended import channels
    from app.domains.publishing.extended.channel_models import STATUS_CONNECTED, SocialChannelCredential

    return channels, SocialChannelCredential, STATUS_CONNECTED


# --------------------------------------------------------------------------- #
# Tracking rows
# --------------------------------------------------------------------------- #
def _ensure(session: Any, row: Any, now: datetime) -> bool:
    meta = dict(row.meta or {})
    if not meta.get("inbox_reader"):
        return False
    if row.kind == "telegram" and meta.get("bot_id"):
        # One reader per bot: getUpdates is bot-wide, two readers would steal each other's updates.
        _, Cred, _ = _channel_models()
        older = session.execute(
            select(Cred.id).where(Cred.user_id == row.user_id, Cred.kind == "telegram", Cred.id != row.id)
            .order_by(Cred.created_at.asc())
        ).scalars().all()
        for other_id in older:
            other = session.get(Cred, other_id)
            if other is not None and dict(other.meta or {}).get("bot_id") == meta.get("bot_id") and \
                    repo.find_post(session, row.user_id, "telegram", external_id_for("telegram", other.id)):
                return False
    _, created = repo.ensure_post(
        session, user_id=row.user_id, platform=row.kind, external_id=external_id_for(row.kind, row.id),
        job_id=None, url=str(meta.get("public_url") or ""),
        title=f"{row.label or row.target_name} ({_LABELS.get(row.kind, row.kind)})",
        posted_at=None, now=now,
    )
    return created


def ensure_channel_post_for(user_id: str, channel_id: str, *, now: datetime | None = None) -> bool:
    _, Cred, _ = _channel_models()
    with get_session() as session:  # type: ignore[misc]
        row = session.get(Cred, channel_id)
        if row is None or row.user_id != user_id:
            return False
        return _ensure(session, row, now or datetime.now(timezone.utc))


def ensure_all(session: Any, user_id: str, now: datetime) -> int:
    """Track every readable channel the creator owns (used by "Sync now")."""
    try:
        _, Cred, _ = _channel_models()
        rows = session.execute(select(Cred).where(Cred.user_id == user_id)).scalars().all()
    except Exception as exc:  # noqa: BLE001 - channel table missing: the core inbox still works
        logger.info(f"social inbox: channel tracking unavailable: {exc}")
        return 0
    return sum(int(_ensure(session, row, now)) for row in rows)


def drop_channel_post(user_id: str, kind: str, channel_id: str) -> None:
    with get_session() as session:  # type: ignore[misc]
        post = repo.find_post(session, user_id, kind, external_id_for(kind, channel_id))
        if post is None:
            return
        session.execute(delete(InboxThread).where(InboxThread.post_id == post.id, InboxThread.user_id == user_id))
        session.delete(post)


def connected_kinds(session: Any, user_id: str) -> dict[str, str]:
    """``{kind: ""}`` for channel kinds with at least one connected, readable channel."""
    try:
        _, Cred, connected = _channel_models()
        rows = session.execute(
            select(Cred.kind, Cred.meta).where(Cred.user_id == user_id, Cred.status == connected)
        ).all()
    except Exception as exc:  # noqa: BLE001
        logger.info(f"social inbox: channel connections unavailable: {exc}")
        return {}
    return {str(kind): "" for kind, meta in rows if dict(meta or {}).get("inbox_reader")}


def resolve_access(session: Any, user_id: str, platform: str):
    from .sync import AccountAccess

    connected = platform in connected_kinds(session, user_id)
    note = "" if connected else f"Connect a {_LABELS.get(platform, platform)} channel from the calendar's Channels page."
    return AccountAccess(connected=connected, caps=capabilities_for(platform, connected=connected), note=note)


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #
def _known_ids(session: Any, user_id: str, post_id: str) -> dict[str, str]:
    """Message id -> thread id for the channel's stored threads (joins replies across polls)."""
    out: dict[str, str] = {}
    for thread in session.execute(
        select(InboxThread).where(InboxThread.user_id == user_id, InboxThread.post_id == post_id)
    ).scalars().all():
        out[thread.external_thread_id] = thread.external_thread_id
        for m in thread.messages or []:
            if isinstance(m, dict) and m.get("id"):
                out[str(m["id"])] = thread.external_thread_id
    return out


def _pull(kind: str, channel_id: str, row: Any, secret: dict, known: dict[str, str],
          transport: Transport) -> tuple[list[FetchedThread], dict]:
    """All network work for one channel; returns ``(threads, cursor_updates)``. Raises InboxPlatformError."""
    meta = dict(row.meta or {})
    if kind == "telegram":
        token = str(secret.get("bot_token") or "")
        offset = int(meta.get("update_offset") or 0)
        updates, next_offset = telegram_client.fetch_updates(token, offset, transport=transport)
        threads = telegram_client.threads_from_updates(
            updates, channel_id=channel_id, chat_id=row.target_id, linked_chat_id=str(meta.get("linked_chat_id") or ""),
            chat_username=str(meta.get("username") or ""),
        )
        return threads, ({"update_offset": next_offset} if next_offset != offset else {})
    if kind == "discord":
        token = str(secret.get("bot_token") or "")
        read_channel = str(meta.get("channel_id") or "")
        if not token or not read_channel:
            raise InboxPlatformError(kind, "Add a bot token to this Discord channel to read replies.",
                                     not_available=True)
        after = str(meta.get("discord_after") or "")
        messages = discord_client.fetch_messages(token, read_channel, after, transport=transport)
        threads = discord_client.threads_from_messages(
            messages, webhook_id=row.target_id, bot_user_id=str(meta.get("bot_user_id") or ""),
            guild_id=str(meta.get("guild_id") or ""), channel_id=read_channel, known=known,
        )
        newest = discord_client.newest_id(messages, after)
        return threads, ({"discord_after": newest} if newest != after else {})
    if kind == "mastodon":
        token = str(secret.get("access_token") or "")
        since = str(meta.get("mastodon_since_id") or "")
        notes = mastodon_client.fetch_mentions(row.instance_url, token, since, transport=transport)
        threads = mastodon_client.threads_from_notifications(notes, known=known)
        newest = mastodon_client.newest_id(notes, since)
        return threads, ({"mastodon_since_id": newest} if newest != since else {})
    raise InboxPlatformError(kind, f"{kind} is not supported.", not_available=True)


def sync_channel_post(user_id: str, post_id: str, *, transport: Transport | None = None,
                      now: datetime | None = None) -> dict:
    from .sync import _next_poll  # noqa: PLC0415 - avoid an import cycle

    channels, _, _ = _channel_models()
    moment = now or datetime.now(timezone.utc)
    with get_session() as session:  # type: ignore[misc]
        post = repo.get_post(session, user_id, post_id)
        if post is None:
            return {"post_id": post_id, "state": "missing"}
        kind, channel_id = post.platform, channel_id_of(post)
        known = _known_ids(session, user_id, post_id)
    row, secret = channels.channel_secret(channel_id)
    threads: list[FetchedThread] = []
    cursor: dict = {}
    state, note, failed = STATE_OK, "", False
    if row is None or row.user_id != user_id:
        state, note = STATE_NOT_OFFERED, "This channel was disconnected."
    elif not secret:
        state, note = STATE_MISSING_PERMISSION, "The stored credential cannot be read. Reconnect the channel."
    else:
        try:
            threads, cursor = _pull(kind, channel_id, row, secret, known, transport or default_transport())
        except InboxPlatformError as exc:
            if exc.permission:
                state = STATE_MISSING_PERMISSION
            elif exc.not_available:
                state = STATE_NOT_OFFERED
            else:
                state, failed = STATE_ERROR, True
            note = str(exc)
        except Exception as exc:  # noqa: BLE001 - network/parse failure; retried with backoff
            logger.warning(f"social inbox: {kind} channel {channel_id} pull failed: {type(exc).__name__}")
            state, note, failed = STATE_ERROR, "The platform could not be reached; will retry.", True

    with get_session() as session:  # type: ignore[misc]
        post = repo.get_post(session, user_id, post_id)
        if post is None:
            return {"post_id": post_id, "state": "missing"}
        for fetched in threads:
            repo.upsert_thread(session, user_id=user_id, platform=kind, post_id=post.id, fetched=fetched, now=moment)
        post.inbox_state = state
        post.state_note = note[:1000]
        post.poll_failures = (int(post.poll_failures or 0) + 1) if failed else 0
        post.last_polled_at = moment
        post.next_poll_at = None if row is None else _next_poll(post, moment, failed=failed)
        session.flush()
        repo.refresh_post_counts(session, post)
    if cursor:
        channels.save_meta(channel_id, cursor)  # only after the threads are stored
    return {"post_id": post_id, "state": state, "threads": len(threads)}


# --------------------------------------------------------------------------- #
# Replies
# --------------------------------------------------------------------------- #
def _last_inbound_id(thread: InboxThread) -> str:
    for m in reversed(list(thread.messages or [])):
        if isinstance(m, dict) and not m.get("from_me") and m.get("id"):
            return str(m["id"])
    return ""


def _last_inbound_author(thread: InboxThread) -> str:
    for m in reversed(list(thread.messages or [])):
        if isinstance(m, dict) and not m.get("from_me") and m.get("author_id"):
            return str(m["author_id"])
    return thread.author_external_id or ""


def send_reply(thread: InboxThread, post: InboxPost | None, text: str, transport: Transport) -> str:
    """Answer a channel thread through the platform; returns the platform message id."""
    if post is None or not is_channel_post(post):
        raise InboxPlatformError(thread.platform, "This conversation is no longer tracked.", not_available=True)
    channels, _, _ = _channel_models()
    row, secret = channels.channel_secret(channel_id_of(post))
    if row is None or row.user_id != thread.user_id or not secret:
        raise InboxPlatformError(thread.platform, "Reconnect this channel to reply.", permission=True)
    meta = dict(row.meta or {})
    if thread.platform == "telegram":
        return telegram_client.reply(str(secret.get("bot_token") or ""), thread.external_thread_id,
                                     _last_inbound_id(thread), text, transport=transport)
    if thread.platform == "discord":
        token = str(secret.get("bot_token") or "")
        if not token:
            raise InboxPlatformError("discord", "Add a bot token to reply from Menivor.", not_available=True)
        return discord_client.reply(token, str(meta.get("channel_id") or ""), _last_inbound_id(thread), text,
                                    transport=transport)
    if thread.platform == "mastodon":
        return mastodon_client.reply(row.instance_url, str(secret.get("access_token") or ""),
                                     acct=_last_inbound_author(thread), in_reply_to=_last_inbound_id(thread),
                                     text=text, direct=thread.kind == KIND_DM, transport=transport)
    raise InboxPlatformError(thread.platform, f"Replies to {thread.platform} are not supported.", not_available=True)
