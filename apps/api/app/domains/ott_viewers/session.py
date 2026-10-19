"""Channel viewer sessions (MV6): an HMAC-signed token bound to one viewer of one channel.

The token rides in the ``X-OTT-Viewer`` header (never a cookie, never in page
HTML). It carries the viewer id, the channel id, the viewer's session version
and an expiry (30 days). A token is refused when the signature, channel,
version or expiry does not match, or when the viewer was deleted. The secret is
``OTT_VIEWER_SESSION_SECRET`` (32+ characters); without it no session is issued.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from .models import OttViewer

SECRET_ENV = "OTT_VIEWER_SESSION_SECRET"
HEADER = "x-ott-viewer"
TTL_S = 30 * 24 * 3600


class SessionRefused(Exception):
    pass


@dataclass(frozen=True)
class ViewerClaims:
    viewer_id: str
    channel_id: str
    version: int
    exp: int


def _secret() -> bytes:
    value = (os.getenv(SECRET_ENV) or "").strip()
    if len(value) < 32:
        raise SessionRefused("viewer sessions are not configured")
    return value.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(viewer: OttViewer, *, now: Optional[float] = None) -> tuple[str, int]:
    exp = int((now or time.time()) + TTL_S)
    body = _b64(json.dumps({"v": viewer.id, "c": viewer.channel_id, "n": int(viewer.session_version), "e": exp},
                           separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", exp


def decode(token: str, *, now: Optional[float] = None) -> ViewerClaims:
    try:
        body, sig = str(token or "").split(".", 1)
    except ValueError as exc:
        raise SessionRefused("malformed session") from exc
    expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise SessionRefused("bad session")
    try:
        data = json.loads(_unb64(body))
        claims = ViewerClaims(viewer_id=str(data["v"]), channel_id=str(data["c"]), version=int(data["n"]),
                              exp=int(data["e"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise SessionRefused("malformed session") from exc
    if claims.exp < int(now or time.time()):
        raise SessionRefused("session expired")
    return claims


def viewer_for(session: Session, token: str, *, channel_id: Optional[str] = None,
               now: Optional[float] = None) -> OttViewer:
    """The live viewer behind ``token``; ``channel_id`` pins it to one channel."""
    claims = decode(token, now=now)
    if channel_id is not None and claims.channel_id != channel_id:
        raise SessionRefused("this session belongs to another channel")
    viewer = session.get(OttViewer, claims.viewer_id)
    if viewer is None or viewer.channel_id != claims.channel_id or int(viewer.session_version) != claims.version:
        raise SessionRefused("signed out")
    return viewer


def from_request(session: Session, request: Any) -> Optional[OttViewer]:
    """The viewer of a request carrying ``X-OTT-Viewer``, else ``None`` (a bad token is ignored)."""
    token = request.headers.get(HEADER) if request is not None else None
    if not token:
        return None
    try:
        return viewer_for(session, token)
    except SessionRefused:
        return None


__all__ = ["HEADER", "SECRET_ENV", "SessionRefused", "TTL_S", "ViewerClaims", "decode", "from_request", "issue",
           "viewer_for"]
