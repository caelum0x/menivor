"""Capture: slideshow/scroll planning, native game command plans, ad job requests, encoding."""

from __future__ import annotations

import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.domains.capture import ads, encode
from app.domains.capture.native import (
    NativeTargetError,
    launch_commands,
    parse_target,
    record_command,
    screenshot_command,
)
from app.domains.capture.slideshow import description_lines, plan_slides
from app.domains.capture.website import budget, plan_chunks


# --------------------------------------------------------------------------- #
# slideshow
# --------------------------------------------------------------------------- #
def test_description_lines_skips_noise_and_truncates() -> None:
    text = "NEW!\n- Sort colorful water into tubes.\n- Sort colorful water into tubes.\n" + "Relax " * 40 + "."
    lines = description_lines(text, limit=5, max_chars=60)
    assert lines[0] == "Sort colorful water into tubes."
    assert len(lines) == 2 and lines[1].endswith("...") and len(lines[1]) <= 63


def test_plan_slides_uses_only_real_listing_facts() -> None:
    listing = {"title": "Orbit Arcade", "developer": "Ereboslab", "description": "Dodge planets in orbit. Chain combos for points.",
               "rating": 4.6, "rating_count": 120, "store": "app_store"}
    segments = plan_slides(listing, has_icon=True, screenshot_count=3)
    texts = [s.card.text for s in segments if s.card]
    assert texts[0] == "Orbit Arcade"
    assert "Dodge planets in orbit." in texts
    assert "Rated 4.6 out of 5" in texts
    assert texts[-1] == "Get Orbit Arcade" and segments[-1].card.subtext == "On the App Store"
    assert all(0 <= s.image_index < 4 for s in segments)
    assert 10 <= sum(s.seconds for s in segments) <= 40


def test_plan_slides_omits_low_or_missing_rating_and_handles_no_icon() -> None:
    listing = {"title": "X", "description": "", "rating": 3.2, "store": "play_store"}
    segments = plan_slides(listing, has_icon=False, screenshot_count=2)
    texts = [s.card.text for s in segments if s.card]
    assert not any(t.startswith("Rated") for t in texts)
    assert segments[-1].card.subtext == "On Google Play"
    assert plan_slides(listing, has_icon=False, screenshot_count=0) == []


# --------------------------------------------------------------------------- #
# website scroll + game inputs
# --------------------------------------------------------------------------- #
def test_plan_chunks_reaches_bottom_in_viewport_steps() -> None:
    stops = plan_chunks(4000, 960)
    assert stops[-1] == 4000 and len(stops) == 6
    assert all(b > a for a, b in zip(stops, stops[1:]))
    assert plan_chunks(0, 960) == []
    assert len(plan_chunks(10**7, 960)) == 14


def test_budget_fits_duration() -> None:
    scroll, pause, up = budget(20, 5)
    total = (scroll + pause) * 5 + up + 1.5 + 1.2 + 1.5
    assert abs(total - 20) < 0.01 and up <= 3.0


def test_native_target_validation() -> None:
    ios = parse_target({"platform": "ios", "app_id": "com.caelum.flowblast", "title": "  Flow   Blast "})
    assert ios.device == "booted" and ios.title == "Flow Blast"
    assert ios.source_url() == "ios-device://booted/com.caelum.flowblast"
    with pytest.raises(NativeTargetError):
        parse_target({"platform": "android"})  # adb serial required
    with pytest.raises(NativeTargetError):
        parse_target({"platform": "web"})
    for bad in ({"device": "booted; rm -rf /"}, {"app_id": "com.x;reboot"}, {"deep_link": "game://play?x=1 && reboot"},
                {"deep_link": "game://play?x='1'"}, {"deep_link": "javascript alert(1)"}, {"settle_s": 99}):
        with pytest.raises(NativeTargetError):
            parse_target({"platform": "ios", **bad})
    with pytest.raises(NativeTargetError):
        parse_target({"platform": "ios", "app_id": "com.other.app"}, allowed_app_ids=("com.caelum.flowblast",))
    with pytest.raises(NativeTargetError):
        parse_target({"platform": "ios"}, allowed_app_ids=("com.caelum.flowblast",))


