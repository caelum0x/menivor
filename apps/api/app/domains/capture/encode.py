"""FFmpeg helpers for captures: browser WebM -> platform-ready H.264 MP4.

Playwright records VP8 WebM at the viewport size, starting when the browser
context opens (a blank page while the site loads). :func:`finalize_recording`
trims that lead-in, caps the duration, scales/pads to the exact output size at
30 fps and adds a silent AAC track (platforms reject video-only files; the reel
pipeline adds captions/voice later).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

FPS = 30
ENCODE_TIMEOUT_S = 600
OUTPUT_SIZES: dict[str, tuple[int, int]] = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}


class EncodeError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001 - no ffmpeg at all
        raise EncodeError("ffmpeg is not installed on this server") from exc


def _run(cmd: list[str], timeout: int = ENCODE_TIMEOUT_S) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise EncodeError("video encoding timed out") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()[-3:]
        raise EncodeError(f"ffmpeg failed: {' | '.join(tail)[:300]}")
    return proc


def probe_duration(path: str) -> float:
    """Container duration in seconds (0.0 when unknown)."""
    probe = shutil.which("ffprobe")
    if probe:
        try:
            proc = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                capture_output=True, timeout=60, check=False,
            )
            value = json.loads(proc.stdout or b"{}").get("format", {}).get("duration")
            return float(value) if value else 0.0
        except (ValueError, OSError, subprocess.TimeoutExpired):
            return 0.0
    return 0.0


def scale_filter(width: int, height: int) -> str:
    """Contain inside ``width x height`` on black, even dimensions, 30 fps."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS},format=yuv420p"
    )


def finalize_recording(src: str, out_path: str, aspect: str, *, trim_start: float, max_seconds: float) -> float:
    """Encode ``src`` to ``out_path``; returns the output duration in seconds."""
    if aspect not in OUTPUT_SIZES:
        raise EncodeError(f"unsupported aspect ratio {aspect}")
    if not os.path.isfile(src) or os.path.getsize(src) == 0:
        raise EncodeError("the browser produced no recording")
    width, height = OUTPUT_SIZES[aspect]
    cmd = [
        ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, trim_start):.2f}", "-i", src,
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", f"{max(1.0, max_seconds):.2f}",
        "-map", "0:v", "-map", "1:a",
        "-vf", scale_filter(width, height),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", out_path,
    ]
    _run(cmd)
    duration = probe_duration(out_path)
    if duration <= 0.0:
        duration = float(max_seconds)
    return duration


def trim_seconds(total: float, lead_in: float, wanted: float) -> tuple[float, float]:
    """Clamp (start, length) to what the recording actually contains."""
    start = max(0.0, min(lead_in, max(0.0, total - 1.0))) if total > 0 else max(0.0, lead_in)
    available = total - start if total > 0 else wanted
    return start, max(1.0, min(wanted, available))


__all__ = [
    "EncodeError",
    "OUTPUT_SIZES",
    "ffmpeg_bin",
    "finalize_recording",
    "probe_duration",
    "scale_filter",
    "trim_seconds",
]
