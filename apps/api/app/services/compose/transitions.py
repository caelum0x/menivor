"""Cross-faded clip stitcher for ReelForge (ported primitive).

Stitches a sequence of rendered clips into a single reel with animated
``xfade`` video transitions and ``acrossfade`` audio transitions — the
"concatenate_with_transitions" behaviour from the MIT-licensed
AI-Youtube-Shorts-Generator, rewritten to ReelForge's subprocess +
``-filter_complex`` convention (NOT the ffmpeg-python DSL the original used).

Public API
----------
``stitch_with_transitions(clip_paths, out_path, *, transition_dur=0.5,
transitions=('fade','diagbr','diagtl'), ffmpeg=None) -> str``

Pure, deterministic filter-string builders (unit-testable without ffmpeg):

* ``_xfade_chain(labels, durations, transition_dur, transitions, pick=None)``
* ``_acrossfade_chain(labels, transition_dur)``
* ``_validate_clips(paths)`` — fail-fast on <1 clip / missing files.

A single-clip input short-circuits to a straight file copy (no re-encode).

--------------------------------------------------------------------------- #
Attribution (MIT)
This module is a ReelForge port of ``concatenate_with_transitions`` from
SaarD00/AI-Youtube-Shorts-Generator (https://github.com/SaarD00/AI-Youtube-Shorts-Generator),
MIT License. The original ffmpeg-python DSL implementation has been rewritten to
ReelForge's subprocess + filter_complex convention; the xfade/acrossfade
chaining logic and the cumulative-offset formula are adapted from that project.
--------------------------------------------------------------------------- #
"""

from __future__ import annotations

import os
import random
import shutil
from collections.abc import Callable, Sequence

from loguru import logger

from app.services.compose.compose_ffmpeg import _LIBX264, _probe_video, _run_ffmpeg, live_encode_args
from app.utils import utils

__all__ = [
    "stitch_with_transitions",
    "_xfade_chain",
    "_acrossfade_chain",
    "_validate_clips",
]

# Default animated transitions, cycled/picked per join (matches the original set).
DEFAULT_TRANSITIONS: tuple[str, ...] = ("fade", "diagbr", "diagtl")
DEFAULT_TRANSITION_DUR: float = 0.5


# --------------------------------------------------------------------------- #
# Validation (fail-fast at the boundary)
# --------------------------------------------------------------------------- #
def _validate_clips(paths: Sequence[str]) -> list[str]:
    """Return the clip paths as a list, raising fast on invalid input.

    Raises:
        ValueError: if fewer than one clip is supplied.
        FileNotFoundError: if any clip path is missing on disk.
    """
    clips = [str(p) for p in (paths or [])]
    if len(clips) < 1:
        raise ValueError("stitch_with_transitions requires at least one clip")
    for path in clips:
        if not path or not os.path.exists(path):
            raise FileNotFoundError(f"stitch clip not found: {path!r}")
    return clips


# --------------------------------------------------------------------------- #
# Pure filter-string builders (deterministic when ``pick`` is injected)
# --------------------------------------------------------------------------- #
def _default_pick(transitions: Sequence[str], rng: random.Random) -> Callable[[int], str]:
    """Build a transition picker that draws from ``transitions`` with ``rng``."""
    pool = tuple(transitions) or DEFAULT_TRANSITIONS

    def _pick(_index: int) -> str:
        return rng.choice(pool)

    return _pick


def _xfade_chain(
    labels: Sequence[str],
    durations: Sequence[float],
    transition_dur: float,
    transitions: Sequence[str],
    *,
    pick: Callable[[int], str] | None = None,
) -> tuple[str, str]:
    """Build the ``xfade`` video chain and return ``(graph, out_label)``.

    ``labels`` are the ffmpeg video pads (``"0:v"``, ``"1:v"``, ...). The offset
    for the i-th join is the cumulative merged duration so far minus one
    ``transition_dur`` (``offset_i = sum(d[0..i-1]) - i*transition_dur``), matching
    the ported cumulative-offset behaviour so each transition overlaps the tail of
    the running composite.

    Deterministic when a ``pick`` callable is supplied (the caller injects a
    seeded rng / picker); otherwise a fresh module-seeded picker is used.
    """
    n = len(labels)
    if n != len(durations):
        raise ValueError("labels and durations length mismatch")
    if n == 0:
        raise ValueError("_xfade_chain requires at least one label")
    if n == 1:
        # Nothing to cross-fade — the single stream is the output.
        return "", str(labels[0])

    picker = pick or _default_pick(transitions, random.Random())
    fragments: list[str] = []
    cumulative = float(durations[0])
    prev = str(labels[0])
    for i in range(1, n):
        offset = max(0.0, cumulative - transition_dur)
        effect = picker(i)
        out = f"vx{i}"
        fragments.append(
            f"[{prev}][{labels[i]}]xfade=transition={effect}:"
            f"duration={transition_dur:g}:offset={offset:g}[{out}]"
        )
        prev = out
        cumulative = cumulative + float(durations[i]) - transition_dur
    return ";".join(fragments), prev