def test_native_ios_command_plan() -> None:
    link = parse_target({"platform": "ios", "device": "ABCD-1234", "deep_link": "flowblast://play?menivor_demo=1&seed=7"})
    assert launch_commands(link, "xcrun") == [["xcrun", "simctl", "openurl", "ABCD-1234", "flowblast://play?menivor_demo=1&seed=7"]]
    app = parse_target({"platform": "ios", "app_id": "com.caelum.flowblast"})
    assert launch_commands(app, "xcrun") == [
        ["xcrun", "simctl", "launch", "--terminate-running-process", "booted", "com.caelum.flowblast"]]
    assert launch_commands(parse_target({"platform": "ios"}), "xcrun") == []
    assert record_command(app, "xcrun", "/tmp/o.mp4", 30) == [
        "xcrun", "simctl", "io", "booted", "recordVideo", "--codec=h264", "--force", "/tmp/o.mp4"]
    assert screenshot_command(app, "xcrun", "/tmp/s.jpg")[:5] == ["xcrun", "simctl", "io", "booted", "screenshot"]


def test_native_android_command_plan_quotes_the_deep_link_for_the_device_shell() -> None:
    link = parse_target({"platform": "android", "device": "emulator-5554", "app_id": "com.caelum.flowblast",
                         "deep_link": "flowblast://play?menivor_demo=1&seed=7"})
    [cmd] = launch_commands(link, "adb")
    assert cmd[:4] == ["adb", "-s", "emulator-5554", "shell"]
    assert "'flowblast://play?menivor_demo=1&seed=7'" in cmd and cmd[-2:] == ["-p", "com.caelum.flowblast"]
    app = parse_target({"platform": "android", "device": "emulator-5554", "app_id": "com.caelum.flowblast"})
    assert launch_commands(app, "adb") == [["adb", "-s", "emulator-5554", "shell", "monkey", "-p", "com.caelum.flowblast",
                                            "-c", "android.intent.category.LAUNCHER", "1"]]
    assert record_command(app, "adb", "/sdcard/x.mp4", 30) == [
        "adb", "-s", "emulator-5554", "shell", "screenrecord", "--time-limit", "30", "/sdcard/x.mp4"]


# --------------------------------------------------------------------------- #
# ads
# --------------------------------------------------------------------------- #
def _capture(kind: str = "play_store", **meta):
    return SimpleNamespace(id="c" * 32, source_url="https://www.example.com/x", source_kind=kind, meta=meta)


def test_draft_script_store_uses_listing() -> None:
    capture = _capture(listing={"title": "Aqua Sort", "description": "Sort the water into tubes. Relax with calm levels."})
    draft = ads.draft_script(capture)
    assert draft["hook"] == "Sort the water into tubes."
    assert draft["cta"] == "Get Aqua Sort on Google Play."
    assert draft["script"].splitlines()[-1] == draft["cta"]


def test_draft_script_game_and_website() -> None:
    game = ads.draft_script(_capture("native_game", page={"title": "FlowBlast", "platform": "ios"}))
    assert game["hook"] == "This is FlowBlast. Watch a round." and game["cta"] == "Play FlowBlast on the App Store."
    legacy = ads.draft_script(_capture("web_game", page={"title": "FlowBlast"}))  # old rows still read
    assert legacy["cta"] == "Play FlowBlast at example.com."
    site = ads.draft_script(_capture("website", page={"title": "Rally", "description": ""}))
    assert site["hook"] == "Take a look at Rally."


OUTPUT = {"aspect": "9:16", "key": "uploads/abc.mp4", "duration_ms": 21400}


def test_build_job_request_captions_mode() -> None:
    body = ads.build_job_request(_capture(), OUTPUT, mode="captions", script="Hook.\nCTA.", platforms=["tiktok"])
    params = body["params"]
    assert params["screen_recording_key"] == "uploads/abc.mp4"
    assert params["layout"] == "captions_only" and params["aspect"] == "9:16"
    assert params["target_duration_s"] == 21 and params["platforms"] == ["tiktok"]
    assert "avatar_id" not in body and body["tos_disclosure"] is True


