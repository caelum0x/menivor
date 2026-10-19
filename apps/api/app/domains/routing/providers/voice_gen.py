"""Voice (text-to-speech) generation — REAL media-stack adapters.

The gateway's **voice** backend, served under the ``audio`` modality alongside
Suno music. Two adapters share one shape so a single execution branch covers the
primary and the self-hosted fallbacks (CTO plan §10.6):

  * :class:`ElevenLabsVoiceAdapter` — ElevenLabs TTS. Synchronous: ``submit`` POSTs
    the script and gets **binary audio bytes** back (no hosted URL), so it runs an
    **output-hosting step** (:func:`host_audio_bytes`) that stores the clip in R2
    and returns a presigned ``https`` URL — the exact ``output_url`` shape Suno's
    provider hands back directly.
  * :class:`SelfHostVoiceAdapter` — a parameterized adapter for the free/OSS
    voices behind ElevenLabs (Chatterbox/Kokoro/EdgeTTS). These self-hosted
    services may return a hosted ``audio_url`` directly (used as-is) or base64/raw
    bytes (hosted the same way as ElevenLabs).

Both are synchronous, so ``submit`` yields a terminal clip and there is no poll
step. Imports ``requests`` lazily; runs live with a real ``ELEVENLABS_API_KEY``
(``xi-api-key``). The inline ``data:`` audio form is intentionally NOT used: the
provider-execution contract only permits inline data for images, so voice output
must be a real ``https`` URL.
"""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from app.domains.routing.providers.kling_fal import (
    ACCEPTANCE_DEFINITE_NO,
    ACCEPTANCE_UNKNOWN,
    KlingError as ProviderCallError,
)

_ELEVENLABS_BASE = "https://api.elevenlabs.io"
_DEFAULT_TTS_MODEL = "eleven_multilingual_v2"
_AUDIO_CONTENT_TYPE = "audio/mpeg"


def host_audio_bytes(
    data: bytes,
    content_type: str = _AUDIO_CONTENT_TYPE,
    *,
    key_prefix: str = "prism/voice",
) -> str:
    """Store synthesized audio in R2 and return a presigned ``https`` GET URL.

    This is the voice **output-hosting step**: providers that return raw audio
    bytes (rather than a provider-hosted URL like Suno) get a real, renderable
    ``output_url`` here. The object key is generated server-side so a clip is
    never addressable by a caller-supplied path.
    """
    if not data:
        raise ProviderCallError("voice synthesis produced no audio", kind="provider")
    from app.platform.storage.r2 import get_r2_client

    client = get_r2_client()
    key = f"{key_prefix}/{uuid4().hex}.mp3"
    client.upload_bytes(key, data, content_type)
    return client.presign_result_get(key)


@dataclass
class VoiceClip:
    run_id: str
    output_url: str = ""
    characters: int = 0
    raw: dict = field(default_factory=dict)


