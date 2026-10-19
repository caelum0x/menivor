"""Pure-FFmpeg synthetic "fake camera motion" pass for ReelForge.

The license-clean answer to Higgsfield-style camera presets, applied to a REAL
screen recording: subtle synthetic camera movement (drift / push / pull / whip)
is baked into the background clip via FFmpeg's own ``scale`` + ``crop`` filters —
NO new binary or Python dependency, mirroring :mod:`silence_cut`.

Design rules (identical contract to the ``auto_tighten`` pre-step):

* PURE FFMPEG. Motion is an OVERLAY TRANSFORM, never a cut: an animated
  ``scale=...:eval=frame`` zoom (evaluated per frame off the presentation time
  ``t``) is cropped back to the recording's own native resolution, so the frame
  count, timestamps and DURATION are untouched. This is far safer for VFR screen
  recordings than ``zoompan`` (which regenerates timestamps at a fixed rate).
* A/V-SYNC SAFE + NEVER-EMPTY/CORRUPT. Only the VIDEO stream is filtered; the
  audio is stream-copied verbatim (``-c:a copy``), so the voiceover/native audio
  stays sample-for-sample aligned and can never drift. The output is verified to
  be a real, non-empty clip of the SAME duration before it is accepted.
* SUBTLE. The synthetic zoom is clamped to ``<= 1.15x`` (``intensity <= 0.15``)
  so on-screen text / UI stays legible.
* DEGRADE-SAFE + DEFAULT-OFF (via ``preset='none'``). On ANY problem — an unknown
  preset, ``preset='none'``, an unreadable/zero-length input, a missing FFmpeg,
  an ffmpeg error, or an output whose duration drifted — the ORIGINAL clip is
  returned UNCHANGED (copied to ``output_path``) with ``applied=False``. Motion
  never raises out of :func:`motion` and never fails the job.

This module operates ONLY on the background screen recording, PRE-compose. The
voiceover + caption timeline (the ElevenLabs/whisper WORD timings) is the single
source of truth and is never touched here, so the golden caption-drift gate is
unaffected.

Mockable seams (so tests need no heavy real media):

* :func:`apply_motion` — module-level; :func:`motion` looks it up by name at call
  time, so a test can ``monkeypatch.setattr`` it to inject a fake render.
* :func:`_run` — module-level thin ``subprocess.run`` wrapper used for every
  FFmpeg/ffprobe invocation; patch it to fake ffmpeg / avoid real encodes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import NamedTuple

from loguru import logger

from app.services.compose.compose_ffmpeg import (
    _get_ffprobe_binary,
    _probe_video,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Preset catalogue + tuning constants
# --------------------------------------------------------------------------- #
_PRESET_KEN_BURNS: str = "ken_burns"   # slow diagonal drift + gentle zoom
_PRESET_PUSH_IN: str = "push_in"       # gradual centred zoom IN
_PRESET_PULL_OUT: str = "pull_out"     # gradual centred zoom OUT
_PRESET_WHIP_PAN: str = "whip_pan"     # fast horizontal sweep (whip)
_PRESET_NONE: str = "none"             # explicit no-op (default-off)

# Public, ordered list of every selectable preset (``none`` included last).
MOTION_PRESETS: tuple[str, ...] = (
    _PRESET_KEN_BURNS,
    _PRESET_PUSH_IN,
    _PRESET_PULL_OUT,
    _PRESET_WHIP_PAN,
    _PRESET_NONE,
)
# The presets that actually render a motion transform (everything but ``none``).
_ANIMATED_PRESETS: frozenset[str] = frozenset(MOTION_PRESETS) - {_PRESET_NONE}

# Default synthetic-motion strength and the subtlety ceiling. ``intensity`` is
# the extra zoom fraction, so a value of ``0.06`` peaks at 1.06x and the ceiling
# of ``0.15`` keeps the maximum synthetic zoom at 1.15x (text/UI stays legible).
_DEFAULT_INTENSITY: float = 0.06
_MAX_INTENSITY: float = 0.15

# whip_pan horizontal oscillation frequency (Hz) — a quick left/right sweep.
_WHIP_HZ: float = 1.5
# ken_burns keeps a small BASE zoom so there is always crop room to drift into,
# then ramps the remaining zoom over the clip: Z = 1 + I*(base + (1-base)*p).
_KEN_BURNS_BASE_ZOOM_FRACTION: float = 0.3

# The rendered output must stay within this of the source duration, else the pass
# is treated as a failure and the ORIGINAL is kept (motion never changes length).
_DURATION_TOLERANCE_S: float = 0.25

_LIBX264: str = "libx264"


# --------------------------------------------------------------------------- #
# Low-level subprocess seam (mockable)
# --------------------------------------------------------------------------- #
def _run(command: list[str]) -> subprocess.CompletedProcess:
    """Run an FFmpeg/ffprobe command, capturing stdout+stderr as text.

    The single subprocess seam for the module: tests patch it to avoid real
    encodes. It never raises on a non-zero exit — callers inspect ``returncode``
    themselves so a failed render can degrade gracefully.
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
# Intensity clamp (pure — unit-testable)
# --------------------------------------------------------------------------- #
def _clamp_intensity(intensity: float) -> float:
    """Clamp the requested motion ``intensity`` into ``[0.0, _MAX_INTENSITY]``.

    Keeps the synthetic zoom subtle (``<= 1.15x``) so text/UI stays legible; a
    non-numeric value falls back to the default strength.
    """
    try:
        value = float(intensity)
    except (TypeError, ValueError):
        return _DEFAULT_INTENSITY
    return max(0.0, min(_MAX_INTENSITY, value))


