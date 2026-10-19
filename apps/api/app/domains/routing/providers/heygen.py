"""HeyGen talking-head avatar adapter (avatar capability, asynchronous).

HeyGen video generation is async: :meth:`submit` enqueues and returns a
non-terminal run carrying the provider ``video_id``; :meth:`poll` maps HeyGen's
status to a normalized state and, on completion, attaches usage (seconds).
"""

from __future__ import annotations

import os
from typing import Any

from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    ModelListing,
    NormalizedUsage,
    ProviderError,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.providers._pricing import quote_from_price
from app.domains.routing.providers._transport import build_json_transport

_PROVIDER_KEY = "heygen"
_DEFAULT_BASE_URL = "https://api.heygen.com"

# HeyGen status string -> normalized run state.
_STATE_MAP = {
    "pending": RUN_QUEUED,
    "waiting": RUN_QUEUED,
    "processing": RUN_RUNNING,
    "completed": RUN_COMPLETED,
    "failed": RUN_FAILED,
}


class HeyGenAdapter:
    """Routing adapter for HeyGen avatar video generation."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        request_fn: Any = None,
    ) -> None:
        self._api_key = api_key or os.getenv("HEYGEN_API_KEY", "")
        self._base_url = base_url or os.getenv("HEYGEN_BASE_URL", _DEFAULT_BASE_URL)
        self._request = request_fn or build_json_transport(
            provider_key=_PROVIDER_KEY,
            base_url=self._base_url,
            headers={"X-Api-Key": self._api_key},
        )

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

    def catalog(self) -> list[ModelListing]:
        payload = self._request("GET", "/v2/avatars")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        avatars = (data or {}).get("avatars", []) if isinstance(data, dict) else []
        listings: list[ModelListing] = []
        for avatar in avatars or []:
            aid = str(avatar.get("avatar_id") or "").strip()
            if not aid:
                continue
            listings.append(
                ModelListing(
                    provider_key=_PROVIDER_KEY,
                    model_id=f"heygen/{aid}",
                    capability="avatar",
                    metering_unit="seconds",
                )
            )
        return listings

    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        estimated = request.get("estimated_quantity") if isinstance(request, dict) else None
        return quote_from_price(price_version, estimated)

    def submit(self, request: Any, snapshot: dict, correlation_id: str) -> ProviderRun:
        body = request if isinstance(request, dict) else {}
        payload = self._request("POST", "/v2/video/generate", json=body)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        video_id = str((data or {}).get("video_id", "") or "")
        if not video_id:
            raise ProviderError(
                "heygen submit did not return a video_id",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=video_id,
            state=RUN_QUEUED,
            raw=payload,
        )

    def poll(self, run: ProviderRun) -> ProviderRun:
        payload = self._request(
            "GET", f"/v1/video_status.get?video_id={run.run_id}"
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        data = data or {}
        state = _STATE_MAP.get(str(data.get("status", "")).lower(), RUN_RUNNING)
        usage = None
        result_ref = ""
        if state == RUN_COMPLETED:
            usage = self.normalize_usage(data)
            result_ref = str(data.get("video_url", "") or "")
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=run.run_id,
            state=state,
            progress=100 if state == RUN_COMPLETED else run.progress,
            result_ref=result_ref,
            usage=usage,
            raw=payload,
        )

    def cancel(self, run: ProviderRun) -> bool:
        return False

    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        payload = payload or {}
        # HeyGen reports duration in seconds (may be fractional); round up.
        raw_seconds = payload.get("duration", payload.get("seconds", 0)) or 0
        seconds = int(raw_seconds) + (1 if float(raw_seconds) % 1 else 0)
        return NormalizedUsage(
            unit="seconds",
            quantity_units=max(0, seconds),
            cost_micros=0,
            raw=dict(payload),
        )
