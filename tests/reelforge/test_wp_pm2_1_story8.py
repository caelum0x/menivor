"""Wave P PM2.1 (MH5): story in 8 frames.

Acceptance covered here:
1. eight frames share the character: the locked identity leads every prompt,
   seeds are stable, and each frame is scored against the reference (MH4
   ``appearance-v1``) and stored with the character;
2. frames-only (Ken Burns) is paid in standard credits; the animated version is
   quoted in AI-video credits before render and debited at start; a failed shot
   falls back to its frame and its credits come back once; a failed story
   refunds everything;
3. the real ffmpeg builds a 720x1280 video with sound (integration test).
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.characters import hub
from app.domains.film import story8, story8_render, story8_tasks
from app.integrations.railyard import meters  # noqa: F401 - registers the outbox table
from app.models.db import character_refs, characters  # noqa: F401 - registers the tables
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services.billing import premium_credits as pc
from app.utils import utils

KEY = "story8-key"
H = {"x-api-key": KEY}
SCRIPT = ("A tired baker opens her shop before dawn. The street is empty and cold. She wants one perfect loaf. "
          "The oven breaks on the busiest morning. She bakes on the neighbour's stove instead. The first loaf "
          "comes out golden. A line forms outside the door. She smiles and flips the sign to open.")


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
    monkeypatch.setattr(story8, "get_session", _session)
    monkeypatch.setattr(story8, "enqueue", lambda job_id: "celery-1")
    monkeypatch.setenv("AI_VIDEO_CLIP_COST_USD", "0.20")
    with factory() as s:
        s.add(User(email="story@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    return factory


def _uid(maker) -> str:
    with maker() as s:
        return s.query(User).one().id


def _fund(maker, standard=0, ai_video=0):
    with maker() as s:
        uid = s.query(User).one().id
        if standard:
            CreditRepository(s).grant(uid, standard, "test_grant")
        if ai_video:
            pc.grant(s, uid, pc.KIND_AI_VIDEO, ai_video, "test_grant")
        s.commit()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(story8.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def _png(colour=(200, 120, 40), size=(512, 512)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="PNG")
    return out.getvalue()


# --------------------------------------------------------------------------- #
# Lines and plan
# --------------------------------------------------------------------------- #
def test_a_script_becomes_exactly_eight_lines_in_order():
    lines = story8.split_script(SCRIPT)
    assert len(lines) == 8 and lines[0].startswith("A tired baker") and lines[-1].endswith("open.")
    long = " ".join(f"Sentence number {n} goes here." for n in range(19))
    joined = story8.split_script(long)
    assert len(joined) == 8 and " ".join(joined) == long
    short = story8.split_script("One two three four five six seven eight nine ten eleven twelve.")
    assert len(short) == 8 and all(short)
    with pytest.raises(story8.Story8Error):
        story8.split_script("Too short.")


def test_a_topic_is_written_through_the_llm_in_eight_lines():
    prompts = []

    def fake_llm(prompt):
        prompts.append(prompt)
        return "\n".join(f"{n}. Line {n} of the story." for n in range(1, 9))

    lines = story8.write_lines("a baker who saves her shop", llm=fake_llm)
    assert lines == [f"Line {n} of the story." for n in range(1, 9)]
    assert "exactly 8 narration lines" in prompts[0] and "no brand or tool names" in prompts[0]
    with pytest.raises(story8.Story8Error) as err:
        story8.write_lines("topic", llm=lambda p: "Error: relay down")
    assert err.value.status_code == 503


def test_every_frame_leads_with_the_locked_character_and_keeps_its_seed():
    character = {"id": "c1", "name": "Mara", "descriptors": ["red scarf", "short grey hair"], "style": "warm film",
                 "reference_images": ["uploads/u/mara.jpg"], "negative": ["hat"]}
    frames = story8.build_plan(story8.split_script(SCRIPT), character)
    assert len(frames) == 8
    for frame in frames:
        assert frame.prompt.startswith("Mara, red scarf, short grey hair")
        assert "hat" in frame.negative
    assert len({f.seed for f in frames}) == 8
    again = story8.build_plan(story8.split_script(SCRIPT), character)
    assert [f.seed for f in again] == [f.seed for f in frames]
    assert {f.camera for f in frames} <= {"push_in", "pull_out", "pan_left", "pan_right"}


def test_prices_frames_in_standard_credits_and_animation_in_ai_video_credits(monkeypatch):
    from app.domains.reels.pricing import standard_credits

    monkeypatch.setenv("AI_VIDEO_CLIP_COST_USD", "0.20")
    price = story8.quote(story8.build_plan(story8.split_script(SCRIPT)))
    assert price["seconds"] == 28
    assert price["frames"] == {"standard_credits": standard_credits(28) + 1, "ai_video_credits": 0}
    assert price["animated"]["standard_credits"] == price["frames"]["standard_credits"]
    assert price["animated"]["ai_video_credits"] == 8 * pc.ai_video_credits_for_usd(0.20)


# --------------------------------------------------------------------------- #
# Routes: plan, start (debit), quote checks
# --------------------------------------------------------------------------- #
def test_plan_then_make_frames_debits_standard_credits(maker):
    client = _client()
    plan = client.post("/api/v1/film/story8/plan", json={"script": SCRIPT}, headers=H)
    assert plan.status_code == 200, plan.text
    data = plan.json()["data"]
    assert len(data["lines"]) == 8 and "prompt" not in json.dumps(data["frames"])
    price = data["quote"]["frames"]
    body = {"lines": data["lines"], "mode": "frames", "quoted": price}
    assert client.post("/api/v1/film/story8", json=body, headers=H).status_code == 402
    _fund(maker, standard=5)
    stale = client.post("/api/v1/film/story8", json={**body, "quoted": {**price, "standard_credits": 1}}, headers=H)
    assert stale.status_code == 409
    res = client.post("/api/v1/film/story8", json=body, headers=H)
    assert res.status_code == 200, res.text
    job_id = res.json()["data"]["job_id"]
    with maker() as s:
        assert CreditRepository(s).balance(_uid(maker)) == 5 - price["standard_credits"]
        job = s.get(Job, job_id)
        assert job.kind == "story8" and len(job.params["frames"]) == 8
    view = client.get(f"/api/v1/film/story8/{job_id}", headers=H).json()["data"]
    assert view["mode"] == "frames" and len(view["frames"]) == 8


def test_animated_needs_ai_video_credits_quoted_first(maker):
    client = _client()
    data = client.post("/api/v1/film/story8/plan", json={"script": SCRIPT}, headers=H).json()["data"]
    price = data["quote"]["animated"]
    _fund(maker, standard=5)
    body = {"lines": data["lines"], "mode": "animated", "quoted": price}
    short = client.post("/api/v1/film/story8", json=body, headers=H)
    assert short.status_code == 402 and short.json()["data"]["code"] == "ai_video_credits_required"
    with maker() as s:  # the failed start charged nothing
        assert CreditRepository(s).balance(_uid(maker)) == 5
    _fund(maker, ai_video=price["ai_video_credits"])
    assert client.post("/api/v1/film/story8", json=body, headers=H).status_code == 200
    with maker() as s:
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == 0


def test_enqueue_failure_refunds_everything(maker, monkeypatch):
    client = _client()
    data = client.post("/api/v1/film/story8/plan", json={"script": SCRIPT}, headers=H).json()["data"]
    price = data["quote"]["animated"]
    _fund(maker, standard=5, ai_video=price["ai_video_credits"])

    def boom(job_id):
        raise RuntimeError("broker down")

    monkeypatch.setattr(story8, "enqueue", boom)
    res = client.post("/api/v1/film/story8", json={"lines": data["lines"], "mode": "animated", "quoted": price},
                      headers=H)
    assert res.status_code == 502
    with maker() as s:
        assert CreditRepository(s).balance(_uid(maker)) == 5
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == price["ai_video_credits"]


def test_blocked_words_are_refused_before_any_charge(maker):
    client = _client()
    lines = story8.split_script(SCRIPT)
    lines[3] = "underage content"
    _fund(maker, standard=5)
    price = story8.quote()["frames"]
    res = client.post("/api/v1/film/story8", json={"lines": lines, "mode": "frames", "quoted": price}, headers=H)
    assert res.status_code == 400


# --------------------------------------------------------------------------- #
# Worker: frames, scores, animation fallback, failure refunds
# --------------------------------------------------------------------------- #
class FakeStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload(self, path, key, content_type):
        self.objects[key] = Path(path).read_bytes()

    def fetch(self, key):
        return self.objects[key]


def _deps(store, **over):
    def narrate(text, language, audio_path):
        ffmpeg = story8_render.ffmpeg_bin()
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=28",
                        "-c:a", "libmp3lame", audio_path], check=True)
        return [[w, n * 0.4, n * 0.4 + 0.35] for n, w in enumerate(text.split()[:60])]

    base = dict(frame_image=lambda prompt, negative, seed: _png((seed % 255, 90, 160)), narrate=narrate,
                upload=store.upload, fetch=store.fetch, submit_shot=lambda session, job, frame: "x",
                enqueue_shot=lambda job_id: None, schedule_assemble=lambda job_id: None, burn_captions=False)
    base.update(over)
    return story8_tasks.Deps(**base)


def _started(maker, mode="frames", character_id=None):
    price = story8.quote()[mode]
    _fund(maker, standard=price["standard_credits"], ai_video=price["ai_video_credits"])
    uid = _uid(maker)
    with maker() as s:
        job = story8.start(s, uid, lines=story8.split_script(SCRIPT), mode=mode, quoted=price,
                           character_id=character_id)
        s.commit()
        return job.id


def _real_face_character(maker, store) -> str:
    """A consented character with a reference image (the hub facade rows)."""
    from datetime import datetime, timezone

    from app.models.db.characters import Character

    store.objects["uploads/u/ref.png"] = _png((10, 90, 160))
    uid = _uid(maker)  # outside the session: StaticPool shares one connection
    with maker() as s:
        row = Character(user_id=uid, name="Mara", descriptors=["red scarf"], reference_images=["uploads/u/ref.png"],
                        negative=[], style="", lora_ref="", identity_key="v2|" + "a" * 64)
        s.add(row)
        s.flush()
        s.add(hub.CharacterHubProfile(character_id=row.id, user_id=uid, kind=hub.KIND_REAL_FACE,
                                      consent_verified_at=datetime.now(timezone.utc)))
        s.commit()
        return row.id


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg") and not shutil.which("ffprobe"), reason="ffmpeg required")
def test_frames_story_renders_scores_and_finishes(maker, monkeypatch):
    store = FakeStore()
    character_id = _real_face_character(maker, store)
    job_id = _started(maker, character_id=character_id)
    result = story8_tasks.run(job_id, _deps(store))
    assert result["stage"] == "finished", result
    with maker() as s:
        job = s.get(Job, job_id)
        assert job.state == story8.TASK_STATE_COMPLETE and job.result_key.endswith("final.mp4")
        frames = job.params["frames"]
        assert all(f["key"] in store.objects for f in frames)
        assert all(isinstance(f["identity_score"], float) for f in frames)
        scores = s.query(hub.CharacterIdentityScore).filter_by(job_id=job_id).count()
        assert scores == 8
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                            "-of", "json", "-"], input=store.objects[f"jobs/{job_id}/story8/final.mp4"],
                           capture_output=True, check=True)
    streams = json.loads(probe.stdout)["streams"]
    video = next(st for st in streams if st["codec_type"] == "video")
    assert (video["width"], video["height"]) == (720, 1280)
    assert any(st["codec_type"] == "audio" for st in streams)


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_animated_story_falls_back_per_shot_and_refunds_those_shots_once(maker):
    store = FakeStore()
    job_id = _started(maker, mode="animated")
    shots: list[str] = []

    def submit(session, story, frame):
        job = Job(user_id=story.user_id, kind="broll_gen", state=4, params={"story8_parent": story.id})
        session.add(job)
        session.flush()
        shots.append(job.id)
        return job.id

    deps = _deps(store, submit_shot=submit)
    assert story8_tasks.run(job_id, deps)["stage"] == "animating"
    assert len(shots) == 8
    ffmpeg = story8_render.ffmpeg_bin()
    with maker() as s:
        for n, shot_id in enumerate(shots):
            row = s.get(Job, shot_id)
            if n < 6:
                key = f"jobs/{shot_id}/clip.mp4"
                path = Path(f"/tmp/story8-test-{shot_id}.mp4")
                subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                                "testsrc=size=320x568:rate=24:duration=3", str(path)], check=True)
                store.objects[key] = path.read_bytes()
                path.unlink()
                row.state, row.result_key = 1, key
            else:
                row.state = -1
        s.commit()
    result = story8_tasks.assemble(job_id, deps)
    assert result == {"job_id": job_id, "stage": "finished", "fallback_frames": 2}
    per_clip = pc.ai_video_credits_for_usd(0.20)
    with maker() as s:
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == 2 * per_clip
        job = s.get(Job, job_id)
        assert job.state == 1 and sum(1 for f in job.params["frames"] if f["clip_key"]) == 6
    assert story8_tasks.assemble(job_id, deps)["state"] == 1  # finished stories are left alone


def test_waiting_shots_reschedule_until_the_timeout(maker):
    store = FakeStore()
    job_id = _started(maker, mode="animated")
    scheduled = []
    deps = _deps(store, schedule_assemble=scheduled.append,
                 submit_shot=lambda session, job, frame: _pending_shot(session, job))
    story8_tasks.run(job_id, deps)
    scheduled.clear()
    assert story8_tasks.assemble(job_id, deps)["stage"] == "animating"
    assert scheduled == [job_id]


def _pending_shot(session, story):
    job = Job(user_id=story.user_id, kind="broll_gen", state=4, params={})
    session.add(job)
    session.flush()
    return job.id


def test_a_failed_frame_lane_fails_the_story_and_refunds_it(maker):
    store = FakeStore()
    job_id = _started(maker, mode="animated")

    def down(prompt, negative, seed):
        raise RuntimeError("image lane down")

    assert story8_tasks.run(job_id, _deps(store, frame_image=down))["stage"] == "failed"
    price = story8.quote()["animated"]
    with maker() as s:
        job = s.get(Job, job_id)
        assert job.state == story8.TASK_STATE_FAILED and "image lane down" in job.error
        assert CreditRepository(s).balance(_uid(maker)) == price["standard_credits"]
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == price["ai_video_credits"]
    # A second failure pass refunds nothing more.
    story8_tasks._fail(job_id, "again")
    with maker() as s:
        assert CreditRepository(s).balance(_uid(maker)) == price["standard_credits"]
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == price["ai_video_credits"]


# --------------------------------------------------------------------------- #
# Commands and copy
# --------------------------------------------------------------------------- #
def test_ffmpeg_commands_keep_the_gop_loudness_and_camera_moves():
    push = " ".join(story8_render.ken_burns_command("f.png", "o.mp4", seconds=3.5, camera="push_in", ffmpeg="ff"))
    pull = " ".join(story8_render.ken_burns_command("f.png", "o.mp4", seconds=3.5, camera="pull_out", ffmpeg="ff"))
    pan = " ".join(story8_render.ken_burns_command("f.png", "o.mp4", seconds=3.5, camera="pan_left", ffmpeg="ff"))
    assert "d=105" in push and "1+0.12*on/105" in push and "1.12-0.12*on/105" in pull and "(1-on/105)" in pan
    for cmd in (push, " ".join(story8_render.concat_command(["a.mp4", "b.mp4"], "o.mp4", ffmpeg="ff"))):
        assert "-g 60" in cmd and "-sc_threshold 0" in cmd
    mux = " ".join(story8_render.mux_command("v.mp4", "a.mp3", "o.mp4", ass_path="/tmp/c.ass", ffmpeg="ff"))
    assert "loudnorm=I=-15" in mux and "ass=" in mux and "+faststart" in mux


def test_captions_are_two_to_four_words_a_line():
    words = [[w, n * 0.3, n * 0.3 + 0.25] for n, w in enumerate("one two three four five six seven eight".split())]
    ass = story8_render.captions_ass(words)
    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert dialogues and all(2 <= line.count("\\k") <= 4 for line in dialogues)


def test_no_vendor_or_model_names_reach_the_client(maker):
    from app.domains.presets_hub.catalog import vendor_hits

    client = _client()
    data = client.post("/api/v1/film/story8/plan", json={"script": SCRIPT}, headers=H).json()["data"]
    assert not vendor_hits(json.dumps(data))
    blurb = json.loads(story8.PRESET_FILE.read_text(encoding="utf-8"))["blurb"]
    assert not vendor_hits(blurb)
