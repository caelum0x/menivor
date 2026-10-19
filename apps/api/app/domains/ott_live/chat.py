"""Live chat (MV11) on Scribase Realtime (dogfood), with a moderation budget, slow mode and takedown.

* Only signed-in viewers of the stream's channel can post; banned viewers
  cannot. Messages are plain text, 300 characters at most, no links, and
  never a word from ``OTT_CHAT_BLOCKED_WORDS``.
* **Budget:** a viewer may post 20 messages per 5 minutes and a stream takes
  600 messages per minute; **slow mode** adds a per-viewer wait set by the
  creator.
* Each accepted message is stored, then broadcast on the Realtime topic
  ``ott-live:<stream>`` (``SCRIBASE_REALTIME_URL`` + ``SCRIBASE_SERVICE_KEY``);
  clients that cannot hold a socket read ``GET .../chat`` every few seconds.
* **Takedown:** the creator (or staff) hides a message; it disappears from
  reads at once and a ``hide`` event removes it from open screens (well
  inside 60 s).
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import LIVE, OttChatMessage, OttLiveStream

MAX_LEN = 300
VIEWER_BUDGET = 20
VIEWER_WINDOW = timedelta(minutes=5)
STREAM_BUDGET = 600
STREAM_WINDOW = timedelta(minutes=1)
MAX_SLOW_MODE_S = 300
_LINK = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|co|app|xyz|ru|me)\b)", re.IGNORECASE)
Poster = Callable[[str, Mapping[str, Any], Mapping[str, str]], int]


class ChatError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def now() -> datetime:
    return datetime.now(timezone.utc)


def topic(stream_id: str) -> str:
    return f"ott-live:{stream_id}"


def _blocked_words() -> list[str]:
    return [w.strip().lower() for w in (os.getenv("OTT_CHAT_BLOCKED_WORDS") or "").split(",") if w.strip()]


def clean(text: str) -> str:
    body = " ".join(str(text or "").split())
    if not body:
        raise ChatError(400, "empty", "Type a message.")
    if len(body) > MAX_LEN:
        raise ChatError(400, "long", f"Messages are {MAX_LEN} characters at most.")
    if _LINK.search(body):
        raise ChatError(400, "link", "Links are not allowed in chat.")
    lowered = body.lower()
    if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _blocked_words()):
        raise ChatError(400, "blocked", "That message is not allowed here.")
    return body


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def post(session: Session, stream: OttLiveStream, viewer: Any, text: str, *, at: Optional[datetime] = None,
         broadcaster: Optional["Broadcaster"] = None) -> dict[str, Any]:
    moment = at or now()
    if stream.status != LIVE or not stream.chat_enabled:
        raise ChatError(409, "chat_off", "Chat is closed right now.")
    if viewer.channel_id != stream.channel_id:
        raise ChatError(401, "signed_out", "Sign in to this channel to chat.")
    if viewer.id in (stream.banned_viewer_ids or []):
        raise ChatError(403, "banned", "You cannot post in this chat.")
    body = clean(text)
    last = session.execute(select(func.max(OttChatMessage.created_at)).where(
        OttChatMessage.stream_id == stream.id, OttChatMessage.viewer_id == viewer.id)).scalar_one()
    if stream.slow_mode_s and last is not None:
        wait = int(stream.slow_mode_s - (moment - _aware(last)).total_seconds())
        if wait > 0:
            raise ChatError(429, "slow_mode", f"Slow mode is on. You can post again in {wait} s.")
    mine = session.execute(select(func.count(OttChatMessage.id)).where(
        OttChatMessage.stream_id == stream.id, OttChatMessage.viewer_id == viewer.id,
        OttChatMessage.created_at >= moment - VIEWER_WINDOW)).scalar_one()
    if mine >= VIEWER_BUDGET:
        raise ChatError(429, "viewer_budget", "You are posting a lot. Take a short break and try again.")
    total = session.execute(select(func.count(OttChatMessage.id)).where(
        OttChatMessage.stream_id == stream.id, OttChatMessage.created_at >= moment - STREAM_WINDOW)).scalar_one()
    if total >= STREAM_BUDGET:
        raise ChatError(429, "stream_budget", "Chat is very busy. Try again in a moment.")
    message = OttChatMessage(stream_id=stream.id, viewer_id=viewer.id,
                             display_name=(viewer.display_name or "viewer")[:60], body=body, created_at=moment)
    session.add(message)
    session.flush()
    view = message_view(message)
    (broadcaster or Broadcaster()).send(topic(stream.id), "chat", view)
    return view


def hide(session: Session, stream: OttLiveStream, message_id: str, *, reason: str = "creator",
         broadcaster: Optional["Broadcaster"] = None) -> dict[str, Any]:
    message = session.get(OttChatMessage, message_id)
    if message is None or message.stream_id != stream.id:
        raise ChatError(404, "not_found", "message not found")
    if message.hidden_at is None:
        message.hidden_at, message.hidden_reason = now(), reason[:16]
        session.flush()
        (broadcaster or Broadcaster()).send(topic(stream.id), "hide", {"id": message.id})
    return {"id": message.id, "hidden": True}


def ban(session: Session, stream: OttLiveStream, viewer_id: str, *, broadcaster: Optional["Broadcaster"] = None
        ) -> dict[str, Any]:
    stream.banned_viewer_ids = sorted({*(stream.banned_viewer_ids or []), viewer_id})
    hidden = session.execute(select(OttChatMessage).where(OttChatMessage.stream_id == stream.id,
                                                          OttChatMessage.viewer_id == viewer_id,
                                                          OttChatMessage.hidden_at.is_(None))).scalars().all()
    for message in hidden:
        hide(session, stream, message.id, reason="ban", broadcaster=broadcaster)
    session.flush()
    return {"banned": viewer_id, "hidden": len(hidden)}


def set_rules(session: Session, stream: OttLiveStream, body: Mapping[str, Any]) -> None:
    if body.get("slow_mode_s") is not None:
        value = int(body["slow_mode_s"])
        if not 0 <= value <= MAX_SLOW_MODE_S:
            raise ChatError(400, "slow_mode", f"slow mode is 0 to {MAX_SLOW_MODE_S} seconds")
        stream.slow_mode_s = value
    if body.get("chat_enabled") is not None:
        stream.chat_enabled = bool(body["chat_enabled"])
    session.flush()


def message_view(message: OttChatMessage) -> dict[str, Any]:
    return {"id": message.id, "name": message.display_name, "body": message.body,
            "at": _aware(message.created_at).isoformat() if message.created_at else None}


def recent(session: Session, stream: OttLiveStream, *, after: Optional[datetime] = None, limit: int = 50
           ) -> list[dict[str, Any]]:
    query = select(OttChatMessage).where(OttChatMessage.stream_id == stream.id, OttChatMessage.hidden_at.is_(None))
    if after is not None:
        query = query.where(OttChatMessage.created_at > after)
    rows = session.execute(query.order_by(OttChatMessage.created_at.desc()).limit(limit)).scalars().all()
    return [message_view(m) for m in reversed(rows)]


# --------------------------------------------------------------------------- #
# Scribase Realtime broadcast
# --------------------------------------------------------------------------- #
def _post(url: str, body: Mapping[str, Any], headers: Mapping[str, str]) -> int:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310 - configured Scribase URL
        return int(response.status)


class Broadcaster:
    """``POST {SCRIBASE_REALTIME_URL}/api/broadcast`` with the service key; failures are logged, never raised."""

    def __init__(self, env: Optional[Mapping[str, str]] = None, poster: Optional[Poster] = None) -> None:
        env = env if env is not None else os.environ
        self.url = (env.get("SCRIBASE_REALTIME_URL") or "").rstrip("/")
        self.key = (env.get("SCRIBASE_SERVICE_KEY") or "").strip()
        self.poster = poster or _post

    def send(self, topic_name: str, event: str, payload: Mapping[str, Any]) -> bool:
        if not (self.url and self.key):
            return False
        body = {"messages": [{"topic": topic_name, "event": event, "payload": dict(payload), "private": False}]}
        try:
            status = self.poster(f"{self.url}/api/broadcast", body,
                                 {"apikey": self.key, "Authorization": f"Bearer {self.key}"})
            return 200 <= status < 300
        except Exception as exc:  # noqa: BLE001 - readers fall back to polling
            logger.warning(f"ott chat: broadcast failed: {type(exc).__name__}")
            return False


__all__ = ["Broadcaster", "ChatError", "MAX_LEN", "STREAM_BUDGET", "VIEWER_BUDGET", "ban", "clean", "hide", "post",
           "recent", "set_rules", "topic"]
