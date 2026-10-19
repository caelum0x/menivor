"""Pure-FFmpeg "auto-zoom / punch-in" pass for ReelForge (openscreen-style
attention zoom, ported to an already-recorded screen capture).

The openscreen (MIT) idea is to punch a smooth zoom in on the moment the viewer
should be looking at. openscreen has live cursor/click metadata to drive that;
ReelForge only has the finished SCREEN RECORDING, so we drive the zoom from
SCENE / MOTION cues instead:

* Scene-cut timestamps come from PySceneDetect (BSD-3, OPTIONAL — import-guarded
  so the suite and prod both run WITHOUT it installed) when available, else an
  FFmpeg ``select='gt(scene,...)'`` + ``showinfo`` scene-score fallback parsed
  from stderr (mirroring the ``compose_ffmpeg`` freezedetect stderr approach).
* Those timestamps are turned into a short list of "punch-in" moments — each a
  window that eases the zoom 1.0 -> ``scale`` -> 1.0 with a raised-cosine
  (ease-in / ease-out) curve — capped at ``max_zooms``, at most ~1.3x, and never
  closer together than ``min_gap_s``.
* The moments are rendered with FFmpeg's ``zoompan`` filter (fixed output size,
  one output frame per input frame) so the pass is A/V-SYNC SAFE and preserves
  the clip's duration exactly — the audio is copied through untouched.

Design rules (identical contract to :mod:`app.services.editing.silence_cut`):

* PURE FFMPEG for the render (``zoompan``); PySceneDetect is an OPTIONAL,
  import-guarded accelerator only.
* A/V-SYNC SAFE + DURATION-PRESERVING. ``zoompan`` emits exactly one output
  frame per input frame at a pinned CFR (``-fps_mode cfr`` + explicit ``-r``); the
  audio stream is stream-copied, so video and audio never drift and the reel is
  the same length it was — which keeps it >= the narration (the timing-authority
  guard is trivially satisfied and the golden caption-drift gate is unaffected).
* DEGRADE-SAFE + DEFAULT-OFF. On ANY problem — no scene cuts / no usable
  moments, a missing ``zoompan`` filter, an unreadable file, a would-be-empty or
  broken result, or any exception — the ORIGINAL clip is returned UNCHANGED
  (copied to ``output_path``) with ``applied=False``. We never emit an empty,
  zero-length or corrupted video and never fail the job.

This module operates ONLY on the background screen recording, PRE-compose. The
voiceover + caption timeline (driven by the ElevenLabs/whisper WORD timings) is
the single source of truth and is never touched here.

Mockable seams (so tests need no heavy real media / scene detection):

* :func:`detect_scene_changes` — module-level; :func:`plan_zoom_moments` looks
  it up by name at call time, so a test can ``monkeypatch.setattr`` it to inject
  synthetic scene timestamps.
* :func:`plan_zoom_moments` / :func:`apply_zooms` — module-level; :func:`auto_zoom`
  looks them up by name at call time, so a test can inject moments directly and
  fake (or skip) the real render.
* :func:`_run` — module-level thin ``subprocess.run`` wrapper used for every
  FFmpeg invocation; patch it to fake ffmpeg stderr / avoid real encodes.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess

from loguru import logger

from app.services.compose.compose_ffmpeg import (
    _get_ffprobe_binary,
    _probe_video,
    ffmpeg_has_filter,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Planning / render tuning constants
# --------------------------------------------------------------------------- #
# Never plan more than this many punch-ins in a single clip (too many reads busy).
_DEFAULT_MAX_ZOOMS: int = 4
# Minimum spacing (s) between two punch-in starts, so zooms do not stack.
_DEFAULT_MIN_GAP_S: float = 3.0
# Default punch-in zoom factor and the HARD cap — beyond ~1.3x a screen recording
# looks over-cropped / pixelated, so every requested zoom is clamped to this.
_DEFAULT_ZOOM: float = 1.25
_MAX_ZOOM_CAP: float = 1.3
# A punch-in smaller than this is not worth a full re-encode — treat as a no-op.
_MIN_ZOOM: float = 1.02
# How long a single punch-in window lasts (s): ease-in to the peak at the
# midpoint, then ease-out back to 1.0.
_DEFAULT_ZOOM_DUR_S: float = 1.2

# FFmpeg ``select`` scene-score threshold (0..1); a frame whose scene score
# exceeds this is treated as a scene cut. PySceneDetect uses its OWN content
# threshold scale (~0..255), so it gets a separate constant below.
_SCENE_THRESHOLD: float = 0.4
_PYSCENEDETECT_THRESHOLD: float = 27.0
# Ignore scene-fragments shorter than this (s) when using PySceneDetect.
_DEFAULT_MIN_SCENE_LEN_S: float = 0.6

# Fallback output frame rate when the source fps cannot be probed.
_DEFAULT_FPS: int = 30

# The rendered output must stay within this of the source duration, else the pass
# is treated as a failure and the ORIGINAL is kept (zoompan re-times off its own
# fps counter, so a mis-probed rate could desync it from the copied audio).
_DURATION_TOLERANCE_S: float = 0.25

_LIBX264: str = "libx264"

# A planned punch-in: (start_s, duration_s, scale). The zoom eases
# 1.0 -> scale -> 1.0 across ``[start_s, start_s + duration_s]``.
Moment = tuple[float, float, float]


# --------------------------------------------------------------------------- #
# Low-level subprocess seam (mockable)
# --------------------------------------------------------------------------- #
def _run(command: list[str]) -> subprocess.CompletedProcess:
    """Run an FFmpeg/ffprobe command, capturing stdout+stderr as text.

    The single subprocess seam for the module: tests patch it to feed synthetic
    ffmpeg stderr or to avoid real encodes. It never raises on a non-zero exit —
    callers inspect ``returncode`` / stderr themselves so a failed analysis pass
    can degrade gracefully.
    """
    return subprocess.run(command, capture_output=True, text=True, check=False)


# --------------------------------------------------------------------------- #
# ffprobe helper
# --------------------------------------------------------------------------- #
def _probe_duration(path: str, ffprobe: str | None = None) -> float:
    """Return ``path``'s duration in seconds (0.0 when it cannot be determined)."""
    info = _probe_video(path, ffprobe or _get_ffprobe_binary())
    return float(info.duration) if info and info.duration > 0 else 0.0


