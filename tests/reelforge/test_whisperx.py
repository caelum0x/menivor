"""WhisperX schema parsing + client (fake transport = the network seam)."""

from __future__ import annotations

import pytest

from app.services.captions.whisperx_client import WhisperXClient, WhisperXError
from app.services.captions.whisperx_schema import parse_alignment


_PAYLOAD = {
    "language": "en",
    "segments": [
        {
            "text": "this changed my life",
            "start": 0.0,
            "end": 1.2,
            "words": [
                {"word": "this", "start": 0.0, "end": 0.3, "score": 0.99},
                {"word": "changed", "start": 0.3, "end": 0.7, "score": 0.98},
                {"word": "my", "start": 0.7, "end": 0.9},  # missing score -> defaults
                {"word": "life", "start": 0.9, "end": 1.2},
            ],
        }
    ],
}


# --------------------------------------------------------------------------- #
# Schema parsing
# --------------------------------------------------------------------------- #
def test_parse_alignment_word_timings():
    res = parse_alignment(_PAYLOAD)
    assert res.language == "en" and len(res.segments) == 1
    words = res.words
    assert [w.word for w in words] == ["this", "changed", "my", "life"]
    assert words[0].start == 0.0 and words[0].end == 0.3
    assert words[2].score == 1.0  # defaulted
    assert res.duration == 1.2


def test_parse_missing_word_timings_fall_back_to_segment():
    payload = {"segments": [{"text": "hi", "start": 2.0, "end": 3.0,
                             "words": [{"word": "hi"}]}]}
    res = parse_alignment(payload)
    w = res.words[0]
    assert w.start == 2.0 and w.end == 3.0  # fell back to segment bounds


def test_empty_payload_is_safe():
    res = parse_alignment({})
    assert res.segments == () and res.duration == 0.0


# --------------------------------------------------------------------------- #
# Client (fake transport)
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self):
        return self._body


class FakeTransport:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def request(self, method, url, *, headers=None, json=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return self._resp


def test_client_transcribes_and_parses():
    t = FakeTransport(_Resp(200, _PAYLOAD))
    client = WhisperXClient(base_url="https://wx.example", api_key="k", transport=t)
    res = client.transcribe("https://r2/audio.mp3", language="en")
    assert [w.word for w in res.words] == ["this", "changed", "my", "life"]
    # Real request shape: POST /transcribe with align + bearer auth.
    call = t.calls[0]
    assert call["method"] == "POST" and call["url"] == "https://wx.example/transcribe"
    assert call["json"]["align"] is True and call["json"]["audio_url"] == "https://r2/audio.mp3"
    assert call["headers"]["Authorization"] == "Bearer k"


def test_client_http_error_raises():
    client = WhisperXClient(base_url="https://wx.example", transport=FakeTransport(_Resp(500)))
    with pytest.raises(WhisperXError):
        client.transcribe("https://r2/a.mp3")


def test_client_requires_config():
    # No base_url + no config -> clear error, not a crash.
    client = WhisperXClient(base_url="", transport=FakeTransport(_Resp(200)))
    with pytest.raises(WhisperXError):
        client.transcribe("https://r2/a.mp3")
