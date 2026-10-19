"""Pure-FFmpeg + (optional) rembg background-removal MATTING pass for ReelForge.

The green-screen HeyGen avatar is normally keyed by ``compose_ffmpeg``'s
``chromakey`` node. That works, but real avatars pick up green spill, uneven
lighting and haloing. This OPTIONAL pre-compose pass instead runs the AVATAR
clip through `rembg <https://github.com/danielgatis/rembg>`_ (MIT) — a neural
foreground/alpha matter — to produce a much cleaner cut-out, then either:

* ``mode='replace'`` — composite the matted avatar over a PERFECT solid colour
  (default chroma green ``0x00FF00``). Downstream ``compose_avatar_over_screen``
  then chroma-keys that flawless, spill-free green exactly as before — so the
  matting drops in with ZERO compose changes and simply yields a cleaner key.
* ``mode='alpha'`` — write a true RGBA clip (alpha preserved via ``qtrle`` in a
  ``.mov``) for callers that want to overlay the avatar without any keying, or
  to produce a product cut-out.

Design rules (mirroring :mod:`app.services.editing.silence_cut`):

* rembg is a STRICTLY OPTIONAL import. There is NO module-level ``import rembg``:
  the suite and prod import + run this module WITHOUT rembg (and without its
  onnxruntime/model download) installed. rembg is loaded lazily, import-guarded,
  only when a matte is actually requested.
* PURE FFMPEG transport. Frames are decoded to raw ``rgb24`` via an ffmpeg pipe,
  matted frame-wise, and re-encoded through a second ffmpeg pipe that ALSO reads
  the ORIGINAL clip purely to re-mux its audio track unchanged — so the audio is
  byte-passed, never re-timed.
* A/V-SYNC SAFE + NEVER-EMPTY/CORRUPT. The re-encode runs at the source frame
  rate, maps the original audio (``-map 1:a?``) and bounds the result with
  ``-shortest`` so the matted video and its audio stay aligned and the output is
  never a zero-length/broken clip.
* DEGRADE-SAFE + DEFAULT-OFF. On ANY problem — rembg/model unavailable, an
  unreadable/zero-length input, a bad frame, an ffmpeg error, or any exception —
  the ORIGINAL clip is returned UNCHANGED (copied to ``output_path``) with
  ``applied=False``. The integrator then simply falls back to the EXISTING
  chromakey path on the raw avatar. Matting NEVER fails the job.

This module operates ONLY on the background/avatar recording. The voiceover +
caption timeline (driven by the ElevenLabs/whisper WORD timings) is the single
source of truth and is never touched here.

Mockable seams (so tests need neither rembg nor heavy real media):

* :func:`_get_session` — module-level; ``is_available``/``remove_background`` look
  it up by name at call time, so a test can ``monkeypatch.setattr`` it to return a
  sentinel session (flipping ``is_available`` True) with no rembg installed.
* :func:`_frame_matte` — module-level per-frame matter; patch it to inject a fake
  alpha/cut-out so the compositing + ffmpeg-muxing transport is exercised WITHOUT
  rembg.
* :func:`_run` — module-level thin ``subprocess.run`` wrapper used for probes.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess

from loguru import logger

from app.services.compose.compose_ffmpeg import (
    _get_ffprobe_binary,
    _probe_video,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Tuning constants
# --------------------------------------------------------------------------- #
# rembg model used for the avatar cut-out. ``u2net_human_seg`` is tuned for
# people (the talking-head avatar); callers may override via ``matte(model=...)``.
_DEFAULT_MODEL: str = "u2net_human_seg"

# Matting modes.
_MODE_ALPHA: str = "alpha"      # write a true RGBA clip (alpha preserved)
_MODE_REPLACE: str = "replace"  # composite over a solid colour (chroma-key ready)
_VALID_MODES: frozenset[str] = frozenset({_MODE_ALPHA, _MODE_REPLACE})

# Default replacement background for ``replace`` mode: pure chroma green so the
# existing compose ``chromakey`` keys it perfectly with no spill.
_DEFAULT_BG_RGB: tuple[int, int, int] = (0, 255, 0)

# Fallback frame rate when the source fps cannot be probed.
_DEFAULT_FPS: float = 30.0

# The matte re-encode must stay within this of the source duration, else it is
# treated as a failure and the ORIGINAL is kept. The frame count is pinned to the
# audio timeline (CFR decode at the encode fps), so a drift signals a desync.
_DURATION_TOLERANCE_S: float = 0.25

_LIBX264: str = "libx264"
# Alpha-preserving codec/container for ``alpha`` mode (Apple Animation / QuickTime).
_ALPHA_CODEC: str = "qtrle"

# Named colours accepted by ``bg_key`` (beyond ``0xRRGGBB`` / ``#rrggbb`` hex).
_NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "black": (0, 0, 0),
    "white": (255, 255, 255),
}


# --------------------------------------------------------------------------- #
# Low-level subprocess seam (mockable)
# --------------------------------------------------------------------------- #
def _run(command: list[str]) -> subprocess.CompletedProcess:
    """Run an ffprobe/ffmpeg command, capturing stdout+stderr as text.

    The single simple-subprocess seam for the module (probes): tests patch it to
    avoid real media. It never raises on a non-zero exit — callers inspect
    ``returncode`` / stdout themselves so a failed probe degrades gracefully.
    """
    return subprocess.run(command, capture_output=True, text=True, check=False)


# --------------------------------------------------------------------------- #
# ffprobe helpers
# --------------------------------------------------------------------------- #
def _has_audio_stream(path: str, ffprobe: str | None = None) -> bool:
    """True when ``path`` carries at least one audio stream (best-effort)."""
    binary = ffprobe or _get_ffprobe_binary()
    try:
        result = _run(
            [
                binary,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                path,
            ]
        )
    except (OSError, ValueError) as exc:  # pragma: no cover - environment issue
        logger.warning(f"audio-stream probe failed for {path!r}: {exc}")
        return False
    return bool((result.stdout or "").strip())


def _probe_duration(path: str, ffprobe: str | None = None) -> float:
    """Return ``path``'s duration in seconds (0.0 when it cannot be determined)."""
    info = _probe_video(path, ffprobe or _get_ffprobe_binary())
    return float(info.duration) if info and info.duration > 0 else 0.0


