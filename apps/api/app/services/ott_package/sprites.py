"""Trick-play thumbnails (MV3): one sprite sheet plus a WebVTT index for the scrub bar."""

from __future__ import annotations

import math

THUMB_W, THUMB_H = 160, 90
EVERY_S = 5
COLUMNS = 10


def _ts(seconds: float) -> str:
    h, rem = divmod(max(0.0, seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def sprite_command(ffmpeg: str, src: str, out: str, seconds: float, *, vertical: bool = False) -> list[str]:
    count = max(1, math.ceil(seconds / EVERY_S))
    rows = max(1, math.ceil(count / COLUMNS))
    w, h = (THUMB_H, THUMB_W) if vertical else (THUMB_W, THUMB_H)
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-vf",
            f"fps=1/{EVERY_S},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"tile={COLUMNS}x{rows}", "-frames:v", "1", "-q:v", "4", out]


def sprite_vtt(seconds: float, image_name: str, *, vertical: bool = False) -> str:
    w, h = (THUMB_H, THUMB_W) if vertical else (THUMB_W, THUMB_H)
    lines = ["WEBVTT", ""]
    for i in range(max(1, math.ceil(seconds / EVERY_S))):
        start, end = i * EVERY_S, min(seconds, (i + 1) * EVERY_S)
        x, y = (i % COLUMNS) * w, (i // COLUMNS) * h
        lines += [f"{_ts(start)} --> {_ts(end)}", f"{image_name}#xywh={x},{y},{w},{h}", ""]
    return "\n".join(lines)


__all__ = ["EVERY_S", "sprite_command", "sprite_vtt"]
