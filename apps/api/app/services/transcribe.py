"""Transcribe an audio file to WORD-level timings using faster-whisper.

Bring Your Own Voiceover (BYOV): a creator uploads their OWN narration audio
instead of using TTS / voice-clone. That audio becomes the reel's narration and
its transcription drives the captions. Per the integration contract §8 the WORD
timings produced here are the *single timing authority* for the whole pipeline —
the same list feeds the ASS karaoke captions AND (via the audio) the HeyGen
avatar lip-sync + duration.

Built on MoneyPrinterTurbo's existing faster-whisper stack
(:mod:`app.services.subtitle`) — no new dependency is introduced.

The heavy ``faster_whisper`` import is *guarded*: importing this module never
requires the model to be installed. The dependency is only needed when
:func:`transcribe_to_words` (or the SRT fallback) is actually called, at which
point a clear :class:`TranscriptionDependencyError` is raised if it is missing.
This keeps the module safe to import from the API layer / Celery task
registration and easy to unit-test with a mocked ``faster_whisper``.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

from app.services.captions.words import WordTiming

__all__ = [
    "TranscriptionError",
    "TranscriptionDependencyError",
    "transcribe_to_words",
    "transcribe_to_srt",
    "words_from_srt",
    "reset_model_cache",
]

# faster-whisper transcription parameters. Mirrors ``app/services/subtitle.py``
# (``word_timestamps=True`` is what makes §8 word-level timing possible) so BYOV
# captions line up with MPT's own whisper output.
_BEAM_SIZE: int = 5
_VAD_MIN_SILENCE_MS: int = 500


class TranscriptionError(RuntimeError):
    """Base error for BYOV transcription failures.

    Raised for any recoverable, caller-facing problem (missing file, model
    load/decode failure). The caller (e.g. the BYOV stage in ``reelforge``) can
    catch this to fall back to another caption source instead of crashing.
    """


class TranscriptionDependencyError(TranscriptionError):
    """Raised when ``faster_whisper`` is required but not installed.

    Kept as a distinct subclass so a caller can tell "the library is missing"
    (a deploy/config problem) apart from "this particular audio failed".
    """


# Process-wide model cache. Loading a WhisperModel is expensive, so the first
# call materializes it and subsequent calls reuse it (same pattern as
# ``subtitle.create``'s module-level ``model``).
_model: Any = None


def reset_model_cache() -> None:
    """Drop the cached WhisperModel (test hook / config reload)."""
    global _model
    _model = None


def _import_whisper_model() -> Any:
    """Return the ``faster_whisper.WhisperModel`` class or raise clearly.

    The import is deliberately performed lazily *inside* this function so the
    module stays importable without the heavy dependency and so tests can
    inject a fake ``faster_whisper`` (or its absence) via ``sys.modules``.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - exercised via mocked absence
        raise TranscriptionDependencyError(
            "faster-whisper is not installed but is required to transcribe "
            "audio. Install it with `pip install faster-whisper` to enable "
            "Bring Your Own Voiceover captions."
        ) from exc
    return WhisperModel


def _load_model() -> Any:
    """Load (once) and return the cached WhisperModel.

    Reuses the model-path resolution from ``app/services/subtitle.py``: prefer a
    locally-downloaded ``models/whisper-<size>`` directory, otherwise fall back
    to the bare size string so faster-whisper fetches it. The default size comes
    from ``config.app['whisper_model_size']`` (small/base are the recommended
    BYOV defaults), then ``config.whisper['model_size']``, then ``"base"``.
    """
    global _model
    if _model is not None:
        return _model

    whisper_model_cls = _import_whisper_model()

    from app.config import config

    model_size = (
        config.app.get("whisper_model_size")
        or config.whisper.get("model_size")
        or "base"
    )
    device = config.whisper.get("device", "cpu")
    compute_type = config.whisper.get("compute_type", "int8")

    from app.bootstrap import ENGINE_ROOT
    model_path = str(ENGINE_ROOT / "models" / f"whisper-{model_size}")
    if not (os.path.isdir(model_path) and os.path.isfile(f"{model_path}/model.bin")):
        model_path = model_size

    logger.info(
        f"loading whisper model: {model_path}, device: {device}, "
        f"compute_type: {compute_type}"
    )
    try:
        _model = whisper_model_cls(
            model_size_or_path=model_path,
            device=device,
            compute_type=compute_type,
        )
    except Exception as exc:  # noqa: BLE001 - surface a typed, catchable error
        raise TranscriptionError(
            f"failed to load faster-whisper model {model_path!r}: {exc}"
        ) from exc
    return _model


def _normalize_language(language: str | None) -> str | None:
    """Map an empty / ``"auto"`` language selection to None (auto-detect)."""
    if not language:
        return None
    lang = language.strip()
    if not lang or lang.lower() == "auto":
        return None
    return lang


