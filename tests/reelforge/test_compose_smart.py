"""Unit + integration tests for the Stage-5 "smart screen-recording handling"
and audio-finishing additions to ``compose_ffmpeg`` (CTO §5).

Scope:
  * PURE STRING/NUMERIC BUILDERS for the new opt-in features
    (``_speed_factor``, ``_setpts_node``, ``_blur_pad_node``, ``_needs_blur_pad``,
    ``_build_screen_prep``, ``_build_audio_graph``, ``_clamp_loudnorm_i``,
    freezedetect/ffprobe parsers, ``_build_command`` argv shaping).
  * The wiring in ``compose_avatar_over_screen`` that engages them (subprocess
    is monkeypatched — no real ffmpeg for the unit layer).
  * An OPTIONAL real-ffmpeg integration layer (auto-skipped when the binary or a
    required filter is missing) that renders blur-pad, speed-ramp and
    music-ducked outputs and probes them with ffprobe.

Legacy defaults must stay inert: with none of the new kwargs the existing
behaviour (and the existing ``test_compose.py`` assertions) is unchanged — that
guarantee is exercised here too.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.models.schema import VideoAspect
from app.services.compose import compose_ffmpeg as cf

PORTRAIT_W, PORTRAIT_H = VideoAspect.portrait.to_resolution()  # 1080 x 1920


class _FakeCompleted:
    """Stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0, stderr: str = "", stdout: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


@pytest.fixture
def compose_inputs(tmp_path):
    screen = tmp_path / "screen.mp4"
    avatar = tmp_path / "avatar.mp4"
    audio = tmp_path / "audio.mp3"
    for p in (screen, avatar, audio):
        p.write_bytes(b"\x00")
    out = tmp_path / "out.mp4"
    return {
        "screen_path": str(screen),
        "avatar_path": str(avatar),
        "audio_path": str(audio),
        "output_file": str(out),
    }


# --------------------------------------------------------------------------- #
# _speed_factor
# --------------------------------------------------------------------------- #
def test_speed_factor_fits_and_caps_at_max():
    # 10s recording into 5s target would need 2x, but is capped at max_speed.
    assert cf._speed_factor(10.0, 5.0, max_speed=1.6) == pytest.approx(1.6)


def test_speed_factor_uses_exact_ratio_below_cap():
    assert cf._speed_factor(6.0, 5.0, max_speed=1.6) == pytest.approx(1.2)


@pytest.mark.parametrize(
    "screen,target",
    [(5.0, 5.0), (4.0, 5.0), (0.0, 5.0), (5.0, 0.0)],
)
def test_speed_factor_identity_when_fits_or_degenerate(screen, target):
    assert cf._speed_factor(screen, target) == 1.0


def test_speed_factor_never_below_one_even_with_bad_cap():
    assert cf._speed_factor(10.0, 5.0, max_speed=0.5) == 1.0


# --------------------------------------------------------------------------- #
# _setpts_node
# --------------------------------------------------------------------------- #
def test_setpts_node_shape():
    node = cf._setpts_node("0:v", "scr_sp", 1.6)
    assert node == "[0:v]setpts=PTS/1.6[scr_sp]"


# --------------------------------------------------------------------------- #
# _blur_pad_node
# --------------------------------------------------------------------------- #
def test_blur_pad_node_has_blurred_cover_bg_and_fit_fg():
    node = cf._blur_pad_node("0:v", "scr_bp", PORTRAIT_W, PORTRAIT_H)
    assert node.startswith("[0:v]split=2")
    # Background: scale-to-cover + crop + boxblur.
    assert "force_original_aspect_ratio=increase" in node
    assert f"boxblur={cf._BLUR_PAD_STRENGTH}" in node
    # Foreground: scale-to-fit (letterbox) centred.
    assert "force_original_aspect_ratio=decrease" in node
    assert "overlay=(W-w)/2:(H-h)/2" in node
    assert node.endswith("[scr_bp]")


