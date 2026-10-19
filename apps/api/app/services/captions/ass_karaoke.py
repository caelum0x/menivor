"""ASS karaoke subtitle generation for ReelForge captions.

Pure-string builders (no ffmpeg, no I/O beyond :func:`write_ass`) that render an
Advanced SubStation Alpha (.ass) file with per-word ``{\\k}`` karaoke highlight
and a per-word pop bounce. See INTEGRATION_CONTRACT.md §2.5 / §8.

Timing contract:
- ``\\k`` values for a line sum EXACTLY to the line duration in centiseconds
  (the last word absorbs any rounding remainder — "last-word pad").
- Timestamps render as ``H:MM:SS.cc``.
- Turkish-safe uppercase (``i -> İ``, ``ı -> I``) is applied before writing when
  ``upper`` is set; the style declares ``Encoding = 1`` so the renderer picks the
  Latin/Turkish code page.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Sequence

from app.services.captions._engine import caption_engine, preset_ids
from app.services.captions.words import WordTiming

__all__ = [
    "KaraokeStyle",
    "build_ass",
    "turkish_upper",
    "write_ass",
    "BURN_FONT_SUBSTITUTIONS",
    "build_ass_engine",
    "engine_preset_ids",
    "write_ass_engine",
]

# --------------------------------------------------------------------------- #
# Shared-engine burn path (preview parity)
# --------------------------------------------------------------------------- #
# Server-side fonts differ from the web-loaded preview fonts: the burn box only
# bundles ``Montserrat-ExtraBold.ttf`` (see apps/api/assets/resource/fonts),
# while the shared ``hormozi`` preset names the display weight ``Montserrat
# Black``. Without this map libass would fail to resolve "Montserrat Black" and
# substitute a default sans (tofu / wrong face). Callers that BURN pass this map
# so the closest bundled family is used; the preview keeps its own web font.
# Bundling ``Montserrat-Black.ttf`` lets this collapse to an identity map and the
# burned face then matches the preview weight exactly (owner step).
BURN_FONT_SUBSTITUTIONS: Mapping[str, str] = {
    "Montserrat Black": "Montserrat ExtraBold",
}

# Per-word pop bounce: scale to 110% over the first 80ms of the word's slot.
_POP_TAG: str = r"{\t(0,80,\fscx110\fscy110)}"


@dataclass(frozen=True)
class KaraokeStyle:
    """Immutable ASS style parameters for the karaoke caption line."""

    font: str = "Montserrat ExtraBold"
    fontsize: int = 88
    primary: str = "&H00FFFFFF"  # white (spoken / already highlighted)
    secondary: str = "&H0000FFFF"  # yellow (unspoken / pending highlight)
    outline_col: str = "&H00000000"
    back_col: str = "&H64000000"
    outline: int = 5
    shadow: int = 1
    alignment: int = 8  # top-center
    margin_v: int = 380
    margin_lr: int = 60
    play_w: int = 1080
    play_h: int = 1920
    pop: bool = True  # per-word scale bounce
    # Keyword emphasis colour (ASS &HAABBGGRR). One word per 2+ word line is
    # drawn in this colour (M2.4). ``None`` turns emphasis off.
    emphasis: Optional[str] = "&H0014FF39"  # neon green (rgb #39ff14)


def turkish_upper(text: str) -> str:
    """Turkish-safe uppercase: ``i -> İ`` and ``ı -> I`` before ``str.upper()``.

    Python's ``str.upper()`` maps dotless/dotted ``i`` incorrectly for Turkish,
    so the special glyphs are substituted first and the dotted capital is left
    untouched by the trailing ``upper()``.
    """
    return text.replace("ı", "I").replace("i", "İ").upper()


def _format_ts(seconds: float) -> str:
    """Render ``seconds`` as an ASS timestamp ``H:MM:SS.cc`` (centisecond)."""
    if seconds < 0:
        seconds = 0.0
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_text(text: str) -> str:
    """Escape caption text so it can't break ASS override blocks."""
    return (
        text.replace("\r", "")
        .replace("\n", r"\N")
        .replace("{", "(")
        .replace("}", ")")
    )


def _compute_k_values(
    words: list[WordTiming],
    line_start: float,
    line_end: float,
) -> list[int]:
    """Per-word ``\\k`` durations (centiseconds) summing to the line duration.

    Uses cumulative targets relative to ``line_start`` so inter-word gaps are
    folded into the preceding word's highlight, then pads the last word so the
    total equals ``round((line_end - line_start) * 100)`` exactly.
    """
    total_cs = max(1, int(round((line_end - line_start) * 100)))
    ks: list[int] = []
    cum = 0
    for word in words:
        target = int(round((word.end - line_start) * 100))
        target = max(target, cum)
        target = min(target, total_cs)
        ks.append(target - cum)
        cum = target

    if ks:
        remainder = total_cs - sum(ks)
        ks[-1] += remainder
        ks[-1] = max(ks[-1], 0)
    return ks


