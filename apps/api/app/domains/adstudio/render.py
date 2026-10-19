"""Local FFmpeg rendering of product ad videos (free, no provider).

Every segment is rendered as its own short H.264 clip from one product image:

1. the image is composited "contain" over a blurred, darkened "cover" copy of
   itself (clean framing for white-background product shots at any aspect);
2. an optional grade (``before`` = desaturated + dim, ``after`` = vivid);
3. camera motion via ``zoompan`` (zoom in/out, pan left/right);
4. an optional Pillow-rendered caption card faded in over the top.

Segments share codec parameters, so they are joined with the concat demuxer
without re-encoding, and a silent stereo AAC track is added (platforms reject
video without an audio stream; creators add a trending sound when posting).
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable

from app.domains.adstudio.cards import render_card
from app.domains.adstudio.variants import ASPECTS, Segment

FPS = 30
SEGMENT_TIMEOUT_S = 240
_MOTION_EXPR = {
    "zoom_in": ("1+0.10*on/{d}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "zoom_out": ("1.10-0.10*on/{d}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pan_right": ("1.10", "(iw-iw/zoom)*on/{d}", "ih/2-(ih/zoom/2)"),
    "pan_left": ("1.10", "(iw-iw/zoom)*(1-on/{d})", "ih/2-(ih/zoom/2)"),
}
_GRADES = {
    "before": "hue=s=0,eq=brightness=-0.06:contrast=0.92,",
    "after": "eq=saturation=1.25:contrast=1.04,",
    "normal": "",
}


class RenderError(RuntimeError):
    """A user-presentable render failure."""


def _ffmpeg() -> str:
    from app.utils import utils

    return utils.get_ffmpeg_binary()


def _run(cmd: list[str], timeout: int = SEGMENT_TIMEOUT_S) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RenderError("video rendering timed out") from exc
    except OSError as exc:
        raise RenderError("FFmpeg is not available on this server") from exc
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()[-3:]
        raise RenderError("video rendering failed: " + " | ".join(tail)[:400])


def _foreground_box(width: int, height: int) -> tuple[int, int, str]:
    if height > width:
        return int(width * 0.88), int(height * 0.5), f"(H-h)/2-{int(height * 0.12)}"
    return int(width * 0.9), int(height * 0.66), f"(H-h)/2-{int(height * 0.08)}"


def segment_filter(segment: Segment, width: int, height: int, has_card: bool) -> str:
    frames = max(1, round(segment.seconds * FPS))
    fg_w, fg_h, fg_y = _foreground_box(width, height)
    z, x, y = (part.format(d=frames) for part in _MOTION_EXPR.get(segment.motion, _MOTION_EXPR["zoom_in"]))
    grade = _GRADES.get(segment.grade, "")
    graph = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        f"boxblur=24:2,eq=brightness=-0.12[bg];"
        f"[0:v]scale={fg_w}:{fg_h}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:{fg_y},setsar=1[comp];"
        f"[comp]{grade}zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={FPS}[v]"
    )
    if has_card:
        graph += (
            ";[1:v]format=rgba,fade=t=in:st=0.12:d=0.3:alpha=1[cap];"
            "[v][cap]overlay=0:0:format=auto,format=yuv420p[out]"
        )
    else:
        graph += ";[v]format=yuv420p[out]"
    return graph


def render_segment(image_path: str, segment: Segment, width: int, height: int, out_path: str, work_dir: str, index: int) -> None:
    cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", image_path]
    has_card = segment.card is not None and bool(segment.card.text.strip())
    if has_card:
        card_path = os.path.join(work_dir, f"card-{index}.png")
        render_card(segment.card, width, height, card_path)  # type: ignore[arg-type]
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{segment.seconds:.3f}", "-i", card_path]
    cmd += [
        "-filter_complex", segment_filter(segment, width, height, has_card),
        "-map", "[out]", "-t", f"{segment.seconds:.3f}", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-an", out_path,
    ]
    _run(cmd)


def render_ad(
    image_paths: list[str],
    segments: list[Segment],
    aspect: str,
    out_path: str,
    work_dir: str,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> float:
    """Render ``segments`` into ``out_path``; returns the duration in seconds."""
    if not image_paths:
        raise RenderError("this product has no usable images to render")
    if not segments:
        raise RenderError("nothing to render for this ad")
    if aspect not in ASPECTS:
        raise RenderError(f"unsupported aspect ratio {aspect}")
    width, height = ASPECTS[aspect]
    clips: list[str] = []
    for index, segment in enumerate(segments):
        clip = os.path.join(work_dir, f"seg-{index:02d}.mp4")
        image = image_paths[segment.image_index % len(image_paths)]
        render_segment(image, segment, width, height, clip, work_dir, index)
        clips.append(clip)
        if progress is not None:
            progress(index + 1, len(segments))
    list_path = os.path.join(work_dir, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as handle:
        for clip in clips:
            handle.write(f"file '{clip}'\n")
    _run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k",
        "-shortest", "-movflags", "+faststart", out_path,
    ])
    return float(sum(s.seconds for s in segments))


def extract_poster(video_path: str, poster_path: str, at_s: float = 1.0) -> bool:
    try:
        _run([
            _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at_s:.2f}",
            "-i", video_path, "-frames:v", "1", "-q:v", "3", poster_path,
        ], timeout=60)
    except RenderError:
        return False
    return os.path.isfile(poster_path)


__all__ = ["RenderError", "extract_poster", "render_ad", "segment_filter"]
