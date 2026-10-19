"""Pure-FFmpeg "auto-tighten" dead-air remover for ReelForge (Submagic-style
"Remove Silences" retention pre-step).

The raw SCREEN RECORDING (and its own native audio track) is analysed for
*dead air* — stretches that are simultaneously SILENT (audio below a noise
floor) and STATIC (no visual motion) — and those stretches are cut out before
the existing ``compose_avatar_over_screen`` smart-handling runs. The result is a
shorter, tighter recording with no perceptible gaps.

Design rules (see the ReelForge auto_tighten contract):

* PURE FFMPEG, no new binary dependency. Detection reuses FFmpeg's own
  ``silencedetect`` (audio) + ``freezedetect`` (video) analysis filters, parsed
  from stderr — mirroring the ``compose_ffmpeg`` freezedetect approach.
* A/V-SYNC SAFE. Kept segments are re-assembled with a single ``trim`` +
  ``atrim`` + ``concat`` filtergraph pass (accurate cuts, consistent re-encode);
  because ``concat`` advances the video and audio clocks independently, a
  post-concat ``aresample`` + ``apad`` re-sync pins the audio to the CFR
  (``-fps_mode cfr`` + explicit ``-r``) video length via ``-shortest`` so audio
  never drifts against video.
* DEGRADE-SAFE. On ANY problem — no removable dead air, an entirely
  silent/static clip, a missing filter/tool, an unreadable file, a would-be
  empty result, or any exception — the ORIGINAL clip is returned UNCHANGED
  (copied to ``output_path``) with ``applied=False``. We never emit an empty,
  zero-length or corrupted video, and never remove everything.

This module operates ONLY on the background screen recording. The voiceover +
caption timeline (driven by the ElevenLabs/whisper WORD timings) is the single
source of truth and is never touched here.

Mockable seams (so tests need no heavy real media):

* :func:`detect_dead_air` — module-level; ``tighten`` looks it up by name at
  call time, so a test can ``monkeypatch.setattr`` it to inject synthetic dead
  ranges.
* :func:`_run` — module-level thin ``subprocess.run`` wrapper used for every
  FFmpeg invocation; patch it to fake ffmpeg stderr / avoid real encodes.
"""

from __future__ import annotations

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
# Detection / assembly tuning constants
# --------------------------------------------------------------------------- #
# Audio quieter than this (dBFS) counts as silence for silencedetect.
_DEFAULT_AUDIO_SILENCE_DB: float = -30.0
# A silent run must last at least this long (s) to be considered dead air.
_DEFAULT_MIN_SILENCE_S: float = 0.6
# A static (frozen) run must last at least this long (s) to count as a motion gap.
_DEFAULT_MIN_MOTION_GAP_S: float = 0.8
# freezedetect noise floor: how still the frame must be to count as "frozen".
_FREEZE_NOISE_DB: str = "-60dB"

# Small pad (s) kept on each side of a cut so the edit is not jarring.
_DEFAULT_PAD_S: float = 0.1
# Drop kept slivers shorter than this (s) — a flicker of content between two
# dead zones reads as a glitch, so it is folded away.
_DEFAULT_MIN_KEEP_S: float = 0.4

# If tightening would remove less than this (s) it is not worth a re-encode:
# treat it as a NO-OP and return the original untouched.
_MIN_REMOVED_S: float = 0.2

# Detection modes.
_MODE_AUTO: str = "auto"        # dead = silent AND static (screen-recording default)
_MODE_AUDIO: str = "audio"      # dead = silent only
_MODE_MOTION: str = "motion"    # dead = static only
_MODE_UNION: str = "union"      # dead = silent OR static
_VALID_MODES: frozenset[str] = frozenset(
    {_MODE_AUTO, _MODE_AUDIO, _MODE_MOTION, _MODE_UNION}
)

_LIBX264: str = "libx264"

Range = tuple[float, float]


# --------------------------------------------------------------------------- #
# Low-level subprocess seam (mockable)
# --------------------------------------------------------------------------- #
def _run(command: list[str]) -> subprocess.CompletedProcess:
    """Run an FFmpeg/ffprobe command, capturing stdout+stderr as text.

    This is the single subprocess seam for the module: tests patch it to feed
    synthetic ffmpeg stderr or to avoid real encodes. It never raises on a
    non-zero exit — callers inspect ``returncode`` / stderr themselves so a
    failed analysis pass can degrade gracefully.
    """
    return subprocess.run(command, capture_output=True, text=True, check=False)


