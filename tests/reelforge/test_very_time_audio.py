"""Very ___ Time sound: ElevenLabs SFX, room tone, ducked mix at -14 LUFS, payoff lip-sync helpers."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import wave

import numpy as np
import pytest

from app.domains.film import story8_render, very_time_audio as vta, very_time_payoff as payoff
from app.domains.routing.providers import _lipsync
from app.services.audio import sfx_elevenlabs as sfx

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG or not shutil.which("ffprobe"), reason="ffmpeg required")


# --------------------------------------------------------------------------- #
# ElevenLabs Sound Effects
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status, content=b""):
        self.status_code = status
        self.content = content


class _Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, json=None, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "params": params})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def eleven_key(monkeypatch):
    from app.config import config

    monkeypatch.setitem(config.elevenlabs, "api_key", "xi-test")
    return "xi-test"


def test_sfx_request_shape_and_file(tmp_path, eleven_key):
    session = _Session(_Resp(200, b"ID3audio"))
    out = sfx.generate_sfx("  spoon   clinks on a tea glass ", seconds=0.2, out_path=str(tmp_path / "s.mp3"),
                           session=session)
    assert open(out, "rb").read() == b"ID3audio"
    call = session.calls[0]
    assert call["url"] == "https://api.elevenlabs.io/v1/sound-generation"
    assert call["headers"]["xi-api-key"] == "xi-test"
    assert call["params"] == {"output_format": "mp3_44100_128"}
    assert call["json"] == {"text": "spoon clinks on a tea glass", "duration_seconds": 0.5,
                            "prompt_influence": 0.4, "model_id": "eleven_text_to_sound_v2"}
    assert sfx.is_enabled()


@pytest.mark.parametrize("status", [401, 403, 422])
def test_sfx_final_errors_do_not_retry(tmp_path, eleven_key, status):
    session = _Session(_Resp(status), _Resp(200, b"x"))
    with pytest.raises(sfx.SfxError) as err:
        sfx.generate_sfx("ferry horn", seconds=40, out_path=str(tmp_path / "s.mp3"), session=session)
    assert err.value.status == status and len(session.calls) == 1


def test_sfx_retries_once_on_rate_limit_and_server_errors(tmp_path, eleven_key):
    session = _Session(_Resp(429), _Resp(200, b"ok"))
    sfx.generate_sfx("ferry horn", seconds=40, out_path=str(tmp_path / "s.mp3"), session=session)
    assert len(session.calls) == 2 and session.calls[0]["json"]["duration_seconds"] == 30.0
    session = _Session(_Resp(503), _Resp(502), _Resp(200, b"never"))
    with pytest.raises(sfx.SfxError) as err:
        sfx.generate_sfx("ferry horn", seconds=2, out_path=str(tmp_path / "s.mp3"), session=session)
    assert err.value.retryable and len(session.calls) == 2


def test_sfx_without_key_or_text(tmp_path, monkeypatch):
    from app.config import config

    monkeypatch.setitem(config.elevenlabs, "api_key", "")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert not sfx.is_enabled()
    with pytest.raises(sfx.SfxError):
        sfx.generate_sfx("cat purr", seconds=2, out_path=str(tmp_path / "s.mp3"), session=_Session())
    monkeypatch.setitem(config.elevenlabs, "api_key", "k")
    with pytest.raises(sfx.SfxError):
        sfx.generate_sfx("   ", seconds=2, out_path=str(tmp_path / "s.mp3"), session=_Session())


# --------------------------------------------------------------------------- #
# Command shapes
# --------------------------------------------------------------------------- #
def _graph(command):
    return command[command.index("-filter_complex") + 1]


def test_mix_ducks_the_bed_under_the_voice():
    cmd = vta.mix_command(out="m.wav", total_s=15, vo="vo.mp3", vo_delay_s=10.6,
                          sfx=[("a.mp3", 0.4), ("b.mp3", 5.25)], room="room.wav", ffmpeg="ff")
    graph = _graph(cmd)
    assert cmd[:2] == ["ff", "-y"] and cmd[cmd.index("-map") + 1] == "[mix]"
    assert [cmd[i + 1] for i, v in enumerate(cmd) if v == "-i"] == ["vo.mp3", "room.wav", "a.mp3", "b.mp3"]
    assert "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=delays=10600:all=1" in graph
    assert "asplit=2[vo][key]" in graph
    assert "adelay=delays=400:all=1" in graph and "adelay=delays=5250:all=1" in graph
    assert "[room][sfx0][sfx1]amix=inputs=3:duration=longest:normalize=0[bed]" in graph
    assert f"[bed][key]{vta.DUCK}[duck]" in graph
    assert "[vo][duck]amix=inputs=2:duration=longest:normalize=0,atrim=0:15.000[mix]" in graph
    assert cmd[-7:] == ["-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", "m.wav"]


def test_mix_without_voice_has_no_ducking_and_without_bed_no_split():
    graph = _graph(vta.mix_command(out="m.wav", total_s=4, vo=None, room="room.wav", ffmpeg="ff"))
    assert "sidechaincompress" not in graph and "[room]anull[bed]" in graph and "[bed]atrim=0:4.000[mix]" in graph
    graph = _graph(vta.mix_command(out="m.wav", total_s=4, vo="vo.mp3", ffmpeg="ff"))
    assert "asplit" not in graph and "sidechaincompress" not in graph and graph.endswith("[mix]")
    cmd = vta.mix_command(out="m.wav", total_s=4, vo=None, ffmpeg="ff")
    assert "anullsrc=r=48000:cl=stereo" in cmd


def test_native_audio_and_silence_commands():
    cmd = vta.native_audio_command("shot.mp4", "r.wav", seconds=2.5, ffmpeg="ff")
    assert "-vn" in cmd and "apad,atrim=0:2.500" in cmd[cmd.index("-af") + 1]
    assert "anullsrc=r=48000:cl=stereo" in vta.silence_command("s.wav", 3, ffmpeg="ff")


def test_sfx_prompt_fills_slots():
    assert vta.sfx_prompt("{ritual}, close  and quiet {x}", {"ritual": "tea pouring"}) == \
        "tea pouring, close and quiet {x}"


def test_parse_loudnorm_json():
    text = 'noise\n[Parsed_loudnorm_0 @ 0x1]\n{\n "input_i" : "-23.1",\n "input_tp" : "-5.0"\n}\n'
    assert vta.parse_loudnorm_json(text) == {"input_i": "-23.1", "input_tp": "-5.0"}
    with pytest.raises(vta.AudioError):
        vta.parse_loudnorm_json("nothing")


def test_mux_command_default_is_unchanged_and_audio_filter_overrides():
    default = story8_render.mux_command("v.mp4", "a.mp3", "o.mp4", ffmpeg="ff", audio_delay_s=10.8)
    graph = default[default.index("-filter_complex") + 1]
    assert graph == ("[0:v]null[v];[1:a]loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100,"
                     "adelay=delays=10800:all=1,apad[a]")
    mixed = story8_render.mux_command("v.mp4", "mix.wav", "o.mp4", ffmpeg="ff", audio_delay_s=10.8,
                                      audio_filter="anull")
    assert mixed[mixed.index("-filter_complex") + 1] == "[0:v]null[v];[1:a]anull[a]"
    blank = story8_render.mux_command("v.mp4", "mix.wav", "o.mp4", ffmpeg="ff", audio_filter="")
    assert blank[blank.index("-filter_complex") + 1].endswith("[1:a]anull[a]")


# --------------------------------------------------------------------------- #
# Real ffmpeg: loudness, ducking, room tone, speech check
# --------------------------------------------------------------------------- #
def _ff(*args):
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def _tone(path, seconds, freq=440, peak=0.5):
    """A sine at ``peak`` amplitude (ffmpeg's sine source is 1/8 full scale)."""
    _ff("-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
        "-af", f"volume={peak * 8:g}", "-ac", "2", path)


def _noise(path, seconds, amplitude=0.08):
    _ff("-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:r=48000:a={amplitude}:seed=7", "-ac", "2", path)


def _ebur128(path):
    done = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true",
                           "-f", "null", "-"], capture_output=True, text=True, check=True)
    summary = done.stderr[done.stderr.rfind("Summary:"):]
    integrated = float(re.search(r"I:\s*(-?\d+(?:\.\d+)?) LUFS", summary).group(1))
    peak = float(re.search(r"Peak:\s*(-?\d+(?:\.\d+)?) dBFS", summary).group(1))
    return integrated, peak