# --------------------------------------------------------------------------- #
# _crop_loss_fraction / _needs_blur_pad
# --------------------------------------------------------------------------- #
def test_crop_loss_zero_for_matching_aspect():
    assert cf._crop_loss_fraction(1080, 1920, 1080, 1920) == pytest.approx(0.0)


def test_landscape_into_portrait_triggers_blur_pad():
    # 16:9 screen recording into 9:16 portrait crops away most of the width.
    assert cf._needs_blur_pad(1920, 1080, PORTRAIT_W, PORTRAIT_H) is True


def test_near_portrait_does_not_trigger_blur_pad():
    # A slightly-off portrait source crops cleanly enough — no blur-pad.
    assert cf._needs_blur_pad(1000, 1900, PORTRAIT_W, PORTRAIT_H) is False


@pytest.mark.parametrize("w,h", [(0, 100), (100, 0), (0, 0)])
def test_crop_loss_degenerate_dims_are_zero(w, h):
    assert cf._crop_loss_fraction(w, h, PORTRAIT_W, PORTRAIT_H) == 0.0


# --------------------------------------------------------------------------- #
# _build_screen_prep
# --------------------------------------------------------------------------- #
def test_screen_prep_noop_returns_raw_input():
    graph, label = cf._build_screen_prep(1.0, False, PORTRAIT_W, PORTRAIT_H)
    assert graph == ""
    assert label == "0:v"


def test_screen_prep_speed_only():
    graph, label = cf._build_screen_prep(1.5, False, PORTRAIT_W, PORTRAIT_H)
    assert graph == "[0:v]setpts=PTS/1.5[scr_sp]"
    assert label == "scr_sp"


def test_screen_prep_blur_only_consumes_raw_input():
    graph, label = cf._build_screen_prep(1.0, True, PORTRAIT_W, PORTRAIT_H)
    assert graph.startswith("[0:v]split=2")
    assert label == "scr_bp"


def test_screen_prep_speed_then_blur_chains_labels():
    graph, label = cf._build_screen_prep(1.4, True, PORTRAIT_W, PORTRAIT_H)
    # setpts runs first, its output feeds the blur-pad.
    assert "[0:v]setpts=PTS/1.4[scr_sp]" in graph
    assert "[scr_sp]split=2" in graph
    assert label == "scr_bp"
    # The two fragments are joined into one graph.
    assert graph.count(";[scr_sp]split=2") == 1


# --------------------------------------------------------------------------- #
# _clamp_loudnorm_i / _build_audio_graph
# --------------------------------------------------------------------------- #
def test_loudnorm_clamps_minus3_up_to_valid_ceiling():
    # ffmpeg loudnorm only accepts I in [-70, -5]; -3 must clamp to -5.
    assert cf._clamp_loudnorm_i(-3.0) == cf._LOUDNORM_I_CEILING == -5.0


@pytest.mark.parametrize("val,expected", [(-100.0, -70.0), (-16.0, -16.0), (0.0, -5.0)])
def test_loudnorm_clamp_range(val, expected):
    assert cf._clamp_loudnorm_i(val) == expected


def test_audio_graph_ducks_music_and_loudnorms():
    graph, out = cf._build_audio_graph()
    assert out == "aout"
    # Voiceover split; music is the sidechaincompress main, voiceover the trigger.
    assert "[2:a]asplit=2[vo][vo_key]" in graph
    assert "[3:a][vo_key]sidechaincompress=" in graph
    # Ducked music mixed under voiceover, then loudness-normalised.
    assert "[vo][duck]amix=inputs=2:duration=first" in graph
    # Social default: -14 LUFS integrated, -1 dBTP true peak.
    assert "loudnorm=I=-14:TP=-1:" in graph
    assert graph.endswith("[aout]")


