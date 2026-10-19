"""Playback tokens (MV5 tier 1): HMAC-SHA256 signed, bound to one title and one playback session.

A token expires in 10 minutes or less (``MAX_TTL_S``); the player asks for a new
one to keep watching. It rides in the stream URL path, so a copied manifest or
segment link stops working when it expires. The secret is ``OTT_PLAYBACK_SECRET``
(32+ characters); without it no token is issued (fail closed).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

SECRET_ENV = "OTT_PLAYBACK_SECRET"
MAX_TTL_S = 600
DEFAULT_TTL_S = 600


class TokenError(Exception):
    pass


@dataclass(frozen=True)
class Grant:
    title_id: str
    session_id: str
    viewer: str
    country: str
    exp: int


def _secret() -> bytes:
    value = (os.getenv(SECRET_ENV) or "").strip()
    if len(value) < 32:
        raise TokenError("playback tokens are not configured")
    return value.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


#: Server-to-server grants (the FAST playout engine, PM3.4) may live up to 6 hours: the engine loads a
#: title's playlist once and its viewers follow the rewritten segment links for the whole title.
ENGINE_MAX_TTL_S = 6 * 3600


def issue(title_id: str, viewer: str, country: str, *, ttl_s: int = DEFAULT_TTL_S, now: float | None = None,
          session_id: str | None = None, max_ttl_s: int = MAX_TTL_S) -> tuple[str, Grant]:
    ttl = max(30, min(int(ttl_s), min(int(max_ttl_s), ENGINE_MAX_TTL_S)))
    grant = Grant(title_id=title_id, session_id=session_id or secrets.token_urlsafe(12), viewer=viewer,
                  country=country, exp=int((now or time.time()) + ttl))
    body = _b64(json.dumps(grant.__dict__, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", grant


def verify(token: str, *, title_id: str | None = None, now: float | None = None) -> Grant:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise TokenError("bad signature")
    try:
        grant = Grant(**json.loads(_unb64(body)))
    except (ValueError, TypeError) as exc:
        raise TokenError("malformed token") from exc
    if grant.exp < int(now or time.time()):
        raise TokenError("token expired")
    if title_id is not None and grant.title_id != title_id:
        raise TokenError("token is for another title")
    return grant


__all__ = ["DEFAULT_TTL_S", "ENGINE_MAX_TTL_S", "Grant", "MAX_TTL_S", "SECRET_ENV", "TokenError", "issue", "verify"]
