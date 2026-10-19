"""Chapter-to-audio synthesis over the Kokoro sidecar (pure logic + injected client).

A chapter is split into sentence-aligned chunks no longer than the sidecar's
per-request cap, each chunk is synthesized as MP3 and the MP3 byte streams are
concatenated. MPEG audio frames are self-delimiting, so a concatenation of
same-format MP3 streams plays back as one continuous file in every mainstream
player (no re-encode, no ffmpeg needed).

Kokoro is opt-in: :func:`require_enabled` fails with 503 unless ``KOKORO_URL``
points at the sidecar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from app.domains.routing.providers.kokoro import (
    DEFAULT_VOICE,
    MAX_INPUT_CHARS,
    SpeechResult,
    kokoro_url,
)

# One export request covers at most this many characters (~25 minutes of
# speech). The app splits longer chapters into parts before calling.
MAX_CHAPTER_CHARS = 20_000
# Chunk size sent to the sidecar per call (well under MAX_INPUT_CHARS).
CHUNK_CHARS = 1_200

_SENTENCE_END = re.compile(r"(?<=[.!?…。！？])[\"'”’)\]]*\s+")
_WS = re.compile(r"\s+")


class AudiobookError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class SpeechClient(Protocol):
    def synthesize(
        self, text: str, *, voice: str, speed: float, response_format: str
    ) -> SpeechResult: ...


@dataclass(frozen=True)
class ChapterAudio:
    audio: bytes
    content_type: str
    characters: int
    chunks: int
    voice: str


def require_enabled(env: Mapping[str, str] | None = None) -> str:
    base = kokoro_url(env)
    if not base:
        raise AudiobookError(503, "audiobook export is not enabled on this server")
    return base


def _split_long(sentence: str, limit: int) -> list[str]:
    """Split one over-long sentence on word boundaries (hard-cut single huge words)."""
    parts: list[str] = []
    current = ""
    for word in sentence.split(" "):
        while len(word) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(word[:limit])
            word = word[limit:]
        candidate = f"{current} {word}".strip() if current else word
        if len(candidate) > limit:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return [p for p in parts if p]


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Sentence-aligned chunks, each ``<= limit`` characters, whitespace-normalized."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    normalized = _WS.sub(" ", str(text or "")).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(normalized):
        sentence = sentence.strip()
        if not sentence:
            continue
        pieces = [sentence] if len(sentence) <= limit else _split_long(sentence, limit)
        for piece in pieces:
            candidate = f"{current} {piece}" if current else piece
            if len(candidate) <= limit:
                current = candidate
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def synthesize_chapter(
    client: SpeechClient,
    text: str,
    *,
    voice: str = DEFAULT_VOICE,
    speed: float = 1.0,
) -> ChapterAudio:
    """Synthesize one chapter (or chapter part) to a single MP3 byte stream."""
    chunks = chunk_text(text, min(CHUNK_CHARS, MAX_INPUT_CHARS))
    if not chunks:
        raise AudiobookError(400, "chapter text is empty")
    total_chars = sum(len(c) for c in chunks)
    if total_chars > MAX_CHAPTER_CHARS:
        raise AudiobookError(
            413, f"chapter part exceeds {MAX_CHAPTER_CHARS} characters; split it"
        )
    audio_parts: list[bytes] = []
    used_voice = voice or DEFAULT_VOICE
    for chunk in chunks:
        result = client.synthesize(
            chunk, voice=used_voice, speed=speed, response_format="mp3"
        )
        audio_parts.append(result.audio)
        used_voice = result.voice
    return ChapterAudio(
        audio=b"".join(audio_parts),
        content_type="audio/mpeg",
        characters=total_chars,
        chunks=len(chunks),
        voice=used_voice,
    )
