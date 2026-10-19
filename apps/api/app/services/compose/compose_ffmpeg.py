"""Pure-FFmpeg avatar-over-screen compositor for ReelForge (contract §2.6).

Builds a single `-filter_complex` graph that:

1. Scales + crops the screen recording to fill 1080x1920 (crop-to-fill, NOT the
   fit+letterbox used by ``video.combine_videos``).
2. Chroma-keys the green-screen HeyGen avatar and renders it as a circular
   picture-in-picture (or split / hook-intro variant).
3. Burns the karaoke ``.ass`` captions as the LAST filtergraph node via libass.
4. Muxes the ElevenLabs narration and writes an interchange-friendly MP4
   (``-pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart``) so the output
   drops straight into MPT's ``generate_video`` conventions.

Stage-5 "smart screen-recording handling" (CTO §5) is layered on top as opt-in
keyword arguments that DEFAULT to the historical behaviour so existing callers
and tests are unaffected:

* ``target_duration_s`` — when set, the screen recording is ``ffprobe``-analysed
  (resolution/duration/fps). If it runs longer than the narration/target it is
  slowed down via ``setpts`` (capped at ``max_speed`` = 1.6x) so it fits; if its
  aspect cannot crop cleanly to the target it is composited with a blurred
  scale-pad background instead of a hard crop.
* ``trim_freeze`` — leading static frames are located with ``freezedetect`` and
  skipped with an input ``-ss`` seek (best-effort; failures are non-fatal).
* ``music_path`` — background music is ducked under the voiceover with
  ``sidechaincompress`` and the mix is loudness-normalised with ``loudnorm``
  (default -14 LUFS integrated, -1 dBTP true peak; configurable through
  ``MENIVOR_LOUDNORM_I`` / ``MENIVOR_LOUDNORM_TP``).

Reuses MPT helpers rather than reimplementing them:
``utils.get_ffmpeg_binary``, ``video._get_effective_video_codec`` (+ its libx264
runtime fallback via ``video._disable_runtime_video_codec``),
``VideoAspect.to_resolution`` and ``utils.font_dir``.

Shared filtergraph contract (preview == output)
-----------------------------------------------
The layout builders below (``_fill_node`` / ``_layout_pip`` / ``_layout_split`` /
``_layout_hook_intro``) terminate at the ``[comp]`` sink, and ``_build_audio_graph``
terminates at ``[aout]``. Those two fragments are pure, deterministic and
environment-independent, so they are the SOURCE OF TRUTH for the shared
``packages/render-core`` library (TS + Python + Rust), which the client uses to
build its preview from the same ``RenderSpec``. ``render-core`` reproduces these
fragments byte-for-byte, and ``tests/reelforge/test_render_core_parity.py`` imports
this module and asserts executor == library so the preview can never silently
diverge from the burned output. When you change a ``[comp]``/``[aout]`` node here,
update ``render-core`` and its golden fixtures in lock-step (that test will fail
until you do).

The nodes appended AFTER ``[comp]`` — the libass caption burn (``_build_final_node``,
which escapes an absolute path and embeds ``utils.font_dir()``) and the brand
watermark — are render-time and environment-specific, so they are intentionally
OUTSIDE the shared byte-identical contract.
"""

import functools
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from typing import NamedTuple

from loguru import logger

from app.models.schema import VideoAspect
from app.services.compose import encode_count as _encodes
from app.services import video as video_service
from app.utils import utils

# --------------------------------------------------------------------------- #
# Layout / chroma tuning constants (contract §2.6)
# --------------------------------------------------------------------------- #
_PIP_DIAMETER: int = 480
_PIP_MARGIN: int = 48
_HOOK_DURATION: float = 3.0

_LIBX264: str = "libx264"

# libx264 speed/quality for the final reel encodes. FFmpeg's default preset is
# ``medium``: on the 2-vCPU render box a 25 s 1080x1920 reel took minutes and
# ~1.5 GB RSS. ``veryfast`` + CRF 21 measured ~3x faster with a visually
# equivalent phone-screen result (see docs/SCALE-PLAN.md section 7). Operators
# can override per host via MENIVOR_X264_PRESET / MENIVOR_X264_CRF.
_X264_PRESETS: frozenset[str] = frozenset(
    {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"}
)
_DEFAULT_X264_PRESET: str = "veryfast"
_DEFAULT_X264_CRF: int = 21


# ``-shortest`` makes FFmpeg (6+) hold up to 10 s of RAW decoded frames in a
# sync queue: ~1.2-1.4 GB for a 1080x1920 reel. One second is enough to cut the
# output at the shorter stream (same duration, measured) at ~0.4 GB.
_SHORTEST_BUF_S: str = "1"


@functools.lru_cache(maxsize=4)
def _supports_shortest_buf(ffmpeg: str) -> bool:
    """True when this FFmpeg build accepts ``-shortest_buf_duration`` (6.0+)."""
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-h", "full"],
            capture_output=True, text=True, check=False, timeout=20,
        )
        return "shortest_buf_duration" in str(result.stdout or "")
    except Exception:  # noqa: BLE001 - a failed probe keeps plain -shortest
        return False


def _shortest_args(ffmpeg: str) -> list[str]:
    """``-shortest`` plus a bounded sync-queue buffer when supported."""
    if _supports_shortest_buf(ffmpeg):
        return ["-shortest", "-shortest_buf_duration", _SHORTEST_BUF_S]
    return ["-shortest"]


def _x264_speed_args(codec: str) -> list[str]:
    """``-preset``/``-crf`` for libx264 (empty for hardware encoders)."""
    if codec != _LIBX264:
        return []
    preset = os.environ.get("MENIVOR_X264_PRESET", "").strip().lower()
    if preset not in _X264_PRESETS:
        preset = _DEFAULT_X264_PRESET
    try:
        crf = int(os.environ.get("MENIVOR_X264_CRF", "") or _DEFAULT_X264_CRF)
    except ValueError:
        crf = _DEFAULT_X264_CRF
    crf = max(14, min(30, crf))
    return ["-preset", preset, "-crf", str(crf)]


# A keyframe every 2 s (60 frames at 30 fps) on every live encode. The
# pre-encoded background loops use the same GOP, so their segments stream-copy
# into a mix and every reel seeks and cuts on the same 2 s grid.
_GOP_SECONDS: int = 2


def gop_frames(fps: int | float) -> int:
    """Frames per GOP for ``fps`` (60 at 30 fps; never below 1)."""
    try:
        return max(1, int(round(float(fps) * _GOP_SECONDS)))
    except (TypeError, ValueError):
        return 30 * _GOP_SECONDS


def live_encode_args(codec: str, fps: int | float = 30) -> list[str]:
    """Speed/quality plus GOP args for a live (per-reel) encode.

    ``-preset veryfast -crf 21 -g 60`` for libx264 at 30 fps; hardware encoders
    get only the GOP (they have no x264 preset/CRF). The offline loop renderer
    (``scripts/background-loops``) keeps ``-preset slow`` on purpose: it runs
    once per asset, not per reel.
    """
    return [*_x264_speed_args(codec), "-g", str(gop_frames(fps))]

# --------------------------------------------------------------------------- #
# Brand-watermark overlay constants (optional logo on top of the burned reel)
# --------------------------------------------------------------------------- #
# The logo is sized as a fraction of this reference width (the 1080 portrait
# width) so it scales consistently regardless of the actual output aspect.
_WATERMARK_REF_WIDTH: int = 1080
_WATERMARK_POSITIONS: frozenset[str] = frozenset(
    {"top_left", "top_right", "bottom_left", "bottom_right", "center"}
)
_WATERMARK_POSITION: str = "bottom_right"
_WATERMARK_OPACITY: float = 0.85
_WATERMARK_SCALE: float = 0.16
_WATERMARK_MARGIN: int = 40

