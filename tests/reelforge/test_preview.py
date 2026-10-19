"""Real-FFmpeg integration test for ReelForge poster + preview generation.

Like ``test_compose_integration.py`` this suite runs the ACTUAL FFmpeg binary
end to end: it synthesises a 1080x1920 vertical video with ``lavfi`` (with an
AAC audio track so the preview clip has something to stream-copy), then asserts
that ``app.services.preview`` produces a real, non-empty JPEG poster and a real,
short MP4 preview.

It auto-skips when FFmpeg / ffprobe is unavailable so a hermetic CI box without
a media stack is never broken.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from app.services import preview
from app.utils import utils

# --------------------------------------------------------------------------- #
# Availability gate
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg") or utils.get_ffmpeg_binary()
_FFPROBE = shutil.which("ffprobe")


def _have_media_stack() -> bool:
    if not _FFPROBE:
        return False
    if not _FFMPEG:
        return False
    try:
        result = subprocess.run(
            [_FFMPEG, "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _have_media_stack(),
    reason="ffmpeg/ffprobe not available",
)


# --------------------------------------------------------------------------- #
# lavfi input synthesis
# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "ffmpeg failed")


def _probe(path: str) -> dict:
    result = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def source_video(tmp_path_factory) -> str:
    """A ~4s 1080x1920 H.264 video with an AAC audio track."""
    d = tmp_path_factory.mktemp("preview_inputs")
    out = str(d / "final.mp4")
    _run(
        [
            _FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1920:rate=30:duration=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            out,
        ]
    )
    assert os.path.exists(out) and os.path.getsize(out) > 0
    return out


# --------------------------------------------------------------------------- #
# Poster
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_generate_poster_produces_real_jpeg(source_video, tmp_path):
    out_jpg = str(tmp_path / "poster.jpg")

    returned = preview.generate_poster(source_video, out_jpg, at_s=1.0, width=540)

    assert returned == out_jpg
    assert os.path.isfile(out_jpg) and os.path.getsize(out_jpg) > 0

    info = _probe(out_jpg)
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    assert vstreams, "poster must contain an image stream"
    v = vstreams[0]
    assert v["codec_name"] in {"mjpeg", "jpeg"}
    # Scaled to width=540, aspect-preserved height (9:16 -> 960).
    assert v["width"] == 540
    assert v["height"] == 960


@pytest.mark.integration
def test_generate_poster_native_resolution(source_video, tmp_path):
    out_jpg = str(tmp_path / "poster_full.jpg")

    preview.generate_poster(source_video, out_jpg, at_s=0.5, width=0)

    info = _probe(out_jpg)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (1080, 1920)


# --------------------------------------------------------------------------- #
# Preview clip
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_generate_preview_clip_produces_short_mp4(source_video, tmp_path):
    out_mp4 = str(tmp_path / "preview.mp4")

    returned = preview.generate_preview_clip(
        source_video, out_mp4, start_s=0.0, duration_s=3.0
    )

    assert returned == out_mp4
    assert os.path.isfile(out_mp4) and os.path.getsize(out_mp4) > 0

    info = _probe(out_mp4)
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    assert vstreams, "preview must contain a video stream"

    duration = float(info["format"]["duration"])
    # ~3s teaser (allow slack for keyframe-aligned copy and container rounding).
    assert 1.0 <= duration <= 5.0, f"unexpected preview duration {duration}s"


@pytest.mark.integration
def test_generate_preview_clip_clamps_long_duration(source_video, tmp_path):
    out_mp4 = str(tmp_path / "preview_clamped.mp4")

    # Ask for far more than the source has; clamp + short source => short clip.
    preview.generate_preview_clip(source_video, out_mp4, start_s=0.0, duration_s=999.0)

    info = _probe(out_mp4)
    duration = float(info["format"]["duration"])
    assert duration <= 5.0, f"preview should stay short, got {duration}s"


# --------------------------------------------------------------------------- #
# Error handling (no ffmpeg needed for these, but harmless under the gate)
# --------------------------------------------------------------------------- #
def test_missing_source_raises(tmp_path):
    missing = str(tmp_path / "does_not_exist.mp4")
    with pytest.raises(FileNotFoundError):
        preview.generate_poster(missing, str(tmp_path / "p.jpg"))
    with pytest.raises(FileNotFoundError):
        preview.generate_preview_clip(missing, str(tmp_path / "p.mp4"))


def test_invalid_duration_raises(source_video, tmp_path):
    with pytest.raises(ValueError):
        preview.generate_preview_clip(
            source_video, str(tmp_path / "p.mp4"), duration_s=0.0
        )
