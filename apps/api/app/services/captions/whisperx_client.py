"""WhisperX microservice client — two-stage transcribe → align.

Calls a WhisperX GPU microservice (``external/workers/whisperx``) that returns
word-level timestamps, then parses the response into the typed
:class:`~app.services.captions.whisperx_schema.AlignmentResult` the caption
builders consume. The only network step is the injectable ``transport`` (default:
``requests``), so the client's request assembly + response handling are
unit-testable against a fake transport — the boundary is the network, not stubbed
logic. Config (base URL, api key) resolves from ``config.app``; nothing hardcoded.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.services.captions.whisperx_schema import AlignmentResult, parse_alignment


class WhisperXError(RuntimeError):
    """A transcription call failed (config missing, bad response, HTTP error)."""


@runtime_checkable
class Transport(Protocol):
    def request(self, method: str, url: str, *, headers: dict | None = None,
                json: Any | None = None) -> Any: ...


class RequestsTransport:
    """Default transport backed by ``requests`` (lazy import)."""

    def __init__(self, timeout_s: float = 300.0) -> None:
        self._timeout = timeout_s

    def request(self, method, url, *, headers=None, json=None):
        import requests

        return requests.request(method, url, headers=headers, json=json, timeout=self._timeout)


class WhisperXClient:
    """Transcribe + align audio to word-level timings via the WhisperX service."""

    def __init__(self, *, base_url: str = "", api_key: str = "", transport: Transport | None = None) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._transport = transport

    def _config(self) -> tuple[str, str]:
        base = self._base_url
        key = self._api_key
        if not base:
            from app.config import config

            base = str(config.app.get("whisperx_base_url", "") or "")
            key = key or str(config.app.get("whisperx_api_key", "") or "")
        if not base:
            raise WhisperXError("whisperx_base_url not configured")
        return base.rstrip("/"), key

    def transcribe(
        self, audio_url: str, *, language: str | None = None
    ) -> AlignmentResult:
        """Submit an audio URL for two-stage transcribe→align; return word timings.

        The WhisperX service does both stages and returns segments with per-word
        timestamps; this client parses that into the typed alignment result.
        """
        base, key = self._config()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body: dict = {"audio_url": audio_url, "align": True}
        if language:
            body["language"] = language

        transport = self._transport or RequestsTransport()
        resp = transport.request("POST", f"{base}/transcribe", headers=headers, json=body)
        status = int(getattr(resp, "status_code", 0))
        if not (200 <= status < 300):
            raise WhisperXError(f"whisperx transcribe failed (HTTP {status})")
        try:
            payload = resp.json()
        except Exception as exc:  # pragma: no cover - malformed body
            raise WhisperXError(f"whisperx returned a non-JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise WhisperXError(f"whisperx returned an unexpected payload type: {type(payload)}")
        return parse_alignment(payload)
