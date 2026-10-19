"""M2.4 acceptance: captions in 2-4 word phrases with keyword emphasis, music
at least 12 dB under the voice during speech, and a licence record for every
audio asset.

The loudness test runs real FFmpeg (``ebur128`` + the compose sidechain
constants) and is skipped only when FFmpeg or a needed filter is missing.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.audio import leveling, licences
from app.services.captions import emphasis
from app.services.captions.ass_karaoke import KaraokeStyle, build_ass, write_ass
from app.services.captions.presets import CAPTION_STYLE_PRESETS
from app.services.captions.words import WordTiming, group_words_into_phrases


# --------------------------------------------------------------------------- #
# Phrase segmentation: 2-4 words
# --------------------------------------------------------------------------- #
def _random_words(rng: random.Random, count: int) -> list[WordTiming]:
    words: list[WordTiming] = []
    t = 0.0
    for i in range(count):
        t += rng.choice([0.02, 0.05, 0.1, 0.3, 0.6, 1.2])  # tight to long pauses
        dur = rng.choice([0.12, 0.2, 0.35, 0.8, 1.6])  # includes over-long words
        words.append(WordTiming(f"w{i}", round(t, 3), round(t + dur, 3)))
        t += dur
    return words


@pytest.mark.parametrize("seed", range(60))
def test_phrases_stay_within_two_to_four_words(seed):
    rng = random.Random(seed)
    words = _random_words(rng, rng.randint(2, 80))
    phrases = group_words_into_phrases(words)
    assert all(2 <= len(p) <= 4 for p in phrases), [len(p) for p in phrases]
    assert [w for p in phrases for w in p] == words  # order and timing unchanged


def test_one_word_script_is_a_single_line():
    (line,) = group_words_into_phrases([WordTiming("hello", 0.0, 0.4)])
    assert [w.text for w in line] == ["hello"]


def test_short_line_borrows_from_a_full_neighbour():
    # Four quick words, a long pause, then one word: the split gives [4, 1];
    # merging would make 5, so the lone word borrows one and both lines stay 2-4.
    words = [WordTiming(f"a{i}", i * 0.2, i * 0.2 + 0.15) for i in range(4)]
    words.append(WordTiming("tail", 3.0, 3.3))
    phrases = group_words_into_phrases(words)
    assert [len(p) for p in phrases] == [3, 2]


# --------------------------------------------------------------------------- #
# Keyword emphasis: Relay Haiku first, deterministic fallback
# --------------------------------------------------------------------------- #
_LINES = [
    [WordTiming("the", 0.0, 0.2), WordTiming("money", 0.2, 0.5)],
    [WordTiming("it", 0.6, 0.7), WordTiming("is", 0.7, 0.8), WordTiming("gone", 0.8, 1.2)],
]


def test_deterministic_emphasis_picks_content_words():
    assert emphasis.deterministic_emphasis(_LINES) == [1, 2]


def test_llm_answer_is_used_when_valid():
    picks = emphasis.pick_emphasis(_LINES, chat=lambda _p: '{"1": "money", "2": "is"}')
    assert picks == [1, 1]


def test_llm_cannot_introduce_a_word_and_bad_lines_fall_back():
    answer = 'Sure: {"1": "billionaire", "2": 7}'
    assert emphasis.pick_emphasis(_LINES, chat=lambda _p: answer) == [1, 2]


def test_llm_null_means_no_emphasis():
    assert emphasis.pick_emphasis(_LINES, chat=lambda _p: '{"1": null}') == [None, 2]


def test_llm_failure_falls_back_to_deterministic():
    def boom(_prompt):
        raise TimeoutError("relay slow")

    assert emphasis.pick_emphasis(_LINES, chat=boom) == [1, 2]


def test_llm_garbage_falls_back_to_deterministic():
    assert emphasis.pick_emphasis(_LINES, chat=lambda _p: "no json here") == [1, 2]


def test_relay_call_uses_haiku_on_the_anthropic_provider(monkeypatch):
    seen = {}

    def fake_run_chat_text(**kwargs):
        seen.update(kwargs)
        return '{"1": "money", "2": "gone"}'

    import app.domains.railyard as railyard

    monkeypatch.setattr(railyard, "run_chat_text", fake_run_chat_text)
    monkeypatch.setattr(emphasis, "_llm_enabled", lambda: True)
    assert emphasis.pick_emphasis(_LINES) == [1, 2]
    assert seen["model"] == emphasis.EMPHASIS_MODEL
    assert "haiku" in seen["model"]
    assert seen["relay_provider"] == "anthropic"
    assert seen["temperature"] == 0.0


def test_relay_off_uses_no_network(monkeypatch):
    monkeypatch.setattr(emphasis, "_llm_enabled", lambda: False)
    monkeypatch.setattr(
        emphasis, "_relay_haiku_chat", lambda _p: pytest.fail("Relay must not be called")
    )
    assert emphasis.pick_emphasis(_LINES) == [1, 2]


def test_env_flag_disables_llm(monkeypatch):
    monkeypatch.setenv("MENIVOR_CAPTION_EMPHASIS_LLM", "0")
    assert emphasis._llm_enabled() is False


def test_build_ass_draws_the_keyword_in_the_emphasis_colour():
    style = KaraokeStyle(emphasis="&H0014FF39")
    ass = build_ass(_LINES, style=style, emphasis=[1, None])
    first, second = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
    assert r"{\1c&H14FF39&\2c&H14FF39&}money{\1c&HFFFFFF&\2c&H00FFFF&}" in first
    assert r"\1c" not in second


def test_build_ass_without_emphasis_colour_has_no_overrides():
    ass = build_ass(_LINES, style=KaraokeStyle(emphasis=None))
    assert r"\1c" not in ass


def test_write_ass_uses_the_relay_pick(tmp_path, monkeypatch):
    monkeypatch.setattr(emphasis, "_llm_enabled", lambda: True)
    monkeypatch.setattr(emphasis, "_relay_haiku_chat", lambda _p: '{"1": "the", "2": "it"}')
    path = write_ass(str(tmp_path / "c.ass"), _LINES, style=KaraokeStyle())
    text = Path(path).read_text(encoding="utf-8")
    assert r"&H14FF39&}the{" in text and r"&H14FF39&}it{" in text


def test_every_preset_has_a_distinct_emphasis_colour():
    for name, style in CAPTION_STYLE_PRESETS.items():
        assert style.emphasis, name
        assert style.emphasis not in (style.primary, style.secondary), name


# --------------------------------------------------------------------------- #
# Licence record for every audio asset
# --------------------------------------------------------------------------- #
def test_every_audio_asset_has_a_licence_record():
    manifest = licences.load_manifest()
    on_disk = list(licences.iter_audio_assets())
    assert on_disk, "expected bundled audio assets"
    missing = [p for p in on_disk if p not in manifest]
    assert not missing, f"audio assets without a licence record: {missing}"


def test_licence_records_match_the_files():
    manifest = licences.load_manifest()
    root = licences.assets_root()
    for path, record in manifest.items():
        file = root / path
        assert file.is_file(), f"licence record for a missing file: {path}"
        assert licences.file_sha256(file) == record["sha256"], f"{path} changed; update its record"
        assert str(record["source"]).strip() and str(record["licence"]).strip()
        assert isinstance(record["cleared_for_output"], bool)


def test_unknown_licences_are_never_marked_cleared():
    for path, record in licences.load_manifest().items():
        if str(record["licence"]).lower() == "unknown":
            assert record["cleared_for_output"] is False, path


def test_music_library_reports_licence_and_honours_cleared_only(monkeypatch):
    from app.services import music

    tracks = music.list_music()
    assert tracks and all("licence" in t and "cleared" in t for t in tracks)
    monkeypatch.setenv("MENIVOR_MUSIC_CLEARED_ONLY", "1")
    cleared = [t for t in tracks if t["cleared"]]
    assert len(music.list_music()) == len(cleared)
    for t in tracks:
        if not t["cleared"]:
            assert music.get_music_path(t["id"]) is None


# --------------------------------------------------------------------------- #
# Music at least 12 dB under the voice during speech (ffmpeg ebur128)
# --------------------------------------------------------------------------- #
def test_bed_gain_targets_the_voice_offset():
    assert leveling.bed_gain_db(-18.0, -10.0) == -24.0
    assert leveling.bed_gain_db(None, -10.0) == leveling.FALLBACK_VOICE_LUFS - 16.0 + 10.0
    assert leveling.bed_gain_db(-18.0, -60.0) == leveling.MAX_BOOST_DB


def test_parse_ebur128_takes_the_summary_value():
    stderr = "t: 1 M: -20 S: -20 I: -21.0 LUFS LRA: 0\n  Integrated loudness:\n    I:         -19.4 LUFS\n"
    assert leveling.parse_ebur128_integrated(stderr) == -19.4
    assert leveling.parse_ebur128_integrated("I: -70.0 LUFS") is None


def test_prepare_music_bed_never_raises(tmp_path):
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"not audio")
    out = tmp_path / "bed.wav"
    assert leveling.prepare_music_bed(str(junk), None, str(out)) == str(junk)
    assert leveling.prepare_music_bed(None, None, str(out)) is None


def _ffmpeg_has(*filters: str) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    listing = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=False
    ).stdout
    return all(f" {name} " in listing for name in filters)


_SPEECH_S = 6.0


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _speech_like_voice(path: Path) -> None:
    # Pink noise, band-limited to the voice range, with a 4 Hz syllable
    # envelope: 6 s of "speech" then 2 s of silence.
    _ff(
        "-f", "lavfi", "-i",
        f"anoisesrc=color=pink:amplitude=0.5:duration={_SPEECH_S}:sample_rate=48000",
        "-af",
        "highpass=f=200,lowpass=f=3500,volume='0.35+0.65*abs(sin(2*PI*4*t))':eval=frame,"
        "apad=pad_dur=2",
        "-ac", "1", str(path),
    )


def _loud_music(path: Path) -> None:
    # A loud, dense chord: mastered far hotter than a TTS voice.
    _ff(
        "-f", "lavfi", "-i", "sine=f=220:d=8:sample_rate=48000",
        "-f", "lavfi", "-i", "sine=f=277:d=8:sample_rate=48000",
        "-f", "lavfi", "-i", "sine=f=330:d=8:sample_rate=48000",
        "-filter_complex", "[0:a][1:a][2:a]amix=inputs=3:normalize=0,volume=0.9",
        "-ac", "1", str(path),
    )


def _ducked_music(voice: Path, music: Path, out: Path) -> None:
    """Run compose's own sidechain stage (same constants) and keep the music."""
    from app.services.compose import compose_ffmpeg as cf

    graph = (
        "[0:a]asplit=2[vo][vo_key];"
        f"[1:a][vo_key]sidechaincompress=threshold={cf._DUCK_THRESHOLD:g}:"
        f"ratio={cf._DUCK_RATIO:g}:attack={cf._DUCK_ATTACK:g}:release={cf._DUCK_RELEASE:g}[duck];"
        "[vo]anullsink"
    )
    _ff("-i", str(voice), "-i", str(music), "-filter_complex", graph, "-map", "[duck]", str(out))


