"""M1.2: single-pass compose for faceless style reels.

Pure tests cover the graph, the input order and the eligibility rules. The
golden-frame tests render every non-presenter style both ways with a real
FFmpeg (libass + drawtext) and check the single pass matches the two-pass
output frame for frame, with ONE full encode instead of two.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import replace
from typing import Any

import pytest

from app.services.reelforge import ReelForgeParams

NON_PRESENTER_STYLES = (
    "gameplay_split",
    "meme_hook",
    "anime",
    "satisfying_split",
    "pov_text",
    "before_after",
    "story_gameplay",
    "character_story",
)


def _params(**over: Any) -> ReelForgeParams:
    base: dict[str, Any] = {
        "video_subject": "Menivor",
        "voice_name": "en-US-AriaNeural",
        "layout": "captions_only",
        "style": "gameplay_split",
    }
    base.update(over)
    return ReelForgeParams(**base)


# --------------------------------------------------------------------------- #
# Pure: graph and command
# --------------------------------------------------------------------------- #
def test_graph_chains_scene_captions_and_narration_input():
    from app.services.compose.single_pass import build_filtergraph

    graph, vmap, amap = build_filtergraph(
        "[0:v]null[out]", 2, width=1080, height=1920, scene_size=(1080, 1920),
        ass_path=None, music=False, watermark=False,
    )
    assert graph == "[0:v]null[out];[out]null[final]"
    assert (vmap, amap) == ("[final]", "2:a")


def test_graph_fills_only_when_the_aspect_differs_and_indexes_music_and_logo():
    from app.services.compose.single_pass import build_filtergraph

    graph, vmap, amap = build_filtergraph(
        "[0:v]null[out]", 3, width=1080, height=1080, scene_size=(1080, 1920),
        ass_path=None, music=True, watermark=True,
    )
    assert "[out]scale=1080:1080" in graph
    assert "[3:a]asplit" in graph and "[4:a][vo_key]sidechaincompress" in graph
    assert "[5:v]scale=" in graph  # logo after narration and music
    assert (vmap, amap) == ("[wm]", "[aout]")


def test_command_puts_scene_inputs_first_and_uses_live_settings(monkeypatch):
    from app.services.compose.single_pass import build_command

    monkeypatch.delenv("MENIVOR_X264_PRESET", raising=False)
    argv = build_command(
        "ffmpeg", ["-i", "scene0.png", "-i", "loop.mp4"], "a.m4a", "o.mp4", "G", "libx264",
        video_map="[final]", audio_map="2:a", music_path="m.mp3",
    )
    inputs = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-i"]
    assert inputs == ["scene0.png", "loop.mp4", "a.m4a", "m.mp3"]
    assert argv[argv.index("-g") + 1] == "60"
    assert argv[argv.index("-preset") + 1] == "veryfast"


def test_single_pass_flag_defaults_on(monkeypatch):
    from app.services.compose.single_pass import single_pass_enabled

    monkeypatch.delenv("COMPOSE_SINGLE_PASS", raising=False)
    assert single_pass_enabled()
    for off in ("off", "0", "false", "NO"):
        monkeypatch.setenv("COMPOSE_SINGLE_PASS", off)
        assert not single_pass_enabled()


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #
def test_eligible_for_a_faceless_style(monkeypatch):
    from app.services import reelforge

    monkeypatch.delenv("COMPOSE_SINGLE_PASS", raising=False)
    assert reelforge._single_pass_eligible(_params())


@pytest.mark.parametrize(
    "over",
    [
        {"style": ""},
        {"screen_recording_key": "jobs/x/screen.mp4"},
        {"layout": "pip"},
        {"auto_tighten": True},
        {"auto_zoom": True},
        {"camera_motion": "ken_burns"},
        {"music_prompt": "lofi"},
    ],
)
def test_not_eligible_when_a_step_needs_a_rendered_screen(monkeypatch, over):
    from app.services import reelforge

    monkeypatch.delenv("COMPOSE_SINGLE_PASS", raising=False)
    assert not reelforge._single_pass_eligible(_params(**over))


def test_flag_off_keeps_the_two_pass_path(monkeypatch):
    from app.services import reelforge

    monkeypatch.setenv("COMPOSE_SINGLE_PASS", "off")
    assert not reelforge._single_pass_eligible(_params())


def test_catalog_moves_still_single_pass(monkeypatch):
    from app.services import reelforge

    monkeypatch.delenv("COMPOSE_SINGLE_PASS", raising=False)
    assert reelforge._single_pass_eligible(_params(camera_motion="dolly_in"))


# --------------------------------------------------------------------------- #
# Encode tally
# --------------------------------------------------------------------------- #
def test_tally_counts_only_inside_the_block():
    from app.services.compose import encode_count

    encode_count.count("compose")  # no active tally: ignored
    with encode_count.tally() as counts:
        encode_count.count("scene")
        encode_count.count("compose")
    encode_count.count("compose")
    assert counts == {"scene": 1, "compose": 1}
    assert encode_count.total(counts) == 2


# --------------------------------------------------------------------------- #
# Real FFmpeg: golden frames and encode count
# --------------------------------------------------------------------------- #
def _full_ffmpeg() -> str:
    candidates = [os.environ.get("IMAGEIO_FFMPEG_EXE", ""), shutil.which("ffmpeg") or ""]
    try:
        import imageio_ffmpeg

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        pass
    for binary in candidates:
        if not binary:
            continue
        try:
            out = subprocess.run([binary, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20).stdout
        except Exception:  # noqa: BLE001
            continue
        if re.search(r"\sass\s", out) and re.search(r"\sdrawtext\s", out):
            return binary
    return ""


FULL_FFMPEG = _full_ffmpeg()
needs_full_ffmpeg = pytest.mark.skipif(not FULL_FFMPEG, reason="no FFmpeg with libass + drawtext")

_ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,2,40,40,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:03.00,Default,,0,0,0,,One click makes the reel
"""


