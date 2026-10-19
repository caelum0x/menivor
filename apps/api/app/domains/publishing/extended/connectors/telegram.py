"""Telegram channel / group post through the Bot API (free, no review).

The creator makes a bot with @BotFather, adds it as an admin of their channel
(or a member of their group) and pastes the bot token plus the chat id or
``@channelusername``. Posting:

* video: ``sendVideo`` (multipart upload; the Bot API accepts up to 50 MB),
  caption up to 1024 characters;
* images (Design Studio pages): ``sendPhoto`` for one page, ``sendMediaGroup``
  for 2-10 pages (an album; the caption rides on the first photo), 1024
  characters of caption, 10 MB per photo;
* text only: ``sendMessage`` (up to 4096 characters).

Text is sent as plain text (no ``parse_mode``) so user captions can never
break Markdown/HTML entity parsing. The bot token is part of the Bot API URL,
so transport errors are re-raised WITHOUT the underlying message (which would
contain the URL, and therefore the token).
"""

from __future__ import annotations

import json as _json
import re
from dataclasses import dataclass
from typing import Any

from .base import (
    STEP_PUBLISHED,
    PublishContext,
    PublishError,
    Step,
    Transport,
    image_type,
    json_of,
    multipart_body,
    multipart_files,
    register,
    status_of,
)

PLATFORM = "telegram"
API_BASE = "https://api.telegram.org"
TEXT_MAX = 4096
CAPTION_MAX = 1024
MAX_ALBUM = 10
PHOTO_MAX_BYTES = 10 * 1024 * 1024

_TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")
_CHAT_ID_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{3,31})$")


class TelegramError(PublishError):
    """A Bot API refusal. ``code`` is Telegram's ``error_code`` (0 = unreachable)."""

    def __init__(self, message: str, *, code: int = 0, retryable: bool = False) -> None:
        self.code = code
        super().__init__(PLATFORM, message, retryable=retryable)


def valid_token(token: str) -> bool:
    return bool(_TOKEN_RE.match(str(token or "").strip()))


def normalize_chat_id(raw: str) -> str:
    """``"@Name"`` / ``"-100123"`` / ``"t.me/name"`` -> a Bot API ``chat_id``; ``""`` when invalid."""
    value = str(raw or "").strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if value.lower().startswith(prefix):
            value = "@" + value[len(prefix):].strip("/")
            break
    if value and not value.startswith(("@", "-")) and not value.isdigit():
        value = f"@{value}"
    return value if _CHAT_ID_RE.match(value) else ""


def call(token: str, method: str, *, transport: Transport, json: Any = None, data: Any = None,
         headers: dict | None = None) -> Any:
    """One Bot API call; returns ``result`` or raises :class:`TelegramError`."""
    try:
        resp = transport.request(
            "POST", f"{API_BASE}/bot{token}/{method}",
            headers=headers or ({"Content-Type": "application/json"} if json is not None else None),
            json=json, data=data,
        )
    except Exception:  # noqa: BLE001 - never chain/log the cause: its message holds the URL (and token)
        raise TelegramError("Telegram could not be reached", retryable=True) from None
    body = json_of(resp)
    if body.get("ok") is True:
        return body.get("result")
    code = int(body.get("error_code") or status_of(resp) or 0)
    description = str(body.get("description") or f"HTTP {status_of(resp)}")[:300]
    if code == 401 or code == 404:
        raise TelegramError("Telegram rejected the bot token. Create a new token with @BotFather and reconnect.",
                            code=code)
    if code == 429 or code >= 500:
        raise TelegramError(f"Telegram is busy: {description}", code=code, retryable=True)
    raise TelegramError(description, code=code)


@dataclass(frozen=True)
class ChatInfo:
    bot_id: str
    bot_username: str
    chat_id: str
    chat_type: str          # "channel" | "supergroup" | "group" | "private"
    title: str
    username: str           # public @username of the chat ("" when private)
    linked_chat_id: str = ""  # a channel's discussion group (where comments live)


def verify(token: str, chat_id: str, *, transport: Transport) -> ChatInfo:
    """Check the token, the chat, and that the bot may post there."""
    if not valid_token(token):
        raise TelegramError("That does not look like a bot token. Copy it from @BotFather (digits:letters).")
    chat = normalize_chat_id(chat_id)
    if not chat:
        raise TelegramError("Enter the channel as @username or its numeric id (for example -1001234567890).")
    me = call(token, "getMe", transport=transport) or {}
    info = call(token, "getChat", transport=transport, json={"chat_id": chat}) or {}
    bot_id = str(me.get("id") or "")
    member = call(token, "getChatMember", transport=transport,
                  json={"chat_id": chat, "user_id": int(bot_id) if bot_id.isdigit() else bot_id}) or {}
    status = str(member.get("status") or "")
    chat_type = str(info.get("type") or "")
    if chat_type == "channel" and status not in ("administrator", "creator"):
        raise TelegramError("Add the bot as an admin of the channel with permission to post messages.")
    if status in ("left", "kicked", ""):
        raise TelegramError("The bot is not a member of that chat. Add it first.")
    if status == "administrator" and chat_type == "channel" and member.get("can_post_messages") is False:
        raise TelegramError("The bot is an admin but cannot post. Turn on 'Post messages' for it.")
    return ChatInfo(
        bot_id=bot_id,
        bot_username=str(me.get("username") or ""),
        chat_id=str(info.get("id") or chat),
        chat_type=chat_type,
        title=str(info.get("title") or info.get("username") or chat)[:200],
        username=str(info.get("username") or ""),
        linked_chat_id=str(info.get("linked_chat_id") or ""),
    )


