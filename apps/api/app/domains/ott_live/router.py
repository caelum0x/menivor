"""Live and chat routes (MV10, MV11). 404 until OTT_ENABLED and OTT_LIVE_LIVE (chat also OTT_CHAT_LIVE).

Creator: ``GET/POST /ott/studio/live``, ``POST /ott/studio/live/{id}/key``,
``GET /ott/studio/live/{id}/chat``, ``PUT /ott/studio/live/{id}/chat``,
``POST /ott/studio/live/{id}/chat/{message_id}/hide``, ``POST /ott/studio/live/{id}/chat/ban``.
MediaMTX (``?secret=OTT_LIVE_HOOK_SECRET``): ``POST /ott/live/hooks/{auth,ready,ended,recording-url,recording-done}``.
Viewers: ``GET /ott/c/{handle}/live``, ``POST /ott/live/{id}/watch``, ``POST /ott/live/{id}/latency``,
``GET/POST /ott/live/{id}/chat``.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.ott import flags
from app.domains.ott.service import ensure_channel
from app.domains.ott_viewers import service as viewers, session as viewer_session
from app.models.exception import HttpException
from app.utils import utils

from . import chat, service
from .models import OttLiveStream

router = new_router()
_LIVE = [Depends(flags.require("live"))]
_CHAT = [Depends(flags.require("live")), Depends(flags.require("chat"))]
NO_STORE = {"Cache-Control": "no-store, private"}
PUBLIC_CACHE = "public, max-age=10, s-maxage=15"


class StreamCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    access_tier: str = Field("free", max_length=8)


class ChatRules(BaseModel):
    slow_mode_s: int | None = Field(None, ge=0, le=300)
    chat_enabled: bool | None = None


class ChatPost(BaseModel):
    body: str = Field(..., min_length=1, max_length=600)


class Ban(BaseModel):
    viewer_id: str = Field(..., max_length=32)


class Latency(BaseModel):
    seconds: float = Field(..., gt=0, lt=120)


class RecordingDone(BaseModel):
    path: str = Field(..., max_length=80)
    key: str = Field(..., max_length=512)
    seconds: float = Field(..., gt=0, le=12 * 3600)
    short_side: int = Field(720, ge=0, le=4320)


def _http(exc: Exception, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=getattr(exc, "status_code", 400), message=str(exc),
                         data={"code": getattr(exc, "code", "error")})


def _own_stream(session, channel_id: str, stream_id: str) -> OttLiveStream:
    stream = session.get(OttLiveStream, stream_id)
    if stream is None or stream.channel_id != channel_id:
        raise service.LiveError(404, "not_found", "stream not found")
    return stream


def _studio(request: Request, fn):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            return utils.get_response(200, fn(session, ensure_channel(session, str(user.id))))
        except (service.LiveError, chat.ChatError) as exc:
            raise _http(exc, request_id) from exc


@router.get("/ott/studio/live", dependencies=_LIVE, summary="My live streams")
def my_streams(request: Request):
    from sqlalchemy import select

    return _studio(request, lambda s, ch: {"streams": [service.stream_view(x) for x in s.execute(
        select(OttLiveStream).where(OttLiveStream.channel_id == ch.id).order_by(OttLiveStream.created_at.desc())
    ).scalars()], "max_streams": service.max_streams(), "max_viewers": service.max_viewers()})


@router.post("/ott/studio/live", dependencies=_LIVE, summary="Create a live stream (the key is shown once)")
def create_stream(request: Request, body: StreamCreate):
    return _studio(request, lambda s, ch: service.create_stream(s, ch, title=body.title, access_tier=body.access_tier))


@router.post("/ott/studio/live/{stream_id}/key", dependencies=_LIVE, summary="New stream key")
def rotate(request: Request, stream_id: str = Path(..., max_length=32)):
    return _studio(request, lambda s, ch: service.rotate_key(s, _own_stream(s, ch.id, stream_id)))


@router.get("/ott/studio/live/{stream_id}/chat", dependencies=_CHAT, summary="Chat with viewer ids (moderation)")
def studio_chat(request: Request, stream_id: str = Path(..., max_length=32)):
    from sqlalchemy import select

    from .models import OttChatMessage

    def _read(s, ch):
        stream = _own_stream(s, ch.id, stream_id)
        rows = s.execute(select(OttChatMessage).where(OttChatMessage.stream_id == stream.id)
                         .order_by(OttChatMessage.created_at.desc()).limit(200)).scalars().all()
        return {"messages": [{**chat.message_view(m), "viewer_id": m.viewer_id, "hidden": m.hidden_at is not None}
                             for m in reversed(rows)], "slow_mode_s": stream.slow_mode_s,
                "chat_enabled": stream.chat_enabled}

    return _studio(request, _read)


@router.put("/ott/studio/live/{stream_id}/chat", dependencies=_CHAT, summary="Slow mode and chat on or off")
def chat_rules(request: Request, body: ChatRules, stream_id: str = Path(..., max_length=32)):
    def _set(s, ch):
        stream = _own_stream(s, ch.id, stream_id)
        chat.set_rules(s, stream, body.model_dump(exclude_none=True))
        return service.stream_view(stream)

    return _studio(request, _set)


@router.post("/ott/studio/live/{stream_id}/chat/{message_id}/hide", dependencies=_CHAT, summary="Take a message down")
def hide_message(request: Request, stream_id: str = Path(..., max_length=32),
                 message_id: str = Path(..., max_length=32)):
    return _studio(request, lambda s, ch: chat.hide(s, _own_stream(s, ch.id, stream_id), message_id))


@router.post("/ott/studio/live/{stream_id}/chat/ban", dependencies=_CHAT, summary="Ban a viewer from this chat")
def ban(request: Request, body: Ban, stream_id: str = Path(..., max_length=32)):
    return _studio(request, lambda s, ch: chat.ban(s, _own_stream(s, ch.id, stream_id), body.viewer_id))


# --------------------------------------------------------------------------- #
# MediaMTX hooks
# --------------------------------------------------------------------------- #
def _hook(request: Request, secret: str, fn):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    try:
        service.check_hook(secret)
        with get_session() as session:
            return fn(session)
    except service.LiveError as exc:
        raise _http(exc, request_id) from exc


@router.post("/ott/live/hooks/auth", dependencies=_LIVE, summary="MediaMTX asks: may this client publish or read?")
async def hook_auth(request: Request, secret: str = Query("", max_length=200)):
    body = await request.json()
    _hook(request, secret, lambda s: service.authorize(s, body if isinstance(body, dict) else {}))
    return Response(status_code=200)


@router.post("/ott/live/hooks/ready", dependencies=_LIVE, summary="MediaMTX: a stream went live")
def hook_ready(request: Request, secret: str = Query("", max_length=200), path: str = Query(..., max_length=80)):
    _hook(request, secret, lambda s: service.on_ready(s, path))
    return utils.get_response(200, {"ok": True})


@router.post("/ott/live/hooks/ended", dependencies=_LIVE, summary="MediaMTX: a stream ended")
def hook_ended(request: Request, secret: str = Query("", max_length=200), path: str = Query(..., max_length=80)):
    _hook(request, secret, lambda s: service.on_ended(s, path))
    return utils.get_response(200, {"ok": True})


@router.post("/ott/live/hooks/recording-url", dependencies=_LIVE, summary="Where to upload a finished recording")
def hook_recording_url(request: Request, secret: str = Query("", max_length=200),
                       path: str = Query(..., max_length=80)):
    from app.services.ott_transcode.router import storage

    result = _hook(request, secret, lambda s: service.recording_upload_url(s, path, presign_put=storage().presign_put))
    return utils.get_response(200, result)


@router.post("/ott/live/hooks/recording-done", dependencies=_LIVE, summary="A recording is uploaded: make it VOD")
def hook_recording_done(request: Request, body: RecordingDone, secret: str = Query("", max_length=200)):
    from app.services.ott_transcode.models import LANE_BOX1
    from app.services.ott_transcode.router import enqueue_box1

    result = _hook(request, secret, lambda s: service.recording_uploaded(
        s, body.path, key=body.key, seconds=body.seconds, short_side=body.short_side))
    if result.get("lane") == LANE_BOX1 and result.get("job_id"):
        enqueue_box1(result["job_id"])
    return utils.get_response(200, result)


# --------------------------------------------------------------------------- #
# Viewers
# --------------------------------------------------------------------------- #
@router.get("/ott/c/{handle}/live", dependencies=_LIVE, summary="Live now on this channel (public)")
def channel_live(request: Request, response: Response, handle: str = Path(..., max_length=40)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            channel = viewers.published_channel(session, handle)
        except viewers.ViewerError as exc:
            raise _http(exc, request_id) from exc
        streams = [{k: v for k, v in service.stream_view(s).items() if k in ("id", "title", "access_tier",
                                                                             "started_at", "chat_enabled")}
                   for s in service.live_now(session, channel.id)]
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return utils.get_response(200, {"streams": streams})


def _viewer_stream(session, request: Request, stream_id: str):
    stream = session.get(OttLiveStream, stream_id)
    if stream is None:
        raise service.LiveError(404, "not_found", "stream not found")
    account = viewer_session.from_request(session, request)
    if account is not None and account.channel_id != stream.channel_id:
        account = None
    return stream, account


@router.post("/ott/live/{stream_id}/watch", dependencies=_LIVE, summary="Watch a live stream")
def watch(request: Request, response: Response, stream_id: str = Path(..., max_length=32)):
    from app.domains.ott_access import service as access

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            stream, account = _viewer_stream(session, request, stream_id)
            user_id = None
            if request.headers.get("x-api-key") or request.headers.get("authorization"):
                try:
                    user_id = str(_resolve_user(request, session, request_id).id)
                except HttpException:
                    user_id = None
            result = service.watch(session, stream, viewer_account_id=account.id if account else None,
                                   user_id=user_id, device=f"device:{access.client_fingerprint(request)}")
            service.record_viewers(session, stream)
        except service.LiveError as exc:
            raise _http(exc, request_id) from exc
    response.headers.update(NO_STORE)
    return utils.get_response(200, result)


@router.post("/ott/live/{stream_id}/latency", dependencies=_LIVE, summary="Report the latency this player sees")
def latency(request: Request, body: Latency, stream_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        stream = session.get(OttLiveStream, stream_id)
        if stream is None:
            raise HttpException(task_id=request_id, status_code=404, message="stream not found")
        try:
            service.add_latency(session, stream, body.seconds)
        except service.LiveError as exc:
            raise _http(exc, request_id) from exc
    return Response(status_code=204)


@router.get("/ott/live/{stream_id}/chat", dependencies=_CHAT, summary="Recent chat (public)")
def read_chat(request: Request, response: Response, stream_id: str = Path(..., max_length=32),
              after: str = Query("", max_length=40)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    since = None
    if after:
        try:
            since = datetime.fromisoformat(after)
        except ValueError as exc:
            raise HttpException(task_id=request_id, status_code=400, message="bad after") from exc
    with get_session() as session:
        stream = session.get(OttLiveStream, stream_id)
        if stream is None:
            raise HttpException(task_id=request_id, status_code=404, message="stream not found")
        messages = chat.recent(session, stream, after=since)
    response.headers.update(NO_STORE)
    return utils.get_response(200, {"messages": messages, "topic": chat.topic(stream_id)})


@router.post("/ott/live/{stream_id}/chat", dependencies=_CHAT, summary="Post in the live chat")
def post_chat(request: Request, body: ChatPost, response: Response, stream_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        try:
            stream, account = _viewer_stream(session, request, stream_id)
            if account is None:
                raise chat.ChatError(401, "signed_out", "Sign in to this channel to chat.")
            message = chat.post(session, stream, account, body.body)
        except (service.LiveError, chat.ChatError) as exc:
            raise _http(exc, request_id) from exc
    response.headers.update(NO_STORE)
    return utils.get_response(200, message)
