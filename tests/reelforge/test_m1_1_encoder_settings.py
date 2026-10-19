"""M1.1: live encoder settings (veryfast, CRF 21, 2 s GOP) and pre-encoded loops."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("MENIVOR_X264_PRESET", raising=False)
    monkeypatch.delenv("MENIVOR_X264_CRF", raising=False)
    monkeypatch.delenv("MENIVOR_LOOP_PRESET", raising=False)
    monkeypatch.setenv("MENIVOR_LOOP_CACHE", str(tmp_path / "loop-cache"))


# --------------------------------------------------------------------------- #
# Live encode args
# --------------------------------------------------------------------------- #
def test_live_encode_args_are_veryfast_crf21_gop60():
    from app.services.compose.compose_ffmpeg import live_encode_args

    assert live_encode_args("libx264", 30) == ["-preset", "veryfast", "-crf", "21", "-g", "60"]


def test_gop_follows_the_frame_rate_and_hardware_gets_only_the_gop():
    from app.services.compose.compose_ffmpeg import gop_frames, live_encode_args

    assert gop_frames(24) == 48
    assert gop_frames("bad") == 60
    assert live_encode_args("h264_videotoolbox", 30) == ["-g", "60"]


def _after(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_every_compose_command_carries_the_live_settings():
    from app.services.compose.compose_ffmpeg import (
        _build_captions_command,
        _build_command,
        _build_concat_command,
    )

    commands = [
        _build_captions_command("ffmpeg", "s.mp4", "a.mp3", "o.mp4", "[0:v]null[final]", "libx264", 2, 30),
        _build_command("ffmpeg", "s.mp4", "v.mp4", "a.mp3", "o.mp4", "g", "libx264", 2, 30),
        _build_concat_command(
            "ffmpeg", "m.mp4", "o.mp4", "g", "libx264", 2, 30,
            intro_path="i.mp4", outro_path=None, max_broll_s=3.0, video_map="[v]", audio_map="[a]",
        ),
    ]
    for argv in commands:
        assert _after(argv, "-preset") == "veryfast"
        assert _after(argv, "-crf") == "21"
        assert _after(argv, "-g") == "60"


def test_transitions_stitch_no_longer_uses_the_medium_preset():
    from app.services.compose.transitions import _build_stitch_command

    argv = _build_stitch_command("ffmpeg", ["a.mp4", "b.mp4"], "o.mp4", "g", "[v]", "[a]")
    assert "medium" not in argv
    assert _after(argv, "-preset") == "veryfast"
    assert _after(argv, "-g") == "60"


def test_offline_loop_renderer_keeps_the_slow_preset():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "background-loops", "render-loops.mjs")
    text = open(root, encoding="utf-8").read()
    assert "'-preset', 'slow'" in text
    assert "'-g', String(FPS * 2)" in text


# --------------------------------------------------------------------------- #
# Pre-encoded loops
# --------------------------------------------------------------------------- #
def test_prepare_command_is_a_fixed_gop_1080x1920_encode():
    from app.services.loops.prepared import prepare_command

    argv = prepare_command("in.mp4", "out.mp4", 1080, 1920, preset="slow")
    assert "scale=1080:1920" in _after(argv, "-vf")
    assert _after(argv, "-g") == "60"
    assert _after(argv, "-keyint_min") == "60"
    assert _after(argv, "-sc_threshold") == "0"
    assert _after(argv, "-r") == "30"
    assert _after(argv, "-preset") == "slow"
    assert "-an" in argv


def test_concat_copy_never_encodes():
    from app.services.loops.prepared import concat_copy_command

    argv = concat_copy_command("list.txt", "mix.mp4")
    assert _after(argv, "-c") == "copy"
    assert "libx264" not in argv


def test_prepared_loop_caches_and_reuses(tmp_path):
    from app.services.loops import prepared

    src = tmp_path / "loop.mp4"
    src.write_bytes(b"source")
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(argv)
        with open(argv[-1], "wb") as handle:
            handle.write(b"prepared")
        return subprocess.CompletedProcess(argv, 0)

    first = prepared.prepared_loop(str(src), "540", ffmpeg="ffmpeg", runner=runner)
    second = prepared.prepared_loop(str(src), "540", ffmpeg="ffmpeg", runner=runner)
    assert first == second != str(src)
    assert prepared.is_prepared(first)
    assert len(calls) == 1
    assert "scale=540:960" in _after(calls[0], "-vf")
    # A prepared path is returned as-is (never prepared twice).
    assert prepared.prepared_loop(first, "1080", runner=runner) == first


def test_prepared_loop_falls_back_to_the_source_on_failure(tmp_path):
    from app.services.loops import prepared

    src = tmp_path / "loop.mp4"
    src.write_bytes(b"source")

    def runner(argv, **kwargs):
        raise subprocess.CalledProcessError(1, argv)

    assert prepared.prepared_loop(str(src), "1080", runner=runner) == str(src)
    assert prepared.prepared_loop(str(tmp_path / "missing.mp4")) == str(tmp_path / "missing.mp4")


def test_prepared_loop_rejects_unknown_tier(tmp_path):
    from app.services.loops import prepared

    src = tmp_path / "loop.mp4"
    src.write_bytes(b"source")
    assert prepared.prepared_loop(str(src), "4k") == str(src)


def test_every_packaged_loop_is_listed_for_prewarm():
    from app.services.loops.prepared import packaged_loops

    names = {os.path.basename(p) for p in packaged_loops()}
    assert {"block-runner.mp4", "sand-slice.mp4", "marble-run.mp4"} <= names


needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed"
)


@needs_ffmpeg
def test_real_prepared_loop_has_the_tier_size_fps_and_gop(tmp_path):
    from app.services.loops.prepared import prepared_loop

    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=s=720x1280:r=30:d=4", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", str(src)],
        check=True, timeout=120,
    )
    out = prepared_loop(str(src), "540", ffmpeg="ffmpeg")
    assert out != str(src)
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate:frame=key_frame,pts_time", "-of", "json", out],
        capture_output=True, text=True, check=True,
    ).stdout)
    stream = probe["streams"][0]
    assert (stream["width"], stream["height"], stream["r_frame_rate"]) == (540, 960, "30/1")
    keys = [round(float(f["pts_time"]), 2) for f in probe["frames"] if f.get("key_frame") == 1]
    assert keys == [0.0, 2.0]


def test_style_loop_mix_of_prepared_variants_is_a_stream_copy(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app.domains.content import background_library as bglib
    from app.services.loops import prepared
    from app.services.styles import pipeline

    clips = [SimpleNamespace(id=f"c{i}", needs_asset=False) for i in range(2)]
    monkeypatch.setattr(bglib, "variants_of", lambda _bg: clips)
    monkeypatch.setattr(bglib, "materialize", lambda clip, **_: [f"/src/{clip.id}.mp4"])
    monkeypatch.setattr(prepared, "prepared_loop", lambda src, *a, **k: f"/cache/{os.path.basename(src)}")
    monkeypatch.setattr(prepared, "is_prepared", lambda path: path.startswith("/cache/"))
    runs: list[list[str]] = []
    monkeypatch.setattr(pipeline.subprocess, "run", lambda argv, **kw: runs.append(argv))
    monkeypatch.setattr(pipeline, "_ffmpeg", lambda: "ffmpeg")

    out = pipeline._loop_path("block-runner", "job-1", 20.0, str(tmp_path))
    assert out.endswith("loop-mix.mp4")
    assert len(runs) == 1
    assert _after(runs[0], "-c") == "copy"
    assert "libx264" not in runs[0]
    listing = (tmp_path / "loop-mix.txt").read_text()
    assert listing.count("file '/cache/") == 3  # 20 s / 8 s segments


def test_style_loop_mix_reencodes_when_a_variant_is_not_prepared(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app.domains.content import background_library as bglib
    from app.services.loops import prepared
    from app.services.styles import pipeline

    clips = [SimpleNamespace(id=f"c{i}", needs_asset=False) for i in range(2)]
    monkeypatch.setattr(bglib, "variants_of", lambda _bg: clips)
    monkeypatch.setattr(bglib, "materialize", lambda clip, **_: [f"/src/{clip.id}.mp4"])
    monkeypatch.setattr(prepared, "prepared_loop", lambda src, *a, **k: src)
    runs: list[list[str]] = []
    monkeypatch.setattr(pipeline.subprocess, "run", lambda argv, **kw: runs.append(argv))
    monkeypatch.setattr(pipeline, "_ffmpeg", lambda: "ffmpeg")

    pipeline._loop_path("block-runner", "job-1", 10.0, str(tmp_path))
    assert "libx264" in runs[0]
