"""Unit + real-ffmpeg tests for the b-roll cutaway concat (compose_ffmpeg).

Scope: the PURE STRING BUILDERS behind ``concat_with_broll`` and the boundary /
command-assembly behaviour of the public helper. ``subprocess.run`` is
monkeypatched so the unit tests are hermetic. One optional integration test runs
the ACTUAL FFmpeg binary end to end and is skipped when no media stack is
available.

Covered behaviours:
  * No-op when both intro and outro are ``None`` (returns main, no ffmpeg).
  * Missing main / b-roll inputs raise ``FileNotFoundError``; bad cap raises.
  * Each b-roll clip is cover-cropped + trimmed + given SILENT audio.
  * The concat filter uses ``v=1:a=1`` with the correct segment count/order.
  * Input pads are assigned main=0, intro/outro next, silence last.
  * libx264 runtime fallback mirrors ``compose_avatar_over_screen``.
  * Real ffmpeg concats synthetic lavfi clips into a 1080x1920 h264 MP4 whose
    duration ~= main + intro + outro.
"""

import json
import os
import shutil
import subprocess

import pytest

from app.models.schema import VideoAspect
from app.services.compose import compose_ffmpeg as cf

PORTRAIT_W, PORTRAIT_H = VideoAspect.portrait.to_resolution()  # 1080 x 1920


