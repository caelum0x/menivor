"""Pure highlight-selection policy (no DB, no LLM, no IO).

Given scored candidate windows (from the ranker), select the best short-form
clips: within the duration band, above a score floor, non-overlapping, highest
score first, capped at N. Kept side-effect free so the core product logic is
exhaustively unit-testable and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

# Sensible defaults for vertical short-form; overridable per request.
DEFAULT_MIN_LEN_S = 15
DEFAULT_MAX_LEN_S = 60
DEFAULT_MAX_CLIPS = 5
DEFAULT_MIN_SCORE = 50


@dataclass(frozen=True)
class Candidate:
    """A scored transcript window proposed by the ranker."""

    start_s: int
    end_s: int
    score: int
    title: str = ""
    hook: str = ""
    transcript: str = ""
    reason: str = ""

    @property
    def length_s(self) -> int:
        return max(0, int(self.end_s) - int(self.start_s))


def _overlaps(a: Candidate, b: Candidate) -> bool:
    return int(a.start_s) < int(b.end_s) and int(b.start_s) < int(a.end_s)


def _bounded(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(value), maximum))


def select_highlights(
    candidates: list[Candidate],
    *,
    max_clips: int = DEFAULT_MAX_CLIPS,
    min_len_s: int = DEFAULT_MIN_LEN_S,
    max_len_s: int = DEFAULT_MAX_LEN_S,
    min_score: int = DEFAULT_MIN_SCORE,
) -> list[Candidate]:
    """Return the selected clips, best score first, non-overlapping.

    A candidate qualifies when its length is within ``[min_len_s, max_len_s]``
    and its score is at least ``min_score``. Qualified candidates are considered
    highest-score-first (ties broken by earlier start, then shorter length) and
    greedily selected while they do not overlap an already-selected clip, up to
    ``max_clips``.
    """
    max_clips = _bounded(max_clips, 1, 50)
    min_len_s = max(1, int(min_len_s))
    max_len_s = max(min_len_s, int(max_len_s))
    min_score = max(0, int(min_score))

    qualified = [
        c
        for c in candidates
        if min_len_s <= c.length_s <= max_len_s and int(c.score) >= min_score
    ]
    qualified.sort(key=lambda c: (-int(c.score), int(c.start_s), c.length_s))

    selected: list[Candidate] = []
    for cand in qualified:
        if len(selected) >= max_clips:
            break
        if any(_overlaps(cand, s) for s in selected):
            continue
        selected.append(cand)
    return selected


def candidate_from_dict(row: dict) -> Candidate:
    """Coerce a ranker/transcript dict into a :class:`Candidate` (defensive)."""
    return Candidate(
        start_s=int(row.get("start_s", 0) or 0),
        end_s=int(row.get("end_s", 0) or 0),
        score=_bounded(row.get("score", 0) or 0, 0, 100),
        title=str(row.get("title", "") or ""),
        hook=str(row.get("hook", "") or ""),
        transcript=str(row.get("transcript", row.get("text", "")) or ""),
        reason=str(row.get("reason", "") or ""),
    )
