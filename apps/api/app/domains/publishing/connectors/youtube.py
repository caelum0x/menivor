"""YouTube Data API v3 connector — resumable video upload (Shorts).

Two real steps (https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol):

1. **Init** — ``POST https://www.googleapis.com/upload/youtube/v3/videos``
   ``?uploadType=resumable&part=snippet,status`` with the snippet/status JSON and
   a ``Bearer`` access token; the API returns the upload session URL in the
   ``Location`` response header.
2. **Upload** — ``PUT`` the MP4 bytes to that session URL; the response body is
   the created video resource (``id`` → ``https://youtube.com/shorts/<id>``).

A ``#Shorts`` tag + a ≤60s vertical video make it a Short. Byte upload uses the
local ``video_path``; the transport is the injectable network boundary.
"""

from __future__ import annotations

from .base import (
    PublishConnector,
    PublishError,
    PublishRequest,
    PublishResult,
    Transport,
    _ok,
    _safe_json,
    register_connector,
)

_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_MAX_TITLE = 100


class YouTubeConnector(PublishConnector):
    platform = "youtube"

    def publish(self, req: PublishRequest, *, transport: Transport) -> PublishResult:
        if not req.access_token:
            raise PublishError(self.platform, "missing OAuth access token")
        body = self._snippet_status(req)

        init = transport.request(
            "POST",
            _UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {req.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
            },
            json=body,
        )
        if not _ok(init):
            raise PublishError(
                self.platform,
                f"resumable init failed (HTTP {init.status_code}): {_safe_json(init)}",
                retryable=int(getattr(init, "status_code", 0)) >= 500,
            )
        session_url = _location(init)
        if not session_url:
            raise PublishError(self.platform, "resumable init returned no upload Location")

        payload = self._read_bytes(req)
        put = transport.request(
            "PUT",
            session_url,
            headers={"Authorization": f"Bearer {req.access_token}", "Content-Type": "video/mp4"},
            data=payload,
        )
        if not _ok(put):
            raise PublishError(
                self.platform,
                f"upload failed (HTTP {put.status_code}): {_safe_json(put)}",
                retryable=int(getattr(put, "status_code", 0)) >= 500,
            )
        data = _safe_json(put)
        vid = str(data.get("id") or "")
        if not vid:
            raise PublishError(self.platform, f"upload returned no video id: {data}")
        return PublishResult(
            platform=self.platform,
            status="published",
            external_id=vid,
            url=f"https://youtube.com/shorts/{vid}",
            raw=data,
        )

    def _snippet_status(self, req: PublishRequest) -> dict:
        title = (req.title or req.caption or "New Short")[:_MAX_TITLE]
        description = req.description or req.caption_with_tags()
        # Ensure a #Shorts signal is present in the description.
        if "#shorts" not in description.lower():
            description = (description + "\n#Shorts").strip()
        tags = [t.lstrip("#") for t in req.hashtags if t]
        return {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": str(req.extra.get("category_id", "22")),  # People & Blogs
            },
            "status": {
                "privacyStatus": _privacy(req.privacy),
                "selfDeclaredMadeForKids": bool(req.extra.get("made_for_kids", False)),
                # MN5: YouTube's altered or synthetic content disclosure.
                "containsSyntheticMedia": bool(req.extra.get("ai_generated", True)),
            },
        }

    @staticmethod
    def _read_bytes(req: PublishRequest) -> bytes:
        if not req.video_path:
            raise PublishError("youtube", "YouTube upload requires a local video_path")
        try:
            with open(req.video_path, "rb") as fh:
                return fh.read()
        except OSError as exc:
            raise PublishError("youtube", f"cannot read video_path: {exc}") from exc


def _privacy(value: str) -> str:
    v = str(value or "").strip().lower()
    return v if v in ("public", "unlisted", "private") else "public"


def _location(resp) -> str:
    headers = getattr(resp, "headers", None) or {}
    try:
        return headers.get("Location") or headers.get("location") or ""
    except AttributeError:
        return ""


register_connector(YouTubeConnector())
