"""Extra tracks for packaging (MV3): WebVTT subtitles and alternate audio (dubs).

Captions stay burned into reels (M2.4); an OTT title can also carry WebVTT per
language (MV16 generates them, ``domains/dub`` makes dubbed audio). This module
only turns what exists into packager stream descriptors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_LANG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


@dataclass(frozen=True)
class Track:
    kind: str  # "text" or "audio"
    path: str
    language: str
    name: str


def check_language(language: str) -> str:
    if not _LANG.match(language or ""):
        raise ValueError(f"not a language tag: {language!r}")
    return language


def subtitle(path: str, language: str, name: str = "") -> Track:
    return Track("text", path, check_language(language), name or language)


def dub(path: str, language: str, name: str = "") -> Track:
    return Track("audio", path, check_language(language), name or language)


def is_webvtt(text: str) -> bool:
    return text.lstrip("﻿").startswith("WEBVTT")


__all__ = ["Track", "check_language", "dub", "is_webvtt", "subtitle"]