# --------------------------------------------------------------------------- #
# Scene detection — optional PySceneDetect, else FFmpeg scene-score fallback
# --------------------------------------------------------------------------- #
_SHOWINFO_PTS_RE = re.compile(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)")


def _parse_showinfo_pts(stderr: str) -> list[float]:
    """Parse ``pts_time:<t>`` timestamps from ``showinfo`` stderr into sorted secs.

    The ``select='gt(scene,...)'`` filter only forwards scene-cut frames, so each
    ``showinfo`` line corresponds to a detected cut. Duplicates are collapsed.
    """
    return sorted({float(m) for m in _SHOWINFO_PTS_RE.findall(stderr or "")})


def _import_scenedetect():
    """Import PySceneDetect if present, else ``None`` (OPTIONAL dep, import-guarded).

    Kept as a tiny seam so the suite and prod both run WITHOUT ``scenedetect``
    installed, and so a test could patch it. Any import error degrades to the
    FFmpeg scene-score fallback.
    """
    try:
        import scenedetect  # noqa: F401  (presence probe only)

        return scenedetect
    except Exception as exc:  # noqa: BLE001 - optional dep must never hard-fail
        logger.debug(f"PySceneDetect unavailable; using ffmpeg scene fallback: {exc}")
        return None


def _detect_scenes_pyscenedetect(
    input_path: str, min_scene_len_s: float
) -> list[float] | None:
    """Scene-cut timestamps via PySceneDetect, or ``None`` when unavailable/failed.

    Returns the START second of every scene AFTER the first (the first scene
    starts at 0.0 and is not a cut). ``None`` (not ``[]``) signals "fall back to
    the FFmpeg scene-score detector"; an empty list would mean "PySceneDetect ran
    and found no cuts" and would suppress the fallback.
    """
    if _import_scenedetect() is None:
        return None
    try:
        from scenedetect import ContentDetector, detect

        scene_list = detect(
            input_path,
            ContentDetector(threshold=_PYSCENEDETECT_THRESHOLD),
        )
        times: list[float] = []
        min_len = max(0.0, float(min_scene_len_s))
        for index, (start, _end) in enumerate(scene_list):
            if index == 0:  # first scene starts at the head — not a cut
                continue
            # Filter by the scene FRAGMENT's LENGTH (end - start), not by the
            # cut's absolute timestamp: a short fragment is the thing worth
            # dropping, while a legitimate early cut must be kept.
            duration = float(_end.get_seconds()) - float(start.get_seconds())
            if duration >= min_len:
                times.append(float(start.get_seconds()))
        return sorted(set(times))
    except Exception as exc:  # noqa: BLE001 - degrade to the ffmpeg fallback
        logger.warning(f"PySceneDetect failed for {input_path!r}: {exc}")
        return None