def _samples(path):
    with wave.open(path, "rb") as fh:
        rate = fh.getframerate()
        data = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16).reshape(-1, fh.getnchannels())
    return rate, data[:, 0].astype(np.float64) / 32768.0


def _band_db(path, start, end, low_hz=2000.0):
    """Energy above ``low_hz`` (the noise bed, not the 440 Hz voice) in a window, dB."""
    rate, samples = _samples(path)
    window = samples[int(start * rate):int(end * rate)]
    spectrum = np.fft.rfft(window * np.hanning(len(window)))
    freqs = np.fft.rfftfreq(len(window), 1.0 / rate)
    energy = np.sum(np.abs(spectrum[freqs >= low_hz]) ** 2) / len(window) ** 2
    return 10 * np.log10(energy + 1e-12)


def _duration(path):
    out = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of",
                          "csv=p=0", path], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


@pytest.mark.integration
@needs_ffmpeg
def test_mix_and_master_hits_minus_14_lufs_and_ducks_the_bed(tmp_path):
    vo, room, click = str(tmp_path / "vo.wav"), str(tmp_path / "room.wav"), str(tmp_path / "click.wav")
    _tone(vo, 2.0)
    _noise(room, 15)
    _tone(click, 0.15, freq=3000, peak=0.6)
    mix, master = str(tmp_path / "mix.wav"), str(tmp_path / "master.wav")
    vta.run(vta.mix_command(out=mix, total_s=15, vo=vo, vo_delay_s=10.6, sfx=[(click, 2.0)], room=room,
                            ffmpeg=FFMPEG))
    measured = vta.loudnorm_two_pass(mix, master, ffmpeg=FFMPEG)
    assert "input_i" in measured
    integrated, peak = _ebur128(master)
    assert abs(integrated - vta.TARGET_LUFS) <= 1.0, integrated
    assert peak <= -1.0, peak
    assert abs(_duration(master) - 15.0) < 0.05
    # The bed (noise above 2 kHz) drops while the voice plays.
    before, during = _band_db(mix, 6.0, 10.0), _band_db(mix, 11.0, 12.4)
    assert before - during >= 6.0, (before, during)
    # Without a voice nothing ducks: the same windows stay level.
    bed_only = str(tmp_path / "bed.wav")
    vta.run(vta.mix_command(out=bed_only, total_s=15, vo=None, room=room, ffmpeg=FFMPEG))
    assert abs(_band_db(bed_only, 6.0, 10.0) - _band_db(bed_only, 11.0, 12.4)) < 2.0


