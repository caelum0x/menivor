"""Hormozi caption engine — 1-2 word groups with a highlighted key word.

The near-universal viral caption look: Montserrat Black, ALL CAPS, white base with
ONE key noun/verb popped in the accent color (#FFD93D), 1-2 words on screen at a
time, thick outline + shadow, lower-third safe-zone. Reported +15-40% avg view
duration (docs/reelforge/vision2026).

This module owns the PURE parts the existing ``ass_karaoke`` builder doesn't:

* :func:`group_words` — chunk word-timed tokens into 1-2 word display groups
  preserving timing (start of first word → end of last).
* :func:`select_highlight` — pick the key noun/verb in a group to accent
  (stopword-filtered, content-word heuristic — no ML).
* :func:`hormozi_style` — the KaraokeStyle-shaped param bundle for the look.

Deterministic + dependency-free; the ASS renderer consumes the groups.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.captions._engine import shared_preset

HORMOZI_HIGHLIGHT = "#FFD93D"

# Function words that should never be the accented key word.
_STOPWORDS = frozenset(
    """a an and the to of in on at for with is are was were be been being it its this that these those
    i you he she we they me him her us them my your his our their as but or if so no not do does did
    have has had will would can could should just about into over under out up down off then than
    what when where who how why which am pm ok okay yeah""".split()
)


@dataclass(frozen=True)
class WordCue:
    """A word with its start/end time (seconds) — the single timing authority."""

    text: str
    start: float
    end: float


@dataclass(frozen=True)
class CaptionGroup:
    """A 1-2 word on-screen group with the accented word index."""

    words: tuple[str, ...]
    start: float
    end: float
    highlight_index: int   # index within ``words`` to accent (-1 = none)

    @property
    def text(self) -> str:
        return " ".join(self.words)


def group_words(words: list[WordCue], *, max_per_group: int = 2) -> list[CaptionGroup]:
    """Chunk word cues into ≤``max_per_group`` groups, preserving timing.

    A group's start is the first word's start and end is the last word's end, so
    the karaoke timing stays exact (no drift vs. the word-level source).
    """
    if max_per_group < 1:
        raise ValueError("max_per_group must be >= 1")
    groups: list[CaptionGroup] = []
    for i in range(0, len(words), max_per_group):
        chunk = words[i : i + max_per_group]
        texts = tuple(w.text for w in chunk)
        groups.append(
            CaptionGroup(
                words=texts,
                start=chunk[0].start,
                end=chunk[-1].end,
                highlight_index=select_highlight(texts),
            )
        )
    return groups


def _content_score(word: str) -> float:
    """Higher = more likely the meaningful key word (noun/verb-ish)."""
    w = "".join(ch for ch in word.lower() if ch.isalpha())
    if not w or w in _STOPWORDS:
        return -1.0
    score = float(len(w))
    # Common noun/verb endings nudge the score up.
    if w.endswith(("ing", "ed", "tion", "ness", "ment", "er", "est")):
        score += 2.0
    return score


def select_highlight(words: tuple[str, ...]) -> int:
    """Pick the index of the key content word to accent (-1 if none qualify)."""
    best_i, best = -1, 0.0
    for i, w in enumerate(words):
        s = _content_score(w)
        if s > best:
            best, best_i = s, i
    return best_i


@dataclass(frozen=True)
class HormoziStyle:
    """KaraokeStyle-shaped params for the Hormozi look (fed to the ASS builder).

    The field defaults mirror the shared ``reelforge_caption_engine`` ``hormozi``
    preset — the SAME registry the web caption preview renders from — so the API
    and the client agree on the look. They double as the offline fallback if the
    shared package cannot be imported (see :func:`hormozi_style`).
    """

    font: str = "Montserrat Black"
    all_caps: bool = True
    highlight_hex: str = HORMOZI_HIGHLIGHT
    base_hex: str = "#FFFFFF"
    outline: int = 4
    shadow: int = 2
    max_per_group: int = 2

    def as_params(self) -> dict:
        return {
            "font": self.font,
            "all_caps": self.all_caps,
            "highlight_hex": self.highlight_hex,
            "base_hex": self.base_hex,
            "outline": self.outline,
            "shadow": self.shadow,
            "max_per_group": self.max_per_group,
        }


def hormozi_style(highlight_hex: str = HORMOZI_HIGHLIGHT) -> HormoziStyle:
    """Return the Hormozi style bundle with an optional accent override.

    The look is single-sourced from the shared ``reelforge_caption_engine``
    ``hormozi`` preset so the values the API reports here match what the client
    preview renders and what the burn-in path (``ass_karaoke.build_ass_engine``)
    emits. If the shared package is unavailable the frozen field defaults above
    (kept in sync with that preset) are used instead.
    """
    preset = shared_preset("hormozi")
    if preset is not None:
        return HormoziStyle(
            font=preset.font,
            all_caps=preset.uppercase,
            highlight_hex=highlight_hex or preset.highlight_hex,
            base_hex=preset.primary_hex,
            outline=preset.outline,
            shadow=preset.shadow,
            max_per_group=preset.words_per_group,
        )
    return HormoziStyle(highlight_hex=highlight_hex or HORMOZI_HIGHLIGHT)