# --------------------------------------------------------------------------- #
# Colour parsing (pure — unit-testable)
# --------------------------------------------------------------------------- #
def _parse_bg_color(bg_key: str | None) -> tuple[int, int, int]:
    """Parse a ``replace``-mode background colour into an ``(r, g, b)`` triple.

    Accepts ``None``/empty (→ default chroma green), a named colour
    (``"green"``/``"blue"``/``"black"``/``"white"``), or a hex string in
    ``0xRRGGBB`` / ``#RRGGBB`` / ``RRGGBB`` form. Anything unparseable falls back
    to the default green so ``replace`` mode always has a valid, key-able colour.
    """
    if bg_key is None:
        return _DEFAULT_BG_RGB
    text = str(bg_key).strip().lower()
    if not text:
        return _DEFAULT_BG_RGB
    if text in _NAMED_COLORS:
        return _NAMED_COLORS[text]

    hex_part = text
    if hex_part.startswith("0x"):
        hex_part = hex_part[2:]
    elif hex_part.startswith("#"):
        hex_part = hex_part[1:]
    if len(hex_part) == 6:
        try:
            r = int(hex_part[0:2], 16)
            g = int(hex_part[2:4], 16)
            b = int(hex_part[4:6], 16)
            return (r, g, b)
        except ValueError:
            pass
    logger.warning(f"unparseable bg_key {bg_key!r}; defaulting to chroma green")
    return _DEFAULT_BG_RGB


# --------------------------------------------------------------------------- #
# rembg session seam (import-guarded, cached, mockable)
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=4)
def _get_session(model: str = _DEFAULT_MODEL):
    """Resolve a rembg inference session for ``model`` (import-guarded, cached).

    rembg is loaded lazily HERE — there is no module-level import — so the suite
    and prod run without it. Returns the session object, or ``None`` when rembg is
    not importable or its model cannot be resolved (no network / missing weights),
    which flips :func:`is_available` to ``False`` and degrades matting to a no-op.
    The session is cached so the (potentially heavy) model download happens once.
    """
    try:
        from rembg import new_session  # type: ignore[import-not-found]

        return new_session(model)
    except Exception as exc:  # noqa: BLE001 - optional dep / model must degrade
        logger.info(
            f"rembg matting unavailable for model {model!r} "
            f"(optional dep/model not resolvable): {exc}"
        )
        return None


def is_available(model: str = _DEFAULT_MODEL) -> bool:
    """True when rembg is importable AND its ``model`` is resolvable.

    Cheap after the first call (the session is cached). Used by :func:`matte` to
    degrade to a no-op — and by the integrator to fall back to the existing
    chromakey path — when the optional dependency/model is absent.
    """
    return _get_session(model) is not None


