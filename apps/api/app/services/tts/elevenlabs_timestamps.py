"""ElevenLabs ``/with-timestamps`` TTS adapter for ReelForge.

This adapter POSTs to ElevenLabs' ``text-to-speech/{voice_id}/with-timestamps``
endpoint, which returns both the synthesized audio (base64) and a
character-level ``alignment`` (start/end times in seconds). That alignment is
the **single source of truth** for timing across the ReelForge pipeline: it
drives BOTH the ASS karaoke captions and the avatar-duration validation. No
second forced-alignment pass is performed (see INTEGRATION_CONTRACT.md §8/§9).

The returned object is a drop-in ``SubMaker`` for MoneyPrinterTurbo's existing
``voice.create_subtitle`` / ``voice.get_audio_duration`` (the legacy
``.subs`` / ``.offset`` path). It additionally carries ``.words`` and
``.characters`` (``list[WordTiming]``, seconds) which ride along invisibly to
the legacy subtitle code and are consumed by the ReelForge caption builder.

This module reuses the auth/retry/error conventions of
``app.services.voice.elevenlabs_tts`` rather than reimplementing them: the
``xi-api-key`` header, the default ``eleven_multilingual_v2`` model, the
``voice_settings`` block, 3 retries, and the non-retryable
``{401, 403, 422}`` + ``{voice_disabled, voice_access_denied, unauthorized}``
set.
"""

import base64
from typing import NamedTuple

import requests
from loguru import logger

from app.config import config
from app.services.voice import (
    SubMaker,
    ensure_file_path_exists,
    ensure_legacy_submaker_fields,
)

_ELEVENLABS_TIMESTAMPS_URL: str = (
    "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
)
_HUNDRED_NS: int = 10_000_000

# Errors where retrying will never help (auth/access/validation failures).
# Mirrors app.services.voice.elevenlabs_tts.
_NON_RETRYABLE_CODES: frozenset[int] = frozenset({401, 403, 422})
_NON_RETRYABLE_STATUSES: frozenset[str] = frozenset(
    {"voice_disabled", "voice_access_denied", "unauthorized"}
)

_DEFAULT_MODEL_ID: str = "eleven_multilingual_v2"
_OUTPUT_FORMAT: str = "mp3_44100_128"
_REQUEST_TIMEOUT_SECONDS: float = 120.0
_MAX_RETRIES: int = 3


class WordTiming(NamedTuple):
    """Immutable word/char timing for karaoke captions (seconds)."""

    text: str
    start: float
    end: float


def elevenlabs_tts_with_timestamps(
    text: str,
    voice_id: str,
    voice_file: str,
    voice_rate: float = 1.0,
    voice_volume: float = 1.0,
    model_id: str = "",
) -> SubMaker | None:
    """Synthesize speech with character-level timestamps.

    POSTs to ``/with-timestamps``, base64-decodes ``audio_base64`` to
    ``voice_file`` (mp3), and builds a ``SubMaker`` carrying the legacy
    ``.subs`` / ``.offset`` fields (one segment per non-space char) plus the
    ReelForge ``.words`` / ``.characters`` (``list[WordTiming]``, seconds).

    Uses ``alignment`` (NOT ``normalized_alignment``) so caption text matches
    the user's script. Retries up to 3 times; the non-retryable set
    (``{401, 403, 422}`` + ``{voice_disabled, voice_access_denied,
    unauthorized}``) short-circuits. Returns ``None`` on failure so the caller
    can fall back without crashing the pipeline.

    Note: ``voice_rate`` / ``voice_volume`` are accepted for signature parity
    with the other TTS providers and the ``tts()`` dispatcher, but ElevenLabs'
    ``/with-timestamps`` endpoint exposes no rate/volume field (matching the
    behaviour of ``elevenlabs_tts``), so they are intentionally unused here.
    """
    text = (text or "").strip()
    if not text:
        logger.error("ElevenLabs timestamps TTS text is empty")
        return None

    if not voice_id:
        logger.error("ElevenLabs timestamps TTS voice_id is empty")
        return None

    api_key = config.elevenlabs.get("api_key", "")
    if not api_key:
        logger.error("ElevenLabs API key is not set")
        return None

    if not model_id:
        model_id = config.elevenlabs.get("model_id", _DEFAULT_MODEL_ID)

    url = _ELEVENLABS_TIMESTAMPS_URL.format(voice_id=voice_id)
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }
    params = {"output_format": _OUTPUT_FORMAT}

    for attempt in range(_MAX_RETRIES):
        try:
            logger.info(
                f"start elevenlabs timestamps tts, voice_id: {voice_id}, "
                f"try: {attempt + 1}"
            )

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                params=params,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                error_status = _extract_error_status(response)
                if (
                    response.status_code in _NON_RETRYABLE_CODES
                    or error_status in _NON_RETRYABLE_STATUSES
                ):
                    logger.error(
                        "ElevenLabs timestamps TTS failed (non-retryable) — "
                        f"voice_id: {voice_id}, status: {response.status_code}, "
                        f"error: {error_status or response.text[:200]}. "
                        "Please select a different ElevenLabs voice."
                    )
                    return None

                logger.error(
                    "elevenlabs timestamps tts failed with status "
                    f"{response.status_code}: {response.text[:200]}"
                )
                continue

            data = response.json()
            sub_maker = _decode_and_build(data, voice_file)
            if sub_maker is None:
                # Malformed but 200 response: retry may yield a valid payload.
                continue

            logger.success(f"elevenlabs timestamps tts succeeded: {voice_file}")
            return sub_maker
        except Exception as e:  # noqa: BLE001 - never crash the pipeline
            logger.error(f"elevenlabs timestamps tts failed: {e!s}")

    return None


