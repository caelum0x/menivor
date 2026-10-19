"""Telegram inbox: direct messages to the bot + comments in the channel's discussion group.

* Read  - ``getUpdates`` from the stored offset (Telegram keeps undelivered
  updates for 24 hours; the inbox polls every 15 minutes). The offset is only
  advanced after the threads are saved, so a failed save re-reads them.
* Reply - ``sendMessage`` with ``reply_parameters`` to the person's last message.

Only messages from private chats with the bot, the connected chat itself, and
the channel's linked discussion group are kept; anything else the bot happens
to see is ignored. Automatic forwards of our own channel posts into the
discussion group are skipped (they are the posts, not comments).

``getUpdates`` does not work while a webhook is set on the bot; that is
reported as "not available" with the fix, never silently.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domains.publishing.extended.connectors import telegram as tg

from .models import KIND_COMMENT, KIND_DM
from .platform_types import FetchedMessage, FetchedThread, InboxPlatformError, Transport

PLATFORM = "telegram"
MAX_UPDATES = 100


def _map_error(exc: tg.TelegramError) -> InboxPlatformError:
    message = str(exc).split("] ", 1)[-1]
    if exc.code == 409:
        return InboxPlatformError(
            PLATFORM, "This bot has a webhook set elsewhere, so Menivor cannot read its messages. Remove the "
                      "webhook (deleteWebhook) or use a separate bot for Menivor.", not_available=True)
    if exc.code in (401, 404):
        return InboxPlatformError(PLATFORM, message, permission=True)
    return InboxPlatformError(PLATFORM, message, retryable=bool(exc.retryable))


def fetch_updates(token: str, offset: int, *, transport: Transport) -> tuple[list[dict], int]:
    """``(updates, next_offset)``; ``next_offset`` is unchanged when nothing new arrived."""
    body: dict = {"timeout": 0, "limit": MAX_UPDATES, "allowed_updates": ["message", "edited_message"]}
    if offset > 0:
        body["offset"] = offset
    try:
        result = tg.call(token, "getUpdates", transport=transport, json=body)
    except tg.TelegramError as exc:
        raise _map_error(exc) from None
    updates = [u for u in (result or []) if isinstance(u, dict)]
    next_offset = offset
    for update in updates:
        try:
            next_offset = max(next_offset, int(update.get("update_id")) + 1)
        except (TypeError, ValueError):
            continue
    return updates, next_offset


def _name(user: dict) -> str:
    parts = [str(user.get("first_name") or ""), str(user.get("last_name") or "")]
    full = " ".join(p for p in parts if p).strip()
    return full or (f"@{user['username']}" if user.get("username") else "Telegram user")


def _text(msg: dict) -> str:
    text = str(msg.get("text") or msg.get("caption") or "").strip()
    if text:
        return text
    for kind, label in (("photo", "[photo]"), ("video", "[video]"), ("voice", "[voice message]"),
                        ("sticker", "[sticker]"), ("document", "[file]"), ("animation", "[GIF]")):
        if msg.get(kind):
            return label
    return "[message]"


def threads_from_updates(updates: list[dict], *, channel_id: str, chat_id: str, linked_chat_id: str = "",
                         chat_username: str = "") -> list[FetchedThread]:
    """Group raw updates into DM and comment threads for one connected channel."""
    allowed_groups = {c for c in (str(chat_id), str(linked_chat_id)) if c}
    grouped: dict[str, dict] = {}
    for update in updates:
        msg = update.get("message") or update.get("edited_message")
        if not isinstance(msg, dict):
            continue
        chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
        sender = msg.get("from") if isinstance(msg.get("from"), dict) else {}
        chat_type = str(chat.get("type") or "")
        cid = str(chat.get("id") or "")
        if msg.get("is_automatic_forward") or (msg.get("sender_chat") or {}).get("type") == "channel":
            continue  # our own channel post mirrored into the discussion group
        if sender.get("is_bot"):
            continue
        if chat_type == "private":
            kind, key, permalink = KIND_DM, f"{channel_id}:dm:{cid}", ""
        elif chat_type in ("group", "supergroup") and cid in allowed_groups:
            reply = msg.get("reply_to_message") if isinstance(msg.get("reply_to_message"), dict) else {}
            root = msg.get("message_thread_id") or reply.get("message_id") or msg.get("message_id")
            kind, key = KIND_COMMENT, f"{channel_id}:g:{cid}:{root}"
            username = str(chat.get("username") or (chat_username if cid == str(chat_id) else ""))
            permalink = f"https://t.me/{username}/{msg.get('message_id')}" if username else ""
        else:
            continue
        try:
            at = datetime.fromtimestamp(int(msg.get("edit_date") or msg.get("date") or 0), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            at = None
        message = FetchedMessage(
            external_id=f"{cid}:{msg.get('message_id')}",
            author_name=_name(sender),
            author_id=str(sender.get("id") or ""),
            text=_text(msg)[:4000],
            at=at,
            from_me=False,
        )
        bucket = grouped.setdefault(key, {"kind": kind, "messages": {}, "permalink": permalink, "first": message})
        bucket["messages"][message.external_id] = message
        if permalink and not bucket["permalink"]:
            bucket["permalink"] = permalink
    out: list[FetchedThread] = []
    for key, bucket in grouped.items():
        messages = tuple(sorted(bucket["messages"].values(), key=lambda m: m.at or datetime.min.replace(
            tzinfo=timezone.utc)))
        latest = messages[-1]
        out.append(FetchedThread(
            kind=bucket["kind"], external_thread_id=key[:160], author_name=bucket["first"].author_name,
            author_id=bucket["first"].author_id, text=latest.text, permalink=bucket["permalink"],
            messages=messages,
        ))
    return out


def reply(token: str, thread_external_id: str, last_inbound_message_id: str, text: str, *,
          transport: Transport) -> str:
    """Reply in the thread's chat; returns ``"<chat_id>:<message_id>"``."""
    parts = thread_external_id.split(":")
    # "<channel>:dm:<chat>" or "<channel>:g:<chat>:<root>"
    if len(parts) < 3 or parts[1] not in ("dm", "g"):
        raise InboxPlatformError(PLATFORM, "This Telegram conversation cannot be answered from Menivor.",
                                 not_available=True)
    chat_id = parts[2]
    reply_to = ""
    if last_inbound_message_id and ":" in last_inbound_message_id:
        msg_chat, msg_id = last_inbound_message_id.rsplit(":", 1)
        if msg_chat == chat_id:
            reply_to = msg_id
    try:
        return tg.send_message(token, chat_id, text, reply_to=reply_to, transport=transport)
    except tg.TelegramError as exc:
        if exc.code == 403:
            raise InboxPlatformError(PLATFORM, "The person blocked the bot or the bot was removed from the group.",
                                     not_available=True) from None
        raise _map_error(exc) from None
