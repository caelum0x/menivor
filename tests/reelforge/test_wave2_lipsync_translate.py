"""Lip-sync translation: designed voices only, own videos only, priced plan -> approval -> full fake pipeline."""

from __future__ import annotations

import pytest

from app.domains.actors import service as actors
from app.domains.approvals import service as approvals
from app.domains.brand_agent import library, spaces
from app.domains.lipsync_translate import engines, pipeline
from app.domains.lipsync_translate import router as translate_router
from app.domains.studio_render import adapter as render_adapter
from app.domains.studio_render import service as renders
from tests.reelforge._wave2_support import H, client_for, data, grant_ai_video, make_env

VIDEO = "https://cdn.test/own.mp4"
ACTOR = {"name": "Lena Varo", "look_prompt": "Original woman, 30s", "voice_design_prompt": "Bright friendly voice",
         "attest_synthetic": True}


class FakeVoice:
    def save(self, *, name, description, generated_voice_id):
        return "voice_designed_1"


@pytest.fixture()
def env(monkeypatch):
    env = make_env(monkeypatch)
    monkeypatch.setattr(render_adapter, "PAID_CHECK", lambda: True)
    monkeypatch.setattr(render_adapter, "ENQUEUE", lambda render_id: None)
    with env.db.scope() as s:
        space = spaces.ensure_default(s, env.uid)
        library.add_item(s, user_id=env.uid, space_id=space.id, action_id=None, kind="video", ref="v1", url=VIDEO,
                         title="Our UGC ad")
        actor = actors.create(s, env.uid, **ACTOR)
        env.bare_actor = actors.create(s, env.uid, **{**ACTOR, "name": "Pell Ostrava"})["id"]
        env.actor = actors.lock_voice(s, env.uid, actor["id"], FakeVoice(), "gen1234")["id"]
    return env


def _plan(env, **kw):
    args = {"video_url": VIDEO, "actor_id": env.actor, "targets": ["de", "tr", "xx", "en"], "seconds": 10,
            "transcript": "Stop paying more for coffee. Brewly costs less. Try it today.", "env": {}}
    args.update(kw)
    with env.db.scope() as s:
        return pipeline.plan(s, env.uid, **args)


def test_plan_prices_each_language_and_spends_nothing(env):
    out = _plan(env)
    assert out["status"] == "planned"
    plan = out["plan"]
    assert [t["code"] for t in plan["targets"]] == ["de", "tr"]  # unknown and source language dropped
    assert plan["voice_id"] == "voice_designed_1" and plan["engine"] == "kling"
    per_lang = engines.tts_usd(int(len(args_transcript := plan["transcript"]) * 1.15), {}) + engines.lipsync_usd("kling", 10)
    assert args_transcript and plan["usd"] == pytest.approx(round(per_lang, 4) * 2, abs=1e-4)
    assert out["credits"] > 0 and "lip-sync (kling)" in plan["steps"]


@pytest.mark.parametrize("kwargs,status", [
    ({"video_url": "https://elsewhere.test/someone.mp4"}, 422),   # not the user's own video
    ({"actor_id": "BARE"}, 409),                                   # actor has no designed voice
    ({"targets": ["en"]}, 422),                                    # nothing to translate into
    ({"options": {"voice_sample": "https://x/me.mp3"}}, 422),      # never clone from audio
    ({"engine": "elevenlabs-clone"}, 422),
])
def test_plan_refusals(env, kwargs, status):
    if kwargs.get("actor_id") == "BARE":
        kwargs = {**kwargs, "actor_id": env.bare_actor}
    with pytest.raises(pipeline.TranslateError) as err:
        _plan(env, **kwargs)
    assert err.value.status_code == status


def test_translation_shape_is_checked():
    assert pipeline.parse_lines('Sure: ["Eins.", "Zwei."]', 2) == ["Eins.", "Zwei."]
    with pytest.raises(pipeline.TranslateError):
        pipeline.parse_lines('["only one"]', 2)
    with pytest.raises(pipeline.TranslateError):
        pipeline.parse_lines("no json here", 1)
    assert "German" in pipeline.translate_prompt(["a"], "German")
    cues = pipeline.cues_for(["aa", "aaaa"], 6.0)
    assert cues[0]["end"] == pytest.approx(2.0) and cues[1]["end"] == pytest.approx(6.0)


def test_relay_is_required_for_translation(monkeypatch):
    import app.domains.adclone.relay_writer as rw

    monkeypatch.setattr(rw, "relay_llm", lambda *a, **k: None)
    with pytest.raises(pipeline.TranslateError) as err:
        pipeline.relay_translate(["hello"], "German")
    assert err.value.status_code == 409