# --------------------------------------------------------------------------- #
# Smart screen-recording handling constants (CTO §5 Stage-5)
# --------------------------------------------------------------------------- #
# Never accelerate a recording past this factor — beyond it motion looks unreal.
_MAX_SPEED: float = 1.6
# freezedetect tuning: noise floor + minimum static run (seconds) that counts as
# a freeze. Only leading freezes (starting at ~0.0) are trimmed.
_FREEZE_NOISE_DB: str = "-60dB"
_FREEZE_MIN_DURATION: float = 0.5
# Only scan the first few seconds for a leading freeze (keeps the extra pass cheap).
_FREEZE_SCAN_S: float = 6.0
# A leading freeze is one whose start timestamp is within this epsilon of 0.0.
_FREEZE_START_EPS: float = 0.30
# Never trim away more than this fraction of the recording as "leading static".
_FREEZE_MAX_TRIM_FRACTION: float = 0.5
# If a cover-crop to the target aspect would discard more than this fraction of
# the source's dominant dimension, prefer a blur-pad composite over a hard crop.
_BLUR_PAD_CROP_LOSS_THRESHOLD: float = 0.35
# boxblur strength (luma_radius:luma_power) for the padded background.
_BLUR_PAD_STRENGTH: str = "24:2"
# Integrated-loudness target (LUFS) and true-peak ceiling (dBTP). Social
# platforms normalise to about -14 LUFS integrated with a -1 dBTP ceiling, so
# that is the default (story8 already lands near -15). Override per deploy with
# ``MENIVOR_LOUDNORM_I`` / ``MENIVOR_LOUDNORM_TP``. FFmpeg's loudnorm accepts I
# in [-70, -5] and TP in [-9, 0]; requested values are clamped into range.
_LOUDNORM_TARGET_I: float = -14.0
_LOUDNORM_I_CEILING: float = -5.0
_LOUDNORM_I_FLOOR: float = -70.0
_LOUDNORM_TP: float = -1.0
_LOUDNORM_TP_CEILING: float = 0.0
_LOUDNORM_TP_FLOOR: float = -9.0
_LOUDNORM_LRA: float = 11.0
# sidechaincompress ducking curve (music compressed when voiceover is present).
_DUCK_THRESHOLD: float = 0.03
_DUCK_RATIO: float = 8.0
_DUCK_ATTACK: float = 5.0
_DUCK_RELEASE: float = 250.0

# --------------------------------------------------------------------------- #
# B-roll cutaway constants (optional muted intro/outro stock clips)
# --------------------------------------------------------------------------- #
# Default cap on how long a single spliced b-roll clip may play. Stock cutaways
# are meant to be brief creative accents, not to pad the reel.
_BROLL_MAX_S: float = 2.5
# Silent-audio track sample rate for the b-roll segments. Every concat segment's
# audio is coerced to this rate + stereo layout so the streams are concat-safe.
_BROLL_SAMPLE_RATE: int = 44100
_BROLL_CHANNEL_LAYOUT: str = "stereo"


class VideoInfo(NamedTuple):
    """Result of ``_probe_video`` — the geometry we need for smart handling."""

    width: int
    height: int
    duration: float
    fps: float


# --------------------------------------------------------------------------- #
# Filtergraph fragment helpers (pure string builders — unit-testable)
# --------------------------------------------------------------------------- #
def _chroma_filter(chroma: dict) -> str:
    """Render a ``chromakey`` filter node from a chroma spec dict."""
    color = chroma.get("color", "0x00FF00")
    similarity = float(chroma.get("similarity", 0.18))
    blend = float(chroma.get("blend", 0.10))
    return f"chromakey={color}:{similarity:.4g}:{blend:.4g}"


def _fill_node(src: str, out: str, width: int, height: int) -> str:
    """Scale-to-cover then crop-to-fill ``src`` into ``width`` x ``height``."""
    return (
        f"[{src}]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1[{out}]"
    )


def _circular_avatar_node(src: str, out: str, diameter: int, chroma: dict) -> str:
    """Chroma-key ``src`` and mask it into a filled circle of ``diameter`` px.

    The ``geq`` node keeps the chroma-produced alpha inside the inscribed circle
    and forces alpha to 0 outside it, yielding a clean circular PiP badge.
    """
    radius = diameter // 2
    return (
        f"[{src}]{_chroma_filter(chroma)},"
        f"scale={diameter}:{diameter}:force_original_aspect_ratio=increase,"
        f"crop={diameter}:{diameter},format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='if(lte(hypot(X-{radius},Y-{radius}),{radius}),alpha(X,Y),0)'[{out}]"
    )


# --------------------------------------------------------------------------- #
# Smart screen-recording filter fragments (opt-in — pure string builders)
# --------------------------------------------------------------------------- #
def _speed_factor(
    screen_duration: float, target_duration: float, max_speed: float = _MAX_SPEED
) -> float:
    """Return the ``setpts`` speed factor that fits ``screen_duration`` into
    ``target_duration``, clamped to ``[1.0, max_speed]``.

    A factor of ``1.0`` means "leave the recording untouched" (it already fits,
    or the inputs are degenerate). We never SLOW a recording down here — a short
    recording is handled by ``-shortest``/looping upstream, not by stretching.
    """
    if (
        screen_duration <= 0
        or target_duration <= 0
        or max_speed <= 1.0
        or screen_duration <= target_duration
    ):
        return 1.0
    return min(float(max_speed), screen_duration / target_duration)


def _setpts_node(src: str, out: str, speed: float) -> str:
    """Speed-ramp ``src`` by ``speed`` via ``setpts`` (video-only, timestamps)."""
    return f"[{src}]setpts=PTS/{speed:.4g}[{out}]"


def _blur_pad_node(
    src: str, out: str, width: int, height: int, blur: str = _BLUR_PAD_STRENGTH
) -> str:
    """Fit ``src`` inside ``width`` x ``height`` over a blurred scale-to-cover
    background, so an un-croppable aspect gets soft bars instead of a hard crop.

    The source is split: one copy is scaled-to-cover + blurred as the backdrop,
    the other is scaled-to-fit (letterboxed) and centred on top.
    """
    return (
        f"[{src}]split=2[bp_bg][bp_fg];"
        f"[bp_bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur={blur},setsar=1[bp_bgb];"
        f"[bp_fg]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"setsar=1[bp_fgs];"
        f"[bp_bgb][bp_fgs]overlay=(W-w)/2:(H-h)/2:format=auto[{out}]"
    )


def _crop_loss_fraction(src_w: int, src_h: int, dst_w: int, dst_h: int) -> float:
    """Fraction of the source's dominant dimension a cover-crop would discard.

    0.0 == aspects match (nothing cropped); →1.0 == a very lopsided crop.
    """
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return 0.0
    src_ratio = src_w / src_h
    dst_ratio = dst_w / dst_h
    lo, hi = sorted((src_ratio, dst_ratio))
    if hi <= 0:
        return 0.0
    return 1.0 - (lo / hi)


def _needs_blur_pad(
    src_w: int,
    src_h: int,
    dst_w: int,
    dst_h: int,
    threshold: float = _BLUR_PAD_CROP_LOSS_THRESHOLD,
) -> bool:
    """True when cropping ``src`` to the ``dst`` aspect would lose too much."""
    return _crop_loss_fraction(src_w, src_h, dst_w, dst_h) > threshold


def _build_screen_prep(
    speed: float, blur_pad: bool, width: int, height: int, source: str = "0:v"
) -> tuple[str, str]:
    """Build the optional screen-preprocess subgraph and its output label.

    Returns ``(prep_graph, screen_label)``. When no preprocessing is required the
    graph is ``""`` and the label is the raw ``source`` (``"0:v"``), so the
    layout builders composite the untouched screen exactly as before.
    """
    fragments: list[str] = []
    label = source
    if speed and speed > 1.0:
        setpts_out = "scr_sp"
        fragments.append(_setpts_node(label, setpts_out, speed))
        label = setpts_out
    if blur_pad:
        pad_out = "scr_bp"
        fragments.append(_blur_pad_node(label, pad_out, width, height))
        label = pad_out
    return ";".join(fragments), label


def _clamp_loudnorm_i(target_i: float) -> float:
    """Clamp a requested integrated-loudness target into FFmpeg's valid range."""
    return max(_LOUDNORM_I_FLOOR, min(_LOUDNORM_I_CEILING, float(target_i)))


def _clamp_loudnorm_tp(true_peak: float) -> float:
    """Clamp a requested true-peak ceiling into FFmpeg's valid range."""
    return max(_LOUDNORM_TP_FLOOR, min(_LOUDNORM_TP_CEILING, float(true_peak)))


