"""Wan-2.2 character LoRA training adapter (``lora_train`` capability, async).

Trains a per-character LoRA from a handful of the creator's OWN reference images
so a recurring AI character can be reproduced with model-native identity fidelity
(the trained ``.safetensors`` is later fed to the WAN LoraLoader node — see
``wan_camera``). It runs on a Replicate / ComfyUI-Deploy GPU training deployment
and implements the frozen :class:`ProviderAdapter` contract exactly like the
async media adapters, so the routing/worker layer never learns training
internals.

Async lifecycle (transport shape mirrors ``sadtalker``):

1. **submit** — ``POST /run`` with ``{reference_urls, steps, rank, base_model,
   correlation_id}``. Requires at least ``min_references`` PRESIGNED reference
   URLs (short-lived signed GETs of the creator's OWN objects — never raw client
   URLs, SSRF §8) and returns a ``run_id``.
2. **poll** — ``GET /status/{run_id}`` until terminal; on completion the trained
   weights URL becomes ``result_ref`` and usage is metered in training ``steps``
   (falling back to ``seconds`` of wall-clock when the run reports no steps).

Transport is the injectable ``request_fn`` (``build_json_transport``) — the single
fakeable seam — so submit/poll are unit-testable without a network. The adapter
NEVER debits wallets, mutates job rows, or sets the client price (contract §3).
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

_PROVIDER_KEY = "lora_train"
_DEFAULT_BASE_URL = "https://lora-train.internal.reelforge.app"
LORA_TRAIN_MODEL_ID = "wan-2.2/character-lora-trainer"

# Minimum reference images a training run needs to lock an identity.
_DEFAULT_MIN_REFERENCES = 1

_STATE_MAP = {
    "queued": RUN_QUEUED,
    "pending": RUN_QUEUED,
    "starting": RUN_QUEUED,
    "not-started": RUN_QUEUED,
    "running": RUN_RUNNING,
    "processing": RUN_RUNNING,
    "training": RUN_RUNNING,
    "uploading": RUN_RUNNING,
    "completed": RUN_COMPLETED,
    "succeeded": RUN_COMPLETED,
    "success": RUN_COMPLETED,
    "failed": RUN_FAILED,
    "error": RUN_FAILED,
    "canceled": RUN_FAILED,
    "cancelled": RUN_FAILED,
}

# Where a completed training run exposes its trained weights url.
_RESULT_KEYS: tuple[str, ...] = (
    "weights_url",
    "lora_url",
    "output_url",
    "safetensors_url",
    "url",
)


class LoRATrainAdapter:
    """ProviderAdapter for Wan-2.2 character-LoRA training (submit → poll)."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        min_references: int = _DEFAULT_MIN_REFERENCES,
        request_fn: Any = None,
    ) -> None:
        self._api_key = (
            api_key
            or os.getenv("REPLICATE_API_TOKEN", "")
            or os.getenv("COMFY_DEPLOY_TOKEN", "")
        )
        self._base_url = base_url or os.getenv(
            "LORA_TRAIN_BASE_URL", _DEFAULT_BASE_URL
        )
        self._min_references = max(1, int(min_references or 1))
        self._request = request_fn or build_json_transport(
            provider_key=_PROVIDER_KEY,
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

    def catalog(self) -> list[ModelListing]:
        return [
            ModelListing(
                provider_key=_PROVIDER_KEY,
                model_id=LORA_TRAIN_MODEL_ID,
                capability="lora_train",
                metering_unit="steps",
                latency_band="slow",
            )
        ]

    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        est = None
        if isinstance(request, dict):
            est = request.get("steps") or request.get("estimated_quantity")
        return quote_from_price(price_version, est)

    def submit(self, request: Any, snapshot: dict, correlation_id: str) -> ProviderRun:
        body = request if isinstance(request, dict) else {}
        reference_urls = [
            str(u) for u in (body.get("reference_urls") or []) if str(u).strip()
        ]
        if len(reference_urls) < self._min_references:
            raise ProviderError(
                f"lora_train submit requires >= {self._min_references} "
                f"reference_urls (got {len(reference_urls)})",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        steps = int(body.get("steps", 0) or 0)
        payload = self._request(
            "POST",
            "/run",
            json={
                "reference_urls": reference_urls,
                "steps": steps,
                "rank": int(body.get("rank", 0) or 0),
                "base_model": str(body.get("base_model", "wan-2.2") or "wan-2.2"),
                "correlation_id": correlation_id,
            },
        )
        run_id = str((payload or {}).get("run_id", "") or (payload or {}).get("id", "") or "")
        if not run_id:
            raise ProviderError(
                "lora_train submit did not return a run id",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        raw = dict(payload or {})
        raw["steps"] = steps
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=run_id,
            state=self._map_state((payload or {}).get("state") or "queued"),
            raw=raw,
        )

    def poll(self, run: ProviderRun) -> ProviderRun:
        if run.is_terminal:
            return run
        payload = self._request("GET", f"/status/{run.run_id}") or {}
        state = self._map_state(payload.get("state") or payload.get("status") or "running")
        # Carry the submit-time step count forward so usage can be metered on the
        # terminal poll even when the status endpoint omits it.
        prior_steps = run.raw.get("steps") if isinstance(run.raw, dict) else None
        raw = dict(payload)
        if prior_steps and not raw.get("steps"):
            raw["steps"] = prior_steps
        result_ref = ""
        usage = None
        if state == RUN_COMPLETED:
            result_ref = _extract_result_url(payload)
            usage = self.normalize_usage(raw)
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=run.run_id,
            state=state,
            progress=100 if state == RUN_COMPLETED else int(payload.get("progress", run.progress) or 0),
            result_ref=result_ref,
            usage=usage,
            raw=raw,
        )

    def cancel(self, run: ProviderRun) -> bool:
        try:
            self._request("POST", f"/cancel/{run.run_id}")
            return True
        except ProviderError:
            return False

    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        payload = payload or {}
        steps = int(payload.get("steps", 0) or 0)
        if steps > 0:
            return NormalizedUsage(
                unit="steps", quantity_units=steps, cost_micros=0, raw=dict(payload)
            )
        raw_seconds = payload.get("seconds", payload.get("duration", 0)) or 0
        seconds = int(raw_seconds) + (1 if float(raw_seconds) % 1 else 0)
        return NormalizedUsage(
            unit="seconds",
            quantity_units=max(0, seconds),
            cost_micros=0,
            raw=dict(payload),
        )

    def _map_state(self, raw: Any) -> str:
        return _STATE_MAP.get(str(raw or "").strip().lower(), RUN_RUNNING)


def _extract_result_url(payload: dict) -> str:
    """Find the trained ``.safetensors`` url in a completed training payload."""
    payload = payload or {}
    for key in _RESULT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    output = payload.get("output")
    if isinstance(output, str) and output.startswith(("http://", "https://")):
        return output
    if isinstance(output, list) and output:
        last = output[-1]
        if isinstance(last, str) and last.startswith(("http://", "https://")):
            return last
    return ""