def test_loudnorm_default_is_social_target(monkeypatch):
    monkeypatch.delenv("MENIVOR_LOUDNORM_I", raising=False)
    monkeypatch.delenv("MENIVOR_LOUDNORM_TP", raising=False)
    assert cf._LOUDNORM_TARGET_I == -14.0
    assert cf._LOUDNORM_TP == -1.0
    assert cf._loudnorm_targets() == (-14.0, -1.0)


def test_loudnorm_env_override_and_clamp(monkeypatch):
    monkeypatch.setenv("MENIVOR_LOUDNORM_I", "-16")
    monkeypatch.setenv("MENIVOR_LOUDNORM_TP", "-2")
    graph, _ = cf._build_audio_graph()
    assert "loudnorm=I=-16:TP=-2:" in graph
    # Out-of-range values clamp into ffmpeg's accepted ranges.
    monkeypatch.setenv("MENIVOR_LOUDNORM_I", "-3")
    monkeypatch.setenv("MENIVOR_LOUDNORM_TP", "3")
    assert cf._loudnorm_targets() == (-5.0, 0.0)
    # Garbage falls back to the default.
    monkeypatch.setenv("MENIVOR_LOUDNORM_I", "loud")
    monkeypatch.setenv("MENIVOR_LOUDNORM_TP", "")
    assert cf._loudnorm_targets() == (-14.0, -1.0)


def test_loudnorm_explicit_args_win_over_env(monkeypatch):
    monkeypatch.setenv("MENIVOR_LOUDNORM_I", "-16")
    graph, _ = cf._build_audio_graph(target_i=-23.0, true_peak=-2.0)
    assert "loudnorm=I=-23:TP=-2:" in graph


# --------------------------------------------------------------------------- #
# ffprobe / freezedetect parsers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "rate,expected",
    [("30/1", 30.0), ("30000/1001", pytest.approx(29.97, abs=0.01)), ("24", 24.0),
     ("0/0", 0.0), ("", 0.0), (None, 0.0)],
)
def test_parse_fps(rate, expected):
    assert cf._parse_fps(rate) == expected


def test_parse_leading_freeze_end_trims_head_freeze():
    stderr = (
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_start: 0\n"
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_duration: 1.5\n"
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_end: 1.5\n"
    )
    assert cf._parse_leading_freeze_end(stderr, screen_duration=30.0) == pytest.approx(1.5)


def test_parse_leading_freeze_end_ignores_midclip_freeze():
    stderr = (
        "lavfi.freezedetect.freeze_start: 12.0\n"
        "lavfi.freezedetect.freeze_end: 13.0\n"
    )
    assert cf._parse_leading_freeze_end(stderr, screen_duration=30.0) == 0.0


def test_parse_leading_freeze_end_clamps_to_half_duration():
    stderr = (
        "lavfi.freezedetect.freeze_start: 0\n"
        "lavfi.freezedetect.freeze_end: 100.0\n"
    )
    # Never trim more than half the recording.
    assert cf._parse_leading_freeze_end(stderr, screen_duration=10.0) == pytest.approx(5.0)


def test_parse_leading_freeze_end_no_metadata():
    assert cf._parse_leading_freeze_end("no freeze here", screen_duration=10.0) == 0.0


def test_probe_video_returns_none_for_missing_file(tmp_path):
    assert cf._probe_video(str(tmp_path / "nope.mp4")) is None


# --------------------------------------------------------------------------- #
# _build_command — new optional knobs
# --------------------------------------------------------------------------- #
def test_build_command_legacy_defaults_have_no_ss_no_music():
    cmd = cf._build_command(
        "ffmpeg", "s.mp4", "a.mp4", "v.mp3", "o.mp4",
        "graph", cf._LIBX264, 2, 30,
    )
    assert "-ss" not in cmd
    # Exactly three inputs (screen/avatar/audio).
    assert cmd.count("-i") == 3
    assert cmd[cmd.index("-map") + 1] == "[final]"
    # Second map is the raw narration.
    assert "2:a" in cmd


