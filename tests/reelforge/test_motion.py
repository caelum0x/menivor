"""Unit + integration tests for the ReelForge "fake camera motion" pass
(``app.services.editing.motion``).

Scope:
  * PURE intensity clamp (``<= 1.15x`` subtlety ceiling) + preset expression
    builders (each preset produces a ``scale``+``crop`` chain whose zoom stays
    within the clamp).
  * ``motion`` DEGRADE-SAFE orchestration via the mockable ``apply_motion`` +
    ``_probe_duration`` seams (no real heavy media): ``preset='none'`` / unknown
    -> applied False + original copied through; a real render -> applied True with
    the source duration; ``apply_motion`` raising -> original returned unchanged;
    a drifted output duration -> original kept.
  * An OPTIONAL real-ffmpeg integration test (auto-skipped when ffmpeg/ffprobe is
    missing) that renders EACH animated preset and asserts the output is a
    non-empty clip of the SAME duration with its audio stream intact.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess

import pytest

# The ``editing`` package re-exports a public function named ``motion`` (the
# opt-in entry point), which shadows the ``motion`` SUBMODULE attribute on the
# package — so ``from app.services.editing import motion`` yields the function
# (what integration callers want, mirroring ``from ... import tighten``). To
# reach the module's own internals here we resolve the submodule directly.
mo = importlib.import_module("app.services.editing.motion")

# --------------------------------------------------------------------------- #
# Intensity clamp — the subtlety ceiling (<= 1.15x)
# --------------------------------------------------------------------------- #
def test_clamp_intensity_within_range_is_unchanged():
    assert mo._clamp_intensity(0.06) == pytest.approx(0.06)
    assert mo._clamp_intensity(0.0) == 0.0


def test_clamp_intensity_caps_at_max_zoom():
    # Anything above the ceiling is clamped so the synthetic zoom stays <= 1.15x.
    assert mo._clamp_intensity(0.5) == mo._MAX_INTENSITY
    assert mo._clamp_intensity(1.0) == mo._MAX_INTENSITY
    assert mo._MAX_INTENSITY == pytest.approx(0.15)


def test_clamp_intensity_floors_negative_at_zero():
    assert mo._clamp_intensity(-0.3) == 0.0


def test_clamp_intensity_non_numeric_falls_back_to_default():
    assert mo._clamp_intensity("nonsense") == mo._DEFAULT_INTENSITY
    assert mo._clamp_intensity(None) == mo._DEFAULT_INTENSITY


# --------------------------------------------------------------------------- #
# Preset catalogue
# --------------------------------------------------------------------------- #
def test_preset_catalogue_is_complete_and_ordered():
    assert mo.MOTION_PRESETS == (
        "ken_burns",
        "push_in",
        "pull_out",
        "whip_pan",
        "none",
    )
    # ``none`` is a no-op sentinel, never an animated render target.
    assert "none" not in mo._ANIMATED_PRESETS
    assert mo._ANIMATED_PRESETS == frozenset(
        {"ken_burns", "push_in", "pull_out", "whip_pan"}
    )


# --------------------------------------------------------------------------- #
# Motion filtergraph builders (pure string builders)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("preset", ["ken_burns", "push_in", "pull_out", "whip_pan"])
def test_build_motion_filter_shape_per_preset(preset):
    graph = mo._build_motion_filter(preset, 0.06, 640, 360, 3.0)
    # Every preset animates via scale(eval=frame) then crops back to native size.
    assert "scale=w=" in graph
    assert "eval=frame" in graph
    assert "crop=640:360" in graph
    assert graph.endswith("setsar=1")
    # No commas leak INTO an expression (they would be parsed as filter breaks).
    # The only top-level filter separators are scale , crop , setsar.
    assert graph.count("crop=640:360") == 1


def test_push_in_and_pull_out_are_centred():
    push = mo._motion_spec("push_in", 0.06, 3.0)
    pull = mo._motion_spec("pull_out", 0.06, 3.0)
    assert push.crop_x == mo._CENTER_X and push.crop_y == mo._CENTER_Y
    assert pull.crop_x == mo._CENTER_X and pull.crop_y == mo._CENTER_Y
    # push_in zooms IN (grows with progress); pull_out starts zoomed and relaxes.
    assert "*(t/3)" in push.zoom
    assert "(1-(t/3))" in pull.zoom


def test_whip_pan_oscillates_horizontally_only():
    spec = mo._motion_spec("whip_pan", 0.06, 3.0)
    assert "sin(2*PI*" in spec.crop_x         # fast horizontal sweep
    assert spec.crop_y == mo._CENTER_Y        # vertical stays centred
    # Constant zoom (no progress term) just opens horizontal pan room.
    assert spec.zoom == "(1+0.06)"


def test_ken_burns_drifts_diagonally_with_zoom():
    spec = mo._motion_spec("ken_burns", 0.06, 3.0)
    assert "(t/3)" in spec.crop_x and "(t/3)" in spec.crop_y  # diagonal drift
    assert "(t/3)" in spec.zoom                               # ramps with progress


def test_motion_spec_rejects_unknown_preset():
    with pytest.raises(ValueError, match="unsupported motion preset"):
        mo._motion_spec("nonsense", 0.06, 3.0)


def test_even_rounds_down():
    assert mo._even(641) == 640
    assert mo._even(640) == 640
    assert mo._even(1) == 0


# --------------------------------------------------------------------------- #
# apply_motion — validation (no ffmpeg needed)
# --------------------------------------------------------------------------- #
def test_apply_motion_rejects_none_and_unknown_preset(tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"\x00")
    for bad in ("none", "nonsense"):
        with pytest.raises(ValueError, match="unsupported motion preset"):
            mo.apply_motion(str(f), str(tmp_path / "o.mp4"), preset=bad)


def test_apply_motion_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        mo.apply_motion("/no/such/file.mp4", str(tmp_path / "o.mp4"), preset="push_in")


# --------------------------------------------------------------------------- #
# motion — DEGRADE-SAFE orchestration via the mockable apply_motion seam
# --------------------------------------------------------------------------- #
def _seed_input(tmp_path) -> tuple[str, str]:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"ORIGINAL-CLIP-BYTES")
    return str(src), str(tmp_path / "out.mp4")


def test_motion_none_is_noop_original_copied(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(mo, "_probe_duration", lambda *a, **k: 10.0)
    # apply_motion must never be reached for the no-op preset.
    monkeypatch.setattr(
        mo, "apply_motion",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not render")),
    )

    result = mo.motion(src, out, "none")
    assert result["applied"] is False
    assert result["preset"] == "none"
    assert result["original_s"] == 10.0
    assert result["output_s"] == 10.0
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_motion_unknown_preset_is_noop_original_copied(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(mo, "_probe_duration", lambda *a, **k: 8.0)
    monkeypatch.setattr(
        mo, "apply_motion",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not render")),
    )
    result = mo.motion(src, out, "cinematic_dolly")
    assert result["applied"] is False
    assert result["preset"] == "cinematic_dolly"
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_motion_zero_duration_input_is_noop(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(mo, "_probe_duration", lambda *a, **k: 0.0)
    monkeypatch.setattr(
        mo, "apply_motion",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not render")),
    )
    result = mo.motion(src, out, "ken_burns")
    assert result["applied"] is False
    assert result["output_s"] == 0.0


def test_motion_applies_and_reports_same_duration(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    # Motion never changes duration: source and output probe to the same length.
    durations = iter([10.0, 10.0])  # source probe, then output probe

    def _fake_dur(*a, **k):
        return next(durations)

    monkeypatch.setattr(mo, "_probe_duration", _fake_dur)

    captured = {}

    def _fake_apply(input_path, output_path, *, preset, intensity, aspect=None, **kw):
        captured["preset"] = preset
        captured["intensity"] = intensity
        captured["aspect"] = aspect
        shutil.copyfile(input_path, output_path)  # simulate ffmpeg writing a file
        return output_path

    monkeypatch.setattr(mo, "apply_motion", _fake_apply)

    result = mo.motion(src, out, "push_in", intensity=0.5, aspect="9:16")
    assert result["applied"] is True
    assert result["preset"] == "push_in"
    assert result["original_s"] == 10.0
    assert result["output_s"] == 10.0
    # opts are forwarded to apply_motion (clamping itself happens inside it).
    assert captured["preset"] == "push_in"
    assert captured["intensity"] == 0.5
    assert captured["aspect"] == "9:16"


def test_motion_render_raises_returns_original(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(mo, "_probe_duration", lambda *a, **k: 9.0)

    def _boom(*a, **k):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(mo, "apply_motion", _boom)

    result = mo.motion(src, out, "ken_burns")
    assert result["applied"] is False
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_motion_duration_drift_keeps_original(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    # Source is 10s but the render came back 6s (a corrupt/short output): reject
    # it and keep the original so duration is never changed.
    durations = iter([10.0, 6.0])

    def _fake_dur(*a, **k):
        return next(durations)

    monkeypatch.setattr(mo, "_probe_duration", _fake_dur)
    monkeypatch.setattr(
        mo, "apply_motion",
        lambda ip, op, **k: (shutil.copyfile(ip, op), op)[1],
    )

    result = mo.motion(src, out, "push_in")
    assert result["applied"] is False
    assert result["original_s"] == 10.0
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_motion_case_insensitive_preset(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    durations = iter([5.0, 5.0])
    monkeypatch.setattr(mo, "_probe_duration", lambda *a, **k: next(durations))
    seen = {}

    def _fake_apply(ip, op, *, preset, **k):
        seen["preset"] = preset
        shutil.copyfile(ip, op)
        return op

    monkeypatch.setattr(mo, "apply_motion", _fake_apply)
    result = mo.motion(src, out, "  Ken_Burns  ")
    assert result["applied"] is True
    assert result["preset"] == "ken_burns"
    assert seen["preset"] == "ken_burns"


# --------------------------------------------------------------------------- #
# Optional real-ffmpeg integration
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _run_real(cmd: list[str]) -> None:
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


def _stream(info: dict, kind: str) -> dict | None:
    for s in info.get("streams", []):
        if s.get("codec_type") == kind:
            return s
    return None


@pytest.mark.integration
@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe unavailable"
)
@pytest.mark.parametrize("preset", ["ken_burns", "push_in", "pull_out", "whip_pan"])
def test_real_motion_preserves_duration_and_audio(tmp_path, preset):
    # A 3s tone+motion clip; each preset must render a non-empty clip of the SAME
    # duration with its audio intact (A/V-sync-safe overlay transform).
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / f"{preset}.mp4")
    _run_real([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", src,
    ])

    src_info = _probe(src)
    src_dur = float(src_info["format"]["duration"])

    result = mo.motion(src, out, preset, intensity=0.08, aspect="9:16")
    assert result["applied"] is True, result
    assert result["preset"] == preset

    out_info = _probe(out)
    v = _stream(out_info, "video")
    a = _stream(out_info, "audio")
    assert v is not None, "motion output must keep a video stream"
    assert a is not None, "motion output must keep the audio stream intact"

    out_dur = float(out_info["format"]["duration"])
    # Motion is an overlay transform — duration is preserved (NOT a cut).
    assert out_dur == pytest.approx(src_dur, abs=0.15)
    # Native geometry is preserved for the downstream compose crop-to-fill.
    assert int(v["width"]) == 640 and int(v["height"]) == 360

    # A/V-sync safety: audio and video durations stay aligned within tolerance.
    v_dur = float(v.get("duration") or out_dur)
    a_dur = float(a.get("duration") or out_dur)
    assert abs(v_dur - a_dur) <= 0.25


@pytest.mark.integration
@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe unavailable"
)
def test_real_motion_none_returns_original_unchanged(tmp_path):
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "out.mp4")
    _run_real([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=2",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", src,
    ])

    result = mo.motion(src, out, "none")
    assert result["applied"] is False
    assert result["preset"] == "none"
    # The original bytes are copied through byte-for-byte.
    with open(src, "rb") as a, open(out, "rb") as b:
        assert a.read() == b.read()


@pytest.mark.integration
@pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe unavailable"
)
def test_real_motion_video_only_input_has_no_audio_to_break(tmp_path):
    # A muted screen recording (no audio track) must still render + preserve
    # duration without an audio stream-copy blowing up.
    src = str(tmp_path / "mute.mp4")
    out = str(tmp_path / "mute_motion.mp4")
    _run_real([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", "testsrc2=size=480x270:rate=30:duration=2",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", src,
    ])

    src_dur = float(_probe(src)["format"]["duration"])
    result = mo.motion(src, out, "ken_burns")
    assert result["applied"] is True, result
    out_info = _probe(out)
    assert _stream(out_info, "video") is not None
    assert _stream(out_info, "audio") is None  # still no audio, no crash
    assert float(out_info["format"]["duration"]) == pytest.approx(src_dur, abs=0.15)