def _detect_scenes_ffmpeg(input_path: str, threshold: float) -> list[float]:
    """Scene-cut timestamps via an FFmpeg ``select`` + ``showinfo`` analysis pass.

    ``select='gt(scene,threshold)'`` forwards only frames whose scene score
    exceeds ``threshold``; ``showinfo`` logs each forwarded frame's ``pts_time``
    to stderr, which we parse. Missing filter / unreadable file degrade to ``[]``.
    """
    ffmpeg = utils.get_ffmpeg_binary()
    command: list[str] = [
        ffmpeg,
        "-hide_banner",
        "-i",
        input_path,
        "-vf",
        f"select='gt(scene,{float(threshold):g})',showinfo",
        "-an",
        "-f",
        "null",
        os.devnull,
    ]
    try:
        result = _run(command)
    except (OSError, ValueError) as exc:  # pragma: no cover - environment issue
        logger.warning(f"ffmpeg scene-detect pass failed for {input_path!r}: {exc}")
        return []
    # showinfo writes its metadata to stderr regardless of exit status.
    return _parse_showinfo_pts(result.stderr or "")


def detect_scene_changes(
    input_path: str,
    *,
    threshold: float = _SCENE_THRESHOLD,
    min_scene_len_s: float = _DEFAULT_MIN_SCENE_LEN_S,
) -> list[float]:
    """Detect scene-cut timestamps (seconds) in a screen recording.

    Prefers PySceneDetect (OPTIONAL, import-guarded) and otherwise runs FFmpeg's
    ``select='gt(scene,threshold)'`` + ``showinfo`` scene-score pass. Returns a
    sorted list of cut timestamps (NOT including the implicit 0.0 head), or ``[]``
    when the file is unreadable or no cut is found — so the caller degrades to a
    no-op.

    This is the mockable detection seam: :func:`plan_zoom_moments` calls it by
    name, so tests can ``monkeypatch.setattr`` it to inject timestamps.
    """
    if not input_path or not os.path.exists(input_path):
        return []
    scenes = _detect_scenes_pyscenedetect(input_path, min_scene_len_s)
    if scenes is not None:
        return scenes
    return _detect_scenes_ffmpeg(input_path, threshold)


# --------------------------------------------------------------------------- #
# Moment planning (pure — unit-testable)
# --------------------------------------------------------------------------- #
def _clamp_zoom(zoom: float) -> float:
    """Clamp a requested zoom into the valid ``[1.0, _MAX_ZOOM_CAP]`` range."""
    return max(1.0, min(_MAX_ZOOM_CAP, float(zoom)))


def _select_moments(
    scene_times: list[float],
    total: float,
    *,
    max_zooms: int,
    min_gap_s: float,
    zoom: float,
    dur_s: float,
) -> list[Moment]:
    """Turn scene-cut timestamps into at most ``max_zooms`` punch-in moments.

    Greedy left-to-right selection: a cut is accepted only when its full
    ``dur_s`` window fits inside ``[0, total]`` and its start is at least
    ``max(min_gap_s, dur_s)`` after the previously accepted start (so windows
    never overlap). The zoom scale is clamped to ``[1.0, _MAX_ZOOM_CAP]``; a
    scale at/below ``_MIN_ZOOM`` yields ``[]`` (not worth a re-encode).
    """
    scale = _clamp_zoom(zoom)
    if scale <= _MIN_ZOOM or total <= 0 or int(max_zooms) <= 0:
        return []

    dur = max(0.1, min(float(dur_s), float(total)))
    gap = max(float(min_gap_s), dur)

    moments: list[Moment] = []
    last_start: float | None = None
    for raw in sorted({float(t) for t in scene_times if t is not None}):
        start = max(0.0, raw)
        if start + dur > total:  # window would run past the end of the clip
            continue
        if last_start is not None and (start - last_start) < gap:
            continue
        moments.append((round(start, 4), round(dur, 4), round(scale, 4)))
        last_start = start
        if len(moments) >= int(max_zooms):
            break
    return moments


