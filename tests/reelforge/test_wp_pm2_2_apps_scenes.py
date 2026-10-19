"""Wave P PM2.2: MH8 apps shelf and MH6 talking scenes.

1. Eleven apps (ten tools plus the H22 hook-score tile), each one input screen
   and a price first (MG3); an app is shown only with a real uploaded preview
   loop and a runner that works on this deployment (no placeholder tiles).
2. Local tools run for real (ffmpeg, onset detection, rembg when installed);
   image-edit apps are priced at 3x the recorded image price and refunded once
   on failure.
3. Talking scenes are complete behind PRESENTER_LIVE (off): mouth-audio offset
   under 80 ms, duration within 0.25 s, the disclosure line burned on, and every
   scene route answers 404 with the flag off.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.apps_shelf import catalog, router as apps_router, runners, service, tasks
from app.domains.film.story8_render import ffmpeg_bin
from app.domains.presets_hub.catalog import vendor_hits
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services.avatar import scenes
from app.services.billing import premium_credits as pc
from app.utils import utils

KEY = "apps-key"
H = {"x-api-key": KEY}
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _png(colour=(30, 140, 200), size=(320, 568), mode="RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, colour).save(out, format="PNG")
    return out.getvalue()


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def test_eleven_apps_load_including_the_hook_score_tile():
    ids = [a.id for a in catalog.all_apps()]
    assert len(ids) == 11 and "hook-score" in ids
    for app in catalog.all_apps():
        assert not catalog.copy_hits(app), app.id
        assert app.preview == f"presets/apps/{app.id}.mp4"


def test_apps_are_hidden_without_a_live_preview_and_a_working_runner(monkeypatch):
    app = catalog.get("transition")
    env = {"APPS_PREVIEWS_LIVE": "1"}
    monkeypatch.setattr(catalog, "previews", lambda: {})
    assert not catalog.visible(app, env)
    monkeypatch.setattr(catalog, "previews", lambda: {"transition": "presets/apps/transition.mp4",
                                                     "expand": "presets/apps/expand.mp4"})
    assert catalog.visible(app, env)
    assert not catalog.visible(app, {})  # uploads not switched live yet
    assert not catalog.visible(catalog.get("expand"), env)  # no image-model key on this server
    assert catalog.visible(catalog.get("expand"), {**env, "FAL_KEY": "k"})


def test_image_apps_are_priced_at_three_times_the_recorded_image_price():
    one = service.price_hint(catalog.get("expand"))
    nine = service.price_hint(catalog.get("nine-angles"))
    assert one["credits"] == pc.ai_video_credits_for_usd(0.04) and one["price_source"].startswith("https://fal.ai/")
    assert nine["credits"] == pc.ai_video_credits_for_usd(0.36) and nine["provider_usd"] == 0.36
    public = service.public_price(catalog.get("expand"))
    assert "price_source" not in public and "provider_usd" not in public
    assert service.price_hint(catalog.get("meme")) == {"credit_kind": "standard", "credits": None,
                                                       "priced_by": "create"}
    assert service.price_hint(catalog.get("hook-score"))["credits"] == 0


def test_preview_plan_lists_render_jobs_only_free_first():
    from importlib import util

    spec = util.spec_from_file_location("apps_previews", Path(catalog.ASSETS).parents[2] / "tools" / "ops" /
                                        "apps_previews.py")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = module.plan()
    costs = [j["cost_usd"] for j in plan["jobs"]]
    assert len(plan["jobs"]) == 11 and costs == sorted(costs, key=lambda c: c > 0)
    assert plan["total_cost_usd"] == pytest.approx(0.48)
    assert all(j["output_key"].startswith("presets/apps/") for j in plan["jobs"])


# --------------------------------------------------------------------------- #
# Routes and money
# --------------------------------------------------------------------------- #
@pytest.fixture()
def maker(monkeypatch):
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
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    import app.controllers.v1.jobs as jobs_mod

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(jobs_mod, "get_session", _session)
    monkeypatch.setattr(apps_router, "get_session", _session)
    monkeypatch.setattr(apps_router, "enqueue", lambda job_id: "celery-1")
    monkeypatch.setattr(apps_router, "enqueue_scene", lambda job_id: "celery-2")
    monkeypatch.setattr(service, "_require_owned", lambda s, u, k: None)
    monkeypatch.setattr(catalog, "previews", lambda: {a.id: a.preview for a in catalog.all_apps()})
    monkeypatch.setenv("APPS_PREVIEWS_LIVE", "1")
    monkeypatch.setenv("FAL_KEY", "test-key")
    with factory() as s:
        s.add(User(email="apps@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    return factory


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(apps_router.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def _uid(maker):
    with maker() as s:
        return s.query(User).one().id


def test_shelf_lists_live_apps_with_prices_and_no_vendor_names(maker, monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_MEDIA_BASE_URL", "https://media.example")
    res = _client().get("/api/v1/apps")
    assert res.status_code == 200 and "s-maxage" in res.headers["cache-control"]
    apps = res.json()["data"]["apps"]
    ids = {a["id"] for a in apps}
    assert "transition" in ids and "expand" in ids
    assert all(a["preview_url"].startswith("https://media.example/presets/apps/") for a in apps)
    assert not vendor_hits(json.dumps(apps))


def test_shelf_preview_urls_default_to_the_public_media_origin(maker, monkeypatch):
    # The box had no R2_PUBLIC_MEDIA_BASE_URL: tiles must still get media.menivor.com, never "".
    monkeypatch.delenv("R2_PUBLIC_MEDIA_BASE_URL", raising=False)
    apps = _client().get("/api/v1/apps").json()["data"]["apps"]
    assert apps and all(a["preview_url"].startswith("https://media.menivor.com/") for a in apps)


def test_shelf_never_lists_a_tile_without_a_preview_url(maker, monkeypatch):
    from app.domains.apps_shelf import service

    monkeypatch.setattr(service, "_public_preview", lambda key: "")
    assert _client().get("/api/v1/apps").json()["data"]["apps"] == []


def test_create_flow_apps_return_the_normal_create_call(maker):
    client = _client()
    plan = client.post("/api/v1/apps/meme/plan", json={"text": "cold brew"}, headers=H).json()["data"]
    assert plan["route"] == "jobs" and plan["body"]["params"]["style"] == "meme_hook"
    ad = client.post("/api/v1/apps/click-to-ad/plan", json={"text": "https://shop.example/p/1"}, headers=H).json()
    assert ad["data"]["body"]["params"]["source_url"] == "https://shop.example/p/1"
    assert client.post("/api/v1/apps/meme/runs", json={"inputs": {"text": "x"}, "quoted_credits": 0},
                       headers=H).status_code == 400


def test_local_app_debits_its_credit_and_refunds_on_failure(maker):
    client = _client()
    inputs = {"image_key": "uploads/u/a.png", "image_key_2": "uploads/u/b.png"}
    assert client.post("/api/v1/apps/transition/quote", json=inputs, headers=H).json()["data"]["credits"] == 1
    assert client.post("/api/v1/apps/transition/runs", json={"inputs": inputs, "quoted_credits": 1},
                       headers=H).status_code == 402
    with maker() as s:
        CreditRepository(s).grant(_uid(maker), 3, "test")
        s.commit()
    assert client.post("/api/v1/apps/transition/runs", json={"inputs": inputs, "quoted_credits": 0},
                       headers=H).status_code == 409
    job_id = client.post("/api/v1/apps/transition/runs", json={"inputs": inputs, "quoted_credits": 1},
                         headers=H).json()["data"]["job_id"]
    with maker() as s:
        assert CreditRepository(s).balance(_uid(maker)) == 2

    def broken(key):
        raise runners.AppRunError("the photo could not be read")

    assert tasks.run(job_id, tasks.Deps(fetch=broken))["state"] == -1
    assert tasks.run(job_id, tasks.Deps(fetch=broken))["state"] == -1
    with maker() as s:
        assert CreditRepository(s).balance(_uid(maker)) == 3
    view = client.get(f"/api/v1/apps/runs/{job_id}", headers=H).json()["data"]
    assert view["refunded"] is True and "could not be read" in view["error"]


def test_free_tools_have_a_daily_cap(maker, monkeypatch):
    monkeypatch.setattr(runners, "AppRunError", runners.AppRunError)
    client = _client()
    body = {"inputs": {"video_key": "uploads/u/clip.mp4"}, "quoted_credits": 0}
    cap = catalog.get("hook-score").price["daily_cap"]
    for _ in range(cap):
        assert client.post("/api/v1/apps/hook-score/runs", json=body, headers=H).status_code == 200
    assert client.post("/api/v1/apps/hook-score/runs", json=body, headers=H).status_code == 429


def test_nine_angles_makes_nine_images_and_refunds_ai_credits_on_failure(maker):
    client = _client()
    credits = service.price_hint(catalog.get("nine-angles"))["credits"]
    with maker() as s:
        pc.grant(s, _uid(maker), pc.KIND_AI_VIDEO, credits * 2, "test")
        s.commit()
    body = {"inputs": {"image_key": "uploads/u/p.png"}, "quoted_credits": credits}
    ok_id = client.post("/api/v1/apps/nine-angles/runs", json=body, headers=H).json()["data"]["job_id"]
    uploaded, prompts = [], []

    def edit(prompt, url):
        prompts.append(prompt)
        return _png()

    deps = tasks.Deps(edit_image=edit, signed_url=lambda k: f"https://signed/{k}",
                      upload=lambda path, key, ct: uploaded.append(key))
    assert tasks.run(ok_id, deps)["state"] == 1
    assert len(uploaded) == 9 and len(set(prompts)) == 9 and "from the back" in " ".join(prompts)
    bad_id = client.post("/api/v1/apps/nine-angles/runs", json=body, headers=H).json()["data"]["job_id"]

    def down(prompt, url):
        raise runners.AppRunError("the image model refused this photo (422)")

    assert tasks.run(bad_id, tasks.Deps(edit_image=down, signed_url=lambda k: "https://x"))["state"] == -1
    with maker() as s:
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == credits


def test_bad_inputs_are_refused_before_any_charge(maker):
    client = _client()
    assert client.post("/api/v1/apps/relight/quote", json={"image_key": "uploads/u/a.png", "choice": "disco"},
                       headers=H).status_code == 400
    assert client.post("/api/v1/apps/beat-cut/quote", json={"video_key": "uploads/u/c.mp4", "music_id": "nope"},
                       headers=H).status_code == 400
    assert client.post("/api/v1/apps/expand/quote", json={}, headers=H).status_code == 400


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def test_edit_image_calls_the_edit_model_and_downloads_the_result():
    class Resp:
        def __init__(self, status, body=None, content=b""):
            self.status_code, self._body, self.content = status, body, content

        def json(self):
            return self._body

    class Session:
        def __init__(self):
            self.posts = []

        def post(self, url, headers, json, timeout):
            self.posts.append((url, json))
            return Resp(200, {"images": [{"url": "https://fal.media/x.png"}]})

        def get(self, url, timeout):
            return Resp(200, content=b"png-bytes")

    session = Session()
    assert runners.edit_image("relight it", "https://in/p.png", session=session, api_key="k") == b"png-bytes"
    assert session.posts == [(runners.EDIT_ENDPOINT, {"prompt": "relight it", "image_url": "https://in/p.png"})]


def test_remove_background_needs_real_transparency():
    assert runners.remove_background(b"x", remover=lambda data: _png(mode="RGBA", colour=(0, 0, 0, 0)))
    with pytest.raises(runners.AppRunError):
        runners.remove_background(b"x", remover=lambda data: _png())


def _click_track(path: str, beats: list[float], seconds: float = 8.0) -> None:
    rate = runners.SAMPLE_RATE
    audio = np.zeros(int(seconds * rate), dtype="float32")
    for t in beats:
        start = int(t * rate)
        audio[start:start + 800] = 0.8 * np.sin(np.linspace(0, 80 * np.pi, 800))
    pcm = (audio * 32767).astype("<i2").tobytes()
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "-",
                    path], input=pcm, check=True)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_beats_are_found_where_the_track_hits(tmp_path):
    truth = [0.5 * n + 0.25 for n in range(15)]
    path = str(tmp_path / "click.wav")
    _click_track(path, truth)
    found = runners.detect_beats(runners.decode_audio(path))
    assert len(found) >= 12
    assert all(min(abs(f - t) for t in truth) < 0.05 for f in found)
    segments = runners.plan_beat_cut(6.0, found)
    cuts = np.cumsum([s.duration for s in segments])[:-1]
    assert all(min(abs(c - (b - 2 / 30)) for b in found) < 0.02 for c in cuts)


@pytest.mark.integration
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_transition_and_beat_cut_render_for_real(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(_png((200, 40, 40)))
    b.write_bytes(_png((40, 40, 200)))
    out = str(tmp_path / "t.mp4")
    runners.run(runners.transition_command(str(a), str(b), out))
    assert abs(runners.probe_seconds(out) - 5.0) < 0.2
    clip = str(tmp_path / "clip.mp4")
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=30:d=8",
                    clip], check=True)
    music = str(tmp_path / "m.wav")
    _click_track(music, [0.5 * n + 0.25 for n in range(15)])
    segments = runners.plan_beat_cut(runners.probe_seconds(clip), runners.detect_beats(runners.decode_audio(music)))
    cut = str(tmp_path / "cut.mp4")
    runners.run(runners.beat_cut_command(clip, music, segments, cut))
    assert abs(runners.probe_seconds(cut) - sum(s.duration for s in segments)) < 0.2


@pytest.mark.integration
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_hook_score_measures_motion_and_sound(tmp_path):
    busy = str(tmp_path / "busy.mp4")
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-shortest", busy], check=True)
    still = str(tmp_path / "still.mp4")
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:size=360x640:d=3",
                    still], check=True)
    loud, quiet = runners.hook_signals(busy), runners.hook_signals(still)
    assert loud["motion"] > quiet["motion"] and loud["speech"] > quiet["speech"]
    assert loud["not_measured"] == ["text", "face_or_subject"]
    result = runners.score_hook(quiet, "Nobody tells you this")
    assert 0 <= result["score"] <= 1 and result["passes_gate"] is False


# --------------------------------------------------------------------------- #
# Talking scenes (behind PRESENTER_LIVE)
# --------------------------------------------------------------------------- #
def test_every_scene_route_is_404_while_presenters_are_off(maker, monkeypatch):
    monkeypatch.delenv("PRESENTER_LIVE", raising=False)
    client = _client()
    assert client.get("/api/v1/scenes").status_code == 404
    assert client.post("/api/v1/scenes/podcast/quote").status_code == 404
    assert client.post("/api/v1/scenes/podcast/runs", json={"character_id": "c", "script": "hi", "quoted_credits": 1},
                       headers=H).status_code == 404
    assert client.get("/api/v1/scenes/runs/x", headers=H).status_code == 404


def test_five_scenes_load_with_the_disclosure_line():
    ids = {s.id for s in scenes.scenes()}
    assert ids == {"selfie", "podcast", "car", "desk", "product-in-hand"}
    assert all(s.disclosure == "This video was created with AI." for s in scenes.scenes())
    ass = scenes.disclosure_ass("This video was created with AI.", 12.0)
    assert "Dialogue: 0,0:00:00.00,0:00:12.00,Disclosure" in ass


def test_offset_measurement_finds_a_known_shift():
    rng = np.random.default_rng(3)
    audio = np.abs(rng.normal(size=400))
    fps = 25
    for shift_frames in (0, 2, -3):
        mouth = np.roll(audio, shift_frames)
        assert scenes.best_lag_ms(audio, mouth, fps=fps) == pytest.approx(shift_frames * 40.0)
    assert scenes.duration_ok(10.2, 10.0) and not scenes.duration_ok(10.3, 10.0)


def _scene_job(maker, **params) -> str:
    uid = _uid(maker)
    with maker() as s:
        pc.grant(s, uid, pc.KIND_AI_VIDEO, 200, "test")
        speak = Job(user_id=uid, kind="speak_lipsync", state=1, params={}, result_key="jobs/sp/out.mp4")
        s.add(speak)
        s.flush()
        pc.debit(s, uid, pc.KIND_AI_VIDEO, 150, "premium_debit:scene", None)
        job = Job(user_id=uid, kind=scenes.JOB_KIND, state=4, params={
            "scene_id": "podcast", "ai_video_credits": 150, "disclosure": "This video was created with AI.",
            "_speak_job": speak.id, "_audio_s": 3.0, "_speak_started": 0, **params})
        s.add(job)
        s.commit()
        return job.id


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
@pytest.mark.parametrize(("offset", "expect_state"), [(40.0, 1), (120.0, -1)])
def test_scene_ships_only_when_lips_and_voice_line_up(maker, tmp_path, offset, expect_state):
    clip = tmp_path / "talk.mp4"
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=25:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-shortest", str(clip)], check=True)
    job_id = _scene_job(maker)
    burned, uploaded = [], []
    deps = scenes.Deps(fetch=lambda key: clip.read_bytes(), measure_offset_ms=lambda path: offset,
                       burn=lambda src, out, text, secs: (burned.append(text), shutil.copy(src, out)),
                       upload=lambda path, key, ct: uploaded.append(key), now=lambda: 10.0)
    result = scenes.check(job_id, deps)
    with maker() as s:
        job = s.get(Job, job_id)
        assert job.state == expect_state, result
        balance = pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO)
    if expect_state == 1:
        assert burned == ["This video was created with AI."] and uploaded == [f"jobs/{job_id}/scene/final.mp4"]
        assert balance == 50
    else:
        assert uploaded == [] and balance == 200  # refunded in full


def test_web_copy_does_not_mention_talking_scenes_while_off():
    web = Path(catalog.ASSETS).parents[4] / "apps" / "web"
    for rel in ("app/apps/page.tsx", "src/features/apps-shelf/AppsShelf.tsx", "src/features/apps-shelf/AppUse.tsx"):
        text = (web / rel).read_text(encoding="utf-8").lower()
        for word in ("talking", "lip-sync", "lipsync", "presenter"):
            assert word not in text, (rel, word)
