"""MiniMax Speech 02 HD on Replicate: the premium voice when ElevenLabs is not configured.

``minimax/speech-02-hd`` (input schema read from Replicate 2026-10-05): ``text``,
``voice_id`` (a MiniMax system voice), ``emotion`` (auto, happy, sad, angry,
fearful, disgusted, surprised, calm, fluent, neutral), ``speed`` 0.5-2,
``pitch``, ``volume``, ``audio_format`` mp3, ``sample_rate``, ``language_boost``.
There is no seed: takes differ by speed. Licence: MiniMax hosted API terms
(``minimax`` is ``commercial_api`` in routing.license_class).
"""

from __future__ import annotations

import os
from typing import Any

from app.domains.gateway import replicate_run

MODEL = "minimax/speech-02-hd"
VOICE_ENV = "VERY_TIME_REPLICATE_VOICE"
REPLY_VOICE_ENV = "VERY_TIME_REPLICATE_REPLY_VOICE"
# Both voices are named in the model's own voice_id description.
DEFAULT_VOICE = "English_Deep-VoicedGentleman"
DEFAULT_REPLY_VOICE = "English_Wiselady"
# Delivery -> (MiniMax emotion, speed). Deadpan is neutral and a touch slow.
DELIVERY_EMOTION: dict[str, tuple[str, float]] = {
    "deadpan": ("neutral", 0.95),
    "quiet": ("calm", 0.94),
    "tired": ("sad", 0.9),
    "warm": ("happy", 1.0),
}
_LANGUAGE_BOOST = {"en": "English", "tr": "Turkish", "de": "German", "es": "Spanish", "fr": "French",
                   "pt": "Portuguese", "ar": "Arabic", "ru": "Russian", "it": "Italian", "nl": "Dutch"}


class ReplicateSpeechError(RuntimeError):
    pass


def is_enabled() -> bool:
    return replicate_run.is_enabled()


def default_voice() -> str:
    return os.getenv(VOICE_ENV, "").strip() or DEFAULT_VOICE


def default_reply_voice() -> str:
    return os.getenv(REPLY_VOICE_ENV, "").strip() or DEFAULT_REPLY_VOICE


def build_input(text: str, *, voice_id: str = "", delivery: str = "deadpan", speed: float | None = None,
                language: str = "") -> dict:
    """The prediction input (pure)."""
    words = " ".join(str(text or "").split())
    if not words:
        raise ReplicateSpeechError("there is no text to speak")
    emotion, base_speed = DELIVERY_EMOTION.get(delivery, DELIVERY_EMOTION["deadpan"])
    value = max(0.5, min(2.0, float(speed if speed is not None else base_speed)))
    inp: dict[str, Any] = {"text": words[:10_000], "voice_id": voice_id or default_voice(), "emotion": emotion,
                           "speed": round(value, 3), "audio_format": "mp3", "sample_rate": 44100}
    boost = _LANGUAGE_BOOST.get(str(language or "").strip().lower()[:2])
    if boost:
        inp["language_boost"] = boost
    return inp


def synthesize(text: str, *, voice_id: str = "", delivery: str = "deadpan", out_path: str, speed: float | None = None,
               language: str = "", seed: int | None = None, session: Any = None) -> float:
    """Speak ``text`` into ``out_path`` (mp3); returns its length in seconds.

    ``seed`` is accepted for parity with the other voices; MiniMax has none, so
    callers vary ``speed`` to make distinct takes.
    """
    from app.services.tts.eleven_v3 import audio_seconds

    _ = seed
    try:
        url = replicate_run.run(MODEL, build_input(text, voice_id=voice_id, delivery=delivery, speed=speed,
                                                   language=language), session=session)
        replicate_run.download(url, out_path, session=session)
    except ReplicateSpeechError:
        raise
    except Exception as exc:  # noqa: BLE001 - one error type for the take picker
        raise ReplicateSpeechError(f"the voice did not render: {exc}") from exc
    return float(audio_seconds(out_path))


__all__ = ["DEFAULT_REPLY_VOICE", "DEFAULT_VOICE", "DELIVERY_EMOTION", "MODEL", "ReplicateSpeechError",
           "build_input", "default_reply_voice", "default_voice", "is_enabled", "synthesize"]