def _override_hex(colour: str) -> str:
    """``&HAABBGGRR`` style colour to the ``&HBBGGRR&`` override form."""
    digits = colour.strip().lstrip("&").lstrip("Hh").rstrip("&")
    return "&H%s&" % digits[-6:].upper().rjust(6, "0")


def _colour_override(primary: str, secondary: str) -> str:
    """Override block setting the spoken (1c) and upcoming (2c) colours."""
    return "{\\1c%s\\2c%s}" % (_override_hex(primary), _override_hex(secondary))


def _build_line_text(
    words: list[WordTiming],
    style: KaraokeStyle,
    upper: bool,
    emphasis_index: Optional[int] = None,
) -> str:
    """Build the karaoke override string for one phrase line.

    ``emphasis_index`` names the keyword drawn in ``style.emphasis`` for both
    the spoken and the upcoming colour, so it stays accented through the sweep.
    The line's own colours are restored right after that word.
    """
    line_start = words[0].start
    line_end = words[-1].end
    ks = _compute_k_values(words, line_start, line_end)
    accent = style.emphasis if emphasis_index is not None else None

    segments: list[str] = []
    for index, (word, k) in enumerate(zip(words, ks)):
        text = turkish_upper(word.text) if upper else word.text
        segment = "{\\k%d}" % k
        if style.pop:
            segment += _POP_TAG
        if accent and index == emphasis_index:
            segment += _colour_override(accent, accent)
            segment += _escape_text(text)
            segment += _colour_override(style.primary, style.secondary)
        else:
            segment += _escape_text(text)
        segments.append(segment)
    return " ".join(segments)


def _build_header(style: KaraokeStyle) -> str:
    """Script Info + V4+ Styles sections."""
    style_fields = [
        "Default",
        style.font,
        str(style.fontsize),
        style.primary,
        style.secondary,
        style.outline_col,
        style.back_col,
        "-1",  # Bold (ExtraBold face)
        "0",  # Italic
        "0",  # Underline
        "0",  # StrikeOut
        "100",  # ScaleX
        "100",  # ScaleY
        "0",  # Spacing
        "0",  # Angle
        "1",  # BorderStyle (outline + drop shadow)
        str(style.outline),
        str(style.shadow),
        str(style.alignment),
        str(style.margin_lr),  # MarginL
        str(style.margin_lr),  # MarginR
        str(style.margin_v),  # MarginV
        "1",  # Encoding (Latin/Turkish-safe)
    ]
    return "\n".join(
        [
            "[Script Info]",
            "; ReelForge karaoke captions",
            "ScriptType: v4.00+",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            f"PlayResX: {style.play_w}",
            f"PlayResY: {style.play_h}",
            "",
            "[V4+ Styles]",
            (
                "Format: Name, Fontname, Fontsize, PrimaryColour, "
                "SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
                "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
                "MarginV, Encoding"
            ),
            "Style: " + ",".join(style_fields),
            "",
        ]
    )


def build_ass(
    lines: list[list[WordTiming]],
    style: KaraokeStyle = KaraokeStyle(),
    upper: bool = False,
    emphasis: Optional[Sequence[Optional[int]]] = None,
) -> str:
    """Render the full ASS document string for the given phrase lines.

    Args:
        lines: Phrase lines (each a list of ``WordTiming``), e.g. from
            :func:`app.services.captions.words.group_words_into_phrases`.
        style: Karaoke styling.
        upper: Apply Turkish-safe uppercase to every word.
        emphasis: Per-line keyword index (``None`` entries = no keyword). When
            omitted and ``style.emphasis`` is set, the deterministic keyword
            pick is used, so this function stays pure (no network).

    Returns:
        The complete ``.ass`` file contents as a UTF-8 string.
    """
    picks = _resolve_emphasis(lines, style, emphasis)
    parts = [_build_header(style)]
    parts.append("[Events]")
    parts.append(
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text"
    )

    for line_index, words in enumerate(lines):
        if not words:
            continue
        start = words[0].start
        end = words[-1].end
        end = max(end, start)
        pick = picks[line_index] if line_index < len(picks) else None
        if pick is not None and not 0 <= pick < len(words):
            pick = None
        text = _build_line_text(words, style, upper, pick)
        dialogue = (
            f"Dialogue: 0,{_format_ts(start)},{_format_ts(end)},"
            f"Default,,0,0,0,,{text}"
        )
        parts.append(dialogue)

    return "\n".join(parts) + "\n"


