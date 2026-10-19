"""Canonical AI B-roll generation operations."""

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._base import RequestClient


class BrollResource:
    def __init__(self, client: RequestClient) -> None:
        self._client = client

    def generate(
        self, body: Dict[str, Any], *, idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._client._request(
            "POST", "/generation/broll/generate", body=body, headers=headers
        )

    def get(self, generation_id: str) -> Dict[str, Any]:
        return self._client._request(
            "GET",
            f"/generation/broll/generations/{quote(generation_id, safe='')}",
        )

    def list(self) -> List[Dict[str, Any]]:
        data = self._client._request("GET", "/generation/broll/generations")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("generations"), list):
            return data["generations"]
        return []
