"""TikTok Content Posting API adapter (PULL_FROM_URL) — mirror of ``src/tiktok/client.ts``.

Real request shapes; the token is injected per call. No native scheduling → the
ReelForge queue owns it. Sibling of the backend ``publishing/connectors/tiktok.py``.
"""

from __future__ import annotations

from .caps import caps_for
from .http import HttpFn, HttpOptions, http_json
from .publisher import AnalyticsSnapshot, PublishRequest, PublishResult, TokenRefresh

_BASE = "https://open.tiktokapis.com/v2"


class TikTokPublisher:
    platform = "tiktok"

    def __init__(self, http: HttpFn = http_json) -> None:
        self._http = http

    def caps(self) -> dict:
        return caps_for("tiktok") or {}

    def schedule_supported(self) -> bool:
        return False  # no native scheduling → ReelForge queue

    def publish(self, req: PublishRequest, token: str) -> PublishResult:
        body = {
            "post_info": {
                "title": req.caption[: self.caps()["caption_max"]],
                "privacy_level": "SELF_ONLY",
                "disable_comment": False,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": req.video_url,
            },
        }
        res = self._http(
            f"{_BASE}/post/publish/video/init/",
            HttpOptions(method="POST", body=body, token=token),
        )
        publish_id = res["data"]["publish_id"]
        return PublishResult(
            platform="tiktok",
            post_id=publish_id,
            url=f"https://www.tiktok.com/@me/video/{publish_id}",
        )

    def refresh(self, refresh_token: str) -> TokenRefresh:
        res = self._http(
            f"{_BASE}/oauth/token/",
            HttpOptions(
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body={"grant_type": "refresh_token", "refresh_token": refresh_token},
            ),
        )
        return TokenRefresh(access_token=res["access_token"], expires_in=res["expires_in"])

    def fetch_analytics(self, post_id: str, token: str) -> AnalyticsSnapshot:
        res = self._http(
            f"{_BASE}/video/query/?fields=view_count,average_watch_time",
            HttpOptions(method="POST", body={"filters": {"video_ids": [post_id]}}, token=token),
        )
        videos = res["data"]["videos"]
        v = videos[0] if videos else {}
        return AnalyticsSnapshot(
            platform="tiktok",
            views=v.get("view_count", 0),
            watch_time_s=v.get("average_watch_time", 0),
            retention_pct=0,
        )