def plan_zoom_moments(
    input_path: str,
    *,
    max_zooms: int = _DEFAULT_MAX_ZOOMS,
    min_gap_s: float = _DEFAULT_MIN_GAP_S,
    zoom: float = _DEFAULT_ZOOM,
    dur_s: float = _DEFAULT_ZOOM_DUR_S,
    threshold: float = _SCENE_THRESHOLD,
) -> list[Moment]:
    """Plan punch-in moments for ``input_path``: ``[(start_s, dur_s, scale), ...]``.

    Detects scene cuts (via the :func:`detect_scene_changes` seam) and selects a
    spaced, capped subset as punch-in windows (see :func:`_select_moments`).
    Returns ``[]`` (a no-op) when the file is unreadable/zero-length, no scene cut
    is found, or the requested zoom is negligible — so :func:`auto_zoom` degrades
    to the untouched original.
    """
    if not input_path or not os.path.exists(input_path):
        return []
    total = _probe_duration(input_path)
    if total <= 0:
        return []

    scene_times = detect_scene_changes(input_path, threshold=threshold)
    return _select_moments(
        scene_times,
        total,
        max_zooms=max_zooms,
        min_gap_s=min_gap_s,
        zoom=zoom,
        dur_s=dur_s,
    )


# --------------------------------------------------------------------------- #
# Ease math (pure — unit-testable) + zoompan expression builders
# --------------------------------------------------------------------------- #
def _zoom_at(t: float, moments: list[Moment], *, max_zoom: float = _MAX_ZOOM_CAP) -> float:
    """Zoom factor at time ``t`` (s): the raised-cosine ease of every moment.

    Each moment contributes a Hann bump over ``[start, start+dur]`` that is 0.0 at
    both edges and peaks at ``scale`` at the midpoint, so the zoom eases in and
    out smoothly. Bumps are summed (moments do not overlap in practice) on top of
    the 1.0 baseline and the result is clamped to ``max_zoom``. Outside every
    window the zoom is exactly 1.0. This is the exact curve
    :func:`_build_zoom_expr` renders in FFmpeg.
    """
    zoom = 1.0
    for start, dur, scale in moments:
        if dur <= 0:
            continue
        end = start + dur
        if start <= t <= end:
            zoom += (float(scale) - 1.0) * 0.5 * (
                1.0 - math.cos(2.0 * math.pi * (t - start) / dur)
            )
    return min(float(max_zoom), zoom)


def _build_zoom_expr(
    moments: list[Moment], fps: float, *, max_zoom: float = _MAX_ZOOM_CAP
) -> str:
    """Build the ``zoompan`` ``z`` expression that mirrors :func:`_zoom_at`.

    ``zoompan`` evaluates ``z`` once per OUTPUT frame; with ``d=1`` and a pinned
    ``fps`` the current time is ``on/fps`` (``on`` = output frame index). Each
    moment becomes an ``if(between(T, start, end), <Hann bump>, 0)`` term summed
    onto ``1`` and clamped to ``max_zoom``. Commas are left bare — the caller
    wraps the whole expression in single quotes so FFmpeg's filtergraph parser
    does not treat them as filter separators.
    """
    rate = float(fps) if fps and fps > 0 else float(_DEFAULT_FPS)
    time_expr = f"(on/{rate:g})"
    terms: list[str] = ["1"]
    for start, dur, scale in moments:
        if dur <= 0:
            continue
        end = start + dur
        terms.append(
            f"if(between({time_expr},{start:.4f},{end:.4f}),"
            f"({float(scale):.4f}-1)*0.5*"
            f"(1-cos(2*PI*({time_expr}-{start:.4f})/{dur:.4f})),0)"
        )
    return f"min({float(max_zoom):g},{'+'.join(terms)})"


