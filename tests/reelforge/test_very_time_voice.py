"""Very ___ Time voice: Eleven v3 tags and dialogue, the take picker, the free path, the takes route."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.config import config
from app.domains.film import story8_render, very_time, very_time_voice as vv
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.services import ratelimit
from app.services.tts import eleven_v3
from app.utils import utils

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
KEY = "vt-voice-key"
H = {"x-api-key": KEY}
URL = "/api/v1/film/very-time/takes"
LINE = "You met me at a very Turkish time in my life."


# --------------------------------------------------------------------------- #
# Fakes and helpers
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status=200, content=b"ID3fake", body=None):
        self.status_code = status
        self.content = content
        self._body = body or {}

    def json(self):
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "params": params})
        return self.responses.pop(0)


@pytest.fixture()
def keyed(monkeypatch):
    monkeypatch.setitem(config.elevenlabs, "api_key", "xi-test")
    monkeypatch.setattr(eleven_v3, "audio_seconds", lambda path: 2.5)
    monkeypatch.delenv(eleven_v3.VOICE_ENV, raising=False)
    monkeypatch.delenv(eleven_v3.REPLY_VOICE_ENV, raising=False)


def _tone(path, *, seconds=1.5, freq=220, wobble=False):
    """A flat sine, or one with big loudness and pitch swings (wobble)."""
    if wobble:
        expr = f"aevalsrc='(0.1+0.8*abs(sin(2*PI*3*t)))*sin(2*PI*({freq}+400*sin(2*PI*2*t))*t)':s=16000:d={seconds}"
    else:
        expr = f"sine=frequency={freq}:sample_rate=16000:duration={seconds}"
    subprocess.run([story8_render.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", expr, path], check=True)
    return path


def _probe_seconds(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


# --------------------------------------------------------------------------- #
# Eleven v3
# --------------------------------------------------------------------------- #
def test_tagged_text_sanitises_and_caps_tags():
    assert eleven_v3.tagged_text("  You  met me ", ["deadpan", "flatly"]) == "[deadpan] [flatly] You met me"
    assert eleven_v3.tagged_text("x", ["a]b[c", "<script>", "one", "two", "three"]) == "[a b c] [script] [one] x"
    assert eleven_v3.tagged_text("x", []) == "x"
    assert eleven_v3.DELIVERY_TAGS["deadpan"] == ("deadpan", "flatly")


def test_synthesize_posts_v3_with_tags_voice_and_seed(keyed, tmp_path):
    sess = _Session([_Resp(content=b"ID3audio")])
    out = tmp_path / "a.mp3"
    seconds = eleven_v3.synthesize(LINE, voice_id="JBFqnCBsd6RMkjVDRZzb", tags=("deadpan",), out_path=str(out),
                                   seed=2, session=sess)
    assert seconds == 2.5 and out.read_bytes() == b"ID3audio"
    call = sess.calls[0]
    assert call["url"].endswith("/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb")
    assert call["json"]["model_id"] == "eleven_v3"
    assert call["json"]["text"] == f"[deadpan] {LINE}"
    assert call["json"]["seed"] == 2
    assert call["headers"]["xi-api-key"] == "xi-test"
    assert call["params"] == {"output_format": "mp3_44100_128"}


def test_dialogue_posts_both_voices_in_order(keyed, tmp_path):
    sess = _Session([_Resp()])
    eleven_v3.dialogue([(LINE, "JBFqnCBsd6RMkjVDRZzb", ("deadpan",)), ("Sit down.", "21m00Tcm4TlvDq8ikWAM", ())],
                       out_path=str(tmp_path / "d.mp3"), seed=3, session=sess)
    call = sess.calls[0]
    assert call["url"].endswith("/v1/text-to-dialogue")
    assert call["json"]["model_id"] == "eleven_v3" and call["json"]["seed"] == 3
    assert call["json"]["inputs"] == [{"text": f"[deadpan] {LINE}", "voice_id": "JBFqnCBsd6RMkjVDRZzb"},
                                      {"text": "Sit down.", "voice_id": "21m00Tcm4TlvDq8ikWAM"}]


def test_non_retryable_errors_stop_and_transient_ones_retry(keyed, tmp_path):
    sess = _Session([_Resp(status=401, body={"detail": {"status": "unauthorized"}})])
    with pytest.raises(eleven_v3.ElevenV3Error) as err:
        eleven_v3.synthesize(LINE, voice_id="JBFqnCBsd6RMkjVDRZzb", out_path=str(tmp_path / "x.mp3"), session=sess)
    assert not err.value.retryable and len(sess.calls) == 1
    sess = _Session([_Resp(status=500), _Resp(status=429), _Resp()])
    eleven_v3.synthesize(LINE, voice_id="JBFqnCBsd6RMkjVDRZzb", out_path=str(tmp_path / "y.mp3"), session=sess)
    assert len(sess.calls) == 3


def test_disabled_and_bad_voice_are_refused(monkeypatch, tmp_path):
    monkeypatch.setitem(config.elevenlabs, "api_key", "")
    assert not eleven_v3.is_enabled()
    with pytest.raises(eleven_v3.ElevenV3Error):
        eleven_v3.synthesize(LINE, voice_id="JBFqnCBsd6RMkjVDRZzb", out_path=str(tmp_path / "x.mp3"),
                             session=_Session([]))
    monkeypatch.setitem(config.elevenlabs, "api_key", "k")
    with pytest.raises(eleven_v3.ElevenV3Error):
        eleven_v3.synthesize(LINE, voice_id="../x", out_path=str(tmp_path / "x.mp3"), session=_Session([]))


def test_default_voices_are_configurable(monkeypatch):
    assert eleven_v3.default_voice() == eleven_v3.DEFAULT_VOICE
    monkeypatch.setenv(eleven_v3.VOICE_ENV, "abcdefgh1234")
    monkeypatch.setenv(eleven_v3.REPLY_VOICE_ENV, "zyxwvuts9876")
    assert eleven_v3.default_voice() == "abcdefgh1234" and eleven_v3.default_reply_voice() == "zyxwvuts9876"


# --------------------------------------------------------------------------- #
# Take picker
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_flatness_ranks_a_flat_tone_below_a_swinging_one(tmp_path):
    flat = vv.flatness(_tone(str(tmp_path / "flat.wav")))
    swing = vv.flatness(_tone(str(tmp_path / "swing.wav"), wobble=True))
    assert flat < swing


def test_pick_prefers_flat_and_penalises_long_takes():
    takes = [vv.Take("a", 3.0, 5.0), vv.Take("b", 6.0, 1.0), vv.Take("c", 3.5, 2.0)]
    assert vv.pick(takes) == 1
    assert vv.pick(takes, max_seconds=4.0) == 2
    assert vv.pick([vv.Take("a", 9, 3.0), vv.Take("b", 9, 2.0)], max_seconds=4.0) == 1
    with pytest.raises(ValueError):
        vv.pick([])


@pytest.mark.parametrize("key,ok", [
    ("vt-takes/u1/0123456789abcdef0123456789abcdef/take-1.mp3", True),
    ("vt-takes/u1/0123456789abcdef0123456789abcdef/take-3.mp3", True),
    ("vt-takes/u2/0123456789abcdef0123456789abcdef/take-1.mp3", False),
    ("vt-takes/u1/0123456789abcdef0123456789abcdef/take-4.mp3", False),
    ("vt-takes/u1/../u2/0123456789abcdef/take-1.mp3", False),
    ("vt-takes/u1/NOTHEX0123456789abcdef/take-1.mp3", False),
    ("uploads/u1/0123456789abcdef0123456789abcdef/take-1.mp3", False),
    ("", False),
])
def test_owns_take(key, ok):
    assert vv.owns_take("u1", key) is ok
    assert vv.take_key("u1", "ab" * 16, 2) == f"vt-takes/u1/{'ab' * 16}/take-2.mp3"


def _fake_free(calls):
    def narrate(text, language, out_path, *, rate=1.0, voice=""):
        calls.append({"text": text, "rate": rate, "voice": voice})
        _tone(out_path, seconds=1.0, freq=200 + int(rate * 100))
    return narrate


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_free_takes_vary_the_rate(tmp_path):
    calls = []
    takes = vv.make_takes(line=LINE, engine="free", delivery="deadpan", language="en", count=3,
                          work_dir=str(tmp_path), free_narrate=_fake_free(calls))
    assert len(takes) == 3 and [c["rate"] for c in calls] == list(vv.FREE_RATES)
    assert all(t.seconds > 0.9 and t.flatness < float("inf") for t in takes)


@pytest.mark.skipif(not HAS_FFMPEG or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_free_two_voice_take_is_host_gap_reply(tmp_path):
    calls = []
    takes = vv.make_takes(line=LINE, reply_line="Sit down, the tea is ready.", engine="free", delivery="quiet",
                          language="tr", count=1, work_dir=str(tmp_path), free_narrate=_fake_free(calls))
    assert [c["voice"] for c in calls] == ["", vv.FREE_REPLY_VOICES["tr"]]
    assert abs(_probe_seconds(takes[0].path) - (2.0 + vv.REPLY_GAP_S)) < 0.15


class _FakeEleven:
    DEFAULT = eleven_v3.DEFAULT_VOICE

    def __init__(self):
        self.calls = []

    def is_enabled(self):
        return True

    def default_voice(self):
        return eleven_v3.DEFAULT_VOICE

    def default_reply_voice(self):
        return eleven_v3.DEFAULT_REPLY_VOICE

    def synthesize(self, text, *, voice_id, tags, out_path, seed):
        self.calls.append(("tts", text, voice_id, tuple(tags), seed))
        _tone(out_path, seconds=1.0 + seed * 0.1, wobble=seed != 2)
        return 1.0 + seed * 0.1

    def dialogue(self, turns, *, out_path, seed):
        self.calls.append(("dialogue", [t[1] for t in turns], seed))
        _tone(out_path, seconds=2.0)
        return 2.0

    def audio_seconds(self, path):
        return 1.0


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_eleven_takes_use_seeds_and_the_pick_is_the_flat_one(tmp_path):
    fake = _FakeEleven()
    takes = vv.make_takes(line=LINE, engine="eleven_v3", delivery="deadpan", language="en", count=3,
                          work_dir=str(tmp_path), eleven=fake)
    assert [c[4] for c in fake.calls] == [1, 2, 3]
    assert all(c[3] == ("deadpan", "flatly") for c in fake.calls)
    assert vv.pick(takes) == 1
    fake = _FakeEleven()
    vv.make_takes(line=LINE, reply_line="Sit.", engine="eleven_v3", delivery="deadpan", language="en", count=1,
                  work_dir=str(tmp_path), eleven=fake)
    assert fake.calls == [("dialogue", [eleven_v3.DEFAULT_VOICE, eleven_v3.DEFAULT_REPLY_VOICE], 1)]


def test_unknown_engine_or_delivery_is_refused(tmp_path):
    with pytest.raises(vv.VoiceError):
        vv.make_takes(line=LINE, engine="paid", delivery="deadpan", language="", count=1, work_dir=str(tmp_path))
    with pytest.raises(vv.VoiceError):
        vv.make_takes(line=LINE, engine="free", delivery="shouty", language="", count=1, work_dir=str(tmp_path))


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_take_for_job_uses_the_chosen_take_or_picks(tmp_path):
    key = vv.take_key("u1", "ab" * 16, 2)
    fetched = []
    path, seconds, used = vv.take_for_job(
        take_key=key, user_id="u1", line=LINE, engine="eleven_v3", delivery="deadpan", language="en",
        work_dir=str(tmp_path), fetch=lambda k: fetched.append(k) or b"ID3chosen", eleven=_FakeEleven())
    assert used == key and fetched == [key] and open(path, "rb").read() == b"ID3chosen" and seconds == 1.0
    with pytest.raises(vv.VoiceError) as err:
        vv.take_for_job(take_key=vv.take_key("u2", "ab" * 16, 1), user_id="u1", line=LINE, engine="free",
                        delivery="deadpan", language="en", work_dir=str(tmp_path), fetch=lambda k: b"")
    assert err.value.status_code == 403
    fake = _FakeEleven()
    path, _seconds, used = vv.take_for_job(take_key=None, user_id="u1", line=LINE, engine="eleven_v3",
                                           delivery="deadpan", language="en", work_dir=str(tmp_path),
                                           fetch=lambda k: b"", eleven=fake)
    assert used == "auto" and path.endswith("take-2.mp3") and len(fake.calls) == 3


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
@pytest.fixture()
def api(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    import app.controllers.v1.jobs as jobs_mod

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(jobs_mod, "get_session", _session)
    monkeypatch.setattr(vv, "get_session", _session)
    monkeypatch.delenv(very_time.BLOCKED_ENV, raising=False)
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    ratelimit._local_buckets.clear()
    with factory() as s:
        s.add(User(email="vv@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    uploads = []
    made = []
    monkeypatch.setattr(vv, "upload", lambda path, key: uploads.append(key))
    monkeypatch.setattr(vv, "media_url", lambda key: f"https://media.example/{key}")

    def fake_make(**kw):
        made.append(kw)
        return [vv.Take(f"/tmp/t{n}.mp3", 2.0, flat) for n, flat in enumerate((3.0, 1.0, 2.0)[: kw["count"]], 1)]

    monkeypatch.setattr(vv, "make_takes", fake_make)
    app = FastAPI()
    app.include_router(vv.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    yield TestClient(app), uploads, made
    ratelimit._local_buckets.clear()


def test_takes_route_returns_takes_and_the_recommended_one(api):
    client, uploads, made = api
    res = client.post(URL, headers=H, json={"place_word": "Turkish", "count": 3})
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert len(data["takes"]) == 3 and data["recommended"] == data["takes"][1]["key"]
    assert uploads == [t["key"] for t in data["takes"]]
    assert data["takes"][0]["url"].startswith("https://media.example/vt-takes/")
    assert made[0]["line"] == LINE and made[0]["engine"] == "free"


def test_takes_route_guard_blocks_before_any_voice_call(api):
    client, uploads, made = api
    res = client.post(URL, headers=H,
                      json={"place_word": "Turkish", "reply_line": "wave the flag and the sultan"})
    assert res.status_code == 400 and res.json()["data"]["code"] == "guard_blocked"
    assert made == [] and uploads == []


def test_takes_route_premium_voice_unavailable_is_503(api, monkeypatch):
    client, _uploads, made = api
    monkeypatch.setitem(config.elevenlabs, "api_key", "")
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    res = client.post(URL, headers=H, json={"place_word": "Turkish", "engine": "eleven_v3"})
    assert res.status_code == 503 and res.json()["data"]["code"] == "voice_unavailable" and made == []


def test_takes_route_validates_and_rate_limits(api):
    client, _uploads, _made = api
    assert client.post(URL, headers=H,
                       json={"place_word": "Turkish", "delivery": "shouty"}).status_code == 400
    assert client.post(URL, headers=H,
                       json={"place_word": "Turkish", "count": 4}).status_code == 422
    codes = [client.post(URL, headers=H, json={"place_word": "Turkish", "count": 1}).status_code
             for _ in range(vv.RATE_LIMIT + 1)]
    assert 429 in codes