def send_message(token: str, chat_id: str, text: str, *, reply_to: str = "", transport: Transport) -> str:
    """Send a plain-text message (optionally as a reply); returns ``"<chat_id>:<message_id>"``."""
    body: dict = {"chat_id": chat_id, "text": text[:TEXT_MAX]}
    if reply_to and str(reply_to).isdigit():
        body["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
    result = call(token, "sendMessage", transport=transport, json=body) or {}
    return f"{chat_id}:{result.get('message_id') or ''}"


def message_url(chat_id: str, message_id: str, username: str = "") -> str:
    """Public link to a message: ``t.me/<username>/<id>`` or ``t.me/c/<internal>/<id>``."""
    if not message_id:
        return ""
    if username:
        return f"https://t.me/{username.lstrip('@')}/{message_id}"
    cid = str(chat_id or "")
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return ""


class TelegramConnector:
    platform = PLATFORM

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        token = ctx.access_token
        chat_id = ctx.target_id
        if not token or not chat_id:
            raise PublishError(PLATFORM, "the Telegram channel is not fully connected")
        text = ctx.text or ""
        if ctx.is_image_post:
            return self._publish_images(ctx, token, chat_id, text, transport)
        if ctx.video_path and ctx.video_size() > 0:
            if len(text) > CAPTION_MAX:
                raise PublishError(PLATFORM, f"Telegram video captions are limited to {CAPTION_MAX} characters")
            with open(ctx.video_path, "rb") as fh:
                payload = fh.read()
            body, content_type = multipart_body(
                {"chat_id": chat_id, "caption": text, "supports_streaming": "true"},
                "video", "reel.mp4", payload,
            )
            result = call(token, "sendVideo", transport=transport, data=body,
                          headers={"Content-Type": content_type})
        else:
            if not text.strip():
                raise PublishError(PLATFORM, "nothing to post: add text or a video")
            if len(text) > TEXT_MAX:
                raise PublishError(PLATFORM, f"Telegram messages are limited to {TEXT_MAX} characters")
            result = call(token, "sendMessage", transport=transport,
                          json={"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": False}})
        message_id = str((result or {}).get("message_id") or "")
        if not message_id:
            raise PublishError(PLATFORM, "Telegram accepted the post but returned no message id")
        url = message_url(chat_id, message_id, str(ctx.meta.get("username") or ""))
        return Step(status=STEP_PUBLISHED, external_id=f"{chat_id}:{message_id}", url=url,
                    progress={"message_id": message_id})

    def _publish_images(self, ctx: PublishContext, token: str, chat_id: str, text: str,
                        transport: Transport) -> Step:
        images = ctx.image_bytes()
        if not images:
            raise PublishError(PLATFORM, "Telegram needs the image files to upload")
        if len(images) > MAX_ALBUM:
            raise PublishError(PLATFORM, f"Telegram albums take at most {MAX_ALBUM} images")
        if len(text) > CAPTION_MAX:
            raise PublishError(PLATFORM, f"Telegram photo captions are limited to {CAPTION_MAX} characters")
        if any(len(p) > PHOTO_MAX_BYTES for p in images):
            raise PublishError(PLATFORM, "Telegram accepts photos up to 10 MB")
        if len(images) == 1:
            content_type, ext = image_type(images[0])
            body, form_type = multipart_body({"chat_id": chat_id, "caption": text}, "photo", f"design.{ext}",
                                             images[0], content_type=content_type)
            result = call(token, "sendPhoto", transport=transport, data=body, headers={"Content-Type": form_type})
            first = result or {}
        else:
            media, files = [], []
            for index, payload in enumerate(images):
                content_type, ext = image_type(payload)
                name = f"page{index}"
                item = {"type": "photo", "media": f"attach://{name}"}
                if index == 0 and text:
                    item["caption"] = text
                media.append(item)
                files.append((name, f"{name}.{ext}", payload, content_type))
            body, form_type = multipart_files({"chat_id": chat_id, "media": _json.dumps(media)}, files)
            result = call(token, "sendMediaGroup", transport=transport, data=body,
                          headers={"Content-Type": form_type})
            first = result[0] if isinstance(result, list) and result else {}
        message_id = str((first or {}).get("message_id") or "")
        if not message_id:
            raise PublishError(PLATFORM, "Telegram accepted the photos but returned no message id")
        url = message_url(chat_id, message_id, str(ctx.meta.get("username") or ""))
        return Step(status=STEP_PUBLISHED, external_id=f"{chat_id}:{message_id}", url=url,
                    progress={"message_id": message_id})

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:  # noqa: ARG002 - single step
        message_id = str(ctx.progress.get("message_id") or "")
        if not message_id:
            raise PublishError(PLATFORM, "nothing to resume for Telegram")
        return Step(status=STEP_PUBLISHED, external_id=f"{ctx.target_id}:{message_id}",
                    url=message_url(ctx.target_id, message_id, str(ctx.meta.get("username") or "")),
                    progress=dict(ctx.progress))


register(TelegramConnector())
