"""Wave P PM1.1: the 27 full showcase reels with sound.

Covers the render job (missing set against the checked-in manifest, paid-model
skip list, off-peak and paid-lane gating, the loudness-normalised 720x1280
encode, the dry-run upload plan with no deletes) and the new ``checks.py`` full
reel checks (audio present, loudness target, no silent tail, M2.4 caption
phrases, no vendor or model names).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SHOWCASE = Path(__file__).resolve().parents[2] / "apps" / "api" / "tools" / "ops" / "showcase"
sys.path.insert(0, str(SHOWCASE))

import checks  # noqa: E402
import plan  # noqa: E402
import render_full  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# --------------------------------------------------------------------------- #
# Manifest and missing set
# --------------------------------------------------------------------------- #
def test_manifest_lists_the_27_plan_reels_in_sources_order():
    manifest = render_full.load_manifest()
    sources = render_full.source_keys()
    assert len(manifest["keys"]) == 27
    assert manifest["keys"] == sources == [r["key"] for r in plan.REELS]
    assert manifest["width"] == 720 and manifest["height"] == 1280


def test_missing_set_skips_files_that_pass_and_keeps_manifest_order(tmp_path):
    keys = ["a", "b", "c", "d"]
    (tmp_path / "b-full.mp4").write_bytes(b"x")
    (tmp_path / "c-full.mp4").write_bytes(b"x")
    verdicts = {"b": True, "c": False}
    missing = render_full.missing_set(
        keys, keys, str(tmp_path), passes=lambda key, path: verdicts[key])
    assert missing == ["a", "c", "d"]


def test_missing_set_refuses_manifest_drift(tmp_path):
    with pytest.raises(render_full.ManifestDrift) as err:
        render_full.missing_set(["a", "b"], ["a", "c"], str(tmp_path), passes=lambda k, p: True)
    assert "b" in str(err.value) and "c" in str(err.value)


# --------------------------------------------------------------------------- #
# Paid-model skip list
# --------------------------------------------------------------------------- #
def test_no_plan_reel_needs_a_paid_model():
    assert [r["key"] for r in plan.REELS if render_full.paid_model_reason(r)] == []


@pytest.mark.parametrize("style", ["ugc_avatar", "greenscreen", "anime"])
def test_presenter_and_ai_art_styles_are_skipped_and_listed(style):
    reel = {"key": "x", "style": style}
    assert render_full.paid_model_reason(reel)


def test_character_style_uses_the_free_narrator_art():
    assert render_full.paid_model_reason({"key": "x", "style": "character_story"}) is None


# --------------------------------------------------------------------------- #
# Scheduling: off-peak, never ahead of paid renders
# --------------------------------------------------------------------------- #
def test_gate_refuses_outside_offpeak_without_now():
    noon = dt.datetime(2026, 9, 30, 12, 0)
    ok, why = render_full.may_render(noon, now_flag=False, window=(1, 7), paid_busy=lambda: False)
    assert not ok and "off-peak" in why


def test_gate_defers_while_paid_renders_wait():
    night = dt.datetime(2026, 9, 30, 3, 0)
    ok, why = render_full.may_render(night, now_flag=False, window=(1, 7), paid_busy=lambda: True)
    assert not ok and "paid" in why
    ok, _ = render_full.may_render(night, now_flag=False, window=(1, 7), paid_busy=lambda: False)
    assert ok


def test_paid_queue_probe_is_off_without_a_broker(monkeypatch):
    monkeypatch.delenv("SHOWCASE_BROKER_URL", raising=False)
    assert render_full.paid_queue_busy() is False


def test_paid_queue_probe_reads_the_paid_and_first_lanes():
    class FakeRedis:
        def __init__(self, lengths):
            self.lengths = lengths

        def llen(self, name):
            return self.lengths.get(name, 0)

    assert render_full.paid_queue_busy(client=FakeRedis({"render": 1})) is True
    assert render_full.paid_queue_busy(client=FakeRedis({"render_first": 2})) is True
    assert render_full.paid_queue_busy(client=FakeRedis({"render_bulk": 9})) is False


# --------------------------------------------------------------------------- #
# Upload plan (dry run, no deletes)
# --------------------------------------------------------------------------- #
def test_upload_plan_lists_27_private_full_uploads_and_no_deletes(tmp_path):
    lines = render_full.upload_plan([r["key"] for r in plan.REELS], staging=str(tmp_path))
    private = [line for line in lines if " marketing/showcase/" in line]
    assert len(private) == 27
    assert all(line.startswith("PUT (deploy step)") for line in lines)
    assert not any("delete" in line.lower() or "rm " in line.lower() for line in lines)


# --------------------------------------------------------------------------- #
# checks.py: parsers and rules
# --------------------------------------------------------------------------- #
EBUR_TAIL = """
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -15.2 LUFS
    Threshold: -25.5 LUFS
