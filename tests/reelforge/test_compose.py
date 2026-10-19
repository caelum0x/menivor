"""Unit tests for app/services/compose/compose_ffmpeg.py (INTEGRATION_CONTRACT §2.6).

Scope: the PURE STRING BUILDERS and the boundary validation of
``compose_avatar_over_screen``. No real ffmpeg is invoked — ``subprocess.run`` is
monkeypatched so the tests are hermetic. One optional smoke test exercises the
real ffmpeg binary only if it is installed and is skipped otherwise.

FOCUS behaviours covered:
  * ``_LAYOUTS`` registers exactly {"pip", "hook_intro", "split"}.
  * An unknown layout raises ``ValueError`` naming the allowed set.
  * ``_escape_ass_filter_path`` escapes ``:`` and backslashes.
  * Every layout builder returns a filtergraph string terminating in ``[comp]``.
  * Layouts fill with scale + crop-to-fill (NOT fit + letterbox/pad).
"""

import os
import shutil
import subprocess

import pytest

from app.models.schema import VideoAspect
from app.services.compose import compose_ffmpeg as cf


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
CHROMA = {"color": "0x00FF00", "similarity": 0.18, "blend": 0.10}
PORTRAIT_W, PORTRAIT_H = VideoAspect.portrait.to_resolution()  # 1080 x 1920
DIAMETER = cf._PIP_DIAMETER
MARGIN = cf._PIP_MARGIN


def _build(name: str) -> str:
    """Invoke a layout builder with canonical portrait dimensions."""
    return cf._LAYOUTS[name](PORTRAIT_W, PORTRAIT_H, DIAMETER, MARGIN, CHROMA)


@pytest.fixture
def compose_inputs(tmp_path):
    """Three placeholder input files + an output path for compose calls."""
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


