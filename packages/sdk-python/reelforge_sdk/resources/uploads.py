"""Presigned upload operations."""

from typing import Any, Dict

from ._base import RequestClient


class UploadsResource:
    def __init__(self, client: RequestClient) -> None:
        self._client = client

    def presign(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._client._request("POST", "/uploads/presign", body=body)

    def register(self, key: str, kind: str = "upload") -> Dict[str, Any]:
        return self._client._request(
            "POST",
            "/uploads/register",
            body={"key": key, "kind": kind},
        )
