"""TikTok Content Posting API v2: creator info, Direct Post, upload to inbox, status.

Docs: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post

* ``creator_info`` must be queried before each post: it says which privacy
  levels the creator may use, whether comments/duet/stitch are switched off for
  them, the longest video they may post, and the nickname the UI must show.
* Direct Post (``video.publish`` scope) goes live; ``post_info.is_aigc`` sets
  TikTok's own "AI-generated" label. Upload to inbox (``video.upload``) sends a
  draft the creator finishes in the TikTok app (no caption/label fields there).
* Video source: ``FILE_UPLOAD`` (bytes, chunked; no domain verification) or
  ``PULL_FROM_URL`` (TikTok fetches a URL on a domain verified in the developer
  portal).
"""

from __future__ import annotations

import math
import os

from .base import (
    AuthError,
    ClientError,
    PostSpec,
    PublishOutcome,
    RateLimited,
    Transport,
    body_of,
    is_ok,
    require_platform_url,
)

API = "https://open.tiktokapis.com"
CREATOR_INFO_URL = f"{API}/v2/post/publish/creator_info/query/"
DIRECT_INIT_URL = f"{API}/v2/post/publish/video/init/"
INBOX_INIT_URL = f"{API}/v2/post/publish/inbox/video/init/"
STATUS_URL = f"{API}/v2/post/publish/status/fetch/"
MAX_CAPTION = 2200
# FILE_UPLOAD chunk rules: a single chunk up to 64 MB; else >= 5 MB chunks, the
# last chunk taking the remainder (up to 128 MB).
_SINGLE_CHUNK_MAX = 64 * 1024 * 1024
_CHUNK = 10 * 1024 * 1024

# Hosts TikTok hands out upload URLs on (open-upload.tiktokapis.com today).
UPLOAD_HOSTS = ("tiktokapis.com",)

_VISIBILITY = {
    "public": "PUBLIC_TO_EVERYONE",
    "friends": "MUTUAL_FOLLOW_FRIENDS",
    "followers": "FOLLOWER_OF_CREATOR",
    "private": "SELF_ONLY",
}
_AUTH_CODES = {"access_token_invalid", "scope_not_authorized", "scope_permission_missed", "token_not_authorized"}
_RATE_CODES = {"rate_limit_exceeded", "spam_risk_too_many_posts", "spam_risk_too_many_pending_share"}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}


def _raise_for(resp, what: str) -> dict:
    body = body_of(resp)
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = str(err.get("code") or "").lower()
    message = str(err.get("message") or "") or f"HTTP {getattr(resp, 'status_code', 0)}"
    status = int(getattr(resp, "status_code", 0) or 0)
    if is_ok(resp) and code in ("", "ok"):
        return body
    if code in _AUTH_CODES or status == 401:
        raise AuthError("tiktok", f"TikTok rejected the connection during {what}: {message}", code=code)
    if code in _RATE_CODES or status == 429:
        raise RateLimited("tiktok", f"TikTok posting limit reached during {what}: {message}",
                          retry_after_s=3600 if code.startswith("spam_risk") else 60, code=code)
    raise ClientError("tiktok", f"TikTok {what} failed: {message}", retryable=status >= 500, code=code)


def creator_info(token: str, *, transport: Transport) -> dict:
    """Return the creator's posting options (nickname, privacy levels, toggles, max duration)."""
    resp = transport.request("POST", CREATOR_INFO_URL, headers=_headers(token), json={})
    data = _raise_for(resp, "creator info").get("data") or {}
    return {
        "nickname": str(data.get("creator_nickname") or ""),
        "username": str(data.get("creator_username") or ""),
        "avatar_url": str(data.get("creator_avatar_url") or ""),
        "privacy_level_options": [str(p) for p in (data.get("privacy_level_options") or [])],
        "comment_disabled": bool(data.get("comment_disabled", False)),
        "duet_disabled": bool(data.get("duet_disabled", False)),
        "stitch_disabled": bool(data.get("stitch_disabled", False)),
        "max_video_post_duration_sec": int(data.get("max_video_post_duration_sec") or 0),
    }


def privacy_level(visibility: str, options: list[str], *, audited: bool) -> str:
    """Map a visibility choice onto one of the creator's allowed TikTok levels.

    An unaudited app may only post ``SELF_ONLY``. A level the creator does not
    offer is an error (never silently widened).
    """
    wanted = "SELF_ONLY" if not audited else _VISIBILITY.get(str(visibility or "").lower(), "")
    if not wanted:
        raise ClientError("tiktok", f"unknown visibility {visibility!r}")
    if options and wanted not in options:
        raise ClientError("tiktok", f"this TikTok account does not allow {wanted} posts "
                                    f"(allowed: {', '.join(options)})", code="privacy_level_option_mismatch")
    return wanted


