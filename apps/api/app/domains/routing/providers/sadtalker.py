"""SadTalker photo-avatar adapter (avatar capability, asynchronous).

Turns a still photo + narration audio into a talking-head clip on a GPU
deployment (RunPod-style), so a creator can bring their OWN photo instead of a
licensed HeyGen preset — the CTO plan §10.2 "SadTalker photo-avatar provider".
Async: :meth:`submit` enqueues on the GPU worker and returns a run id;
:meth:`poll` maps status and attaches seconds of usage on completion.
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

_PROVIDER_KEY = "sadtalker"
_DEFAULT_BASE_URL = "https://sadtalker.internal.reelforge.app"

_STATE_MAP = {
    "queued": RUN_QUEUED,
    "pending": RUN_QUEUED,
    "running": RUN_RUNNING,
    "processing": RUN_RUNNING,
    "completed": RUN_COMPLETED,
    "succeeded": RUN_COMPLETED,
    "failed": RUN_FAILED,
    "error": RUN_FAILED,
}


class SadTalkerAdapter:
    """Routing adapter for SadTalker photo → talking-head generation."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        request_fn: Any = None,
    ) -> None:
        self._api_key = api_key or os.getenv("SADTALKER_API_KEY", "")
        self._base_url = base_url or os.getenv("SADTALKER_BASE_URL", _DEFAULT_BASE_URL)
        self._request = request_fn or build_json_transport(
            provider_key=_PROVIDER_KEY,
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

    def catalog(self) -> list[ModelListing]:
        # A single reviewed photo-avatar model; operator-curated.
        return [
            ModelListing(
                provider_key=_PROVIDER_KEY,
                model_id="sadtalker/photo-avatar",
                capability="avatar",
                metering_unit="seconds",
                latency_band="slow",
            )
        ]

    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        estimated = request.get("estimated_quantity") if isinstance(request, dict) else None
        return quote_from_price(price_version, estimated)

    def submit(self, request: Any, snapshot: dict, correlation_id: str) -> ProviderRun:
        body = request if isinstance(request, dict) else {}
        # SadTalker needs a source image + driving audio; the domain supplies both.
        if not body.get("image_url") or not body.get("audio_url"):
            raise ProviderError(
                "sadtalker submit requires image_url + audio_url",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        payload = self._request(
            "POST",
            "/run",
            json={
                "image_url": body["image_url"],
                "audio_url": body["audio_url"],
                "preprocess": body.get("preprocess", "full"),
                "still": bool(body.get("still", True)),
                "correlation_id": correlation_id,
            },
        )
        run_id = str(payload.get("run_id", "") or payload.get("id", "") or "")
        if not run_id:
            raise ProviderError(
                "sadtalker submit did not return a run id",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        return ProviderRun(
            provider_key=_PROVIDER_KEY, run_id=run_id, state=RUN_QUEUED, raw=payload
        )

    def poll(self, run: ProviderRun) -> ProviderRun:
        payload = self._request("GET", f"/status/{run.run_id}")
        state = _STATE_MAP.get(str(payload.get("state", "")).lower(), RUN_RUNNING)
        usage = None
        result_ref = ""
        if state == RUN_COMPLETED:
            usage = self.normalize_usage(payload)
            result_ref = str(payload.get("output_url", "") or "")
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=run.run_id,
            state=state,
            progress=int(payload.get("progress", run.progress) or 0),
            result_ref=result_ref,
            usage=usage,
            raw=payload,
        )

    def cancel(self, run: ProviderRun) -> bool:
        try:
            self._request("POST", f"/cancel/{run.run_id}")
            return True
        except ProviderError:
            return False

    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        payload = payload or {}
        raw_seconds = payload.get("seconds", payload.get("duration", 0)) or 0
        seconds = int(raw_seconds) + (1 if float(raw_seconds) % 1 else 0)
        return NormalizedUsage(
            unit="seconds",
            quantity_units=max(0, seconds),
            cost_micros=0,
            raw=dict(payload),
        )
