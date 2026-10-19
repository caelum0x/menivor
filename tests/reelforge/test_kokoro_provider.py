"""Kokoro-FastAPI sidecar provider + audiobook chapter synthesis (HTTP mocked)."""

from __future__ import annotations

import json

import pytest

from app.domains.audiobook import service as audiobook
from app.domains.routing.base import RUN_COMPLETED, ProviderError, ProviderRegistry
from app.domains.routing.providers.kokoro import (
    MAX_INPUT_CHARS,
    KokoroClient,
    KokoroTTSAdapter,
    kokoro_url,
)
from app.domains.routing.providers.registry import build_adapter, register_available_adapters
from app.domains.routing.providers.tts import SelfHostTTSAdapter


class FakeHttp:
    """Records calls; replies from a queue of (status, body, content_type)."""

    def __init__(self, *replies):
        self.replies = list(replies) or [(200, b"ID3audio", "audio/mpeg")]
        self.calls: list[tuple[str, str, dict | None, float]] = []

    def __call__(self, method, url, body, timeout):
        self.calls.append((method, url, body, timeout))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_kokoro_url_reads_env_and_strips():
    assert kokoro_url({"KOKORO_URL": " http://kokoro:8880/ "}) == "http://kokoro:8880"
    assert kokoro_url({}) == ""


def test_synthesize_posts_openai_compatible_request():
    http = FakeHttp()
    client = KokoroClient("http://kokoro:8880/", http_fn=http)
    result = client.synthesize("Hello there.", voice="bf_emma", speed=9.0)
    method, url, body, _ = http.calls[0]
    assert method == "POST"
    assert url == "http://kokoro:8880/v1/audio/speech"
    assert body == {
        "model": "kokoro",
        "input": "Hello there.",
        "voice": "bf_emma",
        "response_format": "mp3",
        "speed": 2.0,  # clamped
        "stream": False,
    }
    assert result.audio == b"ID3audio"
    assert result.content_type == "audio/mpeg"
    assert result.characters == len("Hello there.")


def test_synthesize_defaults_voice_and_rejects_bad_format():
    http = FakeHttp()
    KokoroClient("http://k", http_fn=http).synthesize("Hi", voice="", response_format="exe")
    body = http.calls[0][2]
    assert body["voice"] == "af_heart"
    assert body["response_format"] == "mp3"


@pytest.mark.parametrize(
    "reply, retryable",
    [
        ((503, b"busy", "text/plain"), True),
        ((422, b"bad voice", "application/json"), False),
        (ConnectionError("refused"), True),
    ],
)
def test_errors_are_normalized(reply, retryable):
    client = KokoroClient("http://k", http_fn=FakeHttp(reply))
    with pytest.raises(ProviderError) as info:
        client.synthesize("Hi")
    assert info.value.retryable is retryable


def test_json_body_on_200_is_rejected_and_empty_audio_retryable():
    with pytest.raises(ProviderError):
        KokoroClient("http://k", http_fn=FakeHttp((200, b"{}", "application/json"))).synthesize("Hi")
    with pytest.raises(ProviderError) as info:
        KokoroClient("http://k", http_fn=FakeHttp((200, b"", "audio/mpeg"))).synthesize("Hi")
    assert info.value.retryable is True


def test_input_validation():
    client = KokoroClient("http://k", http_fn=FakeHttp())
    with pytest.raises(ProviderError):
        client.synthesize("   ")
    with pytest.raises(ProviderError):
        client.synthesize("a" * (MAX_INPUT_CHARS + 1))
    with pytest.raises(ProviderError):
        KokoroClient("", http_fn=FakeHttp())


def test_list_voices_v09_object_shape():
    body = {"voices": [{"id": "af_heart", "name": "af_heart"}, {"name": "no-id"}], "default_voice": "af_heart"}
    http = FakeHttp((200, json.dumps(body).encode(), "application/json"))
    assert KokoroClient("http://k", http_fn=http).list_voices() == ["af_heart"]


def test_list_voices():
    http = FakeHttp((200, json.dumps({"voices": ["af_heart", "bm_george", 3]}).encode(), "application/json"))
    assert KokoroClient("http://k", http_fn=http).list_voices() == ["af_heart", "bm_george"]
    assert http.calls[0][:2] == ("GET", "http://k/v1/audio/voices")


def test_adapter_submit_hosts_audio_and_meters_characters():
    hosted: list[bytes] = []
    adapter = KokoroTTSAdapter(
        base_url="http://k", http_fn=FakeHttp(), host_fn=lambda b: hosted.append(b) or "https://r2/x.mp3"
    )
    run = adapter.submit({"text": "Read me aloud."}, {"model_id": "kokoro/tts"}, "corr-1")
    assert run.state == RUN_COMPLETED
    assert run.result_ref == "https://r2/x.mp3"
    assert run.run_id == "corr-1"
    assert run.usage.unit == "characters"
    assert run.usage.quantity_units == len("Read me aloud.")
    assert hosted == [b"ID3audio"]
    assert run.raw["voice"] == "af_heart"