class _VoiceHTTP:
    """Shared retry/status handling for the voice adapters (mirrors SunoAdapter)."""

    provider_key = "voice"

    def __init__(
        self,
        *,
        session: Any = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        self._session = session
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._sleep = sleep

    def _sess(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _call(
        self,
        method: str,
        url: str,
        *,
        headers: dict,
        json: dict | None = None,
    ):
        import requests

        is_submit = method.upper() == "POST"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._sess().request(
                    method, url, headers=headers, json=json, timeout=self._timeout
                )
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"{self.provider_key} network error: {exc}",
                    kind="transient",
                    retryable=True,
                    acceptance=ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO,
                ) from exc
            status = resp.status_code
            if 200 <= status < 300:
                return resp
            if status in (401, 403):
                raise ProviderCallError(
                    f"{self.provider_key} auth failed (HTTP {status})",
                    kind="auth",
                    status=status,
                )
            if status in (400, 422):
                raise ProviderCallError(
                    f"{self.provider_key} rejected request (HTTP {status})",
                    kind="validation",
                    status=status,
                )
            if status == 429:
                if attempt <= self._max_retries:
                    self._sleep(min(30.0, 2**attempt))
                    continue
                raise ProviderCallError(
                    f"{self.provider_key} rate limit",
                    kind="rate_limit",
                    retryable=True,
                    status=429,
                )
            if status == 408 or status >= 500:
                if not is_submit and attempt <= self._max_retries:
                    self._sleep(min(20.0, 2 ** (attempt - 1)))
                    continue
                raise ProviderCallError(
                    f"{self.provider_key} server error (HTTP {status})",
                    kind="transient",
                    retryable=True,
                    status=status,
                    acceptance=ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO,
                )
            raise ProviderCallError(
                f"{self.provider_key} unexpected status {status}",
                kind="provider",
                status=status,
            )


class ElevenLabsVoiceAdapter(_VoiceHTTP):
    """ElevenLabs TTS — synchronous, byte-returning, R2-hosted output."""

    provider_key = "elevenlabs"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = _DEFAULT_TTS_MODEL,
        base_url: str | None = None,
        session: Any = None,
        host_fn: Callable[[bytes], str] | None = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        super().__init__(
            session=session, timeout_s=timeout_s, max_retries=max_retries, sleep=sleep
        )
        self._api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
        self._model = model or _DEFAULT_TTS_MODEL
        self._base_url = (
            base_url or os.getenv("ELEVENLABS_BASE_URL", _ELEVENLABS_BASE)
        ).rstrip("/")
        self._host = host_fn or host_audio_bytes

    def _headers(self) -> dict:
        if not self._api_key:
            raise ProviderCallError("ELEVENLABS_API_KEY not configured", kind="auth")
        return {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": _AUDIO_CONTENT_TYPE,
        }

    def submit(self, *, prompt: str, voice_id: str = "") -> VoiceClip:
        text = str(prompt or "")
        if not text:
            raise ProviderCallError("a prompt (text) is required", kind="validation")
        vid = str(voice_id or "").strip()
        if not vid:
            raise ProviderCallError(
                "elevenlabs requires a voice_id", kind="validation"
            )
        resp = self._call(
            "POST",
            f"{self._base_url}/v1/text-to-speech/{vid}",
            headers=self._headers(),
            json={"text": text, "model_id": self._model},
        )
        output_url = self._host(resp.content)
        return VoiceClip(
            run_id=str(resp.headers.get("request-id") or uuid4().hex),
            output_url=output_url,
            characters=len(text),
        )


class SelfHostVoiceAdapter(_VoiceHTTP):
    """Self-hosted / free TTS (Chatterbox, Kokoro, EdgeTTS) — one shape, many keys.

    The endpoint may return a hosted ``audio_url`` directly (used as-is) or
    base64/raw bytes, which are hosted through :func:`host_audio_bytes`.
    """

    def __init__(
        self,
        *,
        provider_key: str,
        model: str = "",
        base_url: str | None = None,
        synth_path: str = "/tts",
        api_key: str = "",
        session: Any = None,
        host_fn: Callable[[bytes], str] | None = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        super().__init__(
            session=session, timeout_s=timeout_s, max_retries=max_retries, sleep=sleep
        )
        self.provider_key = provider_key
        self._model = model
        env_key = f"{provider_key.upper().replace('-', '_')}_API_KEY"
        self._api_key = api_key or os.getenv(env_key, "")
        self._base_url = (
            base_url or os.getenv(f"{provider_key.upper().replace('-', '_')}_BASE_URL", "")
        ).rstrip("/")
        self._synth_path = synth_path
        self._host = host_fn or host_audio_bytes

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        # Free/unauthenticated backends (EdgeTTS) attach no auth header.
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def submit(
        self, *, prompt: str, voice_id: str = "", language: str = ""
    ) -> VoiceClip:
        text = str(prompt or "")
        if not text:
            raise ProviderCallError("a prompt (text) is required", kind="validation")
        if not self._base_url:
            raise ProviderCallError(
                f"{self.provider_key} base URL not configured", kind="validation"
            )
        resp = self._call(
            "POST",
            f"{self._base_url}{self._synth_path}",
            headers=self._headers(),
            json={
                "text": text,
                "voice": str(voice_id or self._model or ""),
                "language": str(language or "auto"),
            },
        )
        body = self._json(resp)
        # 1) Already-hosted URL from the self-host service.
        hosted = str(body.get("audio_url") or "").strip()
        if hosted:
            output_url = hosted
        else:
            # 2) Base64 payload, else 3) raw audio bytes — hosted to R2.
            b64 = str(body.get("audio_base64") or body.get("audio") or "")
            data = base64.b64decode(b64) if b64 else resp.content
            output_url = self._host(data)
        return VoiceClip(
            run_id=str(body.get("id") or uuid4().hex),
            output_url=output_url,
            characters=len(text),
            raw=body,
        )

    @staticmethod
    def _json(resp) -> dict:
        try:
            body = resp.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {}
