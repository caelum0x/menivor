"""Unit + integration tests for the ReelForge "auto-tighten" dead-air remover
(``app.services.editing.silence_cut``).

Scope:
  * PURE range algebra + keep-segment assembly (merge/invert/intersect, padding,
    min-keep folding, NO-OP sentinel).
  * stderr parsers for ``silencedetect`` / ``freezedetect`` metadata.
  * ``tighten`` DEGRADE-SAFE orchestration via the mockable ``detect_dead_air``
    seam (no real heavy media): no dead air -> applied False + original length;
    entirely-dead input -> applied False (never empties); detector raises ->
    original returned unchanged.
  * An OPTIONAL real-ffmpeg integration test (auto-skipped when ffmpeg/ffprobe or
    a required filter is missing) that synthesises a clip with a clear
    silent+static gap and asserts the gap is removed, the output is shorter and
    non-empty, and its A/V durations stay aligned.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.services.editing import silence_cut as sc

# --------------------------------------------------------------------------- #
# Range algebra
# --------------------------------------------------------------------------- #
def test_merge_ranges_coalesces_overlapping_and_adjacent():
    merged = sc._merge_ranges([(0.0, 1.0), (0.9, 2.0), (2.0, 3.0), (5.0, 6.0)])
    assert merged == [(0.0, 3.0), (5.0, 6.0)]


def test_merge_ranges_empty():
    assert sc._merge_ranges([]) == []


def test_clamp_ranges_bounds_and_drops_degenerate():
    clamped = sc._clamp_ranges([(-1.0, 2.0), (5.0, 4.0), (8.0, 20.0)], total=10.0)
    assert clamped == [(0.0, 2.0), (8.0, 10.0)]


def test_invert_ranges_returns_gaps():
    keeps = sc._invert_ranges([(2.0, 4.0), (6.0, 7.0)], total=10.0)
    assert keeps == [(0.0, 2.0), (4.0, 6.0), (7.0, 10.0)]


def test_invert_ranges_full_dead_returns_empty():
    assert sc._invert_ranges([(0.0, 10.0)], total=10.0) == []


def test_invert_ranges_no_dead_returns_whole():
    assert sc._invert_ranges([], total=10.0) == [(0.0, 10.0)]


def test_intersect_ranges_overlap_only():
    a = [(0.0, 5.0), (7.0, 10.0)]
    b = [(3.0, 8.0), (9.0, 12.0)]
    assert sc._intersect_ranges(a, b) == [(3.0, 5.0), (7.0, 8.0), (9.0, 10.0)]


def test_intersect_ranges_disjoint_is_empty():
    assert sc._intersect_ranges([(0.0, 1.0)], [(2.0, 3.0)]) == []


# --------------------------------------------------------------------------- #
# stderr parsers
# --------------------------------------------------------------------------- #
def test_parse_silence_ranges_pairs_start_end():
    stderr = (
        "[silencedetect @ 0x1] silence_start: 1.5\n"
        "[silencedetect @ 0x1] silence_end: 3.0 | silence_duration: 1.5\n"
        "[silencedetect @ 0x1] silence_start: 6.0\n"
        "[silencedetect @ 0x1] silence_end: 6.4 | silence_duration: 0.4\n"
    )
    ranges = sc._parse_paired_ranges(
        stderr, sc._SILENCE_START_RE, sc._SILENCE_END_RE, total=10.0
    )
    assert ranges == [(1.5, 3.0), (6.0, 6.4)]


def test_parse_dangling_start_closes_at_total():
    # A trailing silence_start with no matching end runs to EOF.
    stderr = "silence_start: 8.0\n"
    ranges = sc._parse_paired_ranges(
        stderr, sc._SILENCE_START_RE, sc._SILENCE_END_RE, total=10.0
    )
    assert ranges == [(8.0, 10.0)]


def test_parse_freeze_ranges():
    stderr = (
        "lavfi.freezedetect.freeze_start: 2.0\n"
        "lavfi.freezedetect.freeze_end: 4.5\n"
    )
    ranges = sc._parse_paired_ranges(
        stderr, sc._FREEZE_START_RE, sc._FREEZE_END_RE, total=10.0
    )
    assert ranges == [(2.0, 4.5)]


def test_parse_no_metadata_is_empty():
    assert sc._parse_paired_ranges(
        "nothing here", sc._SILENCE_START_RE, sc._SILENCE_END_RE, total=10.0
    ) == []


# --------------------------------------------------------------------------- #
# build_keep_segments — pad / min-keep / NO-OP
# --------------------------------------------------------------------------- #
def test_build_keep_segments_inverts_and_pads():
    # One dead gap 4..6 in a 10s clip; pad 0.1 grows the neighbouring keeps.
    keeps = sc.build_keep_segments([(4.0, 6.0)], total_duration=10.0, pad_s=0.1)
    assert keeps == [(0.0, 4.1), (5.9, 10.0)]


def test_build_keep_segments_noop_when_no_dead_air():
    # Nothing removable -> single full-length segment sentinel.
    assert sc.build_keep_segments([], total_duration=10.0) == [(0.0, 10.0)]


def test_build_keep_segments_noop_when_entirely_dead():
    # Whole clip dead -> NEVER return empty; return the full-length no-op.
    assert sc.build_keep_segments([(0.0, 10.0)], total_duration=10.0) == [(0.0, 10.0)]


def test_build_keep_segments_noop_when_removal_below_threshold():
    # A 0.05s gap is under _MIN_REMOVED_S -> not worth cutting.
    keeps = sc.build_keep_segments([(5.0, 5.05)], total_duration=10.0, pad_s=0.0)
    assert keeps == [(0.0, 10.0)]


def test_build_keep_segments_drops_short_sliver_between_dead_zones():
    # Two dead zones sandwich a 0.2s sliver < min_keep_s=0.4 -> the sliver folds
    # away, leaving only the two long keeps.
    dead = [(3.0, 5.0), (5.2, 8.0)]
    keeps = sc.build_keep_segments(
        dead, total_duration=10.0, pad_s=0.0, min_keep_s=0.4
    )
    assert keeps == [(0.0, 3.0), (8.0, 10.0)]


def test_is_noop_detects_full_length_segment():
    assert sc._is_noop([(0.0, 10.0)], total_duration=10.0) is True
    assert sc._is_noop([], total_duration=10.0) is True
    assert sc._is_noop([(0.0, 4.0), (6.0, 10.0)], total_duration=10.0) is False


# --------------------------------------------------------------------------- #
# detect_dead_air — mode validation + no-file degrade
# --------------------------------------------------------------------------- #
def test_detect_dead_air_rejects_bad_mode(tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"\x00")
    with pytest.raises(ValueError, match="unsupported mode"):
        sc.detect_dead_air(str(f), mode="nonsense")


def test_detect_dead_air_missing_file_returns_empty():
    assert sc.detect_dead_air("/no/such/file.mp4") == []


def test_detect_dead_air_auto_intersects_silence_and_freeze(tmp_path, monkeypatch):
    # Drive detection entirely from synthetic ffmpeg stderr (no real media): the
    # audio is silent 2..8, the video frozen 4..10 -> AUTO dead = 4..8.
    f = tmp_path / "screen.mp4"
    f.write_bytes(b"\x00")
    fake_stderr = (
        "silence_start: 2.0\nsilence_end: 8.0\n"
        "freeze_start: 4.0\nfreeze_end: 10.0\n"
    )

    monkeypatch.setattr(sc, "_probe_duration", lambda *a, **k: 10.0)
    monkeypatch.setattr(sc, "_has_audio_stream", lambda *a, **k: True)
    monkeypatch.setattr(sc, "ffmpeg_has_filter", lambda *a, **k: True)
    monkeypatch.setattr(
        sc, "_run",
        lambda cmd: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=fake_stderr),
    )

    dead = sc.detect_dead_air(str(f), mode="auto")
    assert dead == [(4.0, 8.0)]


def test_detect_dead_air_auto_no_audio_falls_back_to_static(tmp_path, monkeypatch):
    # A muted screen recording: AUTO collapses to the frozen (static) ranges.
    f = tmp_path / "screen.mp4"
    f.write_bytes(b"\x00")
    monkeypatch.setattr(sc, "_probe_duration", lambda *a, **k: 10.0)
    monkeypatch.setattr(sc, "_has_audio_stream", lambda *a, **k: False)
    monkeypatch.setattr(sc, "ffmpeg_has_filter", lambda *a, **k: True)
    monkeypatch.setattr(
        sc, "_run",
        lambda cmd: subprocess.CompletedProcess(
            cmd, 0, stdout="", stderr="freeze_start: 3.0\nfreeze_end: 7.0\n"
        ),
    )
    assert sc.detect_dead_air(str(f), mode="auto") == [(3.0, 7.0)]


# --------------------------------------------------------------------------- #
# _build_cut_filtergraph
# --------------------------------------------------------------------------- #
def test_cut_filtergraph_with_audio_pairs_trim_atrim_concat():
    graph, vmap, amap = sc._build_cut_filtergraph(
        [(0.0, 4.0), (6.0, 10.0)], has_audio=True
    )
    assert vmap == "[cv]" and amap == "[ca]"
    assert "[0:v]trim=start=0.0000:end=4.0000" in graph
    assert "[0:a]atrim=start=6.0000:end=10.0000" in graph
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[cv][ca]" in graph


def test_cut_filtergraph_without_audio_is_video_only():
    graph, vmap, amap = sc._build_cut_filtergraph([(0.0, 4.0)], has_audio=False)
    assert vmap == "[cv]" and amap == ""
    assert "atrim" not in graph
    assert "concat=n=1:v=1:a=0[cv]" in graph


# --------------------------------------------------------------------------- #
# tighten — DEGRADE-SAFE orchestration via the mockable detect_dead_air seam
# --------------------------------------------------------------------------- #
def _seed_input(tmp_path) -> tuple[str, str]:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"ORIGINAL-CLIP-BYTES")
    return str(src), str(tmp_path / "out.mp4")


def test_tighten_no_dead_air_is_noop(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(sc, "_probe_duration", lambda *a, **k: 12.0)
    monkeypatch.setattr(sc, "detect_dead_air", lambda *a, **k: [])
    # apply_cuts must never be reached on a no-op.
    monkeypatch.setattr(
        sc, "apply_cuts",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not cut")),
    )

    result = sc.tighten(src, out)
    assert result["applied"] is False
    assert result["original_s"] == 12.0
    assert result["tightened_s"] == 12.0
    assert result["removed_s"] == 0.0
    # Original copied through unchanged.
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_tighten_entirely_dead_never_empties(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(sc, "_probe_duration", lambda *a, **k: 8.0)
    # Whole clip flagged dead -> keep-builder returns the full no-op sentinel.
    monkeypatch.setattr(sc, "detect_dead_air", lambda *a, **k: [(0.0, 8.0)])
    monkeypatch.setattr(
        sc, "apply_cuts",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not cut")),
    )

    result = sc.tighten(src, out)
    assert result["applied"] is False
    assert result["tightened_s"] == 8.0
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_tighten_detector_raises_returns_original(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(sc, "_probe_duration", lambda *a, **k: 9.0)

    def _boom(*a, **k):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(sc, "detect_dead_air", _boom)

    result = sc.tighten(src, out)
    assert result["applied"] is False
    with open(out, "rb") as fh:
        assert fh.read() == b"ORIGINAL-CLIP-BYTES"


def test_tighten_zero_duration_input_is_noop(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(sc, "_probe_duration", lambda *a, **k: 0.0)
    result = sc.tighten(src, out)
    assert result["applied"] is False
    assert result["removed_s"] == 0.0


def test_tighten_applies_cut_and_reports_removed(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    # Source is 10s; detector flags a 4..6 dead gap -> keeps remove ~1.8s.
    monkeypatch.setattr(sc, "detect_dead_air", lambda *a, **k: [(4.0, 6.0)])

    durations = iter([10.0, 8.2])  # source probe, then output probe

    def _fake_dur(*a, **k):
        return next(durations)

    monkeypatch.setattr(sc, "_probe_duration", _fake_dur)

    captured = {}

    def _fake_apply(input_path, keep_segments, output_path, **kw):
        captured["keeps"] = keep_segments
        # Simulate ffmpeg writing a real (shorter) file.
        shutil.copyfile(input_path, output_path)
        return output_path

    monkeypatch.setattr(sc, "apply_cuts", _fake_apply)

    result = sc.tighten(src, out, pad_s=0.1)
    assert result["applied"] is True
    assert result["original_s"] == 10.0
    assert result["tightened_s"] == 8.2
    assert result["removed_s"] == pytest.approx(1.8, abs=1e-6)
    assert captured["keeps"] == [(0.0, 4.1), (5.9, 10.0)]


def test_tighten_forwards_threshold_kwargs(tmp_path, monkeypatch):
    src, out = _seed_input(tmp_path)
    monkeypatch.setattr(sc, "_probe_duration", lambda *a, **k: 10.0)

    seen = {}

    def _capture_detect(input_path, *, mode, **thresholds):
        seen["mode"] = mode
        seen["thresholds"] = thresholds
        return []

    monkeypatch.setattr(sc, "detect_dead_air", _capture_detect)

    sc.tighten(
        src, out,
        mode="audio",
        audio_silence_db=-40.0,
        min_silence_s=0.5,
        pad_s=0.2,          # consumed by build_keep_segments, NOT forwarded
        min_keep_s=0.3,     # consumed by build_keep_segments, NOT forwarded
    )
    assert seen["mode"] == "audio"
    assert seen["thresholds"] == {"audio_silence_db": -40.0, "min_silence_s": 0.5}


# --------------------------------------------------------------------------- #
# Optional real-ffmpeg integration
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _have(*filters: str) -> bool:
    if not _FFMPEG or not _FFPROBE:
        return False
    return all(sc.ffmpeg_has_filter(f, _FFMPEG) for f in filters)


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
    not _have("silencedetect", "freezedetect", "trim", "atrim", "concat"),
    reason="ffmpeg with silencedetect/freezedetect/concat unavailable",
)
def test_real_tighten_removes_silent_static_gap(tmp_path):
    # Build a 3-part clip: 2s tone+motion, 2s SILENT+FROZEN gap, 2s tone+motion.
    active1 = str(tmp_path / "a1.mp4")
    gap = str(tmp_path / "gap.mp4")
    active2 = str(tmp_path / "a2.mp4")
    screen = str(tmp_path / "screen.mp4")
    out = str(tmp_path / "tight.mp4")

    def _active(path: str):
        _run_real([
            _FFMPEG, "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
            "-shortest", path,
        ])

    _active(active1)
    _active(active2)
    # The dead gap: a single static colour frame + true silence.
    _run_real([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", "color=c=black:size=640x360:rate=30:duration=2",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", "2", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", gap,
    ])

    concat_txt = str(tmp_path / "list.txt")
    with open(concat_txt, "w", encoding="utf-8") as fh:
        for part in (active1, gap, active2):
            fh.write(f"file '{part}'\n")
    # Re-encode on concat so timestamps are clean for the detectors.
    _run_real([
        _FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", screen,
    ])

    src_info = _probe(screen)
    src_dur = float(src_info["format"]["duration"])
    assert src_dur == pytest.approx(6.0, abs=0.4)

    result = sc.tighten(
        screen, out,
        mode="auto",
        min_silence_s=0.4,
        min_motion_gap_s=0.4,
        pad_s=0.1,
    )

    assert result["applied"] is True, result
    # Roughly the ~2s dead gap should be gone (minus the 0.1s pads).
    assert result["removed_s"] >= 1.0
    assert 0 < result["tightened_s"] < src_dur

    out_info = _probe(out)
    v = _stream(out_info, "video")
    a = _stream(out_info, "audio")
    assert v is not None, "tightened output must keep a video stream"
    assert a is not None, "tightened output must keep an audio stream"

    # Output must be a real, non-empty file shorter than the source.
    out_dur = float(out_info["format"]["duration"])
    assert 0 < out_dur < src_dur

    # A/V-sync safety: audio and video durations stay aligned within tolerance.
    v_dur = float(v.get("duration") or out_dur)
    a_dur = float(a.get("duration") or out_dur)
    assert abs(v_dur - a_dur) <= 0.25


@pytest.mark.integration
@pytest.mark.skipif(
    not _have("trim", "atrim", "concat"),
    reason="ffmpeg without trim/concat",
)
def test_real_apply_cuts_is_av_sync_safe(tmp_path):
    # A plain 4s tone+motion clip; keep only 0..1 and 3..4 -> ~2s A/V-aligned out.
    src = str(tmp_path / "src.mp4")
    out = str(tmp_path / "cut.mp4")
    _run_real([
        _FFMPEG, "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=4",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", src,
    ])

    sc.apply_cuts(src, [(0.0, 1.0), (3.0, 4.0)], out)

    info = _probe(out)
    v = _stream(info, "video")
    a = _stream(info, "audio")
    assert v is not None and a is not None
    out_dur = float(info["format"]["duration"])
    assert out_dur == pytest.approx(2.0, abs=0.3)
    assert abs(float(v.get("duration") or out_dur)
               - float(a.get("duration") or out_dur)) <= 0.2
