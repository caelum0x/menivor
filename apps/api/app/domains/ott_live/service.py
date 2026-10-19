"""Live streams (MV10): passthrough on MediaMTX, capped, recorded, and turned into VOD titles.

* The creator creates a stream and gets an ingest address plus a stream key
  (shown once, only its SHA-256 kept). OBS publishes RTMP or SRT to MediaMTX,
  which asks :func:`authorize` before accepting a publisher or a viewer.
* **Caps (OD-MV5):** at most ``OTT_LIVE_MAX_STREAMS`` (2) live at once on the
  whole box and ``OTT_LIVE_MAX_VIEWERS`` (50) viewers per stream; passthrough
  only (no transcoding).
* Viewers get a short token (the same HMAC tokens as VOD, bound to
  ``live:<stream>``) in the LL-HLS URL; MediaMTX sends it back to the auth
  hook on read.
* MediaMTX records fMP4; each finished recording segment is uploaded to the
  OTT bucket by the sidecar hook and :func:`recording_uploaded` turns it into a
  draft VOD title queued for packaging (target: within 10 minutes of the end).
* Latency is recorded from player samples (never promised in copy).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import statistics
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import parse_qs

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.ott.models import OttChannel, OttTitle
from app.domains.ott_access import limits, tokens

from .models import ENDED, IDLE, LIVE, OttLiveStream

DEFAULT_MAX_STREAMS = 2
DEFAULT_MAX_VIEWERS = 50
PATH_PREFIX = "live/"
STALE_AFTER = timedelta(hours=12)
MAX_LATENCY_SAMPLES = 50
HOOK_SECRET_ENV = "OTT_LIVE_HOOK_SECRET"
INGEST_ENV = "OTT_LIVE_INGEST_URL"
PLAYBACK_ENV = "OTT_LIVE_PLAYBACK_BASE"


class LiveError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def now() -> datetime:
    return datetime.now(timezone.utc)


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name) or default))
    except ValueError:
        return default


def max_streams() -> int:
    return _int_env("OTT_LIVE_MAX_STREAMS", DEFAULT_MAX_STREAMS)


def max_viewers() -> int:
    return _int_env("OTT_LIVE_MAX_VIEWERS", DEFAULT_MAX_VIEWERS)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def ingest_base() -> str:
    return (os.getenv(INGEST_ENV) or "rtmp://live.menivor.com").rstrip("/")


def playback_base() -> str:
    return (os.getenv(PLAYBACK_ENV) or "https://live.menivor.com").rstrip("/")


# --------------------------------------------------------------------------- #
# Creator side
# --------------------------------------------------------------------------- #
def create_stream(session: Session, channel: OttChannel, *, title: str, access_tier: str = "free") -> dict[str, Any]:
    from app.domains.presets_hub.catalog import vendor_hits

    name = " ".join(str(title or "").split())[:120]
    if not name:
        raise LiveError(400, "title", "give the stream a title")
    if vendor_hits(name):
        raise LiveError(400, "copy_vendor", "titles cannot name tools or models")
    if access_tier not in ("free", "paid"):
        raise LiveError(400, "access", "access is free or paid")
    key = f"sk_{secrets.token_urlsafe(24)}"
    stream = OttLiveStream(channel_id=channel.id, title=name, path=secrets.token_hex(8), key_hash=_hash(key),
                           access_tier=access_tier, status=IDLE, latency_samples=[], recordings=[],
                           vod_title_ids=[], banned_viewer_ids=[])
    session.add(stream)
    session.flush()
    return {**stream_view(stream), **ingest(stream, key)}


def ingest(stream: OttLiveStream, key: str) -> dict[str, Any]:
    """What OBS needs; the key appears in this answer only."""
    return {"ingest": {"server": f"{ingest_base()}/{PATH_PREFIX.rstrip('/')}",
                       "stream_key": f"{stream.path}?key={key}",
                       "srt": f"{ingest_base().replace('rtmp://', 'srt://')}:8890?streamid=publish:"
                              f"{PATH_PREFIX}{stream.path}:{key}"}}


def rotate_key(session: Session, stream: OttLiveStream) -> dict[str, Any]:
    if stream.status == LIVE:
        raise LiveError(409, "live", "end the stream before you change its key")
    key = f"sk_{secrets.token_urlsafe(24)}"
    stream.key_hash = _hash(key)
    session.flush()
    return ingest(stream, key)


def stream_view(stream: OttLiveStream) -> dict[str, Any]:
    samples = [float(s) for s in stream.latency_samples or []]
    return {"id": stream.id, "title": stream.title, "status": stream.status, "access_tier": stream.access_tier,
            "started_at": stream.started_at.isoformat() if stream.started_at else None,
            "ended_at": stream.ended_at.isoformat() if stream.ended_at else None,
            "peak_viewers": stream.peak_viewers,
            "latency_s": {"median": round(statistics.median(samples), 1), "samples": len(samples)} if samples
            else None,
            "vod_title_ids": list(stream.vod_title_ids or []), "chat_enabled": stream.chat_enabled,
            "slow_mode_s": stream.slow_mode_s}


# --------------------------------------------------------------------------- #
# MediaMTX hooks
# --------------------------------------------------------------------------- #
def hook_secret() -> str:
    return (os.getenv(HOOK_SECRET_ENV) or "").strip()


def check_hook(given: str) -> None:
    secret = hook_secret()
    if len(secret) < 24 or not hmac.compare_digest(str(given or ""), secret):
        raise LiveError(401, "hook", "unknown caller")


def _stream_for_path(session: Session, path: str) -> Optional[OttLiveStream]:
    clean = str(path or "")
    if not clean.startswith(PATH_PREFIX):
        return None
    return session.execute(select(OttLiveStream).where(OttLiveStream.path == clean[len(PATH_PREFIX):])
                           ).scalar_one_or_none()


def _query(raw: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(str(raw or "")).items() if v}


def authorize(session: Session, body: Mapping[str, Any], *, at: Optional[float] = None) -> None:
    """MediaMTX's HTTP auth: raise to refuse. ``action`` is publish, read or playback."""
    action = str(body.get("action") or "")
    stream = _stream_for_path(session, str(body.get("path") or ""))
    if stream is None:
        raise LiveError(404, "path", "unknown stream")
    query = _query(str(body.get("query") or ""))
    if action == "publish":
        key = query.get("key") or str(body.get("password") or "")
        if not key or not hmac.compare_digest(_hash(key), stream.key_hash):
            raise LiveError(401, "key", "wrong stream key")
        live_now = session.execute(select(func.count(OttLiveStream.id)).where(
            OttLiveStream.status == LIVE, OttLiveStream.id != stream.id)).scalar_one()
        if live_now >= max_streams():
            raise LiveError(429, "streams_full", f"only {max_streams()} live streams can run at once")
        return
    if action in ("read", "playback"):
        try:
            grant = tokens.verify(query.get("t", ""), title_id=f"live:{stream.id}", now=at)
        except tokens.TokenError as exc:
            raise LiveError(401, "token", "this link has expired") from exc
        if not limits.admit(f"live-audience:{stream.id}", grant.session_id, limit=max_viewers(), now=at):
            raise LiveError(429, "viewers_full", "this stream is full")
        return
    raise LiveError(403, "action", "not allowed")