def transcribe_to_words(
    audio_path: str,
    language: str | None = None,
) -> list[WordTiming]:
    """Transcribe ``audio_path`` to a flat list of word-level ``WordTiming``.

    Runs faster-whisper with ``word_timestamps=True`` and flattens every
    segment's words into one ordered list of ``WordTiming(text, start, end)`` in
    seconds — the §8 single timing authority for captions and avatar sync.

    Args:
        audio_path: Local path to the creator's uploaded narration audio.
        language: Optional language hint (ISO code). ``None``/``""``/``"auto"``
            means auto-detect.

    Returns:
        Ordered ``list[WordTiming]`` (may be empty for silent audio).

    Raises:
        TranscriptionError: The file is missing or decoding failed.
        TranscriptionDependencyError: ``faster_whisper`` is not installed.
    """
    if not audio_path or not os.path.isfile(audio_path):
        raise TranscriptionError(f"audio file not found: {audio_path!r}")

    model = _load_model()
    lang = _normalize_language(language)

    try:
        segments, info = model.transcribe(
            audio_path,
            language=lang,
            beam_size=_BEAM_SIZE,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=_VAD_MIN_SILENCE_MS),
        )
    except Exception as exc:  # noqa: BLE001 - surface a typed, catchable error
        raise TranscriptionError(
            f"faster-whisper failed to transcribe {audio_path!r}: {exc}"
        ) from exc

    detected = getattr(info, "language", None)
    if detected:
        logger.info(f"transcribed {audio_path!r}: detected language {detected!r}")

    words: list[WordTiming] = []
    # ``segments`` is a lazy generator — iterating it drives the actual decode,
    # so any late failure is wrapped as a typed error too.
    try:
        for segment in segments:
            for word in getattr(segment, "words", None) or []:
                text = (getattr(word, "word", None) or "").strip()
                start = getattr(word, "start", None)
                end = getattr(word, "end", None)
                if not text or start is None or end is None:
                    continue
                start_s = float(start)
                end_s = float(end)
                # Guard against non-monotonic timings from the model.
                words.append(WordTiming(text, start_s, max(end_s, start_s)))
    except TranscriptionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(
            f"faster-whisper decode error while reading {audio_path!r}: {exc}"
        ) from exc

    logger.info(f"transcribed {audio_path!r}: {len(words)} words")
    return words


def transcribe_to_srt(audio_path: str, out_srt: str) -> str:
    """Transcribe ``audio_path`` to an SRT file (delegates to MPT ``subtitle``).

    Fallback path for callers that want an SRT artifact rather than word
    timings. Delegates to :func:`app.services.subtitle.create`, which uses the
    same faster-whisper stack.

    Args:
        audio_path: Local path to the narration audio.
        out_srt: Destination path for the ``.srt`` file.

    Returns:
        The ``out_srt`` path on success.

    Raises:
        TranscriptionError: The file is missing or ``subtitle.create`` failed.
    """
    if not audio_path or not os.path.isfile(audio_path):
        raise TranscriptionError(f"audio file not found: {audio_path!r}")
    if not out_srt:
        raise TranscriptionError("out_srt destination path is required")

    from app.services import subtitle

    try:
        subtitle.create(audio_path, out_srt)
    except Exception as exc:  # noqa: BLE001 - surface a typed, catchable error
        raise TranscriptionError(
            f"subtitle.create failed for {audio_path!r}: {exc}"
        ) from exc
    return out_srt


def _srt_ts_to_seconds(ts: str) -> float:
    """Parse an SRT timestamp ``HH:MM:SS,mmm`` (or ``.mmm``) into seconds."""
    cleaned = ts.strip().replace(".", ",")
    try:
        hms, _, ms = cleaned.partition(",")
        hh, mm, ss = hms.split(":")
        seconds = int(hh) * 3600 + int(mm) * 60 + int(ss)
        seconds += (int(ms) / 1000.0) if ms else 0.0
        return float(seconds)
    except (ValueError, AttributeError) as exc:
        raise TranscriptionError(f"malformed SRT timestamp {ts!r}: {exc}") from exc


def _parse_srt_time_range(times: str) -> tuple[float, float]:
    """Parse an ``... --> ...`` SRT time range into ``(start, end)`` seconds."""
    if "-->" not in times:
        raise TranscriptionError(f"malformed SRT time range {times!r}")
    start_raw, _, end_raw = times.partition("-->")
    return _srt_ts_to_seconds(start_raw), _srt_ts_to_seconds(end_raw)


def words_from_srt(srt_path: str) -> list[WordTiming]:
    """Parse an SRT file into *approximate* word-level ``WordTiming``.

    Used when true word timestamps are unavailable (e.g. only an SRT was
    produced). Each subtitle line is split on whitespace and its time span is
    divided *evenly* across its words. These timings are approximate — good
    enough for karaoke highlighting but not the exact §8 authority that
    :func:`transcribe_to_words` provides.

    Args:
        srt_path: Path to an existing ``.srt`` file.

    Returns:
        Ordered ``list[WordTiming]`` (empty if the SRT has no text).

    Raises:
        TranscriptionError: The file is missing or a timestamp is malformed.
    """
    if not srt_path or not os.path.isfile(srt_path):
        raise TranscriptionError(f"SRT file not found: {srt_path!r}")

    from app.services import subtitle

    items = subtitle.file_to_subtitles(srt_path)
    words: list[WordTiming] = []
    for item in items:
        # file_to_subtitles yields (index, "start --> end", text).
        if not item or len(item) < 3:
            continue
        _idx, times, text = item[0], item[1], item[2]
        tokens = str(text or "").split()
        if not tokens:
            continue

        start_s, end_s = _parse_srt_time_range(str(times))
        span = max(end_s - start_s, 0.0)
        n = len(tokens)
        step = span / n if n else 0.0

        for i, token in enumerate(tokens):
            w_start = start_s + step * i
            # Snap the last token to the exact line end to avoid drift.
            w_end = end_s if i == n - 1 else start_s + step * (i + 1)
            words.append(
                WordTiming(token, round(w_start, 3), round(max(w_end, w_start), 3))
            )

    logger.info(f"parsed {srt_path!r}: {len(words)} approximate words")
    return words
