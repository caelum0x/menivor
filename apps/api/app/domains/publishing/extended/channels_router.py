"""HTTP surface for Telegram / Discord / Mastodon channels (owner-scoped, token-free).

    GET    /publishing/channels                         the caller's (and shared workspace) channels + setup help
    POST   /publishing/channels/telegram                connect: bot token + chat id
    POST   /publishing/channels/discord                 connect: webhook URL (+ optional bot token for the inbox)
    POST   /publishing/channels/mastodon                connect: instance + access token
    POST   /publishing/channels/{channel_id}/verify     re-check a stored credential
    POST   /publishing/channels/{channel_id}/test       post a short text right now
    DELETE /publishing/channels/{channel_id}            disconnect (cancels its not-started posts)
    POST   /publishing/channel-posts                    post text and/or a finished reel now or later
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Path, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import (
    get_session,
    require_database as _require_db,
    resolve_principal as _resolve_user,
)
from app.core.launch import require_publishing_enabled
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

from . import channels as channel_service
from .connectors.base import new_default_transport

router = new_router()

_CONNECT_LIMIT = 30
_POST_LIMIT = 60
_WINDOW_S = 3600
_CHANNEL_ID = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
_ID_PATTERN = r"^[A-Za-z0-9]*$"


def _error(request_id: str, status: int, message: str, details: list | None = None) -> HttpException:
    return HttpException(
        task_id=request_id, status_code=status, message=f"{request_id}: {message}",
        data={"problems": details} if details else None,
    )


def _caller(request: Request, request_id: str, *, bucket: str = "", limit: int = 0) -> str:
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if bucket:
            enforce_rate_limit(request, f"{bucket}:{user.id}", limit=limit, window_s=_WINDOW_S)
        return str(user.id)


def _run(request_id: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except channel_service.ChannelError as exc:
        raise _error(request_id, exc.status_code, str(exc), exc.details) from exc
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - storage failure; never echo a credential
        logger.error(f"channels: {getattr(fn, '__name__', 'call')} failed, request_id: {request_id}: "
                     f"{type(exc).__name__}")
        raise _error(request_id, 502, "the channel request failed; try again") from exc


@router.get("/publishing/channels", summary="Telegram / Discord / Mastodon channels")
def list_channels(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    return utils.get_response(200, _run(request_id, channel_service.list_channels, user_id))


class TelegramBody(BaseModel):
    bot_token: str = Field(..., min_length=20, max_length=100)
    chat_id: str = Field(..., min_length=2, max_length=120)
    label: str = Field(default="", max_length=200)
    workspace_id: str | None = Field(default=None, max_length=32, pattern=_ID_PATTERN)


@router.post("/publishing/channels/telegram", summary="Connect a Telegram channel or group")
def connect_telegram(request: Request, body: TelegramBody):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="channel_connect", limit=_CONNECT_LIMIT)
    record = _run(request_id, channel_service.connect_telegram, user_id, body.bot_token, body.chat_id,
                  label=body.label, workspace_id=body.workspace_id or None, transport=new_default_transport())
    return utils.get_response(200, record)


class DiscordBody(BaseModel):
    webhook_url: str = Field(..., min_length=40, max_length=400)
    label: str = Field(default="", max_length=200)
    bot_token: str = Field(default="", max_length=200)
    channel_id: str = Field(default="", max_length=25, pattern=r"^\d*$")
    workspace_id: str | None = Field(default=None, max_length=32, pattern=_ID_PATTERN)


@router.post("/publishing/channels/discord", summary="Connect a Discord channel webhook")
def connect_discord(request: Request, body: DiscordBody):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="channel_connect", limit=_CONNECT_LIMIT)
    record = _run(request_id, channel_service.connect_discord, user_id, body.webhook_url, label=body.label,
                  bot_token=body.bot_token, channel_id=body.channel_id, workspace_id=body.workspace_id or None,
                  transport=new_default_transport())
    return utils.get_response(200, record)


class MastodonBody(BaseModel):
    instance: str = Field(..., min_length=3, max_length=261)
    access_token: str = Field(..., min_length=20, max_length=200)
    label: str = Field(default="", max_length=200)
    visibility: str = Field(default="public", pattern=r"^(public|unlisted|private)$")
    workspace_id: str | None = Field(default=None, max_length=32, pattern=_ID_PATTERN)


@router.post("/publishing/channels/mastodon", summary="Connect a Mastodon account")
def connect_mastodon(request: Request, body: MastodonBody):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="channel_connect", limit=_CONNECT_LIMIT)
    record = _run(request_id, channel_service.connect_mastodon, user_id, body.instance, body.access_token,
                  label=body.label, visibility=body.visibility, workspace_id=body.workspace_id or None,
                  transport=new_default_transport())
    return utils.get_response(200, record)


@router.post("/publishing/channels/{channel_id}/verify", summary="Re-check a channel's credential")
def verify_channel(request: Request, channel_id: str = _CHANNEL_ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="channel_connect", limit=_CONNECT_LIMIT)
    record = _run(request_id, channel_service.reverify, user_id, channel_id, transport=new_default_transport())
    return utils.get_response(200, record)


class TestBody(BaseModel):
    text: str = Field(default="", max_length=1000)


@router.post("/publishing/channels/{channel_id}/test", summary="Post a short test message now")
def test_channel(request: Request, body: TestBody, channel_id: str = _CHANNEL_ID):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    user_id = _caller(request, request_id, bucket="channel_post", limit=_POST_LIMIT)
    record = _run(request_id, channel_service.send_test, user_id, channel_id, body.text,
                  transport=new_default_transport())
    return utils.get_response(200, record)


@router.delete("/publishing/channels/{channel_id}", summary="Disconnect a channel")
def disconnect_channel(request: Request, channel_id: str = _CHANNEL_ID):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    return utils.get_response(200, _run(request_id, channel_service.disconnect, user_id, channel_id))


class ChannelDraftBody(BaseModel):
    channel_id: str = Field(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    caption: str = Field(default="", max_length=4096)
    hashtags: list[str] = Field(default_factory=list, max_length=30)


class ChannelPostsBody(BaseModel):
    drafts: list[ChannelDraftBody] = Field(..., min_length=1, max_length=channel_service.MAX_CHANNELS_PER_POST)
    job_id: str = Field(default="", max_length=32, pattern=_ID_PATTERN)
    scheduled_at: datetime | None = Field(default=None, description="UTC; omit to post now")
    tone: str = Field(default="as_written", pattern=r"^(as_written|professional|casual|concise)$")


@router.post("/publishing/channel-posts", summary="Post to Telegram / Discord / Mastodon channels now or later")
def create_channel_posts(request: Request, body: ChannelPostsBody):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    user_id = _caller(request, request_id, bucket="channel_post", limit=_POST_LIMIT)
    drafts = [
        channel_service.ChannelDraft(channel_id=d.channel_id, caption=d.caption,
                                     hashtags=tuple(t for t in d.hashtags if isinstance(t, str)))
        for d in body.drafts
    ]
    records = _run(request_id, channel_service.create_posts, user_id, drafts, job_id=body.job_id,
                   scheduled_at=body.scheduled_at, tone=body.tone)
    return utils.get_response(200, {"posts": records})
