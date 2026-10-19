"""X (Twitter) API v2 adapter — pay-per-use posting (mirror of ``src/x/client.ts``).

Media upload is 2-step (upload → create tweet); the uploaded media id arrives via
the token as ``f"{media_id}:{access_token}"``. The per-post usage cost is surfaced
for wallet metering by the API layer. Sibling of the backend X connector.
"""

from __future__ import annotations

from .caps import caps_for
from .http import HttpFn, HttpOptions, encode_uri_component, http_json
from .publisher import AnalyticsSnapshot, PublishRequest, PublishResult, TokenRefresh

_API = "https://api.twitter.com/2"

# Per-post cost in integer microdollars (for wallet metering) — $0.015.
X_POST_COST_MICROS = 15_000


class XPublisher:
    platform = "x"

    def __init__(self, http: HttpFn = http_json) -> None:
        self._http = http

    def caps(self) -> dict:
        return caps_for("x") or {}

    def schedule_supported(self) -> bool:
        return False

    def publish(self, req: PublishRequest, token: str) -> PublishResult:
        media_id, access_token = token.split(":", 1)
        res = self._http(
            f"{_API}/tweets",
            HttpOptions(
                method="POST",
                token=access_token,
                body={
                    "text": req.caption[: self.caps()["caption_max"]],
                    "media": {"media_ids": [media_id]},
                },
            ),
        )
        tweet_id = res["data"]["id"]
        return PublishResult(platform="x", post_id=tweet_id, url=f"https://x.com/i/status/{tweet_id}")

    def refresh(self, refresh_token: str) -> TokenRefresh:
        res = self._http(
            f"{_API}/oauth2/token",
            HttpOptions(
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body={"grant_type": "refresh_token", "refresh_token": refresh_token},
            ),
        )
        return TokenRefresh(access_token=res["access_token"], expires_in=res["expires_in"])

    def fetch_analytics(self, post_id: str, token: str) -> AnalyticsSnapshot:
        _, access_token = token.split(":", 1)
        res = self._http(
            f"{_API}/tweets/{encode_uri_component(post_id)}?tweet.fields=public_metrics",
            HttpOptions(token=access_token),
        )
        metrics = (res.get("data") or {}).get("public_metrics") or {}
        return AnalyticsSnapshot(
            platform="x",
            views=metrics.get("impression_count", 0),
            watch_time_s=0,
            retention_pct=0,
        )