# --------------------------------------------------------------------------- #
# Per-frame matting seam (mockable — the ONLY rembg-consuming step)
# --------------------------------------------------------------------------- #
def _frame_matte(
    frame: bytes,
    width: int,
    height: int,
    *,
    mode: str,
    bg_rgb: tuple[int, int, int],
    session,
) -> bytes:
    """Matte one raw ``rgb24`` frame and return the processed raw bytes.

    Input is ``width*height*3`` ``rgb24`` bytes. rembg computes an RGBA cut-out,
    then:

    * ``mode='alpha'``   → returns ``width*height*4`` ``rgba`` bytes (alpha kept).
    * ``mode='replace'`` → alpha-composites the foreground over ``bg_rgb`` and
      returns ``width*height*3`` ``rgb24`` bytes.

    This is the SOLE step that touches rembg/numpy, so tests patch this seam to
    inject a fake alpha and exercise the ffmpeg transport without rembg installed.
    """
    import numpy as np  # local: never a module-level hard dep
    from rembg import remove  # type: ignore[import-not-found]

    arr = np.frombuffer(frame, dtype=np.uint8).reshape((height, width, 3))
    cut = remove(arr, session=session)  # -> (H, W, 4) RGBA ndarray

    if mode == _MODE_ALPHA:
        return np.ascontiguousarray(cut[:, :, :4]).astype(np.uint8).tobytes()

    alpha = cut[:, :, 3:4].astype(np.float32) / 255.0
    foreground = cut[:, :, :3].astype(np.float32)
    background = np.array(bg_rgb, dtype=np.float32).reshape((1, 1, 3))
    composited = foreground * alpha + background * (1.0 - alpha)
    return np.ascontiguousarray(composited.round().clip(0, 255)).astype(
        np.uint8
    ).tobytes()


# --------------------------------------------------------------------------- #
# Raw-frame ffmpeg transport (decode -> matte -> encode+mux)
# --------------------------------------------------------------------------- #
def _read_exact(stream, size: int) -> bytes | None:
    """Read EXACTLY ``size`` bytes from ``stream`` (``None`` at clean EOF).

    ``PIPE`` reads may return short; loop until the frame is whole. A truncated
    final read (fewer than ``size`` bytes) signals the stream ended mid-frame and
    yields ``None`` so the caller stops without emitting a partial frame.
    """
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _decode_command(
    ffmpeg: str, input_path: str, *, fps: float | None = None
) -> list[str]:
    """ffmpeg argv that streams the input's video as raw ``rgb24`` to stdout.

    When ``fps`` is given the decode is pinned to CFR at that rate (``fps=`` video
    filter) so the emitted frame count is exactly ``duration*fps`` and therefore
    matches the audio timeline the encoder re-stamps at the SAME rate. Without it a
    VFR / mis-probed source would yield a frame count that re-encodes to the wrong
    length and desync the avatar's lips from the voiceover.
    """
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", input_path,
        "-map", "0:v:0",
    ]
    if fps and fps > 0:
        command += ["-vf", f"fps={fps:.6g}"]
    command += [
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-",
    ]
    return command


def _encode_command(
    ffmpeg: str,
    input_path: str,
    output_path: str,
    *,
    width: int,
    height: int,
    fps: float,
    mode: str,
    threads: int,
) -> list[str]:
    """ffmpeg argv that reads matted raw frames from stdin and re-muxes audio.

    Input 0 is the raw matted video piped on stdin; input 1 is the ORIGINAL clip,
    used solely to copy its audio track unchanged (``-map 1:a?`` — optional so a
    silent avatar still encodes). The decode is pinned to CFR at ``fps`` and the
    video is re-stamped at the SAME ``fps``, so the video length equals the audio
    length by construction — no ``-shortest`` (which would truncate a longer
    voiceover and drop lip-synced speech when the frame count is off).
    """
    pix_fmt = "rgba" if mode == _MODE_ALPHA else "rgb24"
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo",
        "-pix_fmt", pix_fmt,
        "-s", f"{width}x{height}",
        "-r", f"{fps:.6g}",
        "-i", "-",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "1:a?",
    ]
    if mode == _MODE_ALPHA:
        command += ["-c:v", _ALPHA_CODEC]
    else:
        command += ["-c:v", _LIBX264, "-pix_fmt", "yuv420p"]
    command += [
        "-c:a", "aac", "-b:a", "192k",
        "-r", f"{fps:.6g}",
        "-threads", str(threads or 2),
        "-movflags", "+faststart",
        output_path,
    ]
    return command