def _run(argv: list[str]) -> None:
    subprocess.run(argv, check=True, capture_output=True, timeout=180)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    if not FULL_FFMPEG:
        pytest.skip("no FFmpeg with libass + drawtext")
    root = tmp_path_factory.mktemp("m12")
    ff = [FULL_FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    loop = root / "loop.mp4"
    _run([*ff, "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=4", "-c:v", "libx264",
          "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(loop)])
    page = root / "page.mp4"
    _run([*ff, "-f", "lavfi", "-i", "smptehdbars=s=1080x960:r=30:d=4", "-c:v", "libx264",
          "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(page)])
    images = []
    for index, source in enumerate(("testsrc=s=800x800", "rgbtestsrc=s=800x800", "smptebars=s=800x800")):
        image = root / f"img{index}.png"
        _run([*ff, "-f", "lavfi", "-i", source, "-frames:v", "1", str(image)])
        images.append(str(image))
    audio = root / "voice.m4a"
    _run([*ff, "-f", "lavfi", "-i", "sine=frequency=330:duration=3", "-c:a", "aac", str(audio)])
    ass = root / "captions.ass"
    ass.write_text(_ASS, encoding="utf-8")
    return {"root": root, "loop": str(loop), "page": str(page), "images": images,
            "audio": str(audio), "ass": str(ass)}


def _scene_kwargs(style_id: str, media: dict, work: str) -> dict:
    from app.domains.styles.catalog import get_style
    from app.services.styles import scene as scene_mod
    from app.services.styles.pipeline import _font_path

    style = get_style(style_id)
    images: list[str] = []
    visual_video = ""
    if style.visual == "anime":
        images = media["images"]
    elif style.visual == "character":
        images = media["images"][:1]
    elif style.visual == "page":
        if style.scene in ("stack", "meme"):
            visual_video = media["page"]
        else:
            images = media["images"][:2]
    return {
        "scene": style.scene,
        "images": images,
        "loop_path": media["loop"] if style.scene in scene_mod.LOOP_SCENES else "",
        "hook": "Before: copying rows by hand. After: one click.",
        "title": "Menivor",
        "duration_s": 3.0,
        "font_path": _font_path(),
        "work_dir": work,
        "ffmpeg": FULL_FFMPEG,
        "visual_video": visual_video,
    }


def _frame(video: str, at_s: float, dest: str) -> str:
    _run([FULL_FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at_s}", "-i", video,
          "-frames:v", "1", dest])
    return dest


def _psnr(a: str, b: str) -> float:
    result = subprocess.run(
        [FULL_FFMPEG, "-hide_banner", "-i", a, "-i", b, "-lavfi", "psnr", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    match = re.search(r"average:(inf|[0-9.]+)", result.stderr)
    assert match, result.stderr[-400:]
    return float("inf") if match.group(1) == "inf" else float(match.group(1))


def _duration(video: str) -> float:
    result = subprocess.run([FULL_FFMPEG, "-hide_banner", "-i", video], capture_output=True, text=True)
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", result.stderr).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


@needs_full_ffmpeg
@pytest.mark.parametrize("style_id", NON_PRESENTER_STYLES)
def test_golden_frames_match_two_pass_with_one_encode(style_id, media, monkeypatch, tmp_path):
    from app.services.compose import encode_count
    from app.services.compose.compose_ffmpeg import compose_captions_over_screen
    from app.services.compose.single_pass import compose_scene_with_captions
    from app.services.styles import scene as scene_mod

    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", FULL_FFMPEG)
    kwargs = _scene_kwargs(style_id, media, str(tmp_path / "scene"))

    with encode_count.tally() as two_pass:
        screen = scene_mod.render_scene(out_path=str(tmp_path / "screen.mp4"), **kwargs)
        old = compose_captions_over_screen(screen, media["audio"], str(tmp_path / "old.mp4"), ass_path=media["ass"])
    with encode_count.tally() as one_pass:
        spec = scene_mod.prepare_scene(**kwargs)
        new = compose_scene_with_captions(spec, media["audio"], str(tmp_path / "new.mp4"), ass_path=media["ass"])

    assert encode_count.total(two_pass) == 2
    assert one_pass == {"compose": 1}
    assert abs(_duration(new) - _duration(old)) < 0.15
    for at in (0.5, 2.0):
        score = _psnr(_frame(old, at, str(tmp_path / f"old-{at}.png")), _frame(new, at, str(tmp_path / f"new-{at}.png")))
        assert score >= 30.0, f"{style_id} at {at}s: PSNR {score:.1f} dB"


class _FakeR2:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    def upload_file(self, local_path: str, key: str, content_type: str) -> str:
        self.uploads.append(key)
        return f"https://cdn.example/{key}"


@needs_full_ffmpeg
def test_stage_compose_logs_one_full_encode_for_a_faceless_style(media, monkeypatch, tmp_path):
    from app.services import reelforge
    from app.services.styles import scene as scene_mod
    from app.telemetry import events as telemetry_events

    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", FULL_FFMPEG)
    monkeypatch.delenv("COMPOSE_SINGLE_PASS", raising=False)
    kwargs = _scene_kwargs("gameplay_split", media, str(tmp_path / "scene"))
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    monkeypatch.setattr(reelforge, "_plan_style_scene", lambda *a: scene_mod.prepare_scene(**kwargs))
    monkeypatch.setattr(reelforge, "_download_from_r2", lambda key, dest, *a, **k: shutil.copy(media["audio"], dest) and dest)
    fake = _FakeR2()
    monkeypatch.setattr(reelforge, "_r2", lambda: fake)
    monkeypatch.setattr(reelforge, "_prepare_watermark", lambda *a: (None, "bottom_right", 0.85))
    monkeypatch.setattr(reelforge, "_generate_derivatives", lambda *a: {"poster_key": "", "preview_key": ""})
    monkeypatch.setattr(reelforge, "_materialize_style_scene", lambda *a: pytest.fail("two-pass scene rendered"))
    events: list[dict] = []
    monkeypatch.setattr(telemetry_events, "record_event", lambda job_id, stage, status, **kw: events.append(
        {"stage": stage, "status": status, **kw}))

    ctx = {"audio_key": "jobs/j1/audio.m4a", "ass_path": media["ass"], "audio_duration": 3.0}
    params = replace(_params(), background_id="block-runner")
    result = reelforge.stage_compose("j1", params, ctx)

    assert result["full_encodes"] == 1
    assert "jobs/j1/final.mp4" in fake.uploads
    encodes = [e for e in events if e["status"] == "encodes"]
    assert encodes and encodes[0]["payload"]["full_encodes"] == 1
    assert encodes[0]["payload"]["by_kind"] == {"compose": 1}


def test_stage_compose_two_pass_counts_scene_and_compose(monkeypatch, tmp_path):
    """With the flag off the old path runs and the JobEvent shows 2 encodes."""
    from app.services import reelforge
    from app.services.compose import compose_ffmpeg, encode_count
    from app.telemetry import events as telemetry_events

    monkeypatch.setenv("COMPOSE_SINGLE_PASS", "off")
    screen = tmp_path / "style-screen.mp4"
    screen.write_bytes(b"x")

    def fake_scene(*a):
        encode_count.count("scene")
        return str(screen)

    def fake_compose(screen_path, audio_path, out, **kw):
        encode_count.count("compose")
        open(out, "wb").write(b"mp4")
        return out

    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))
    monkeypatch.setattr(reelforge, "_materialize_style_scene", fake_scene)
    monkeypatch.setattr(compose_ffmpeg, "compose_captions_over_screen", fake_compose)
    monkeypatch.setattr(reelforge, "_download_from_r2", lambda key, dest, *a, **k: dest)
    monkeypatch.setattr(reelforge, "_r2", lambda: _FakeR2())
    monkeypatch.setattr(reelforge, "_prepare_watermark", lambda *a: (None, "bottom_right", 0.85))
    monkeypatch.setattr(reelforge, "_generate_derivatives", lambda *a: {"poster_key": "", "preview_key": ""})
    events: list[dict] = []
    monkeypatch.setattr(telemetry_events, "record_event", lambda job_id, stage, status, **kw: events.append(
        {"status": status, **kw}))

    result = reelforge.stage_compose("j2", _params(), {"audio_key": "k", "audio_duration": 3.0})
    assert result["full_encodes"] == 2
    assert [e["payload"]["by_kind"] for e in events if e["status"] == "encodes"] == [{"scene": 1, "compose": 1}]
