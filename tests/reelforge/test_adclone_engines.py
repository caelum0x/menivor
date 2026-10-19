"""Ad Clone engines: cost estimates + selection, the official Kling client (JWT, i2v, lip-sync,
polling, caps), ElevenLabs Voice Design + TTS, and the Midjourney import / prompt helper.
All network is mocked; nothing here can spend."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import pytest

from app.domains.adclone import adapters, elevenlabs, engines, kling, midjourney, presets, rewrite
from app.domains.adclone.rewrite import CloneOptions
from app.domains.adclone.schemas import CloneBrief

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adclone" / "brief-tiktok-price-shock.json"
OXHAN = presets.load("oxhan")


@pytest.fixture()
def plan() -> dict:
    brief = CloneBrief.model_validate(json.loads(FIXTURE.read_text()))
    return rewrite.build_plan(brief, OXHAN, variation="a", options=CloneOptions())


# --------------------------------------------------------------------------- estimates + choice
def test_summary_and_per_engine_estimates(plan):
    ps = engines.summarize(plan)
    assert ps.payoff_s >= 5 and ps.stills == len(plan["stills"]) and ps.video_s == sum(s["dur"] for s in plan["shots"])
    rows = engines.estimates(plan, env={})
    by = {r["engine"]: r for r in rows}
    assert set(by) == {"kling", "higgsfield_kling", "replicate", "runpod_wan", "minimax_hailuo"}
    assert all(r["usd"] > 0 and r["source"] and not r["configured"] for r in rows)
    # Replicate estimate matches make_episode's standard tier arithmetic (2.5 at 480p + Seedream + 1 re-roll).
    close = sum(s["dur"] for s in plan["shots"] if s.get("framing", "close") != "wide")
    dearest = max(s["dur"] for s in plan["shots"]) * 0.1028
    assert by["replicate"]["usd"] == pytest.approx(close * 0.1028 + ps.stills * 0.035 + dearest, abs=0.01)
    clips = sum(5 if s["dur"] <= 5 else 10 for s in plan["shots"])
    assert by["kling"]["usd"] == pytest.approx(clips * 0.084 + clips / 5 * 0.07, abs=0.01)


def test_kling_is_default_when_its_keys_are_set(plan):
    rows = engines.estimates(plan, env={"KLING_ACCESS_KEY": "ak", "KLING_SECRET_KEY": "sk", "RUNPOD_API_KEY": "r",
                                        "RUNPOD_WAN_ENDPOINT_ID": "e"})
    chosen = engines.choose(rows)
    assert chosen["engine"] == "kling" and not chosen["dry_run_only"]


def test_cheapest_configured_engine_otherwise(plan):
    rows = engines.estimates(plan, env={"REPLICATE_API_TOKEN": "t", "MINIMAX_API_KEY": "m"})
    chosen = engines.choose(rows)
    cheapest = min((r for r in rows if r["configured"]), key=lambda r: r["usd"])
    assert chosen["engine"] == cheapest["engine"] and chosen["reason"] == "cheapest configured engine"


def test_nothing_configured_is_dry_run_only(plan):
    chosen = engines.choose(engines.estimates(plan, env={}))
    assert chosen["dry_run_only"] and chosen["engine"] == "runpod_wan"
    req = engines.choose(engines.estimates(plan, env={}), "kling")
    assert req["engine"] == "kling" and req["dry_run_only"]
    with pytest.raises(ValueError):
        engines.choose(engines.estimates(plan, env={}), "sora")


def test_kling_model_env_changes_price(plan):
    v3 = {r["engine"]: r for r in engines.estimates(plan, env={})}["kling"]["usd"]
    v26 = {r["engine"]: r for r in engines.estimates(plan, env={"KLING_MODEL": "kling-v2-6"})}["kling"]["usd"]
    assert v26 < v3


def test_voice_route():
    assert engines.voice_route({"ELEVENLABS_API_KEY": "x"})["engine"] == "elevenlabs"
    assert engines.voice_route({})["engine"] == "kokoro"


def test_stub_adapters_never_spend(plan):
    for name in ("higgsfield_kling", "runpod_wan", "minimax_hailuo", "replicate"):
        a = adapters.adapter_for(name)
        assert len(a.dry_run(plan)) == len(plan["shots"])
        with pytest.raises(adapters.EngineNotReady):
            a.render_shot()
    assert "make_episode.py" in adapters.ReplicateEpisode().command("../episodes/x.yaml")


# --------------------------------------------------------------------------- Kling client
def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_kling_jwt_is_hs256_signed_with_secret():
    token = kling.make_jwt("AK123", "SK456", now=1_000_000)
    h, p, sig = token.split(".")
    assert json.loads(_b64d(h)) == {"alg": "HS256", "typ": "JWT"}
    assert json.loads(_b64d(p)) == {"iss": "AK123", "exp": 1_001_800, "nbf": 999_995}
    expect = hmac.new(b"SK456", f"{h}.{p}".encode(), hashlib.sha256).digest()
    assert _b64d(sig) == expect


class FakeKling:
    def __init__(self, *, i2v_polls=2, fail=None, balance=False):
        self.calls = []
        self.polls = {"i2v": i2v_polls, "lipsync": 1}
        self.fail = fail
        self.balance = balance

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        assert headers["Authorization"].startswith("Bearer ")
        if self.balance:
            return 400, {"code": 1102, "message": "resource pack exhausted"}
        if method == "POST" and url.endswith("/v1/videos/image2video"):
            return 200, {"code": 0, "data": {"task_id": "t-i2v", "task_status": "submitted"}}
        if method == "POST" and url.endswith("/v1/videos/lip-sync"):
            return 200, {"code": 0, "data": {"task_id": "t-lip", "task_status": "submitted"}}
        kind = "i2v" if "image2video" in url else "lipsync"
        if self.fail == kind:
            return 200, {"code": 0, "data": {"task_status": "failed", "task_status_msg": "nsfw"}}
        self.polls[kind] -= 1
        if self.polls[kind] > 0:
            return 200, {"code": 0, "data": {"task_status": "processing"}}
        vid = {"i2v": {"id": "vid-1", "url": "https://cdn/i2v.mp4", "duration": "5"},
               "lipsync": {"id": "vid-2", "url": "https://cdn/lips.mp4", "duration": "5"}}[kind]
        return 200, {"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [vid]}}}


def _client(http, **kw):
    return kling.KlingClient(access_key="ak", secret_key="sk", http=http, sleep=lambda s: None,
                             clock=lambda: 1_000_000.0, **kw)


def test_kling_talk_shot_i2v_then_lipsync_with_polling():
    http = FakeKling(i2v_polls=3)
    client = _client(http, cap_usd=1.0)
    out = client.render_talk_shot(first_frame=b"\x89PNGframe", prompt="push-in", audio=b"ID3audio", seconds=4.6)
    assert out == {"video_id": "vid-1", "video_url": "https://cdn/i2v.mp4", "lipsync_url": "https://cdn/lips.mp4",
                   "seconds": 5, "spent_usd": pytest.approx(5 * 0.084 + 0.07)}
    posts = [c for c in http.calls if c[0] == "POST"]
    i2v = posts[0][3]
    assert i2v["model_name"] == "kling-v3" and i2v["duration"] == "5" and i2v["aspect_ratio"] == "9:16"
    assert base64.b64decode(i2v["image"]) == b"\x89PNGframe"
    lip = posts[1][3]["input"]
    assert lip == {"video_id": "vid-1", "mode": "audio2video", "audio_type": "file",
                   "audio_file": base64.b64encode(b"ID3audio").decode()}
    assert sum(1 for c in http.calls if c[0] == "GET") == 4
    assert all(c[1].startswith(kling.BASE_URL) for c in http.calls)


def test_kling_spend_cap_blocks_before_the_call():
    http = FakeKling()
    client = _client(http, cap_usd=0.30)
    with pytest.raises(kling.KlingError) as exc:
        client.image_to_video(image="x", prompt="p", seconds=5)
    assert exc.value.stop and http.calls == []


def test_kling_balance_error_stops_cleanly():
    with pytest.raises(kling.KlingError) as exc:
        _client(FakeKling(balance=True)).image_to_video(image="x", prompt="p", seconds=5)
    assert exc.value.stop and exc.value.code == 1102


def test_kling_failed_task_and_timeout():
    client = _client(FakeKling(fail="i2v"))
    with pytest.raises(kling.KlingError, match="failed"):
        client.wait("i2v", "t-i2v")
    ticks = iter(range(0, 10_000, 500))
    slow = kling.KlingClient(access_key="a", secret_key="s", http=FakeKling(i2v_polls=99), sleep=lambda s: None,
                             clock=lambda: float(next(ticks)))
    with pytest.raises(kling.KlingError, match="timed out"):
        slow.wait("i2v", "t", timeout_s=1000)


def test_kling_from_env_and_api_key_mode():
    with pytest.raises(kling.KlingError):
        kling.KlingClient.from_env({})
    c = kling.KlingClient.from_env({"KLING_API_KEY": "console-key", "KLING_MODEL": "kling-v2-6"}, http=FakeKling())
    assert c._headers()["Authorization"] == "Bearer console-key" and c.model == "kling-v2-6"


def test_kling_dry_run_requests_cost_matches_estimate(plan):
    reqs = kling.KlingClient().dry_run_requests(plan)
    assert [r["shot"] for r in reqs] == [s["id"] for s in plan["shots"]]
    total = sum(r["usd"] for r in reqs)
    est = {r["engine"]: r for r in engines.estimates(plan, env={})}["kling"]
    assert total == pytest.approx(est["usd"] - est["items"][2]["usd"], abs=0.01)


# --------------------------------------------------------------------------- ElevenLabs
class FakeEleven:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((url, headers, body))
        assert headers["xi-api-key"] == "el-key"
        if url.endswith("/v1/text-to-voice/design"):
            return 200, json.dumps({"previews": [{"generated_voice_id": "gen1", "audio_base_64": "AAA",
                                                  "duration_secs": 9.1}, {"generated_voice_id": "gen2"}]}).encode()
        if url.endswith("/v1/text-to-voice"):
            return 200, json.dumps({"voice_id": "VoiceId12345678"}).encode()
        if "/v1/text-to-speech/" in url:
            return 200, b"ID3mp3bytes"
        return 404, b""


def test_voice_design_save_and_lock_returns_new_preset():
    http = FakeEleven()
    client = elevenlabs.ElevenLabs(api_key="el-key", http=http)
    previews = client.design(OXHAN["characters"]["H"]["voice"]["voice_design"])
    assert [p["generated_voice_id"] for p in previews] == ["gen1", "gen2"]
    body = http.calls[0][2]
    assert body["model_id"] == elevenlabs.DESIGN_MODEL and "reference_audio_base64" not in body
    assert 100 <= len(body["text"]) <= 1000
    updated = elevenlabs.lock_character_voice(client, OXHAN, "O", "gen2")
    assert updated["characters"]["O"]["voice"]["elevenlabs_voice_id"] == "VoiceId12345678"
    assert OXHAN["characters"]["O"]["voice"]["elevenlabs_voice_id"] == ""
    assert http.calls[1][2]["generated_voice_id"] == "gen2"


def test_voice_design_refuses_imitation_without_calling_api():
    http = FakeEleven()
    with pytest.raises(Exception):
        elevenlabs.ElevenLabs(api_key="el-key", http=http).design("sounds like a famous actor")
    assert http.calls == []


def test_tts_per_line_uses_locked_voice_ids(plan, tmp_path):
    http = FakeEleven()
    client = elevenlabs.ElevenLabs(api_key="el-key", http=http)
    preset = presets.with_voice(presets.with_voice(OXHAN, "H", "HeroVoice1234"), "O", "OxhanVoice123")
    files = elevenlabs.line_audio(client, preset, plan, str(tmp_path))
    assert set(files) == {ln["id"] for ln in plan["lines"]}
    assert all(Path(f).read_bytes() == b"ID3mp3bytes" for f in files.values())
    urls = [c[0] for c in http.calls]
    assert any(u.endswith("/HeroVoice1234") for u in urls) and any(u.endswith("/OxhanVoice123") for u in urls)
    cta_call = next(c for c in http.calls if "Oxhan Atelier dot com" in c[2]["text"])
    assert cta_call[0].endswith("/HeroVoice1234")


def test_tts_without_locked_voice_and_errors(tmp_path):
    client = elevenlabs.ElevenLabs(api_key="el-key", http=lambda *a: (402, b"quota"))
    with pytest.raises(elevenlabs.ElevenLabsError) as exc:
        client.tts(voice_id="", text="hi", out_path=str(tmp_path / "x.mp3"))
    assert exc.value.status_code == 409
    with pytest.raises(elevenlabs.ElevenLabsError) as exc:
        client.tts(voice_id="VoiceId12345678", text="hi", out_path=str(tmp_path / "x.mp3"))
    assert exc.value.status_code == 402
    with pytest.raises(elevenlabs.ElevenLabsError):
        elevenlabs.ElevenLabs.from_env({})


# --------------------------------------------------------------------------- Midjourney (no automation)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
JPG = b"\xff\xd8\xff\xe0" + b"1" * 32


def test_import_inbox_tags_dedupes_and_skips(tmp_path):
    inbox, root = tmp_path / "inbox", tmp_path / "proj"
    (inbox / "hero").mkdir(parents=True)
    (inbox / "hero" / "mj_render_01.png").write_bytes(PNG)
    (inbox / "oxhan_take2.jpg").write_bytes(JPG)
    (inbox / "s3.png").write_bytes(PNG + b"x")
    (inbox / "random.png").write_bytes(PNG + b"y")
    (inbox / "side_fake.png").write_bytes(b"not an image")
    out = midjourney.import_inbox(str(inbox), str(root))
    tags = sorted(e["tag"] for e in out["imported"])
    assert tags == ["hero", "oxhan", "s3"]
    assert {s["why"] for s in out["skipped"]} == {"untagged", "not an image"}
    for e in out["imported"]:
        assert (root / e["path"]).is_file() and e["path"].startswith(f"mj/{e['tag']}/")
    again = midjourney.import_inbox(str(inbox), str(root))
    assert again["imported"] == [] and again["total"] == 3
    with pytest.raises(midjourney.ImportError_):
        midjourney.import_inbox(str(tmp_path / "missing"), str(root))


def test_first_frames_prefer_still_tag_then_character(plan):
    manifest = [{"tag": "hero", "path": "mj/hero/a.png", "sha256": "1"},
                {"tag": "oxhan", "path": "mj/oxhan/b.png", "sha256": "2"}]
    still_of_first_shot = plan["shots"][0]["refs"][0]
    manifest.append({"tag": still_of_first_shot, "path": f"mj/{still_of_first_shot}/c.png", "sha256": "3"})
    frames = midjourney.first_frames(plan, manifest)
    assert frames[plan["shots"][0]["id"]] == f"mj/{still_of_first_shot}/c.png"
    o_shot = next(s["id"] for s in plan["shots"] if s["id"].startswith("vO"))
    assert frames[o_shot] == "mj/oxhan/b.png"


def test_tag_upload_validation():
    m = midjourney.tag_upload([], key="uploads/u1/mj.png", tag="Hero")
    assert m[-1]["tag"] == "hero"
    for key, tag in (("uploads/u1/x.png", "villain"), ("../etc/passwd", "hero"), ("s3://x", "s2")):
        with pytest.raises(midjourney.ImportError_):
            midjourney.tag_upload([], key=key, tag=tag)


def test_mj_prompts_are_ready_to_paste(plan):
    preset = presets.with_mj_refs(OXHAN, sref_url="https://cdn/style.png", cref_urls={"H": "https://cdn/hero.png"})
    prompts = midjourney.prompts(plan, preset)
    assert [p["still"] for p in prompts] == [s["id"] for s in plan["stills"]]
    hero = next(p for p in prompts if p["character"] == "H")
    assert "--ar 9:16" in hero["prompt_v7"] and "--oref https://cdn/hero.png" in hero["prompt_v7"]
    assert "--sref https://cdn/style.png" in hero["prompt_v7"] and "--cref https://cdn/hero.png" in hero["prompt_v6"]
    assert "{" not in hero["prompt_v7"] and "fingerless" in hero["prompt_v7"]
    oxhan = next(p for p in prompts if p["character"] == "O")
    assert "<OXHAN_SHEET_URL>" in oxhan["prompt_v7"]
    s0 = prompts[0]
    assert s0["character"] is None and "--oref" not in s0["prompt_v7"]
    assert all("goggles" not in p["prompt_v7"].lower() for p in prompts)


# --------------------------------------------------------------------------- retries, backoff, price labels
def test_backoff_is_exponential_and_capped():
    assert [kling.backoff_s(i, 10) for i in range(6)] == [10, 20, 40, 80, 120, 120]


def test_wait_backs_off_on_transient_errors_then_succeeds():
    sleeps = []
    answers = iter([(503, {}), (429, {"code": 1300}), "boom", (200, {"code": 0, "data": {"task_status": "processing"}}),
                    (200, {"code": 0, "data": {"task_status": "succeed",
                                               "task_result": {"videos": [{"id": "v", "url": "u"}]}}})])

    def http(method, url, headers, body):
        a = next(answers)
        if a == "boom":
            raise ConnectionError("reset")
        return a

    c = kling.KlingClient(access_key="a", secret_key="s", http=http, sleep=sleeps.append, clock=lambda: 0.0)
    assert c.wait("i2v", "t", poll_s=10) == {"id": "v", "url": "u"}
    assert sleeps == [20, 40, 80, 10]


def test_wait_gives_up_after_too_many_transient_errors():
    c = kling.KlingClient(access_key="a", secret_key="s", http=lambda *a: (502, {}), sleep=lambda s: None,
                          clock=lambda: 0.0)
    with pytest.raises(kling.KlingError) as exc:
        c.wait("i2v", "t")
    assert exc.value.transient


def test_refused_submit_is_not_billed():
    c = kling.KlingClient(access_key="a", secret_key="s", http=lambda *a: (500, {}), cap_usd=5.0)
    with pytest.raises(kling.KlingError):
        c.image_to_video(image="x", prompt="p", seconds=5)
    assert c.spent_usd == 0 and c.ledger == []


def test_unofficial_prices_are_labelled_estimates(plan):
    by = {r["engine"]: r for r in engines.estimates(plan, env={})}
    assert by["kling"]["price_basis"] == "estimate" and by["kling"]["source"].startswith("ESTIMATE")
    assert by["replicate"]["price_basis"] == "list"
    assert engines.choose(list(by.values()), "kling")["price_basis"] == "estimate"


def test_shot_audio_lays_lines_on_lead_and_gaps(tmp_path):
    import shutil
    import subprocess

    from app.domains.adclone import service

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    files = []
    for i in range(2):
        path = tmp_path / f"l{i}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "0.6", "-i", "sine=frequency=300",
                        str(path)], check=True)
        files.append(str(path))
    out = service.shot_audio(files, str(tmp_path / "shot.wav"), lead_s=0.25, gap_s=0.3)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                           capture_output=True, text=True, check=True)
    assert float(probe.stdout) == pytest.approx(0.25 + 0.6 + 0.3 + 0.6, abs=0.1)
