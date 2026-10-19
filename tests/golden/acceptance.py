"""Pure acceptance assertions for the ReelForge golden-test harness.

Every helper here is a *pure* function over one of two inputs:

* an **ffprobe JSON** object (``ffprobe -show_format -show_streams -print_format
  json``), i.e. the dict produced by :func:`json.loads` on ffprobe's stdout; or
* a **word-timing array** — a sequence of items each exposing ``text``/``start``
  /``end`` (the :class:`app.services.tts.elevenlabs_timestamps.WordTiming`
  NamedTuple, a ``(text, start, end)`` tuple, or a mapping with those keys).

No third-party imports, no subprocess, no file I/O for the ffprobe helpers, so
this module is import-safe and unit-testable on a hermetic CI box that has no
media stack at all. The one exception — :func:`moov_precedes_mdat` — reads raw
MP4 bytes (still stdlib-only, no ffmpeg) to verify ``+faststart`` streaming
layout, which ffprobe does not surface in its JSON.

These encode the contractual Definition of Done (CTO plan §8.1):
correct resolution, H.264 + faststart, minimum bitrate, duration window,
caption drift ≤ 50 ms, hook ≤ 2.5 s, avatar/audio duration delta ≤ 150 ms.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "AcceptanceError",
    "video_stream",
    "assert_resolution",
    "assert_h264_faststart",
    "assert_min_bitrate",
    "assert_duration_window",
    "assert_caption_drift",
    "assert_hook_within",
    "assert_avatar_audio_delta",
    "moov_precedes_mdat",
]


class AcceptanceError(AssertionError):
    """Raised when a golden-acceptance check fails.

    Subclasses :class:`AssertionError` so it reads naturally under pytest while
    still being catchable as a distinct type by callers that want to aggregate
    failures across a batch of golden jobs.
    """


# --------------------------------------------------------------------------- #
# ffprobe JSON helpers
# --------------------------------------------------------------------------- #
def video_stream(probe: Mapping[str, Any]) -> dict:
    """Return the first ``codec_type == "video"`` stream from an ffprobe JSON.

    Raises:
        AcceptanceError: if ``probe`` has no video stream.
    """
    if not isinstance(probe, Mapping):
        raise AcceptanceError(f"ffprobe result is not a mapping: {type(probe)!r}")
    streams = probe.get("streams") or []
    for stream in streams:
        if isinstance(stream, Mapping) and stream.get("codec_type") == "video":
            return dict(stream)
    raise AcceptanceError("ffprobe JSON contains no video stream")


def _format_bit_rate(probe: Mapping[str, Any]) -> float | None:
    """Best-effort container/stream bitrate in bits-per-second, or ``None``."""
    fmt = probe.get("format") if isinstance(probe, Mapping) else None
    if isinstance(fmt, Mapping):
        raw = fmt.get("bit_rate")
        if raw not in (None, "", "N/A"):
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    # Fall back to the video stream's own bit_rate when the container omits it.
    try:
        vraw = video_stream(probe).get("bit_rate")
    except AcceptanceError:
        return None
    if vraw not in (None, "", "N/A"):
        try:
            return float(vraw)
        except (TypeError, ValueError):
            return None
    return None


def assert_resolution(
    probe: Mapping[str, Any],
    width: int = 1080,
    height: int = 1920,
) -> None:
    """Assert the first video stream is exactly ``width`` x ``height``.

    Defaults to the 1080x1920 portrait master required by the DoD.
    """
    stream = video_stream(probe)
    try:
        actual = (int(stream["width"]), int(stream["height"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise AcceptanceError(f"video stream missing width/height: {exc}") from exc
    if actual != (width, height):
        raise AcceptanceError(
            f"resolution {actual[0]}x{actual[1]} != expected {width}x{height}"
        )


def assert_h264_faststart(
    probe: Mapping[str, Any],
    *,
    faststart: bool | None = None,
) -> None:
    """Assert the video stream is H.264 (and, if provided, that faststart holds.

    ffprobe's JSON does not expose the ``+faststart`` (moov-before-mdat) layout,
    so callers compute it out-of-band with :func:`moov_precedes_mdat` and pass
    the boolean via ``faststart``. When ``faststart is None`` only the codec is
    checked.
    """
    stream = video_stream(probe)
    codec = stream.get("codec_name")
    if codec != "h264":
        raise AcceptanceError(f"video codec {codec!r} != 'h264'")
    if faststart is None:
        return
    if not faststart:
        raise AcceptanceError(
            "MP4 is not faststart (moov atom does not precede mdat); "
            "re-mux with -movflags +faststart"
        )


def assert_min_bitrate(
    probe: Mapping[str, Any],
    min_bps: int = 8_000_000,
) -> None:
    """Assert the container/video bitrate is at least ``min_bps`` bits/sec.

    The DoD target is 8 Mbps for real renders. Synthetic ``lavfi`` clips (flat
    colour + sine) compress far below that, so the golden harness passes a much
    lower ``min_bps`` for the synthetic suite — the 8 Mbps default is reserved
    for the real 10-job set. ``min_bps`` is intentionally a parameter.
    """
    rate = _format_bit_rate(probe)
    if rate is None:
        raise AcceptanceError("ffprobe JSON exposes no container or stream bit_rate")
    if rate < min_bps:
        raise AcceptanceError(
            f"bitrate {rate:.0f} bps < required {min_bps} bps"
        )


def assert_duration_window(
    probe: Mapping[str, Any],
    min_s: float,
    max_s: float,
) -> None:
    """Assert ``format.duration`` falls within ``[min_s, max_s]`` seconds."""
    if min_s > max_s:
        raise AcceptanceError(f"invalid duration window: {min_s} > {max_s}")
    fmt = probe.get("format") if isinstance(probe, Mapping) else None
    raw = fmt.get("duration") if isinstance(fmt, Mapping) else None
    if raw in (None, "", "N/A"):
        raise AcceptanceError("ffprobe JSON has no format.duration")
    try:
        duration = float(raw)
    except (TypeError, ValueError) as exc:
        raise AcceptanceError(f"format.duration not numeric: {raw!r}") from exc
    if not (min_s <= duration <= max_s):
        raise AcceptanceError(
            f"duration {duration:.3f}s outside window [{min_s}, {max_s}]s"
        )


# --------------------------------------------------------------------------- #
# Word-timing helpers (the single-source-of-truth timing contract)
# --------------------------------------------------------------------------- #
def _coerce_word(word: Any) -> tuple[str, float, float]:
    """Normalise a word-timing item into a ``(text, start, end)`` tuple.

    Accepts NamedTuples / objects with ``text``/``start``/``end`` attributes,
    ``(text, start, end)`` sequences, and mappings with those keys.
    """
    if isinstance(word, Mapping):
        try:
            return (str(word["text"]), float(word["start"]), float(word["end"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AcceptanceError(f"invalid word mapping {word!r}: {exc}") from exc
    # Objects with attributes (WordTiming NamedTuple satisfies both this and the
    # sequence branch; attributes are preferred for clarity).
    if hasattr(word, "start") and hasattr(word, "end"):
        try:
            text = str(getattr(word, "text", ""))
            return (text, float(word.start), float(word.end))
        except (TypeError, ValueError) as exc:
            raise AcceptanceError(f"invalid word object {word!r}: {exc}") from exc
    if isinstance(word, Sequence) and not isinstance(word, (str, bytes)):
        try:
            text, start, end = word[0], word[1], word[2]
            return (str(text), float(start), float(end))
        except (IndexError, TypeError, ValueError) as exc:
            raise AcceptanceError(f"invalid word tuple {word!r}: {exc}") from exc
    raise AcceptanceError(f"unrecognised word-timing item: {word!r}")


def _normalize_words(words: Iterable[Any]) -> list[tuple[str, float, float]]:
    normalized = [_coerce_word(w) for w in words]
    if not normalized:
        raise AcceptanceError("word-timing array is empty")
    return normalized


def assert_caption_drift(
    words: Iterable[Any],
    audio_duration: float,
    max_ms: float = 50.0,
) -> None:
    """Assert captions honour the single-source-of-truth timing contract.

    Three properties, all keyed off the ElevenLabs alignment being the ONE
    timing authority (INTEGRATION_CONTRACT §9):

    1. **Single source of truth:** the last caption ``end`` must equal the
       audio duration to within ``max_ms`` — captions are derived from the same
       alignment that defines ``audio_duration``, so any divergence is drift.
    2. **Monotonic:** each word's ``start`` is non-decreasing and ``end`` >=
       ``start``.
    3. **Non-overlapping:** each word's ``start`` is >= the previous word's
       ``end`` (allowing an ``max_ms`` slack so floating-point rounding at word
       boundaries is not flagged as overlap).

    Args:
        words: word-timing array (seconds).
        audio_duration: contract audio duration in seconds (from
            ``alignment.character_end_times_seconds[-1]``).
        max_ms: maximum tolerated drift/overlap in milliseconds (DoD: 50 ms).
    """
    normalized = _normalize_words(words)
    tol_s = max_ms / 1000.0

    prev_start = float("-inf")
    prev_end = float("-inf")
    for idx, (text, start, end) in enumerate(normalized):
        if end < start:
            raise AcceptanceError(
                f"word {idx} ({text!r}) end {end:.3f}s < start {start:.3f}s"
            )
        if start < prev_start:
            raise AcceptanceError(
                f"word {idx} ({text!r}) start {start:.3f}s not monotonic "
                f"(< previous start {prev_start:.3f}s)"
            )
        if start + tol_s < prev_end:
            raise AcceptanceError(
                f"word {idx} ({text!r}) start {start:.3f}s overlaps previous "
                f"end {prev_end:.3f}s by more than {max_ms} ms"
            )
        prev_start, prev_end = start, end

    caption_end = normalized[-1][2]
    drift_ms = abs(caption_end - audio_duration) * 1000.0
    if drift_ms > max_ms:
        raise AcceptanceError(
            f"caption end {caption_end:.3f}s vs audio {audio_duration:.3f}s "
            f"drift {drift_ms:.1f} ms > {max_ms} ms"
        )


def assert_hook_within(hook_words: Iterable[Any], max_s: float = 2.5) -> None:
    """Assert the hook finishes within ``max_s`` seconds (DoD: ≤ 2.5 s).

    ``hook_words`` is the word-timing sub-array covering the script hook. The
    hook's last word ``end`` must be <= ``max_s``.
    """
    normalized = _normalize_words(hook_words)
    hook_end = max(end for _text, _start, end in normalized)
    if hook_end > max_s:
        raise AcceptanceError(
            f"hook ends at {hook_end:.3f}s > allowed {max_s}s"
        )


def assert_avatar_audio_delta(
    avatar_s: float,
    audio_s: float,
    max_s: float = 0.15,
) -> None:
    """Assert |avatar_duration - audio_duration| <= ``max_s`` (DoD: ≤ 150 ms).

    The avatar render duration and the narration audio derive from the same
    alignment, so a delta beyond ``max_s`` means the talking head is out of sync
    with its own audio track.
    """
    try:
        delta = abs(float(avatar_s) - float(audio_s))
    except (TypeError, ValueError) as exc:
        raise AcceptanceError(
            f"non-numeric avatar/audio duration: {avatar_s!r}, {audio_s!r}"
        ) from exc
    if delta > max_s:
        raise AcceptanceError(
            f"avatar/audio duration delta {delta * 1000:.1f} ms > "
            f"{max_s * 1000:.0f} ms (avatar={avatar_s}s, audio={audio_s}s)"
        )


# --------------------------------------------------------------------------- #
# Faststart (moov/mdat ordering) — raw MP4 scan, stdlib only, no ffmpeg
# --------------------------------------------------------------------------- #
def moov_precedes_mdat(path: str, *, scan_bytes: int = 4 * 1024 * 1024) -> bool:
    """Return ``True`` when the MP4 ``moov`` atom appears before ``mdat``.

    This is the on-disk signature of ``-movflags +faststart`` (the index sits at
    the head so a player can start streaming before the whole file downloads).
    ffprobe does not report it, so we scan the top-level atom list directly.

    Reads at most ``scan_bytes`` from the front of the file — enough to see the
    ``moov`` box on a faststart clip without loading a large ``mdat`` payload.

    Raises:
        AcceptanceError: if the file has neither a ``moov`` nor an ``mdat`` box
            within the scanned window (i.e. it is not a recognisable MP4).
    """
    import struct

    with open(path, "rb") as fh:
        data = fh.read(scan_bytes)

    moov_at: int | None = None
    mdat_at: int | None = None
    offset = 0
    length = len(data)
    while offset + 8 <= length:
        (size,) = struct.unpack(">I", data[offset : offset + 4])
        box_type = data[offset + 4 : offset + 8]
        if box_type == b"moov" and moov_at is None:
            moov_at = offset
        elif box_type == b"mdat" and mdat_at is None:
            mdat_at = offset
        if moov_at is not None and mdat_at is not None:
            break

        if size == 1:
            # 64-bit extended size in the 8 bytes following the type.
            if offset + 16 > length:
                break
            (size,) = struct.unpack(">Q", data[offset + 8 : offset + 16])
        elif size == 0:
            # Box extends to EOF: nothing meaningful can follow it.
            break
        if size < 8:
            break
        offset += size

    if moov_at is None and mdat_at is None:
        raise AcceptanceError(f"{path!r} has no moov/mdat box in first {scan_bytes} bytes")
    if moov_at is None:
        return False
    if mdat_at is None:
        # moov seen, mdat not yet reached in the window → moov is at the head.
        return True
    return moov_at < mdat_at
