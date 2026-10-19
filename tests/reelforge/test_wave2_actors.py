"""AI actors: synthetic presets, likeness block-list, generated faces with provenance, designed voices,
and product-holding shots priced -> approved in the approvals feed -> Kling (fake) -> refund on failure."""

from __future__ import annotations

import base64

import pytest

from app.domains.actors import likeness_guard, presets, render, service
from app.domains.actors import router as actors_router
from app.domains.approvals import service as approvals
from app.domains.brand_agent import gate, library
from app.domains.studio_render import adapter as render_adapter
from app.domains.studio_render import router as renders_router
from app.domains.studio_render import service as renders
from app.domains.studio_render.models import StudioRender
from tests.reelforge._wave2_support import (
    H,
    OTHER,
    ai_video_balance,
    client_for,
    data,
    grant_ai_video,
    make_env,
)

GOOD = {"name": "Lena Varo", "persona": "Barista", "look_prompt": "Original woman, 30s, curly red hair, green apron",
        "voice_design_prompt": "Bright, friendly female voice, quick pace", "attest_synthetic": True}


class FakeKling:
    def __init__(self, fail=False):
        self.calls, self.fail, self.spent_usd = [], fail, 0.0

    def image_to_video(self, *, image, prompt, seconds, aspect_ratio="9:16"):
        self.calls.append({"image": image, "prompt": prompt, "seconds": seconds, "aspect": aspect_ratio})
        if self.fail:
            raise RuntimeError("engine down")
        self.spent_usd = 0.42
        return "task-1"

    def wait(self, kind, task_id):
        return {"id": "vid-1", "url": "https://cdn.kling.test/v.mp4"}


class FakeVoice:
    def __init__(self):
        self.designed, self.saved = [], []

    def design(self, description):
        self.designed.append(description)
        return [{"generated_voice_id": "gen123456", "audio_base_64": ""}]

    def save(self, *, name, description, generated_voice_id):
        self.saved.append(generated_voice_id)
        return "voice_abc12345"


@pytest.fixture()
def env(monkeypatch):
    env = make_env(monkeypatch)
    monkeypatch.setattr(render_adapter, "PAID_CHECK", lambda: True)
    queued = []
    monkeypatch.setattr(render_adapter, "ENQUEUE", queued.append)
    env.queued = queued
    return env


def _actor_with_face(env):
    with env.db.scope() as s:
        actor = service.create(s, env.uid, **GOOD)
        action = service.propose_face(s, env.uid, actor["id"])
        out = gate.decide(s, env.deps, env.uid, action["id"], gate.APPROVE)
        assert out["status"] == "executed"
        item = library.list_items(s, env.uid)[0]
        return service.use_face(s, env.uid, actor["id"], item["id"])


# --------------------------------------------------------------------------- guard + presets
def test_presets_are_original_and_pass_the_guard():
    items = presets.all_presets()
    assert len(items) >= 8
    for p in items:
        assert p["provenance"]["synthetic"] is True and p["consent"]["type"] == "synthetic_no_real_person"
        assert likeness_guard.problems({"name": p["name"], "look prompt": p["look_prompt"],
                                        "voice prompt": p["voice_design_prompt"],
                                        "shot template": p["product_shot_template"]}) == []
        assert "{product}" in p["product_shot_template"]


@pytest.mark.parametrize("field,value", [
    ("name", "Taylor Swift"),
    ("look_prompt", "a woman who looks like Zendaya"),
    ("look_prompt", "lookalike of a famous actress"),
    ("look_prompt", "face swap with my friend"),
    ("voice_design_prompt", "sounds like Morgan Freeman"),
    ("voice_design_prompt", "clone the voice from my sample"),
    ("name", "cristiano  RONALDO"),
    ("look_prompt", "Kylian Mbappé in a hoodie"),
])
def test_real_people_and_impersonation_are_refused(env, field, value):
    with env.db.scope() as s:
        with pytest.raises(service.ActorError) as err:
            service.create(s, env.uid, **{**GOOD, field: value})
    assert err.value.status_code == 422


def test_attestation_is_required_and_stored_as_consent(env):
    with env.db.scope() as s:
        with pytest.raises(service.ActorError):
            service.create(s, env.uid, **{**GOOD, "attest_synthetic": False})
        actor = service.create(s, env.uid, **GOOD)
    assert actor["consent"]["type"] == "synthetic_no_real_person" and actor["consent"]["attested_by"] == env.uid
    assert actor["provenance"]["synthetic"] is True and "{product}" in actor["product_shot_template"]


