"""Generic self-hosted / free TTS adapter (voice capability, synchronous).

One reusable adapter for the fallback voice backends behind the ElevenLabs
primary (CTO plan §10.6): **Chatterbox** (MIT), **Kokoro** (Apache), and
**EdgeTTS** (free). The provider key, base URL, and auth are injected so a single
tested implementation serves several catalog providers. Usage is metered in
characters (``len(text)``); synchronous, so :meth:`submit` yields a terminal run.
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


class SelfHostTTSAdapter:
    """A synchronous TTS adapter parameterized by provider/endpoint."""

    def __init__(
        self,
        *,
        provider_key: str,
        base_url: str,
        synth_path: str = "/tts",
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer ",
        api_key: str = "",
        request_fn: Any = None,
    ) -> None:
        self._provider_key = provider_key
        self._base_url = base_url
        self._synth_path = synth_path
        self._api_key = api_key or os.getenv(
            f"{provider_key.upper().replace('-', '_')}_API_KEY", ""
        )
        headers = {}
        # EdgeTTS is unauthenticated; only attach an auth header when a key exists.
        if self._api_key:
            headers[auth_header] = f"{auth_scheme}{self._api_key}".strip()
        self._request = request_fn or build_json_transport(
            provider_key=provider_key, base_url=base_url, headers=headers
        )

    @property
    def provider_key(self) -> str:
        return self._provider_key

    def catalog(self) -> list[ModelListing]:
        return []

    def quote(self, request: Any, price_version: Any) -> QuoteResult:
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
                f"{self._provider_key} submit requires request['text']",
                provider_key=self._provider_key,
                retryable=False,
            )
        payload = self._request(
            "POST",
            self._synth_path,
            json={
                "text": text,
                "voice": self._voice_id(snapshot),
                "language": (request or {}).get("language", "auto"),
            },
        )
        return ProviderRun(
            provider_key=self._provider_key,
            run_id=str(payload.get("id", "") or correlation_id or "tts-run"),
            state=RUN_COMPLETED,
            progress=100,
            result_ref=str(payload.get("audio_url", "") or payload.get("audio_ref", "")),
            usage=self.normalize_usage({"characters": len(text), **payload}),
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
            cost_micros=0,
            raw={k: v for k, v in payload.items() if k not in {"audio_ref"}},
        )