# --------------------------------------------------------------------------- #
# Motion filtergraph fragments (pure string builders — unit-testable)
# --------------------------------------------------------------------------- #
class _MotionSpec(NamedTuple):
    """A preset's per-frame zoom + crop-position expressions.

    ``zoom`` is an FFmpeg expression (in the presentation time ``t``) for the
    animated ``scale`` factor; ``crop_x`` / ``crop_y`` are the crop-window offset
    expressions (referencing libavfilter's ``in_w``/``out_w``/``in_h``/``out_h``
    crop variables) that pan the cropped window across the up-scaled frame.
    """

    zoom: str
    crop_x: str
    crop_y: str


# Centred crop window: the classic ``crop`` default, but written explicitly so
# every preset shares one code path.
_CENTER_X: str = "(in_w-out_w)/2"
_CENTER_Y: str = "(in_h-out_h)/2"


def _motion_spec(preset: str, intensity: float, duration: float) -> _MotionSpec:
    """Build the ``(zoom, crop_x, crop_y)`` expressions for ``preset``.

    ``progress`` ramps ``0 -> 1`` across the clip (``t`` never exceeds
    ``duration``, so no ``min`` clamp is needed). Every zoom expression stays
    ``>= 1.0`` so the up-scaled frame always fully covers the crop window.

    Raises:
        ValueError: if ``preset`` is not one of ``_ANIMATED_PRESETS``.
    """
    i = float(intensity)
    d = duration if duration > 0 else 1.0
    p = f"(t/{d:.6g})"  # progress 0..1

    if preset == _PRESET_PUSH_IN:
        return _MotionSpec(f"(1+{i:.6g}*{p})", _CENTER_X, _CENTER_Y)
    if preset == _PRESET_PULL_OUT:
        return _MotionSpec(f"(1+{i:.6g}*(1-{p}))", _CENTER_X, _CENTER_Y)
    if preset == _PRESET_KEN_BURNS:
        base = _KEN_BURNS_BASE_ZOOM_FRACTION
        zoom = f"(1+{i:.6g}*({base:.6g}+{1.0 - base:.6g}*{p}))"
        return _MotionSpec(zoom, f"(in_w-out_w)*{p}", f"(in_h-out_h)*{p}")
    if preset == _PRESET_WHIP_PAN:
        zoom = f"(1+{i:.6g})"  # constant zoom just to open horizontal pan room
        sweep = f"(0.5+0.5*sin(2*PI*{_WHIP_HZ:.6g}*t))"
        return _MotionSpec(zoom, f"(in_w-out_w)*{sweep}", _CENTER_Y)

    raise ValueError(
        f"unsupported motion preset: {preset!r} "
        f"(allowed: {', '.join(sorted(_ANIMATED_PRESETS))})"
    )


