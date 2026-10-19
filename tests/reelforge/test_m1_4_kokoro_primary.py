"""M1.4: Kokoro is the primary free voice, edge-tts stays as the fallback."""

from __future__ import annotations

import base64
import importlib
import os

import pytest

from app.services.tts import kokoro_tts as kt
from app.services.tts import narration as nr

KOKORO_ENV = {"KOKORO_URL": "http://kokoro:8880"}


# --------------------------------------------------------------------------- #
# edge-tts stays on the prod path (the old "edge-tts is removed" grep, inverted)
# --------------------------------------------------------------------------- #
def test_edge_tts_is_still_importable_on_the_prod_path():
    assert importlib.util.find_spec("edge_tts") is not None
    from app.services import voice

    assert voice.edge_tts is importlib.import_module("edge_tts")
    assert callable(voice.azure_tts_v1)


def test_edge_tts_is_still_a_requirement():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    reqs = ""
    for name in ("requirements.txt", os.path.join("apps", "api", "requirements.txt")):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            reqs += open(path, encoding="utf-8").read().lower()
    assert "edge-tts" in reqs or "edge_tts" in reqs


# --------------------------------------------------------------------------- #
# Chain order
# --------------------------------------------------------------------------- #
def _engines(steps):
    return [s.engine for s in steps]


def test_order_is_kokoro_then_edge_then_paid_elevenlabs():
    steps = nr.plan_chain(
        "en-US-AriaNeural-Female",
        language="en",
        premium_voice="elevenlabs:abc:Rachel",
        premium_first=False,
        env=KOKORO_ENV,
    )
    assert _engines(steps) == ["kokoro", "edge-tts", "elevenlabs"]
    assert steps[0].voice_name == "kokoro:af_heart"
    assert steps[1].voice_name == "en-US-AriaNeural-Female"


def test_unpaid_job_never_gets_elevenlabs():
    steps = nr.plan_chain("en-US-GuyNeural-Male", language="en", env=KOKORO_ENV)
    assert _engines(steps) == ["kokoro", "edge-tts"]
    assert steps[0].voice_name == "kokoro:am_michael"


def test_paid_premium_voice_goes_first_then_free_engines():
    steps = nr.plan_chain(
        "elevenlabs:abc:Rachel",
        language="en",
        free_voice="en-US-AriaNeural-Female",
        premium_voice="elevenlabs:abc:Rachel",
        premium_first=True,
        env=KOKORO_ENV,
    )
    assert _engines(steps) == ["elevenlabs", "kokoro", "edge-tts"]


def test_without_kokoro_url_edge_is_primary():
    steps = nr.plan_chain("en-US-AriaNeural-Female", language="en", env={})
    assert _engines(steps) == ["edge-tts"]


def test_kokoro_primary_can_be_switched_off():
    env = {**KOKORO_ENV, "MENIVOR_KOKORO_PRIMARY": "off"}
    assert _engines(nr.plan_chain("en-US-AriaNeural-Female", language="en", env=env)) == ["edge-tts"]


def test_turkish_is_not_faked_with_kokoro():
    steps = nr.plan_chain("tr-TR-EmelNeural-Female", language="tr", env=KOKORO_ENV)
    assert _engines(steps) == ["edge-tts"]
    assert nr.free_voice_engine("tr", KOKORO_ENV) == "edge-tts"
    assert nr.free_voice_engine("en", KOKORO_ENV) == "kokoro"


def test_other_kokoro_languages_are_opt_in():
    assert _engines(nr.plan_chain("es-ES-ElviraNeural-Female", language="es", env=KOKORO_ENV)) == [
        "edge-tts"
    ]
    env = {**KOKORO_ENV, "MENIVOR_KOKORO_LANGS": "en,es"}
    steps = nr.plan_chain("es-ES-ElviraNeural-Female", language="es", env=env)
    assert _engines(steps) == ["kokoro", "edge-tts"]
    assert steps[0].voice_name == "kokoro:ef_dora"


def test_auto_language_is_read_from_the_voice():
    steps = nr.plan_chain("en-US-GuyNeural-Male", language="auto", env=KOKORO_ENV)
    assert steps[0].voice_name == "kokoro:am_michael"
    tr = nr.plan_chain("tr-TR-EmelNeural-Female", language="auto", env=KOKORO_ENV)
    assert _engines(tr) == ["edge-tts"]


def test_british_english_uses_british_voice():
    steps = nr.plan_chain("en-GB-SoniaNeural-Female", language="", env=KOKORO_ENV)
    assert steps[0].voice_name == "kokoro:bf_emma"


