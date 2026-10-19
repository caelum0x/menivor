"""Workspace usage and entitlement operations."""

from typing import Any, Dict, Optional
from urllib.parse import quote

from ._base import RequestClient


class WorkspacesResource:
    def __init__(self, client: RequestClient) -> None:
        self._client = client

    def usage(self, workspace_id: str, period: Optional[str] = None) -> Dict[str, Any]:
        return self._client._request(
            "GET",
            f"/me/workspaces/{quote(workspace_id, safe='')}/usage",
            query={} if period is None else {"period": period},
        )

    def entitlements(self, workspace_id: str) -> Dict[str, Any]:
        return self._client._request(
            "GET",
            f"/me/workspaces/{quote(workspace_id, safe='')}/entitlements",
        )
