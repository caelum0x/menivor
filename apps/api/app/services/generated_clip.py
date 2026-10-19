"""Build the WolfCut ``GeneratedClip`` descriptor for a finished ReelForge job.

The generate->edit seam (``EDITING-SUITE-PLAN.md`` §4 / Phase 1): when a job
finishes with a usable output, the completion stage emits a small descriptor
that the desktop editor (WolfCut) wraps into a minimal ``wolfcut.json`` — one
media item, one clip on one video track, plus a captions track when the job
carried ElevenLabs timing — and opens like any other project.

The dict this module produces mirrors the WolfCut host's ``GeneratedClip``
struct (``wolfcut/desktop/src-tauri/src/projects.rs`` / ``src/lib/engine.ts``)
*exactly*, in camelCase, so the desktop deserialises it without translation:

    {src, name, width, height, rateNum, rateDen, duration, hasAudio,
     videoCodec, audioCodec, captions: [{start, end, text}, ...]}

Everything here is best-effort and JSON-serialisable: a probe or caption-timing
hiccup degrades the descriptor (falling back to the job's aspect resolution)
rather than failing the render. All heavy imports (ffprobe, caption grouping)
are performed lazily so importing this module stays cheap for the API layer.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

__all__ = [
    "probe_media_descriptor",
    "caption_segments_from_words",
    "descriptor_from_job",
    "fallback_descriptor",
]

# The compose stage re-encodes every reel to an integer frame rate with
# ``libx264`` (H.264) video and AAC audio (see
# ``compose/compose_ffmpeg.py`` — ``-c:v libx264 -c:a aac``). These are the
# honest defaults used only when a probe of the actual output is unavailable
# (e.g. surfacing the descriptor from a persisted job whose file is remote).
_DEFAULT_RATE_NUM: int = 30
_DEFAULT_RATE_DEN: int = 1
_DEFAULT_VIDEO_CODEC: str = "h264"
_DEFAULT_AUDIO_CODEC: str = "aac"


def _parse_rate_fraction(rate: str | None) -> tuple[int, int]:
    """Parse an ffprobe ``r_frame_rate`` (``"30000/1001"``) into a fraction.

    Returns ``(num, den)`` as the engine works in exact rationals. Falls back to
    the compose default on a blank/zero/malformed value so a callers always gets
    a usable, non-zero denominator.
    """
    if not rate:
        return _DEFAULT_RATE_NUM, _DEFAULT_RATE_DEN
    try:
        if "/" in rate:
            num_s, den_s = rate.split("/", 1)
            num, den = int(num_s), int(den_s)
        else:
            num, den = int(round(float(rate))), 1
    except (TypeError, ValueError):
        return _DEFAULT_RATE_NUM, _DEFAULT_RATE_DEN
    if num <= 0 or den <= 0:
        return _DEFAULT_RATE_NUM, _DEFAULT_RATE_DEN
    return num, den


def probe_media_descriptor(path: str) -> dict[str, Any]:
    """ffprobe ``path`` for the descriptor's media metadata (best-effort).

    Returns a dict with ``width``, ``height``, ``rateNum``, ``rateDen``,
    ``duration``, ``hasAudio``, ``videoCodec`` and ``audioCodec``. On any
    failure returns ``{}`` so the caller falls back to the job's aspect
    resolution and the compose defaults. Uses the compose module's ffprobe
    binary resolution so it honours the same toolchain the render used.
    """
    if not path:
        return {}
    import json
    import subprocess

    try:
        from app.services.compose.compose_ffmpeg import _get_ffprobe_binary

        ffprobe = _get_ffprobe_binary()
    except Exception:  # noqa: BLE001 - fall back to PATH ffprobe
        ffprobe = "ffprobe"

    command = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        path,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not result.stdout:
            logger.warning(f"ffprobe of {path!r} returned no usable output")
            return {}
        probe = json.loads(result.stdout)
    except Exception as exc:  # noqa: BLE001 - probing is best-effort
        logger.warning(f"could not probe {path!r} for a clip descriptor: {exc}")
        return {}

    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        return {}

    rate_num, rate_den = _parse_rate_fraction(video.get("r_frame_rate"))
    try:
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
    except (TypeError, ValueError):
        width, height = 0, 0
    if width <= 0 or height <= 0:
        return {}

    duration: float | None = None
    raw_duration = (probe.get("format") or {}).get("duration") or video.get("duration")
    try:
        if raw_duration is not None:
            duration = float(raw_duration)
            if duration <= 0:
                duration = None
    except (TypeError, ValueError):
        duration = None

    return {
        "width": width,
        "height": height,
        "rateNum": rate_num,
        "rateDen": rate_den,
        "duration": duration,
        "hasAudio": audio is not None,
        "videoCodec": str(video.get("codec_name") or _DEFAULT_VIDEO_CODEC),
        "audioCodec": (
            str(audio.get("codec_name")) if audio is not None else None
        ),
    }


def caption_segments_from_words(
    words: Any, caption_style: str | None = None
) -> list[dict[str, Any]]:
    """Group ``ctx['words']`` timing into caption segments (best-effort).

    ``words`` is the job's authoritative ElevenLabs/TTS timing — a list of
    ``[text, start, end]`` (§8 timing authority). It is grouped into the same
    CapCut-style phrase lines the burned-in ASS uses, then flattened to
    ``[{start, end, text}]`` on the reel's own clock. Honouring videogen's
    single-source-of-truth rule, presence of these segments tells the editor to
    lay them on a captions track and never re-transcribe the asset. Returns
    ``[]`` when there is no usable timing (a job-less/silent clip), which leaves
    the editor free to run local Whisper instead.
    """
    if not words:
        return []
    try:
        from app.services.captions.words import (
            WordTiming,
            group_words_into_phrases,
        )
    except Exception as exc:  # noqa: BLE001 - captions are optional
        logger.warning(f"could not import caption grouping for descriptor: {exc}")
        return []

    timings: list[WordTiming] = []
    for item in words:
        try:
            text, start, end = item[0], float(item[1]), float(item[2])
        except (IndexError, TypeError, ValueError):
            continue
        timings.append(WordTiming(str(text), start, end))
    if not timings:
        return []

    segments: list[dict[str, Any]] = []
    for phrase in group_words_into_phrases(timings):
        if not phrase:
            continue
        text = " ".join(word.text for word in phrase).strip()
        if not text:
            continue
        segments.append(
            {
                "start": float(phrase[0].start),
                "end": float(phrase[-1].end),
                "text": text,
            }
        )
    return segments


def _aspect_resolution(aspect: str | None) -> tuple[int, int]:
    """Best-effort (width, height) for a params aspect id, defaulting portrait."""
    try:
        from app.models.schema import VideoAspect

        return VideoAspect(str(aspect)).to_resolution()
    except Exception:  # noqa: BLE001 - unknown aspect -> portrait default
        return 1080, 1920


def _clip_name(params: Any) -> str:
    """A display name for the media, its clip and the project."""
    subject = str(getattr(params, "video_subject", "") or "").strip()
    return (subject or "ReelForge video")[:100]


def _assemble(
    *,
    name: str,
    src: str | None,
    media: dict[str, Any],
    aspect: str | None,
    captions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge probed media (with aspect/compose fallbacks) into the descriptor."""
    width = int(media.get("width") or 0)
    height = int(media.get("height") or 0)
    if width <= 0 or height <= 0:
        width, height = _aspect_resolution(aspect)

    descriptor: dict[str, Any] = {
        "name": name,
        "width": width,
        "height": height,
        "rateNum": int(media.get("rateNum") or _DEFAULT_RATE_NUM),
        "rateDen": int(media.get("rateDen") or _DEFAULT_RATE_DEN),
        "duration": media.get("duration"),
        "hasAudio": bool(media.get("hasAudio", True)),
        "videoCodec": media.get("videoCodec") or _DEFAULT_VIDEO_CODEC,
        "audioCodec": media.get("audioCodec") or _DEFAULT_AUDIO_CODEC,
        "captions": captions,
    }
    if src is not None:
        descriptor["src"] = src
    return descriptor


