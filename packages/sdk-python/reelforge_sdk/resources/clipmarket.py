"""Clipping marketplace — campaigns, submissions, fraud-gated CPM payout."""

from typing import Any, Dict, Optional
from urllib.parse import quote

from ._base import RequestClient


class ClipmarketResource:
    def __init__(self, client: RequestClient) -> None:
        self._client = client

    def create_campaign(
        self,
        *,
        cpm_micros: int,
        budget_micros: int,
        title: Optional[str] = None,
        min_views: int = 0,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "cpm_micros": cpm_micros,
            "budget_micros": budget_micros,
            "title": title,
            "min_views": min_views,
        }
        return self._client._request("POST", "/clipmarket/campaigns", body=body)

    def list_campaigns(self, *, limit: int = 50) -> Dict[str, Any]:
        return self._client._request("GET", "/clipmarket/campaigns", query={"limit": limit})

    def set_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        return self._client._request(
            "POST", f"/clipmarket/campaigns/{quote(campaign_id, safe='')}/status", body={"status": status}
        )

    def submit(self, campaign_id: str, clip_url: str) -> Dict[str, Any]:
        return self._client._request(
            "POST", f"/clipmarket/campaigns/{quote(campaign_id, safe='')}/submit", body={"clip_url": clip_url}
        )

    def review(self, submission_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._client._request(
            "POST", f"/clipmarket/submissions/{quote(submission_id, safe='')}/review", body=body
        )