def test_adapter_voice_from_model_id():
    http = FakeHttp()
    adapter = KokoroTTSAdapter(base_url="http://k", http_fn=http, host_fn=lambda b: "u")
    adapter.submit({"text": "x"}, {"model_id": "kokoro/am_michael"}, "c")
    assert http.calls[0][2]["voice"] == "am_michael"


def test_registry_uses_real_adapter_only_when_kokoro_url_set(monkeypatch):
    monkeypatch.delenv("KOKORO_URL", raising=False)
    assert isinstance(build_adapter("kokoro", "k"), SelfHostTTSAdapter)
    monkeypatch.setenv("KOKORO_URL", "http://kokoro:8880")
    assert isinstance(build_adapter("kokoro", ""), KokoroTTSAdapter)

    reg = ProviderRegistry()
    keys = register_available_adapters(reg, env={"KOKORO_URL": "http://kokoro:8880"})
    assert keys.count("kokoro") == 1
    assert isinstance(reg.get("kokoro"), KokoroTTSAdapter)

    assert "kokoro" not in register_available_adapters(ProviderRegistry(), env={})


# --------------------------------------------------------------------------- #
# Audiobook chapter synthesis
# --------------------------------------------------------------------------- #
def test_chunk_text_respects_limit_and_sentences():
    text = "One two three. Four five six! Seven eight nine?  Ten."
    chunks = audiobook.chunk_text(text, limit=30)
    assert all(len(c) <= 30 for c in chunks)
    assert " ".join(chunks) == "One two three. Four five six! Seven eight nine? Ten."
    assert audiobook.chunk_text("   ") == []


def test_chunk_text_splits_overlong_sentence_and_words():
    chunks = audiobook.chunk_text("word " * 50 + "x" * 25, limit=20)
    assert all(0 < len(c) <= 20 for c in chunks)
    assert "".join(chunks).replace(" ", "") == ("word" * 50) + "x" * 25


def test_synthesize_chapter_concatenates_chunks():
    http = FakeHttp((200, b"A", "audio/mpeg"), (200, b"B", "audio/mpeg"))
    client = KokoroClient("http://k", http_fn=http)
    sentence = "This is a sentence that is fairly long. " * 40  # > one chunk
    chapter = audiobook.synthesize_chapter(client, sentence, voice="bf_emma", speed=1.2)
    assert chapter.chunks == len(http.calls) >= 2
    assert chapter.audio.startswith(b"AB")
    assert chapter.content_type == "audio/mpeg"
    assert all(call[2]["voice"] == "bf_emma" and call[2]["speed"] == 1.2 for call in http.calls)


def test_synthesize_chapter_limits():
    client = KokoroClient("http://k", http_fn=FakeHttp())
    with pytest.raises(audiobook.AudiobookError) as empty:
        audiobook.synthesize_chapter(client, "  ")
    assert empty.value.status_code == 400
    with pytest.raises(audiobook.AudiobookError) as big:
        audiobook.synthesize_chapter(client, "Hello world. " * 2000)
    assert big.value.status_code == 413


def test_require_enabled():
    with pytest.raises(audiobook.AudiobookError) as off:
        audiobook.require_enabled({})
    assert off.value.status_code == 503
    assert audiobook.require_enabled({"KOKORO_URL": "http://k/"}) == "http://k"


def test_gateway_kokoro_voice_clip_hosts_sidecar_audio(monkeypatch):
    from app.domains.gateway import provider_execution as pe
    from app.domains.routing.providers import kokoro as kokoro_mod

    http = FakeHttp()
    monkeypatch.setattr(kokoro_mod, "_httpx_request", http)
    hosted: list[tuple[bytes, str, str]] = []
    monkeypatch.setattr(
        "app.domains.routing.providers.voice_gen.host_audio_bytes",
        lambda data, ctype, key_prefix: hosted.append((data, ctype, key_prefix)) or "https://r2/k.mp3",
    )
    monkeypatch.setenv("KOKORO_URL", "http://kokoro:8880")
    assert pe._kokoro_base_url() == "http://kokoro:8880"
    clip = pe._kokoro_voice_clip(pe._kokoro_base_url(), text="Narrate.", voice_id="", speed=1.1)
    assert clip.output_url == "https://r2/k.mp3"
    assert clip.characters == len("Narrate.")
    assert hosted == [(b"ID3audio", "audio/mpeg", "prism/voice/kokoro")]
    assert http.calls[0][2]["voice"] == "af_heart"
