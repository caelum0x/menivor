"""YouTube Data API adapter — resumable upload init + Shorts metadata.

Mirror of ``src/youtube/client.ts``. The resumable ``PUT`` of the bytes is done
by the API layer (streams from R2); this returns the request shapes. Sibling of
the backend ``publishing/connectors/youtube.py``.
"""

from __future__ import annotations

from .caps import caps_for
from .http import HttpFn, HttpOptions, encode_uri_component, http_json
from .publisher import AnalyticsSnapshot, PublishRequest, PublishResult, TokenRefresh

_API = "https://www.googleapis.com/youtube/v3"
_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"


class YouTubePublisher:
    platform = "youtube"

    def __init__(self, http: HttpFn = http_json) -> None:
        self._http = http

    def caps(self) -> dict:
        return caps_for("youtube") or {}

    def schedule_supported(self) -> bool:
        return True  # publishAt

    def publish(self, req: PublishRequest, token: str) -> PublishResult:
        snippet = {
            "snippet": {
                "title": req.caption[: self.caps()["caption_max"]] or "Short",
                "categoryId": "22",
            },
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
        }
        # Real init returns the resumable session in the Location header; the API
        # layer PUTs the bytes there. We return the inserted resource once complete.
        res = self._http(
            f"{_UPLOAD}?uploadType=resumable&part=snippet,status",
            HttpOptions(
                method="POST",
                token=token,
                headers={"X-Upload-Content-Type": "video/mp4"},
                body=snippet,
            ),
        )
        return PublishResult(
            platform="youtube", post_id=res["id"], url=f"https://youtube.com/shorts/{res['id']}"
        )

    def refresh(self, refresh_token: str) -> TokenRefresh:
        res = self._http(
            "https://oauth2.googleapis.com/token",
            HttpOptions(
                method="POST",
                body={"grant_type": "refresh_token", "refresh_token": refresh_token},
            ),
        )
        return TokenRefresh(access_token=res["access_token"], expires_in=res["expires_in"])

    def fetch_analytics(self, post_id: str, token: str) -> AnalyticsSnapshot:
        res = self._http(
            f"{_API}/videos?part=statistics&id={encode_uri_component(post_id)}",
            HttpOptions(token=token),
        )
        items = res.get("items") or []
        view_count = items[0]["statistics"].get("viewCount", 0) if items else 0
        return AnalyticsSnapshot(
            platform="youtube", views=int(view_count), watch_time_s=0, retention_pct=0
        )