def on_ready(session: Session, path: str) -> Optional[OttLiveStream]:
    stream = _stream_for_path(session, path)
    if stream is None:
        return None
    went_live = stream.status != LIVE
    stream.status, stream.started_at, stream.ended_at = LIVE, now(), None
    session.flush()
    if went_live:
        # Wave Q QM1.5 (U39): ott.live.started to webhooks and a live push to opted-in viewers, after commit.
        from app.domains.ott import events
        from app.domains.ott.models import OttChannel

        channel = session.get(OttChannel, stream.channel_id)
        if channel is not None:
            event_id, payload = events.live_started(channel, stream)
            events.queue(session, channel.id, events.LIVE_STARTED, event_id, payload)
    return stream


def on_ended(session: Session, path: str) -> Optional[OttLiveStream]:
    stream = _stream_for_path(session, path)
    if stream is None or stream.status != LIVE:
        return stream
    stream.status, stream.ended_at = ENDED, now()
    session.flush()
    return stream


def recording_key(stream: OttLiveStream, user_id: str, n: int) -> str:
    return f"ott-uploads/{user_id}/live-{stream.id}/part-{int(n):02d}.mp4"


def recording_upload_url(session: Session, path: str, *, presign_put) -> dict[str, Any]:
    """Where the sidecar uploads a finished recording segment (a presigned PUT into the OTT bucket)."""
    stream = _stream_for_path(session, path)
    if stream is None:
        raise LiveError(404, "path", "unknown stream")
    channel = session.get(OttChannel, stream.channel_id)
    n = len(stream.recordings or []) + 1
    key = recording_key(stream, str(channel.user_id), n)
    return {"key": key, "url": presign_put(key, "video/mp4", 3600), "part": n}


