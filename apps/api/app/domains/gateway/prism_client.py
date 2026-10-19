"""Typed server-to-server client for the Prism media execution boundary."""

from __future__ import annotations

import os
from typing import Any

import httpx

_ACCEPTANCE_DEFINITE_NO = "definitely_not_accepted"
_ACCEPTANCE_UNKNOWN = "unknown"


class PrismClientError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        acceptance: str = _ACCEPTANCE_DEFINITE_NO,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.acceptance = acceptance

    @property
    def may_have_been_accepted(self) -> bool:
        return self.acceptance == _ACCEPTANCE_UNKNOWN


class PrismClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"), transport=transport, timeout=timeout
        )

    def _headers(self, correlation_id: str = "") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        return headers

    @staticmethod
    def _parse(response: httpx.Response, *, is_submit: bool = False) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if 200 <= response.status_code < 300 and isinstance(payload, dict):
            return payload
        message = f"Prism error (status {response.status_code})"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                message = str(error["message"])
        ambiguous = is_submit and (
            response.status_code == 408
            or response.status_code >= 500
            or 200 <= response.status_code < 300
        )
        raise PrismClientError(
            response.status_code,
            message,
            acceptance=(_ACCEPTANCE_UNKNOWN if ambiguous else _ACCEPTANCE_DEFINITE_NO),
        )

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        modality: str,
        max_cost_micros: int,
        correlation_id: str,
        duration_seconds: int = 5,
        aspect_ratio: str = "9:16",
        image_url: str = "",
    ) -> dict[str, Any]:
        body = {
            "model": model,
            "prompt": prompt,
            "modality": modality,
            "duration_seconds": int(duration_seconds),
            "aspect_ratio": aspect_ratio,
            "image_url": image_url or None,
            "routing": {
                "fallback": "equivalent",
                "max_cost_micros": int(max_cost_micros),
                "sort": "price",
            },
        }
        try:
            response = self._client.post(
                "/v1/media/generations",
                json=body,
                headers=self._headers(correlation_id),
            )
        except httpx.RequestError as exc:
            raise PrismClientError(
                502,
                f"Prism unreachable: {exc}",
                acceptance=_ACCEPTANCE_UNKNOWN,
            ) from exc
        result = self._parse(response, is_submit=True)
        if not str(result.get("id", "") or ""):
            raise PrismClientError(
                502,
                "Prism accepted the request but returned no generation id",
                acceptance=_ACCEPTANCE_UNKNOWN,
            )
        return result

    def generation(
        self, generation_id: str, *, correlation_id: str = ""
    ) -> dict[str, Any]:
        try:
            response = self._client.get(
                "/v1/generation",
                params={"id": generation_id},
                headers=self._headers(correlation_id),
            )
        except httpx.RequestError as exc:
            raise PrismClientError(502, f"Prism unreachable: {exc}") from exc
        return self._parse(response)

    def generation_by_correlation(self, correlation_id: str) -> dict[str, Any]:
        """Recover a submit whose response was lost without issuing another POST."""
        try:
            response = self._client.get(
                "/v1/generation/by-correlation",
                params={"correlation_id": correlation_id},
                headers=self._headers(correlation_id),
            )
        except httpx.RequestError as exc:
            raise PrismClientError(502, f"Prism unreachable: {exc}") from exc
        return self._parse(response)


def prism_client_from_config() -> PrismClient | None:
    """Build the optional Prism adapter lazily; absent config keeps direct routing."""
    base_url = os.getenv("PRISM_GATEWAY_URL", "").strip()
    api_key = os.getenv("PRISM_GATEWAY_API_KEY", "").strip()
    if not base_url and not api_key:
        return None
    if not base_url or not api_key:
        raise PrismClientError(
            503, "Prism requires both PRISM_GATEWAY_URL and PRISM_GATEWAY_API_KEY"
        )
    return PrismClient(base_url, api_key)
