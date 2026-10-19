"""Real-FFmpeg integration anchor for the ReelForge compositor.

Unlike ``test_compose.py`` (which asserts on the filtergraph *strings* with a
monkeypatched ``subprocess``), this suite runs the ACTUAL FFmpeg binary end to
end: it synthesises a screen recording, a green-screen avatar clip and a
narration track with ``lavfi``, composes them through every layout, then probes
the real output with ``ffprobe``.

It is skipped automatically when FFmpeg (or the filters the graph needs) is not
available, so it never breaks a hermetic CI box that lacks a media stack — but
on any machine with a real FFmpeg it proves the chroma-key → circular PiP →
scale/crop-to-fill → overlay → H.264 encode path genuinely produces a
poster-ready 1080x1920 MP4.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from app.services.compose import compose_ffmpeg
from app.services.compose.compose_ffmpeg import (
    compose_avatar_over_screen,
    ffmpeg_has_filter,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Availability gate
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg") or utils.get_ffmpeg_binary()
_FFPROBE = shutil.which("ffprobe")
_REQUIRED_FILTERS = ("chromakey", "geq", "overlay", "scale", "crop", "vstack")


def _have_media_stack() -> bool:
    if not _FFMPEG or not _FFPROBE:
        return False
    return all(ffmpeg_has_filter(f, _FFMPEG) for f in _REQUIRED_FILTERS)


pytestmark = pytest.mark.skipif(
    not _have_media_stack(),
    reason="ffmpeg/ffprobe with the required filters not available",
)


# --------------------------------------------------------------------------- #
# lavfi input synthesis
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
    # Mostly green (chroma-keyable) with a moving non-green box so the keyer and
    # the circular alpha mask have real content to operate on.
    _run([
        _FFMPEG, "-y", "-f", "lavfi",
        "-i", f"color=c=0x00FF00:size=512x512:rate=30:duration={seconds}",
        "-vf", "drawbox=x=156:y=156:w=200:h=200:color=red@1.0:t=fill",
        "-pix_fmt", "yuv420p", path,
    ])


def _make_audio(path: str, seconds: float = 2.0) -> None:
    _run([
        _FFMPEG, "-y", "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={seconds}",
        "-c:a", "aac", "-b:a", "128k", path,
    ])


def _probe(path: str) -> dict:
    result = subprocess.run(
        [_FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def inputs(tmp_path_factory) -> dict:
    d = tmp_path_factory.mktemp("compose_inputs")
    screen = str(d / "screen.mp4")
    avatar = str(d / "avatar.mp4")
    audio = str(d / "audio.m4a")
    _make_screen(screen)
    # drawbox may be absent on a minimal build; fall back to plain green.
    try:
        _make_avatar(avatar)
    except RuntimeError:
        _run([
            _FFMPEG, "-y", "-f", "lavfi",
            "-i", "color=c=0x00FF00:size=512x512:rate=30:duration=2",
            "-pix_fmt", "yuv420p", avatar,
        ])
    _make_audio(audio)
    return {"screen": screen, "avatar": avatar, "audio": audio}


# --------------------------------------------------------------------------- #
# The anchor: every layout renders a real 1080x1920 H.264 MP4 with audio
# --------------------------------------------------------------------------- #
@pytest.mark.integration
@pytest.mark.parametrize("layout", ["pip", "hook_intro", "split"])
def test_layout_renders_real_portrait_video(inputs, tmp_path, layout):
    out = str(tmp_path / f"out_{layout}.mp4")

    returned = compose_avatar_over_screen(
        inputs["screen"], inputs["avatar"], inputs["audio"], out,
        layout=layout, ass_path=None, fps=30, threads=2,
    )
    assert returned == out
    assert os.path.exists(out) and os.path.getsize(out) > 0

    info = _probe(out)
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    astreams = [s for s in info["streams"] if s["codec_type"] == "audio"]

    assert vstreams, "no video stream in composed output"
    v = vstreams[0]
    assert (v["width"], v["height"]) == (1080, 1920), "output must be 1080x1920"
    assert v["codec_name"] == "h264"
    assert astreams, "narration audio must be muxed in"

    duration = float(info["format"]["duration"])
    assert 1.4 <= duration <= 3.2, f"unexpected duration {duration}s"


# --------------------------------------------------------------------------- #
# libass preflight: captions on a libass-less ffmpeg fail fast & clearly
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_caption_request_without_libass_fails_fast(inputs, tmp_path):
    # Build a REAL karaoke .ass with the production generator (a stub without
    # [V4+ Styles]/[Events] would make libass reject the track on its own).
    from app.services.captions.ass_karaoke import write_ass
    from app.services.tts.elevenlabs_timestamps import WordTiming

    ass = str(tmp_path / "cap.ass")
    line = [WordTiming("merhaba", 0.0, 0.6), WordTiming("dünya", 0.6, 1.2)]
    write_ass(ass, [line])
    out = str(tmp_path / "out_cap.mp4")

    if ffmpeg_has_filter("ass", _FFMPEG):
        # libass IS present: captions should burn and produce a real portrait video.
        compose_avatar_over_screen(
            inputs["screen"], inputs["avatar"], inputs["audio"], out,
            layout="pip", ass_path=ass,
        )
        v = [s for s in _probe(out)["streams"] if s["codec_type"] == "video"][0]
        assert (v["width"], v["height"]) == (1080, 1920)
    else:
        # libass ABSENT: must raise an actionable error, not a cryptic ffmpeg crash.
        with pytest.raises(RuntimeError, match="libass"):
            compose_avatar_over_screen(
                inputs["screen"], inputs["avatar"], inputs["audio"], out,
                layout="pip", ass_path=ass,
            )


def test_ffmpeg_has_filter_probe_is_truthful():
    # Positive control: a filter that exists on every build.
    assert ffmpeg_has_filter("scale", _FFMPEG) is True
    # Negative control: a filter that cannot exist.
    assert ffmpeg_has_filter("definitely_not_a_real_filter_zzz", _FFMPEG) is False
    # Cached probe must be self-consistent.
    assert compose_ffmpeg.ffmpeg_has_filter("scale", _FFMPEG) is True