class Recorder:
    def __init__(self):
        self.calls = []

    def deps(self, tmp_path):
        def fetch(url, dest):
            self.calls.append(("fetch", url))
            with open(dest, "wb") as f:
                f.write(b"video")
            return dest

        def tts(voice_id, text, out):
            self.calls.append(("tts", voice_id, text))
            with open(out, "wb") as f:
                f.write(b"mp3:" + text.encode())
            return out

        def lipsync(*, video_url, audio, seconds):
            self.calls.append(("lipsync", video_url, audio[:4], seconds))
            return f"https://cdn.kling.test/{len(self.calls)}.mp4"

        def burn(video, cues, out):
            self.calls.append(("burn", [c["text"] for c in cues]))
            with open(out, "wb") as f:
                f.write(b"final")
            return out

        return pipeline.PipelineDeps(
            fetch=fetch, transcribe=lambda path, lang: [{"start": 0, "end": 2, "text": "unused"}],
            translate=lambda lines, label: [f"[{label}] {line}" for line in lines], tts=tts, lipsync=lipsync,
            burn=burn, upload=lambda path, key, ct: self.calls.append(("upload", key)),
            media_url=lambda key: f"https://media.menivor.test/{key}")


def test_full_pipeline_after_approval(env, tmp_path):
    grant_ai_video(env.db, env.uid, 1000)
    planned = _plan(env)
    with env.db.scope() as s:
        submitted = renders.submit(s, env.uid, planned["id"])
    approvals.decide(env.uid, submitted["approval_item_id"], "approve")
    rec = Recorder()
    out = renders.run(submitted["id"], runners={"lipsync_translation": lambda plan: pipeline.run_plan(
        plan, deps=rec.deps(tmp_path))})
    assert out["status"] == "done"
    outputs = out["result"]["outputs"]
    assert [o["code"] for o in outputs] == ["de", "tr"]
    assert outputs[0]["video_url"].startswith("https://media.menivor.test/studio/lipsync/")
    tts_calls = [c for c in rec.calls if c[0] == "tts"]
    assert {c[1] for c in tts_calls} == {"voice_designed_1"}  # always the designed voice
    assert tts_calls[0][2].startswith("[German] Stop paying more for coffee.")
    assert [c[1] for c in rec.calls if c[0] == "lipsync"] == [VIDEO, VIDEO]
    burned = [c[1] for c in rec.calls if c[0] == "burn"]
    assert burned[1][0].startswith("[Turkish]")


def test_pipeline_refuses_reference_audio_in_a_plan():
    with pytest.raises(pipeline.TranslateError):
        pipeline.run_plan({"reference_audio": "x"}, deps=None)


def test_infinitetalk_dubber_respects_the_cap_and_polls():
    calls = []

    def http(method, url, headers, body):
        calls.append((method, url))
        if method == "POST":
            return 200, {"id": "job1"}
        return 200, {"status": "COMPLETED", "output": {"video_url": "https://rp.test/out.mp4"}, "executionTime": 60000}

    dub = engines.InfiniteTalkDubber(api_key="k", endpoint_id="ep", cap_usd=5.0, http=http, sleep=lambda s: None)
    assert dub.dub(video_url=VIDEO, audio=b"a", seconds=10) == "https://rp.test/out.mp4"
    assert dub.spent_usd > 0 and calls[0][1].endswith("/v2/ep/run")
    capped = engines.InfiniteTalkDubber(api_key="k", endpoint_id="ep", cap_usd=0.01, http=http)
    with pytest.raises(engines.LipsyncError):
        capped.dub(video_url=VIDEO, audio=b"a", seconds=60)


def test_kling_lip_sync_by_url():
    from app.domains.adclone.kling import KlingClient

    sent = []

    def http(method, url, headers, body):
        sent.append(body)
        if method == "POST":
            return 200, {"code": 0, "data": {"task_id": "t1"}}
        return 200, {"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [{"url": "https://k/v.mp4"}]}}}

    client = KlingClient(api_key="k", http=http, sleep=lambda s: None, cap_usd=1.0)
    assert engines.kling_dub(client, video_url=VIDEO, audio=b"a", seconds=7) == "https://k/v.mp4"
    assert sent[0]["input"]["video_url"] == VIDEO and "video_id" not in sent[0]["input"]


def test_http_options_and_plan(env, monkeypatch):
    client = client_for(translate_router, monkeypatch=monkeypatch, db=env.db)
    opts = data(client.get("/api/v1/translate/options", headers=H))
    assert len(opts["languages"]) >= 30 and opts["videos"][0]["url"] == VIDEO
    assert {v["name"]: v["ready"] for v in opts["voices"]} == {"Lena Varo": True, "Pell Ostrava": False}
    body = {"video_url": VIDEO, "actor_id": env.actor, "targets": ["fr"], "seconds": 8}
    assert data(client.post("/api/v1/translate/plan", headers=H, json=body))["render"]["status"] == "planned"
    sneaky = client.post("/api/v1/translate/plan", headers=H, json={**body, "voice_sample": "https://x/a.mp3"})
    assert sneaky.status_code == 422


def test_kling_lip_sync_needs_a_source():
    from app.domains.adclone.kling import KlingClient, KlingError

    client = KlingClient(api_key="k", http=lambda *a: (200, {}), cap_usd=1.0)
    with pytest.raises(KlingError):
        client.lip_sync(video_id="", audio_b64="x", seconds=5)
