"""Discord channel post through a channel webhook (free, no bot review).

The creator creates a webhook under *Channel settings -> Integrations ->
Webhooks* and pastes its URL. Posting executes the webhook with
``?wait=true`` so Discord returns the created message:

* video: multipart ``payload_json`` + ``files[0]`` (servers without boosts
  accept 10 MB uploads);
* images (Design Studio pages): multipart ``payload_json`` + ``files[0..9]``
  (up to 10 attachments, same size limit);
* text only: JSON ``{"content": ...}`` (2000 characters).

``allowed_mentions.parse = []`` is always sent, so a caption can never ping
``@everyone`` / ``@here`` / roles. The webhook URL is a secret (it contains the
webhook token); only a strict ``discord.com/api/webhooks/<id>/<token>`` URL is
accepted, which also rules out SSRF through this field. Transport errors are
re-raised without their message for the same reason as Telegram.
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
    error_text,
    image_type,
    is_ok,
    json_of,
    multipart_body,
    multipart_files,
    register,
    retryable,
    status_of,
)

PLATFORM = "discord"
API_BASE = "https://discord.com/api/v10"
CONTENT_MAX = 2000
NO_MENTIONS = {"parse": []}
MAX_FILES = 10

_WEBHOOK_RE = re.compile(
    r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api(?:/v\d{1,2})?/webhooks/(\d{5,25})/([A-Za-z0-9_\-]{20,200})/?$"
)
_SNOWFLAKE_RE = re.compile(r"^\d{5,25}$")


@dataclass(frozen=True)
class Webhook:
    id: str
    token: str

    @property
    def url(self) -> str:
        return f"https://discord.com/api/webhooks/{self.id}/{self.token}"


def parse_webhook(raw: str) -> Webhook | None:
    match = _WEBHOOK_RE.match(str(raw or "").strip())
    return Webhook(id=match.group(1), token=match.group(2)) if match else None


def valid_snowflake(value: str) -> bool:
    return bool(_SNOWFLAKE_RE.match(str(value or "").strip()))


def _request(transport: Transport, method: str, url: str, **kwargs: Any):
    try:
        return transport.request(method, url, **kwargs)
    except Exception:  # noqa: BLE001 - the URL holds the webhook token; never chain it
        raise PublishError(PLATFORM, "Discord could not be reached", retryable=True) from None


@dataclass(frozen=True)
class WebhookInfo:
    webhook_id: str
    name: str
    channel_id: str
    guild_id: str


def verify(webhook_url: str, *, transport: Transport) -> WebhookInfo:
    hook = parse_webhook(webhook_url)
    if hook is None:
        raise PublishError(PLATFORM, "Paste the full webhook URL (https://discord.com/api/webhooks/...).")
    resp = _request(transport, "GET", hook.url)
    if status_of(resp) in (401, 404):
        raise PublishError(PLATFORM, "Discord does not know this webhook. It may have been deleted; create a new one.")
    if not is_ok(resp):
        raise PublishError(PLATFORM, f"Discord refused the webhook: {error_text(resp)}", retryable=retryable(resp))
    body = json_of(resp)
    return WebhookInfo(
        webhook_id=str(body.get("id") or hook.id),
        name=str(body.get("name") or "")[:200],
        channel_id=str(body.get("channel_id") or ""),
        guild_id=str(body.get("guild_id") or ""),
    )


def verify_bot(bot_token: str, channel_id: str, *, transport: Transport) -> tuple[str, str]:
    """Optional inbox reader: the bot must see the channel. Returns ``(channel_name, bot_user_id)``."""
    if not bot_token or not valid_snowflake(channel_id):
        raise PublishError(PLATFORM, "A bot token and the channel id are both needed to read replies.")
    resp = _request(transport, "GET", f"{API_BASE}/channels/{channel_id}",
                    headers={"Authorization": f"Bot {bot_token}"})
    if status_of(resp) == 401:
        raise PublishError(PLATFORM, "Discord rejected the bot token.")
    if status_of(resp) in (403, 404):
        raise PublishError(PLATFORM, "The bot cannot see that channel. Invite it to the server and give it "
                                     "'View Channel' and 'Read Message History'.")
    if not is_ok(resp):
        raise PublishError(PLATFORM, f"Discord refused the bot: {error_text(resp)}", retryable=retryable(resp))
    name = str(json_of(resp).get("name") or "")
    me = _request(transport, "GET", f"{API_BASE}/users/@me", headers={"Authorization": f"Bot {bot_token}"})
    bot_user_id = str(json_of(me).get("id") or "") if is_ok(me) else ""
    return name, bot_user_id


def message_url(guild_id: str, channel_id: str, message_id: str) -> str:
    if not (guild_id and channel_id and message_id):
        return ""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


class DiscordConnector:
    platform = PLATFORM

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step:
        hook = parse_webhook(ctx.access_token)
        if hook is None:
            raise PublishError(PLATFORM, "the Discord webhook is missing or invalid; reconnect the channel")
        text = ctx.text or ""
        if len(text) > CONTENT_MAX:
            raise PublishError(PLATFORM, f"Discord messages are limited to {CONTENT_MAX} characters")
        payload = {"content": text, "allowed_mentions": NO_MENTIONS}
        if ctx.is_image_post:
            images = ctx.image_bytes()
            if not images:
                raise PublishError(PLATFORM, "Discord needs the image files to upload")
            if len(images) > MAX_FILES:
                raise PublishError(PLATFORM, f"Discord messages take at most {MAX_FILES} images")
            files = []
            for index, data in enumerate(images):
                content_type, ext = image_type(data)
                files.append((f"files[{index}]", f"design-{index + 1}.{ext}", data, content_type))
            body, content_type = multipart_files({"payload_json": _json.dumps(payload)}, files)
            resp = _request(transport, "POST", hook.url, params={"wait": "true"},
                            headers={"Content-Type": content_type}, data=body)
        elif ctx.video_path and ctx.video_size() > 0:
            with open(ctx.video_path, "rb") as fh:
                data = fh.read()
            body, content_type = multipart_body(
                {"payload_json": _json.dumps(payload)}, "files[0]", "reel.mp4", data,
            )
            resp = _request(transport, "POST", hook.url, params={"wait": "true"},
                            headers={"Content-Type": content_type}, data=body)
        else:
            if not text.strip():
                raise PublishError(PLATFORM, "nothing to post: add text or a video")
            resp = _request(transport, "POST", hook.url, params={"wait": "true"},
                            headers={"Content-Type": "application/json"}, json=payload)
        if status_of(resp) == 413:
            what = "images are" if ctx.is_image_post else "video is"
            raise PublishError(PLATFORM, f"The {what} larger than this Discord server accepts.")
        if status_of(resp) in (401, 404):
            raise PublishError(PLATFORM, "Discord no longer accepts this webhook; reconnect the channel.")
        if not is_ok(resp):
            raise PublishError(PLATFORM, f"Discord refused the post: {error_text(resp)}", retryable=retryable(resp))
        message = json_of(resp)
        message_id = str(message.get("id") or "")
        if not message_id:
            raise PublishError(PLATFORM, "Discord accepted the post but returned no message id")
        channel_id = str(message.get("channel_id") or ctx.meta.get("channel_id") or "")
        url = message_url(str(ctx.meta.get("guild_id") or ""), channel_id, message_id)
        return Step(status=STEP_PUBLISHED, external_id=message_id, url=url,
                    progress={"message_id": message_id, "channel_id": channel_id})

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step:  # noqa: ARG002 - single step
        message_id = str(ctx.progress.get("message_id") or "")
        if not message_id:
            raise PublishError(PLATFORM, "nothing to resume for Discord")
        url = message_url(str(ctx.meta.get("guild_id") or ""), str(ctx.progress.get("channel_id") or ""), message_id)
        return Step(status=STEP_PUBLISHED, external_id=message_id, url=url, progress=dict(ctx.progress))


register(DiscordConnector())
