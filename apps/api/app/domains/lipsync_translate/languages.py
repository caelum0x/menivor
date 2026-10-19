"""Target languages for lip-sync translation (ElevenLabs multilingual TTS coverage)."""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
    "nl": "Dutch", "pl": "Polish", "sv": "Swedish", "da": "Danish", "fi": "Finnish", "no": "Norwegian",
    "cs": "Czech", "sk": "Slovak", "ro": "Romanian", "hu": "Hungarian", "el": "Greek", "bg": "Bulgarian",
    "hr": "Croatian", "uk": "Ukrainian", "ru": "Russian", "tr": "Turkish", "ar": "Arabic", "hi": "Hindi",
    "ta": "Tamil", "id": "Indonesian", "ms": "Malay", "fil": "Filipino", "vi": "Vietnamese", "ja": "Japanese",
    "ko": "Korean", "zh": "Chinese",
}
MAX_TARGETS = 10


def label(code: str) -> str:
    return LANGUAGES.get(code, code)


def catalog() -> list[dict[str, str]]:
    return [{"code": k, "label": v} for k, v in LANGUAGES.items()]


__all__ = ["LANGUAGES", "MAX_TARGETS", "catalog", "label"]
