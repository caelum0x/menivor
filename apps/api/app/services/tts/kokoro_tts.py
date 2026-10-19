"""Kokoro narration with word timings, for the reel pipeline (M1.4).

Kokoro-82M (Apache-2.0 weights) runs as the Kokoro-FastAPI sidecar
(infra-box ``stacks/kokoro``, box 1). We only talk to it over HTTP, so its
phonemizer data (espeak-ng, GPL-3.0) stays inside that container.

This adapter calls the sidecar's ``POST /dev/captioned_speech`` endpoint, which
returns the audio (base64) and per-word timestamps in one response. Those
timestamps are the single timing authority for the reel (the same role the
ElevenLabs alignment and the edge-tts WordBoundary cues play), so no ASR pass is
needed for our own narration.

The returned object is a drop-in ``SubMaker`` for ``voice.get_audio_duration``
and ``voice.create_subtitle`` (legacy ``.subs`` / ``.offset`` path, one segment
per word) and carries ``.words`` (``list[WordTiming]``, seconds) for the
caption builder.

Nothing here raises to the caller: any failure returns ``None`` and is logged,
so the narration chain can fall back to edge-tts.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Callable, Mapping

import requests
from loguru import logger

from app.services.tts.elevenlabs_timestamps import WordTiming
from app.services.voice import (
    SubMaker,
    ensure_file_path_exists,
    ensure_legacy_submaker_fields,
)

KOKORO_PREFIX = "kokoro:"
CAPTIONED_PATH = "/dev/captioned_speech"
MAX_INPUT_CHARS = 5_000
MIN_SPEED = 0.5
MAX_SPEED = 2.0
_HUNDRED_NS = 10_000_000
_DEFAULT_TIMEOUT_S = 120.0

# (url, json, timeout) -> (status_code, parsed_json_or_None, text_excerpt)
PostFn = Callable[[str, dict, float], "tuple[int, Any, str]"]


def _requests_post(url: str, payload: dict, timeout: float) -> tuple[int, Any, str]:
    resp = requests.post(url, json=payload, timeout=timeout)
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body, (resp.text or "")[:200]


def kokoro_base_url(env: Mapping[str, str] | None = None) -> str:
    """The sidecar base URL (``KOKORO_URL``), or ``""`` when Kokoro is off."""
    source = env if env is not None else os.environ
    return str(source.get("KOKORO_URL", "") or "").strip().rstrip("/")


def timeout_seconds(env: Mapping[str, str] | None = None) -> float:
    source = env if env is not None else os.environ
    raw = str(source.get("MENIVOR_KOKORO_TIMEOUT_S", "") or "").strip()
    try:
        value = float(raw) if raw else _DEFAULT_TIMEOUT_S
    except ValueError:
        return _DEFAULT_TIMEOUT_S
    return value if value > 0 else _DEFAULT_TIMEOUT_S


def clamp_speed(rate: Any) -> float:
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return 1.0
    if value != value or value <= 0:  # NaN or non-positive
        return 1.0
    return max(MIN_SPEED, min(MAX_SPEED, value))


def voice_id_from_name(voice_name: str) -> str:
    """``kokoro:af_heart`` (optionally ``-Female``/``-Male``) -> ``af_heart``."""
    name = str(voice_name or "").strip()
    if name.startswith(KOKORO_PREFIX):
        name = name[len(KOKORO_PREFIX):]
    for suffix in ("-Female", "-Male"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _is_word(token: str) -> bool:
    return any(ch.isalnum() for ch in token)


def _parse_timestamps(raw: Any) -> list[WordTiming]:
    """Kokoro ``timestamps`` -> word timings; punctuation joins the previous word."""
    if not isinstance(raw, list):
        return []
    words: list[WordTiming] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("word", item.get("text", "")) or "").strip()
        try:
            start = float(item.get("start_time", item.get("start")))
            end = float(item.get("end_time", item.get("end")))
        except (TypeError, ValueError):
            continue
        if not text or end < start or start < 0:
            continue
        if not _is_word(text):
            if words:
                prev = words[-1]
                words[-1] = WordTiming(prev.text + text, prev.start, max(prev.end, end))
            continue
        words.append(WordTiming(text, start, end))
    return words


def build_submaker(words: list[WordTiming]) -> SubMaker:
    """A legacy-compatible SubMaker with one ``.subs`` segment per word."""
    sub_maker = ensure_legacy_submaker_fields(SubMaker())
    sub_maker.subs = [w.text for w in words]
    offsets = []
    for w in words:
        start = max(int(round(w.start * _HUNDRED_NS)), 0)
        offsets.append((start, max(int(round(w.end * _HUNDRED_NS)), start)))
    sub_maker.offset = offsets
    sub_maker.words = list(words)
    sub_maker.characters = []
    return sub_maker


def kokoro_tts(
    text: str,
    voice_name: str,
    voice_file: str,
    voice_rate: float = 1.0,
    *,
    base_url: str | None = None,
    post_fn: PostFn | None = None,
    env: Mapping[str, str] | None = None,
) -> SubMaker | None:
    """Narrate ``text`` with a Kokoro voice; ``None`` on any failure."""
    base = (base_url if base_url is not None else kokoro_base_url(env)).rstrip("/")
    if not base:
        logger.info("kokoro tts skipped: KOKORO_URL is not set")
        return None
    clean = str(text or "").strip()
    voice = voice_id_from_name(voice_name)
    if not clean or not voice:
        logger.error("kokoro tts needs text and a voice")
        return None
    if len(clean) > MAX_INPUT_CHARS:
        logger.warning(f"kokoro tts skipped: script is over {MAX_INPUT_CHARS} characters")
        return None
    payload = {
        "model": "kokoro",
        "input": clean,
        "voice": voice,
        "response_format": "mp3",
        "speed": clamp_speed(voice_rate),
        "stream": False,
        "return_timestamps": True,
    }
    post = post_fn or _requests_post
    try:
        status, body, excerpt = post(f"{base}{CAPTIONED_PATH}", payload, timeout_seconds(env))
    except Exception as exc:  # noqa: BLE001 - network/timeouts fall back to edge-tts
        logger.warning(f"kokoro tts request failed: {exc}")
        return None
    if status != 200 or not isinstance(body, dict):
        logger.warning(f"kokoro tts failed with status {status}: {excerpt}")
        return None
    words = _parse_timestamps(body.get("timestamps"))
    if not words:
        logger.warning("kokoro tts returned no word timestamps")
        return None
    try:
        audio = base64.b64decode(str(body.get("audio") or ""), validate=False)
    except (ValueError, TypeError) as exc:
        logger.warning(f"kokoro tts audio could not be decoded: {exc}")
        return None
    if not audio:
        logger.warning("kokoro tts returned no audio")
        return None
    ensure_file_path_exists(voice_file)
    with open(voice_file, "wb") as fh:
        fh.write(audio)
    logger.success(f"kokoro tts succeeded: voice={voice} words={len(words)}")
    return build_submaker(words)