# --------------------------------------------------------------------------- #
# Range algebra helpers (pure — unit-testable)
# --------------------------------------------------------------------------- #
def _clamp_ranges(ranges: list[Range], total: float) -> list[Range]:
    """Clamp ranges into ``[0, total]`` and drop empty/degenerate ones."""
    out: list[Range] = []
    for start, end in ranges:
        s = max(0.0, min(float(start), total))
        e = max(0.0, min(float(end), total))
        if e - s > 1e-6:
            out.append((s, e))
    return out


def _merge_ranges(ranges: list[Range]) -> list[Range]:
    """Sort and coalesce overlapping/adjacent ranges into a minimal list."""
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged: list[Range] = [ordered[0]]
    for start, end in ordered[1:]:
        last_s, last_e = merged[-1]
        if start <= last_e + 1e-6:
            merged[-1] = (last_s, max(last_e, end))
        else:
            merged.append((start, end))
    return merged


def _intersect_ranges(a: list[Range], b: list[Range]) -> list[Range]:
    """Return the overlap of two range lists (both assumed merged+sorted)."""
    out: list[Range] = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo = max(a[i][0], b[j][0])
        hi = min(a[i][1], b[j][1])
        if hi - lo > 1e-6:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _invert_ranges(ranges: list[Range], total: float) -> list[Range]:
    """Complement ``ranges`` within ``[0, total]`` (the gaps between them)."""
    merged = _merge_ranges(_clamp_ranges(ranges, total))
    keeps: list[Range] = []
    cursor = 0.0
    for start, end in merged:
        if start - cursor > 1e-6:
            keeps.append((cursor, start))
        cursor = max(cursor, end)
    if total - cursor > 1e-6:
        keeps.append((cursor, total))
    return keeps


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
# stderr parsers for the analysis filters
# --------------------------------------------------------------------------- #
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[0-9]+(?:\.[0-9]+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[0-9]+(?:\.[0-9]+)?)")
_FREEZE_START_RE = re.compile(r"freeze_start:\s*(-?[0-9]+(?:\.[0-9]+)?)")
_FREEZE_END_RE = re.compile(r"freeze_end:\s*(-?[0-9]+(?:\.[0-9]+)?)")


def _parse_paired_ranges(
    stderr: str,
    start_re: re.Pattern[str],
    end_re: re.Pattern[str],
    total: float,
) -> list[Range]:
    """Pair ``*_start`` / ``*_end`` metadata lines into ranges.

    Starts and ends are emitted in chronological order. A dangling final start
    with no matching end (a run extending to EOF) is closed at ``total``.
    """
    starts = [max(0.0, float(m)) for m in start_re.findall(stderr or "")]
    ends = [float(m) for m in end_re.findall(stderr or "")]
    ranges: list[Range] = []
    for idx, start in enumerate(starts):
        end = ends[idx] if idx < len(ends) else total
        if end > start:
            ranges.append((start, end))
    return _merge_ranges(_clamp_ranges(ranges, total))


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
def _analyze(
    input_path: str,
    *,
    audio_silence_db: float,
    min_silence_s: float,
    min_motion_gap_s: float,
    want_audio: bool,
    want_video: bool,
    total: float,
    ffmpeg: str | None = None,
) -> tuple[list[Range], list[Range]]:
    """Run one FFmpeg analysis pass and return ``(silent_ranges, static_ranges)``.

    ``silencedetect`` (audio) and ``freezedetect`` (video) both write their
    metadata to stderr; a single ``-f null`` pass gathers both. Missing streams
    / filters degrade to empty range lists.
    """
    binary = ffmpeg or utils.get_ffmpeg_binary()
    command: list[str] = [binary, "-hide_banner", "-i", input_path]
    if want_video:
        command += [
            "-vf",
            f"freezedetect=n={_FREEZE_NOISE_DB}:d={max(0.01, min_motion_gap_s):g}",
        ]
    if want_audio:
        command += [
            "-af",
            f"silencedetect=noise={audio_silence_db:g}dB:"
            f"d={max(0.01, min_silence_s):g}",
        ]
    command += ["-f", "null", os.devnull]

    try:
        result = _run(command)
    except (OSError, ValueError) as exc:  # pragma: no cover - environment issue
        logger.warning(f"dead-air analysis pass failed for {input_path!r}: {exc}")
        return [], []

    stderr = result.stderr or ""
    silent = (
        _parse_paired_ranges(stderr, _SILENCE_START_RE, _SILENCE_END_RE, total)
        if want_audio
        else []
    )
    static = (
        _parse_paired_ranges(stderr, _FREEZE_START_RE, _FREEZE_END_RE, total)
        if want_video
        else []
    )
    return silent, static