def test_explicit_engine_goes_first_with_free_chain_behind():
    steps = nr.plan_chain(
        "chatterbox:emma", language="en", free_voice="en-US-AriaNeural-Female", env=KOKORO_ENV
    )
    assert _engines(steps) == ["chosen", "kokoro", "edge-tts"]


def test_azure_v2_is_not_treated_as_edge():
    assert not nr.is_edge_voice("en-US-AvaMultilingualNeural-V2-Female")
    assert nr.is_edge_voice("en-US-AriaNeural-Female")
    assert not nr.is_edge_voice("no-voice")


# --------------------------------------------------------------------------- #
# narrate(): fallback execution and the clear error
# --------------------------------------------------------------------------- #
def _fake_tts(ok_engines: set[str]):
    calls: list[str] = []

    def fn(*, text, voice_name, voice_rate, voice_file):
        calls.append(voice_name)
        if any(voice_name.startswith(p) for p in ok_engines):
            with open(voice_file, "wb") as fh:
                fh.write(b"ID3audio")
            return object()
        return None

    return fn, calls


def test_kokoro_down_falls_back_to_edge(tmp_path):
    steps = nr.plan_chain("en-US-AriaNeural-Female", language="en", env=KOKORO_ENV)
    fn, calls = _fake_tts({"en-US"})
    result = nr.narrate("Hello there", steps, str(tmp_path / "a.mp3"), tts_fn=fn)
    assert calls == ["kokoro:af_heart", "en-US-AriaNeural-Female"]
    assert result.engine == "edge-tts"
    assert result.fell_back


def test_kokoro_up_is_used(tmp_path):
    steps = nr.plan_chain("en-US-AriaNeural-Female", language="en", env=KOKORO_ENV)
    fn, calls = _fake_tts({"kokoro:"})
    result = nr.narrate("Hello", steps, str(tmp_path / "a.mp3"), tts_fn=fn)
    assert calls == ["kokoro:af_heart"]
    assert result.engine == "kokoro"
    assert not result.fell_back


def test_raising_engine_does_not_end_the_chain(tmp_path):
    def fn(*, text, voice_name, voice_rate, voice_file):
        if voice_name.startswith("kokoro:"):
            raise ConnectionError("sidecar down")
        with open(voice_file, "wb") as fh:
            fh.write(b"x")
        return object()

    steps = nr.plan_chain("en-US-AriaNeural-Female", language="en", env=KOKORO_ENV)
    assert nr.narrate("Hi", steps, str(tmp_path / "a.mp3"), tts_fn=fn).engine == "edge-tts"


def test_all_engines_down_is_a_clear_error(tmp_path):
    steps = nr.plan_chain(
        "en-US-AriaNeural-Female",
        language="en",
        premium_voice="elevenlabs:abc:Rachel",
        env=KOKORO_ENV,
    )
    fn, calls = _fake_tts(set())
    with pytest.raises(nr.NarrationUnavailable) as err:
        nr.narrate("Hi", steps, str(tmp_path / "a.mp3"), tts_fn=fn)
    assert len(calls) == 3
    assert "No voice engine could narrate this reel" in str(err.value)
    assert err.value.attempts[0].startswith("kokoro:")


def test_stale_partial_file_never_counts_as_audio(tmp_path):
    out = tmp_path / "a.mp3"
    out.write_bytes(b"partial")

    def fn(*, text, voice_name, voice_rate, voice_file):
        return object()  # claims success but writes nothing

    with pytest.raises(nr.NarrationUnavailable):
        nr.narrate("Hi", [nr.VoiceStep("edge-tts", "en-US-AriaNeural-Female")], str(out), tts_fn=fn)


# --------------------------------------------------------------------------- #
# Kokoro adapter: captioned speech -> SubMaker with word timings
# --------------------------------------------------------------------------- #
def _captioned_body():
    return {
        "audio": base64.b64encode(b"ID3fake-mp3").decode(),
        "audio_format": "mp3",
        "timestamps": [
            {"word": "Hello", "start_time": 0.0, "end_time": 0.4},
            {"word": ",", "start_time": 0.4, "end_time": 0.45},
            {"word": "world", "start_time": 0.5, "end_time": 0.9},
            {"word": ".", "start_time": 0.9, "end_time": 0.95},
        ],
    }