def test_use_preset_is_idempotent(env):
    with env.db.scope() as s:
        a = service.use_preset(s, env.uid, "mira-soltane")
        b = service.use_preset(s, env.uid, "mira-soltane")
    assert a["id"] == b["id"] and a["provenance"]["preset"] == "mira-soltane"


# --------------------------------------------------------------------------- face + voice
def test_face_comes_only_from_a_generation_for_this_actor(env):
    actor = _actor_with_face(env)
    assert actor["status"] == "ready" and actor["face_image_url"].startswith("https://cdn.test/")
    prov = actor["provenance"]
    assert prov["face"] == "generated" and prov["face_prompt"].startswith(GOOD["look_prompt"])
    with env.db.scope() as s:
        other = service.create(s, env.uid, **{**GOOD, "name": "Ivo Brannick"})
        unrelated = library.add_item(s, user_id=env.uid, space_id=library.list_items(s, env.uid)[0]["space_id"],
                                     action_id=None, kind="image", ref="x", url="https://cdn.test/upload.png")
        with pytest.raises(service.ActorError):
            service.use_face(s, env.uid, other["id"], unrelated["id"])  # not generated for this actor
        with pytest.raises(service.ActorError):
            service.use_face(s, env.uid, other["id"], library.list_items(s, env.uid)[-1]["id"])  # someone else's face


def test_voice_is_designed_from_text_and_locked(env):
    voice = FakeVoice()
    with env.db.scope() as s:
        actor = service.create(s, env.uid, **GOOD)
        out = service.design_voice(s, env.uid, actor["id"], voice)
        assert out["previews"][0]["generated_voice_id"] == "gen123456"
        locked = service.lock_voice(s, env.uid, actor["id"], voice, "gen123456")
        assert locked["voice_id"] == "voice_abc12345"
        assert locked["provenance"]["voice_designed_from"].startswith("text prompt")
        with pytest.raises(service.ActorError):
            service.design_voice(s, env.uid, actor["id"], voice, "imitate my boss")
    assert voice.designed == [GOOD["voice_design_prompt"]]


# --------------------------------------------------------------------------- product shot
def test_shot_plan_is_priced_and_needs_a_face(env):
    with env.db.scope() as s:
        bare = service.create(s, env.uid, **{**GOOD, "name": "Pell Ostrava"})
        with pytest.raises(service.ActorError) as err:
            render.plan_shot(s, env.uid, bare["id"], product="Brewly beans", env={})
        assert err.value.status_code == 409
    actor = _actor_with_face(env)
    with env.db.scope() as s:
        planned = render.plan_shot(s, env.uid, actor["id"], product="Brewly beans", seconds=5, env={})
        with pytest.raises(service.ActorError):
            render.plan_shot(s, env.uid, actor["id"], product="Brewly", first_frame_url="https://evil.test/x.png",
                             env={})
    assert planned["status"] == "planned" and planned["plan"]["engine"] == "kling"
    assert "Brewly beans" in planned["plan"]["prompt"] and planned["quote_usd"] == pytest.approx(0.42)
    assert planned["credits"] == 126  # ceil(3 x 42 cents)


def _approved_render(env, credits=500):
    grant_ai_video(env.db, env.uid, credits)
    actor = _actor_with_face(env)
    with env.db.scope() as s:
        planned = render.plan_shot(s, env.uid, actor["id"], product="Brewly beans", env={})
        submitted = renders.submit(s, env.uid, planned["id"])
    assert submitted["status"] == "pending_approval"
    item = approvals.get_item(env.uid, submitted["approval_item_id"])
    assert item["source"] == "studio_render" and item["payload"]["credits"] == 126
    return submitted, item


def test_spending_waits_for_approval_then_runs_once(env):
    submitted, item = _approved_render(env)
    assert ai_video_balance(env.db, env.uid) == 500 and env.queued == []  # nothing spent before approval
    out = approvals.decide(env.uid, item["id"], "approve", via="web")
    assert out["item"]["status"] == "executed" and env.queued == [submitted["id"]]
    assert ai_video_balance(env.db, env.uid) == 374
    again = approvals.decide(env.uid, item["id"], "approve")
    assert again["idempotent"] and ai_video_balance(env.db, env.uid) == 374
    kling = FakeKling()
    done = renders.run(submitted["id"], runners={"actor_shot": lambda plan: render.run_product_shot(
        plan, client=kling, fetch=lambda url: b"jpegbytes")})
    assert done["status"] == "done" and done["result"]["video_url"] == "https://cdn.kling.test/v.mp4"
    assert base64.b64decode(kling.calls[0]["image"]) == b"jpegbytes"
    assert "Brewly beans" in kling.calls[0]["prompt"]