class _FakeCompleted:
    """Stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


@pytest.fixture
def broll_inputs(tmp_path):
    """A main reel + intro + outro placeholder + an output path."""
    main = tmp_path / "main.mp4"
    intro = tmp_path / "intro.mp4"
    outro = tmp_path / "outro.mp4"
    for p in (main, intro, outro):
        p.write_bytes(b"\x00")
    out = tmp_path / "out.mp4"
    return {
        "main_path": str(main),
        "intro_path": str(intro),
        "outro_path": str(outro),
        "output_file": str(out),
    }


# --------------------------------------------------------------------------- #
# Pure string builders — b-roll video / silent audio / main normalisation
# --------------------------------------------------------------------------- #
def test_broll_video_node_cover_crops_and_trims():
    node = cf._broll_video_node("1:v", "bv0", PORTRAIT_W, PORTRAIT_H, 30, 2.5)
    assert node.startswith(
        f"[1:v]scale={PORTRAIT_W}:{PORTRAIT_H}:force_original_aspect_ratio=increase,"
    )
    assert f"crop={PORTRAIT_W}:{PORTRAIT_H}" in node
    assert "setsar=1" in node
    assert "fps=30" in node
    assert "trim=duration=2.5" in node
    assert "setpts=PTS-STARTPTS" in node
    assert "format=yuv420p" in node
    assert node.endswith("[bv0]")
    # Cover-crop, never letterbox.
    assert "force_original_aspect_ratio=decrease" not in node
    assert "pad=" not in node


def test_broll_silent_audio_node_trims_and_formats():
    node = cf._broll_silent_audio_node("3:a", "sa0", 2.5)
    assert node.startswith("[3:a]atrim=duration=2.5,asetpts=PTS-STARTPTS,")
    assert f"aformat=sample_rates={cf._BROLL_SAMPLE_RATE}" in node
    assert "channel_layouts=stereo" in node
    assert node.endswith("[sa0]")


def test_main_video_node_normalises_for_concat():
    node = cf._main_video_node("0:v", "mv", PORTRAIT_W, PORTRAIT_H, 30)
    assert node.startswith(f"[0:v]scale={PORTRAIT_W}:{PORTRAIT_H}:")
    assert "setsar=1" in node
    assert "fps=30" in node
    assert "format=yuv420p" in node
    # The main reel is not trimmed — it keeps its full length.
    assert "trim=" not in node
    assert node.endswith("[mv]")


def test_main_audio_node_coerces_rate_and_layout():
    node = cf._main_audio_node("0:a", "ma")
    assert node.startswith("[0:a]aformat=sample_rates=")
    assert "channel_layouts=stereo" in node
    assert node.endswith("[ma]")


# --------------------------------------------------------------------------- #
# _build_concat_graph — structure, ordering, pad indices
# --------------------------------------------------------------------------- #
def test_build_concat_graph_requires_a_clip():
    with pytest.raises(ValueError):
        cf._build_concat_graph(
            has_intro=False, has_outro=False,
            width=PORTRAIT_W, height=PORTRAIT_H, fps=30, max_broll_s=2.5,
        )


def test_build_concat_graph_intro_only():
    res = cf._build_concat_graph(
        has_intro=True, has_outro=False,
        width=PORTRAIT_W, height=PORTRAIT_H, fps=30, max_broll_s=2.5,
    )
    g = res.graph
    assert res.video_map == "[cv]" and res.audio_map == "[ca]"
    # Two concat segments: intro then main.
    assert "concat=n=2:v=1:a=1[cv][ca]" in g
    # Intro b-roll is input 1; silence is input 2.
    assert "[1:v]scale=" in g
    assert "[2:a]atrim=duration=2.5" in g
    # Concat order: intro (bv0) before main (mv).
    assert "[bv0][sa0][mv][ma]concat=n=2" in g
    # A single clip needs no asplit.
    assert "asplit" not in g


def test_build_concat_graph_outro_only():
    res = cf._build_concat_graph(
        has_intro=False, has_outro=True,
        width=PORTRAIT_W, height=PORTRAIT_H, fps=30, max_broll_s=2.5,
    )
    g = res.graph
    assert "concat=n=2:v=1:a=1[cv][ca]" in g
    # Outro b-roll is input 1; silence input 2.
    assert "[1:v]scale=" in g
    assert "[2:a]atrim=duration=2.5" in g
    # Concat order: main (mv) before outro (bv0).
    assert "[mv][ma][bv0][sa0]concat=n=2" in g
    assert "asplit" not in g


def test_build_concat_graph_intro_and_outro():
    res = cf._build_concat_graph(
        has_intro=True, has_outro=True,
        width=PORTRAIT_W, height=PORTRAIT_H, fps=30, max_broll_s=2.5,
    )
    g = res.graph
    # Three segments: intro, main, outro.
    assert "concat=n=3:v=1:a=1[cv][ca]" in g
    # Inputs: main=0, intro=1, outro=2, silence=3.
    assert "[1:v]scale=" in g  # intro
    assert "[2:v]scale=" in g  # outro
    # The single silence source (input 3) is split for the two segments.
    assert "[3:a]asplit=2[sa_in0][sa_in1]" in g
    assert "[sa_in0]atrim=duration=2.5" in g
    assert "[sa_in1]atrim=duration=2.5" in g
    # Order: intro (bv0), main (mv), outro (bv1).
    assert "[bv0][sa0][mv][ma][bv1][sa1]concat=n=3" in g


# --------------------------------------------------------------------------- #
# concat_with_broll — no-op / boundary validation
# --------------------------------------------------------------------------- #
def test_concat_no_op_when_no_broll_returns_main(broll_inputs, monkeypatch):
    called = {"run": False}

    def fake_run(*a, **k):
        called["run"] = True
        return _FakeCompleted(0)

    monkeypatch.setattr(cf.subprocess, "run", fake_run)
    out = cf.concat_with_broll(
        broll_inputs["main_path"], broll_inputs["output_file"],
        intro_path=None, outro_path=None,
    )
    # No-op: main returned unchanged and ffmpeg never invoked.
    assert out == broll_inputs["main_path"]
    assert called["run"] is False


def test_concat_missing_main_raises_filenotfound(tmp_path, broll_inputs):
    with pytest.raises(FileNotFoundError):
        cf.concat_with_broll(
            str(tmp_path / "nope.mp4"), broll_inputs["output_file"],
            intro_path=broll_inputs["intro_path"],
        )


def test_concat_missing_intro_raises_filenotfound(tmp_path, broll_inputs):
    with pytest.raises(FileNotFoundError):
        cf.concat_with_broll(
            broll_inputs["main_path"], broll_inputs["output_file"],
            intro_path=str(tmp_path / "missing_intro.mp4"),
        )


def test_concat_missing_outro_raises_filenotfound(tmp_path, broll_inputs):
    with pytest.raises(FileNotFoundError):
        cf.concat_with_broll(
            broll_inputs["main_path"], broll_inputs["output_file"],
            outro_path=str(tmp_path / "missing_outro.mp4"),
        )


def test_concat_nonpositive_max_broll_raises(broll_inputs):
    with pytest.raises(ValueError):
        cf.concat_with_broll(
            broll_inputs["main_path"], broll_inputs["output_file"],
            intro_path=broll_inputs["intro_path"], max_broll_s=0,
        )


# --------------------------------------------------------------------------- #
# concat_with_broll — command assembly (subprocess.run monkeypatched)
# --------------------------------------------------------------------------- #
def _patch_run_capture(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output=False, text=False, check=False):
        captured["cmd"] = cmd
        return _FakeCompleted(0)

    monkeypatch.setattr(cf.subprocess, "run", fake_run)
    monkeypatch.setattr(
        cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264
    )
    return captured


def test_concat_builds_expected_command_intro_and_outro(broll_inputs, monkeypatch):
    captured = _patch_run_capture(monkeypatch)
    out = cf.concat_with_broll(
        broll_inputs["main_path"], broll_inputs["output_file"],
        intro_path=broll_inputs["intro_path"],
        outro_path=broll_inputs["outro_path"],
        max_broll_s=2.5, fps=30, threads=2,
    )
    assert out == broll_inputs["output_file"]
    cmd = captured["cmd"]

    assert cmd[0] == cf.utils.get_ffmpeg_binary()
    # Input order: main, intro, outro, then the lavfi silence source.
    assert cmd[cmd.index("-i") + 1] == broll_inputs["main_path"]
    assert broll_inputs["intro_path"] in cmd
    assert broll_inputs["outro_path"] in cmd
    assert any(a.startswith("anullsrc=") for a in cmd)
    assert "lavfi" in cmd
    # Silence duration is bounded to max_broll_s.
    assert cmd[cmd.index("-t") + 1] == "2.5"
    # Interchange-friendly encode flags per contract.
    for flag in ("-filter_complex", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart"):
        assert flag in cmd
    assert cmd[cmd.index("-c:v") + 1] == cf._LIBX264
    # Concat outputs are mapped.
    assert "[cv]" in cmd
    assert "[ca]" in cmd
    # Whole timeline written — NOT -shortest.
    assert "-shortest" not in cmd
    assert cmd[-1] == broll_inputs["output_file"]


def test_concat_intro_only_has_three_inputs(broll_inputs, monkeypatch):
    captured = _patch_run_capture(monkeypatch)
    cf.concat_with_broll(
        broll_inputs["main_path"], broll_inputs["output_file"],
        intro_path=broll_inputs["intro_path"],
    )
    cmd = captured["cmd"]
    # main + intro + silence == 3 real -i inputs.
    assert cmd.count("-i") == 3
    fg = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=1[cv][ca]" in fg


def test_concat_raises_runtimeerror_on_nonzero_exit(broll_inputs, monkeypatch):
    monkeypatch.setattr(
        cf.subprocess, "run",
        lambda *a, **k: _FakeCompleted(1, stderr="boom: concat failed"),
    )
    monkeypatch.setattr(
        cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264
    )
    with pytest.raises(RuntimeError) as exc:
        cf.concat_with_broll(
            broll_inputs["main_path"], broll_inputs["output_file"],
            intro_path=broll_inputs["intro_path"],
        )
    assert "boom: concat failed" in str(exc.value)


def test_concat_falls_back_to_libx264_on_hw_codec_failure(broll_inputs, monkeypatch):
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
        cf.video_service, "_disable_runtime_video_codec",
        lambda codec, reason: disabled.update(codec=codec, reason=reason),
    )

    out = cf.concat_with_broll(
        broll_inputs["main_path"], broll_inputs["output_file"],
        outro_path=broll_inputs["outro_path"],
    )
    assert out == broll_inputs["output_file"]
    assert calls[0][calls[0].index("-c:v") + 1] == "h264_videotoolbox"
    assert calls[1][calls[1].index("-c:v") + 1] == cf._LIBX264
    assert disabled["codec"] == "h264_videotoolbox"


def test_concat_no_fallback_when_already_libx264(broll_inputs, monkeypatch):
    calls = []
    monkeypatch.setattr(
        cf.subprocess, "run",
        lambda cmd, **k: (calls.append(cmd), _FakeCompleted(1, stderr="x264 broke"))[1],
    )
    monkeypatch.setattr(
        cf.video_service, "_get_effective_video_codec", lambda: cf._LIBX264
    )
    with pytest.raises(RuntimeError):
        cf.concat_with_broll(
            broll_inputs["main_path"], broll_inputs["output_file"],
            intro_path=broll_inputs["intro_path"],
        )
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Optional real-ffmpeg integration test (skipped without a media stack)
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
_REQUIRED_FILTERS = ("scale", "crop", "concat", "anullsrc", "atrim", "aformat")


def _have_media_stack() -> bool:
    if not _FFMPEG or not _FFPROBE:
        return False
    return all(cf.ffmpeg_has_filter(f, _FFMPEG) for f in _REQUIRED_FILTERS)


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "ffmpeg failed")


def _make_clip(path, size, seconds, freq=440):
    """A real MP4 with a video AND an audio stream via lavfi."""
    _run([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        "-shortest", path,
    ])


def _probe(path):
    result = subprocess.run(
        [_FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.integration
@pytest.mark.skipif(
    not _have_media_stack(),
    reason="ffmpeg/ffprobe with the required filters not available",
)
def test_concat_with_broll_real_ffmpeg(tmp_path):
    main = str(tmp_path / "main.mp4")
    intro = str(tmp_path / "intro.mp4")
    outro = str(tmp_path / "outro.mp4")
    out = str(tmp_path / "final.mp4")

    # Main reel is 1080x1920 (portrait); b-roll sources are landscape + longer
    # than the cap so trimming and cover-crop both do real work.
    _make_clip(main, "1080x1920", 1.0, freq=330)
    _make_clip(intro, "1280x720", 2.0, freq=440)
    _make_clip(outro, "640x480", 2.0, freq=550)

    max_broll = 1.0
    returned = cf.concat_with_broll(
        main, out, intro_path=intro, outro_path=outro,
        max_broll_s=max_broll, fps=30, threads=2,
    )
    assert returned == out
    assert os.path.exists(out) and os.path.getsize(out) > 0

    info = _probe(out)
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    astreams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert vstreams, "no video stream in concatenated output"
    v = vstreams[0]
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["codec_name"] == "h264"
    assert astreams, "silent/main audio must be muxed in"

    # Duration ~= main (1.0) + intro (capped 1.0) + outro (capped 1.0) = 3.0s.
    duration = float(info["format"]["duration"])
    assert 2.6 <= duration <= 3.6, f"unexpected duration {duration}s"


@pytest.mark.integration
@pytest.mark.skipif(
    not _have_media_stack(),
    reason="ffmpeg/ffprobe with the required filters not available",
)
def test_concat_with_broll_intro_only_real_ffmpeg(tmp_path):
    main = str(tmp_path / "main.mp4")
    intro = str(tmp_path / "intro.mp4")
    out = str(tmp_path / "final.mp4")
    _make_clip(main, "1080x1920", 1.0, freq=330)
    _make_clip(intro, "1280x720", 2.0, freq=440)

    cf.concat_with_broll(main, out, intro_path=intro, max_broll_s=1.0, fps=30)
    info = _probe(out)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (1080, 1920)
    duration = float(info["format"]["duration"])
    # main (1.0) + intro capped (1.0) ~= 2.0s.
    assert 1.7 <= duration <= 2.5, f"unexpected duration {duration}s"
