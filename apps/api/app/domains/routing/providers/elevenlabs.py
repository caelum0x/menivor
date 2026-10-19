"""ElevenLabs text-to-speech adapter (voice capability, synchronous).

Implements the routing ``ProviderAdapter`` contract for TTS. ElevenLabs returns
audio synchronously, so :meth:`submit` yields a terminal, usage-bearing run;
usage is metered in characters (``len(text)``). Owns outbound calls only.
"""

from __future__ import annotations

import os
from typing import Any

from app.domains.routing.base import (
    RUN_COMPLETED,
    ModelListing,
    NormalizedUsage,
    ProviderError,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.providers._pricing import quote_from_price
from app.domains.routing.providers._transport import build_json_transport

_PROVIDER_KEY = "elevenlabs"
_DEFAULT_BASE_URL = "https://api.elevenlabs.io"


class ElevenLabsAdapter:
    """Routing adapter for ElevenLabs TTS voices."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        request_fn: Any = None,
    ) -> None:
        self._api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
        self._base_url = base_url or os.getenv(
            "ELEVENLABS_BASE_URL", _DEFAULT_BASE_URL
        )
        self._request = request_fn or build_json_transport(
            provider_key=_PROVIDER_KEY,
            base_url=self._base_url,
            headers={"xi-api-key": self._api_key},
        )

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

    def catalog(self) -> list[ModelListing]:
        """List ElevenLabs voices as normalized voice listings."""
        payload = self._request("GET", "/v1/voices")
        listings: list[ModelListing] = []
        for voice in payload.get("voices", []) or []:
            vid = str(voice.get("voice_id") or "").strip()
            if not vid:
                continue
            listings.append(
                ModelListing(
                    provider_key=_PROVIDER_KEY,
                    model_id=f"elevenlabs/{vid}",
                    capability="voice",
                    metering_unit="characters",
                    latency_band="fast",
                )
            )
        return listings

    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        # Estimate characters from the request text when no explicit quantity.
        estimated = None
        if isinstance(request, dict):
            estimated = request.get("estimated_quantity")
            if estimated is None and request.get("text"):
                estimated = len(str(request["text"]))
        return quote_from_price(price_version, estimated)

    def _voice_id(self, snapshot: dict) -> str:
        model_id = str(snapshot.get("model_id", "") or "")
        return model_id.split("/", 1)[1] if "/" in model_id else model_id

    def submit(self, request: Any, snapshot: dict, correlation_id: str) -> ProviderRun:
        text = str((request or {}).get("text", "") if isinstance(request, dict) else "")
        if not text:
            raise ProviderError(
                "elevenlabs submit requires request['text']",
                provider_key=_PROVIDER_KEY,
                retryable=False,
            )
        voice_id = self._voice_id(snapshot)
        model = str(snapshot.get("provider_model", "") or "eleven_multilingual_v2")
        payload = self._request(
            "POST",
            f"/v1/text-to-speech/{voice_id}",
            json={"text": text, "model_id": model},
        )
        usage = self.normalize_usage({"characters": len(text), **payload})
        return ProviderRun(
            provider_key=_PROVIDER_KEY,
            run_id=str(payload.get("request_id", "") or correlation_id or "el-run"),
            state=RUN_COMPLETED,
            progress=100,
            result_ref=str(payload.get("audio_ref", "") or payload.get("raw_text", "")),
            usage=usage,
            raw=payload,
        )

    def poll(self, run: ProviderRun) -> ProviderRun:
        return run  # synchronous

    def cancel(self, run: ProviderRun) -> bool:
        return False

    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        payload = payload or {}
        characters = int(payload.get("characters", 0) or 0)
        return NormalizedUsage(
            unit="characters",
            quantity_units=characters,
            cost_micros=0,  # priced by the domain from the resolved price version
            raw={k: v for k, v in payload.items() if k != "audio_ref"},
        )
