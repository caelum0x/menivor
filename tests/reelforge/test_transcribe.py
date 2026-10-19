"""Unit tests for BYOV audio transcription (``app/services/transcribe.py``).

Bring Your Own Voiceover transcribes a creator's uploaded narration to WORD
timings that drive both the karaoke captions and the avatar sync (§8).

The heavy ``faster_whisper`` dependency is MOCKED here — these tests never load
a real model. We inject a fake ``faster_whisper`` module (or simulate its
absence) via ``sys.modules`` and monkeypatch ``subtitle.create``.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.services import transcribe
from app.services.transcribe import (
    TranscriptionDependencyError,
    TranscriptionError,
    transcribe_to_words,
    transcribe_to_srt,
    words_from_srt,
)
from app.services.captions.words import WordTiming


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeWord:
    """Mimics a faster-whisper word: ``.word`` carries a leading space."""

    def __init__(self, word: str, start: float, end: float) -> None:
        self.word = word
        self.start = start
        self.end = end


class _FakeSegment:
    def __init__(self, words: list[_FakeWord]) -> None:
        self.words = words


class _FakeInfo:
    def __init__(self, language: str = "en") -> None:
        self.language = language
        self.language_probability = 0.99


class _FakeModel:
    """Records the transcribe kwargs and returns canned segments."""

    def __init__(self, segments, info=None, **_kwargs) -> None:
        self._segments = segments
        self._info = info or _FakeInfo()
        self.last_kwargs: dict = {}

    def transcribe(self, audio_path, **kwargs):
        self.last_kwargs = {"audio_path": audio_path, **kwargs}
        return iter(self._segments), self._info


def _install_fake_whisper(monkeypatch, model_factory) -> None:
    """Insert a fake ``faster_whisper`` module exposing ``WhisperModel``."""
    fake_module = types.ModuleType("faster_whisper")

    def _whisper_model(**kwargs):
        return model_factory(kwargs)

    fake_module.WhisperModel = _whisper_model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    transcribe.reset_model_cache()


@pytest.fixture(autouse=True)
def _clear_model_cache():
    transcribe.reset_model_cache()
    yield
    transcribe.reset_model_cache()


# ---------------------------------------------------------------------------
# transcribe_to_words
# ---------------------------------------------------------------------------
def test_transcribe_to_words_returns_wordtiming_list(monkeypatch, tmp_path):
    segments = [
        _FakeSegment([_FakeWord(" Hello", 0.0, 0.5), _FakeWord(" world", 0.5, 1.0)]),
        _FakeSegment([_FakeWord(" again", 1.0, 1.4)]),
    ]
    captured = {}

    def _factory(_kwargs):
        model = _FakeModel(segments)
        captured["model"] = model
        return model

    _install_fake_whisper(monkeypatch, _factory)

    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"\x00\x01")

    words = transcribe_to_words(str(audio), language="en")

    assert words == [
        WordTiming("Hello", 0.0, 0.5),
        WordTiming("world", 0.5, 1.0),
        WordTiming("again", 1.0, 1.4),
    ]
    assert all(isinstance(w, WordTiming) for w in words)
    # word_timestamps must be enabled (§8) and "en" forwarded verbatim.
    assert captured["model"].last_kwargs["word_timestamps"] is True
    assert captured["model"].last_kwargs["language"] == "en"


def test_transcribe_to_words_auto_language_becomes_none(monkeypatch, tmp_path):
    captured = {}

    def _factory(_kwargs):
        model = _FakeModel([_FakeSegment([_FakeWord(" hi", 0.0, 0.2)])])
        captured["model"] = model
        return model

    _install_fake_whisper(monkeypatch, _factory)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"\x00")

    transcribe_to_words(str(audio), language="auto")
    assert captured["model"].last_kwargs["language"] is None


def test_transcribe_to_words_clamps_non_monotonic_and_skips_empty(monkeypatch, tmp_path):
    segments = [
        _FakeSegment(
            [
                _FakeWord("  ", 0.0, 0.1),        # whitespace-only -> skipped
                _FakeWord(" bad", 2.0, 1.0),      # end < start -> clamped to start
            ]
        )
    ]
    _install_fake_whisper(monkeypatch, lambda _k: _FakeModel(segments))
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00")

    words = transcribe_to_words(str(audio))
    assert words == [WordTiming("bad", 2.0, 2.0)]


def test_transcribe_to_words_missing_file_raises():
    with pytest.raises(TranscriptionError):
        transcribe_to_words("/no/such/file.mp3")


def test_transcribe_to_words_decode_error_is_typed(monkeypatch, tmp_path):
    class _BoomModel(_FakeModel):
        def transcribe(self, audio_path, **kwargs):
            raise RuntimeError("cuda exploded")

    _install_fake_whisper(monkeypatch, lambda _k: _BoomModel([]))
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00")

    with pytest.raises(TranscriptionError) as exc:
        transcribe_to_words(str(audio))
    assert "cuda exploded" in str(exc.value)


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------
def test_import_guard_raises_clearly_when_lib_absent(monkeypatch, tmp_path):
    # Simulate faster_whisper being uninstalled: importing it raises ImportError.
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    transcribe.reset_model_cache()

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00")

    with pytest.raises(TranscriptionDependencyError) as exc:
        transcribe_to_words(str(audio))
    assert "faster-whisper" in str(exc.value).lower()
    # It is a subclass of the base error, so a broad caller catch still works.
    assert isinstance(exc.value, TranscriptionError)


# ---------------------------------------------------------------------------
# transcribe_to_srt (delegates to subtitle.create)
# ---------------------------------------------------------------------------
def test_transcribe_to_srt_delegates_to_subtitle_create(monkeypatch, tmp_path):
    from app.services import subtitle

    calls = {}

    def _fake_create(audio_file, subtitle_file=""):
        calls["args"] = (audio_file, subtitle_file)

    monkeypatch.setattr(subtitle, "create", _fake_create)

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00")
    out = tmp_path / "out.srt"

    result = transcribe_to_srt(str(audio), str(out))
    assert result == str(out)
    assert calls["args"] == (str(audio), str(out))


def test_transcribe_to_srt_wraps_failure(monkeypatch, tmp_path):
    from app.services import subtitle

    def _boom(audio_file, subtitle_file=""):
        raise RuntimeError("model download failed")

    monkeypatch.setattr(subtitle, "create", _boom)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00")

    with pytest.raises(TranscriptionError) as exc:
        transcribe_to_srt(str(audio), str(tmp_path / "o.srt"))
    assert "model download failed" in str(exc.value)


def test_transcribe_to_srt_missing_audio_raises():
    with pytest.raises(TranscriptionError):
        transcribe_to_srt("/no/such/a.mp3", "/tmp/o.srt")


# ---------------------------------------------------------------------------
# words_from_srt
# ---------------------------------------------------------------------------
_SAMPLE_SRT = """1
00:00:00,000 --> 00:00:02,000
Hello world

2
00:00:02,000 --> 00:00:03,000
again
"""


def test_words_from_srt_parses_and_splits_evenly(tmp_path):
    srt = tmp_path / "sub.srt"
    srt.write_text(_SAMPLE_SRT, encoding="utf-8")

    words = words_from_srt(str(srt))

    assert [w.text for w in words] == ["Hello", "world", "again"]
    # First line (0->2s) split evenly across two words: 0->1, 1->2.
    assert words[0].start == pytest.approx(0.0)
    assert words[0].end == pytest.approx(1.0)
    assert words[1].start == pytest.approx(1.0)
    assert words[1].end == pytest.approx(2.0)
    # Single-word line snaps to the exact line span.
    assert words[2].start == pytest.approx(2.0)
    assert words[2].end == pytest.approx(3.0)
    assert all(isinstance(w, WordTiming) for w in words)


def test_words_from_srt_missing_file_raises():
    with pytest.raises(TranscriptionError):
        words_from_srt("/no/such/sub.srt")