def _env_float(name: str, default: float) -> float:
    """Read a float override from the environment, falling back on bad input."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _loudnorm_targets(
    target_i: float | None = None, true_peak: float | None = None
) -> tuple[float, float]:
    """Resolve (I, TP): explicit argument, then env override, then default."""
    i = target_i if target_i is not None else _env_float(
        "MENIVOR_LOUDNORM_I", _LOUDNORM_TARGET_I
    )
    tp = true_peak if true_peak is not None else _env_float(
        "MENIVOR_LOUDNORM_TP", _LOUDNORM_TP
    )
    return _clamp_loudnorm_i(i), _clamp_loudnorm_tp(tp)


def _build_audio_graph(
    voice_input: int = 2,
    music_input: int = 3,
    target_i: float | None = None,
    out: str = "aout",
    true_peak: float | None = None,
) -> tuple[str, str]:
    """Build the ducked-music + loudnorm audio subgraph and its output label.

    ``sidechaincompress`` compresses the music (main input) whenever the
    voiceover (sidechain) is present, then the ducked music is mixed back under
    the voiceover and the sum is loudness-normalised (default -14 LUFS
    integrated, -1 dBTP true peak).
    """
    i, tp = _loudnorm_targets(target_i, true_peak)
    graph = ";".join(
        [
            f"[{voice_input}:a]asplit=2[vo][vo_key]",
            (
                f"[{music_input}:a][vo_key]sidechaincompress="
                f"threshold={_DUCK_THRESHOLD:g}:ratio={_DUCK_RATIO:g}:"
                f"attack={_DUCK_ATTACK:g}:release={_DUCK_RELEASE:g}[duck]"
            ),
            "[vo][duck]amix=inputs=2:duration=first:dropout_transition=0[premix]",
            (
                f"[premix]loudnorm=I={i:g}:TP={tp:g}:"
                f"LRA={_LOUDNORM_LRA:g}[{out}]"
            ),
        ]
    )
    return graph, out


# --------------------------------------------------------------------------- #
# Layout builders — each returns the filtergraph string ending in ``[comp]``.
# Input 0 = screen video, input 1 = avatar video (green screen).
# ``screen`` is the screen source label; it defaults to the raw ``"0:v"`` input
# but is redirected to a preprocessed label when smart handling is engaged.
# --------------------------------------------------------------------------- #
def _layout_pip(
    W: int, H: int, diameter: int, margin: int, chroma: dict, screen: str = "0:v"
) -> str:
    """Full-screen recording with a circular avatar badge bottom-right."""
    x = max(0, W - diameter - margin)
    y = max(0, H - diameter - margin)
    return ";".join(
        [
            _fill_node(screen, "bg", W, H),
            _circular_avatar_node("1:v", "av", diameter, chroma),
            f"[bg][av]overlay=x={x}:y={y}:format=auto[comp]",
        ]
    )


def _layout_hook_intro(
    W: int, H: int, diameter: int, margin: int, chroma: dict, screen: str = "0:v"
) -> str:
    """Avatar full-frame for the first ``_HOOK_DURATION`` s, then a PiP badge."""
    radius = diameter // 2
    x = max(0, W - diameter - margin)
    y = max(0, H - diameter - margin)
    chroma_node = _chroma_filter(chroma)
    return ";".join(
        [
            _fill_node(screen, "bg", W, H),
            # One chroma pass, split into a full-frame copy and a PiP copy.
            f"[1:v]{chroma_node},format=rgba,split=2[a_raw][b_raw]",
            (
                f"[a_raw]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1[a_full]"
            ),
            (
                f"[b_raw]scale={diameter}:{diameter}:"
                f"force_original_aspect_ratio=increase,crop={diameter}:{diameter},"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='if(lte(hypot(X-{radius},Y-{radius}),{radius}),alpha(X,Y),0)'"
                f"[a_pip]"
            ),
            (
                f"[bg][a_full]overlay=0:0:format=auto:"
                f"enable='lt(t,{_HOOK_DURATION:g})'[tmp]"
            ),
            (
                f"[tmp][a_pip]overlay=x={x}:y={y}:format=auto:"
                f"enable='gte(t,{_HOOK_DURATION:g})'[comp]"
            ),
        ]
    )


def _layout_split(
    W: int, H: int, diameter: int, margin: int, chroma: dict, screen: str = "0:v"
) -> str:
    """Top half = screen recording, bottom half = chroma-keyed avatar."""
    half = H // 2
    return ";".join(
        [
            # Screen filled to full frame, then split into top + bottom-background.
            f"[{screen}]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,split=2[s_top][s_bot]",
            f"[s_top]crop={W}:{half}:0:0[top]",
            f"[s_bot]crop={W}:{half}:0:{half}[botbg]",
            # Avatar chroma-keyed and filled into the bottom half.
            f"[1:v]{_chroma_filter(chroma)},"
            f"scale={W}:{half}:force_original_aspect_ratio=increase,"
            f"crop={W}:{half},setsar=1,format=rgba[botfg]",
            "[botbg][botfg]overlay=0:0:format=auto[bot]",
            "[top][bot]vstack=inputs=2[comp]",
        ]
    )


_LAYOUTS: dict[str, Callable[..., str]] = {
    "hook_intro": _layout_hook_intro,
    "pip": _layout_pip,
    "split": _layout_split,
}

# Avatar-less composition: burns captions over the uploaded screen recording with
# NO HeyGen avatar overlay. It is intentionally NOT a member of ``_LAYOUTS`` (which
# are all avatar overlays consumed by ``compose_avatar_over_screen``); it is served
# by the dedicated ``compose_captions_over_screen`` path so a job can be produced
# with only the core backend (FFmpeg + local captioning), no paid avatar provider.
CAPTIONS_ONLY_LAYOUT: str = "captions_only"


def supported_layouts() -> frozenset[str]:
    """Every layout the compose stage can render (avatar overlays + captions-only).

    Single source of truth for the controller's fail-fast layout allowlist, so a
    layout added here is automatically accepted at job-create time and the two can
    never drift.
    """
    return frozenset(_LAYOUTS) | {CAPTIONS_ONLY_LAYOUT}


# --------------------------------------------------------------------------- #
# Brand-watermark fragments (pure string builders — unit-testable)
# --------------------------------------------------------------------------- #
def _clamp_opacity(opacity: float) -> float:
    """Clamp a requested watermark opacity into the valid ``[0.0, 1.0]`` range."""
    try:
        value = float(opacity)
    except (TypeError, ValueError):
        return _WATERMARK_OPACITY
    return max(0.0, min(1.0, value))


def _watermark_logo_width(
    scale: float, ref_width: int = _WATERMARK_REF_WIDTH
) -> int:
    """Pixel width for the logo: ``scale`` fraction of ``ref_width`` (>= 1 px)."""
    try:
        fraction = float(scale)
    except (TypeError, ValueError):
        fraction = _WATERMARK_SCALE
    return max(1, int(round(fraction * ref_width)))


def _watermark_overlay_xy(position: str, margin: int) -> tuple[str, str]:
    """Return the ``overlay`` x/y expressions for a corner/centre ``position``.

    Uses libavfilter's ``overlay`` variables so the logo's own (post-scale)
    dimensions never need to be known ahead of time: ``W``/``H`` are the main
    (background) size and ``w``/``h`` are the overlay (logo) size.

    Raises:
        ValueError: if ``position`` is not one of ``_WATERMARK_POSITIONS``.
    """
    if position not in _WATERMARK_POSITIONS:
        allowed = ", ".join(sorted(_WATERMARK_POSITIONS))
        raise ValueError(
            f"unsupported watermark position: {position!r} (allowed: {allowed})"
        )
    m = max(0, int(margin))
    mapping: dict[str, tuple[str, str]] = {
        "top_left": (f"{m}", f"{m}"),
        "top_right": (f"W-w-{m}", f"{m}"),
        "bottom_left": (f"{m}", f"H-h-{m}"),
        "bottom_right": (f"W-w-{m}", f"H-h-{m}"),
        "center": ("(W-w)/2", "(H-h)/2"),
    }
    return mapping[position]


def _watermark_logo_node(
    src: str, out: str, logo_width: int, opacity: float
) -> str:
    """Scale the logo to ``logo_width`` (aspect kept), RGBA-ify and fade its alpha.

    ``colorchannelmixer=aa=<opacity>`` multiplies the (already transparent-PNG)
    alpha channel uniformly, so a fully-opaque logo becomes ``opacity``-translucent
    while a transparent PNG keeps its cut-out shape.
    """
    aa = _clamp_opacity(opacity)
    return (
        f"[{src}]scale={logo_width}:-1,format=rgba,"
        f"colorchannelmixer=aa={aa:.4g}[{out}]"
    )


def _build_watermark_node(
    src_label: str,
    logo_input: str,
    out_label: str,
    *,
    position: str = _WATERMARK_POSITION,
    scale: float = _WATERMARK_SCALE,
    opacity: float = _WATERMARK_OPACITY,
    margin: int = _WATERMARK_MARGIN,
    ref_width: int = _WATERMARK_REF_WIDTH,
) -> str:
    """Build the ``;<logo>;<overlay>`` fragment that stamps the brand logo on top.

    Prepared to be appended AFTER the caption-burn node so the logo sits above the
    captions. ``src_label`` is the current video label (e.g. ``"final"``),
    ``logo_input`` is the logo's ffmpeg input pad (e.g. ``"3:v"``) and
    ``out_label`` is the resulting composited label (e.g. ``"wm"``).

    Raises:
        ValueError: if ``position`` is not one of ``_WATERMARK_POSITIONS``.
    """
    x, y = _watermark_overlay_xy(position, margin)
    logo_w = _watermark_logo_width(scale, ref_width)
    logo_node = _watermark_logo_node(logo_input, "wm_logo", logo_w, opacity)
    return (
        f";{logo_node};"
        f"[{src_label}][wm_logo]overlay=x={x}:y={y}:format=auto[{out_label}]"
    )


# --------------------------------------------------------------------------- #
# libass path escaping
# --------------------------------------------------------------------------- #
def _escape_ass_filter_path(p: str) -> str:
    """Escape an ``.ass`` path for use as an ``ass=`` filtergraph argument.

    abspath -> forward slashes -> backslash-escape every character that is
    special to ffmpeg's filtergraph parser so libass receives one intact
    filename argument regardless of platform:

    * ``:`` (Windows drive / filter option separator)
    * ``'`` (filtergraph quote)
    * ``[`` ``]`` ``;`` ``,`` (filtergraph structural delimiters)

    Normalising every backslash to a forward slash first means the path holds
    no literal backslashes, so the only backslashes present after this point
    are the escape prefixes added below -- there is nothing to double-escape.
    """
    escaped = os.path.abspath(p).replace("\\", "/")
    for meta in ("[", "]", ";", ",", ":", "'"):
        escaped = escaped.replace(meta, "\\" + meta)
    return escaped


# --------------------------------------------------------------------------- #
# ffmpeg / ffprobe binary + capability probes
# --------------------------------------------------------------------------- #
def _get_ffprobe_binary(ffmpeg: str | None = None) -> str:
    """Resolve the ffprobe binary, mirroring ``utils.get_ffmpeg_binary``.

    Prefer an ``ffprobe`` sitting next to the resolved ffmpeg, then the PATH,
    then a bare ``"ffprobe"`` so subprocess surfaces a concrete error at runtime.
    """
    binary = ffmpeg or utils.get_ffmpeg_binary()
    if binary and os.path.sep in binary:
        candidate = os.path.join(
            os.path.dirname(binary),
            "ffprobe" + (".exe" if binary.lower().endswith(".exe") else ""),
        )
        if os.path.exists(candidate):
            return candidate
    return shutil.which("ffprobe") or "ffprobe"


@functools.lru_cache(maxsize=8)
def ffmpeg_has_filter(name: str, ffmpeg: str | None = None) -> bool:
    """Return True if this FFmpeg build exposes the named filter.

    Probed once per (name, binary) via ``ffmpeg -filters`` and cached. Used to
    fail fast when caption burning is requested but the build lacks libass —
    the contract §10 preflight — instead of surfacing a cryptic
    ``No such filter: 'ass'`` deep inside the render.
    """
    binary = ffmpeg or utils.get_ffmpeg_binary()
    try:
        result = subprocess.run(
            [binary, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError) as exc:  # pragma: no cover - environment issue
        logger.warning(f"could not probe ffmpeg filters: {exc}")
        return False
    # Filter lines look like: " T.. ass              V->V  Render ASS subtitles".
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False


def _parse_fps(rate: str | None) -> float:
    """Parse an ffprobe ``r_frame_rate`` (``"30000/1001"``) into fps."""
    if not rate:
        return 0.0
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _probe_video(path: str, ffprobe: str | None = None) -> VideoInfo | None:
    """ffprobe ``path`` for width/height/duration/fps. ``None`` on any failure.

    Best-effort: probing is an optimisation for smart handling, never a hard
    dependency, so a missing ffprobe / unreadable file degrades gracefully
    (the caller then composites with the historical crop-to-fill behaviour).
    """
    if not path or not os.path.exists(path):
        return None
    binary = ffprobe or _get_ffprobe_binary()
    try:
        result = subprocess.run(
            [
                binary,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,duration",
                "-show_entries", "format=duration",
                "-of", "json",
                path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError) as exc:  # pragma: no cover - environment issue
        logger.warning(f"ffprobe failed for {path!r}: {exc}")
        return None
    if result.returncode != 0:
        logger.warning(
            f"ffprobe returned {result.returncode} for {path!r}: "
            f"{(result.stderr or '').strip()[:200]}"
        )
        return None
    try:
        data = json.loads(result.stdout or "{}")
    except (ValueError, TypeError) as exc:
        logger.warning(f"could not parse ffprobe json for {path!r}: {exc}")
        return None

    streams = data.get("streams") or []
    stream = streams[0] if streams else {}
    fmt = data.get("format") or {}

    def _as_float(*candidates: object) -> float:
        for value in candidates:
            if value in (None, "", "N/A"):
                continue
            try:
                return float(value)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                continue
        return 0.0

    width = int(_as_float(stream.get("width")))
    height = int(_as_float(stream.get("height")))
    duration = _as_float(stream.get("duration"), fmt.get("duration"))
    fps = _parse_fps(stream.get("r_frame_rate"))
    return VideoInfo(width=width, height=height, duration=duration, fps=fps)


# Precompiled parsers for freezedetect metadata emitted on stderr.
_FREEZE_START_RE = re.compile(r"freeze_start:\s*([0-9]+(?:\.[0-9]+)?)")
_FREEZE_END_RE = re.compile(r"freeze_end:\s*([0-9]+(?:\.[0-9]+)?)")


def _parse_leading_freeze_end(stderr: str, screen_duration: float) -> float:
    """From freezedetect stderr, return seconds of LEADING static to skip.

    Only a freeze that begins at (approximately) the very start of the clip is
    treated as trimmable lead-in. The trim is clamped so we never discard more
    than ``_FREEZE_MAX_TRIM_FRACTION`` of the recording.
    """
    starts = [float(m) for m in _FREEZE_START_RE.findall(stderr or "")]
    ends = [float(m) for m in _FREEZE_END_RE.findall(stderr or "")]
    if not starts or not ends:
        return 0.0
    # The first detected freeze must start at the head of the clip.
    if min(starts) > _FREEZE_START_EPS:
        return 0.0
    trim = min(ends)
    if screen_duration and screen_duration > 0:
        trim = min(trim, screen_duration * _FREEZE_MAX_TRIM_FRACTION)
    return max(0.0, trim)


def _detect_leading_freeze(
    screen_path: str,
    screen_duration: float = 0.0,
    ffmpeg: str | None = None,
    scan_seconds: float = _FREEZE_SCAN_S,
) -> float:
    """Return seconds of leading static to skip via ``-ss`` (0.0 if none/fail).

    Runs a cheap ``freezedetect`` analysis pass over the first ``scan_seconds``
    and parses the metadata FFmpeg logs to stderr. Entirely best-effort: any
    error (missing filter, unreadable file, non-zero exit) yields ``0.0`` and the
    recording is composited untrimmed.
    """
    if not screen_path or not os.path.exists(screen_path):
        return 0.0
    binary = ffmpeg or utils.get_ffmpeg_binary()
    command = [
        binary,
        "-hide_banner",
        "-t", f"{max(0.1, scan_seconds):.3f}",
        "-i", screen_path,
        "-vf", f"freezedetect=n={_FREEZE_NOISE_DB}:d={_FREEZE_MIN_DURATION:g}",
        "-map", "0:v:0",
        "-f", "null",
        os.devnull,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except (OSError, ValueError) as exc:  # pragma: no cover - environment issue
        logger.warning(f"freezedetect pass failed for {screen_path!r}: {exc}")
        return 0.0
    # freezedetect writes its metadata to stderr regardless of exit status.
    return _parse_leading_freeze_end(result.stderr or "", screen_duration)


class _ScreenPlan(NamedTuple):
    """Resolved smart-handling decisions for the screen recording."""

    trim_ss: float
    speed: float
    blur_pad: bool


def _plan_screen_handling(
    screen_path: str,
    width: int,
    height: int,
    *,
    target_duration_s: float | None,
    trim_freeze: bool,
    max_speed: float,
    blur_pad: bool,
    ffmpeg: str | None = None,
) -> _ScreenPlan:
    """Decide trim / speed-ramp / blur-pad for the screen recording.

    When ``target_duration_s`` is ``None`` we do NOT probe or run any extra
    ffmpeg pass — the recording is composited exactly as legacy callers expect,
    honouring only an explicitly-requested ``blur_pad``.
    """
    if target_duration_s is None:
        return _ScreenPlan(trim_ss=0.0, speed=1.0, blur_pad=blur_pad)

    info = _probe_video(screen_path, _get_ffprobe_binary(ffmpeg))
    trim_ss = 0.0
    if trim_freeze:
        trim_ss = _detect_leading_freeze(
            screen_path,
            screen_duration=info.duration if info else 0.0,
            ffmpeg=ffmpeg,
        )

    effective_duration = 0.0
    if info and info.duration > 0:
        effective_duration = max(0.0, info.duration - trim_ss)

    speed = _speed_factor(effective_duration, float(target_duration_s), max_speed)

    use_blur_pad = blur_pad
    if not use_blur_pad and info and info.width and info.height:
        use_blur_pad = _needs_blur_pad(info.width, info.height, width, height)

    logger.info(
        f"screen plan: dur={info.duration if info else 'unknown'}s "
        f"trim={trim_ss:.3f}s speed={speed:.3g}x blur_pad={use_blur_pad}"
    )
    return _ScreenPlan(trim_ss=trim_ss, speed=speed, blur_pad=use_blur_pad)


def _build_final_node(ass_path: str | None, in_label: str = "comp") -> str:
    """Append the caption-burn (or pass-through) node after ``[in_label]``.

    ``in_label`` defaults to ``comp``; when a VFX node is spliced in first the
    caller passes the VFX output label so captions burn on top of the effects.
    """
    if ass_path:
        esc = _escape_ass_filter_path(ass_path)
        fonts = _escape_ass_filter_path(utils.font_dir())
        return f";[{in_label}]ass={esc}:fontsdir={fonts}[final]"
    return f";[{in_label}]null[final]"


def _build_command(
    ffmpeg: str,
    screen_path: str,
    avatar_path: str,
    audio_path: str,
    output_file: str,
    filtergraph: str,
    codec: str,
    threads: int,
    fps: int,
    *,
    screen_ss: float = 0.0,
    music_path: str | None = None,
    watermark_path: str | None = None,
    video_map: str = "[final]",
    audio_map: str = "2:a",
) -> list[str]:
    """Assemble the full FFmpeg argv for a given video codec.

    Optional smart-handling knobs default to the historical behaviour: no input
    seek, no music input, no watermark input, screen/avatar/audio as inputs
    0/1/2, mapping the burned video ``[final]`` plus the narration ``2:a``.

    When present, the optional inputs are appended in a FIXED order so the
    filtergraph's pad indices stay stable: music becomes input 3 and the
    watermark logo becomes input 3 (no music) or 4 (with music).
    """
    command: list[str] = [ffmpeg, "-y"]
    if screen_ss and screen_ss > 0:
        # Input seek (before -i) skips leading static frames cheaply.
        command += ["-ss", f"{screen_ss:.3f}"]
    command += ["-i", screen_path, "-i", avatar_path, "-i", audio_path]
    if music_path:
        command += ["-i", music_path]
    if watermark_path:
        command += ["-i", watermark_path]
    command += [
        "-filter_complex", filtergraph,
        "-map", video_map,
        "-map", audio_map,
        "-c:v", codec,
        *live_encode_args(codec, fps),
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-threads", str(threads or 2),
        *_shortest_args(ffmpeg),
        "-movflags", "+faststart",
        output_file,
    ]
    return command


def _run_ffmpeg(command: list[str]) -> None:
    """Run FFmpeg once; raise ``RuntimeError(stderr)`` on a non-zero exit."""
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr or "ffmpeg compose failed")


# --------------------------------------------------------------------------- #
# B-roll cutaway filtergraph fragments (pure string builders — unit-testable)
#
# A composed reel (input 0) is book-ended with optional MUTED stock clips: an
# intro before the hook and/or an outro after. Each b-roll clip is normalised to
# the target frame (scale-to-cover + crop, setsar=1, fps, trimmed to
# ``max_broll_s``) and paired with a SILENT stereo audio segment so the concat
# filter (``v=1:a=1``) sees compatible streams for every segment. The main reel
# keeps its own full audio; only the cutaways are silenced.
# --------------------------------------------------------------------------- #
def _broll_video_node(
    src: str, out: str, width: int, height: int, fps: int, max_broll_s: float
) -> str:
    """Normalise a b-roll clip's video for concat: cover-crop, sar, fps, trim.

    Scale-to-cover + crop-to-fill to ``width`` x ``height`` (matching the main
    reel), pin the SAR/fps/pixel-format and hard-trim to ``max_broll_s`` seconds
    (resetting timestamps) so the segment is concat-compatible and never longer
    than the configured cap.
    """
    return (
        f"[{src}]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={fps},"
        f"trim=duration={max_broll_s:g},setpts=PTS-STARTPTS,format=yuv420p[{out}]"
    )


def _broll_silent_audio_node(
    src: str,
    out: str,
    max_broll_s: float,
    sample_rate: int = _BROLL_SAMPLE_RATE,
    channel_layout: str = _BROLL_CHANNEL_LAYOUT,
) -> str:
    """Trim + format one silent-audio segment for a b-roll clip.

    Takes a silence source pad, trims it to ``max_broll_s`` and coerces it to the
    canonical sample-rate + channel-layout so it matches the (also-coerced) main
    reel audio for the concat filter.
    """
    return (
        f"[{src}]atrim=duration={max_broll_s:g},asetpts=PTS-STARTPTS,"
        f"aformat=sample_rates={sample_rate}:channel_layouts={channel_layout}[{out}]"
    )


def _main_video_node(src: str, out: str, width: int, height: int, fps: int) -> str:
    """Normalise the main reel video (sar/fps/format) for concat compatibility.

    The composed reel is already ``width`` x ``height``; the cover-crop is a
    no-op there but guarantees a concat-safe stream even if the main input's
    geometry ever drifts.
    """
    return (
        f"[{src}]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p[{out}]"
    )


def _main_audio_node(
    src: str,
    out: str,
    sample_rate: int = _BROLL_SAMPLE_RATE,
    channel_layout: str = _BROLL_CHANNEL_LAYOUT,
) -> str:
    """Coerce the main reel audio to the canonical rate/layout for concat."""
    return (
        f"[{src}]aformat=sample_rates={sample_rate}:"
        f"channel_layouts={channel_layout}[{out}]"
    )


class _ConcatGraph(NamedTuple):
    """Result of ``_build_concat_graph``: the graph string + its output labels."""

    graph: str
    video_map: str
    audio_map: str


def _build_concat_graph(
    *,
    has_intro: bool,
    has_outro: bool,
    width: int,
    height: int,
    fps: int,
    max_broll_s: float,
    sample_rate: int = _BROLL_SAMPLE_RATE,
    channel_layout: str = _BROLL_CHANNEL_LAYOUT,
) -> _ConcatGraph:
    """Build the ``-filter_complex`` graph that concats intro/main/outro.

    Input pad ordering (kept in lock-step with ``_build_concat_command``):

    * input 0 ............. the composed main reel (video + audio)
    * inputs 1..N ......... the b-roll clips in play order (intro then outro)
    * input N+1 ........... a single ``anullsrc`` silence source

    The silence source is ``asplit`` into one branch per b-roll clip (a filter
    input pad may only be consumed once), each trimmed to ``max_broll_s``. The
    normalised segments are concatenated ``[intro?][main][outro?]`` via
    ``concat=n=...:v=1:a=1`` into ``[cv]``/``[ca]``.

    Raises:
        ValueError: if neither ``has_intro`` nor ``has_outro`` is set (the caller
            treats that as a no-op and must never reach the graph builder).
    """
    n_broll = int(has_intro) + int(has_outro)
    if n_broll == 0:
        raise ValueError("_build_concat_graph requires at least one b-roll clip")

    fragments: list[str] = [
        _main_video_node("0:v", "mv", width, height, fps),
        _main_audio_node("0:a", "ma", sample_rate, channel_layout),
    ]

    # Assign a video-input index to each b-roll clip in play order.
    broll_specs: list[tuple[str, int]] = []
    next_input = 1
    if has_intro:
        broll_specs.append(("intro", next_input))
        next_input += 1
    if has_outro:
        broll_specs.append(("outro", next_input))
        next_input += 1
    silent_input = next_input

    # Fan the single silence source out into one trimmed branch per b-roll clip.
    silent_labels: list[str] = []
    if n_broll == 1:
        fragments.append(
            _broll_silent_audio_node(
                f"{silent_input}:a", "sa0", max_broll_s, sample_rate, channel_layout
            )
        )
        silent_labels = ["sa0"]
    else:
        split_pads = "".join(f"[sa_in{i}]" for i in range(n_broll))
        fragments.append(f"[{silent_input}:a]asplit={n_broll}{split_pads}")
        for i in range(n_broll):
            fragments.append(
                _broll_silent_audio_node(
                    f"sa_in{i}", f"sa{i}", max_broll_s, sample_rate, channel_layout
                )
            )
            silent_labels.append(f"sa{i}")

    # Normalise each b-roll clip's video.
    for i, (_position, inp) in enumerate(broll_specs):
        fragments.append(
            _broll_video_node(f"{inp}:v", f"bv{i}", width, height, fps, max_broll_s)
        )

    # Assemble the concat input order: intro clips, then main, then outro clips.
    concat_inputs: list[tuple[str, str]] = []
    for i, (position, _inp) in enumerate(broll_specs):
        if position == "intro":
            concat_inputs.append((f"bv{i}", silent_labels[i]))
    concat_inputs.append(("mv", "ma"))
    for i, (position, _inp) in enumerate(broll_specs):
        if position == "outro":
            concat_inputs.append((f"bv{i}", silent_labels[i]))

    n = len(concat_inputs)
    pads = "".join(f"[{v}][{a}]" for v, a in concat_inputs)
    fragments.append(f"{pads}concat=n={n}:v=1:a=1[cv][ca]")

    return _ConcatGraph(graph=";".join(fragments), video_map="[cv]", audio_map="[ca]")


def _build_concat_command(
    ffmpeg: str,
    main_path: str,
    output_file: str,
    filtergraph: str,
    codec: str,
    threads: int,
    fps: int,
    *,
    intro_path: str | None,
    outro_path: str | None,
    max_broll_s: float,
    video_map: str,
    audio_map: str,
    sample_rate: int = _BROLL_SAMPLE_RATE,
    channel_layout: str = _BROLL_CHANNEL_LAYOUT,
) -> list[str]:
    """Assemble the full FFmpeg argv for the b-roll concat.

    Inputs are appended in the FIXED order the graph builder assumes: main reel
    (input 0), then intro / outro clips, then a single ``lavfi`` ``anullsrc``
    silence source (its ``-t`` bounds the generated silence to ``max_broll_s``).
    No ``-shortest`` — the whole concatenated timeline is written.
    """
    command: list[str] = [ffmpeg, "-y", "-i", main_path]
    if intro_path:
        command += ["-i", intro_path]
    if outro_path:
        command += ["-i", outro_path]
    command += [
        "-f", "lavfi",
        "-t", f"{max_broll_s:g}",
        "-i", f"anullsrc=channel_layout={channel_layout}:sample_rate={sample_rate}",
        "-filter_complex", filtergraph,
        "-map", video_map,
        "-map", audio_map,
        "-c:v", codec,
        *live_encode_args(codec, fps),
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-threads", str(threads or 2),
        "-movflags", "+faststart",
        output_file,
    ]
    return command


def concat_with_broll(
    main_path: str,
    output_file: str,
    *,
    intro_path: str | None = None,
    outro_path: str | None = None,
    max_broll_s: float = _BROLL_MAX_S,
    aspect: VideoAspect = VideoAspect.portrait,
    fps: int = 30,
    threads: int = 2,
) -> str:
    """Splice muted intro/outro b-roll cutaways around the composed reel.

    Each supplied clip is normalised to the target frame (scale-to-cover + crop
    to the ``aspect`` resolution, ``setsar=1``, ``fps``, hard-trimmed to
    ``max_broll_s``) and given a SILENT stereo audio track, then the segments are
    concatenated ``[intro?][main][outro?]`` with the ``concat`` filter
    (``v=1:a=1``) and re-encoded interchange-friendly
    (``-pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart``). The main reel
    keeps its full audio + burned captions; only the cutaways are muted.

    When BOTH ``intro_path`` and ``outro_path`` are ``None`` this is a no-op and
    ``main_path`` is returned unchanged (no ffmpeg is invoked).

    The hardware video codec is used first and falls back once to libx264 (and is
    disabled for the rest of the process) if it fails at runtime, mirroring
    ``compose_avatar_over_screen``.

    Note:
        This helper RAISES on failure (missing input / non-zero ffmpeg). B-roll is
        an OPTIONAL creative overlay, so the ORCHESTRATOR is expected to call it
        best-effort — a cutaway failure must degrade to the plain reel and never
        fail the job. The main reel (input 0) is required to carry an audio track.

    Raises:
        FileNotFoundError: if ``main_path`` or a supplied b-roll clip is missing.
        ValueError: if ``max_broll_s`` is not positive.
        RuntimeError: if FFmpeg exits non-zero (stderr is the message).
    """
    # No cutaways requested — nothing to do, hand back the reel untouched.
    if intro_path is None and outro_path is None:
        return main_path

    if max_broll_s <= 0:
        raise ValueError(f"max_broll_s must be positive, got {max_broll_s!r}")

    if not main_path or not os.path.exists(main_path):
        raise FileNotFoundError(f"concat main input not found: {main_path!r}")

    for label, path in (("intro", intro_path), ("outro", outro_path)):
        if path is not None and not os.path.exists(path):
            raise FileNotFoundError(f"concat {label} b-roll not found: {path!r}")

    width, height = VideoAspect(aspect).to_resolution()
    ffmpeg = utils.get_ffmpeg_binary()

    concat = _build_concat_graph(
        has_intro=intro_path is not None,
        has_outro=outro_path is not None,
        width=width,
        height=height,
        fps=fps,
        max_broll_s=max_broll_s,
    )

    codec = video_service._get_effective_video_codec()

    logger.info(
        f"splicing b-roll: intro={'yes' if intro_path else 'no'}, "
        f"outro={'yes' if outro_path else 'no'}, size={width}x{height}, "
        f"codec={codec}, max_broll={max_broll_s:g}s"
    )

    def _concat_with(codec_name: str) -> None:
        _run_ffmpeg(
            _build_concat_command(
                ffmpeg,
                main_path,
                output_file,
                concat.graph,
                codec_name,
                threads,
                fps,
                intro_path=intro_path,
                outro_path=outro_path,
                max_broll_s=max_broll_s,
                video_map=concat.video_map,
                audio_map=concat.audio_map,
            )
        )
        _encodes.count("broll")

    try:
        _concat_with(codec)
        return output_file
    except RuntimeError as exc:
        # Retry once with libx264 and disable the failing hardware codec for the
        # rest of the process (mirrors compose_avatar_over_screen).
        if codec == _LIBX264:
            raise
        logger.warning(
            f"b-roll concat failed with codec {codec}, retrying with "
            f"{_LIBX264}: {exc}"
        )
        _concat_with(_LIBX264)
        video_service._disable_runtime_video_codec(codec, str(exc))
        return output_file


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def compose_avatar_over_screen(
    screen_path: str,
    avatar_path: str,
    audio_path: str,
    output_file: str,
    *,
    layout: str = "pip",
    ass_path: str | None = None,
    aspect: VideoAspect = VideoAspect.portrait,
    chroma_color: str = "0x00FF00",
    chroma_similarity: float = 0.18,
    chroma_blend: float = 0.10,
    pip_diameter: int = _PIP_DIAMETER,
    pip_margin: int = _PIP_MARGIN,
    threads: int = 2,
    fps: int = 30,
    target_duration_s: float | None = None,
    trim_freeze: bool = True,
    max_speed: float = _MAX_SPEED,
    blur_pad: bool = False,
    music_path: str | None = None,
    watermark_path: str | None = None,
    watermark_position: str = _WATERMARK_POSITION,
    watermark_opacity: float = _WATERMARK_OPACITY,
    watermark_scale: float = _WATERMARK_SCALE,
    watermark_margin: int = _WATERMARK_MARGIN,
    camera_motion: str = "none",
    effects: list[str] | None = None,
    vfx_intensity: int = 50,
) -> str:
    """Compose the avatar over the screen recording and return ``output_file``.

    Builds the filtergraph via ``_LAYOUTS[layout]`` up to ``[comp]``, appends the
    libass caption-burn node last, then encodes with the configured hardware
    codec — falling back to libx264 (and disabling the codec for the rest of the
    process) if the hardware encoder fails at runtime.

    Smart screen-recording handling (all opt-in, legacy-safe defaults):

    * ``target_duration_s`` — when set, the screen recording is ``ffprobe``-probed
      and, if it runs longer than this target, slowed with ``setpts`` (capped at
      ``max_speed``) so it fits; an un-croppable aspect is blur-padded instead of
      hard-cropped. When ``None`` NO probe/extra ffmpeg pass runs.
    * ``trim_freeze`` — skip leading static frames via a ``freezedetect`` ``-ss``
      seek (only consulted when ``target_duration_s`` is set).
    * ``blur_pad`` — force the blurred scale-pad background even without a probe.
    * ``music_path`` — duck background music under the voiceover
      (``sidechaincompress``) and ``loudnorm`` the mix; when ``None`` the original
      narration is mapped unchanged.

    Brand watermark (optional logo overlay, legacy-safe defaults):

    * ``watermark_path`` — a (typically transparent PNG) brand logo. When set, it
      is scaled to ``watermark_scale`` of the 1080 reference width, RGBA-ified,
      faded to ``watermark_opacity`` and overlaid at ``watermark_position`` (one of
      ``top_left|top_right|bottom_left|bottom_right|center``) with a
      ``watermark_margin`` px inset — as the LAST filtergraph node, so the logo
      sits on top of the burned captions. When ``None`` the filtergraph and the
      ffmpeg command are byte-for-byte identical to the pre-watermark behaviour.

    Raises:
        ValueError: if ``layout`` is not one of ``_LAYOUTS``, or ``watermark_path``
            is set with a ``watermark_position`` outside ``_WATERMARK_POSITIONS``.
        FileNotFoundError: if any required input file is missing.
        RuntimeError: if FFmpeg exits non-zero (stderr is the message), or if a
            requested feature needs a filter this FFmpeg build lacks.
    """
    if layout not in _LAYOUTS:
        allowed = ", ".join(sorted(_LAYOUTS))
        raise ValueError(
            f"unsupported compose layout: {layout!r} (allowed: {allowed})"
        )

    # Validate the watermark position up-front (fail fast, before any I/O) so a
    # bad enum never reaches the filtergraph builder mid-render.
    if watermark_path is not None and watermark_position not in _WATERMARK_POSITIONS:
        allowed = ", ".join(sorted(_WATERMARK_POSITIONS))
        raise ValueError(
            f"unsupported watermark position: {watermark_position!r} "
            f"(allowed: {allowed})"
        )

    for label, path in (
        ("screen", screen_path),
        ("avatar", avatar_path),
        ("audio", audio_path),
    ):
        if not path or not os.path.exists(path):
            raise FileNotFoundError(f"compose {label} input not found: {path!r}")

    if ass_path and not os.path.exists(ass_path):
        # A missing caption file would silently drop the burn node; fail loudly.
        raise FileNotFoundError(f"compose caption input not found: {ass_path!r}")

    if music_path and not os.path.exists(music_path):
        raise FileNotFoundError(f"compose music input not found: {music_path!r}")

    if watermark_path and not os.path.exists(watermark_path):
        raise FileNotFoundError(
            f"compose watermark input not found: {watermark_path!r}"
        )

    ffmpeg = utils.get_ffmpeg_binary()

    if ass_path and not ffmpeg_has_filter("ass", ffmpeg):
        # Burning karaoke captions needs an FFmpeg built with libass. Fail with
        # an actionable message here rather than letting the render die on an
        # opaque "No such filter: 'ass'" mid-pipeline (contract §10 preflight).
        raise RuntimeError(
            "caption burning requires an FFmpeg built with libass "
            "(--enable-libass), but the current binary lacks the 'ass' filter. "
            "Install a libass-enabled FFmpeg or create the job without captions."
        )

    if music_path:
        for needed in ("sidechaincompress", "loudnorm"):
            if not ffmpeg_has_filter(needed, ffmpeg):
                raise RuntimeError(
                    f"background-music ducking requires the {needed!r} filter, "
                    f"which the current FFmpeg build lacks. Compose without music "
                    f"or install a fuller FFmpeg."
                )

    width, height = VideoAspect(aspect).to_resolution()
    chroma = {
        "color": chroma_color,
        "similarity": chroma_similarity,
        "blend": chroma_blend,
    }

    # Resolve smart screen-recording handling (probe/freezedetect only when a
    # target duration is supplied — legacy callers pay nothing).
    plan = _plan_screen_handling(
        screen_path,
        width,
        height,
        target_duration_s=target_duration_s,
        trim_freeze=trim_freeze,
        max_speed=max_speed,
        blur_pad=blur_pad,
        ffmpeg=ffmpeg,
    )

    prep_graph, screen_label = _build_screen_prep(
        plan.speed, plan.blur_pad, width, height
    )

    base_graph = _LAYOUTS[layout](
        width, height, pip_diameter, pip_margin, chroma, screen=screen_label
    )
    # Splice the camera-motion + VFX node between [comp] and the caption burn so
    # effects render UNDER the captions. When nothing is selected the node is
    # empty and the caption burn reads straight from [comp].
    from app.services.compose.vfx import build_vfx_node

    vfx_node, fx_label = build_vfx_node(
        camera_motion,
        effects,
        in_label="comp",
        out_label="cfx",
        intensity=vfx_intensity,
        fps=fps,
        width=width,
        height=height,
        # Composed clip length -> frame-accurate, effects-core kernel-backed
        # camera fragments (falls back to the legacy fragments when None).
        duration_s=target_duration_s,
    )
    filtergraph = base_graph + vfx_node + _build_final_node(ass_path, in_label=fx_label)
    if prep_graph:
        filtergraph = prep_graph + ";" + filtergraph

    # Optional brand-watermark overlay, appended AFTER the caption burn so the
    # logo sits on top. The logo is the LAST ffmpeg input (input 3, or 4 when
    # background music also occupies input 3), keeping every other pad stable.
    video_map = "[final]"
    if watermark_path:
        watermark_input = 4 if music_path else 3
        filtergraph += _build_watermark_node(
            "final",
            f"{watermark_input}:v",
            "wm",
            position=watermark_position,
            scale=watermark_scale,
            opacity=watermark_opacity,
            margin=watermark_margin,
        )
        video_map = "[wm]"

    audio_map = "2:a"
    if music_path:
        audio_graph, audio_out = _build_audio_graph()
        filtergraph = filtergraph + ";" + audio_graph
        audio_map = f"[{audio_out}]"

    codec = video_service._get_effective_video_codec()

    logger.info(
        f"composing avatar reel: layout={layout}, size={width}x{height}, "
        f"codec={codec}, captions={'yes' if ass_path else 'no'}, "
        f"music={'yes' if music_path else 'no'}, "
        f"watermark={watermark_position if watermark_path else 'no'}, "
        f"trim={plan.trim_ss:.3f}s, speed={plan.speed:.3g}x, "
        f"blur_pad={plan.blur_pad}"
    )

    def _compose_with(codec_name: str) -> None:
        _run_ffmpeg(
            _build_command(
                ffmpeg,
                screen_path,
                avatar_path,
                audio_path,
                output_file,
                filtergraph,
                codec_name,
                threads,
                fps,
                screen_ss=plan.trim_ss,
                music_path=music_path,
                watermark_path=watermark_path,
                video_map=video_map,
                audio_map=audio_map,
            )
        )
        _encodes.count("compose")

    try:
        _compose_with(codec)
        return output_file
    except RuntimeError as exc:
        # Hardware encoders depend on GPU/driver/runtime availability that the
        # encoder-list probe cannot fully verify. Retry once with libx264 and
        # disable the failing codec for the rest of this process, mirroring
        # video._write_videofile_with_codec_fallback.
        if codec == _LIBX264:
            raise
        logger.warning(
            f"compose failed with codec {codec}, retrying with {_LIBX264}: {exc}"
        )
        _compose_with(_LIBX264)
        video_service._disable_runtime_video_codec(codec, str(exc))
        return output_file


# --------------------------------------------------------------------------- #
# Captions-only (avatar-less) compositor
#
# Renders the uploaded screen recording full-frame with burned-in captions and
# the reel's own narration audio — NO HeyGen avatar. Input order differs from the
# avatar path because there is no avatar input: screen=0, audio=1, then optional
# music (2) and the watermark logo (2 with no music, else 3). This keeps every
# filtergraph pad index stable, exactly like ``_build_command``.
# --------------------------------------------------------------------------- #
def _build_captions_command(
    ffmpeg: str,
    screen_path: str,
    audio_path: str,
    output_file: str,
    filtergraph: str,
    codec: str,
    threads: int,
    fps: int,
    *,
    music_path: str | None = None,
    watermark_path: str | None = None,
    video_map: str = "[final]",
    audio_map: str = "1:a",
) -> list[str]:
    """Assemble the FFmpeg argv for the avatar-less captions-only compose."""
    command: list[str] = [ffmpeg, "-y", "-i", screen_path, "-i", audio_path]
    if music_path:
        command += ["-i", music_path]
    if watermark_path:
        command += ["-i", watermark_path]
    command += [
        "-filter_complex", filtergraph,
        "-map", video_map,
        "-map", audio_map,
        "-c:v", codec,
        *live_encode_args(codec, fps),
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-threads", str(threads or 2),
        *_shortest_args(ffmpeg),
        "-movflags", "+faststart",
        output_file,
    ]
    return command


def compose_captions_over_screen(
    screen_path: str,
    audio_path: str,
    output_file: str,
    *,
    ass_path: str | None = None,
    aspect: VideoAspect = VideoAspect.portrait,
    threads: int = 2,
    fps: int = 30,
    music_path: str | None = None,
    watermark_path: str | None = None,
    watermark_position: str = _WATERMARK_POSITION,
    watermark_opacity: float = _WATERMARK_OPACITY,
    watermark_scale: float = _WATERMARK_SCALE,
    watermark_margin: int = _WATERMARK_MARGIN,
    camera_motion: str = "none",
    effects: list[str] | None = None,
    vfx_intensity: int = 50,
) -> str:
    """Compose the screen recording with burned captions and NO avatar overlay.

    The screen recording is scaled+cropped to fill the target frame, optional
    camera-motion / VFX are spliced under the captions, the ``.ass`` karaoke
    captions are burned last, an optional brand watermark is stamped on top, and
    the supplied narration ``audio_path`` (the screen recording's own extracted
    audio, or a user voiceover) is muxed — with optional background-music ducking.

    This path needs only FFmpeg (+ libass for captions); it never touches HeyGen
    or any avatar provider. Returns ``output_file``.

    Raises:
        FileNotFoundError: a required input (screen/audio) or optional artifact
            (captions/music/watermark) path was supplied but does not exist.
        RuntimeError: FFmpeg exited non-zero, or a requested feature needs a
            filter this FFmpeg build lacks.
        ValueError: ``watermark_position`` is outside ``_WATERMARK_POSITIONS``.
    """
    if watermark_path is not None and watermark_position not in _WATERMARK_POSITIONS:
        allowed = ", ".join(sorted(_WATERMARK_POSITIONS))
        raise ValueError(
            f"unsupported watermark position: {watermark_position!r} "
            f"(allowed: {allowed})"
        )

    for label, path in (("screen", screen_path), ("audio", audio_path)):
        if not path or not os.path.exists(path):
            raise FileNotFoundError(f"compose {label} input not found: {path!r}")
    if ass_path and not os.path.exists(ass_path):
        raise FileNotFoundError(f"compose caption input not found: {ass_path!r}")
    if music_path and not os.path.exists(music_path):
        raise FileNotFoundError(f"compose music input not found: {music_path!r}")
    if watermark_path and not os.path.exists(watermark_path):
        raise FileNotFoundError(
            f"compose watermark input not found: {watermark_path!r}"
        )

    ffmpeg = utils.get_ffmpeg_binary()

    if ass_path and not ffmpeg_has_filter("ass", ffmpeg):
        raise RuntimeError(
            "caption burning requires an FFmpeg built with libass "
            "(--enable-libass), but the current binary lacks the 'ass' filter. "
            "Install a libass-enabled FFmpeg or create the job without captions."
        )
    if music_path:
        for needed in ("sidechaincompress", "loudnorm"):
            if not ffmpeg_has_filter(needed, ffmpeg):
                raise RuntimeError(
                    f"background-music ducking requires the {needed!r} filter, "
                    f"which the current FFmpeg build lacks."
                )

    width, height = VideoAspect(aspect).to_resolution()

    # Fill the screen recording to the target frame, splice camera-motion / VFX
    # under the captions, then burn the captions as the final video node.
    from app.services.compose.vfx import build_vfx_node

    base_graph = _fill_node("0:v", "comp", width, height)
    vfx_node, fx_label = build_vfx_node(
        camera_motion,
        effects,
        in_label="comp",
        out_label="cfx",
        intensity=vfx_intensity,
        fps=fps,
        width=width,
        height=height,
    )
    filtergraph = base_graph + vfx_node + _build_final_node(ass_path, in_label=fx_label)

    # Optional watermark on top of the burned captions. With no avatar input the
    # logo is input 2 (no music) or 3 (music occupies input 2).
    video_map = "[final]"
    if watermark_path:
        watermark_input = 3 if music_path else 2
        filtergraph += _build_watermark_node(
            "final",
            f"{watermark_input}:v",
            "wm",
            position=watermark_position,
            scale=watermark_scale,
            opacity=watermark_opacity,
            margin=watermark_margin,
        )
        video_map = "[wm]"

    # Narration is input 1; background music (when present) is input 2.
    audio_map = "1:a"
    if music_path:
        audio_graph, audio_out = _build_audio_graph(voice_input=1, music_input=2)
        filtergraph = filtergraph + ";" + audio_graph
        audio_map = f"[{audio_out}]"

    codec = video_service._get_effective_video_codec()

    logger.info(
        f"composing captions-only reel: size={width}x{height}, codec={codec}, "
        f"captions={'yes' if ass_path else 'no'}, "
        f"music={'yes' if music_path else 'no'}, "
        f"watermark={watermark_position if watermark_path else 'no'}"
    )

    def _compose_with(codec_name: str) -> None:
        _run_ffmpeg(
            _build_captions_command(
                ffmpeg,
                screen_path,
                audio_path,
                output_file,
                filtergraph,
                codec_name,
                threads,
                fps,
                music_path=music_path,
                watermark_path=watermark_path,
                video_map=video_map,
                audio_map=audio_map,
            )
        )
        _encodes.count("compose")

    try:
        _compose_with(codec)
        return output_file
    except RuntimeError as exc:
        if codec == _LIBX264:
            raise
        logger.warning(
            f"captions-only compose failed with codec {codec}, "
            f"retrying with {_LIBX264}: {exc}"
        )
        _compose_with(_LIBX264)
        video_service._disable_runtime_video_codec(codec, str(exc))
        return output_file
