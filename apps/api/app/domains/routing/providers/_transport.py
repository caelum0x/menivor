"""Shared JSON HTTP transport for provider adapters (import-safe, injectable).

Each adapter accepts a ``request_fn(method, path, *, json=None) -> dict``. In
production the default is this httpx-backed transport; in tests a fake callable
is injected so adapters run without network access. All upstream failures are
normalized to :class:`app.domains.routing.base.ProviderError` with a retry hint
so the routing/worker layer never sees a raw SDK/HTTP exception.
"""

from __future__ import annotations

from typing import Callable

from app.domains.routing.base import ProviderError

RequestFn = Callable[..., dict]

_DEFAULT_TIMEOUT_S = 60


def build_json_transport(
    *,
    provider_key: str,
    base_url: str,
    headers: dict[str, str],
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> RequestFn:
    """Return a lazy httpx-backed JSON transport for one provider.

    Raises :class:`ProviderError` (never ImportError) when ``httpx`` is missing,
    marks 5xx/network errors retryable and 4xx non-retryable, and always returns
    a parsed JSON dict on success (an empty dict for a 204/no-body response).
    """

    def _request(method: str, path: str, *, json: dict | None = None) -> dict:
        try:
            import httpx
        except Exception as exc:  # pragma: no cover - only without httpx installed
            raise ProviderError(
                f"httpx is required for the {provider_key} transport",
                provider_key=provider_key,
                retryable=False,
            ) from exc
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        request_headers = {"Content-Type": "application/json", **headers}
        try:
            resp = httpx.request(
                method, url, headers=request_headers, json=json, timeout=timeout_s
            )
        except Exception as exc:  # network error -> retryable
            raise ProviderError(
                f"{provider_key} request failed: {exc}",
                provider_key=provider_key,
                retryable=True,
            ) from exc
        if resp.status_code >= 500:
            raise ProviderError(
                f"{provider_key} server error {resp.status_code}",
                provider_key=provider_key,
                retryable=True,
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"{provider_key} client error {resp.status_code}: {resp.text[:200]}",
                provider_key=provider_key,
                retryable=False,
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except Exception:  # non-JSON success body -> expose the raw text
            return {"raw_text": resp.text}

    return _request
