"""Playback (MV5 tier 1): start a stream, serve tokenized manifests, redirect segments.

* ``start``: the title is watchable, the viewer's country is allowed (a clear
  451 message otherwise), a paid title needs access tier 1 live plus access
  (the channel owner until viewer purchases land in MV13), and the viewer has
  fewer than the plan's live streams (a third stream on a two-stream plan is
  refused). Returns a manifest URL carrying a token that expires in 10 min.
* ``manifest``: the stored playlist or MPD for the token's title; HLS key tags
  point at the key server with the token. Relative segment URIs resolve under
  the same tokenized path.
* ``segment_url``: a presigned R2 URL that lives no longer than the token.
No key or token is ever written into page HTML; the player fetches them.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import time
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.domains.ott import catalog_public, flags
from app.domains.ott.models import OttChannel, OttTitle

from . import geo, limits, tokens

STREAM_PATH = "/api/v1/ott/stream/{token}/{path}"
KEY_PATH = "/api/v1/ott/keys/{title_id}"
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_./-]{1,200}$")
MANIFEST_SUFFIXES = (".m3u8", ".mpd")


class AccessError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def client_fingerprint(request: Any) -> str:
    raw = request.headers.get("cf-connecting-ip") or getattr(getattr(request, "client", None), "host", "") or ""
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _api_base() -> str:
    from app.domains.ott.feeds import api_base

    return api_base()


def has_access(session: Session, title: OttTitle, viewer_user_id: str | None,
               viewer_account_id: str | None = None) -> bool:
    if title.access_tier == "free":
        return True
    if not flags.enabled("access"):
        return False
    if flags.enabled("commerce"):
        # Wave P PM3.2 (MV13): the owner, or a channel viewer with a live purchase or subscription.
        from app.domains.ott_commerce import entitlements

        return entitlements.can_watch(session, title, viewer_id=viewer_account_id, user_id=viewer_user_id)
    if not viewer_user_id:
        return False
    channel = session.get(OttChannel, title.channel_id)
    return channel is not None and str(channel.user_id) == str(viewer_user_id)


def start(session: Session, title: OttTitle, *, viewer: str, country: str, viewer_user_id: str | None = None,
          session_id: str | None = None, limit_backend: Any = None, now: float | None = None,
          viewer_account_id: str | None = None) -> dict[str, Any]:
    if not catalog_public.watchable(session, title):
        raise AccessError(404, "not_found", "title not found")
    if not geo.allowed(title.geo_mode, title.geo_countries or [], country):
        raise AccessError(451, "geo_blocked", geo.MESSAGE)
    if not has_access(session, title, viewer_user_id, viewer_account_id):
        raise AccessError(402, "members_only", "This title is for members of the channel.")
    try:
        token, grant = tokens.issue(title.id, viewer, country, now=now, session_id=session_id)
    except tokens.TokenError as exc:
        raise AccessError(503, "playback_off", "Playback is not available right now.") from exc
    if not limits.admit(viewer, grant.session_id, now=now, backend=limit_backend):
        raise AccessError(429, "too_many_streams",
                          f"You are already watching on {limits.max_streams()} screens. Stop one to watch here.")
    base = _api_base()
    manifest = STREAM_PATH.format(token=token, path="master.m3u8")
    view = {"manifest_url": f"{base}{manifest}", "expires_at": grant.exp, "session_id": grant.session_id,
            "protected": title.access_tier != "free"}
    if title.access_tier == "free":
        view["dash_url"] = f"{base}{STREAM_PATH.format(token=token, path='manifest.mpd')}"
    else:
        view["viewer_mark"] = viewer_mark(viewer)
    return view


def viewer_mark(viewer: str) -> str:
    """Wave Q QM1.5 (U17): the short code the player shows over a paid title.

    It is the start of the salted viewer hash the QoE analytics already use, so
    a screen recording that shows it can be traced back to the viewer by the
    operator, while the code itself says nothing about who they are.
    """
    from app.domains.ott_analytics.service import viewer_hash

    return viewer_hash(viewer)[:8].upper()


def _grant_title(session: Session, token: str) -> tuple[tokens.Grant, OttTitle]:
    try:
        grant = tokens.verify(token)
    except tokens.TokenError as exc:
        raise AccessError(403, "token", "This link has expired. Open the title again to keep watching.") from exc
    title = session.get(OttTitle, grant.title_id)
    if not catalog_public.watchable(session, title):
        raise AccessError(404, "not_found", "title not found")
    limits.renew(grant.viewer, grant.session_id)
    return grant, title


def _object_key(title: OttTitle, path: str) -> str:
    clean = posixpath.normpath(path)
    if not _SAFE_PATH.match(path) or clean.startswith("..") or clean.startswith("/"):
        raise AccessError(400, "path", "bad path")
    prefix = title.manifest_key.rsplit("/", 1)[0]
    return f"{prefix}/{clean}"


_KEY_TAG = re.compile(r'(#EXT-X-KEY:[^\n]*URI=")([^"]*)(")')


_KV = re.compile(r"[?&]kv=(\d{1,6})")


def rewrite_playlist(text: str, *, title_id: str, token: str, base: str) -> str:
    key_url = f"{base}{KEY_PATH.format(title_id=title_id)}?t={token}"

    def _sub(m: "re.Match[str]") -> str:
        # QM1.2 (P-M7): keep the key version the packager wrote, so a stale segment set is refused.
        kv = _KV.search(m.group(2))
        return f"{m.group(1)}{key_url}{f'&kv={kv.group(1)}' if kv else ''}{m.group(3)}"

    return _KEY_TAG.sub(_sub, text)


def manifest(session: Session, token: str, path: str, read: Callable[[str], bytes]) -> tuple[bytes, str]:
    grant, title = _grant_title(session, token)
    if not path.endswith(MANIFEST_SUFFIXES):
        raise AccessError(400, "path", "not a manifest")
    if path.endswith(".mpd") and title.access_tier != "free":
        raise AccessError(404, "not_found", "no DASH manifest for protected titles")
    body = read(_object_key(title, path))
    if path.endswith(".m3u8"):
        text = rewrite_playlist(body.decode("utf-8"), title_id=title.id, token=token, base=_api_base())
        return text.encode("utf-8"), "application/vnd.apple.mpegurl"
    del grant
    return body, "application/dash+xml"


def segment_url(session: Session, token: str, path: str, presign: Callable[[str, int], str],
                *, now: float | None = None, client: str = "") -> str:
    grant, title = _grant_title(session, token)
    remaining = int(grant.exp - (now or time.time()))
    url = presign(_object_key(title, path), max(5, min(remaining, tokens.MAX_TTL_S)))
    if not path.endswith((".vtt", ".jpg", "init.mp4")):
        from app.services.billing import ott_usage  # Wave P PM3.1 (MV7): minutes delivered

        # Verifier fix: one segment counts once per grant session and client, so replaying a
        # segment URL cannot inflate the creator's billed minutes.
        if ott_usage.first_delivery(grant.session_id, path, client, ttl_s=max(60, remaining + 60)):
            ott_usage.count_delivered(title.channel_id, ott_usage.SEGMENT_S, now=now)
    return url


def source_url(title: OttTitle) -> str:
    from app.services.ott_transcode.router import SourceStorage

    return SourceStorage().presign_get(title.source_key, 600)


__all__ = ["AccessError", "KEY_PATH", "STREAM_PATH", "client_fingerprint", "has_access", "manifest",
           "rewrite_playlist", "segment_url", "source_url", "start"]
