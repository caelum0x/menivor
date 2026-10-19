"""Pure-FFmpeg poster + short-preview generation for ReelForge (Creator Studio).

Given a finished 1080x1920 vertical video this module produces two lightweight
derivatives that the studio UI uses for gallery thumbnails and hover previews:

* ``generate_poster`` — extracts a single JPEG frame at a chosen timestamp
  (fast ``-ss`` input seek + ``-frames:v 1``), optionally scaled down so the
  thumbnail stays small while preserving the 9:16 aspect ratio.
* ``generate_preview_clip`` — cuts a short (~3-6s) MP4 out of the source. By
  default it stream-copies (``-c copy``) for speed; if the copy fails (e.g. the
  cut point is not on a keyframe and the player needs a clean clip) it falls
  back to a fast re-encode. Either way ``+faststart`` is applied so the clip
  streams progressively in a browser.

Reuses ``utils.get_ffmpeg_binary`` rather than assuming ``ffmpeg`` is on PATH,
runs FFmpeg with ``subprocess.run(check=False)`` and raises ``RuntimeError`` with
the captured stderr on failure. No moviepy, no external services.
"""

from __future__ import annotations

import os
import subprocess

from loguru import logger

from app.utils import utils

# --------------------------------------------------------------------------- #
# Tuning constants
# --------------------------------------------------------------------------- #
_DEFAULT_POSTER_WIDTH: int = 720  # scaled thumbnail width; height keeps aspect
_JPEG_QSCALE: str = "3"  # ffmpeg -q:v (2 best .. 31 worst); 3 = high quality
_PREVIEW_CRF: str = "23"  # x264 quality for the re-encode fallback
_PREVIEW_PRESET: str = "veryfast"
_PREVIEW_AUDIO_BITRATE: str = "128k"

# Preview clips are meant to be short teasers; clamp the caller-supplied range
# so a bad value can never produce a multi-minute "preview".
_MIN_PREVIEW_DURATION: float = 0.5
_MAX_PREVIEW_DURATION: float = 15.0