def _build_zoompan_filter(
    moments: list[Moment],
    width: int,
    height: int,
    fps: float,
    *,
    max_zoom: float = _MAX_ZOOM_CAP,
) -> str:
    """Build the full ``zoompan=...`` ``-vf`` string for ``apply_zooms``.

    The ``z`` expression (and the centred ``x``/``y`` pan expressions) are single-
    quoted so their commas survive the filtergraph parser. ``s=WxH`` pins the
    output to the source resolution and ``d=1`` emits one output frame per input
    frame so the clip's duration is preserved exactly.
    """
    rate = float(fps) if fps and fps > 0 else float(_DEFAULT_FPS)
    z_expr = _build_zoom_expr(moments, rate, max_zoom=max_zoom)
    return (
        f"zoompan=z='{z_expr}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:fps={rate:g}:s={int(width)}x{int(height)}"
    )


# --------------------------------------------------------------------------- #
# Zoom application (A/V-sync-safe, duration-preserving)
# --------------------------------------------------------------------------- #
def apply_zooms(
    input_path: str,
    moments: list[Moment],
    output_path: str,
    *,
    fps: int | None = None,
    threads: int = 2,
) -> str:
    """Render ``moments`` onto ``input_path`` as smooth punch-ins -> ``output_path``.

    A single FFmpeg ``zoompan`` pass applies the keyframed zoom (video re-encoded
    with ``libx264`` + ``-pix_fmt yuv420p`` at a pinned CFR via ``-fps_mode cfr`` +
    explicit ``-r``); the audio is stream-copied so it stays perfectly aligned and
    the output is the SAME duration as the source. Returns ``output_path``.

    Raises:
        ValueError: if ``moments`` is empty.
        FileNotFoundError: if ``input_path`` is missing.
        RuntimeError: if the FFmpeg build lacks ``zoompan``, the source geometry
            cannot be probed, or FFmpeg exits non-zero (stderr is the message).
    """
    if not moments:
        raise ValueError("apply_zooms requires at least one zoom moment")
    if not input_path or not os.path.exists(input_path):
        raise FileNotFoundError(f"auto-zoom input not found: {input_path!r}")

    ffmpeg = utils.get_ffmpeg_binary()
    ffprobe = _get_ffprobe_binary(ffmpeg)
    if not ffmpeg_has_filter("zoompan", ffmpeg):
        raise RuntimeError("auto-zoom requires an FFmpeg build with the 'zoompan' filter")

    info = _probe_video(input_path, ffprobe)
    if info is None or info.width <= 0 or info.height <= 0:
        raise RuntimeError(f"could not probe geometry for {input_path!r}")

    out_fps = int(fps) if fps and fps > 0 else 0
    if out_fps <= 0:
        out_fps = int(round(info.fps)) if info.fps > 0 else _DEFAULT_FPS

    # Conform the input to CFR at ``out_fps`` BEFORE zoompan. zoompan emits one
    # output frame per INPUT frame and stamps output PTS from its own fps counter
    # (ignoring input timestamps), so its duration is input_frame_count/out_fps.
    # For a VFR / NTSC / mis-probed source that count does NOT equal
    # duration*out_fps, and the video would desync from the stream-copied audio.
    # Prepending ``fps=out_fps`` resamples the input to exactly duration*out_fps
    # CFR frames, so the zoompan output duration matches the source (and audio).
    zoompan_vf = _build_zoompan_filter(moments, info.width, info.height, out_fps)
    vf = f"fps={out_fps},{zoompan_vf}"

    command: list[str] = [
        ffmpeg,
        "-y",
        "-i",
        input_path,
        "-vf",
        vf,
        "-c:v",
        _LIBX264,
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(out_fps),
        "-fps_mode",  # the ffmpeg 5.1+ name; ``-vsync`` is gone in ffmpeg 8+
        "cfr",
        # Stream-copy the audio so it is byte-for-byte aligned with the source —
        # the zoom is video-only and duration-preserving, so no re-sync is needed.
        "-c:a",
        "copy",
        "-threads",
        str(threads or 2),
        "-movflags",
        "+faststart",
        output_path,
    ]

    result = _run(command)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr or "ffmpeg auto-zoom render failed")
    return output_path


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _copy_through(input_path: str, output_path: str) -> None:
    """Copy the original clip to ``output_path`` (no-op if they are the same)."""
    if os.path.abspath(input_path) == os.path.abspath(output_path):
        return
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    shutil.copyfile(input_path, output_path)


