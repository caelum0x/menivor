"""Sign in on a TV with a phone (MV9): the TV shows a short code, the phone approves it.

1. The TV asks for a code (``start``): a human code like ``K7M-4QX`` and a
   private device token; both live 10 minutes in Redis (no table).
2. On the phone, the viewer signs in to the same channel and types the code
   (``approve``). The code is bound to that viewer.
3. The TV polls with its device token (``poll``) every 5 s and receives its
   own channel session (device ``tv``) once, then the code is gone.

Codes use an alphabet without look-alike characters; a wrong code is refused
without saying whether it exists on another channel.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any, Optional, Protocol

from sqlalchemy.orm import Session

from . import session as viewer_session
from .models import OttViewer

TTL_S = 600
POLL_INTERVAL_S = 5
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class CodeError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class Store(Protocol):
    def put(self, key: str, value: dict, ttl: int) -> None: ...
    def get(self, key: str) -> Optional[dict]: ...
    def delete(self, key: str) -> None: ...


class RedisStore:
    def __init__(self, client: Any = None) -> None:
        self._client = client

    def _redis(self) -> Any:
        if self._client is None:
            from app.services.billing.service import _get_redis

            self._client = _get_redis()
        return self._client

    def put(self, key: str, value: dict, ttl: int) -> None:
        self._redis().set(key, json.dumps(value), ex=ttl)

    def get(self, key: str) -> Optional[dict]:
        raw = self._redis().get(key)
        return json.loads(raw) if raw else None

    def delete(self, key: str) -> None:
        self._redis().delete(key)


class MemoryStore:
    def __init__(self) -> None:
        self.items: dict[str, tuple[float, dict]] = {}

    def put(self, key: str, value: dict, ttl: int) -> None:
        self.items[key] = (time.time() + ttl, dict(value))

    def get(self, key: str) -> Optional[dict]:
        item = self.items.get(key)
        if item is None or item[0] < time.time():
            self.items.pop(key, None)
            return None
        return dict(item[1])

    def delete(self, key: str) -> None:
        self.items.pop(key, None)


_STORE: Optional[Store] = None


def store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = RedisStore()
    return _STORE


def set_store(new: Optional[Store]) -> None:
    global _STORE
    _STORE = new


def _normalise(user_code: str) -> str:
    return "".join(ch for ch in str(user_code or "").upper() if ch in ALPHABET)


def _code_key(channel_id: str, user_code: str) -> str:
    return f"ott:tvcode:{channel_id}:{_normalise(user_code)}"


def _device_key(device_token: str) -> str:
    return f"ott:tvdevice:{hashlib.sha256(device_token.encode()).hexdigest()}"


def start(channel_id: str) -> dict[str, Any]:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(6))
    device_token = secrets.token_urlsafe(32)
    record = {"channel_id": channel_id, "user_code": raw, "viewer_id": None}
    store().put(_code_key(channel_id, raw), {"device": _device_key(device_token)}, TTL_S)
    store().put(_device_key(device_token), record, TTL_S)
    return {"user_code": f"{raw[:3]}-{raw[3:]}", "device_token": device_token, "expires_in": TTL_S,
            "interval": POLL_INTERVAL_S}


def approve(viewer: OttViewer, user_code: str) -> dict[str, Any]:
    pointer = store().get(_code_key(viewer.channel_id, user_code))
    if pointer is None:
        raise CodeError(404, "code", "That code did not work. Check the TV and try again.")
    record = store().get(pointer["device"])
    if record is None or record.get("channel_id") != viewer.channel_id:
        raise CodeError(404, "code", "That code did not work. Check the TV and try again.")
    record["viewer_id"] = viewer.id
    store().put(pointer["device"], record, TTL_S)
    store().delete(_code_key(viewer.channel_id, user_code))
    return {"approved": True}


def poll(session: Session, channel_id: str, device_token: str) -> dict[str, Any]:
    key = _device_key(str(device_token or ""))
    record = store().get(key)
    if record is None or record.get("channel_id") != channel_id:
        raise CodeError(410, "expired", "This code expired. Show a new one on the TV.")
    if not record.get("viewer_id"):
        raise CodeError(428, "pending", "Waiting for your phone.")
    viewer = session.get(OttViewer, record["viewer_id"])
    store().delete(key)
    if viewer is None or viewer.channel_id != channel_id:
        raise CodeError(410, "expired", "This code expired. Show a new one on the TV.")
    token, exp = viewer_session.issue(viewer)
    return {"session": token, "expires_at": exp, "viewer": {"id": viewer.id, "display_name": viewer.display_name}}


__all__ = ["ALPHABET", "CodeError", "MemoryStore", "POLL_INTERVAL_S", "RedisStore", "TTL_S", "approve", "poll",
           "set_store", "start", "store"]