def _even(value: int) -> int:
    """Round a dimension DOWN to the nearest even number (libx264 needs even)."""
    v = int(value)
    return v - (v % 2)


def _build_motion_filter(
    preset: str,
    intensity: float,
    out_w: int,
    out_h: int,
    duration: float,
) -> str:
    """Assemble the ``-vf`` chain that bakes ``preset`` motion into a clip.

    The frame is up-scaled per-frame (``scale=...:eval=frame``, rounded UP to an
    even size so it always covers the crop window) then cropped back to the
    recording's own ``out_w`` x ``out_h`` — an overlay transform that never
    alters the frame count or duration. ``setsar=1`` pins the pixel aspect so the
    output drops straight back into the compose pipeline.
    """
    spec = _motion_spec(preset, intensity, duration)
    scaled_w = f"ceil({out_w}*{spec.zoom}/2)*2"
    scaled_h = f"ceil({out_h}*{spec.zoom}/2)*2"
    return (
        f"scale=w='{scaled_w}':h='{scaled_h}':eval=frame,"
        f"crop={out_w}:{out_h}:x='{spec.crop_x}':y='{spec.crop_y}',"
        f"setsar=1"
    )


# --------------------------------------------------------------------------- #
# Render application (A/V-sync-safe: video-only filter, audio stream-copied)
# --------------------------------------------------------------------------- #
def apply_motion(
    input_path: str,
    output_path: str,
    *,
    preset: str = _PRESET_KEN_BURNS,
    intensity: float = _DEFAULT_INTENSITY,
    aspect: object = None,
    threads: int = 2,
) -> str:
    """Render ``input_path`` with synthetic camera ``preset`` into ``output_path``.

    A single FFmpeg pass applies the animated ``scale``+``crop`` motion to the
    VIDEO only and stream-copies the audio (``-c:a copy``), so the output keeps
    the source's exact duration and its audio stays perfectly aligned. The
    intensity is clamped to the subtle ``<= 1.15x`` ceiling. ``aspect`` is
    accepted for API symmetry with the other editing passes and to record the
    intended output framing; the motion itself operates in the recording's own
    native geometry (compose handles the reel aspect downstream). Returns
    ``output_path``.

    Raises:
        ValueError: if ``preset`` is not an animated preset (``none``/unknown).
        FileNotFoundError: if ``input_path`` is missing.
        RuntimeError: if the clip cannot be probed or FFmpeg exits non-zero.
    """
    if preset not in _ANIMATED_PRESETS:
        raise ValueError(
            f"unsupported motion preset: {preset!r} "
            f"(allowed: {', '.join(sorted(_ANIMATED_PRESETS))})"
        )
    if not input_path or not os.path.exists(input_path):
        raise FileNotFoundError(f"motion input not found: {input_path!r}")

    ffmpeg = utils.get_ffmpeg_binary()
    ffprobe = _get_ffprobe_binary(ffmpeg)

    info = _probe_video(input_path, ffprobe)
    if not info or info.width <= 0 or info.height <= 0 or info.duration <= 0:
        raise RuntimeError(f"could not probe geometry/duration for {input_path!r}")

    out_w = _even(info.width)
    out_h = _even(info.height)
    if out_w <= 0 or out_h <= 0:
        raise RuntimeError(f"degenerate frame size for {input_path!r}")

    clamped = _clamp_intensity(intensity)
    motion_filter = _build_motion_filter(
        preset, clamped, out_w, out_h, float(info.duration)
    )
    has_audio = _has_audio_stream(input_path, ffprobe)

    logger.info(
        f"applying motion preset={preset} intensity={clamped:.4g} "
        f"size={out_w}x{out_h} aspect={aspect} audio={'yes' if has_audio else 'no'}"
    )

    command: list[str] = [
        ffmpeg, "-y", "-i", input_path,
        "-vf", motion_filter,
        "-c:v", _LIBX264,
        "-pix_fmt", "yuv420p",
    ]
    if has_audio:
        # Stream-copy the audio verbatim: no re-encode, no resample, so the
        # voiceover/native audio can never drift against the filtered video.
        command += ["-c:a", "copy"]
    command += [
        "-threads", str(threads or 2),
        "-movflags", "+faststart",
        output_path,
    ]

    result = _run(command)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr or "ffmpeg motion render failed")
    return output_path


