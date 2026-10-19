"""Workspace webhook subscription operations."""

from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

from ._base import RequestClient


class WebhooksResource:
    def __init__(self, client: RequestClient) -> None:
        self._client = client

    def _base(self, workspace_id: str) -> str:
        return f"/me/workspaces/{quote(workspace_id, safe='')}/webhooks"

    def create(
        self, workspace_id: str, url: str, event_types: Sequence[str]
    ) -> Dict[str, Any]:
        return self._client._request(
            "POST",
            self._base(workspace_id),
            body={"url": url, "event_types": list(event_types)},
        )

    def list(self, workspace_id: str) -> List[Dict[str, Any]]:
        return self._client._request("GET", self._base(workspace_id))

    def delete(self, workspace_id: str, subscription_id: str) -> Dict[str, Any]:
        return self._client._request(
            "DELETE",
            f"{self._base(workspace_id)}/{quote(subscription_id, safe='')}",
        )

    def test(self, workspace_id: str, subscription_id: str) -> Dict[str, Any]:
        return self._client._request(
            "POST",
            f"{self._base(workspace_id)}/{quote(subscription_id, safe='')}/test",
        )

    def deliveries(
        self, workspace_id: str, subscription_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return self._client._request(
            "GET",
            f"{self._base(workspace_id)}/{quote(subscription_id, safe='')}/deliveries",
            query={} if limit is None else {"limit": limit},
        )