def recording_uploaded(session: Session, path: str, *, key: str, seconds: float, short_side: int) -> dict[str, Any]:
    """A finished recording segment is in the bucket: make it a draft VOD title and queue its packaging."""
    from app.services.ott_transcode import service as transcode

    stream = _stream_for_path(session, path)
    if stream is None:
        raise LiveError(404, "path", "unknown stream")
    channel = session.get(OttChannel, stream.channel_id)
    if not key.startswith(f"ott-uploads/{channel.user_id}/live-{stream.id}/"):
        raise LiveError(400, "key", "not this stream's recording")
    if key in (stream.recordings or []):
        return {"title_id": None, "duplicate": True}
    part = len(stream.recordings or []) + 1
    name = stream.title if part == 1 else f"{stream.title} (part {part})"
    title = OttTitle(channel_id=channel.id, kind="episode", source_key=f"ott:{key}", title=name[:120],
                     duration_s=float(seconds), genres=[], geo_countries=[], access_tier=stream.access_tier)
    session.add(title)
    session.flush()
    job = transcode.submit(session, title, source_key=f"ott:{key}", seconds=float(seconds),
                           short_side=int(short_side), user_id=str(channel.user_id))
    stream.recordings = [*(stream.recordings or []), key]
    stream.vod_title_ids = [*(stream.vod_title_ids or []), title.id]
    _queue_content_check(session, title, str(channel.user_id), float(seconds))
    session.flush()
    return {"title_id": title.id, "job_id": job.id, "lane": job.lane}


def _queue_content_check(session: Session, title: OttTitle, user_id: str, seconds: float) -> None:
    """Wave Q QM1.2: a recording is creator content like an upload, so it passes the same check."""
    from sqlalchemy import event

    from app.domains.ott import upload_check

    upload_check.record_upload(session, title, user_id=user_id, size_bytes=0, seconds=seconds)
    title_id = title.id

    def _enqueue(_session) -> None:
        from app.services.ott_transcode.router import enqueue_upload_check

        enqueue_upload_check(title_id)

    event.listen(session, "after_commit", _enqueue, once=True)


# --------------------------------------------------------------------------- #
# Viewers
# --------------------------------------------------------------------------- #
def watch(session: Session, stream: OttLiveStream, *, viewer_account_id: Optional[str], user_id: Optional[str],
          device: str) -> dict[str, Any]:
    from app.domains.ott_commerce import entitlements

    if stream.status != LIVE:
        raise LiveError(409, "not_live", "This stream is not live right now.")
    if stream.access_tier != "free":
        probe = OttTitle(channel_id=stream.channel_id, access_tier="paid", title="")
        if not entitlements.can_watch(session, probe, viewer_id=viewer_account_id, user_id=user_id):
            raise LiveError(402, "members_only", "This stream is for members of the channel.")
    try:
        token, grant = tokens.issue(f"live:{stream.id}", viewer_account_id or device, "XX")
    except tokens.TokenError as exc:
        raise LiveError(503, "playback_off", "Live playback is not available right now.") from exc
    return {"hls_url": f"{playback_base()}/{PATH_PREFIX}{stream.path}/index.m3u8?t={token}", "expires_at": grant.exp}


def record_viewers(session: Session, stream: OttLiveStream, *, at: Optional[float] = None) -> int:
    count = len(limits.store().active(f"live-audience:{stream.id}", at or datetime.now(timezone.utc).timestamp()))
    if count > stream.peak_viewers:
        stream.peak_viewers = count
        session.flush()
    return count


def add_latency(session: Session, stream: OttLiveStream, seconds: float) -> None:
    if not 0 < float(seconds) < 120:
        raise LiveError(400, "latency", "latency sample out of range")
    stream.latency_samples = [*(stream.latency_samples or []), round(float(seconds), 2)][-MAX_LATENCY_SAMPLES:]
    session.flush()


def live_now(session: Session, channel_id: str) -> list[OttLiveStream]:
    return list(session.execute(select(OttLiveStream).where(OttLiveStream.channel_id == channel_id,
                                                            OttLiveStream.status == LIVE)).scalars())


def sweep_stale(session: Session, *, at: Optional[datetime] = None) -> int:
    """Close streams that stayed "live" far longer than possible (a lost end hook)."""
    cutoff = (at or now()) - STALE_AFTER
    rows = session.execute(select(OttLiveStream).where(OttLiveStream.status == LIVE)).scalars().all()
    closed = 0
    for stream in rows:
        started = stream.started_at if stream.started_at is None or stream.started_at.tzinfo else \
            stream.started_at.replace(tzinfo=timezone.utc)
        if started is not None and started < cutoff:
            stream.status, stream.ended_at = ENDED, at or now()
            closed += 1
    session.flush()
    return closed


__all__ = ["LiveError", "PATH_PREFIX", "add_latency", "authorize", "check_hook", "create_stream", "ingest",
           "live_now", "max_streams", "max_viewers", "on_ended", "on_ready", "record_viewers", "recording_upload_url",
           "recording_uploaded", "rotate_key", "stream_view", "sweep_stale", "watch"]