def _source_info(spec: PostSpec, source: str) -> tuple[dict, bytes | None]:
    if source == "url":
        if not spec.video_url:
            raise ClientError("tiktok", "PULL_FROM_URL needs a public video URL")
        return {"source": "PULL_FROM_URL", "video_url": spec.video_url}, None
    if not spec.video_path or not os.path.exists(spec.video_path):
        raise ClientError("tiktok", "FILE_UPLOAD needs the rendered video file", retryable=True)
    with open(spec.video_path, "rb") as fh:
        data = fh.read()
    size = len(data)
    if size == 0:
        raise ClientError("tiktok", "the rendered video file is empty")
    chunk = size if size <= _SINGLE_CHUNK_MAX else _CHUNK
    count = 1 if chunk == size else max(1, math.floor(size / chunk))
    return {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}, data


def _upload_chunks(upload_url: str, data: bytes, info: dict, transport: Transport) -> None:
    size, chunk, count = info["video_size"], info["chunk_size"], info["total_chunk_count"]
    for index in range(count):
        first = index * chunk
        last = size - 1 if index == count - 1 else first + chunk - 1
        part = data[first:last + 1]
        resp = transport.request(
            "PUT", upload_url,
            headers={"Content-Type": "video/mp4", "Content-Length": str(len(part)),
                     "Content-Range": f"bytes {first}-{last}/{size}"},
            data=part,
        )
        if not is_ok(resp):
            raise ClientError("tiktok", f"video upload chunk {index + 1}/{count} failed "
                                        f"(HTTP {getattr(resp, 'status_code', 0)})",
                              retryable=int(getattr(resp, "status_code", 0) or 0) >= 500)


def publish(token: str, spec: PostSpec, *, info: dict, audited: bool, source: str,
            transport: Transport) -> PublishOutcome:
    """Start a Direct Post or inbox upload. Returns ``processing`` with the publish_id."""
    source_info, data = _source_info(spec, source)
    if spec.tiktok_mode == "draft":
        url, body = INBOX_INIT_URL, {"source_info": source_info}
    else:
        post_info = {
            "title": spec.text(MAX_CAPTION),
            "privacy_level": privacy_level(spec.visibility, info.get("privacy_level_options") or [],
                                           audited=audited),
            # Interaction toggles: off unless the creator turned them on AND TikTok allows them.
            "disable_comment": (not spec.allow_comments) or bool(info.get("comment_disabled")),
            "disable_duet": (not spec.allow_duet) or bool(info.get("duet_disabled")),
            "disable_stitch": (not spec.allow_stitch) or bool(info.get("stitch_disabled")),
            "brand_content_toggle": bool(spec.brand_content),
            "brand_organic_toggle": bool(spec.brand_organic),
            "is_aigc": bool(spec.ai_generated),
        }
        url, body = DIRECT_INIT_URL, {"post_info": post_info, "source_info": source_info}
    resp = transport.request("POST", url, headers=_headers(token), json=body)
    payload = _raise_for(resp, "publish start").get("data") or {}
    publish_id = str(payload.get("publish_id") or "")
    if not publish_id:
        raise ClientError("tiktok", "TikTok returned no publish_id", retryable=True)
    if data is not None:
        upload_url = str(payload.get("upload_url") or "")
        if not upload_url:
            raise ClientError("tiktok", "TikTok returned no upload_url for the file upload", retryable=True)
        upload_url = require_platform_url("tiktok", upload_url, UPLOAD_HOSTS)
        _upload_chunks(upload_url, data, source_info, transport)
    return PublishOutcome(status="processing", ref=publish_id, provider_status="PROCESSING_UPLOAD",
                          raw={"publish_id": publish_id, "mode": spec.tiktok_mode})


def fetch_status(token: str, publish_id: str, *, transport: Transport) -> PublishOutcome:
    """Poll a publish_id. ``FAILED`` raises; ``PUBLISH_COMPLETE`` / ``SEND_TO_USER_INBOX`` resolve."""
    resp = transport.request("POST", STATUS_URL, headers=_headers(token), json={"publish_id": publish_id})
    data = _raise_for(resp, "status check").get("data") or {}
    status = str(data.get("status") or "PROCESSING_UPLOAD")
    if status == "FAILED":
        raise ClientError("tiktok", f"TikTok rejected the post: {data.get('fail_reason') or 'unknown reason'}",
                          code=str(data.get("fail_reason") or ""))
    post_ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
    post_id = str(post_ids[0]) if isinstance(post_ids, list) and post_ids else ""
    if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
        return PublishOutcome(status="published", ref=publish_id, external_id=post_id or publish_id,
                              url=post_url(post_id), provider_status=status, raw=data)
    return PublishOutcome(status="processing", ref=publish_id, provider_status=status, raw=data)


def post_url(post_id: str, handle: str = "") -> str:
    if not post_id:
        return ""
    return f"https://www.tiktok.com/@{handle}/video/{post_id}" if handle else f"https://www.tiktok.com/video/{post_id}"
