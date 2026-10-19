"""Replicate-backed lanes for every Very ___ Time step (only REPLICATE_API_TOKEN configured)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.domains.film import story8_render, very_time_lanes as lanes, very_time_voice as voice
from app.domains.gateway import media_catalog, replicate_image, replicate_run
from app.domains.gateway.provider_execution import MediaProviderExecutor
from reelforge_provider_adapter.execution import ProviderRequestV1
from app.domains.routing import license_class
from app.domains.routing.providers import replicate_lipsync, wan_replicate
from app.domains.routing.providers.kling_fal import KlingError
from app.services.audio import sfx_replicate
from app.services.tts import replicate_speech

FFMPEG = shutil.which("ffmpeg")


class _Resp:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code, self._body, self.content = status, body or {}, content

    def json(self):
        return self._body


class _Session:
    """Records every call; answers submits as finished predictions and GETs of outputs with bytes."""

    def __init__(self, output="https://replicate.delivery/out.mp3", status="succeeded", content=b"ID3"):
        self.calls, self.output, self.status, self.content = [], output, status, content

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append((method, url, json, dict(headers or {})))
        if url.startswith("https://replicate.delivery"):
            return _Resp(content=self.content)
        if method == "POST":
            return _Resp(201, {"id": "p1", "status": self.status, "output": self.output,
                               "urls": {"get": "https://api.replicate.com/v1/predictions/p1"}})
        return _Resp(200, {"id": "p1", "status": self.status, "output": self.output})


@pytest.fixture()
def only_replicate(monkeypatch):
    for name in ("FAL_KEY", "ARK_API_KEY", "ELEVENLABS_API_KEY", "MUSETALK_API_KEY", "MUSETALK_BASE_URL",
                 "VERY_TIME_IMAGE_MODEL", "VERY_TIME_REFERENCE_IMAGE_MODEL", "VERY_TIME_VIDEO_MODEL",
                 "VERY_TIME_REFERENCE_VIDEO_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8-test")
    from app.config import config

    monkeypatch.setitem(config.elevenlabs, "api_key", "")


# --------------------------------------------------------------------------- #
# Video: Seedance 2.0 / 1 Lite / Kling 2.1 input schemas
# --------------------------------------------------------------------------- #
def test_seedance2_first_frame_only_uses_image():
    inp = wan_replicate._build_input(model_path="bytedance/seedance-2.0", prompt="p", seconds=2,
                                     aspect_ratio="9:16", image_url="https://x/f.png")
    assert inp == {"prompt": "p", "image": "https://x/f.png", "duration": 4, "aspect_ratio": "9:16",
                   "resolution": "720p", "generate_audio": True}


def test_seedance2_references_never_combine_with_image():
    inp = wan_replicate._build_input(model_path="bytedance/seedance-2.0", prompt="p", seconds=20,
                                     image_url="https://x/f.png", image_urls=("https://x/sheet.png",),
                                     resolution="1080p", generate_audio=False, seed=7)
    assert "image" not in inp
    assert inp["reference_images"] == ["https://x/f.png", "https://x/sheet.png"]
    assert inp["duration"] == 15 and inp["resolution"] == "1080p" and inp["generate_audio"] is False
    assert inp["seed"] == 7
    with pytest.raises(KlingError):
        wan_replicate._build_input(model_path="bytedance/seedance-2.0", prompt="p",
                                   image_urls=tuple(f"https://x/{i}.png" for i in range(10)))


def test_seedance1_lite_and_kling_schemas():
    lite = wan_replicate._build_input(model_path="bytedance/seedance-1-lite", prompt="p", seconds=30,
                                      image_urls=("https://x/a.png", "https://x/b.png"))
    assert lite["reference_images"] == ["https://x/a.png", "https://x/b.png"] and lite["duration"] == 12
    assert "generate_audio" not in lite
    kling = wan_replicate._build_input(model_path="kwaivgi/kling-v2.1", prompt="p", seconds=8,
                                       image_url="https://x/f.png")
    assert kling == {"prompt": "p", "start_image": "https://x/f.png", "duration": 10, "mode": "standard"}
    assert wan_replicate._build_input(model_path="kwaivgi/kling-v2.1", prompt="p", seconds=3,
                                      image_url="https://x/f.png")["duration"] == 5
    with pytest.raises(KlingError):
        wan_replicate._build_input(model_path="kwaivgi/kling-v2.1", prompt="p")


def test_wan_models_keep_their_schema_and_refuse_references():
    inp = wan_replicate._build_input(model_path="wan-video/wan-2.2-i2v-fast", prompt="p", seconds=5,
                                     image_url="https://x/f.png")
    assert inp == {"prompt": "p", "aspect_ratio": "9:16", "num_frames": 81, "image": "https://x/f.png"}
    with pytest.raises(KlingError):
        wan_replicate._build_input(model_path="wan-video/wan-2.2-i2v-fast", prompt="p", image_urls=("https://x",))


def _video_request(model_id, refs):
    from app.domains.gateway.media_gateway import _provider_request

    model = media_catalog.get_row(model_id)
    return _provider_request(model, correlation_id="c1", prompt="brief", cost_micros=1, duration_seconds=5,
                             aspect_ratio="9:16", input_refs=refs)


def test_executor_sends_references_to_seedance_on_replicate():
    session = _Session(status="starting")
    MediaProviderExecutor(api_key="r8", session_http=session).submit(
        _video_request("bytedance/seedance-2.0-r2v-replicate", ("https://x/f.png", "https://x/sheet.png")))
    method, url, body, headers = session.calls[0]
    assert url.endswith("/models/bytedance/seedance-2.0/predictions") and headers["Authorization"] == "Bearer r8"
    assert body["input"]["reference_images"] == ["https://x/f.png", "https://x/sheet.png"]
    assert "image" not in body["input"] and body["input"]["resolution"] == "720p"
    session = _Session(status="starting")
    MediaProviderExecutor(api_key="r8", session_http=session).submit(
        _video_request("bytedance/seedance-2.0-i2v-replicate", ("https://x/f.png",)))
    assert session.calls[0][2]["input"]["image"] == "https://x/f.png"


# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #
def test_replicate_image_reference_mapping():
    seedream = replicate_image.build_image_input("bytedance/seedream-4.5", "p", image_urls=("https://x/a", "https://x/b"))
    assert seedream == {"prompt": "p", "size": "custom", "width": 1080, "height": 1920,
                        "image_input": ["https://x/a", "https://x/b"]}
    kontext = replicate_image.build_image_input("black-forest-labs/flux-kontext-pro", "p", image_urls=("https://x/a",))
    assert kontext == {"prompt": "p", "aspect_ratio": "9:16", "input_image": "https://x/a"}
    with pytest.raises(KlingError):
        replicate_image.build_image_input("black-forest-labs/flux-kontext-pro", "p", image_urls=("a", "b"))
    with pytest.raises(KlingError):
        replicate_image.build_image_input("ideogram-ai/ideogram-v3-turbo", "p", image_urls=("https://x/a",))
    assert replicate_image.build_image_input("ideogram-ai/ideogram-v3-turbo", "p") == {"prompt": "p",
                                                                                      "aspect_ratio": "9:16"}


def test_executor_passes_image_refs_to_replicate():
    from app.domains.gateway.media_gateway import _provider_request

    session = _Session(output=["https://replicate.delivery/img.png"])
    model = media_catalog.get_row("bytedance/seedream-4.5-replicate")
    result = MediaProviderExecutor(api_key="r8", session_http=session).submit(
        _provider_request(model, correlation_id="c", prompt="still", cost_micros=1, input_refs=("https://x/g.png",)))
    assert result.outputs[0].reference == "https://replicate.delivery/img.png"
    assert session.calls[0][2]["input"]["image_input"] == ["https://x/g.png"]
    imagen = ProviderRequestV1(provider_key="imagen", model_ref="m", correlation_id="c", modality="image",
                               prompt="p", input_refs=("https://x/a",), parameters={"estimated_cost_micros": 0,
                                                                                   "quantity_units": 1})
    from reelforge_provider_adapter.execution import ProviderExecutionException

    with pytest.raises((KlingError, ProviderExecutionException), match="does not take reference images"):
        MediaProviderExecutor(api_key="k", session_http=session).submit(imagen)


def test_catalog_rows_are_present_unverified_and_sellable():
    for model_id, inputs in (("bytedance/seedance-2.0-i2v-replicate", ("prompt", "image")),
                             ("bytedance/seedance-2.0-r2v-replicate", ("prompt", "images")),
                             ("bytedance/seedance-1-lite-r2v-replicate", ("prompt", "images")),
                             ("kwaivgi/kling-v2.1-i2v-replicate", ("prompt", "image")),
                             ("bytedance/seedream-4.5-replicate", ("prompt", "images")),
                             ("black-forest-labs/flux-kontext-pro-replicate", ("prompt", "image"))):
        row = media_catalog.get_row(model_id)
        assert row is not None and row.inputs == inputs and not row.legacy
        assert row.price_source.startswith("https://replicate.com/") and row.price_verified is False
        assert license_class.is_model_sellable(model_id), model_id
    assert not license_class.is_model_sellable("zsxkib/mmaudio")
    assert license_class.is_model_sellable(sfx_replicate.MODEL)


# --------------------------------------------------------------------------- #
# Voice, sound effects, lip-sync
# --------------------------------------------------------------------------- #
def test_minimax_speech_input_and_download(tmp_path, monkeypatch):
    inp = replicate_speech.build_input("You met me at a very Turkish time in my life.", delivery="deadpan",
                                       language="tr")
    assert inp["emotion"] == "neutral" and inp["speed"] == 0.95 and inp["voice_id"] == replicate_speech.DEFAULT_VOICE
    assert inp["language_boost"] == "Turkish" and inp["audio_format"] == "mp3"
    assert replicate_speech.build_input("x", delivery="quiet", speed=3)["speed"] == 2.0
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8")
    monkeypatch.setattr("app.services.tts.eleven_v3.audio_seconds", lambda path: 2.4)
    session = _Session()
    out = tmp_path / "vo.mp3"
    assert replicate_speech.synthesize("line", delivery="tired", out_path=str(out), session=session) == 2.4
    assert out.read_bytes() == b"ID3"
    submit = session.calls[0]
    assert submit[1].endswith("/models/minimax/speech-02-hd/predictions") and submit[3]["Prefer"] == "wait"
    assert submit[2]["input"]["emotion"] == "sad"
    with pytest.raises(replicate_speech.ReplicateSpeechError):
        replicate_speech.build_input("   ")


def test_premium_takes_route_to_replicate_when_only_its_token_is_set(only_replicate, tmp_path, monkeypatch):
    assert voice.premium_backend() == voice.BACKEND_REPLICATE
    calls = []

    def fake_synth(text, *, voice_id, delivery, out_path, speed=None, language="", seed=None):
        calls.append((text, voice_id, delivery, speed))
        subprocess.run([story8_render.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=200:sample_rate=16000:duration=1", out_path], check=True)
        return 1.0

    monkeypatch.setattr(replicate_speech, "synthesize", fake_synth)
    monkeypatch.setattr("app.services.tts.eleven_v3.audio_seconds", lambda path: 1.0)
    takes = voice.make_takes(line="the line", engine="eleven_v3", delivery="deadpan", language="en", count=3,
                             work_dir=str(tmp_path))
    assert len(takes) == 3 and [c[3] for c in calls] == list(voice.REPLICATE_SPEEDS)
    calls.clear()
    voice.make_takes(line="the line", reply_line="the reply", engine="eleven_v3", delivery="deadpan",
                     language="en", count=1, work_dir=str(tmp_path))
    assert [c[1] for c in calls] == [replicate_speech.default_voice(), replicate_speech.default_reply_voice()]


def test_premium_voice_unavailable_without_any_key(monkeypatch, tmp_path):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    from app.config import config

    monkeypatch.setitem(config.elevenlabs, "api_key", "")
    assert voice.premium_backend() == ""
    with pytest.raises(voice.VoiceError) as err:
        voice.make_takes(line="l", engine="eleven_v3", delivery="deadpan", language="en", count=1,
                         work_dir=str(tmp_path))
    assert err.value.code == "voice_unavailable"


def test_stable_audio_sfx(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8")
    inp = sfx_replicate.build_input("tea spoon clinks on a tulip glass", seconds=2.4, seed=3)
    assert inp["duration"] == 2 and inp["seed"] == 3 and "no music" in inp["prompt"]
    assert sfx_replicate.build_input("x", seconds=99)["duration"] == sfx_replicate.MAX_S
    session = _Session(output="https://replicate.delivery/sfx.wav", content=b"RIFF")
    out = tmp_path / "sfx.wav"
    sfx_replicate.generate_sfx("ferry horn", seconds=3, out_path=str(out), video_url="https://x/v.mp4",
                               session=session)
    assert out.read_bytes() == b"RIFF"
    body = session.calls[0][2]["input"]
    assert session.calls[0][1].endswith("/models/stability-ai/stable-audio-2.5/predictions")
    assert "video" not in body and "image" not in body


def test_replicate_lipsync_submit_and_poll(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8")
    session = _Session(status="starting", output=None)
    run = replicate_lipsync.submit("https://x/v.mp4", "https://x/a.wav", "story8:1:4", session=session)
    assert run["provider"] == "replicate-lipsync" and run["run_id"] == "p1" and run["state"] == "running"
    assert session.calls[0][2]["input"]["video"] == "https://x/v.mp4"
    done = _Session(status="succeeded", output="https://replicate.delivery/ls.mp4")
    assert replicate_lipsync.poll(run, session=done) == ("completed", "https://replicate.delivery/ls.mp4")
    assert replicate_lipsync.poll(run, session=_Session(status="failed")) == ("failed", "")
    assert replicate_lipsync.poll(run, session=_Session(status="processing")) == ("running", "")

    class Broken:
        def request(self, *a, **k):
            raise ConnectionError("down")

    assert replicate_lipsync.poll(run, session=Broken())[0] == "failed"
    assert replicate_lipsync.poll({}, session=done) == ("failed", "")
    monkeypatch.delenv("REPLICATE_API_TOKEN")
    with pytest.raises(RuntimeError):
        replicate_lipsync.submit("https://x/v.mp4", "https://x/a.wav")


def test_run_raises_on_failed_prediction(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8")
    with pytest.raises(KlingError):
        replicate_run.run("minimax/speech-02-hd", {"text": "x"}, session=_Session(status="failed"))
    monkeypatch.delenv("REPLICATE_API_TOKEN")
    with pytest.raises(KlingError):
        replicate_run.run("minimax/speech-02-hd", {"text": "x"}, session=_Session())


# --------------------------------------------------------------------------- #
# Automatic lanes
# --------------------------------------------------------------------------- #
def test_lanes_only_replicate():
    env = {"REPLICATE_API_TOKEN": "r8"}
    assert lanes.summary(env) == {
        "image_model": "ideogram-ai/ideogram-v3-turbo", "reference_image_model": "google/nano-banana-pro-replicate",
        "video_model": "bytedance/seedance-2.0-i2v-replicate",
        "reference_video_model": "bytedance/seedance-2.0-r2v-replicate",
        "voice": "replicate", "sfx": "replicate", "lipsync": "replicate",
    }
    for model_id in [v for k, v in lanes.summary(env).items() if k.endswith("model")]:
        assert media_catalog.get_model(model_id) is not None, model_id


def test_lanes_fal_ark_and_none():
    fal = {"FAL_KEY": "f"}
    assert lanes.image_model(True, fal) == "bytedance-seed/seedream-4.5-edit"
    assert lanes.video_model(False, fal) == "bytedance/seedance-2.0-i2v"
    assert lanes.voice_backend(fal) == "free" and lanes.sfx_backend(fal) == "" and lanes.lipsync_backend(fal) == ""
    both = {"FAL_KEY": "f", "ARK_API_KEY": "a", "REPLICATE_API_TOKEN": "r"}
    assert lanes.video_model(True, both) == "bytedance/seedance-2.0-r2v-ark"
    assert lanes.image_model(False, both) == "ideogram/ideogram-v3"
    assert lanes.image_model(True, {}) is None and lanes.video_model(True, {}) is None
    assert lanes.voice_backend({}) == "free"
    keyed = {"ELEVENLABS_API_KEY": "x", "MUSETALK_API_KEY": "m", "MUSETALK_BASE_URL": "https://m",
             "REPLICATE_API_TOKEN": "r"}
    assert (lanes.voice_backend(keyed), lanes.sfx_backend(keyed), lanes.lipsync_backend(keyed)) == (
        "elevenlabs", "elevenlabs", "musetalk")
    over = {"REPLICATE_API_TOKEN": "r", "VERY_TIME_VIDEO_MODEL": "kwaivgi/kling-v2.1-i2v-replicate"}
    assert lanes.video_model(False, over) == "kwaivgi/kling-v2.1-i2v-replicate"
    assert all(isinstance(v, bool) for v in lanes.keys(both).values())


def test_nano_banana_pro_on_replicate_takes_references_and_is_sellable():
    from app.domains.gateway.replicate_image import build_image_input
    from app.domains.routing.license_class import is_model_sellable

    row = media_catalog.get_model("google/nano-banana-pro-replicate")
    assert row is not None and row.inputs == ("prompt", "images") and row.price_micros == 150_000
    assert is_model_sellable(row.id)
    inp = build_image_input("google/nano-banana-pro", "p", aspect_ratio="9:16",
                            image_urls=["https://a/sheet.png", "https://a/garment.png"])
    assert inp == {"prompt": "p", "aspect_ratio": "9:16", "resolution": "2K", "output_format": "png",
                   "image_input": ["https://a/sheet.png", "https://a/garment.png"]}
