"""Real-FFmpeg integration anchor for the ReelForge brand-watermark overlay.

Companion to ``test_compose.py`` (which asserts on the filtergraph *strings* with
a monkeypatched ``subprocess``): this suite drives the ACTUAL FFmpeg binary end
to end. It synthesises a screen recording, a green-screen avatar clip, a
narration track and a solid PNG logo with ``lavfi``, composes them once WITHOUT
and once WITH the brand watermark, then:

  * probes the watermarked output and asserts it is still a 1080x1920 H.264 MP4, and
  * samples the logo corner region of both renders and asserts the watermarked
    render's corner genuinely DIFFERS from the un-watermarked one (the logo was
    actually stamped on top).

Skipped automatically when FFmpeg / ffprobe / the required filters are missing,
so it never breaks a hermetic CI box that lacks a media stack.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.services.compose.compose_ffmpeg import (
    _WATERMARK_MARGIN,
    _WATERMARK_REF_WIDTH,
    _WATERMARK_SCALE,
    _watermark_logo_width,
    compose_avatar_over_screen,
    ffmpeg_has_filter,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Availability gate
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg") or utils.get_ffmpeg_binary()
_FFPROBE = shutil.which("ffprobe")
_REQUIRED_FILTERS = (
    "chromakey",
    "geq",
    "overlay",
    "scale",
    "crop",
    "format",
    "colorchannelmixer",
)


def _have_media_stack() -> bool:
    if not _FFMPEG or not _FFPROBE:
        return False
    return all(ffmpeg_has_filter(f, _FFMPEG) for f in _REQUIRED_FILTERS)


pytestmark = pytest.mark.skipif(
    not _have_media_stack(),
    reason="ffmpeg/ffprobe with the required filters not available",
)


# --------------------------------------------------------------------------- #
# lavfi / logo input synthesis
# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "ffmpeg failed")


def _make_screen(path: str, seconds: float = 2.0) -> None:
    _run([
        _FFMPEG, "-y", "-f", "lavfi",
        "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds}",
        "-pix_fmt", "yuv420p", path,
    ])


def _make_avatar(path: str, seconds: float = 2.0) -> None:
    _run([
        _FFMPEG, "-y", "-f", "lavfi",
        "-i", f"color=c=0x00FF00:size=512x512:rate=30:duration={seconds}",
        "-pix_fmt", "yuv420p", path,
    ])


def _make_audio(path: str, seconds: float = 2.0) -> None:
    _run([
        _FFMPEG, "-y", "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={seconds}",
        "-c:a", "aac", "-b:a", "128k", path,
    ])


def _make_logo(path: str) -> None:
    # A solid magenta square PNG stands in for a brand logo. Magenta (high R+B,
    # low G) is nowhere in the testsrc2 corner, so the overlay is unambiguous.
    _run([
        _FFMPEG, "-y", "-f", "lavfi",
        "-i", "color=c=magenta:size=300x300:duration=0.1",
        "-frames:v", "1", path,
    ])


def _probe(path: str) -> dict:
    result = subprocess.run(
        [_FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _region_rgb_mean(
    path: str, x: int, y: int, w: int, h: int
) -> tuple[float, float, float]:
    """Mean (R, G, B) of a ``w`` x ``h`` crop at ``(x, y)`` from ``path``'s frame.

    ffmpeg may snap an odd crop size to the even chroma grid, so the mean is
    computed over whatever complete RGB pixels the crop actually yields rather
    than an assumed exact byte count.
    """
    result = subprocess.run(
        [
            _FFMPEG, "-v", "error", "-i", path,
            "-vf", f"crop={w}:{h}:{x}:{y}",
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ],
        capture_output=True, check=False,
    )
    data = result.stdout
    n = len(data) // 3
    assert n > 0, f"empty raw frame for crop {w}x{h}+{x}+{y} of {path!r}"
    sums = [0, 0, 0]
    for i in range(n):
        base = i * 3
        sums[0] += data[base]
        sums[1] += data[base + 1]
        sums[2] += data[base + 2]
    return sums[0] / n, sums[1] / n, sums[2] / n


@pytest.fixture(scope="module")
def inputs(tmp_path_factory) -> dict:
    d = tmp_path_factory.mktemp("watermark_inputs")
    screen = str(d / "screen.mp4")
    avatar = str(d / "avatar.mp4")
    audio = str(d / "audio.m4a")
    logo = str(d / "logo.png")
    _make_screen(screen)
    _make_avatar(avatar)
    _make_audio(audio)
    _make_logo(logo)
    return {"screen": screen, "avatar": avatar, "audio": audio, "logo": logo}


# --------------------------------------------------------------------------- #
# The anchor: the watermark renders and actually changes the logo corner
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_watermark_renders_and_changes_corner(inputs, tmp_path):
    plain = str(tmp_path / "plain.mp4")
    marked = str(tmp_path / "marked.mp4")

    compose_avatar_over_screen(
        inputs["screen"], inputs["avatar"], inputs["audio"], plain,
        layout="pip", fps=30, threads=2,
    )
    compose_avatar_over_screen(
        inputs["screen"], inputs["avatar"], inputs["audio"], marked,
        layout="pip", fps=30, threads=2,
        watermark_path=inputs["logo"], watermark_position="bottom_right",
        watermark_opacity=0.85, watermark_scale=_WATERMARK_SCALE,
        watermark_margin=_WATERMARK_MARGIN,
    )

    # Watermarked output is still a poster-ready 1080x1920 H.264 MP4.
    info = _probe(marked)
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    assert vstreams, "no video stream in watermarked output"
    v = vstreams[0]
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["codec_name"] == "h264"

    # Sample an even region well inside the bottom-right logo (square logo =>
    # w == h). Even dims sidestep ffmpeg snapping an odd crop to the chroma grid.
    size = _watermark_logo_width(_WATERMARK_SCALE, _WATERMARK_REF_WIDTH)
    sample = 120
    x = 1080 - size - _WATERMARK_MARGIN + 20
    y = 1920 - size - _WATERMARK_MARGIN + 20

    plain_mean = _region_rgb_mean(plain, x, y, sample, sample)
    marked_mean = _region_rgb_mean(marked, x, y, sample, sample)

    # The magenta logo pushes the corner strongly toward high R+B / low G, so the
    # per-channel means must differ well beyond any codec noise.
    delta = sum(abs(a - b) for a, b in zip(plain_mean, marked_mean))
    assert delta > 30.0, (
        f"logo corner unchanged: plain={plain_mean} marked={marked_mean} "
        f"delta={delta}"
    )


@pytest.mark.integration
def test_watermark_center_position_renders_portrait(inputs, tmp_path):
    out = str(tmp_path / "center.mp4")
    compose_avatar_over_screen(
        inputs["screen"], inputs["avatar"], inputs["audio"], out,
        layout="split", watermark_path=inputs["logo"],
        watermark_position="center", watermark_opacity=0.5,
    )
    v = [s for s in _probe(out)["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["codec_name"] == "h264"


@pytest.mark.integration
def test_watermark_invalid_position_rejected_before_ffmpeg(inputs, tmp_path):
    out = str(tmp_path / "bad.mp4")
    with pytest.raises(ValueError, match="watermark position"):
        compose_avatar_over_screen(
            inputs["screen"], inputs["avatar"], inputs["audio"], out,
            layout="pip", watermark_path=inputs["logo"],
            watermark_position="somewhere",
        )