@pytest.mark.integration
@needs_ffmpeg
def test_loudnorm_copies_a_silent_mix(tmp_path):
    silent, out = str(tmp_path / "s.wav"), str(tmp_path / "o.wav")
    vta.run(vta.silence_command(silent, 2, ffmpeg=FFMPEG))
    vta.loudnorm_two_pass(silent, out, ffmpeg=FFMPEG)
    assert abs(_duration(out) - 2.0) < 0.05


def _clip(path, seconds, *, audio):
    args = ["-f", "lavfi", "-i", f"color=c=gray:s=160x284:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds}",
                 "-c:a", "aac", "-shortest"]
    _ff(*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", path)


@pytest.mark.integration
@needs_ffmpeg
def test_room_tone_track_and_speech_present(tmp_path):
    voiced, mute = str(tmp_path / "voiced.mp4"), str(tmp_path / "mute.mp4")
    _clip(voiced, 3, audio=True)
    _clip(mute, 2, audio=False)
    assert vta.has_audio_stream(voiced, ffmpeg=FFMPEG) and not vta.has_audio_stream(mute, ffmpeg=FFMPEG)
    out = vta.room_tone_track([(voiced, 2.0), (mute, 2.0), (None, 1.5), (voiced, 4.0)],
                              str(tmp_path / "room.wav"), str(tmp_path), ffmpeg=FFMPEG)
    assert abs(_duration(out) - 9.5) < 0.05
    rate, samples = _samples(out)
    assert np.abs(samples[int(0.5 * rate):int(1.5 * rate)]).max() > 0.05  # native audio kept
    assert np.abs(samples[int(2.5 * rate):int(3.5 * rate)]).max() == 0.0  # silent slot
    assert payoff.speech_present(voiced, ffmpeg=FFMPEG)
    assert not payoff.speech_present(mute, ffmpeg=FFMPEG)
    silent_audio = str(tmp_path / "silent-audio.mp4")
    _ff("-f", "lavfi", "-i", "color=c=gray:s=160x284:d=2", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", silent_audio)
    assert not payoff.speech_present(silent_audio, ffmpeg=FFMPEG)


# --------------------------------------------------------------------------- #
# Payoff lip-sync (MuseTalk via the routing adapter)
# --------------------------------------------------------------------------- #
class FakeReq:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, path, *, json=None):
        self.calls.append((method, path, json))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _adapter(responses):
    req = FakeReq(responses)
    return _lipsync.build_lipsync_adapter("musetalk", api_key="k", request_fn=req), req


def test_lipsync_submit_and_poll_to_completed():
    adapter, req = _adapter([{"run_id": "m-1", "status": "queued"}, {"status": "processing"},
                             {"status": "completed", "output_url": "https://cdn/talk.mp4", "seconds": 4}])
    run = payoff.submit_lipsync(image_url="https://own/f.png", audio_url="https://own/vo.mp3",
                                correlation_id="vt:1", adapter=adapter)
    assert run == {"provider": "musetalk", "run_id": "m-1", "state": "running"}
    assert req.calls[0] == ("POST", "/run", {"image_url": "https://own/f.png", "audio_url": "https://own/vo.mp3",
                                             "correlation_id": "vt:1"})
    assert payoff.poll_lipsync(run, adapter=adapter) == ("running", "")
    assert payoff.poll_lipsync(run, adapter=adapter) == ("completed", "https://cdn/talk.mp4")


def test_lipsync_failures_map_to_failed_and_submit_raises():
    from app.domains.routing.base import ProviderError

    adapter, _ = _adapter([{"status": "failed"}, ProviderError("boom", provider_key="musetalk"),
                           {"status": "completed"}])
    run = {"run_id": "m-2"}
    assert payoff.poll_lipsync(run, adapter=adapter) == ("failed", "")
    assert payoff.poll_lipsync(run, adapter=adapter) == ("failed", "")
    assert payoff.poll_lipsync(run, adapter=adapter) == ("failed", "")  # completed without a url
    assert payoff.poll_lipsync({}, adapter=adapter) == ("failed", "")
    adapter, _ = _adapter([{"status": "queued"}])  # no run id
    with pytest.raises(RuntimeError):
        payoff.submit_lipsync(image_url="https://a/f.png", audio_url="https://a/v.mp3", correlation_id="c",
                              adapter=adapter)
    with pytest.raises(RuntimeError):
        payoff.submit_lipsync(image_url="", audio_url="https://a/v.mp3", correlation_id="c", adapter=adapter)


def test_lipsync_needs_configuration(monkeypatch):
    monkeypatch.delenv("MUSETALK_API_KEY", raising=False)
    monkeypatch.delenv("MUSETALK_BASE_URL", raising=False)
    assert not payoff.lipsync_configured()
    with pytest.raises(RuntimeError, match="not configured"):
        payoff.submit_lipsync(image_url="https://a/f.png", audio_url="https://a/v.mp3", correlation_id="c")
    monkeypatch.setenv("MUSETALK_API_KEY", "k")
    assert not payoff.lipsync_configured()
    monkeypatch.setenv("MUSETALK_BASE_URL", "https://api.runpod.ai/v2/musetalk/")
    assert payoff.lipsync_configured()
    assert payoff.PAYOFF_MODES == ("native", "lipsync", "voiceover")


def test_lipsync_base_url_env_override(monkeypatch):
    seeded = _lipsync.LIPSYNC_CONFIGS["musetalk"].base_url
    monkeypatch.delenv("MUSETALK_BASE_URL", raising=False)
    assert _lipsync.configured_base_url("musetalk") == seeded
    assert _lipsync.build_lipsync_adapter("musetalk", request_fn=FakeReq([]))._cfg.base_url == seeded
    monkeypatch.setenv("MUSETALK_BASE_URL", "https://api.runpod.ai/v2/musetalk/")
    assert _lipsync.configured_base_url("musetalk") == "https://api.runpod.ai/v2/musetalk"
    assert _lipsync.build_lipsync_adapter("musetalk", request_fn=FakeReq([]))._cfg.base_url == \
        "https://api.runpod.ai/v2/musetalk"
    assert _lipsync.LIPSYNC_CONFIGS["musetalk"].base_url == seeded  # the seeded config is not mutated
    assert os.environ["MUSETALK_BASE_URL"]