# --------------------------------------------------------------------------- #
# Orchestration (DEGRADE-SAFE)
# --------------------------------------------------------------------------- #
def _copy_through(input_path: str, output_path: str) -> None:
    """Copy the original clip to ``output_path`` (no-op if they are the same)."""
    if os.path.abspath(input_path) == os.path.abspath(output_path):
        return
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    shutil.copyfile(input_path, output_path)


def _result(preset: str, original_s: float, output_s: float, applied: bool) -> dict:
    """Assemble the :func:`motion` result envelope."""
    return {
        "applied": bool(applied),
        "preset": str(preset),
        "original_s": round(float(original_s), 4),
        "output_s": round(float(output_s), 4),
    }


def motion(input_path: str, output_path: str, preset: str = _PRESET_KEN_BURNS, **opts):
    """Bake subtle synthetic camera motion into a screen recording.

    Orchestrates the DEGRADE-SAFE application of a named ``preset`` via
    :func:`apply_motion`. ``**opts`` may carry ``intensity`` (clamped to the
    ``<= 1.15x`` ceiling) and ``aspect`` (the intended reel framing, forwarded
    for symmetry). Returns a result dict::

        {
            "applied": bool,      # True only when a motion render was written
            "preset": str,        # the requested preset
            "original_s": float,  # source duration (s)
            "output_s": float,    # output duration (s)
        }

    DEGRADE-SAFE: an unknown preset, ``preset='none'``, an unreadable/zero-length
    input, a missing/failed FFmpeg, or an output whose duration drifted from the
    source all cause the ORIGINAL clip to be copied to ``output_path`` UNCHANGED
    with ``applied=False``. Motion is an overlay transform, so a successful pass
    keeps the source duration exactly; it never raises and never fails the job.
    """
    preset_name = str(preset or "").strip().lower()
    intensity = opts.pop("intensity", _DEFAULT_INTENSITY)
    aspect = opts.pop("aspect", None)

    try:
        original_s = _probe_duration(input_path)

        # Explicit no-op (default-off) or an unknown preset: hand back the
        # original untouched. This mirrors the auto_tighten degrade contract.
        if preset_name not in _ANIMATED_PRESETS:
            if preset_name and preset_name != _PRESET_NONE:
                logger.info(f"unknown motion preset {preset_name!r}; skipping (no-op)")
            _copy_through(input_path, output_path)
            return _result(preset_name, original_s, original_s, applied=False)

        if original_s <= 0:
            _copy_through(input_path, output_path)
            return _result(preset_name, original_s, original_s, applied=False)

        apply_motion(
            input_path,
            output_path,
            preset=preset_name,
            intensity=intensity,
            aspect=aspect,
        )

        # Verify the render is a real, non-empty clip of the SAME duration before
        # accepting it; otherwise fall back to the untouched original.
        output_s = _probe_duration(output_path)
        if output_s <= 0 or not os.path.exists(output_path):
            _copy_through(input_path, output_path)
            return _result(preset_name, original_s, original_s, applied=False)
        if abs(output_s - original_s) > _DURATION_TOLERANCE_S + 0.02 * original_s:
            logger.warning(
                f"motion output duration {output_s:.3f}s drifted from source "
                f"{original_s:.3f}s beyond tolerance; keeping original"
            )
            _copy_through(input_path, output_path)
            return _result(preset_name, original_s, original_s, applied=False)

        return _result(preset_name, original_s, output_s, applied=True)
    except Exception as exc:  # noqa: BLE001 - motion must never fail the job
        logger.warning(f"motion degraded for {input_path!r}: {exc}")
        try:
            _copy_through(input_path, output_path)
        except OSError as copy_exc:  # pragma: no cover - filesystem failure
            logger.error(f"motion fallback copy failed: {copy_exc}")
        fallback_s = _probe_duration(output_path)
        return _result(preset_name, fallback_s, fallback_s, applied=False)