def test_build_command_adds_input_seek_and_music_input():
    cmd = cf._build_command(
        "ffmpeg", "s.mp4", "a.mp4", "v.mp3", "o.mp4",
        "graph", cf._LIBX264, 2, 30,
        screen_ss=1.25, music_path="m.mp3", audio_map="[aout]",
    )
    # Input seek precedes the screen input.
    assert cmd[cmd.index("-ss") + 1] == "1.250"
    assert cmd.index("-ss") < cmd.index("-i")
    # Four inputs now, music last.
    assert cmd.count("-i") == 4
    assert "m.mp3" in cmd
    # Audio mapped from the ducked+normalised graph output.
    assert "[aout]" in cmd


# --------------------------------------------------------------------------- #
# layout builders accept a screen-source label override
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["pip", "hook_intro", "split"])
def test_layout_accepts_custom_screen_label(name):
    graph = cf._LAYOUTS[name](
        PORTRAIT_W, PORTRAIT_H, cf._PIP_DIAMETER, cf._PIP_MARGIN,
        {"color": "0x00FF00", "similarity": 0.18, "blend": 0.1},
        screen="scr_bp",
    )
    assert "[scr_bp]" in graph
    # The raw screen input is no longer referenced when overridden.
    assert "[0:v]" not in graph
    assert graph.endswith("[comp]")


# --------------------------------------------------------------------------- #
# compose_avatar_over_screen wiring (subprocess monkeypatched)
# --------------------------------------------------------------------------- #
def _patch_run_capture(monkeypatch):
    captured: dict = {}

    def fake_run(cmd, capture_output=False, text=False, check=False):
        captured["cmd"] = cmd
        return _FakeCompleted(0)

    monkeypatch.setattr(cf.subprocess, "run", fake_run)
    monkeypatch.setattr(cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264)
    return captured


def test_compose_legacy_call_has_no_smart_nodes(compose_inputs, monkeypatch):
    captured = _patch_run_capture(monkeypatch)
    cf.compose_avatar_over_screen(layout="pip", **compose_inputs)
    fg = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    # No smart nodes engaged by default.
    assert "setpts=" not in fg
    assert "boxblur=" not in fg
    assert "sidechaincompress" not in fg
    assert "-ss" not in captured["cmd"]


def test_compose_target_duration_engages_speed_ramp(compose_inputs, monkeypatch):
    captured = _patch_run_capture(monkeypatch)
    # A long, portrait-ish recording: no blur-pad, but must be sped up.
    monkeypatch.setattr(
        cf, "_probe_video",
        lambda path, ffprobe=None: cf.VideoInfo(1080, 1920, duration=12.0, fps=30.0),
    )
    monkeypatch.setattr(cf, "_detect_leading_freeze", lambda *a, **k: 0.0)

    cf.compose_avatar_over_screen(
        layout="pip", target_duration_s=6.0, **compose_inputs
    )
    fg = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    # 12s into 6s -> 2x, capped at 1.6.
    assert "setpts=PTS/1.6" in fg
    assert "[scr_sp]" in fg


def test_compose_landscape_source_engages_blur_pad(compose_inputs, monkeypatch):
    captured = _patch_run_capture(monkeypatch)
    monkeypatch.setattr(
        cf, "_probe_video",
        lambda path, ffprobe=None: cf.VideoInfo(1920, 1080, duration=4.0, fps=30.0),
    )
    monkeypatch.setattr(cf, "_detect_leading_freeze", lambda *a, **k: 0.0)

    cf.compose_avatar_over_screen(
        layout="pip", target_duration_s=6.0, **compose_inputs
    )
    fg = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "boxblur=" in fg
    assert "[scr_bp]" in fg


