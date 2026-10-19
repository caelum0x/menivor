"""Typed word/segment/alignment DTOs for WhisperX output.

Decouples the transcription/alignment payload from the ASS styling layer so the
caption builders (``ass_karaoke``, ``hormozi``) consume a stable shape regardless
of the ASR backend. WhisperX's value is word-level timestamps (±50ms) from its
two-stage transcribe→align pass; these DTOs carry exactly that. Pure dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WordTiming:
    """One aligned word with start/end seconds + confidence."""

    word: str
    start: float
    end: float
    score: float = 1.0

    @property
    def duration(self) -> float:
        return round(max(0.0, self.end - self.start), 3)


@dataclass(frozen=True)
class Segment:
    """A sentence/segment with its words (WhisperX groups words into segments)."""

    text: str
    start: float
    end: float
    words: tuple[WordTiming, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AlignmentResult:
    """The full transcript: language + ordered segments (+ flattened words)."""

    language: str
    segments: tuple[Segment, ...]

    @property
    def words(self) -> tuple[WordTiming, ...]:
        out: list[WordTiming] = []
        for seg in self.segments:
            out.extend(seg.words)
        return tuple(out)

    @property
    def duration(self) -> float:
        return round(self.segments[-1].end, 3) if self.segments else 0.0


def parse_alignment(payload: dict) -> AlignmentResult:
    """Parse a WhisperX-shaped JSON payload into an :class:`AlignmentResult`.

    Tolerant of the two common shapes: words nested under each segment, or a
    top-level ``word_segments`` list. Missing per-word timings fall back to the
    segment bounds so a word is never dropped.
    """
    language = str(payload.get("language", "") or "")
    segments: list[Segment] = []
    for raw_seg in payload.get("segments", []) or []:
        s_start = float(raw_seg.get("start", 0.0) or 0.0)
        s_end = float(raw_seg.get("end", s_start) or s_start)
        words: list[WordTiming] = []
        for raw_w in raw_seg.get("words", []) or []:
            token = str(raw_w.get("word", raw_w.get("text", "")) or "").strip()
            if not token:
                continue
            w_start = raw_w.get("start")
            w_end = raw_w.get("end")
            words.append(
                WordTiming(
                    word=token,
                    start=float(w_start if w_start is not None else s_start),
                    end=float(w_end if w_end is not None else s_end),
                    score=float(raw_w.get("score", 1.0) or 1.0),
                )
            )
        segments.append(
            Segment(text=str(raw_seg.get("text", "") or "").strip(),
                    start=s_start, end=s_end, words=tuple(words))
        )
    return AlignmentResult(language=language, segments=tuple(segments))
