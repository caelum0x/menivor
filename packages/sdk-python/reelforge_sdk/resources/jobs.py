"""Canonical reel job operations."""

from typing import Any, Dict, Optional

from ._base import RequestClient


class JobsResource:
    def __init__(self, client: RequestClient) -> None:
        self._client = client

    def create(
        self, body: Dict[str, Any], *, idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._client._request("POST", "/jobs", body=body, headers=headers)

    def get(self, job_id: str) -> Dict[str, Any]:
        from urllib.parse import quote

        return self._client._request("GET", f"/jobs/{quote(job_id, safe='')}")

    def list(
        self, *, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> Dict[str, Any]:
        query = {"limit": limit, "offset": offset}
        return self._client._request("GET", "/jobs", query=query)

    def retry(self, job_id: str) -> Dict[str, Any]:
        from urllib.parse import quote

        return self._client._request("POST", f"/jobs/{quote(job_id, safe='')}/retry")

    def rerun(
        self, job_id: str, body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        from urllib.parse import quote

        return self._client._request(
            "POST", f"/jobs/{quote(job_id, safe='')}/rerun", body=body or {}
        )

    def get_batch(self, batch_id: str) -> Dict[str, Any]:
        from urllib.parse import quote

        return self._client._request("GET", f"/batches/{quote(batch_id, safe='')}")

    def export_cut(
        self,
        job_id: str,
        *,
        in_point: float,
        out_point: float,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        from urllib.parse import quote

        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._client._request(
            "POST",
            f"/jobs/{quote(job_id, safe='')}/exports",
            body={"in_point": in_point, "out_point": out_point},
            headers=headers,
        )