"""


def test_integrated_loudness_is_parsed_from_the_ebur128_summary():
    assert checks.parse_integrated_lufs(EBUR_TAIL) == pytest.approx(-15.2)
    assert checks.parse_integrated_lufs("no summary") is None


def test_silent_tail_is_found_from_silencedetect_output():
    log = ("[silencedetect @ 0x1] silence_start: 3.1\n[silencedetect @ 0x1] silence_end: 3.6 | silence_duration: 0.5\n"
           "[silencedetect @ 0x1] silence_start: 24.0\n")
    assert checks.silent_tail_seconds(log, duration_s=27.0) == pytest.approx(3.0)
    closed = log + "[silencedetect @ 0x1] silence_end: 27.0 | silence_duration: 3.0\n"
    assert checks.silent_tail_seconds(closed, duration_s=27.0) == pytest.approx(3.0)
    assert checks.silent_tail_seconds(log.split("[silencedetect @ 0x1] silence_start: 24.0")[0],
                                      duration_s=27.0) == 0.0


ASS = """[Script Info]
Title: x

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{\\k20}This {\\k30}serum {\\c&H00FFFF&}is{\\r}
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\k20}the only step
"""


def test_caption_phrases_follow_the_m2_4_rule():
    assert checks.caption_phrase_violations(ASS) == []
    long_line = ASS + "Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,one two three four five\n"
    assert checks.caption_phrase_violations(long_line) == ["line 3 has 5 words"]
    lone = ASS + "Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,alone\n"
    assert checks.caption_phrase_violations(lone) == ["line 3 has 1 word"]
    assert checks.caption_phrase_violations("[Events]\n") == ["no caption lines"]


def test_vendor_and_model_names_are_caught():
    assert checks.vendor_hits("Voiced with ElevenLabs and edited in ComfyUI")
    assert checks.vendor_hits("Made by our team with care") == []


def test_every_plan_reel_is_free_of_vendor_names():
    for reel in plan.REELS:
        text = " ".join(str(reel.get(k) or "") for k in ("script", "label", "niche"))
        assert checks.vendor_hits(text) == [], reel["key"]


def test_full_verdict_combines_every_rule(tmp_path, monkeypatch):
    video = tmp_path / "k-full.mp4"
    video.write_bytes(b"x")
    ass = tmp_path / "k-captions.ass"
    ass.write_text(ASS)
    good = {"duration_s": 27.0, "audio_streams": 1, "video_streams": 1, "width": 720, "height": 1280}
    monkeypatch.setattr(checks, "probe_full", lambda p: dict(good))
    monkeypatch.setattr(checks, "integrated_lufs", lambda p: -15.1)
    monkeypatch.setattr(checks, "silence_log", lambda p: "")
    reel = {"key": "k", "script": "Fresh bread every morning", "label": "Voiceover reel", "niche": "Bakery"}
    verdict = checks.full_verdict(str(video), str(ass), reel)
    assert verdict["ok"], verdict

    monkeypatch.setattr(checks, "integrated_lufs", lambda p: -21.0)
    monkeypatch.setattr(checks, "probe_full", lambda p: {**good, "audio_streams": 0, "width": 540})
    verdict = checks.full_verdict(str(video), str(ass), {**reel, "script": "made with openai"})
    joined = "; ".join(verdict["errors"])
    for part in ("no audio", "540x", "loudness", "vendor"):
        assert part in joined, joined


# --------------------------------------------------------------------------- #
# Real FFmpeg: the encode hits the loudness target at 720x1280 with audio
# --------------------------------------------------------------------------- #
@pytest.mark.integration
@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_encode_full_normalises_loudness_and_size(tmp_path):
    master = tmp_path / "m.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=22",
         "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=22",
         "-filter:a", "volume=-24dB", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(master)],
        check=True, timeout=120,
    )
    out = tmp_path / "m-full.mp4"
    render_full.encode_full(str(master), str(out))
    info = checks.probe_full(str(out))
    assert (info["width"], info["height"]) == (720, 1280)
    assert info["audio_streams"] == 1
    lufs = checks.integrated_lufs(str(out))
    assert checks.LUFS_MIN <= lufs <= checks.LUFS_MAX, lufs
    assert checks.silent_tail_seconds(checks.silence_log(str(out)), info["duration_s"]) == 0.0


def test_results_are_written_as_json(tmp_path):
    path = tmp_path / "r.json"
    render_full.write_results(str(path), [{"key": "a", "ok": True}], skipped={"b": "needs a presenter"})
    data = json.loads(path.read_text())
    assert data["rendered"] == [{"key": "a", "ok": True}]
    assert data["skipped_paid_model"] == {"b": "needs a presenter"}
    assert os.path.getsize(path) > 0
