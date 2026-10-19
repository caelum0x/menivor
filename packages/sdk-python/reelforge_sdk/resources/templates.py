"""Genre shot-template engine — browse + compile + instantiate viral formats."""

from typing import Any, Dict, Optional
from urllib.parse import quote

from ._base import RequestClient


class TemplatesResource:
    def __init__(self, client: RequestClient) -> None:
        self._client = client

    def list(self) -> Dict[str, Any]:
        return self._client._request("GET", "/templates")

    def get(self, slug: str) -> Dict[str, Any]:
        return self._client._request("GET", f"/templates/{quote(slug, safe='')}")

    def compile(
        self,
        slug: str,
        inputs: Dict[str, Any],
        *,
        duration_s: Optional[float] = None,
        surface: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"inputs": inputs, "duration_s": duration_s, "surface": surface}
        return self._client._request("POST", f"/templates/{quote(slug, safe='')}/compile", body=body)

    def instantiate(
        self,
        slug: str,
        inputs: Dict[str, Any],
        *,
        duration_s: Optional[float] = None,
        surface: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"inputs": inputs, "duration_s": duration_s, "surface": surface}
        return self._client._request("POST", f"/templates/{quote(slug, safe='')}/instantiate", body=body)

    def popular(self, *, limit: int = 10) -> Dict[str, Any]:
        return self._client._request("GET", "/templates/analytics/popular", query={"limit": limit})

    def history(self, *, limit: int = 50) -> Dict[str, Any]:
        return self._client._request("GET", "/templates/history", query={"limit": limit})