def test_kokoro_adapter_builds_word_timings(tmp_path):
    seen = {}

    def post(url, payload, timeout):
        seen.update(url=url, payload=payload)
        return 200, _captioned_body(), ""

    out = tmp_path / "audio.mp3"
    sub = kt.kokoro_tts(
        "Hello, world.", "kokoro:af_heart", str(out), 1.1, base_url="http://k:8880", post_fn=post
    )
    assert sub is not None
    assert out.read_bytes() == b"ID3fake-mp3"
    assert seen["url"] == "http://k:8880/dev/captioned_speech"
    assert seen["payload"]["voice"] == "af_heart"
    assert seen["payload"]["stream"] is False
    assert seen["payload"]["speed"] == pytest.approx(1.1)
    assert [(w.text, w.start, w.end) for w in sub.words] == [
        ("Hello,", 0.0, 0.45),
        ("world.", 0.5, 0.95),
    ]
    from app.services import voice
    from app.services.reelforge import _submaker_words

    assert voice.get_audio_duration(sub) == pytest.approx(0.95)
    assert _submaker_words(sub) == [["Hello,", 0.0, 0.45], ["world.", 0.5, 0.95]]


@pytest.mark.parametrize(
    "response",
    [
        (500, None, "boom"),
        (200, {"audio": "", "timestamps": []}, ""),
        (200, {"audio": base64.b64encode(b"x").decode(), "timestamps": []}, ""),
        (200, ["not", "a", "dict"], ""),
    ],
)
def test_kokoro_adapter_failures_return_none(tmp_path, response):
    sub = kt.kokoro_tts(
        "Hi", "kokoro:af_heart", str(tmp_path / "a.mp3"), base_url="http://k", post_fn=lambda *a: response
    )
    assert sub is None


def test_kokoro_adapter_network_error_returns_none(tmp_path):
    def post(*_a):
        raise TimeoutError("slow")

    assert kt.kokoro_tts("Hi", "kokoro:af_heart", str(tmp_path / "a.mp3"), base_url="http://k", post_fn=post) is None


def test_kokoro_adapter_off_without_url(tmp_path):
    assert kt.kokoro_tts("Hi", "kokoro:af_heart", str(tmp_path / "a.mp3"), env={}) is None


def test_voice_tts_dispatches_kokoro_voices(monkeypatch, tmp_path):
    from app.services import voice

    called = {}

    def fake(text, voice_name, voice_file, voice_rate):
        called["voice"] = voice_name
        return "sub"

    monkeypatch.setattr(kt, "kokoro_tts", fake)
    assert voice.tts("Hi", "kokoro:am_michael", 1.0, str(tmp_path / "a.mp3")) == "sub"
    assert called["voice"] == "kokoro:am_michael"


# --------------------------------------------------------------------------- #
# stage_tts uses the chain
# --------------------------------------------------------------------------- #
def test_stage_tts_falls_back_to_edge_when_kokoro_is_down(monkeypatch, tmp_path):
    from app.services import reelforge, voice

    monkeypatch.setenv("KOKORO_URL", "http://kokoro:8880")
    monkeypatch.setattr(reelforge, "_workdir", lambda job_id: str(tmp_path))

    class _R2:
        def upload_file(self, path, key, ctype):
            return f"https://r2/{key}"

    monkeypatch.setattr(reelforge, "_r2", lambda: _R2())
    tried: list[str] = []

    def fake_tts(*, text, voice_name, voice_rate, voice_file):
        tried.append(voice_name)
        if voice_name.startswith("kokoro:"):
            return None
        with open(voice_file, "wb") as fh:
            fh.write(b"ID3")
        return kt.build_submaker([kt.WordTiming("Hi", 0.0, 0.5)])

    monkeypatch.setattr(voice, "tts", fake_tts)
    params = reelforge.ReelForgeParams(
        video_subject="hi", video_script="Hi", voice_name="en-US-AriaNeural-Female"
    )  # language stays "auto": the engine language comes from the voice
    out = reelforge.stage_tts("job-m14", params, {"script": "Hi"})
    assert tried == ["kokoro:af_heart", "en-US-AriaNeural-Female"]
    assert out["tts_engine"] == "edge-tts"
    assert out["tts_voice"] == "en-US-AriaNeural-Female"
    assert out["audio_duration"] == pytest.approx(0.5)
    assert out["words"] == [["Hi", 0.0, 0.5]]


# --------------------------------------------------------------------------- #
# Box 1 second render slot consumes every render lane (infra-box, if checked out)
# --------------------------------------------------------------------------- #
def test_second_slot_consumes_every_lane_queue():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(
        os.path.dirname(root), "infra-box", "stacks", "menivor-render", "docker-compose.yml"
    )
    if not os.path.isfile(path):
        pytest.skip("infra-box checkout not next to videogen")
    from app.domains.reels.policy import worker_queue_order

    text = open(path, encoding="utf-8").read()
    assert f"MENIVOR_RENDER2_QUEUES:-{worker_queue_order()}}}" in text