def _speech_margin(voice: Path, ducked: Path) -> float:
    window = dict(start_s=0.5, duration_s=_SPEECH_S - 1.0, ffmpeg="ffmpeg")
    v = leveling.measure_integrated_lufs(str(voice), **window)
    m = leveling.measure_integrated_lufs(str(ducked), **window)
    assert v is not None and m is not None
    return v - m


@pytest.mark.skipif(
    not _ffmpeg_has("ebur128", "sidechaincompress", "anoisesrc", "volume"),
    reason="ffmpeg with ebur128/sidechaincompress is required",
)
def test_music_sits_at_least_12_db_under_the_voice_during_speech(tmp_path):
    voice, music = tmp_path / "voice.wav", tmp_path / "music.wav"
    _speech_like_voice(voice)
    _loud_music(music)

    # Without the bed, compose's ducking alone leaves the hot track too loud.
    raw_ducked = tmp_path / "raw_ducked.wav"
    _ducked_music(voice, music, raw_ducked)
    assert _speech_margin(voice, raw_ducked) < leveling.MIN_SPEECH_MARGIN_DB

    bed = leveling.prepare_music_bed(str(music), str(voice), str(tmp_path / "bed.wav"), )
    assert bed == str(tmp_path / "bed.wav")
    ducked = tmp_path / "ducked.wav"
    _ducked_music(voice, Path(bed), ducked)
    margin = _speech_margin(voice, ducked)
    assert margin >= leveling.MIN_SPEECH_MARGIN_DB, f"music only {margin:.1f} dB under voice"


@pytest.mark.skipif(not _ffmpeg_has("ebur128", "volume"), reason="ffmpeg ebur128 required")
def test_bundled_track_bed_is_levelled_against_a_voice(tmp_path):
    record_path = next(iter(licences.load_manifest()))
    track = licences.assets_root() / record_path
    voice = tmp_path / "voice.wav"
    _speech_like_voice(voice)
    bed = leveling.prepare_music_bed(str(track), str(voice), str(tmp_path / "bed.wav"))
    v = leveling.measure_integrated_lufs(str(voice), ffmpeg="ffmpeg")
    b = leveling.measure_integrated_lufs(bed, ffmpeg="ffmpeg")
    assert v is not None and b is not None
    assert v - b == pytest.approx(leveling.MUSIC_UNDER_VOICE_LU, abs=1.0)


def test_manifest_file_is_valid_json():
    data = json.loads(licences.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert data["schema"] == 1 and isinstance(data["assets"], list)
    assert os.path.basename(licences.MANIFEST_PATH) == "asset_licences.json"
