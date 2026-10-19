"""Kokoro TTS over HTTP — the self-hosted Kokoro-FastAPI sidecar.

Fills the ``kokoro`` provider slot. The sidecar is remsky/Kokoro-FastAPI
(Apache-2.0) serving hexgrad/Kokoro-82M (Apache-2.0 weights). It runs as a
separate container (infra-box ``stacks/kokoro``); we only ever talk to it over
HTTP, never import it, so its phonemizer data (espeak-ng, GPL-3.0) stays inside
that container.

Wire protocol (OpenAI-compatible, as exposed by Kokoro-FastAPI):

* ``POST {KOKORO_URL}/v1/audio/speech`` with
  ``{"model": "kokoro", "input": text, "voice": "af_heart",
  "response_format": "mp3", "speed": 1.0, "stream": false}`` → audio bytes.
* ``GET {KOKORO_URL}/v1/audio/voices`` → ``{"voices": [{"id": "af_heart", ...}]}``
  (v0.9; older builds returned plain strings — both are accepted).

The adapter is enabled only when ``KOKORO_URL`` is set (off by default).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import uuid4

from app.domains.routing.base import (
    RUN_COMPLETED,
    ModelListing,
    NormalizedUsage,
    ProviderError,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.providers._pricing import quote_from_price

PROVIDER_KEY = "kokoro"
DEFAULT_VOICE = "af_heart"
DEFAULT_FORMAT = "mp3"
ALLOWED_FORMATS = frozenset({"mp3", "wav", "opus", "flac", "aac", "pcm"})
MIN_SPEED = 0.5
MAX_SPEED = 2.0
# Kokoro-FastAPI splits long input itself; we still cap a single request so one
# call cannot pin the CPU-only sidecar for minutes.
MAX_INPUT_CHARS = 5_000
_DEFAULT_TIMEOUT_S = 120.0

_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/ogg",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "pcm": "application/octet-stream",
}


def kokoro_url(env: Mapping[str, str] | None = None) -> str:
    """The configured sidecar base URL, or ``""`` when Kokoro is disabled."""
    source = env if env is not None else os.environ
    return str(source.get("KOKORO_URL", "") or "").strip().rstrip("/")


def content_type_for(response_format: str) -> str:
    return _CONTENT_TYPES.get(response_format, "application/octet-stream")


def _clamp_speed(speed: Any) -> float:
    try:
        value = float(speed)
    except (TypeError, ValueError):
        return 1.0
    if value != value:  # NaN
        return 1.0
    return max(MIN_SPEED, min(MAX_SPEED, value))


@dataclass(frozen=True)
class SpeechResult:
    audio: bytes
    content_type: str
    characters: int
    voice: str


# (method, url, json|None, timeout) -> (status_code, body_bytes, content_type)
HttpFn = Callable[[str, str, "dict | None", float], "tuple[int, bytes, str]"]


def _httpx_request(method: str, url: str, json: dict | None, timeout: float):
    import httpx

    resp = httpx.request(method, url, json=json, timeout=timeout)
    return resp.status_code, resp.content, resp.headers.get("content-type", "")


class KokoroClient:
    """Thin HTTP client for a Kokoro-FastAPI sidecar."""

    def __init__(
        self,
        base_url: str,
        *,
        http_fn: HttpFn | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        if not base_url:
            raise ProviderError(
                "KOKORO_URL is not configured", provider_key=PROVIDER_KEY, retryable=False
            )
        self._base = base_url.rstrip("/")
        self._http = http_fn or _httpx_request
        self._timeout = timeout_s

    def _send(self, method: str, path: str, json: dict | None) -> tuple[bytes, str]:
        url = f"{self._base}{path}"
        body = dict(json) if json is not None else None
        try:
            status, content, ctype = self._http(method, url, body, self._timeout)
        except ProviderError:
            raise
        except Exception as exc:  # network / timeout -> retryable
            raise ProviderError(
                f"kokoro request failed: {exc}", provider_key=PROVIDER_KEY, retryable=True
            ) from exc
        if status >= 500:
            raise ProviderError(
                f"kokoro server error {status}", provider_key=PROVIDER_KEY, retryable=True
            )
        if status >= 400:
            detail = content[:200].decode("utf-8", "replace") if content else ""
            raise ProviderError(
                f"kokoro client error {status}: {detail}",
                provider_key=PROVIDER_KEY,
                retryable=False,
            )
        return content or b"", ctype or ""

    def synthesize(
        self,
        text: str,
        *,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
        response_format: str = DEFAULT_FORMAT,
    ) -> SpeechResult:
        clean = str(text or "").strip()
        if not clean:
            raise ProviderError(
                "kokoro synthesis requires non-empty text",
                provider_key=PROVIDER_KEY,
                retryable=False,
            )
        if len(clean) > MAX_INPUT_CHARS:
            raise ProviderError(
                f"kokoro input exceeds {MAX_INPUT_CHARS} characters; chunk it first",
                provider_key=PROVIDER_KEY,
                retryable=False,
            )
        fmt = response_format if response_format in ALLOWED_FORMATS else DEFAULT_FORMAT
        chosen_voice = str(voice or "").strip() or DEFAULT_VOICE
        audio, ctype = self._send(
            "POST",
            "/v1/audio/speech",
            {
                "model": "kokoro",
                "input": clean,
                "voice": chosen_voice,
                "response_format": fmt,
                "speed": _clamp_speed(speed),
                "stream": False,
            },
        )
        if not audio:
            raise ProviderError(
                "kokoro returned no audio", provider_key=PROVIDER_KEY, retryable=True
            )
        if ctype.startswith("application/json"):
            raise ProviderError(
                f"kokoro returned JSON instead of audio: {audio[:200]!r}",
                provider_key=PROVIDER_KEY,
                retryable=False,
            )
        return SpeechResult(
            audio=audio,
            content_type=content_type_for(fmt),
            characters=len(clean),
            voice=chosen_voice,
        )

    def list_voices(self) -> list[str]:
        import json as _json

        content, _ = self._send("GET", "/v1/audio/voices", None)
        try:
            payload = _json.loads(content.decode("utf-8")) if content else {}
        except ValueError:
            return []
        voices = payload.get("voices", []) if isinstance(payload, dict) else payload
        if not isinstance(voices, list):
            return []
        # v0.9+ returns [{"id": "af_heart", "name": ...}]; <0.3 returned plain strings.
        ids = [v.get("id") if isinstance(v, dict) else v for v in voices]
        return [v for v in ids if isinstance(v, str) and v]


def _default_host(data: bytes) -> str:
    from app.domains.routing.providers.voice_gen import host_audio_bytes

    return host_audio_bytes(data, key_prefix="prism/voice/kokoro")


class KokoroTTSAdapter:
    """Routing-registry adapter for the ``kokoro`` provider (synchronous TTS).

    ``submit`` synthesizes via the sidecar, hosts the bytes (R2 by default) and
    returns a terminal run whose ``result_ref`` is the hosted URL.
    """

    def __init__(
        self,
        *,
        base_url: str,
        http_fn: HttpFn | None = None,
        host_fn: Callable[[bytes], str] | None = None,
    ) -> None:
        self._client = KokoroClient(base_url, http_fn=http_fn)
        self._host = host_fn or _default_host

    @property
    def provider_key(self) -> str:
        return PROVIDER_KEY

    @property
    def client(self) -> KokoroClient:
        return self._client

    def catalog(self) -> list[ModelListing]:
        return []

    def quote(self, request: Any, price_version: Any) -> QuoteResult:
        estimated = None
        if isinstance(request, dict):
            estimated = request.get("estimated_quantity")
            if estimated is None and request.get("text"):
                estimated = len(str(request["text"]))
        return quote_from_price(price_version, estimated)

    @staticmethod
    def _voice_from(request: dict, snapshot: dict) -> str:
        explicit = str(request.get("voice", "") or request.get("voice_id", "") or "").strip()
        if explicit:
            return explicit
        model_id = str((snapshot or {}).get("model_id", "") or "")
        suffix = model_id.split("/", 1)[1] if "/" in model_id else ""
        # Catalog id "kokoro/tts" names the capability, not a voice.
        return suffix if suffix and suffix != "tts" else DEFAULT_VOICE

    def submit(self, request: Any, snapshot: dict, correlation_id: str) -> ProviderRun:
        req = request if isinstance(request, dict) else {}
        result = self._client.synthesize(
            str(req.get("text", "") or ""),
            voice=self._voice_from(req, snapshot),
            speed=req.get("speed", 1.0),
            response_format=str(req.get("response_format", DEFAULT_FORMAT) or DEFAULT_FORMAT),
        )
        url = self._host(result.audio)
        return ProviderRun(
            provider_key=PROVIDER_KEY,
            run_id=correlation_id or f"kokoro-{uuid4().hex}",
            state=RUN_COMPLETED,
            progress=100,
            result_ref=url,
            usage=self.normalize_usage({"characters": result.characters}),
            raw={"voice": result.voice, "content_type": result.content_type},
        )

    def poll(self, run: ProviderRun) -> ProviderRun:
        return run

    def cancel(self, run: ProviderRun) -> bool:
        return False

    def normalize_usage(self, payload: dict) -> NormalizedUsage:
        characters = int((payload or {}).get("characters", 0) or 0)
        return NormalizedUsage(
            unit="characters", quantity_units=characters, cost_micros=0, raw=dict(payload or {})
        )