def _acrossfade_chain(
    labels: Sequence[str], transition_dur: float
) -> tuple[str, str]:
    """Build the ``acrossfade`` audio chain and return ``(graph, out_label)``.

    ``labels`` are the ffmpeg audio pads (``"0:a"``, ``"1:a"``, ...). Each join
    cross-fades over ``transition_dur`` seconds, mirroring the video xfade chain
    so audio and video stay aligned across the composite.
    """
    n = len(labels)
    if n == 0:
        raise ValueError("_acrossfade_chain requires at least one label")
    if n == 1:
        return "", str(labels[0])

    fragments: list[str] = []
    prev = str(labels[0])
    for i in range(1, n):
        out = f"ax{i}"
        fragments.append(
            f"[{prev}][{labels[i]}]acrossfade=d={transition_dur:g}[{out}]"
        )
        prev = out
    return ";".join(fragments), prev


def _build_stitch_command(
    ffmpeg: str,
    clip_paths: Sequence[str],
    out_path: str,
    filtergraph: str,
    video_map: str,
    audio_map: str,
    fps: int = 30,
) -> list[str]:
    """Assemble the full FFmpeg argv for the cross-faded stitch (pure).

    Uses the shared live-encode settings (veryfast, CRF 21, 2 s GOP) instead of
    FFmpeg's slow ``medium`` default.
    """
    command: list[str] = [ffmpeg, "-y"]
    for path in clip_paths:
        command += ["-i", path]
    command += [
        "-filter_complex",
        filtergraph,
        "-map",
        video_map,
        "-map",
        audio_map,
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        _LIBX264,
        *live_encode_args(_LIBX264, fps),
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        out_path,
    ]
    return command


def _probe_durations(clip_paths: Sequence[str]) -> list[float]:
    """Probe each clip's duration via ``_probe_video`` (fail-fast on unreadable)."""
    durations: list[float] = []
    for path in clip_paths:
        info = _probe_video(path)
        if info is None or info.duration <= 0:
            raise ValueError(f"could not probe a positive duration for clip: {path!r}")
        durations.append(float(info.duration))
    return durations


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def stitch_with_transitions(
    clip_paths: Sequence[str],
    out_path: str,
    *,
    transition_dur: float = DEFAULT_TRANSITION_DUR,
    transitions: Sequence[str] = DEFAULT_TRANSITIONS,
    ffmpeg: str | None = None,
    pick: Callable[[int], str] | None = None,
) -> str:
    """Stitch ``clip_paths`` into ``out_path`` with cross-faded transitions.

    Builds an ``xfade`` video chain (cumulative-offset per join) plus an
    ``acrossfade`` audio chain and encodes an interchange-friendly MP4
    (``-pix_fmt yuv420p -c:v libx264`` with the shared live-encode args
    ``-preset veryfast -crf 21 -g 60``, ``-c:a aac -movflags +faststart``).
    Clip durations are probed with ``compose_ffmpeg._probe_video``.

    A single-clip input short-circuits to a straight file copy (no re-encode).

    Args:
        clip_paths: Ordered rendered clip files (each with a video + audio track).
        out_path: Destination MP4.
        transition_dur: Cross-fade length in seconds (per join).
        transitions: Pool of ``xfade`` transition names to pick from.
        ffmpeg: Explicit ffmpeg binary (defaults to ``utils.get_ffmpeg_binary``).
        pick: Deterministic transition picker ``(index) -> name`` (test seam).

    Returns:
        ``out_path`` on success.

    Raises:
        ValueError: no clips / non-positive ``transition_dur`` / unprobeable clip.
        FileNotFoundError: a clip path is missing.
        RuntimeError: FFmpeg exits non-zero (stderr is the message).
    """
    clips = _validate_clips(clip_paths)
    if transition_dur <= 0:
        raise ValueError(f"transition_dur must be positive, got {transition_dur!r}")

    # Single clip: a straight copy is the whole reel — no transitions to build.
    if len(clips) == 1:
        if os.path.abspath(clips[0]) != os.path.abspath(out_path):
            shutil.copy2(clips[0], out_path)
        return out_path

    durations = _probe_durations(clips)
    video_labels = [f"{i}:v" for i in range(len(clips))]
    audio_labels = [f"{i}:a" for i in range(len(clips))]

    video_graph, video_out = _xfade_chain(
        video_labels, durations, transition_dur, transitions, pick=pick
    )
    audio_graph, audio_out = _acrossfade_chain(audio_labels, transition_dur)
    filtergraph = ";".join(g for g in (video_graph, audio_graph) if g)

    binary = ffmpeg or utils.get_ffmpeg_binary()
    command = _build_stitch_command(
        binary,
        clips,
        out_path,
        filtergraph,
        f"[{video_out}]",
        f"[{audio_out}]",
    )

    logger.info(
        f"stitching {len(clips)} clips with transitions: "
        f"dur={transition_dur:g}s, out={out_path!r}"
    )
    _run_ffmpeg(command)
    return out_path