def test_compose_freeze_trim_adds_input_seek(compose_inputs, monkeypatch):
    captured = _patch_run_capture(monkeypatch)
    monkeypatch.setattr(
        cf, "_probe_video",
        lambda path, ffprobe=None: cf.VideoInfo(1080, 1920, duration=8.0, fps=30.0),
    )
    monkeypatch.setattr(cf, "_detect_leading_freeze", lambda *a, **k: 1.75)

    cf.compose_avatar_over_screen(
        layout="pip", target_duration_s=6.0, **compose_inputs
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("-ss") + 1] == "1.750"


def test_compose_blur_pad_forced_without_target(compose_inputs, monkeypatch):
    # blur_pad=True must apply even with no target_duration_s (no probe pass).
    called = {"probe": 0}
    captured = _patch_run_capture(monkeypatch)
    monkeypatch.setattr(
        cf, "_probe_video",
        lambda *a, **k: called.__setitem__("probe", called["probe"] + 1),
    )
    cf.compose_avatar_over_screen(layout="pip", blur_pad=True, **compose_inputs)
    fg = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "boxblur=" in fg
    # No probing without a target duration.
    assert called["probe"] == 0


def test_compose_with_music_wires_ducking_graph(compose_inputs, tmp_path, monkeypatch):
    captured = _patch_run_capture(monkeypatch)
    monkeypatch.setattr(cf, "ffmpeg_has_filter", lambda name, ffmpeg=None: True)
    music = tmp_path / "bg.mp3"
    music.write_bytes(b"\x00")

    cf.compose_avatar_over_screen(
        layout="pip", music_path=str(music), **compose_inputs
    )
    cmd = captured["cmd"]
    fg = cmd[cmd.index("-filter_complex") + 1]
    assert "sidechaincompress" in fg
    assert "loudnorm=I=-14:TP=-1:" in fg
    # Audio is mapped from the graph output, not the raw narration.
    assert "[aout]" in cmd
    assert cmd.count("-i") == 4  # screen/avatar/voice/music


def test_compose_music_missing_filter_fails_fast(compose_inputs, tmp_path, monkeypatch):
    _patch_run_capture(monkeypatch)
    monkeypatch.setattr(
        cf, "ffmpeg_has_filter",
        lambda name, ffmpeg=None: name != "sidechaincompress",
    )
    music = tmp_path / "bg.mp3"
    music.write_bytes(b"\x00")
    with pytest.raises(RuntimeError, match="sidechaincompress"):
        cf.compose_avatar_over_screen(
            layout="pip", music_path=str(music), **compose_inputs
        )


def test_compose_missing_music_file_raises(compose_inputs, tmp_path, monkeypatch):
    _patch_run_capture(monkeypatch)
    with pytest.raises(FileNotFoundError, match="music"):
        cf.compose_avatar_over_screen(
            layout="pip", music_path=str(tmp_path / "nope.mp3"), **compose_inputs
        )


# --------------------------------------------------------------------------- #
# Optional real-ffmpeg integration layer
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _have(*filters: str) -> bool:
    if not _FFMPEG or not _FFPROBE:
        return False
    return all(cf.ffmpeg_has_filter(f, _FFMPEG) for f in filters)


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout or "ffmpeg failed")