def test_engine_failure_refunds_once(env):
    submitted, item = _approved_render(env)
    approvals.decide(env.uid, item["id"], "approve")
    failing = {"actor_shot": lambda plan: render.run_product_shot(plan, client=FakeKling(fail=True),
                                                                  fetch=lambda url: b"x")}
    out = renders.run(submitted["id"], runners=failing)
    assert out["status"] == "failed" and ai_video_balance(env.db, env.uid) == 500
    renders.run(submitted["id"], runners=failing)  # a second run of a failed render does nothing
    assert ai_video_balance(env.db, env.uid) == 500


def test_paid_switch_off_or_no_credits_blocks_approval(env, monkeypatch):
    submitted, item = _approved_render(env, credits=10)
    with pytest.raises(approvals.ApprovalError) as err:
        approvals.decide(env.uid, item["id"], "approve")
    assert err.value.status_code == 402 and ai_video_balance(env.db, env.uid) == 10
    monkeypatch.setattr(render_adapter, "PAID_CHECK", lambda: False)
    with pytest.raises(approvals.ApprovalError) as err:
        approvals.decide(env.uid, item["id"], "approve")
    assert err.value.status_code == 403 and env.queued == []


def test_reject_never_spends(env):
    submitted, item = _approved_render(env)
    approvals.decide(env.uid, item["id"], "reject")
    with env.db.scope() as s:
        assert s.get(StudioRender, submitted["id"]).status == "rejected"
    assert ai_video_balance(env.db, env.uid) == 500 and env.queued == []


def test_http_actors_and_renders(env, monkeypatch):
    monkeypatch.setattr(actors_router, "voice_client", lambda: FakeVoice())
    client = client_for(actors_router, renders_router, monkeypatch=monkeypatch, db=env.db)
    listing = data(client.get("/api/v1/actors", headers=H))
    assert len(listing["presets"]) >= 8 and listing["mine"] == []
    bad = client.post("/api/v1/actors", headers=H, json={**GOOD, "name": "Elon Musk"})
    assert bad.status_code == 422
    actor = data(client.post("/api/v1/actors/presets/dario-quell/use", headers=H))["actor"]
    face = data(client.post(f"/api/v1/actors/{actor['id']}/face", headers=H, json={}))["action"]
    assert face["status"] == "pending" and face["kind"] == "generate_image"
    voice = data(client.post(f"/api/v1/actors/{actor['id']}/voice/design", headers=H, json={}))
    assert voice["previews"]
    assert client.get(f"/api/v1/studio-renders/{'x' * 32}", headers=H).status_code == 404
    assert client.post(f"/api/v1/actors/{actor['id']}/face", headers=OTHER, json={}).status_code == 404


def test_duplicate_tasks_never_run_a_render_twice(env):
    submitted, item = _approved_render(env)
    approvals.decide(env.uid, item["id"], "approve")
    calls = []
    runner = {"actor_shot": lambda plan: calls.append(1) or {"video_url": "https://k/v.mp4"}}
    assert renders.run(submitted["id"], runners=runner)["status"] == "done"
    assert renders.run(submitted["id"], runners=runner)["status"] == "done"
    assert calls == [1]


def test_reconcile_requeues_lost_tasks_and_refunds_stuck_renders(env):
    from datetime import datetime, timedelta, timezone

    submitted, item = _approved_render(env)
    approvals.decide(env.uid, item["id"], "approve")
    later = datetime.now(timezone.utc) + timedelta(minutes=20)
    requeued = []
    out = renders.reconcile(now=later, enqueue=requeued.append)
    assert out == {"requeued": 1, "failed": 0} and requeued == [submitted["id"]]
    with env.db.scope() as s:
        s.get(StudioRender, submitted["id"]).status = "running"
    out = renders.reconcile(now=later + timedelta(hours=4), enqueue=requeued.append)
    assert out["failed"] == 1 and ai_video_balance(env.db, env.uid) == 500
    with env.db.scope() as s:
        assert s.get(StudioRender, submitted["id"]).status == "failed"