def _run_ffmpeg(cmd: list[str]) -> None:
    """Run an FFmpeg command, raising ``RuntimeError(stderr)`` on failure.

    ``subprocess.run`` is called with ``check=False`` so we control the error
    surface: a non-zero return code is turned into a ``RuntimeError`` carrying
    the captured stderr (falling back to stdout / a generic message).
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # ffmpeg binary missing entirely
        raise RuntimeError(f"ffmpeg binary not found: {exc}") from exc
    except OSError as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"failed to execute ffmpeg: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"ffmpeg exited with code {result.returncode}")


def _validate_source(video_path: str) -> None:
    """Fail fast with a clear error when the source video is unusable."""
    if not video_path:
        raise ValueError("video_path must be a non-empty path")
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"source video not found: {video_path}")
    if os.path.getsize(video_path) <= 0:
        raise ValueError(f"source video is empty: {video_path}")


def _ensure_parent_dir(out_path: str) -> None:
    """Create the destination directory tree if it does not already exist."""
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def generate_poster(
    video_path: str,
    out_jpg: str,
    at_s: float = 1.0,
    width: int = _DEFAULT_POSTER_WIDTH,
) -> str:
    """Extract a single poster/thumbnail JPEG frame from ``video_path``.

    Args:
        video_path: Path to the finished source video.
        out_jpg: Destination ``.jpg`` path (parent dirs are created).
        at_s: Timestamp (seconds) to grab the frame from. Negative values are
            clamped to ``0``; if the video is shorter than ``at_s`` FFmpeg
            returns the last frame, so this stays robust for tiny clips.
        width: Target scaled width in pixels. Height is derived to preserve the
            source aspect ratio (``-1`` → even value). ``width <= 0`` keeps the
            native resolution.

    Returns:
        The ``out_jpg`` path on success.

    Raises:
        FileNotFoundError / ValueError: invalid source.
        RuntimeError: FFmpeg failed (message is the captured stderr).
    """
    _validate_source(video_path)
    if not out_jpg:
        raise ValueError("out_jpg must be a non-empty path")
    _ensure_parent_dir(out_jpg)

    seek = max(0.0, float(at_s))
    ffmpeg = utils.get_ffmpeg_binary()

    cmd: list[str] = [
        ffmpeg,
        "-y",
        # Fast input seek: place -ss before -i so FFmpeg jumps by keyframe.
        "-ss",
        f"{seek:.3f}",
        "-i",
        video_path,
        "-frames:v",
        "1",
    ]

    if width and int(width) > 0:
        # scale=W:-2 keeps aspect ratio with an even height (required for many
        # encoders / consistent thumbnails).
        cmd += ["-vf", f"scale={int(width)}:-2"]

    cmd += [
        "-q:v",
        _JPEG_QSCALE,
        "-f",
        "image2",
        out_jpg,
    ]

    _run_ffmpeg(cmd)

    if not os.path.isfile(out_jpg) or os.path.getsize(out_jpg) <= 0:
        raise RuntimeError(f"poster frame was not produced: {out_jpg}")
    return out_jpg


def generate_preview_clip(
    video_path: str,
    out_mp4: str,
    start_s: float = 0.0,
    duration_s: float = 5.0,
    watermark_text: str | None = None,
) -> str:
    """Cut a short (~3-6s) preview MP4 out of ``video_path``.

    M3.3: the preview is the free export, so it carries the "Made with Menivor"
    watermark (:func:`app.services.share.free_watermark_text`; ``None`` means
    that default, ``""`` means none). A watermark forces the re-encode path.
    When FFmpeg has no ``drawtext`` filter or no font is found, the clip is cut
    without it and a warning is logged (previews never fail a job).

    First attempts a fast stream copy (``-c copy``). If that fails (a common
    outcome when the ``start_s`` seek does not land on a keyframe, yielding an
    unplayable clip) it transparently falls back to a fast H.264/AAC re-encode.
    ``+faststart`` is always applied so the clip plays progressively in a
    browser.

    Args:
        video_path: Path to the finished source video.
        out_mp4: Destination ``.mp4`` path (parent dirs are created).
        start_s: Start offset in seconds (clamped to ``>= 0``).
        duration_s: Clip length in seconds, clamped to
            ``[_MIN_PREVIEW_DURATION, _MAX_PREVIEW_DURATION]``.

    Returns:
        The ``out_mp4`` path on success.

    Raises:
        FileNotFoundError / ValueError: invalid source.
        RuntimeError: both the copy and the re-encode fallback failed.
    """
    _validate_source(video_path)
    if not out_mp4:
        raise ValueError("out_mp4 must be a non-empty path")
    _ensure_parent_dir(out_mp4)

    start = max(0.0, float(start_s))
    duration = float(duration_s)
    if duration <= 0:
        raise ValueError(f"duration_s must be positive, got {duration_s}")
    duration = min(_MAX_PREVIEW_DURATION, max(_MIN_PREVIEW_DURATION, duration))

    ffmpeg = utils.get_ffmpeg_binary()
    text = _free_watermark() if watermark_text is None else str(watermark_text)
    drawtext = _watermark_filter(text, out_mp4) if text else ""

    # Fast path: input-seek + stream copy. Placing -ss/-t before -i makes the
    # cut fast; -c copy avoids re-encoding entirely.
    copy_cmd: list[str] = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        video_path,
        "-c",
        "copy",
        "-map",
        "0",
        "-movflags",
        "+faststart",
        out_mp4,
    ]

    def _output_is_valid() -> bool:
        return os.path.isfile(out_mp4) and os.path.getsize(out_mp4) > 0

    if not drawtext:
        try:
            _run_ffmpeg(copy_cmd)
            if _output_is_valid():
                return out_mp4
        except RuntimeError:
            # Fall through to the re-encode path below.
            pass

    # Fallback: re-encode. Accurate seek via output-side -ss (after -i) so the
    # clip starts cleanly even when the source lacks a nearby keyframe.
    encode_cmd: list[str] = [
        ffmpeg,
        "-y",
        "-i",
        video_path,
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        *(["-vf", drawtext] if drawtext else []),
        "-c:v",
        "libx264",
        "-preset",
        _PREVIEW_PRESET,
        "-crf",
        _PREVIEW_CRF,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        _PREVIEW_AUDIO_BITRATE,
        "-movflags",
        "+faststart",
        out_mp4,
    ]

    _run_ffmpeg(encode_cmd)

    if not _output_is_valid():
        raise RuntimeError(f"preview clip was not produced: {out_mp4}")
    return out_mp4


def _free_watermark() -> str:
    try:
        from app.services.share import free_watermark_text

        return free_watermark_text()
    except Exception as exc:  # noqa: BLE001 - the watermark never fails a preview
        logger.warning(f"free watermark text unavailable: {exc}")
        return ""


def _watermark_font() -> str | None:
    try:
        font_root = utils.font_dir()
        for name in ("Inter-Bold.ttf", "Montserrat-ExtraBold.ttf", "BeVietnamPro-Bold.ttf"):
            candidate = os.path.join(font_root, name)
            if os.path.isfile(candidate):
                return candidate
        for entry in sorted(os.listdir(font_root)):
            if entry.lower().endswith(".ttf"):
                return os.path.join(font_root, entry)
    except Exception:  # noqa: BLE001 - font resolution is best-effort
        return None
    return None


def _has_drawtext() -> bool:
    try:
        from app.services.compose.compose_ffmpeg import ffmpeg_has_filter

        return ffmpeg_has_filter("drawtext")
    except Exception:  # noqa: BLE001
        return False


def _watermark_filter(text: str, out_mp4: str) -> str:
    """A bottom-centre ``drawtext`` filter for ``text`` (``""`` when it cannot run).

    The text goes through a file next to the output, so no filter escaping of
    the text itself is needed.
    """
    font = _watermark_font()
    if not font or not _has_drawtext():
        logger.warning("free watermark skipped: no drawtext filter or font")
        return ""
    textfile = f"{out_mp4}.watermark.txt"
    with open(textfile, "w", encoding="utf-8") as fh:
        fh.write(text)

    def esc(path: str) -> str:
        return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    return (
        f"drawtext=textfile='{esc(textfile)}':fontfile='{esc(font)}':"
        "fontcolor=white@0.9:fontsize=h/30:x=(w-text_w)/2:y=h-text_h-h/14:"
        "box=1:boxcolor=black@0.35:boxborderw=10"
    )