def _result(
    original_s: float,
    output_s: float,
    moments: list[Moment],
    applied: bool,
) -> dict:
    """Assemble the :func:`auto_zoom` result envelope."""
    return {
        "original_s": round(float(original_s), 4),
        "output_s": round(float(output_s), 4),
        "zoom_count": len(moments) if applied else 0,
        "moments": moments if applied else [],
        "applied": bool(applied),
    }


def auto_zoom(
    input_path: str,
    output_path: str,
    *,
    max_zooms: int = _DEFAULT_MAX_ZOOMS,
    min_gap_s: float = _DEFAULT_MIN_GAP_S,
    zoom: float = _DEFAULT_ZOOM,
    **plan_opts: float,
) -> dict:
    """Apply scene-driven punch-in zooms to a screen recording (plan -> apply).

    Orchestrates :func:`plan_zoom_moments` -> :func:`apply_zooms`. ``**plan_opts``
    may carry any of ``dur_s`` / ``threshold`` (forwarded to planning).

    Returns a result dict::

        {
            "original_s": float,          # source duration (s)
            "output_s": float,            # output duration (s) — same as source
            "zoom_count": int,            # number of punch-ins applied
            "moments": list[(t, dur, s)], # the applied moments
            "applied": bool,              # True only when a real render was written
        }

    DEGRADE-SAFE: on ANY exception, an unreadable/zero-length input, no usable
    moments, or a would-be-empty/broken result, the ORIGINAL clip is copied to
    ``output_path`` UNCHANGED and ``applied=False`` is returned. It never emits an
    empty/corrupted video and never fails the job. The render preserves duration,
    so the reel stays >= the narration (timing-authority guard satisfied).
    """
    try:
        total = _probe_duration(input_path)
        if total <= 0:
            _copy_through(input_path, output_path)
            return _result(total, total, [], applied=False)

        moments = plan_zoom_moments(
            input_path,
            max_zooms=max_zooms,
            min_gap_s=min_gap_s,
            zoom=zoom,
            **plan_opts,
        )
        if not moments:
            _copy_through(input_path, output_path)
            return _result(total, total, [], applied=False)

        apply_zooms(input_path, moments, output_path)

        # Verify the render produced a valid, non-empty video before declaring
        # success; otherwise fall back to the untouched original.
        out_total = _probe_duration(output_path)
        if out_total <= 0 or not os.path.exists(output_path):
            _copy_through(input_path, output_path)
            return _result(total, total, [], applied=False)
        # zoompan re-times off its own fps counter, so a would-be-desynced render
        # (VFR / mis-probed rate) shows up as a duration drift from the source
        # (which carries the copied audio's length). Reject it and keep the
        # original rather than emit a clip whose video and audio disagree.
        if abs(out_total - total) > _DURATION_TOLERANCE_S + 0.02 * total:
            logger.warning(
                f"auto-zoom output duration {out_total:.3f}s drifted from source "
                f"{total:.3f}s beyond tolerance; keeping original"
            )
            _copy_through(input_path, output_path)
            return _result(total, total, [], applied=False)

        return _result(total, out_total, moments, applied=True)
    except Exception as exc:  # noqa: BLE001 - auto-zoom must never fail the job
        logger.warning(f"auto-zoom degraded for {input_path!r}: {exc}")
        try:
            _copy_through(input_path, output_path)
        except OSError as copy_exc:  # pragma: no cover - filesystem failure
            logger.error(f"auto-zoom fallback copy failed: {copy_exc}")
        fallback_total = _probe_duration(output_path)
        return _result(fallback_total, fallback_total, [], applied=False)
