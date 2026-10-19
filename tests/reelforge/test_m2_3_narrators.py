"""M2.3 acceptance: original narrator characters with an audio-driven rig.

* The viseme timeline comes from the audio: mouth frames vary during speech and
  stay closed in silence (energy path always; Rhubarb path when installed).
* A character renders identically across two episodes (reference-sheet hash
  and identical pixels for the same pose).
* No real person or IP name in any narrator's metadata (denylist).
* CPU only: the rig is Pillow + FFmpeg, no GPU or paid model.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.domains.characters import narrator_art, narrators
from app.services.styles import narrator_rig
from app.services.styles.narrator_rig import MouthCue

_HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
_SPEECH_S = 3.0
_SILENCE_S = 1.5


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _speech_then_silence(path: Path, *, seed: int = 0) -> None:
    """Syllable-modulated voiced noise for 3 s, then 1.5 s of digital silence."""
    rate = 3.5 + seed * 0.7
    _ff(
        "-f", "lavfi", "-i",
        f"anoisesrc=color=pink:amplitude=0.5:duration={_SPEECH_S}:sample_rate=16000:seed={seed + 1}",
        "-af",
        f"highpass=f=150,lowpass=f=3800,volume='0.05+0.95*abs(sin(PI*{rate}*t))':eval=frame,"
        f"apad=pad_dur={_SILENCE_S}",
        "-ac", "1", str(path),
    )


# --------------------------------------------------------------------------- #
# Roster and denylist
# --------------------------------------------------------------------------- #
def test_roster_has_six_to_ten_original_characters_with_fixed_voices():
    roster = narrators.list_narrators()
    assert 6 <= len(roster) <= 10
    assert len({n.id for n in roster}) == len(roster)
    assert len({n.name for n in roster}) == len(roster)
    assert len({n.voice for n in roster}) == len(roster), "each narrator has its own voice"
    for n in roster:
        assert n.voice.startswith("kokoro:") and n.fallback_voice
        assert n.personality.strip()


def test_no_real_person_or_ip_name_in_narrator_metadata():
    raw = json.loads(narrators.ROSTER_PATH.read_text(encoding="utf-8"))
    for entry in raw["characters"]:
        text = " ".join(str(entry.get(k, "")) for k in ("id", "name", "personality"))
        assert narrators.denylist_hits(text) == [], entry["id"]


def test_denylist_catches_real_and_ip_names():
    assert narrators.denylist_hits("Narrated by MrBeast") == ["mrbeast"]
    assert "pikachu" in narrators.denylist_hits("a pikachu-style mascot")
    assert narrators.denylist_hits("Pip Marlow, a curious explainer") == []


def test_narrator_for_seed_is_stable():
    a = narrators.narrator_for_seed("series:budget-cooking")
    b = narrators.narrator_for_seed("series:budget-cooking")
    assert a == b


def test_unknown_look_parts_are_rejected():
    with pytest.raises(ValueError):
        narrators._parse_look({"body": "robot", "skin": "#FFFFFF", "accent": "#000000",
                               "backdrop": "#111111", "eyes": "dot", "top": "none"})


# --------------------------------------------------------------------------- #
# Reference sheet lock
# --------------------------------------------------------------------------- #
def test_every_narrator_matches_its_locked_reference_sheet():
    lock = narrators.load_lock()
    for n in narrators.list_narrators():
        assert lock.get(n.id) == narrator_art.sheet_hash(n), f"{n.id} art drifted from the lock"
        assert (narrators.LOCK_PATH.parent / n.id / "sheet.png").is_file()


def test_sheets_differ_between_characters():
    hashes = {narrator_art.sheet_hash(n) for n in narrators.list_narrators()}
    assert len(hashes) == len(narrators.list_narrators())


def test_same_pose_rasterises_identically():
    n = narrators.get_narrator("pip")
    narrator_art._render_cached.cache_clear()
    first = narrator_art.render_pose(n, "D", True, 220).tobytes()
    narrator_art._render_cached.cache_clear()
    second = narrator_art.render_pose(n, "D", True, 220).tobytes()
    assert first == second


def test_open_and_closed_mouths_render_differently():
    n = narrators.get_narrator("otto")
    frames = {m: narrator_art.render_pose(n, m, True, 160).tobytes() for m in narrator_art.MOUTH_SHAPES}
    assert len(set(frames.values())) == len(narrator_art.MOUTH_SHAPES)


# --------------------------------------------------------------------------- #
# Frame schedule
# --------------------------------------------------------------------------- #
def test_mouth_track_is_closed_outside_cues():
    cues = [MouthCue(0.0, 0.2, "D"), MouthCue(0.2, 0.4, "C"), MouthCue(0.4, 1.0, "X")]
    track = narrator_rig.mouth_track(cues, 45, fps=30)
    assert track[:6] == ["D"] * 6 and track[6:12] == ["C"] * 6
    assert set(track[12:]) == {"X"}


def test_blink_track_is_fixed_per_character_and_blinks():
    a = narrator_rig.blink_track("pip", 300)
    assert a == narrator_rig.blink_track("pip", 300)
    assert False in a and a.count(False) < 40


# --------------------------------------------------------------------------- #
# Viseme timeline from audio
# --------------------------------------------------------------------------- #
def _check_timeline(cues: list[MouthCue]) -> None:
    track = narrator_rig.mouth_track(cues, int((_SPEECH_S + _SILENCE_S) * 30), fps=30)
    speech = track[3:int(_SPEECH_S * 30) - 3]
    silence = track[int((_SPEECH_S + 0.4) * 30):]
    assert len(set(speech)) >= 3, f"mouth barely moves during speech: {set(speech)}"
    assert any(m not in narrator_art.CLOSED_SHAPES for m in speech)
    assert set(silence) == {"X"}, f"mouth not closed in silence: {set(silence)}"


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg required")
def test_energy_timeline_moves_in_speech_and_rests_in_silence(tmp_path):
    audio = tmp_path / "voice.wav"
    _speech_then_silence(audio)
    _check_timeline(narrator_rig.energy_cues(str(audio), ffmpeg="ffmpeg"))


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg required")
def test_energy_timeline_is_silent_for_silence(tmp_path):
    audio = tmp_path / "silence.wav"
    _ff("-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "1", str(audio))
    cues = narrator_rig.energy_cues(str(audio), ffmpeg="ffmpeg")
    assert {c.value for c in cues} <= {"X"}


@pytest.mark.skipif(
    not (_HAVE_FFMPEG and narrator_rig.rhubarb_binary() and shutil.which("say")),
    reason="Rhubarb (RHUBARB_BIN) and a system TTS (say) are required",
)
def test_rhubarb_timeline_on_real_speech(tmp_path):
    aiff = tmp_path / "speech.aiff"
    subprocess.run(["say", "-o", str(aiff), "I found the best way to save money on groceries."], check=True)
    audio = tmp_path / "speech.wav"
    _ff("-i", str(aiff), "-af", f"apad=pad_dur={_SILENCE_S}", "-ar", "16000", "-ac", "1", str(audio))
    cues, source = narrator_rig.viseme_cues(str(audio), str(tmp_path), ffmpeg="ffmpeg")
    assert source == "rhubarb"
    shapes = {c.value for c in cues}
    assert len(shapes - narrator_art.CLOSED_SHAPES) >= 3
    assert cues[-1].value == "X"


def test_rhubarb_missing_falls_back_to_energy(monkeypatch, tmp_path):
    monkeypatch.setattr(narrator_rig, "rhubarb_binary", lambda: None)
    monkeypatch.setattr(narrator_rig, "energy_cues", lambda *a, **k: [MouthCue(0, 1, "C")])
    cues, source = narrator_rig.viseme_cues("x.wav", str(tmp_path))
    assert source == "energy" and cues[0].value == "C"


# --------------------------------------------------------------------------- #
# Two episodes, one character
# --------------------------------------------------------------------------- #
def _frame_md5(clip: Path, t: float) -> str:
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(clip),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout
    return hashlib.md5(raw).hexdigest()


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg required")
def test_character_renders_identically_across_two_episodes(tmp_path, monkeypatch):
    monkeypatch.setattr(narrator_rig, "rhubarb_binary", lambda: None)  # deterministic path
    n = narrators.get_narrator("wren")
    clips = []
    for episode in (1, 2):
        audio = tmp_path / f"ep{episode}.wav"
        _speech_then_silence(audio, seed=episode)
        out = tmp_path / f"ep{episode}.mp4"
        clips.append(narrator_rig.render_narrator_clip(n, str(audio), str(out), work_dir=str(tmp_path),
                                                       size=220, ffmpeg="ffmpeg"))
    first, second = clips
    assert first.sheet_sha256 == second.sheet_sha256 == narrators.load_lock()["wren"]
    assert [c.value for c in first.cues] != [c.value for c in second.cues]  # different episodes
    # The rest pose in the silent tail is the same image in both episodes.
    t = _SPEECH_S + _SILENCE_S - 0.5
    assert _frame_md5(Path(first.path), t) == _frame_md5(Path(second.path), t)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags=comment:stream=width,height,codec_name",
         "-of", "json", first.path], capture_output=True, text=True, check=True,
    )
    info = json.loads(probe.stdout)
    assert info["streams"][0]["width"] == 220 and info["streams"][0]["codec_name"] == "h264"
    assert info["format"]["tags"]["comment"] == f"menivor-narrator:wren:{first.sheet_sha256}"


# --------------------------------------------------------------------------- #
# Art gate and API
# --------------------------------------------------------------------------- #
def test_rig_is_gated_until_the_owner_approves_the_art(monkeypatch):
    monkeypatch.delenv("MENIVOR_NARRATOR_RIG", raising=False)
    raw = json.loads(narrators.ROSTER_PATH.read_text(encoding="utf-8"))
    assert narrator_rig.rig_enabled() is (raw["art_status"] == "approved")
    monkeypatch.setenv("MENIVOR_NARRATOR_RIG", "1")
    assert narrator_rig.rig_enabled() is True


def test_narrators_route_lists_the_roster():
    import importlib

    router_mod = importlib.import_module("app.domains.characters.router")

    app = FastAPI()
    app.include_router(router_mod.router)
    body = TestClient(app).get("/api/v1/characters/narrators").json()
    data = body.get("data", body)
    assert len(data["narrators"]) == len(narrators.list_narrators())
    assert all(item["sheet_sha256"] for item in data["narrators"])
    assert "available" in data
