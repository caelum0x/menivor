"""Unit tests for ReelForge karaoke captions.

Covers ``app/services/captions/words.py`` and ``ass_karaoke.py``:
- char-alignment -> WordTiming grouping
- phrase grouping (max_words / max_dur)
- ASS output: PlayRes header, Style line (colours/fontsize/alignment/margin)
- ``{\\k<cs>}`` values SUM to the line duration in centiseconds (exact)
- per-word pop tag presence
- timestamp format ``H:MM:SS.cc``
- Turkish-safe uppercase (``i -> İ`` / ``ı -> I``)

Pure-string assertions only — no ffmpeg, no network, no DB.
"""

from __future__ import annotations

import re

import pytest

from app.services.captions.words import (
    WordTiming,
    group_chars_to_words,
    group_words_into_phrases,
)
from app.services.captions.ass_karaoke import (
    KaraokeStyle,
    build_ass,
    turkish_upper,
    write_ass,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _alignment(chars, starts, ends) -> dict:
    return {
        "characters": list(chars),
        "character_start_times_seconds": list(starts),
        "character_end_times_seconds": list(ends),
    }


def _seq_alignment(text: str, step: float = 0.1) -> dict:
    """Build an alignment where each char occupies a ``step``-second slot."""
    chars, starts, ends = [], [], []
    for i, ch in enumerate(text):
        chars.append(ch)
        starts.append(round(i * step, 6))
        ends.append(round((i + 1) * step, 6))
    return _alignment(chars, starts, ends)


def _style_line(ass: str) -> str:
    for line in ass.splitlines():
        if line.startswith("Style:"):
            return line
    raise AssertionError("no Style: line in ASS output")


def _style_fields(ass: str) -> list[str]:
    return _style_line(ass)[len("Style:"):].strip().split(",")


def _dialogue_lines(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


# ---------------------------------------------------------------------------
# group_chars_to_words
# ---------------------------------------------------------------------------

class TestGroupCharsToWords:
    def test_two_words_split_on_space(self):
        al = _alignment(
            ["H", "i", " ", "B", "y", "e"],
            [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        )
        words = group_chars_to_words(al)
        assert [w.text for w in words] == ["Hi", "Bye"]

    def test_word_start_is_first_char_start(self):
        al = _alignment(
            ["a", "b", "c"],
            [0.5, 0.6, 0.7],
            [0.6, 0.7, 0.8],
        )
        (word,) = group_chars_to_words(al)
        assert word.start == 0.5

    def test_word_end_is_last_nonspace_char_end(self):
        # Trailing space must not extend the word's end.
        al = _alignment(
            ["a", "b", " "],
            [0.0, 0.1, 0.2],
            [0.1, 0.2, 0.3],
        )
        (word,) = group_chars_to_words(al)
        assert word.text == "ab"
        assert word.end == 0.2  # end of "b", not of the space

    def test_multiple_spaces_do_not_emit_empty_words(self):
        al = _alignment(
            ["a", " ", " ", "b"],
            [0.0, 0.1, 0.2, 0.3],
            [0.1, 0.2, 0.3, 0.4],
        )
        words = group_chars_to_words(al)
        assert [w.text for w in words] == ["a", "b"]

    def test_returns_wordtiming_instances(self):
        words = group_chars_to_words(_seq_alignment("go now"))
        assert all(isinstance(w, WordTiming) for w in words)
        assert [w.text for w in words] == ["go", "now"]

    def test_ragged_arrays_truncate_to_shortest(self):
        # Only 2 usable chars because starts has length 2.
        al = _alignment(["a", "b", "c"], [0.0, 0.1], [0.1, 0.2])
        (word,) = group_chars_to_words(al)
        assert word.text == "ab"

    @pytest.mark.parametrize("bad", [None, {}, {"characters": []}, "nope", 42])
    def test_invalid_or_empty_alignment_returns_empty(self, bad):
        assert group_chars_to_words(bad) == []

    def test_non_monotonic_end_is_clamped_to_start(self):
        al = _alignment(["a"], [0.5], [0.3])  # end < start
        (word,) = group_chars_to_words(al)
        assert word.end == word.start == 0.5


# ---------------------------------------------------------------------------
# group_words_into_phrases
# ---------------------------------------------------------------------------

class TestGroupWordsIntoPhrases:
    def test_empty_input(self):
        assert group_words_into_phrases([]) == []

    def test_max_words_cap(self):
        words = [WordTiming(f"w{i}", i * 0.1, i * 0.1 + 0.05) for i in range(5)]
        phrases = group_words_into_phrases(words, max_words=2, max_dur=999.0)
        assert [len(p) for p in phrases] == [2, 2, 1]

    def test_max_dur_cap(self):
        # Each word 0.5s apart; max_dur 1.0s -> a line can hold words spanning <=1.0s.
        words = [
            WordTiming("a", 0.0, 0.4),
            WordTiming("b", 0.5, 0.9),
            WordTiming("c", 1.0, 1.4),  # 1.4 - 0.0 = 1.4 > 1.0 -> new line
            WordTiming("d", 1.5, 1.9),
        ]
        phrases = group_words_into_phrases(words, max_words=10, max_dur=1.0)
        assert [[w.text for w in p] for p in phrases] == [["a", "b"], ["c", "d"]]

    def test_single_long_word_gets_its_own_line(self):
        words = [WordTiming("loooong", 0.0, 5.0), WordTiming("next", 5.0, 5.3)]
        phrases = group_words_into_phrases(
            words, max_words=4, max_dur=1.4, min_words=1
        )
        assert [[w.text for w in p] for p in phrases] == [["loooong"], ["next"]]

    def test_single_long_word_joins_a_neighbour_under_the_two_word_floor(self):
        # M2.4: captions read in 2-4 word phrases, so the default floor of two
        # words joins the lone long word with its neighbour.
        words = [WordTiming("loooong", 0.0, 5.0), WordTiming("next", 5.0, 5.3)]
        phrases = group_words_into_phrases(words, max_words=4, max_dur=1.4)
        assert [[w.text for w in p] for p in phrases] == [["loooong", "next"]]

    def test_max_words_floor_of_one(self):
        words = [WordTiming("a", 0.0, 0.1), WordTiming("b", 0.1, 0.2)]
        phrases = group_words_into_phrases(words, max_words=0, max_dur=999.0)
        assert [len(p) for p in phrases] == [1, 1]

    def test_all_words_preserved_and_ordered(self):
        words = [WordTiming(f"w{i}", i * 0.3, i * 0.3 + 0.2) for i in range(9)]
        phrases = group_words_into_phrases(words, max_words=4, max_dur=1.4)
        flat = [w for p in phrases for w in p]
        assert flat == words
        assert all(len(p) >= 1 for p in phrases)

    def test_long_gap_forces_new_line(self):
        # "a b" spoken, then a 1.0s pause, then "c d". Well within max_words and
        # max_dur, but the pause must split the line so the highlight of "b" is
        # not stretched across the silence.
        words = [
            WordTiming("a", 0.0, 0.2),
            WordTiming("b", 0.25, 0.45),
            WordTiming("c", 1.45, 1.65),  # gap 1.45 - 0.45 = 1.0s > 0.5s
            WordTiming("d", 1.70, 1.90),
        ]
        phrases = group_words_into_phrases(words, max_words=10, max_dur=999.0)
        assert [[w.text for w in p] for p in phrases] == [["a", "b"], ["c", "d"]]

    def test_small_gaps_stay_on_one_line(self):
        # 0.1s gaps are below the default max_gap and must not split the line.
        words = [WordTiming(f"w{i}", i * 0.3, i * 0.3 + 0.2) for i in range(3)]
        phrases = group_words_into_phrases(words, max_words=10, max_dur=999.0)
        assert [[w.text for w in p] for p in phrases] == [["w0", "w1", "w2"]]

    def test_gap_splitting_disabled_with_non_positive_max_gap(self):
        words = [
            WordTiming("a", 0.0, 0.2),
            WordTiming("b", 3.0, 3.2),  # huge gap, but splitting disabled
        ]
        phrases = group_words_into_phrases(
            words, max_words=10, max_dur=999.0, max_gap=0.0
        )
        assert [[w.text for w in p] for p in phrases] == [["a", "b"]]

    def test_overlapping_words_do_not_gap_split(self):
        # Non-monotonic / overlapping alignment must not trigger a spurious break.
        words = [
            WordTiming("a", 0.0, 0.5),
            WordTiming("b", 0.3, 0.7),  # starts before "a" ends -> gap < 0
        ]
        phrases = group_words_into_phrases(words, max_words=10, max_dur=999.0)
        assert [[w.text for w in p] for p in phrases] == [["a", "b"]]

    def test_all_words_preserved_with_gaps(self):
        # Alternating tight/loose spacing: every word must still survive, ordered.
        words = [
            WordTiming("a", 0.0, 0.2),
            WordTiming("b", 0.25, 0.45),
            WordTiming("c", 2.0, 2.2),
            WordTiming("d", 2.25, 2.45),
            WordTiming("e", 4.0, 4.2),
        ]
        phrases = group_words_into_phrases(words, max_words=10, max_dur=999.0)
        flat = [w for p in phrases for w in p]
        assert flat == words
        assert all(len(p) >= 1 for p in phrases)


# ---------------------------------------------------------------------------
# ASS header / PlayRes / Style line
# ---------------------------------------------------------------------------

class TestAssHeader:
    def test_playres_header_matches_style(self):
        style = KaraokeStyle(play_w=1080, play_h=1920)
        ass = build_ass([[WordTiming("hi", 0.0, 0.5)]], style=style)
        assert "PlayResX: 1080" in ass
        assert "PlayResY: 1920" in ass

    def test_playres_header_respects_custom_resolution(self):
        style = KaraokeStyle(play_w=720, play_h=1280)
        ass = build_ass([[WordTiming("hi", 0.0, 0.5)]], style=style)
        assert "PlayResX: 720" in ass
        assert "PlayResY: 1280" in ass

    def test_script_info_and_sections_present(self):
        ass = build_ass([[WordTiming("hi", 0.0, 0.5)]])
        assert ass.startswith("[Script Info]")
        assert "ScriptType: v4.00+" in ass
        assert "[V4+ Styles]" in ass
        assert "[Events]" in ass
        assert ass.endswith("\n")

    def test_style_line_colours_fontsize(self):
        style = KaraokeStyle()
        ass = build_ass([[WordTiming("hi", 0.0, 0.5)]], style=style)
        fields = _style_fields(ass)
        # Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, ...
        assert fields[0] == "Default"
        assert fields[1] == "Montserrat ExtraBold"
        assert fields[2] == "88"
        assert fields[3] == "&H00FFFFFF"  # primary = white
        assert fields[4] == "&H0000FFFF"  # secondary = yellow
        assert fields[5] == "&H00000000"  # outline
        assert fields[6] == "&H64000000"  # back

    def test_style_line_alignment_and_margins(self):
        style = KaraokeStyle()
        fields = _style_fields(build_ass([[WordTiming("hi", 0.0, 0.5)]], style=style))
        # Alignment, MarginL, MarginR, MarginV are the 4 fields before Encoding.
        assert fields[15] == "1"      # BorderStyle
        assert fields[16] == "5"      # Outline
        assert fields[17] == "1"      # Shadow
        assert fields[18] == "8"      # Alignment (top-center)
        assert fields[19] == "60"     # MarginL
        assert fields[20] == "60"     # MarginR
        assert fields[21] == "380"    # MarginV
        assert fields[22] == "1"      # Encoding (Turkish-safe)

    def test_style_line_reflects_custom_style(self):
        style = KaraokeStyle(fontsize=100, alignment=2, margin_v=200, margin_lr=40)
        fields = _style_fields(build_ass([[WordTiming("hi", 0.0, 0.5)]], style=style))
        assert fields[2] == "100"
        assert fields[18] == "2"
        assert fields[19] == "40"
        assert fields[20] == "40"
        assert fields[21] == "200"

    def test_style_format_declares_all_columns(self):
        ass = build_ass([[WordTiming("hi", 0.0, 0.5)]])
        fmt = next(ln for ln in ass.splitlines() if ln.startswith("Format:") and "Fontname" in ln)
        # 23 declared columns == 23 emitted style fields.
        assert len(fmt.split(",")) == len(_style_fields(ass)) == 23


# ---------------------------------------------------------------------------
# Karaoke {\k} values and pop tag
# ---------------------------------------------------------------------------

def _k_values(dialogue: str) -> list[int]:
    return [int(m) for m in re.findall(r"\{\\k(\d+)\}", dialogue)]


class TestKaraokeTiming:
    def test_k_sum_equals_line_duration_cs_simple(self):
        line = [WordTiming("a", 0.0, 0.3), WordTiming("b", 0.3, 0.7)]
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        ks = _k_values(dialogue)
        expected_cs = round((0.7 - 0.0) * 100)
        assert sum(ks) == expected_cs == 70
        assert ks == [30, 40]

    def test_k_sum_exact_with_rounding_remainder(self):
        # 0.333s slots force rounding; last word absorbs the remainder.
        line = [
            WordTiming("a", 0.0, 0.333),
            WordTiming("b", 0.333, 0.666),
            WordTiming("c", 0.666, 1.0),
        ]
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        ks = _k_values(dialogue)
        expected_cs = round((1.0 - 0.0) * 100)
        assert sum(ks) == expected_cs == 100

    @pytest.mark.parametrize(
        "line",
        [
            [WordTiming("solo", 0.0, 1.23)],
            [WordTiming("x", 1.11, 1.55), WordTiming("y", 1.55, 2.07)],
            [WordTiming(f"w{i}", i * 0.17, i * 0.17 + 0.17) for i in range(6)],
        ],
    )
    def test_k_sum_exact_for_various_lines(self, line):
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        ks = _k_values(dialogue)
        expected_cs = round((line[-1].end - line[0].start) * 100)
        assert sum(ks) == expected_cs
        assert len(ks) == len(line)
        assert all(k >= 0 for k in ks)

    def test_k_sum_across_multiple_lines(self):
        lines = [
            [WordTiming("a", 0.0, 0.5), WordTiming("b", 0.5, 1.0)],
            [WordTiming("c", 1.0, 1.4), WordTiming("d", 1.4, 2.2)],
        ]
        ass = build_ass(lines)
        dialogues = _dialogue_lines(ass)
        assert len(dialogues) == 2
        for line, dialogue in zip(lines, dialogues):
            ks = _k_values(dialogue)
            assert sum(ks) == round((line[-1].end - line[0].start) * 100)

    def test_pop_tag_present_by_default(self):
        ass = build_ass([[WordTiming("hi", 0.0, 0.5)]])
        assert r"{\t(0,80,\fscx110\fscy110)}" in ass

    def test_pop_tag_absent_when_disabled(self):
        style = KaraokeStyle(pop=False)
        ass = build_ass([[WordTiming("hi", 0.0, 0.5)]], style=style)
        assert r"\fscx110" not in ass
        assert r"{\k" in ass  # karaoke tag still present

    def test_pop_tag_once_per_word(self):
        line = [WordTiming("a", 0.0, 0.3), WordTiming("b", 0.3, 0.6)]
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        assert dialogue.count(r"\fscx110") == 2

    def test_empty_line_skipped(self):
        ass = build_ass([[], [WordTiming("hi", 0.0, 0.5)]])
        assert len(_dialogue_lines(ass)) == 1


# ---------------------------------------------------------------------------
# Timestamp format H:MM:SS.cc
# ---------------------------------------------------------------------------

class TestTimestampFormat:
    _TS = re.compile(r"^\d+:[0-5]\d:[0-5]\d\.\d{2}$")

    def test_dialogue_timestamps_match_format(self):
        ass = build_ass([[WordTiming("hi", 0.0, 0.5)]])
        (dialogue,) = _dialogue_lines(ass)
        # Dialogue: 0,<start>,<end>,Default,,0,0,0,,<text>
        _, start, end = dialogue.split(",", 3)[:3]
        assert self._TS.match(start), start
        assert self._TS.match(end), end

    def test_start_end_values(self):
        ass = build_ass([[WordTiming("hi", 0.0, 0.5)]])
        (dialogue,) = _dialogue_lines(ass)
        fields = dialogue.split(",")
        assert fields[1] == "0:00:00.00"
        assert fields[2] == "0:00:00.50"

    def test_hours_minutes_centiseconds(self):
        # 1h 01m 01.23s -> 1:01:01.23
        line = [WordTiming("x", 3661.23, 3661.50)]
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        assert dialogue.split(",")[1] == "1:01:01.23"

    def test_centisecond_rounding(self):
        line = [WordTiming("x", 0.006, 0.5)]  # 0.6cs rounds up to .01
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        assert dialogue.split(",")[1] == "0:00:00.01"

    def test_negative_time_clamped_to_zero(self):
        line = [WordTiming("x", -1.0, 0.5)]
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        assert dialogue.split(",")[1] == "0:00:00.00"


# ---------------------------------------------------------------------------
# Turkish uppercase
# ---------------------------------------------------------------------------

class TestTurkishUpper:
    def test_dotted_i_maps_to_capital_dotted(self):
        assert turkish_upper("i") == "İ"

    def test_dotless_i_maps_to_ascii_I(self):
        assert turkish_upper("ı") == "I"

    def test_word_istanbul(self):
        assert turkish_upper("istanbul") == "İSTANBUL"

    def test_word_isik(self):
        assert turkish_upper("ışık") == "IŞIK"

    def test_mixed_preserves_other_chars(self):
        assert turkish_upper("iyi ışık") == "İYİ IŞIK"

    def test_ascii_unaffected(self):
        assert turkish_upper("hello") == "HELLO"

    def test_build_ass_applies_upper_when_flagged(self):
        line = [WordTiming("iyi", 0.0, 0.5)]
        ass = build_ass([line], upper=True)
        (dialogue,) = _dialogue_lines(ass)
        assert "İYİ" in dialogue
        assert "iyi" not in dialogue

    def test_build_ass_preserves_case_by_default(self):
        line = [WordTiming("iyi", 0.0, 0.5)]
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        assert "iyi" in dialogue


# ---------------------------------------------------------------------------
# Text escaping
# ---------------------------------------------------------------------------

class TestTextEscaping:
    def test_braces_neutralised(self):
        line = [WordTiming("{evil}", 0.0, 0.5)]
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        # Literal user braces become parens so they cannot open an override block.
        assert "(evil)" in dialogue
        # The only brace-delimited blocks are our own \k / pop tags.
        assert "{evil}" not in dialogue

    def test_newline_becomes_hard_break(self):
        line = [WordTiming("a\nb", 0.0, 0.5)]
        ass = build_ass([line])
        (dialogue,) = _dialogue_lines(ass)
        assert r"a\Nb" in dialogue
        # A literal newline must never leak into the single Dialogue line.
        assert len(_dialogue_lines(ass)) == 1


# ---------------------------------------------------------------------------
# write_ass (file I/O only, no ffmpeg)
# ---------------------------------------------------------------------------

class TestWriteAss:
    def test_returns_path_and_writes_utf8_no_bom(self, tmp_path):
        out = tmp_path / "cap.ass"
        line = [WordTiming("ışık", 0.0, 0.5)]
        returned = write_ass(str(out), [line], upper=True)
        assert returned == str(out)
        raw = out.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")  # no BOM
        text = raw.decode("utf-8")
        assert "IŞIK" in text
        assert text == build_ass([line], upper=True)

    def test_written_file_roundtrips_content(self, tmp_path):
        out = tmp_path / "cap2.ass"
        lines = [[WordTiming("a", 0.0, 0.4), WordTiming("b", 0.4, 0.9)]]
        write_ass(str(out), lines)
        text = out.read_text(encoding="utf-8")
        assert "[Script Info]" in text
        assert _dialogue_lines(text)


# ---------------------------------------------------------------------------
# End-to-end (pure): alignment -> phrases -> ASS, timing authority preserved
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    def test_alignment_to_ass_end_time_matches_last_word(self):
        al = _seq_alignment("hello world foo", step=0.1)
        words = group_chars_to_words(al)
        phrases = group_words_into_phrases(words, max_words=2, max_dur=5.0)
        ass = build_ass(phrases)
        dialogues = _dialogue_lines(ass)
        assert len(dialogues) == len(phrases)
        # Each line's \k sum equals its span in centiseconds — timing authority intact.
        for line, dialogue in zip(phrases, dialogues):
            ks = _k_values(dialogue)
            assert sum(ks) == round((line[-1].end - line[0].start) * 100)
