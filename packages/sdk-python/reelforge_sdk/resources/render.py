"""Async-GPU render — start, poll status, advance (wallet-metered)."""

from typing import Any, Dict, Optional
from urllib.parse import quote

from ._base import RequestClient


class RenderResource:
    def __init__(self, client: RequestClient) -> None:
        self._client = client

    def start(
        self,
        *,
        backend: str,
        spec: Dict[str, Any],
        max_cost_micros: int,
        workflow_version: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "backend": backend,
            "spec": spec,
            "max_cost_micros": max_cost_micros,
            "workflow_version": workflow_version,
            "workspace_id": workspace_id,
        }
        return self._client._request("POST", "/render/jobs", body=body)

    def get(self, job_id: str) -> Dict[str, Any]:
        return self._client._request("GET", f"/render/jobs/{quote(job_id, safe='')}")

    def advance(self, job_id: str) -> Dict[str, Any]:
        return self._client._request("POST", f"/render/jobs/{quote(job_id, safe='')}/advance")