class _FakeCompleted:
    """Stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


# --------------------------------------------------------------------------- #
# _LAYOUTS registry
# --------------------------------------------------------------------------- #
def test_layouts_registry_exact_membership():
    assert set(cf._LAYOUTS) == {"pip", "hook_intro", "split"}


@pytest.mark.parametrize("name", ["pip", "hook_intro", "split"])
def test_layout_values_are_callable(name):
    assert callable(cf._LAYOUTS[name])


# --------------------------------------------------------------------------- #
# Layout builders -> [comp]
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["pip", "hook_intro", "split"])
def test_layout_builder_ends_in_comp(name):
    graph = _build(name)
    assert isinstance(graph, str) and graph
    assert graph.endswith("[comp]"), graph[-60:]
    # Exactly one final [comp] sink label should terminate the graph.
    assert graph.count("[comp]") == 1


@pytest.mark.parametrize("name", ["pip", "hook_intro", "split"])
def test_layout_builder_uses_scale_crop_to_fill_not_letterbox(name):
    graph = _build(name)
    # Fill semantics: scale with force_original_aspect_ratio=increase + crop.
    assert "force_original_aspect_ratio=increase" in graph
    assert "crop=" in graph
    # crop-to-fill must NOT letterbox: no decrease-scale + pad (fit) pipeline.
    assert "force_original_aspect_ratio=decrease" not in graph
    assert "pad=" not in graph


def test_layout_pip_screen_filled_and_avatar_circular():
    graph = _build("pip")
    # Screen (input 0) scaled+cropped to full portrait frame.
    assert f"[0:v]scale={PORTRAIT_W}:{PORTRAIT_H}:force_original_aspect_ratio=increase" in graph
    assert f"crop={PORTRAIT_W}:{PORTRAIT_H}" in graph
    # Circular avatar mask via geq alpha keeps a badge, then overlaid.
    assert "geq=" in graph
    assert "[1:v]" in graph
    # Badge sits bottom-right within margin.
    x = max(0, PORTRAIT_W - DIAMETER - MARGIN)
    y = max(0, PORTRAIT_H - DIAMETER - MARGIN)
    assert f"overlay=x={x}:y={y}" in graph


def test_layout_hook_intro_time_gated_overlays():
    graph = _build("hook_intro")
    # Full-frame avatar shown before the hook duration, PiP after.
    assert f"enable='lt(t,{cf._HOOK_DURATION:g})'" in graph
    assert f"enable='gte(t,{cf._HOOK_DURATION:g})'" in graph
    # A single chroma pass split into two copies.
    assert "split=2" in graph


def test_layout_split_vstacks_two_halves():
    graph = _build("split")
    half = PORTRAIT_H // 2
    assert f"crop={PORTRAIT_W}:{half}" in graph
    assert "vstack=inputs=2[comp]" in graph


# --------------------------------------------------------------------------- #
# chroma filter fragment
# --------------------------------------------------------------------------- #
def test_chroma_filter_uses_spec_values():
    node = cf._chroma_filter({"color": "0x00FF00", "similarity": 0.2, "blend": 0.1})
    assert node.startswith("chromakey=0x00FF00:")
    assert "0.2" in node
    assert "0.1" in node


def test_chroma_filter_defaults():
    node = cf._chroma_filter({})
    assert node.startswith("chromakey=0x00FF00:")


# --------------------------------------------------------------------------- #
# _escape_ass_filter_path
# --------------------------------------------------------------------------- #
def test_escape_ass_path_escapes_colon():
    # A colon inside the filename must be backslash-escaped for the ass= arg.
    escaped = cf._escape_ass_filter_path("/tmp/my:caption.ass")
    assert "\\:" in escaped
    # No bare (unescaped) colon should survive.
    assert ":" not in escaped.replace("\\:", "")


def test_escape_ass_path_converts_backslashes_to_forward_slashes():
    escaped = cf._escape_ass_filter_path("/tmp/dir\\sub\\file.ass")
    assert "\\" not in escaped.replace("\\:", "")  # no lone backslashes remain
    assert "/tmp/dir/sub/file.ass" in escaped


def test_escape_ass_path_is_absolute():
    escaped = cf._escape_ass_filter_path("relative.ass")
    # abspath prepends cwd -> result begins from filesystem root.
    assert escaped.startswith("/")


def test_escape_ass_path_escapes_single_quote():
    escaped = cf._escape_ass_filter_path("/tmp/it's.ass")
    assert "\\'" in escaped


@pytest.mark.parametrize("meta", ["[", "]", ";", ","])
def test_escape_ass_path_escapes_filtergraph_metacharacters(meta):
    # Filtergraph structural delimiters must be backslash-escaped so a path
    # containing them cannot corrupt or inject into the filtergraph.
    escaped = cf._escape_ass_filter_path(f"/tmp/a{meta}b.ass")
    assert "\\" + meta in escaped
    # No bare (unescaped) metacharacter should survive.
    assert meta not in escaped.replace("\\" + meta, "")


def test_escape_ass_path_escapes_all_metacharacters_together():
    escaped = cf._escape_ass_filter_path("/tmp/a[b];c,d:e'f.ass")
    for meta in ("[", "]", ";", ",", ":", "'"):
        assert "\\" + meta in escaped
        assert meta not in escaped.replace("\\" + meta, "")


def test_escape_ass_path_windows_drive_has_no_double_escape():
    # Guard against a double-escape regression on Windows-style inputs: the
    # backslashes are normalised to "/" before any escaping, so the only
    # backslash produced is the single escape prefix on the drive colon.
    escaped = cf._escape_ass_filter_path("C:\\videos\\out.ass")
    # Drive colon is escaped exactly once (no "\\\\:").
    assert "C\\:/videos/out.ass" in escaped
    assert "\\\\" not in escaped


# --------------------------------------------------------------------------- #
# _build_final_node
# --------------------------------------------------------------------------- #
def test_build_final_node_passthrough_when_no_captions():
    assert cf._build_final_node(None) == ";[comp]null[final]"


def test_build_final_node_burns_ass_when_provided(tmp_path):
    ass = tmp_path / "c.ass"
    ass.write_text("dummy", encoding="utf-8")
    node = cf._build_final_node(str(ass))
    assert node.startswith(";[comp]ass=")
    assert node.endswith("[final]")
    assert "fontsdir=" in node


# --------------------------------------------------------------------------- #
# compose_avatar_over_screen — boundary validation
# --------------------------------------------------------------------------- #
def test_invalid_layout_raises_valueerror_listing_allowed(compose_inputs):
    with pytest.raises(ValueError) as exc:
        cf.compose_avatar_over_screen(layout="bogus", **compose_inputs)
    msg = str(exc.value)
    assert "bogus" in msg
    # The message must enumerate the full allowed set.
    for allowed in ("pip", "hook_intro", "split"):
        assert allowed in msg


def test_missing_input_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        cf.compose_avatar_over_screen(
            screen_path=str(tmp_path / "nope.mp4"),
            avatar_path=str(tmp_path / "nope2.mp4"),
            audio_path=str(tmp_path / "nope3.mp3"),
            output_file=str(tmp_path / "out.mp4"),
            layout="pip",
        )


def test_missing_ass_input_raises_filenotfound(compose_inputs, tmp_path, monkeypatch):
    monkeypatch.setattr(
        cf.subprocess, "run", lambda *a, **k: _FakeCompleted(0)
    )
    with pytest.raises(FileNotFoundError):
        cf.compose_avatar_over_screen(
            ass_path=str(tmp_path / "missing.ass"), layout="pip", **compose_inputs
        )


# --------------------------------------------------------------------------- #
# compose_avatar_over_screen — command assembly (subprocess.run monkeypatched)
# --------------------------------------------------------------------------- #
def test_compose_builds_expected_command(compose_inputs, monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output=False, text=False, check=False):
        captured["cmd"] = cmd
        return _FakeCompleted(0)

    monkeypatch.setattr(cf.subprocess, "run", fake_run)
    monkeypatch.setattr(cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264)

    out = cf.compose_avatar_over_screen(layout="pip", **compose_inputs)
    assert out == compose_inputs["output_file"]

    cmd = captured["cmd"]
    # Interchange-friendly encode flags per contract.
    assert "-filter_complex" in cmd
    fg = cmd[cmd.index("-filter_complex") + 1]
    assert fg.endswith("[final]")
    assert ";[comp]null[final]" in fg  # no captions -> passthrough
    for flag in ("-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest"):
        assert flag in cmd
    # Video codec is the (patched) libx264.
    assert cmd[cmd.index("-c:v") + 1] == cf._LIBX264
    # Final video map + audio-from-third-input map.
    assert "[final]" in cmd
    assert "2:a" in cmd
    # FFmpeg binary is resolved via utils, never hardcoded literally at index 0.
    assert cmd[0] == cf.utils.get_ffmpeg_binary()


def test_compose_with_captions_appends_ass_node(compose_inputs, tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cf.subprocess, "run",
        lambda cmd, **k: (captured.__setitem__("cmd", cmd), _FakeCompleted(0))[1],
    )
    monkeypatch.setattr(cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264)
    # This test exercises the ass-node string path, so assert libass is available
    # (the real preflight is covered separately in test_compose_integration.py).
    monkeypatch.setattr(cf, "ffmpeg_has_filter", lambda name, ffmpeg=None: True)

    ass = tmp_path / "cap.ass"
    ass.write_text("x", encoding="utf-8")
    cf.compose_avatar_over_screen(ass_path=str(ass), layout="split", **compose_inputs)

    fg = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert ";[comp]ass=" in fg
    assert fg.endswith("[final]")


def test_compose_raises_runtimeerror_on_nonzero_exit(compose_inputs, monkeypatch):
    monkeypatch.setattr(
        cf.subprocess, "run",
        lambda *a, **k: _FakeCompleted(1, stderr="boom: bad filter"),
    )
    monkeypatch.setattr(cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264)

    with pytest.raises(RuntimeError) as exc:
        cf.compose_avatar_over_screen(layout="pip", **compose_inputs)
    assert "boom: bad filter" in str(exc.value)


def test_compose_falls_back_to_libx264_on_hw_codec_failure(compose_inputs, monkeypatch):
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        codec = cmd[cmd.index("-c:v") + 1]
        if codec != cf._LIBX264:
            return _FakeCompleted(1, stderr="hw encoder unavailable")
        return _FakeCompleted(0)

    disabled = {}
    monkeypatch.setattr(cf.subprocess, "run", fake_run)
    monkeypatch.setattr(
        cf.video_service, "_get_effective_video_codec", lambda: "h264_videotoolbox"
    )
    monkeypatch.setattr(
        cf.video_service,
        "_disable_runtime_video_codec",
        lambda codec, reason: disabled.update(codec=codec, reason=reason),
    )

    out = cf.compose_avatar_over_screen(layout="pip", **compose_inputs)
    assert out == compose_inputs["output_file"]
    # First attempt hw codec, retry with libx264.
    assert calls[0][calls[0].index("-c:v") + 1] == "h264_videotoolbox"
    assert calls[1][calls[1].index("-c:v") + 1] == cf._LIBX264
    # The failing codec is disabled for the rest of the process.
    assert disabled["codec"] == "h264_videotoolbox"


def test_compose_no_fallback_when_already_libx264(compose_inputs, monkeypatch):
    calls = []
    monkeypatch.setattr(
        cf.subprocess, "run",
        lambda cmd, **k: (calls.append(cmd), _FakeCompleted(1, stderr="x264 broke"))[1],
    )
    monkeypatch.setattr(cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264)

    with pytest.raises(RuntimeError):
        cf.compose_avatar_over_screen(layout="pip", **compose_inputs)
    # No retry — libx264 failure is terminal.
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Brand-watermark string builders
# --------------------------------------------------------------------------- #
def test_watermark_positions_registry_exact_membership():
    assert cf._WATERMARK_POSITIONS == {
        "top_left",
        "top_right",
        "bottom_left",
        "bottom_right",
        "center",
    }


@pytest.mark.parametrize(
    "position,expected",
    [
        ("top_left", ("40", "40")),
        ("top_right", ("W-w-40", "40")),
        ("bottom_left", ("40", "H-h-40")),
        ("bottom_right", ("W-w-40", "H-h-40")),
        ("center", ("(W-w)/2", "(H-h)/2")),
    ],
)
def test_watermark_overlay_xy_positions(position, expected):
    assert cf._watermark_overlay_xy(position, 40) == expected


def test_watermark_overlay_xy_invalid_position_raises():
    with pytest.raises(ValueError) as exc:
        cf._watermark_overlay_xy("middle_left", 40)
    msg = str(exc.value)
    assert "middle_left" in msg
    for allowed in cf._WATERMARK_POSITIONS:
        assert allowed in msg


def test_watermark_overlay_xy_negative_margin_clamped_to_zero():
    assert cf._watermark_overlay_xy("top_left", -10) == ("0", "0")


@pytest.mark.parametrize(
    "raw,expected",
    [(-1.0, 0.0), (0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (2.5, 1.0)],
)
def test_clamp_opacity(raw, expected):
    assert cf._clamp_opacity(raw) == expected


def test_clamp_opacity_bad_type_falls_back_to_default():
    assert cf._clamp_opacity("nope") == cf._WATERMARK_OPACITY


def test_watermark_logo_width_is_scale_times_reference():
    # 0.16 * 1080 == 172.8 -> rounds to 173.
    assert cf._watermark_logo_width(0.16) == 173
    # Never smaller than a single pixel.
    assert cf._watermark_logo_width(0.0) == 1


def test_watermark_logo_node_scales_rgba_and_fades_alpha():
    node = cf._watermark_logo_node("3:v", "wm_logo", 173, 0.85)
    assert node.startswith("[3:v]scale=173:-1,")
    assert "format=rgba" in node
    assert "colorchannelmixer=aa=0.85" in node
    assert node.endswith("[wm_logo]")


def test_build_watermark_node_structure_bottom_right():
    frag = cf._build_watermark_node(
        "final", "3:v", "wm", position="bottom_right", scale=0.16,
        opacity=0.85, margin=40,
    )
    # Leading ';' lets it append directly after the [final] node.
    assert frag.startswith(";[3:v]scale=173:-1,")
    # Two sub-nodes: the logo prep and the overlay onto [final].
    assert ";[final][wm_logo]overlay=x=W-w-40:y=H-h-40:format=auto[wm]" in frag
    assert frag.endswith("[wm]")


def test_build_watermark_node_invalid_position_raises():
    with pytest.raises(ValueError):
        cf._build_watermark_node(
            "final", "3:v", "wm", position="bogus_corner",
        )


# --------------------------------------------------------------------------- #
# compose_avatar_over_screen — watermark wiring
# --------------------------------------------------------------------------- #
def _make_png(path) -> str:
    """A 1x1 transparent PNG placeholder (bytes only; ffmpeg is monkeypatched)."""
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c62000100000500010d0a2db40000000049454e44ae"
        "426082"
    )
    path.write_bytes(png)
    return str(path)


def test_compose_without_watermark_command_unchanged(compose_inputs, monkeypatch):
    """When watermark_path is None the command/graph is byte-for-byte unchanged."""
    captured = {}
    monkeypatch.setattr(
        cf.subprocess, "run",
        lambda cmd, **k: (captured.__setitem__("cmd", cmd), _FakeCompleted(0))[1],
    )
    monkeypatch.setattr(cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264)

    cf.compose_avatar_over_screen(layout="pip", watermark_path=None, **compose_inputs)
    cmd = captured["cmd"]
    fg = cmd[cmd.index("-filter_complex") + 1]
    # No watermark => graph still ends at [final], video maps [final], only 3 inputs.
    assert fg.endswith("[final]")
    assert "[wm]" not in fg
    assert "overlay=x=W-w" not in fg
    assert cmd[cmd.index("-map") + 1] == "[final]"
    assert cmd.count("-i") == 3


def test_compose_with_watermark_appends_overlay_and_input(
    compose_inputs, tmp_path, monkeypatch
):
    captured = {}
    monkeypatch.setattr(
        cf.subprocess, "run",
        lambda cmd, **k: (captured.__setitem__("cmd", cmd), _FakeCompleted(0))[1],
    )
    monkeypatch.setattr(cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264)

    logo = _make_png(tmp_path / "logo.png")
    cf.compose_avatar_over_screen(
        layout="pip", watermark_path=logo, watermark_position="top_right",
        watermark_opacity=0.5, watermark_scale=0.2, watermark_margin=24,
        **compose_inputs,
    )
    cmd = captured["cmd"]
    # The logo is appended as the LAST (4th) input, i.e. pad index 3.
    assert cmd.count("-i") == 4
    assert cmd[-1] == compose_inputs["output_file"]
    assert logo in cmd
    fg = cmd[cmd.index("-filter_complex") + 1]
    # Overlay sits AFTER the caption/passthrough node (references [final]).
    assert ";[final][wm_logo]overlay=x=W-w-24:y=24:format=auto[wm]" in fg
    assert "[3:v]scale=216:-1," in fg  # 0.2 * 1080
    assert "colorchannelmixer=aa=0.5" in fg
    assert fg.endswith("[wm]")
    # Video is mapped from the watermarked label.
    assert cmd[cmd.index("-map") + 1] == "[wm]"


def test_compose_watermark_input_index_shifts_after_music(
    compose_inputs, tmp_path, monkeypatch
):
    captured = {}
    monkeypatch.setattr(
        cf.subprocess, "run",
        lambda cmd, **k: (captured.__setitem__("cmd", cmd), _FakeCompleted(0))[1],
    )
    monkeypatch.setattr(cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264)
    monkeypatch.setattr(cf, "ffmpeg_has_filter", lambda name, ffmpeg=None: True)

    music = tmp_path / "music.mp3"
    music.write_bytes(b"\x00")
    logo = _make_png(tmp_path / "logo.png")

    cf.compose_avatar_over_screen(
        layout="pip", music_path=str(music), watermark_path=logo,
        watermark_position="bottom_left", **compose_inputs,
    )
    fg = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    # With music at input 3, the logo becomes input 4.
    assert "[4:v]scale=" in fg
    assert ";[final][wm_logo]overlay=x=40:y=H-h-40:format=auto[wm]" in fg


def test_compose_invalid_watermark_position_raises_valueerror(
    compose_inputs, tmp_path
):
    logo = _make_png(tmp_path / "logo.png")
    with pytest.raises(ValueError) as exc:
        cf.compose_avatar_over_screen(
            layout="pip", watermark_path=logo, watermark_position="nope",
            **compose_inputs,
        )
    assert "nope" in str(exc.value)


def test_compose_missing_watermark_file_raises_filenotfound(compose_inputs, tmp_path):
    with pytest.raises(FileNotFoundError):
        cf.compose_avatar_over_screen(
            layout="pip", watermark_path=str(tmp_path / "missing.png"),
            **compose_inputs,
        )


# --------------------------------------------------------------------------- #
# Optional real-ffmpeg smoke test (skipped when ffmpeg is unavailable)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_generated_filtergraph_parses_in_real_ffmpeg():
    """Feed a layout's filtergraph to real ffmpeg with lavfi test sources and
    assert ffmpeg accepts the graph (exit 0). Validates the string builders
    produce a syntactically valid libavfilter graph."""
    ffmpeg = shutil.which("ffmpeg")
    graph = _build("pip") + cf._build_final_node(None)  # ends in [final]
    cmd = [
        ffmpeg, "-hide_banner", "-y",
        "-f", "lavfi", "-i", f"testsrc=size={PORTRAIT_W}x{PORTRAIT_H}:rate=30:duration=0.2",
        "-f", "lavfi", "-i", "testsrc=size=640x640:rate=30:duration=0.2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
        "-filter_complex", graph,
        "-map", "[final]", "-map", "2:a",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        "-t", "0.2", "-f", "null", os.devnull,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
