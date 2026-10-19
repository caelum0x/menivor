"""Pure clipping planning logic (no DB, no ffmpeg, no network).

REUSES :func:`app.domains.repurpose.policy.select_highlights` for the
duration-band + score-floor + non-overlapping + top-N selection rather than
re-deriving it, then adds clipping-specific helpers that map the selected
highlight windows onto concrete cut points snapped to WhisperX word boundaries.

Every function here is deterministic and side-effect free so the core product
logic is exhaustively unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.domains.repurpose.policy import (
    DEFAULT_MAX_CLIPS,
    DEFAULT_MAX_LEN_S,
    DEFAULT_MIN_LEN_S,
    DEFAULT_MIN_SCORE,
    Candidate,
    select_highlights,
)

__all__ = [
    "Word",
    "ClipPlan",
    "cut_points_from_window",
    "plan_clips",
    "should_stitch",
    "segments_from_words",
]


@dataclass(frozen=True)
class Word:
    """A single WhisperX word timing (seconds)."""

    text: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class ClipPlan:
    """A resolved short clip: word-boundary-snapped cut points + metadata."""

    start_s: float
    end_s: float
    score: int
    title: str = ""
    hook: str = ""
    transcript: str = ""
    reason: str = ""

    @property
    def length_s(self) -> float:
        return round(max(0.0, float(self.end_s) - float(self.start_s)), 3)


def _as_word(item: object) -> Word | None:
    """Coerce a Word / mapping / (text, start, end)-like into a :class:`Word`."""
    if isinstance(item, Word):
        return item
    if isinstance(item, dict):
        text = str(item.get("text", "") or "")
        start = item.get("start_s", item.get("start"))
        end = item.get("end_s", item.get("end"))
    else:
        text = str(getattr(item, "text", "") or "")
        start = getattr(item, "start_s", getattr(item, "start", None))
        end = getattr(item, "end_s", getattr(item, "end", None))
    if start is None or end is None:
        return None
    try:
        s = float(start)
        e = float(end)
    except (TypeError, ValueError):
        return None
    return Word(text=text, start_s=s, end_s=max(e, s))


def _normalize_words(words: Sequence[object]) -> list[Word]:
    """Coerce + drop unusable entries, keeping reading order."""
    out: list[Word] = []
    for item in words or []:
        w = _as_word(item)
        if w is not None:
            out.append(w)
    return out


def cut_points_from_window(
    words: Sequence[object], start_s: float, end_s: float
) -> tuple[float, float]:
    """Snap a desired ``[start_s, end_s]`` window to WhisperX word boundaries.

    The snapped start is the start of the first word that is not entirely before
    the window; the snapped end is the end of the last word that begins before the
    window ends. When no words fall inside the window the raw bounds are returned
    unchanged (so a speechless window degrades gracefully).
    """
    lo = min(float(start_s), float(end_s))
    hi = max(float(start_s), float(end_s))
    normalized = _normalize_words(words)
    inside = [w for w in normalized if w.end_s > lo and w.start_s < hi]
    if not inside:
        return lo, hi
    snapped_start = min(w.start_s for w in inside)
    snapped_end = max(w.end_s for w in inside)
    return round(snapped_start, 3), round(max(snapped_end, snapped_start), 3)


def _transcript_for_window(
    words: Sequence[object], start_s: float, end_s: float
) -> str:
    """Join the text of every word whose span overlaps ``[start_s, end_s]``."""
    lo = min(float(start_s), float(end_s))
    hi = max(float(start_s), float(end_s))
    tokens = [
        w.text.strip()
        for w in _normalize_words(words)
        if w.end_s > lo and w.start_s < hi and w.text.strip()
    ]
    return " ".join(tokens)


def _candidate_from_segment(seg: object) -> Candidate:
    """Coerce a ranked segment (dict / object) into a repurpose ``Candidate``."""
    if isinstance(seg, dict):
        get = seg.get
    else:
        get = lambda k, d=None: getattr(seg, k, d)  # noqa: E731
    start = get("start_s", get("start", 0)) or 0
    end = get("end_s", get("end", 0)) or 0
    return Candidate(
        start_s=int(float(start)),
        end_s=int(float(end)),
        score=int(float(get("score", 0) or 0)),
        title=str(get("title", "") or ""),
        hook=str(get("hook", "") or ""),
        transcript=str(get("transcript", get("text", "")) or ""),
        reason=str(get("reason", "") or ""),
    )


def plan_clips(
    words: Sequence[object],
    ranked_segments: Sequence[object],
    *,
    target_count: int = DEFAULT_MAX_CLIPS,
    min_len_s: int = DEFAULT_MIN_LEN_S,
    max_len_s: int = DEFAULT_MAX_LEN_S,
    score_floor: int = DEFAULT_MIN_SCORE,
) -> list[ClipPlan]:
    """Map ranked segments to word-boundary-snapped :class:`ClipPlan` cut points.

    Selection is delegated to the reused repurpose highlight policy (duration
    band + score floor + non-overlapping + top-N); each surviving window is then
    snapped to the nearest enclosing WhisperX word boundaries and given the exact
    transcript of the words it contains. Deterministic.
    """
    candidates = [_candidate_from_segment(s) for s in (ranked_segments or [])]
    selected = select_highlights(
        candidates,
        max_clips=target_count,
        min_len_s=min_len_s,
        max_len_s=max_len_s,
        min_score=score_floor,
    )
    plans: list[ClipPlan] = []
    for cand in selected:
        start_s, end_s = cut_points_from_window(words, cand.start_s, cand.end_s)
        transcript = _transcript_for_window(words, start_s, end_s) or cand.transcript
        plans.append(
            ClipPlan(
                start_s=start_s,
                end_s=end_s,
                score=int(cand.score),
                title=cand.title,
                hook=cand.hook,
                transcript=transcript,
                reason=cand.reason,
            )
        )
    return plans


def should_stitch(plans: Sequence[ClipPlan]) -> bool:
    """True when there is more than one clip to cross-fade into a single reel."""
    return len(list(plans)) > 1


def segments_from_words(
    words: Sequence[object],
    *,
    window_s: float = DEFAULT_MAX_LEN_S,
    stride_s: float | None = None,
) -> list[dict]:
    """Build coarse candidate windows over the transcript for the ranker to score.

    Sliding windows of ``window_s`` seconds (default stride == ``window_s``, i.e.
    non-overlapping) are cut on word boundaries so the ranker receives complete,
    scoreable transcript spans. Returns dicts (``start_s``/``end_s``/``text``)
    without a ``score`` so the injected ranker fills it in. Deterministic.
    """
    normalized = _normalize_words(words)
    if not normalized:
        return []
    window = max(1.0, float(window_s))
    stride = max(1.0, float(stride_s if stride_s is not None else window_s))

    total_end = max(w.end_s for w in normalized)
    segments: list[dict] = []
    cursor = normalized[0].start_s
    seen: set[tuple[float, float]] = set()
    while cursor < total_end:
        w_start = cursor
        w_end = cursor + window
        start_s, end_s = cut_points_from_window(normalized, w_start, w_end)
        key = (start_s, end_s)
        if end_s > start_s and key not in seen:
            seen.add(key)
            segments.append(
                {
                    "start_s": start_s,
                    "end_s": end_s,
                    "text": _transcript_for_window(normalized, start_s, end_s),
                }
            )
        cursor += stride
    return segments
