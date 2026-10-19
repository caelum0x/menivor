"""Instagram Graph API adapter — 2-step Reels publish (mirror of ``src/instagram/client.ts``).

Token injected per call as ``f"{ig_user_id}:{access_token}"``. Sibling of the
backend ``publishing/connectors/instagram.py``.
"""

from __future__ import annotations

from .caps import caps_for
from .http import HttpFn, HttpOptions, encode_uri_component, http_json
from .publisher import AnalyticsSnapshot, PublishRequest, PublishResult, TokenRefresh

_GRAPH = "https://graph.facebook.com/v19.0"


class InstagramPublisher:
    platform = "instagram"

    def __init__(self, http: HttpFn = http_json) -> None:
        self._http = http

    def caps(self) -> dict:
        return caps_for("instagram") or {}

    def schedule_supported(self) -> bool:
        return False

    def publish(self, req: PublishRequest, token: str) -> PublishResult:
        ig_user_id, access_token = token.split(":", 1)
        # 1) create a REELS media container
        container = self._http(
            f"{_GRAPH}/{ig_user_id}/media",
            HttpOptions(
                method="POST",
                token=access_token,
                body={
                    "media_type": "REELS",
                    "video_url": req.video_url,
                    "caption": req.caption[: self.caps()["caption_max"]],
                },
            ),
        )
        # 2) publish it (production should poll container status first)
        published = self._http(
            f"{_GRAPH}/{ig_user_id}/media_publish",
            HttpOptions(method="POST", token=access_token, body={"creation_id": container["id"]}),
        )
        return PublishResult(
            platform="instagram",
            post_id=published["id"],
            url=f"https://www.instagram.com/reel/{published['id']}/",
        )

    def refresh(self, refresh_token: str) -> TokenRefresh:
        # IG uses long-lived-token refresh; refresh_token IS the long-lived token.
        res = self._http(
            f"{_GRAPH}/refresh_access_token?grant_type=ig_refresh_token"
            f"&access_token={encode_uri_component(refresh_token)}",
        )
        return TokenRefresh(access_token=res["access_token"], expires_in=res["expires_in"])

    def fetch_analytics(self, post_id: str, token: str) -> AnalyticsSnapshot:
        _, access_token = token.split(":", 1)
        res = self._http(
            f"{_GRAPH}/{post_id}/insights?metric=plays,reach",
            HttpOptions(token=access_token),
        )
        plays = _metric_value(res.get("data", []), "plays")
        return AnalyticsSnapshot(platform="instagram", views=plays, watch_time_s=0, retention_pct=0)


def _metric_value(data: list, name: str) -> int:
    for metric in data:
        if metric.get("name") == name:
            values = metric.get("values") or []
            return values[0].get("value", 0) if values else 0
    return 0
