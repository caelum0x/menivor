"""Generic synchronous image-generation adapter (image capability).

One reusable adapter for image providers that expose a synchronous "generate one
image" JSON endpoint (Stability, Black Forest Labs / FLUX, OpenAI images, etc.).
The provider key, base URL, auth header, and generate path are injected so a
single, tested implementation serves several catalog providers. Usage is metered
per image.
"""

from __future__ import annotations

import os
from typing import Any

from app.domains.routing.base import (
    RUN_COMPLETED,
    ModelListing,
    NormalizedUsage,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.providers._pricing import quote_from_price
from app.domains.routing.providers._transport import build_json_transport


class ImageAdapter:
    """A synchronous image provider adapter parameterized by endpoint/auth."""

    def __init__(
        self,
        *,
        provider_key: str,
        base_url: str,
        generate_path: str = "/generate",
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer ",
        api_key: str = "",
        request_fn: Any = None,
    ) -> None:
        self._provider_key = provider_key
        self._base_url = base_url
        self._generate_path = generate_path
        self._api_key = api_key or os.getenv(
            f"{provider_key.upper().replace('-', '_')}_API_KEY", ""
        )
        headers = {auth_header: f"{auth_scheme}{self._api_key}".strip()}
        self._request = request_fn or build_json_transport(
            provider_key=provider_key, base_url=base_url, headers=headers
        )

    @property
    def provider_key(self) -> str:
        return self._provider_key

    def catalog(self) -> list[ModelListing]:
        # Image providers vary widely; the reviewed catalog is operator-curated,
        # so the adapter reports no dynamic listings by default.
        return []

    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        estimated = request.get("estimated_quantity") if isinstance(request, dict) else None
        # Images default to a single unit when the caller gives no estimate.
        return quote_from_price(price_version, estimated if estimated is not None else 1)

    def submit(self, request: Any, snapshot: dict, correlation_id: str) -> ProviderRun:
        body = {
            "model": snapshot.get("model_id", "").split("/", 1)[-1],
            **(request if isinstance(request, dict) else {}),
        }
        payload = self._request("POST", self._generate_path, json=body)
        images = payload.get("images") or payload.get("data") or []
        count = len(images) if isinstance(images, list) and images else 1
        result_ref = ""
        if isinstance(images, list) and images:
            first = images[0]
            result_ref = str(
                first.get("url") if isinstance(first, dict) else first
            )
        # Build the usage payload with the integer count last so the raw
        # ``images`` list (if any) never shadows it.
        usage_payload = {k: v for k, v in payload.items() if k != "images"}
        usage_payload["images"] = count
        return ProviderRun(
            provider_key=self._provider_key,
            run_id=str(payload.get("id", "") or correlation_id or "img-run"),
            state=RUN_COMPLETED,
            progress=100,
            result_ref=result_ref,
            usage=self.normalize_usage(usage_payload),
            raw=payload,
        )

    def poll(self, run: ProviderRun) -> ProviderRun:
        return run  # synchronous

    def cancel(self, run: ProviderRun) -> bool:
        return False

    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        payload = payload or {}
        count = int(payload.get("images", 1) or 1)
        return NormalizedUsage(
            unit="images",
            quantity_units=max(1, count),
            cost_micros=0,
            raw={k: v for k, v in payload.items() if k not in {"images"}},
        )