def descriptor_from_job(
    params: Any, ctx: dict[str, Any], *, src: str | None = None
) -> dict[str, Any]:
    """Assemble the ``GeneratedClip`` descriptor from a job's params + context.

    ``ctx`` is the completed pipeline context: it carries the compose stage's
    probe of the final output (``clip_media``, set by ``stage_compose``) and the
    authoritative word timing (``words``). Missing probe data falls back to the
    job's aspect resolution and the compose defaults; missing word timing yields
    an empty captions list. ``src`` (an R2 URL or local path) is included only
    when provided, so the same base descriptor can be persisted without a URL
    and have a freshly-presigned one injected per read.
    """
    media = ctx.get("clip_media")
    media = media if isinstance(media, dict) else {}
    captions = caption_segments_from_words(
        ctx.get("words"), getattr(params, "caption_style", None)
    )
    return _assemble(
        name=_clip_name(params),
        src=src,
        media=media,
        aspect=getattr(params, "aspect", None),
        captions=captions,
    )


def fallback_descriptor(
    *, name: str, src: str, aspect: str | None, media: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A descriptor for a completed job with no persisted media metadata.

    Used by the pull path (``GET /jobs/{id}``) for jobs rendered before the
    descriptor was persisted: the aspect gives the resolution and the compose
    defaults supply the rate/codecs, so an older reel still opens in the editor.
    Carries no captions (the editor can transcribe locally on demand).
    """
    return _assemble(
        name=name or "ReelForge video",
        src=src,
        media=media if isinstance(media, dict) else {},
        aspect=aspect,
        captions=[],
    )