def _probe(path: str) -> dict:
    r = subprocess.run(
        [_FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture
def landscape_inputs(tmp_path):
    """A 16:9 (landscape) screen recording + green avatar + narration."""
    screen = str(tmp_path / "screen.mp4")
    avatar = str(tmp_path / "avatar.mp4")
    audio = str(tmp_path / "audio.m4a")
    _run([_FFMPEG, "-y", "-f", "lavfi",
          "-i", "testsrc2=size=1280x720:rate=30:duration=3",
          "-pix_fmt", "yuv420p", screen])
    _run([_FFMPEG, "-y", "-f", "lavfi",
          "-i", "color=c=0x00FF00:size=512x512:rate=30:duration=3",
          "-pix_fmt", "yuv420p", avatar])
    _run([_FFMPEG, "-y", "-f", "lavfi",
          "-i", "sine=frequency=440:duration=3", "-c:a", "aac", audio])
    return {"screen": screen, "avatar": avatar, "audio": audio}


@pytest.mark.integration
@pytest.mark.skipif(
    not _have("boxblur", "overlay", "scale", "crop"),
    reason="ffmpeg with blur-pad filters unavailable",
)
def test_real_blur_pad_renders_portrait(landscape_inputs, tmp_path):
    out = str(tmp_path / "blur.mp4")
    cf.compose_avatar_over_screen(
        landscape_inputs["screen"], landscape_inputs["avatar"],
        landscape_inputs["audio"], out,
        layout="pip", blur_pad=True,
    )
    v = [s for s in _probe(out)["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (1080, 1920)


@pytest.mark.integration
@pytest.mark.skipif(
    not _have("setpts", "scale", "crop"),
    reason="ffmpeg with setpts unavailable",
)
def test_real_speed_ramp_renders_and_fits(landscape_inputs, tmp_path):
    # 3s recording, 1.5s target -> capped 1.6x speed-ramp. blur-pad auto-on for
    # the landscape source; both smart nodes must co-exist in one valid graph.
    out = str(tmp_path / "fast.mp4")
    cf.compose_avatar_over_screen(
        landscape_inputs["screen"], landscape_inputs["avatar"],
        landscape_inputs["audio"], out,
        layout="pip", target_duration_s=1.5,
    )
    info = _probe(out)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in info["streams"])


@pytest.mark.integration
@pytest.mark.skipif(
    not _have("sidechaincompress", "loudnorm", "amix", "asplit"),
    reason="ffmpeg with ducking/loudnorm filters unavailable",
)
def test_real_music_ducking_muxes_normalised_audio(landscape_inputs, tmp_path):
    music = str(tmp_path / "music.m4a")
    _run([_FFMPEG, "-y", "-f", "lavfi",
          "-i", "sine=frequency=220:duration=5", "-c:a", "aac", music])
    out = str(tmp_path / "ducked.mp4")
    cf.compose_avatar_over_screen(
        landscape_inputs["screen"], landscape_inputs["avatar"],
        landscape_inputs["audio"], out,
        layout="pip", music_path=music,
    )
    info = _probe(out)
    astreams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert astreams, "ducked+normalised audio must be muxed in"
    assert astreams[0]["codec_name"] == "aac"


@pytest.mark.integration
@pytest.mark.skipif(
    not _have("freezedetect"),
    reason="ffmpeg without freezedetect",
)
def test_real_freezedetect_trims_leading_static(tmp_path):
    # 2s of a frozen title card, then 2s of motion. freezedetect must locate the
    # ~0s→2s leading freeze so we trim into the moving section.
    screen = str(tmp_path / "screen.mp4")
    frozen = str(tmp_path / "frozen.mp4")
    motion = str(tmp_path / "motion.mp4")
    _run([_FFMPEG, "-y", "-f", "lavfi",
          "-i", "color=c=blue:size=1080x1920:rate=30:duration=2",
          "-pix_fmt", "yuv420p", frozen])
    _run([_FFMPEG, "-y", "-f", "lavfi",
          "-i", "testsrc2=size=1080x1920:rate=30:duration=2",
          "-pix_fmt", "yuv420p", motion])
    concat = str(tmp_path / "concat.txt")
    with open(concat, "w", encoding="utf-8") as fh:
        fh.write(f"file '{frozen}'\nfile '{motion}'\n")
    _run([_FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", concat,
          "-c", "copy", screen])

    trim = cf._detect_leading_freeze(screen, screen_duration=4.0, ffmpeg=_FFMPEG)
    # Leading freeze is ~2s; must detect a positive trim within the first half.
    assert 1.0 <= trim <= 2.0
