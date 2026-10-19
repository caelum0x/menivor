"""Unit + integration tests for the ReelForge "auto-zoom / punch-in" pass
(``app.services.editing.auto_zoom``).

Scope:
  * PURE moment planning (scene-time -> spaced/capped punch-in windows, zoom
    clamping, negligible-zoom no-op).
  * PURE ease math (``_zoom_at`` raised-cosine bump: 1.0 at edges, ``scale`` at
    the midpoint, clamped to the cap, 1.0 outside every window) and the FFmpeg
    ``zoompan`` expression / filter builders.
  * The ``showinfo`` scene-score stderr parser.
  * ``plan_zoom_moments`` driven entirely through the mockable
    ``detect_scene_changes`` seam (no real detection).
  * ``auto_zoom`` DEGRADE-SAFE orchestration via the mockable
    ``plan_zoom_moments`` / ``apply_zooms`` seams: no moments -> applied False +
    original length; planner raises -> original returned unchanged; zero-length
    input -> applied False; a real render is reported with its zoom_count.
  * OPTIONAL real-ffmpeg integration tests (auto-skipped when ffmpeg/ffprobe or a
    required filter is missing) that synthesise a clip with a clear scene change
    and assert a zoom is planned + applied, the output is non-empty, the SAME
    duration as the source, and its A/V durations stay aligned.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.services.editing import auto_zoom as az


# --------------------------------------------------------------------------- #
# showinfo stderr parser
# --------------------------------------------------------------------------- #
def test_parse_showinfo_pts_extracts_sorted_unique():
    stderr = (
        "[Parsed_showinfo_1 @ 0x1] n:0 pts:60000 pts_time:2.0 ...\n"
        "[Parsed_showinfo_1 @ 0x1] n:1 pts:120000 pts_time:4.5 ...\n"
        "[Parsed_showinfo_1 @ 0x1] n:2 pts:120000 pts_time:2.0 ...\n"  # dup
    )
    assert az._parse_showinfo_pts(stderr) == [2.0, 4.5]


def test_parse_showinfo_pts_no_metadata_is_empty():
    assert az._parse_showinfo_pts("nothing to see here") == []


# --------------------------------------------------------------------------- #
# _clamp_zoom
# --------------------------------------------------------------------------- #
def test_clamp_zoom_bounds_to_cap_and_floor():
    assert az._clamp_zoom(1.25) == 1.25
    assert az._clamp_zoom(9.0) == az._MAX_ZOOM_CAP       # capped at ~1.3x
    assert az._clamp_zoom(0.5) == 1.0                     # never below 1.0


# --------------------------------------------------------------------------- #
# _select_moments — spacing / cap / window-fit / negligible zoom
# --------------------------------------------------------------------------- #
def test_select_moments_spaces_and_caps():
    # Cuts at 2/4/8/12 in a 20s clip; min_gap 3, dur 1.0 -> 4 is too close to 2
    # (gap 2 < 3) so it is dropped; 2, 8, 12 survive, capped at max_zooms=2.
    moments = az._select_moments(
        [2.0, 4.0, 8.0, 12.0],
        total=20.0,
        max_zooms=2,
        min_gap_s=3.0,
        zoom=1.25,
        dur_s=1.0,
    )
    assert moments == [(2.0, 1.0, 1.25), (8.0, 1.0, 1.25)]


def test_select_moments_drops_windows_past_end():
    # A cut at 9.8 in a 10s clip with a 1.2s window would run to 11.0 -> dropped.
    moments = az._select_moments(
        [9.8],
        total=10.0,
        max_zooms=4,
        min_gap_s=3.0,
        zoom=1.25,
        dur_s=1.2,
    )
    assert moments == []


def test_select_moments_clamps_zoom_scale():
    moments = az._select_moments(
        [2.0], total=10.0, max_zooms=1, min_gap_s=3.0, zoom=5.0, dur_s=1.0
    )
    assert moments == [(2.0, 1.0, az._MAX_ZOOM_CAP)]


def test_select_moments_negligible_zoom_is_noop():
    # A zoom at/below _MIN_ZOOM is not worth a re-encode.
    assert az._select_moments(
        [2.0], total=10.0, max_zooms=4, min_gap_s=3.0, zoom=1.0, dur_s=1.0
    ) == []


def test_select_moments_min_gap_floored_to_duration():
    # Even with a tiny min_gap, windows must not overlap: the effective gap is
    # max(min_gap, dur)=1.0, so a cut at 2.5 (gap 0.5 < 1.0) is dropped.
    moments = az._select_moments(
        [2.0, 2.5, 4.0],
        total=10.0,
        max_zooms=4,
        min_gap_s=0.1,
        zoom=1.25,
        dur_s=1.0,
    )
    assert moments == [(2.0, 1.0, 1.25), (4.0, 1.0, 1.25)]


# --------------------------------------------------------------------------- #
# _zoom_at — raised-cosine ease units
# --------------------------------------------------------------------------- #
def test_zoom_at_edges_are_unity_and_midpoint_is_peak():
    moments = [(2.0, 1.0, 1.25)]
    assert az._zoom_at(2.0, moments) == pytest.approx(1.0, abs=1e-9)   # ease-in start
    assert az._zoom_at(3.0, moments) == pytest.approx(1.0, abs=1e-9)   # ease-out end
    assert az._zoom_at(2.5, moments) == pytest.approx(1.25, abs=1e-9)  # peak at midpoint


def test_zoom_at_outside_window_is_unity():
    moments = [(2.0, 1.0, 1.25)]
    assert az._zoom_at(0.5, moments) == pytest.approx(1.0, abs=1e-9)
    assert az._zoom_at(9.0, moments) == pytest.approx(1.0, abs=1e-9)


def test_zoom_at_is_monotonic_into_the_peak():
    moments = [(0.0, 1.0, 1.30)]
    quarter = az._zoom_at(0.25, moments)
    assert 1.0 < quarter < 1.30
    # Symmetric ease: a quarter before the peak equals a quarter after it.
    assert az._zoom_at(0.75, moments) == pytest.approx(quarter, abs=1e-9)


def test_zoom_at_clamps_to_cap():
    # Two overlapping bumps summed could exceed the cap; _zoom_at clamps them.
    moments = [(0.0, 2.0, 1.3), (0.0, 2.0, 1.3)]
    assert az._zoom_at(1.0, moments) == pytest.approx(az._MAX_ZOOM_CAP, abs=1e-9)


# --------------------------------------------------------------------------- #
# zoompan expression / filter builders
# --------------------------------------------------------------------------- #
def test_build_zoom_expr_contains_bump_and_cap():
    expr = az._build_zoom_expr([(2.0, 1.0, 1.25)], fps=30)
    assert expr.startswith(f"min({az._MAX_ZOOM_CAP:g},1+")
    assert "between((on/30),2.0000,3.0000)" in expr
    assert "cos(2*PI*" in expr
    # Commas are left bare (the filter builder single-quotes the whole thing).
    assert "\\," not in expr


def test_build_zoom_expr_empty_moments_is_flat_unity():
    # No moments -> the zoom is a constant 1.0 (clamped baseline).
    assert az._build_zoom_expr([], fps=30) == f"min({az._MAX_ZOOM_CAP:g},1)"


def test_build_zoompan_filter_pins_size_fps_and_center_pan():
    vf = az._build_zoompan_filter([(2.0, 1.0, 1.25)], width=640, height=360, fps=30)
    assert vf.startswith("zoompan=z='")
    assert "s=640x360" in vf
    assert "fps=30" in vf
    assert "d=1" in vf
    # Centred pan expressions are single-quoted so their commas survive.
    assert "x='iw/2-(iw/zoom/2)'" in vf
    assert "y='ih/2-(ih/zoom/2)'" in vf


# --------------------------------------------------------------------------- #
# detect_scene_changes — no-file degrade
# --------------------------------------------------------------------------- #
def test_detect_scene_changes_missing_file_returns_empty():
    assert az.detect_scene_changes("/no/such/file.mp4") == []


def test_detect_scene_changes_ffmpeg_fallback_parses_stderr(tmp_path, monkeypatch):
    # Drive detection entirely from synthetic showinfo stderr (no real media) and
    # force the PySceneDetect path to be unavailable so the ffmpeg fallback runs.
    f = tmp_path / "screen.mp4"
    f.write_bytes(b"\x00")
    monkeypatch.setattr(az, "_import_scenedetect", lambda: None)
    monkeypatch.setattr(
        az,
        "_run",
        lambda cmd: subprocess.CompletedProcess(
            cmd, 0, stdout="", stderr="pts_time:2.0\npts_time:4.5\n"
        ),
    )
    assert az.detect_scene_changes(str(f)) == [2.0, 4.5]


# --------------------------------------------------------------------------- #
# plan_zoom_moments — via the mockable detect_scene_changes seam
# --------------------------------------------------------------------------- #
def test_plan_zoom_moments_uses_scene_seam(tmp_path, monkeypatch):
    f = tmp_path / "screen.mp4"
    f.write_bytes(b"\x00")
    monkeypatch.setattr(az, "_probe_duration", lambda *a, **k: 20.0)
    monkeypatch.setattr(az, "detect_scene_changes", lambda *a, **k: [2.0, 4.0, 10.0])

    moments = az.plan_zoom_moments(
        str(f), max_zooms=4, min_gap_s=3.0, zoom=1.25, dur_s=1.0
    )
    # 4.0 dropped (gap 2 < 3); 2.0 and 10.0 kept.
    assert moments == [(2.0, 1.0, 1.25), (10.0, 1.0, 1.25)]


def test_plan_zoom_moments_zero_duration_is_empty(tmp_path, monkeypatch):
    f = tmp_path / "screen.mp4"
    f.write_bytes(b"\x00")
    monkeypatch.setattr(az, "_probe_duration", lambda *a, **k: 0.0)
    assert az.plan_zoom_moments(str(f)) == []


def test_plan_zoom_moments_missing_file_is_empty():
    assert az.plan_zoom_moments("/no/such/file.mp4") == []


# --------------------------------------------------------------------------- #
# auto_zoom — DEGRADE-SAFE orchestration via the mockable seams
# --------------------------------------------------------------------------- #
def _seed_input(tmp_path) -> tuple[str, str]:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"ORIGINAL-CLIP-BYTES")
    return str(src), str(tmp_path / "out.mp4")


def test_auto_zoom_no_moments_is_noop(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(az, "_probe_duration", lambda *a, **k: 12.0)
    monkeypatch.setattr(az, "plan_zoom_moments", lambda *a, **k: [])
    # apply_zooms must never be reached on a no-op.
    monkeypatch.setattr(
        az,
        "apply_zooms",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not render")),
    )

    result = az.auto_zoom(src, out)
    assert result["applied"] is False
    assert result["zoom_count"] == 0
    assert result["original_s"] == 12.0
    assert result["output_s"] == 12.0
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_auto_zoom_planner_raises_returns_original(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(az, "_probe_duration", lambda *a, **k: 9.0)

    def _boom(*a, **k):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(az, "plan_zoom_moments", _boom)

    result = az.auto_zoom(src, out)
    assert result["applied"] is False
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_auto_zoom_zero_duration_input_is_noop(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(az, "_probe_duration", lambda *a, **k: 0.0)
    result = az.auto_zoom(src, out)
    assert result["applied"] is False
    assert result["zoom_count"] == 0


def test_auto_zoom_render_failure_degrades_to_original(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(az, "_probe_duration", lambda *a, **k: 10.0)
    monkeypatch.setattr(az, "plan_zoom_moments", lambda *a, **k: [(2.0, 1.0, 1.25)])

    def _boom(*a, **k):
        raise RuntimeError("ffmpeg zoompan blew up")

    monkeypatch.setattr(az, "apply_zooms", _boom)

    result = az.auto_zoom(src, out)
    assert result["applied"] is False
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_auto_zoom_applies_and_reports_count(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    moments = [(2.0, 1.0, 1.25), (8.0, 1.0, 1.25)]
    monkeypatch.setattr(az, "plan_zoom_moments", lambda *a, **k: moments)

    durations = iter([10.0, 10.0])  # source probe, then output probe (same length)

    def _fake_dur(*a, **k):
        return next(durations)

    monkeypatch.setattr(az, "_probe_duration", _fake_dur)

    captured = {}

    def _fake_apply(input_path, mom, output_path, **kw):
        captured["moments"] = mom
        shutil.copyfile(input_path, output_path)  # simulate a real render
        return output_path

    monkeypatch.setattr(az, "apply_zooms", _fake_apply)

    result = az.auto_zoom(src, out, max_zooms=3, min_gap_s=2.0, zoom=1.25)
    assert result["applied"] is True
    assert result["zoom_count"] == 2
    assert result["original_s"] == 10.0
    assert result["output_s"] == 10.0            # duration-preserving
    assert result["moments"] == moments
    assert captured["moments"] == moments


def test_auto_zoom_forwards_plan_kwargs(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(az, "_probe_duration", lambda *a, **k: 10.0)

    seen = {}

    def _capture_plan(input_path, *, max_zooms, min_gap_s, zoom, **plan_opts):
        seen["max_zooms"] = max_zooms
        seen["min_gap_s"] = min_gap_s
        seen["zoom"] = zoom
        seen["plan_opts"] = plan_opts
        return []

    monkeypatch.setattr(az, "plan_zoom_moments", _capture_plan)

    az.auto_zoom(
        src, out, max_zooms=2, min_gap_s=4.0, zoom=1.3, dur_s=0.8, threshold=0.3
    )
    assert seen["max_zooms"] == 2
    assert seen["min_gap_s"] == 4.0
    assert seen["zoom"] == 1.3
    assert seen["plan_opts"] == {"dur_s": 0.8, "threshold": 0.3}


# --------------------------------------------------------------------------- #
# Optional real-ffmpeg integration
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _have(*filters: str) -> bool:
    if not _FFMPEG or not _FFPROBE:
        return False
    return all(az.ffmpeg_has_filter(f, _FFMPEG) for f in filters)


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


def _make_scene_clip(tmp_path) -> str:
    """Build a 4s clip with a hard scene cut at ~2s: two very different halves."""
    first = str(tmp_path / "first.mp4")
    second = str(tmp_path / "second.mp4")
    screen = str(tmp_path / "screen.mp4")

    # Half 1: a busy test pattern + tone. Half 2: a flat solid colour + tone.
    _run_real([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", first,
    ])
    _run_real([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", "color=c=blue:size=640x360:rate=30:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", second,
    ])

    concat_txt = str(tmp_path / "list.txt")
    with open(concat_txt, "w", encoding="utf-8") as fh:
        for part in (first, second):
            fh.write(f"file '{part}'\n")
    # Re-encode on concat so timestamps are clean for the scene detector.
    _run_real([
        _FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", screen,
    ])
    return screen


@pytest.mark.integration
@pytest.mark.skipif(
    not _have("zoompan", "select", "showinfo"),
    reason="ffmpeg with zoompan/select/showinfo unavailable",
)
def test_real_auto_zoom_plans_and_applies_a_punch_in(tmp_path):
    screen = _make_scene_clip(tmp_path)
    out = str(tmp_path / "zoomed.mp4")

    src_info = _probe(screen)
    src_dur = float(src_info["format"]["duration"])
    assert src_dur == pytest.approx(4.0, abs=0.4)

    result = az.auto_zoom(
        screen, out,
        max_zooms=3,
        min_gap_s=0.5,   # allow the single mid-clip cut to be selected
        zoom=1.25,
        dur_s=1.0,
        threshold=0.3,   # the solid->pattern boundary scores well above this
    )

    assert result["applied"] is True, result
    assert result["zoom_count"] >= 1

    out_info = _probe(out)
    v = _stream(out_info, "video")
    a = _stream(out_info, "audio")
    assert v is not None, "zoomed output must keep a video stream"
    assert a is not None, "zoomed output must keep an audio stream"

    # Output must be a real, non-empty file the SAME length as the source.
    out_dur = float(out_info["format"]["duration"])
    assert out_dur == pytest.approx(src_dur, abs=0.4)

    # A/V-sync safety: audio and video durations stay aligned within tolerance.
    v_dur = float(v.get("duration") or out_dur)
    a_dur = float(a.get("duration") or out_dur)
    assert abs(v_dur - a_dur) <= 0.25


@pytest.mark.integration
@pytest.mark.skipif(
    not _have("zoompan"),
    reason="ffmpeg without zoompan",
)
def test_real_apply_zooms_is_av_sync_safe(tmp_path):
    # A plain 4s tone+motion clip; a single punch-in at 1..2 -> same-length out.
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "zoom.mp4")
    _run_real([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=4",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", src,
    ])

    az.apply_zooms(src, [(1.0, 1.0, 1.25)], out)

    info = _probe(out)
    v = _stream(info, "video")
    a = _stream(info, "audio")
    assert v is not None and a is not None
    out_dur = float(info["format"]["duration"])
    assert out_dur == pytest.approx(4.0, abs=0.4)
    assert abs(float(v.get("duration") or out_dur)
               - float(a.get("duration") or out_dur)) <= 0.25