def _resolve_emphasis(
    lines: list[list[WordTiming]],
    style: KaraokeStyle,
    emphasis: Optional[Sequence[Optional[int]]],
) -> list[Optional[int]]:
    """Per-line keyword indices for :func:`build_ass` (pure, no network)."""
    if not style.emphasis:
        return [None] * len(lines)
    if emphasis is not None:
        return list(emphasis)
    from app.services.captions.emphasis import deterministic_emphasis

    return deterministic_emphasis(lines)


def write_ass(
    path: str,
    lines: list[list[WordTiming]],
    style: KaraokeStyle = KaraokeStyle(),
    upper: bool = False,
    emphasis: Optional[Sequence[Optional[int]]] = None,
) -> str:
    """Write the ASS document to ``path`` as UTF-8 (no BOM) and return ``path``.

    When the style has an emphasis colour and no ``emphasis`` is passed, the
    keywords are picked with Relay Haiku, falling back to the deterministic
    pick (:func:`app.services.captions.emphasis.pick_emphasis`).
    """
    if style.emphasis and emphasis is None:
        from app.services.captions.emphasis import pick_emphasis

        emphasis = pick_emphasis(lines)
    content = build_ass(lines, style=style, upper=upper, emphasis=emphasis)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return path


# --------------------------------------------------------------------------- #
# Shared caption-engine renderer — preview-identical burn
# --------------------------------------------------------------------------- #
# The functions above are the self-contained ReelForge karaoke builder (per-line
# \k timing that sums to the line duration, per-word pop bounce). The functions
# below instead delegate to the shared ``reelforge_caption_engine`` — the SAME
# builder + preset registry the web caption preview renders from — so that a clip
# burned with one of the shared presets (``hormozi``, ``karaoke-classic``,
# ``minimal-top-label``, ``brainrot-popin``) is byte-for-byte the string the
# client previewed (verified against the golden ``.ass`` fixtures).


def engine_preset_ids() -> tuple[str, ...]:
    """Preset ids the shared engine can render (empty if it is unavailable)."""
    return preset_ids()


def _word_to_engine_dict(word: Any) -> dict:
    """Normalise a word cue to the shared engine's ``{text,start,end}`` shape.

    Accepts a :class:`WordTiming` (or any object exposing ``text``/``start``/
    ``end``), a ``(text, start, end)`` tuple/list, or a mapping. Times coerce to
    ``float`` and text to ``str`` so a loose caller can never emit a malformed
    dialogue line.
    """
    if isinstance(word, Mapping):
        text, start, end = word["text"], word["start"], word["end"]
    elif hasattr(word, "text") and hasattr(word, "start") and hasattr(word, "end"):
        text, start, end = word.text, word.start, word.end
    elif isinstance(word, (tuple, list)) and len(word) >= 3:
        text, start, end = word[0], word[1], word[2]
    else:  # pragma: no cover - defensive; callers pass one of the above
        raise TypeError(f"unsupported word cue: {word!r}")
    return {"text": str(text), "start": float(start), "end": float(end)}


def build_ass_engine(
    words: Sequence[Any],
    preset: str,
    *,
    upper: Optional[bool] = None,
    fonts: Optional[Mapping[str, str]] = None,
) -> str:
    """Render preview-identical ASS via the shared ``reelforge_caption_engine``.

    Args:
        words: A FLAT sequence of word cues (the engine groups them by the
            preset's ``words_per_group`` exactly like the preview — do NOT
            pre-group into phrases).
        preset: A shared-engine preset id (see :func:`engine_preset_ids`).
        upper: ``None`` honours the preset's own ``uppercase`` flag (preview
            parity); ``True``/``False`` overrides it.
        fonts: Optional preset-font → available-font substitution applied to the
            rendered style (e.g. :data:`BURN_FONT_SUBSTITUTIONS` when burning so
            libass resolves a bundled family). ``None`` keeps the preset font, so
            the output stays byte-identical to the client preview.

    Returns:
        The complete ``.ass`` document string.

    Raises:
        RuntimeError: if the shared engine package is not importable.
    """
    engine = caption_engine()
    if engine is None:  # pragma: no cover - only on a stripped deploy
        raise RuntimeError(
            "reelforge_caption_engine is unavailable; cannot render shared preset"
        )

    style = engine.get_preset(preset)
    if upper is not None and upper != style.uppercase:
        style = replace(style, uppercase=upper)
    if fonts:
        substitute = fonts.get(style.font)
        if substitute and substitute != style.font:
            style = replace(style, font=substitute)

    dict_words = [_word_to_engine_dict(w) for w in words]
    return engine.build_ass(dict_words, style)


def write_ass_engine(
    path: str,
    words: Sequence[Any],
    preset: str,
    *,
    upper: Optional[bool] = None,
    fonts: Optional[Mapping[str, str]] = None,
) -> str:
    """Render via the shared engine and write UTF-8 (no BOM) to ``path``."""
    content = build_ass_engine(words, preset, upper=upper, fonts=fonts)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return path