def _extract_error_status(response: "requests.Response") -> str:
    """Best-effort read of ElevenLabs' ``detail.status`` from an error body."""
    try:
        detail = response.json().get("detail", {})
        if isinstance(detail, dict):
            return detail.get("status", "") or ""
    except Exception:  # noqa: BLE001 - error body may not be JSON
        pass
    return ""


def _decode_and_build(data: dict, voice_file: str) -> SubMaker | None:
    """Decode ``audio_base64`` to ``voice_file`` and build the SubMaker.

    Uses ``alignment`` (not ``normalized_alignment``) so caption text matches
    the user's original script. Returns ``None`` on a structurally invalid
    payload so the caller can retry.
    """
    audio_b64 = data.get("audio_base64")
    alignment = data.get("alignment")
    if not audio_b64 or not isinstance(alignment, dict):
        logger.error(
            "elevenlabs timestamps response missing audio_base64 or alignment"
        )
        return None

    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []

    if not characters or not (len(characters) == len(starts) == len(ends)):
        logger.error(
            "elevenlabs timestamps alignment is empty or length-mismatched "
            f"(chars={len(characters)}, starts={len(starts)}, ends={len(ends)})"
        )
        return None

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception as e:  # noqa: BLE001
        logger.error(f"failed to base64-decode elevenlabs audio: {e!s}")
        return None

    if not audio_bytes:
        logger.error("elevenlabs timestamps decoded audio is empty")
        return None

    ensure_file_path_exists(voice_file)
    with open(voice_file, "wb") as f:
        f.write(audio_bytes)

    return _build_submaker_from_elevenlabs_alignment(characters, starts, ends)


def _build_submaker_from_elevenlabs_alignment(
    characters: list[str],
    starts: list[float],
    ends: list[float],
) -> SubMaker:
    """Build a legacy-compatible ``SubMaker`` from a character alignment.

    Emits ONE legacy ``.subs`` / ``.offset`` segment PER non-space character so
    the tolerant ``voice._match_script_line`` accumulator can rebuild exact
    sentence counts. ``.offset`` units are ``(start_100ns, end_100ns)`` tuples
    (100-nanosecond ticks), matching ``edge_tts`` and the rest of the legacy
    subtitle path. ``.cues`` is left empty so ``create_subtitle`` takes the
    legacy branch.

    Also attaches ReelForge karaoke data:
      * ``.characters`` — one :class:`WordTiming` per glyph (seconds).
      * ``.words`` — whitespace-grouped :class:`WordTiming` (seconds); a word's
        start is its first char's start and its end is its last non-space
        char's end.
    """
    sub_maker = ensure_legacy_submaker_fields(SubMaker())
    # Reset in case a caller reuses an object; avoids stale accumulation.
    sub_maker.subs = []
    sub_maker.offset = []

    char_timings: list[WordTiming] = []
    words: list[WordTiming] = []

    # Word accumulator state.
    word_chars: list[str] = []
    word_start: float | None = None
    word_end: float | None = None

    def _flush_word() -> None:
        nonlocal word_chars, word_start, word_end
        if word_chars and word_start is not None and word_end is not None:
            words.append(
                WordTiming(text="".join(word_chars), start=word_start, end=word_end)
            )
        word_chars = []
        word_start = None
        word_end = None

    for char, start, end in zip(characters, starts, ends):
        # Guard against non-numeric alignment entries.
        try:
            start_s = float(start)
            end_s = float(end)
        except (TypeError, ValueError):
            continue

        char_timings.append(WordTiming(text=char, start=start_s, end=end_s))

        if char.isspace():
            # Whitespace is a word boundary; it carries no legacy segment.
            _flush_word()
            continue

        # One legacy segment per non-space glyph.
        start_100ns = max(int(round(start_s * _HUNDRED_NS)), 0)
        end_100ns = max(int(round(end_s * _HUNDRED_NS)), start_100ns)
        sub_maker.subs.append(char)
        sub_maker.offset.append((start_100ns, end_100ns))

        # Grow the current word.
        word_chars.append(char)
        if word_start is None:
            word_start = start_s
        word_end = end_s

    _flush_word()

    sub_maker.characters = char_timings
    sub_maker.words = words
    return sub_maker