def test_build_job_request_avatar_and_voiceover_modes() -> None:
    avatar = ads.build_job_request(_capture(), OUTPUT, mode="avatar", script="Hi.", avatar_id="av1", voice_id="v1")
    assert avatar["params"]["layout"] == "pip" and avatar["avatar_id"] == "av1" and avatar["voice_id"] == "v1"
    voice = ads.build_job_request(_capture(), OUTPUT, mode="voiceover", script="Hi.", voiceover_key="uploads/n.mp3")
    assert voice["voiceover_key"] == "uploads/n.mp3" and voice["params"]["layout"] == "captions_only"
    with pytest.raises(ads.AdRequestError):
        ads.build_job_request(_capture(), OUTPUT, mode="avatar", script="Hi.")
    with pytest.raises(ads.AdRequestError):
        ads.build_job_request(_capture(), OUTPUT, mode="voiceover", script="Hi.")
    with pytest.raises(ads.AdRequestError):
        ads.build_job_request(_capture(), {"aspect": "9:16"}, mode="captions", script="Hi.")
    with pytest.raises(ads.AdRequestError):
        ads.build_job_request(_capture(), OUTPUT, mode="captions", script="   ")


def test_synthesize_voiceover_rejects_paid_voice(tmp_path) -> None:
    with pytest.raises(ads.AdRequestError):
        ads.synthesize_voiceover("Hi.", "elevenlabs:abc", str(tmp_path / "n.mp3"))


# --------------------------------------------------------------------------- #
# encode
# --------------------------------------------------------------------------- #
def test_trim_seconds_clamps() -> None:
    assert encode.trim_seconds(30.0, 4.0, 20.0) == (4.0, 20.0)
    assert encode.trim_seconds(10.0, 4.0, 20.0) == (4.0, 6.0)
    assert encode.trim_seconds(0.0, 3.0, 20.0) == (3.0, 20.0)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_finalize_recording_outputs_exact_size_with_audio(tmp_path) -> None:
    src = str(tmp_path / "src.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=540x960:rate=25:duration=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", src],
        check=True, timeout=60,
    )
    out = str(tmp_path / "out.mp4")
    seconds = encode.finalize_recording(src, out, "9:16", trim_start=1.0, max_seconds=2.0)
    assert os.path.getsize(out) > 0 and 1.5 <= seconds <= 2.6
    if shutil.which("ffprobe"):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "csv=p=0", out],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "video,1080,1920" in probe.replace("\n", ",") or "1080,1920" in probe
        assert "audio" in probe


def test_finalize_recording_rejects_missing_input(tmp_path) -> None:
    with pytest.raises(encode.EncodeError):
        encode.finalize_recording(str(tmp_path / "none.webm"), str(tmp_path / "o.mp4"), "9:16", trim_start=0, max_seconds=5)


def test_record_native_ios_launches_records_and_stops_with_sigint(monkeypatch, tmp_path) -> None:
    import signal

    from app.domains.capture import native

    ran: list[list[str]] = []
    signals: list[int] = []

    class FakeProc:
        def __init__(self, cmd, **_k):
            self.cmd, self.returncode, self.stderr = cmd, None, None
            ran.append(cmd)

        def poll(self):
            return self.returncode

        def send_signal(self, sig):
            signals.append(sig)
            with open(self.cmd[-1], "wb") as fh:  # simctl writes the file on SIGINT
                fh.write(b"\x00" * 32)
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(native.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(native.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(native, "_run", lambda cmd, *a, **k: ran.append(cmd) or b"")
    monkeypatch.setattr(native.time, "sleep", lambda _s: None)
    target = parse_target({"platform": "ios", "app_id": "com.caelum.flowblast", "title": "FlowBlast", "settle_s": 0})
    rec = native.record_native(target, 30, str(tmp_path), capture_id="c" * 32)
    assert ran[0][:3] == ["/usr/bin/xcrun", "simctl", "launch"]
    assert ran[1][3:5] == ["booted", "recordVideo"] and ran[2][4] == "screenshot"
    assert signals == [signal.SIGINT] and os.path.getsize(rec.video_path) == 32
    assert rec.page_meta == {"title": "FlowBlast", "platform": "ios", "app_id": "com.caelum.flowblast",
                             "capture_mode": "native_ios"}


def test_record_native_without_tooling_fails_clearly(monkeypatch, tmp_path) -> None:
    from app.domains.capture import native

    monkeypatch.setattr(native.shutil, "which", lambda name: None)
    with pytest.raises(native.NativeCaptureError, match="adb"):
        native.record_native(parse_target({"platform": "android", "device": "emulator-5554"}), 10, str(tmp_path),
                             capture_id="c" * 32)
