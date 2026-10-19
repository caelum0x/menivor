"""YouTube Data API v3: resumable ``videos.insert`` for Shorts.

Docs: https://developers.google.com/youtube/v3/docs/videos/insert

A vertical video of up to 3 minutes is classified as a Short by YouTube. The
synthetic-media disclosure is ``status.containsSyntheticMedia``; Menivor videos
always set it. ``selfDeclaredMadeForKids`` is always declared (false).
"""

from __future__ import annotations

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

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
MAX_TITLE = 100
MAX_DESCRIPTION = 5000
# The resumable session URL must stay on Google's API host (it receives the bearer token).
UPLOAD_HOSTS = ("googleapis.com",)
_PRIVACY = {"public": "public", "friends": "unlisted", "private": "private"}


def _raise_for(resp, what: str) -> dict:
    if is_ok(resp):
        return body_of(resp)
    body = body_of(resp)
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    reasons = {str(e.get("reason") or "") for e in (err.get("errors") or []) if isinstance(e, dict)}
    message = str(err.get("message") or f"HTTP {getattr(resp, 'status_code', 0)}")
    status = int(getattr(resp, "status_code", 0) or 0)
    if status == 401 or reasons & {"authError", "unauthorized"}:
        raise AuthError("youtube", f"YouTube rejected the connection during {what}: {message}")
    if reasons & {"quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}:
        raise RateLimited("youtube", f"YouTube upload limit reached during {what}: {message}",
                          retry_after_s=3600, code=",".join(sorted(reasons)))
    raise ClientError("youtube", f"YouTube {what} failed: {message}", retryable=status >= 500)


def metadata(spec: PostSpec, *, verified: bool) -> dict:
    title = (spec.title or spec.caption or "New video").strip().splitlines()[0][:MAX_TITLE]
    privacy = _PRIVACY.get(str(spec.visibility or "").lower(), "private") if verified else "private"
    return {
        "snippet": {
            "title": title,
            "description": spec.text(MAX_DESCRIPTION),
            "tags": [t.lstrip("#") for t in spec.hashtags if t][:30],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": bool(spec.ai_generated),
        },
    }


def publish(token: str, spec: PostSpec, *, verified: bool, transport: Transport) -> PublishOutcome:
    """Upload the file (resumable session, single PUT) and return the video id."""
    if not spec.video_path or not os.path.exists(spec.video_path):
        raise ClientError("youtube", "YouTube needs the rendered video file", retryable=True)
    with open(spec.video_path, "rb") as fh:
        data = fh.read()
    if not data:
        raise ClientError("youtube", "the rendered video file is empty")
    start = transport.request(
        "POST", UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(len(data))},
        json=metadata(spec, verified=verified),
    )
    _raise_for(start, "upload start")
    headers = getattr(start, "headers", {}) or {}
    session_url = str(headers.get("Location") or headers.get("location") or "")
    if not session_url:
        raise ClientError("youtube", "YouTube returned no upload session", retryable=True)
    session_url = require_platform_url("youtube", session_url, UPLOAD_HOSTS)
    put = transport.request("PUT", session_url,
                            headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4",
                                     "Content-Length": str(len(data))},
                            data=data)
    body = _raise_for(put, "upload")
    video_id = str(body.get("id") or "")
    if not video_id:
        raise ClientError("youtube", "YouTube returned no video id", retryable=True)
    upload_status = str((body.get("status") or {}).get("uploadStatus") or "uploaded")
    return PublishOutcome(status="processing", ref=video_id, external_id=video_id,
                          url=f"https://www.youtube.com/shorts/{video_id}", provider_status=upload_status)


def fetch_status(token: str, video_id: str, *, transport: Transport) -> PublishOutcome:
    """``processed`` -> published; ``failed`` / ``rejected`` raise; else still processing."""
    resp = transport.request("GET", VIDEOS_URL, params={"part": "status,processingDetails", "id": video_id},
                             headers={"Authorization": f"Bearer {token}"})
    items = _raise_for(resp, "status check").get("items") or []
    if not items:
        raise ClientError("youtube", "the uploaded video is no longer on the channel")
    status = items[0].get("status") or {}
    upload = str(status.get("uploadStatus") or "uploaded")
    if upload in ("failed", "rejected", "deleted"):
        reason = status.get("rejectionReason") or status.get("failureReason") or upload
        raise ClientError("youtube", f"YouTube did not accept the video ({reason})")
    url = f"https://www.youtube.com/shorts/{video_id}"
    if upload == "processed":
        return PublishOutcome(status="published", ref=video_id, external_id=video_id, url=url,
                              provider_status=upload)
    return PublishOutcome(status="processing", ref=video_id, external_id=video_id, url=url, provider_status=upload)