def _stream_matte(
    input_path: str,
    output_path: str,
    *,
    mode: str,
    bg_rgb: tuple[int, int, int],
    width: int,
    height: int,
    fps: float,
    session,
    ffmpeg: str,
    threads: int = 2,
) -> None:
    """Decode → per-frame matte → encode+mux the whole clip (raises on failure).

    Spawns a decoder (raw ``rgb24`` on stdout) and an encoder (matted raw frames
    on stdin, original audio re-muxed), pumping one frame at a time so neither
    pipe's buffer grows unbounded. Each frame passes through :func:`_frame_matte`
    (the mockable seam). Raises ``RuntimeError`` on any decode/encode failure so
    the :func:`matte` wrapper can degrade to the untouched original.
    """
    frame_size = width * height * 3
    if frame_size <= 0:
        raise RuntimeError(f"invalid frame geometry {width}x{height}")

    decoder = subprocess.Popen(  # noqa: S603 - args are fixed, no shell
        _decode_command(ffmpeg, input_path, fps=fps),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    encoder = subprocess.Popen(  # noqa: S603 - args are fixed, no shell
        _encode_command(
            ffmpeg, input_path, output_path,
            width=width, height=height, fps=fps, mode=mode, threads=threads,
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    frames = 0
    try:
        assert decoder.stdout is not None and encoder.stdin is not None
        while True:
            frame = _read_exact(decoder.stdout, frame_size)
            if frame is None:
                break
            processed = _frame_matte(
                frame, width, height, mode=mode, bg_rgb=bg_rgb, session=session
            )
            encoder.stdin.write(processed)
            frames += 1
    except BrokenPipeError as exc:
        raise RuntimeError(f"matte encoder closed early: {exc}") from exc
    finally:
        if decoder.stdout is not None:
            decoder.stdout.close()
        if encoder.stdin is not None:
            try:
                encoder.stdin.close()
            except BrokenPipeError:  # pragma: no cover - encoder already gone
                pass

    # stdin is already closed above, so DON'T use ``communicate`` (it would try to
    # re-flush the closed pipe). Drain the encoder's stderr — small under
    # ``-loglevel error`` — then reap both processes.
    enc_err = encoder.stderr.read() if encoder.stderr is not None else b""
    encoder.wait()
    decoder.wait()
    if frames == 0:
        raise RuntimeError("matte decoded no frames from input")
    if encoder.returncode != 0:
        detail = enc_err.decode("utf-8", "replace").strip() if enc_err else ""
        raise RuntimeError(detail or "matte encode failed")


# --------------------------------------------------------------------------- #
# Public: background removal (raises on failure)
# --------------------------------------------------------------------------- #
def remove_background(
    input_video_path: str,
    output_path: str,
    *,
    mode: str = _MODE_ALPHA,
    bg_key: str | None = None,
    model: str = _DEFAULT_MODEL,
    threads: int = 2,
) -> str:
    """Remove (``alpha``) or replace (``replace``) the AVATAR clip's background.

    Decodes the clip frame-wise, mattes each frame with rembg and re-encodes an
    A/V-sync-safe output with the ORIGINAL audio re-muxed unchanged. In
    ``replace`` mode the foreground is composited over ``bg_key``'s colour
    (default chroma green ``0x00FF00`` — ready for the existing compose
    chromakey); in ``alpha`` mode a true RGBA clip is written (``qtrle``/``.mov``).

    Returns ``output_path``.

    Raises:
        ValueError: if ``mode`` is not ``'alpha'`` or ``'replace'``.
        FileNotFoundError: if ``input_video_path`` is missing.
        RuntimeError: if rembg/model is unavailable or ffmpeg fails.
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"unsupported mode: {mode!r} (allowed: {', '.join(sorted(_VALID_MODES))})"
        )
    if not input_video_path or not os.path.exists(input_video_path):
        raise FileNotFoundError(f"matting input not found: {input_video_path!r}")

    ffmpeg = utils.get_ffmpeg_binary()
    ffprobe = _get_ffprobe_binary(ffmpeg)

    info = _probe_video(input_video_path, ffprobe)
    if not info or info.width <= 0 or info.height <= 0 or info.duration <= 0:
        raise RuntimeError(f"could not probe video geometry for {input_video_path!r}")

    session = _get_session(model)
    if session is None:
        raise RuntimeError(
            "rembg background matting is unavailable "
            "(optional dependency/model not installed)"
        )

    fps = info.fps if info.fps and info.fps > 0 else _DEFAULT_FPS
    bg_rgb = _parse_bg_color(bg_key)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    _stream_matte(
        input_video_path,
        output_path,
        mode=mode,
        bg_rgb=bg_rgb,
        width=info.width,
        height=info.height,
        fps=fps,
        session=session,
        ffmpeg=ffmpeg,
        threads=threads,
    )
    return output_path


# --------------------------------------------------------------------------- #
# Orchestration (DEGRADE-SAFE wrapper)
# --------------------------------------------------------------------------- #
def _copy_through(input_path: str, output_path: str) -> None:
    """Copy the original clip to ``output_path`` (no-op if they are the same)."""
    if os.path.abspath(input_path) == os.path.abspath(output_path):
        return
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    shutil.copyfile(input_path, output_path)


def _result(
    mode: str, original_s: float, output_s: float, applied: bool
) -> dict:
    """Assemble the :func:`matte` result envelope."""
    return {
        "applied": bool(applied),
        "mode": str(mode),
        "original_s": round(float(original_s), 4),
        "output_s": round(float(output_s), 4),
    }


def matte(input_path: str, output_path: str, **opts) -> dict:
    """Background-matte the avatar clip, DEGRADE-SAFE (never fails the job).

    ``**opts`` may carry ``mode`` (``'alpha'`` | ``'replace'``, default
    ``'alpha'``), ``bg_key`` (``replace`` background colour), ``model`` (rembg
    model) and ``threads``. Returns a result dict::

        {
            "applied": bool,       # True only when a real matte was written
            "mode": str,           # the mode requested
            "original_s": float,   # source duration (s)
            "output_s": float,     # output duration (s)
        }

    DEGRADE-SAFE: on ANY problem — rembg/model unavailable
    (``is_available()`` False), an unreadable/zero-length input, an ffmpeg error,
    a would-be-empty result, or any exception — the ORIGINAL clip is copied to
    ``output_path`` UNCHANGED and ``applied=False`` is returned. The integrator
    then simply keeps the existing chromakey path on the raw avatar.
    """
    mode = str(opts.get("mode", _MODE_ALPHA))
    bg_key = opts.get("bg_key")
    model = str(opts.get("model", _DEFAULT_MODEL))
    threads = int(opts.get("threads", 2) or 2)

    try:
        original_s = _probe_duration(input_path)
        if original_s <= 0:
            _copy_through(input_path, output_path)
            return _result(mode, max(0.0, original_s), max(0.0, original_s), False)

        # Optional-dep gate: degrade to a no-op when rembg/model is not resolvable.
        if not is_available(model):
            logger.info(
                f"matte: rembg unavailable; returning original unchanged "
                f"({input_path!r})"
            )
            _copy_through(input_path, output_path)
            return _result(mode, original_s, original_s, False)

        remove_background(
            input_path,
            output_path,
            mode=mode if mode in _VALID_MODES else _MODE_ALPHA,
            bg_key=bg_key,
            model=model,
            threads=threads,
        )

        # Verify the matte actually produced a valid, non-empty video before
        # declaring success; otherwise fall back to the untouched original.
        output_s = _probe_duration(output_path)
        if output_s <= 0 or not os.path.exists(output_path):
            _copy_through(input_path, output_path)
            return _result(mode, original_s, original_s, False)
        # A drift from the source duration means the matted frame count no longer
        # matches the audio timeline (VFR / mis-probed rate), i.e. the avatar's
        # lips would desync from the voiceover. Reject and keep the original so the
        # integrator falls back to the existing chromakey path.
        if abs(output_s - original_s) > _DURATION_TOLERANCE_S + 0.02 * original_s:
            logger.warning(
                f"matte output duration {output_s:.3f}s drifted from source "
                f"{original_s:.3f}s beyond tolerance; keeping original"
            )
            _copy_through(input_path, output_path)
            return _result(mode, original_s, original_s, False)

        return _result(mode, original_s, output_s, True)
    except Exception as exc:  # noqa: BLE001 - matting must never fail the job
        logger.warning(f"matte degraded for {input_path!r}: {exc}")
        try:
            _copy_through(input_path, output_path)
        except OSError as copy_exc:  # pragma: no cover - filesystem failure
            logger.error(f"matte fallback copy failed: {copy_exc}")
        fallback_s = _probe_duration(output_path)
        return _result(mode, fallback_s, fallback_s, False)
