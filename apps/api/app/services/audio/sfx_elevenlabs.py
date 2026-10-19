"""ElevenLabs Sound Effects (text to a short diegetic sound) for per-beat SFX.

``POST https://api.elevenlabs.io/v1/sound-generation`` (docs read 2026-10-05,
https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert):

* query ``output_format`` (``mp3_44100_128`` here);
* body ``text`` (required), ``duration_seconds`` (0.5 to 30, optional),
  ``prompt_influence`` (0 to 1, default 0.3), ``model_id``
  (default ``eleven_text_to_sound_v2``), ``loop`` (v2 only);
* 200 returns the audio bytes; 422 is a validation error.

Auth is the ``xi-api-key`` header from ``config.elevenlabs["api_key"]``
(``ELEVENLABS_API_KEY``). 401/403/422 are final; 429 and 5xx are retried once.
"""

from __future__ import annotations

import os
from typing import Any

URL = "https://api.elevenlabs.io/v1/sound-generation"
MODEL_ID = "eleven_text_to_sound_v2"
OUTPUT_FORMAT = "mp3_44100_128"
MIN_SECONDS = 0.5
MAX_SECONDS = 30.0
MAX_TEXT = 450
TIMEOUT_S = 90.0
_FINAL = frozenset({401, 403, 422})


class SfxError(RuntimeError):
    def __init__(self, message: str, *, status: int = 0, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def _api_key() -> str:
    try:
        from app.config import config

        key = str(config.elevenlabs.get("api_key", "") or "")
    except Exception:  # noqa: BLE001 - config may be incomplete in tools/tests
        key = ""
    return key or os.getenv("ELEVENLABS_API_KEY", "")


def is_enabled() -> bool:
    return bool(_api_key().strip())


def _session(session: Any):
    if session is not None:
        return session
    import requests

    return requests.Session()


def generate_sfx(text: str, *, seconds: float, out_path: str, prompt_influence: float = 0.4,
                 session: Any = None) -> str:
    """Generate one sound effect into ``out_path`` (mp3) and return the path."""
    prompt = " ".join(str(text or "").split())[:MAX_TEXT]
    if not prompt:
        raise SfxError("a sound description is required", status=422)
    key = _api_key().strip()
    if not key:
        raise SfxError("ElevenLabs is not configured", status=401)
    body = {
        "text": prompt,
        "duration_seconds": round(min(MAX_SECONDS, max(MIN_SECONDS, float(seconds))), 2),
        "prompt_influence": round(min(1.0, max(0.0, float(prompt_influence))), 2),
        "model_id": MODEL_ID,
    }
    headers = {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    sess = _session(session)
    last: SfxError | None = None
    for _ in range(2):
        try:
            resp = sess.post(URL, json=body, headers=headers, params={"output_format": OUTPUT_FORMAT},
                             timeout=TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - network errors are retryable once
            last = SfxError(f"sound effects request failed: {type(exc).__name__}", retryable=True)
            continue
        status = int(getattr(resp, "status_code", 0) or 0)
        if status == 200:
            audio = resp.content or b""
            if not audio:
                raise SfxError("sound effects returned no audio", status=200)
            with open(out_path, "wb") as fh:
                fh.write(audio)
            return out_path
        if status in _FINAL:
            raise SfxError(f"sound effects refused the request ({status})", status=status)
        last = SfxError(f"sound effects failed ({status})", status=status,
                        retryable=status == 429 or status >= 500)
        if not last.retryable:
            raise last
    raise last or SfxError("sound effects failed")


__all__ = ["MODEL_ID", "SfxError", "URL", "generate_sfx", "is_enabled"]