def detect_dead_air(
    input_path: str,
    *,
    audio_silence_db: float = _DEFAULT_AUDIO_SILENCE_DB,
    min_silence_s: float = _DEFAULT_MIN_SILENCE_S,
    min_motion_gap_s: float = _DEFAULT_MIN_MOTION_GAP_S,
    mode: str = _MODE_AUTO,
) -> list[Range]:
    """Detect DEAD-AIR ranges ``[(start, end), ...]`` in a screen recording.

    Uses FFmpeg's ``silencedetect`` (audio below ``audio_silence_db`` for at
    least ``min_silence_s``) and ``freezedetect`` (a static frame for at least
    ``min_motion_gap_s``), parsed from stderr, then combines them per ``mode``:

    * ``"auto"``   — dead = SILENT **and** STATIC (a screen recording that is
      both quiet and visually frozen). This is the safe default: brief pauses
      where the screen is still scrolling, or silent motion, are KEPT.
    * ``"audio"``  — dead = silent ranges only.
    * ``"motion"`` — dead = static ranges only.
    * ``"union"``  — dead = silent **or** static.

    Returns a merged, sorted list of dead ranges (NOT keep segments); feed it to
    :func:`build_keep_segments`. Returns ``[]`` (nothing removable) when the file
    is unreadable, the required filters are unavailable, or no dead air is found
    — so the caller degrades to a no-op.
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"unsupported mode: {mode!r} (allowed: {', '.join(sorted(_VALID_MODES))})"
        )
    if not input_path or not os.path.exists(input_path):
        return []

    ffmpeg = utils.get_ffmpeg_binary()
    ffprobe = _get_ffprobe_binary(ffmpeg)

    total = _probe_duration(input_path, ffprobe)
    if total <= 0:
        return []

    need_audio = mode in (_MODE_AUTO, _MODE_AUDIO, _MODE_UNION)
    need_video = mode in (_MODE_AUTO, _MODE_MOTION, _MODE_UNION)

    has_audio = _has_audio_stream(input_path, ffprobe) if need_audio else False
    # Guard against a build missing the analysis filters (degrade-safe).
    if need_audio and has_audio and not ffmpeg_has_filter("silencedetect", ffmpeg):
        has_audio = False
    if need_video and not ffmpeg_has_filter("freezedetect", ffmpeg):
        need_video = False

    silent, static = _analyze(
        input_path,
        audio_silence_db=audio_silence_db,
        min_silence_s=min_silence_s,
        min_motion_gap_s=min_motion_gap_s,
        want_audio=need_audio and has_audio,
        want_video=need_video,
        total=total,
        ffmpeg=ffmpeg,
    )

    if mode == _MODE_AUDIO:
        return silent
    if mode == _MODE_MOTION:
        return static
    if mode == _MODE_UNION:
        return _merge_ranges(silent + static)

    # AUTO: dead = silent AND static. When the clip has NO audio track at all,
    # every frame is "silent", so auto collapses to the static ranges (a muted
    # screen recording's dead air is its frozen stretches).
    if need_audio and not has_audio:
        return static
    return _intersect_ranges(silent, static)


# --------------------------------------------------------------------------- #
# Keep-segment assembly
# --------------------------------------------------------------------------- #
def build_keep_segments(
    dead_ranges: list[Range],
    total_duration: float,
    *,
    pad_s: float = _DEFAULT_PAD_S,
    min_keep_s: float = _DEFAULT_MIN_KEEP_S,
) -> list[Range]:
    """Invert dead ranges into padded KEEP segments ``[(start, end), ...]``.

    The dead ranges are complemented within ``[0, total_duration]``; each kept
    segment is then grown by ``pad_s`` on both sides (so a small cushion of the
    surrounding silence remains and the cut is not jarring), re-merged, and any
    kept sliver shorter than ``min_keep_s`` is dropped.

    DEGRADE-SAFE: if the result would be EMPTY or would cover essentially the
    whole clip (nothing meaningfully removed), a single full-length segment
    ``[(0.0, total_duration)]`` is returned — the NO-OP sentinel — so the caller
    never renders an empty or pointless cut.
    """
    full: list[Range] = [(0.0, float(total_duration))]
    if total_duration <= 0:
        return full

    keeps = _invert_ranges(dead_ranges, float(total_duration))
    if not keeps:
        return full

    pad = max(0.0, float(pad_s))
    padded = [
        (max(0.0, s - pad), min(float(total_duration), e + pad)) for s, e in keeps
    ]
    merged = _merge_ranges(padded)

    kept = [seg for seg in merged if (seg[1] - seg[0]) >= max(0.0, float(min_keep_s))]
    if not kept:
        return full

    removed = float(total_duration) - sum(e - s for s, e in kept)
    if removed < _MIN_REMOVED_S:
        return full
    return kept


def _is_noop(keep_segments: list[Range], total_duration: float) -> bool:
    """True when the keep list removes nothing meaningful (a NO-OP)."""
    if not keep_segments:
        return True
    kept = sum(e - s for s, e in keep_segments)
    return (float(total_duration) - kept) < _MIN_REMOVED_S


# --------------------------------------------------------------------------- #
# Cut application (A/V-sync-safe concat)
# --------------------------------------------------------------------------- #
def _build_cut_filtergraph(
    keep_segments: list[Range], *, has_audio: bool
) -> tuple[str, str, str]:
    """Build the ``trim``/``atrim`` + ``concat`` graph and its output labels.

    Each kept segment is trimmed (video via ``trim``, audio via ``atrim``) and
    time-reset with ``setpts``/``asetpts`` so the pieces butt together with no
    gap, then concatenated in order. Returns ``(graph, video_map, audio_map)``;
    ``audio_map`` is ``""`` when the source has no audio track.
    """
    frags: list[str] = []
    for i, (start, end) in enumerate(keep_segments):
        frags.append(
            f"[0:v]trim=start={start:.4f}:end={end:.4f},"
            f"setpts=PTS-STARTPTS[v{i}]"
        )
        if has_audio:
            frags.append(
                f"[0:a]atrim=start={start:.4f}:end={end:.4f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )

    n = len(keep_segments)
    if has_audio:
        pads = "".join(f"[v{i}][a{i}]" for i in range(n))
        frags.append(f"{pads}concat=n={n}:v=1:a=1[cv][ca]")
        return ";".join(frags), "[cv]", "[ca]"

    pads = "".join(f"[v{i}]" for i in range(n))
    frags.append(f"{pads}concat=n={n}:v=1:a=0[cv]")
    return ";".join(frags), "[cv]", ""


def apply_cuts(
    input_path: str,
    keep_segments: list[Range],
    output_path: str,
    *,
    fps: int | None = None,
    threads: int = 2,
) -> str:
    """Concatenate ``keep_segments`` of ``input_path`` into ``output_path``.

    A single FFmpeg ``trim``/``atrim`` + ``concat`` filtergraph pass cuts the
    segments (consistent re-encode with ``libx264`` + ``aac``, ``-pix_fmt
    yuv420p``); a post-concat ``aresample=async``/``apad`` re-sync plus CFR
    output (``-fps_mode cfr`` + explicit ``-r``) and ``-shortest`` pin the audio to
    the deterministic video length, so the tightened recording drops straight
    back into the compose pipeline with no A/V drift even for VFR screen
    recordings or a source whose audio ends before its video. Returns
    ``output_path``.

    Raises:
        ValueError: if ``keep_segments`` is empty.
        FileNotFoundError: if ``input_path`` is missing.
        RuntimeError: if FFmpeg exits non-zero (stderr is the message).
    """
    if not keep_segments:
        raise ValueError("apply_cuts requires at least one keep segment")
    if not input_path or not os.path.exists(input_path):
        raise FileNotFoundError(f"tighten input not found: {input_path!r}")

    ffmpeg = utils.get_ffmpeg_binary()
    ffprobe = _get_ffprobe_binary(ffmpeg)
    has_audio = _has_audio_stream(input_path, ffprobe)

    graph, video_map, audio_map = _build_cut_filtergraph(
        keep_segments, has_audio=has_audio
    )

    # A/V-SYNC SAFE re-sync pass. ``concat`` advances the video and audio
    # timelines INDEPENDENTLY: each segment's video runs to a frame boundary
    # while its audio is sample-accurate, so the per-segment durations diverge
    # and the mismatch accumulates into audible drift — worst on VFR screen
    # recordings, and pathological when the source audio ends before the video
    # (a tail keep segment yields full video but ~no audio). After concat we
    # resample the audio against a continuous clock and ``apad`` it so it is
    # never shorter than the video; ``-shortest`` (below) then trims/holds it to
    # the CFR video length, keeping every segment aligned.
    if audio_map:
        resynced_audio_map = "[caout]"
        graph = f"{graph};{audio_map}aresample=async=1:first_pts=0,apad[caout]"
    else:
        resynced_audio_map = ""

    # Force CFR output with an explicit frame rate so VFR segment durations
    # become deterministic under ``-fps_mode cfr``. Use the caller's fps when pinned,
    # else derive it from the source; degrade to the historical behaviour when it
    # cannot be determined.
    out_fps = int(fps) if fps and fps > 0 else 0
    if out_fps <= 0:
        info = _probe_video(input_path, ffprobe)
        if info and info.fps > 0:
            out_fps = int(round(info.fps))

    command: list[str] = [
        ffmpeg, "-y", "-i", input_path,
        "-filter_complex", graph,
        "-map", video_map,
    ]
    if resynced_audio_map:
        command += ["-map", resynced_audio_map, "-c:a", "aac", "-b:a", "192k"]
    command += [
        "-c:v", _LIBX264,
        "-pix_fmt", "yuv420p",
    ]
    if out_fps > 0:
        command += ["-r", str(out_fps), "-fps_mode", "cfr"]
    command += [
        "-threads", str(threads or 2),
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]

    result = _run(command)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr or "ffmpeg auto-tighten cut failed")
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
    tightened_s: float,
    segments: list[Range],
    applied: bool,
) -> dict:
    """Assemble the ``tighten`` result envelope."""
    return {
        "original_s": round(float(original_s), 4),
        "tightened_s": round(float(tightened_s), 4),
        "removed_s": round(max(0.0, float(original_s) - float(tightened_s)), 4),
        "segments": segments,
        "applied": bool(applied),
    }


def tighten(
    input_path: str,
    output_path: str,
    *,
    mode: str = _MODE_AUTO,
    **thresholds: float,
) -> dict:
    """Remove dead air from a screen recording (detect → build → apply).

    Orchestrates :func:`detect_dead_air` → :func:`build_keep_segments` →
    :func:`apply_cuts`. ``**thresholds`` may carry any of ``audio_silence_db``,
    ``min_silence_s``, ``min_motion_gap_s`` (forwarded to detection) and
    ``pad_s``, ``min_keep_s`` (forwarded to keep-segment assembly).

    Returns a result dict::

        {
            "original_s": float,   # source duration (s)
            "tightened_s": float,  # output duration (s)
            "removed_s": float,    # original_s - tightened_s
            "segments": list[tuple[float, float]],  # applied keep segments
            "applied": bool,       # True only when a real cut was written
        }

    DEGRADE-SAFE: on ANY exception, an unreadable/zero-length input, no removable
    dead air, an entirely silent/static clip, or a would-be-empty result, the
    ORIGINAL clip is copied to ``output_path`` UNCHANGED and ``applied=False`` is
    returned. It never emits an empty/corrupted video and never removes
    everything.
    """
    build_kwargs = {
        k: thresholds.pop(k) for k in ("pad_s", "min_keep_s") if k in thresholds
    }

    try:
        total = _probe_duration(input_path)
        if total <= 0:
            _copy_through(input_path, output_path)
            return _result(total, total, [(0.0, max(0.0, total))], applied=False)

        dead_ranges = detect_dead_air(input_path, mode=mode, **thresholds)
        keep_segments = build_keep_segments(dead_ranges, total, **build_kwargs)

        if _is_noop(keep_segments, total):
            _copy_through(input_path, output_path)
            return _result(total, total, [(0.0, total)], applied=False)

        apply_cuts(input_path, keep_segments, output_path)

        # Verify the cut actually produced a valid, non-empty video before
        # declaring success; otherwise fall back to the untouched original.
        out_total = _probe_duration(output_path)
        if out_total <= 0 or not os.path.exists(output_path):
            _copy_through(input_path, output_path)
            return _result(total, total, [(0.0, total)], applied=False)

        return _result(total, out_total, keep_segments, applied=True)
    except Exception as exc:  # noqa: BLE001 - auto-tighten must never fail the job
        logger.warning(f"auto-tighten degraded for {input_path!r}: {exc}")
        try:
            _copy_through(input_path, output_path)
        except OSError as copy_exc:  # pragma: no cover - filesystem failure
            logger.error(f"auto-tighten fallback copy failed: {copy_exc}")
        fallback_total = _probe_duration(output_path)
        return _result(
            fallback_total,
            fallback_total,
            [(0.0, max(0.0, fallback_total))],
            applied=False,
        )
