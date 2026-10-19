"""ElevenLabs Eleven v3 voice: audio tags for delivery and two-voice dialogue.

Endpoints (read 2026-10-05):

* Text to speech: ``POST /v1/text-to-speech/{voice_id}`` with
  ``{"text", "model_id": "eleven_v3", "voice_settings", "seed"}`` and the
  ``output_format`` query parameter; the response body is the audio file.
  https://elevenlabs.io/docs/api-reference/text-to-speech/convert
* Text to dialogue: ``POST /v1/text-to-dialogue`` with
  ``{"inputs": [{"text", "voice_id"}, ...], "model_id": "eleven_v3", "settings", "seed"}``
  (seed 0 to 4294967295); the response body is the audio file. The docs list no
  with-timestamps variant for dialogue, so durations come from ffprobe.
  https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert
* Audio tags: square brackets before the words they shape, for example
  ``[whispers] I never knew``; v3 has no SSML breaks (use punctuation).
  https://elevenlabs.io/docs/best-practices/prompting/eleven-v3

Auth and error conventions follow ``elevenlabs_timestamps``: the
``xi-api-key`` header from ``config.elevenlabs["api_key"]``, retries for
transient failures and no retry for ``401/403/422`` or a disabled voice.

Default voices are ElevenLabs premade voices any account can use:
``JBFqnCBsd6RMkjVDRZzb`` ("George", calm low British male, the host) and
``21m00Tcm4TlvDq8ikWAM`` ("Rachel", calm American female, the reply). Override
with ``VERY_TIME_ELEVEN_VOICE`` and ``VERY_TIME_ELEVEN_REPLY_VOICE``.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Sequence

from loguru import logger

MODEL_V3 = "eleven_v3"
API_BASE = "https://api.elevenlabs.io/v1"
OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_REPLY_VOICE = "21m00Tcm4TlvDq8ikWAM"
VOICE_ENV = "VERY_TIME_ELEVEN_VOICE"
REPLY_VOICE_ENV = "VERY_TIME_ELEVEN_REPLY_VOICE"
MAX_TAGS = 3
MAX_SEED = 4_294_967_295
# v3 stability is a preset: 0.0 creative, 0.5 natural, 1.0 robust. Natural keeps tags audible.
STABILITY = 0.5
TIMEOUT_S = 120.0
MAX_RETRIES = 3

DELIVERY_TAGS: dict[str, tuple[str, ...]] = {
    "deadpan": ("deadpan", "flatly"),
    "quiet": ("quietly",),
    "tired": ("tired", "sighs"),
    "warm": ("warmly",),
}

_NON_RETRYABLE_CODES = frozenset({400, 401, 403, 422})
_NON_RETRYABLE_STATUSES = frozenset({"voice_disabled", "voice_access_denied", "unauthorized"})
_TAG_CLEAN = re.compile(r"[^a-z ]+")
_VOICE_ID = re.compile(r"^[A-Za-z0-9]{8,40}$")


class ElevenV3Error(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, status: int = 0) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


def api_key() -> str:
    from app.config import config

    return str(config.elevenlabs.get("api_key", "") or "").strip()


def is_enabled() -> bool:
    return bool(api_key())


def default_voice() -> str:
    return (os.getenv(VOICE_ENV) or "").strip() or DEFAULT_VOICE


def default_reply_voice() -> str:
    return (os.getenv(REPLY_VOICE_ENV) or "").strip() or DEFAULT_REPLY_VOICE


def clean_tags(tags: Sequence[str]) -> list[str]:
    out: list[str] = []
    for tag in tags or ():
        word = " ".join(_TAG_CLEAN.sub(" ", str(tag or "").lower()).split())[:24]
        if word and word not in out:
            out.append(word)
        if len(out) == MAX_TAGS:
            break
    return out


def tagged_text(text: str, tags: Sequence[str]) -> str:
    """``[deadpan] [flatly] You met me ...`` (tags letters and spaces only, at most three)."""
    words = " ".join(str(text or "").split())
    prefix = " ".join(f"[{t}]" for t in clean_tags(tags))
    return f"{prefix} {words}".strip()


def _voice(voice_id: str) -> str:
    voice = str(voice_id or "").strip()
    if not _VOICE_ID.match(voice):
        raise ElevenV3Error("the voice id is not valid")
    return voice


def _seed(seed: int | None) -> dict[str, int]:
    if seed is None:
        return {}
    return {"seed": max(0, min(MAX_SEED, int(seed)))}


def _session(session: Any):
    if session is not None:
        return session
    import requests

    return requests.Session()


def _error_status(response: Any) -> str:
    try:
        detail = response.json().get("detail", {})
        return str(detail.get("status", "")) if isinstance(detail, dict) else ""
    except Exception:  # noqa: BLE001 - best effort
        return ""


def _post_audio(url: str, payload: dict[str, Any], out_path: str, session: Any) -> None:
    key = api_key()
    if not key:
        raise ElevenV3Error("ElevenLabs is not configured")
    sess = _session(session)
    headers = {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    last = ""
    for attempt in range(MAX_RETRIES):
        try:
            response = sess.post(url, json=payload, headers=headers, params={"output_format": OUTPUT_FORMAT},
                                 timeout=TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - network errors are retried
            last = str(exc)
            logger.warning(f"eleven v3 request failed (try {attempt + 1}): {exc}")
            continue
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 200:
            content = bytes(response.content or b"")
            if not content:
                last = "empty audio"
                continue
            with open(out_path, "wb") as fh:
                fh.write(content)
            return
        error_status = _error_status(response)
        if status in _NON_RETRYABLE_CODES or error_status in _NON_RETRYABLE_STATUSES:
            raise ElevenV3Error(f"ElevenLabs refused the request ({status} {error_status})".strip(), status=status)
        last = f"status {status}"
    raise ElevenV3Error(f"ElevenLabs did not return audio ({last})", retryable=True)


def audio_seconds(path: str) -> float:
    """Duration from ffprobe (next to the ffmpeg the renders use)."""
    from app.domains.film.story8_render import ffmpeg_bin

    ffmpeg = ffmpeg_bin()
    probe = os.path.join(os.path.dirname(ffmpeg), "ffprobe")
    if os.path.exists(probe):
        done = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                              capture_output=True, text=True, timeout=60, check=False)
        try:
            return float(done.stdout.strip())
        except ValueError:
            pass
    done = subprocess.run([ffmpeg, "-hide_banner", "-i", path, "-f", "null", "-"], capture_output=True, text=True,
                          timeout=120, check=False)
    found = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", done.stderr or "")
    if not found:
        raise ElevenV3Error("could not read the audio length")
    h, m, s = found[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def synthesize(text: str, *, voice_id: str, tags: Sequence[str] = (), out_path: str, seed: int | None = None,
               session: Any = None) -> float:
    """One v3 line with delivery tags, written to ``out_path`` (mp3); returns its seconds."""
    if not str(text or "").strip():
        raise ElevenV3Error("the line is empty")
    payload = {"text": tagged_text(text, tags), "model_id": MODEL_V3,
               "voice_settings": {"stability": STABILITY, "similarity_boost": 0.75}, **_seed(seed)}
    _post_audio(f"{API_BASE}/text-to-speech/{_voice(voice_id)}", payload, out_path, session)
    return audio_seconds(out_path)


def dialogue(turns: Sequence[tuple[str, str, Sequence[str]]], *, out_path: str, seed: int | None = None,
             session: Any = None) -> float:
    """Two (or more) voices in one v3 dialogue render: ``turns`` are ``(text, voice_id, tags)``."""
    inputs = [{"text": tagged_text(text, tags), "voice_id": _voice(voice)}
              for text, voice, tags in turns if str(text or "").strip()]
    if not inputs:
        raise ElevenV3Error("the dialogue is empty")
    payload = {"inputs": inputs, "model_id": MODEL_V3, "settings": {"stability": STABILITY}, **_seed(seed)}
    _post_audio(f"{API_BASE}/text-to-dialogue", payload, out_path, session)
    return audio_seconds(out_path)


__all__ = ["DELIVERY_TAGS", "ElevenV3Error", "MODEL_V3", "audio_seconds", "clean_tags", "default_reply_voice",
           "default_voice", "dialogue", "is_enabled", "synthesize", "tagged_text"]
