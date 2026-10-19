"""Word/phrase grouping for ReelForge karaoke captions.

Pure functions (no ffmpeg, no network) that turn an ElevenLabs
``/with-timestamps`` character alignment into word-level timings and then into
CapCut-style phrase lines. See INTEGRATION_CONTRACT.md §2.5 / §8 — the alignment
is the single timing authority for the whole pipeline.
"""

from __future__ import annotations

# WordTiming's canonical home is the ElevenLabs adapter (§2.2). Import it from
# there; fall back to a structurally-identical NamedTuple so these pure-string
# builders stay unit-testable without importing the network-heavy TTS stack.
try:  # pragma: no cover - exercised implicitly when the adapter is present
    from app.services.tts.elevenlabs_timestamps import WordTiming
except Exception:  # pragma: no cover - standalone/test fallback
    from typing import NamedTuple

    class WordTiming(NamedTuple):
        """Immutable word/char timing for karaoke captions (seconds)."""

        text: str
        start: float
        end: float


__all__ = ["WordTiming", "group_chars_to_words", "group_words_into_phrases"]


def group_chars_to_words(alignment: dict) -> list[WordTiming]:
    """Convert an ElevenLabs char alignment into word-level ``WordTiming``.

    Whitespace characters act as word boundaries. Each word's ``start`` is the
    start time of its first character and ``end`` is the end time of its last
    non-space character.

    Args:
        alignment: The ``alignment`` object from ``/with-timestamps`` with keys
            ``characters``, ``character_start_times_seconds`` and
            ``character_end_times_seconds``.

    Returns:
        List of ``WordTiming`` in reading order (empty list on missing/invalid
        input — never raises to the caller).
    """
    if not alignment or not isinstance(alignment, dict):
        return []

    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []

    count = min(len(chars), len(starts), len(ends))
    words: list[WordTiming] = []

    cur_chars: list[str] = []
    cur_start: float | None = None
    cur_end: float | None = None

    for i in range(count):
        char = chars[i]
        if char is None:
            continue
        if char.isspace():
            _flush = _finalize_word(cur_chars, cur_start, cur_end)
            if _flush is not None:
                words.append(_flush)
            cur_chars, cur_start, cur_end = [], None, None
            continue

        try:
            start = float(starts[i])
            end = float(ends[i])
        except (TypeError, ValueError):
            continue

        if cur_start is None:
            cur_start = start
        cur_end = end
        cur_chars.append(char)

    tail = _finalize_word(cur_chars, cur_start, cur_end)
    if tail is not None:
        words.append(tail)

    return words


def _finalize_word(
    chars: list[str],
    start: float | None,
    end: float | None,
) -> WordTiming | None:
    """Build a single ``WordTiming`` from an accumulated char run, or None."""
    if not chars or start is None or end is None:
        return None
    # Guard against non-monotonic alignment data.
    safe_end = max(end, start)
    return WordTiming("".join(chars), start, safe_end)


def group_words_into_phrases(
    words: list[WordTiming],
    max_words: int = 4,
    max_dur: float = 1.4,
    max_gap: float = 0.5,
    min_words: int = 2,
) -> list[list[WordTiming]]:
    """Group words into CapCut-style phrase lines.

    A new line is started whenever the current line already holds ``max_words``
    words, when appending the next word would make the line span longer than
    ``max_dur`` seconds, or when the silent gap between the previous word and the
    next word exceeds ``max_gap`` seconds. A single word longer than ``max_dur``
    still occupies its own line (it cannot be split further).

    Breaking on ``max_gap`` matters for two reasons: it keeps words from
    different spoken sentences off the same caption line (readability), and it
    prevents the pre-word silence from being folded into the preceding word's
    ``\\k`` karaoke highlight (see :func:`ass_karaoke._compute_k_values`), which
    would otherwise stretch that word's yellow→white sweep across the pause.

    Args:
        words: Ordered word timings (typically from :func:`group_chars_to_words`).
        max_words: Hard cap on words per line (~3-5 reads well).
        max_dur: Soft cap on line duration in seconds (~1.2-1.4s).
        max_gap: Soft cap on the silent gap between two consecutive words before
            a new line is forced (~0.4-0.6s reads as a natural sentence pause).
            A non-positive value disables gap-based splitting.
        min_words: Floor on words per line (M2.4: captions read in 2-4 word
            phrases). After the split above, a line shorter than this is merged
            into a neighbour, or takes a word from a neighbour that can spare
            one. The floor is capped at ``max_words`` and only yields when the
            whole input is shorter than it. ``1`` keeps the plain split.

    Returns:
        List of phrase lines, each a non-empty list of ``WordTiming``.
    """
    if not words:
        return []

    max_words = max(1, int(max_words))
    phrases: list[list[WordTiming]] = []
    current: list[WordTiming] = []

    for word in words:
        if current:
            phrase_start = current[0].start
            prospective_dur = word.end - phrase_start
            # Gap between the last placed word and this one (skip on overlap /
            # non-monotonic data, where the difference is <= 0).
            gap = word.start - current[-1].end
            gap_break = max_gap > 0 and gap > max_gap
            if len(current) >= max_words or prospective_dur > max_dur or gap_break:
                phrases.append(current)
                current = []
        current.append(word)

    if current:
        phrases.append(current)

    floor = max(1, min(int(min_words), max_words))
    if floor <= 1:
        return phrases
    return _enforce_min_words(phrases, floor, max_words)


def _enforce_min_words(
    phrases: list[list[WordTiming]], floor: int, max_words: int
) -> list[list[WordTiming]]:
    """Return new phrase lines where every line holds at least ``floor`` words.

    Short lines are repaired left to right, preferring the neighbour with the
    smaller silent gap. A merge is used when the joined line fits in
    ``max_words``; otherwise the short line borrows the nearest word from a
    neighbour that stays at or above ``floor`` after lending it. Word order and
    word timings are never changed, only line boundaries move.
    """
    lines = [list(p) for p in phrases if p]
    i = 0
    while i < len(lines):
        if len(lines) < 2 or len(lines[i]) >= floor:
            i += 1
            continue
        if _repair_short_line(lines, i, floor, max_words):
            # Re-check from the previous line: a merge can shift indices.
            i = max(0, i - 1)
            continue
        i += 1
    return lines


def _neighbour_order(lines: list[list[WordTiming]], i: int) -> list[int]:
    """Neighbour indices of line ``i``, closest in time first."""
    candidates: list[tuple[float, int]] = []
    if i > 0:
        candidates.append((lines[i][0].start - lines[i - 1][-1].end, i - 1))
    if i + 1 < len(lines):
        candidates.append((lines[i + 1][0].start - lines[i][-1].end, i + 1))
    candidates.sort(key=lambda pair: (pair[0], pair[1]))
    return [idx for _, idx in candidates]


def _repair_short_line(
    lines: list[list[WordTiming]], i: int, floor: int, max_words: int
) -> bool:
    """Merge or rebalance line ``i`` with a neighbour. True if anything changed."""
    order = _neighbour_order(lines, i)
    for j in order:
        if len(lines[i]) + len(lines[j]) <= max_words:
            lo, hi = min(i, j), max(i, j)
            lines[lo:hi + 1] = [lines[lo] + lines[hi]]
            return True
    for j in order:
        need = floor - len(lines[i])
        if len(lines[j]) - need < floor:
            continue
        if j < i:
            lines[i] = lines[j][-need:] + lines[i]
            lines[j] = lines[j][:-need]
        else:
            lines[i] = lines[i] + lines[j][:need]
            lines[j] = lines[j][need:]
        return True
    return False
