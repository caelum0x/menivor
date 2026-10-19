""""Very ___ Time" template (preset very-time@v1) on top of story8.

Covers: the preset, the guard-rail (before any debit), the plan and start
routes, the animated shot contract, static captions, the shipped LUTs, the vfx
LUT fragment, the render's LUT skip and a real ffmpeg render through the LUT.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
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
from app.domains.film import story8, story8_render, story8_tasks, very_time
from app.integrations.railyard import meters  # noqa: F401 - registers the outbox table
from app.models.db import character_refs, characters  # noqa: F401 - registers the tables
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services.billing import premium_credits as pc
from app.services.captions.ass_static import build_static_ass
from app.services.compose import vfx
from app.utils import utils

API_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
KEY = "very-time-key"
H = {"x-api-key": KEY}
BODY = {"place_word": "Turkish", "ritual": "pouring tea into a tulip glass on a saucer"}
LINE = "You met me at a very Turkish time in my life."


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
    monkeypatch.setattr(very_time, "get_session", _session)
    monkeypatch.setattr(story8, "enqueue", lambda job_id: "celery-1")
    monkeypatch.setenv("AI_VIDEO_CLIP_COST_USD", "0.20")
    monkeypatch.delenv(very_time.VIDEO_MODEL_ENV, raising=False)
    monkeypatch.delenv(very_time.BLOCKED_ENV, raising=False)
    # v2: provider lanes come from the configured keys; these v1 tests run on the fal lane.
    for name in ("ARK_API_KEY", "REPLICATE_API_TOKEN", "ELEVENLABS_API_KEY", "MUSETALK_API_KEY",
                 "MUSETALK_BASE_URL", "VERY_TIME_REFERENCE_VIDEO_MODEL", "VERY_TIME_IMAGE_MODEL",
                 "VERY_TIME_REFERENCE_IMAGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAL_KEY", "fal-test-key")
    with factory() as s:
        s.add(User(email="vt@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
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
    app.include_router(very_time.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def _png(colour=(200, 120, 40), size=(512, 512)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="PNG")
    return out.getvalue()


def _inputs(**over):
    return very_time.clean_inputs(**{**BODY, **over})


# --------------------------------------------------------------------------- #
# Preset
# --------------------------------------------------------------------------- #
def test_preset_has_five_beats_fifteen_seconds_and_three_looks():
    data = story8.preset("very-time@v1")
    assert data is story8.preset("very-time")
    assert [b["id"] for b in data["beats"]] == ["detail", "character", "insert", "wide", "deadpan"]
    assert [b["seconds"] for b in data["beats"]] == [2.0, 3.0, 2.5, 3.0, 4.5]
    assert abs(sum(story8.beat_seconds(data, i) for i in range(5)) - 15.0) < 0.01
    assert [b["speaks"] for b in data["beats"]] == [False, False, False, False, True]
    for beat in data["beats"]:
        assert beat["camera"] and beat["camera_text"]
        for slot in ("{ritual}", "{garment}"):
            assert slot in beat["image_prompt"] or slot in beat["motion_prompt"] or beat["id"] == "deadpan"
    assert "{chest_text}" in data["beats"][1]["image_prompt"] and "{place_word}" in data["default_line"]
    assert set(data["looks"]) == {"console", "flash", "atelier"}
    for look in data["looks"].values():
        assert look["style"] and look["negative"] and look["lut"] in vfx.LUT_FILES
        assert look["caption_style"] in ("game_yellow", "serif_lower_third")
    assert data["looks"]["console"]["caption_style"] == "game_yellow"
    assert data["looks"]["console"]["degrade"] == "console"
    assert "#4A0E17" in data["brand"]["garment"] and data["brand"]["chest_text"] == "very {place_word} time"
    banned = " ".join(t for terms in data["banned"].values() for t in terms)
    for term in ("flag", "crescent", "sultan", "ottoman", "khan", "steppe warrior", "fez", "hagia sophia",
                 "blue mosque", "braided crown grandmother", "doner shop man", "bauhaus nazar"):
        assert term in banned
    assert data["animated"]["video_model"] == "bytedance/seedance-2.0-i2v" and data["animated"]["seconds_from_beat"]


def test_story8_preset_is_unchanged_and_old_jobs_default_to_it():
    assert story8.preset() is story8.preset("story8")
    assert story8.frame_count() == 8 and story8.quote()["seconds"] == 28
    assert story8.job_preset_id({}) == "story8" and story8.job_preset_id({"preset": "very-time"}) == "very-time"
    with pytest.raises(story8.Story8Error):
        story8.preset("nope")


# --------------------------------------------------------------------------- #
# Guard-rail
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("field,text,term", [
    ("ritual", "waving FLAGS at a ferry", "flag"),
    ("ritual", "drinking tea under a Crescent Moon", "crescent moon"),
    ("ritual", "dressed as a SULTAN", "sultan"),
    ("ritual", "sultanların çayı", "sultan"),
    ("ritual", "BAYRAKLARI asmak", "bayrak"),
    ("ritual", "OSMANLI kıyafeti", "osmanli"),
    ("line", "Ottomans everywhere", "ottoman"),
    ("ritual", "posing as a steppe-warrior", "steppe warrior"),
    ("ritual", "a Khan on a horse", "khan"),
    ("ritual", "selfie at Hagia Sophia", "hagia sophia"),
    ("ritual", "the doner-shop man slicing", "doner shop man"),
    ("garment", "a shirt with a Bauhaus-Nazar graphic", "bauhaus nazar"),
    ("chest_text", "very SAVAGE time", "savage"),
    ("ritual", "underage content", "underage"),
])
def test_guard_blocks_banned_terms_in_any_field(field, text, term):
    inputs = {**BODY, field: text}
    assert term in very_time.guard(inputs)


def test_guard_is_turkish_aware_and_whole_word():
    assert very_time.fold("İSTANBUL ışık") == "istanbul isik"
    assert very_time.guard({**BODY, "ritual": "AY YILDIZ bayrağı"})  # dotless I and ğ fold
    # Whole words only: a flagship store, a khaki shirt and a fezzy drink are fine.
    clean = {"place_word": "Turkish", "ritual": "queueing at the flagship bakery in a khaki coat",
             "line": "You met me at a very Turkish time in my life."}
    assert very_time.guard(clean) == []
    assert very_time.guard(_inputs(place_word="Türk", ritual="çay demlemek, simit ve martılar")) == []


def test_guard_refuses_an_insult_as_the_place_word(monkeypatch):
    assert "stupid" in very_time.guard({**BODY, "place_word": "Stupid"})
    monkeypatch.setenv(very_time.BLOCKED_ENV, "badword, other")
    assert "badword" in very_time.guard({**BODY, "place_word": "Badword"})
    assert very_time.guard({**BODY, "ritual": "a stupid little cat"}) == []  # insult list is for the place word


def test_inputs_are_validated():
    for bad in ("", "Turkish1", "x" * 25, "Turk!sh", "-Turkish"):
        with pytest.raises(story8.Story8Error):
            very_time.clean_inputs(place_word=bad, ritual="tea")
    assert very_time.clean_inputs(place_word="Güney Doğu", ritual="tea").place_word == "Güney Doğu"
    assert very_time.clean_inputs(place_word="Anatolian-ish", ritual="tea").line.endswith("Anatolian-ish time in my life.")
    with pytest.raises(story8.Story8Error):
        very_time.clean_inputs(place_word="Turkish", ritual="tea", look="neon")
    with pytest.raises(story8.Story8Error):
        very_time.clean_inputs(place_word="Turkish", ritual="  ")
    inputs = very_time.clean_inputs(place_word="Turkish", ritual="tea", brand={"chest_text": "{place_word} mode"})
    assert inputs.chest_text == "Turkish mode" and "#4A0E17" in inputs.garment


def test_guard_blocks_plan_and_start_before_any_debit(maker):
    client = _client()
    plan = client.post("/api/v1/film/very-time/plan", json={**BODY, "ritual": "waving flags"}, headers=H)
    assert plan.status_code == 400
    assert plan.json()["data"] == {"code": "guard_blocked", "terms": ["flag"]}
    _fund(maker, standard=10, ai_video=10_000)
    with maker() as s:
        from app.models.db.models import CreditLedger

        rows_before = s.query(CreditLedger).count()
    quoted = {"standard_credits": 2, "ai_video_credits": 0}
    res = client.post("/api/v1/film/very-time", json={**BODY, "line": "a very sultan time", "mode": "frames",
                                                         "quoted": quoted}, headers=H)
    assert res.status_code == 400 and res.json()["data"]["code"] == "guard_blocked"
    assert "sultan" in res.json()["data"]["terms"]
    with maker() as s:
        assert CreditRepository(s).balance(_uid(maker)) == 10
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == 10_000
        assert s.query(CreditLedger).count() == rows_before
        assert s.query(Job).count() == 0


# --------------------------------------------------------------------------- #
# Plan and start
# --------------------------------------------------------------------------- #
def test_plan_returns_five_beats_one_line_and_both_prices(maker):
    from app.domains.presets_hub.catalog import vendor_hits
    from app.domains.reels.pricing import standard_credits

    client = _client()
    res = client.post("/api/v1/film/very-time/plan", json={**BODY, "look": "flash"}, headers=H)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert {"preset", "look", "caption_style", "lines", "beats", "quote"} <= set(data)
    assert data["duration_s"] == 15 and data["end_card"]["seconds"] == 0  # no CTA or logo: no end card
    assert data["preset"] == "very-time@v1" and data["look"] == "flash"
    assert data["caption_style"] == "serif_lower_third"
    assert data["lines"] == ["", "", "", "", LINE]
    assert [b["beat"] for b in data["beats"]] == ["detail", "character", "insert", "wide", "deadpan"]
    assert [b["seconds"] for b in data["beats"]] == [2.0, 3.0, 2.5, 3.0, 4.5]
    assert set(data["beats"][0]) == {"index", "beat", "line", "camera", "seconds"}
    assert data["quote"]["seconds"] == 15
    assert data["quote"]["frames"] == {"standard_credits": standard_credits(15) + 1, "ai_video_credits": 0}
    assert data["quote"]["animated"]["ai_video_credits"] == 5 * pc.ai_video_credits_for_usd(0.20)
    assert not vendor_hits(json.dumps(data)) and "prompt" not in json.dumps(data)
    custom = client.post("/api/v1/film/very-time/plan", json={**BODY, "line": "Bu çok Türk bir an."},
                         headers=H).json()["data"]
    assert custom["lines"][-1] == "Bu çok Türk bir an." and custom["caption_style"] == "game_yellow"
    bad = client.post("/api/v1/film/very-time/plan", json={**BODY, "place_word": "T4"}, headers=H)
    assert bad.status_code == 400 and bad.json()["data"]["code"] == "place_word"


def test_every_frame_carries_the_brand_garment_and_look():
    rows = very_time.build_frames(_inputs(look="atelier", brand={"garment": "a cream linen shirt"}))
    assert len(rows) == 5
    for row in rows:
        assert "a cream linen shirt" in row["prompt"] and '"very Turkish time"' in row["prompt"]
        assert "soft window light" in row["prompt"]
        assert "pouring tea" in row["prompt"] or row["beat"] == "deadpan"
        assert "flags" in row["negative"] and "Ottoman costume" in row["negative"]
        assert "cream linen shirt" in row["brief"]["continuity"]
    assert len({r["seed"] for r in rows}) == 5
    character = {"id": "c1", "name": "Selim", "descriptors": ["grey moustache"], "reference_images": ["u/s.png"]}
    with_char = very_time.build_frames(_inputs(), character)
    assert all(r["prompt"].startswith("Selim, grey moustache, wearing an oversized oxblood") for r in with_char)


def test_start_debits_and_stores_the_preset_look_and_brand(maker):
    client = _client()
    plan = client.post("/api/v1/film/very-time/plan", json=BODY, headers=H).json()["data"]
    price = plan["quote"]["frames"]
    body = {**BODY, "brand": {"chest_text": "very {place_word} time"}, "mode": "frames", "quoted": price}
    assert client.post("/api/v1/film/very-time", json=body, headers=H).status_code == 402
    _fund(maker, standard=5)
    stale = client.post("/api/v1/film/very-time", json={**body, "quoted": {**price, "standard_credits": 9}},
                        headers=H)
    assert stale.status_code == 409 and stale.json()["data"]["code"] == "quote_changed"
    res = client.post("/api/v1/film/very-time", json=body, headers=H)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert set(data) == {"job_id", "state"} and data["state"] == story8.TASK_STATE_PROCESSING
    with maker() as s:
        assert CreditRepository(s).balance(_uid(maker)) == 5 - price["standard_credits"]
        job = s.get(Job, data["job_id"])
        assert job.kind == "story8"
        params = job.params
        assert params["preset"] == "very-time" and params["look"] == "console"
        assert params["brand"] == {"garment": story8.preset("very-time")["brand"]["garment"],
                                   "chest_text": "very Turkish time", "preset": "", "cta": "",
                                   "garment_ref": None, "logo_ref": None}
        assert params["caption_style"] == "game_yellow" and params["line"] == LINE
        assert [f["seconds"] for f in params["frames"]] == [2.0, 3.0, 2.5, 3.0, 4.5]
    view = client.get(f"/api/v1/film/story8/{data['job_id']}", headers=H).json()["data"]
    assert view["preset"] == "very-time" and view["look"] == "console" and len(view["frames"]) == 5


def test_animated_start_needs_ai_video_credits(maker):
    client = _client()
    plan = client.post("/api/v1/film/very-time/plan", json=BODY, headers=H).json()["data"]
    price = plan["quote"]["animated"]
    _fund(maker, standard=5)
    body = {**BODY, "mode": "animated", "quoted": price}
    short = client.post("/api/v1/film/very-time", json=body, headers=H)
    assert short.status_code == 402 and short.json()["data"]["code"] == "ai_video_credits_required"
    _fund(maker, ai_video=price["ai_video_credits"])
    assert client.post("/api/v1/film/very-time", json=body, headers=H).status_code == 200
    with maker() as s:
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == 0


# --------------------------------------------------------------------------- #
# Animated shots: the multi-reference contract
# --------------------------------------------------------------------------- #
class FakeStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload(self, path, key, content_type):
        self.objects[key] = Path(path).read_bytes()

    def fetch(self, key):
        return self.objects[key]


def _no_ocr(image):
    from app.domains.film.chest_check import OcrUnavailable

    raise OcrUnavailable("no OCR in these v1 tests")


def _deps(store, **over):
    def narrate(text, language, audio_path):
        subprocess.run([story8_render.ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=330:duration=3", "-c:a", "libmp3lame", audio_path], check=True)
        return [[w, n * 0.3, n * 0.3 + 0.25] for n, w in enumerate(text.split())]

    def voice_take(*, params, user_id, work, fetch, max_seconds):
        path = str(Path(work) / "take.mp3")
        narrate(params.get("line") or "line", "", path)
        return path, 3.0, "auto"

    from app.domains.film import very_time_worker

    fake_image = lambda prompt, negative, seed: _png((seed % 255, 90, 160))  # noqa: E731
    vt = very_time_worker.VtDeps(
        presign=lambda key: f"https://bucket.example.com/{key}",
        ref_image=lambda prompt, negative, seed, urls, model: fake_image(prompt, negative, seed),
        text_image=lambda prompt, negative, seed, model: fake_image(prompt, negative, seed),
        ocr=_no_ocr, voice_take=voice_take)
    base = dict(frame_image=fake_image, narrate=narrate,
                upload=store.upload, fetch=store.fetch, enqueue_shot=lambda job_id: None,
                schedule_assemble=lambda job_id: None, burn_captions=False, very_time=vt)
    base.update(over)
    return story8_tasks.Deps(**base)


def _real_face_character(maker, store) -> str:
    from datetime import datetime, timezone

    from app.models.db.characters import Character

    store.objects["uploads/u/ref.png"] = _png((10, 90, 160))
    uid = _uid(maker)
    with maker() as s:
        row = Character(user_id=uid, name="Selim", descriptors=["grey moustache"],
                        reference_images=["uploads/u/ref.png"], negative=[], style="", lora_ref="",
                        identity_key="v2|" + "b" * 64)
        s.add(row)
        s.flush()
        s.add(hub.CharacterHubProfile(character_id=row.id, user_id=uid, kind=hub.KIND_REAL_FACE,
                                      consent_verified_at=datetime.now(timezone.utc)))
        s.commit()
        return row.id


def _started(maker, mode="frames", **over) -> str:
    inputs = _inputs(**over)
    price = story8.quote(very_time.build_frames(inputs), "very-time")[mode]
    _fund(maker, standard=price["standard_credits"], ai_video=price["ai_video_credits"])
    uid = _uid(maker)
    with maker() as s:
        job = very_time.start(s, uid, inputs, mode=mode, quoted=price)
        s.commit()
        return job.id


@pytest.mark.parametrize("with_character", [True, False])
def test_animated_shots_carry_video_model_references_and_brief(maker, with_character):
    store = FakeStore()
    character_id = _real_face_character(maker, store) if with_character else None
    job_id = _started(maker, mode="animated", character_id=character_id, look="flash")
    assert story8_tasks.run(job_id, _deps(store))["stage"] == "animating"
    with maker() as s:
        story = s.get(Job, job_id)
        shots = [s.get(Job, story.params["_shots"][str(i)]) for i in range(5)]
        if with_character:
            assert s.query(hub.CharacterIdentityScore).filter_by(job_id=job_id).first().preset_id == \
                "very-time:frame-1"
    for index, shot in enumerate(shots):
        params = shot.params
        frame = story.params["frames"][index]
        assert shot.kind == "broll_gen" and params["story8_parent"] == job_id
        # Old keys stay so the old worker path still works.
        assert params["image_key"] == frame["key"] and params["prompt"] and params["mode"] == "i2v"
        assert params["duration_s"] == frame["seconds"]
        # v2: an identity image (the character's, or the host sheet made for the job) needs the
        # reference-to-video row (i2v takes one image).
        assert params["video_model"] == "bytedance/seedance-2.0-r2v"
        identity = "uploads/u/ref.png" if with_character else f"jobs/{job_id}/story8/sheet.png"
        expected = [{"key": frame["key"], "role": "first_frame"}, {"key": identity, "role": "identity"}]
        assert params["references"] == expected
        brief = params["brief"]
        assert set(brief) == {"format", "action", "camera", "continuity", "audio", "constraints"}
        assert brief["format"] == f"9:16, {frame['seconds']:g} s, 720p"
        assert "very Turkish time" in brief["continuity"] and "keep the flash lookbook look" in brief["constraints"]
        if index == 4:
            assert LINE in brief["audio"] and "flat and quiet" in brief["audio"]
        else:
            assert brief["audio"] == "room tone and one diegetic sound; no music; no speech"


def test_video_model_is_configurable(maker, monkeypatch):
    monkeypatch.setenv(very_time.VIDEO_MODEL_ENV, "bytedance/seedance-2.0-r2v-ark")
    store = FakeStore()
    job_id = _started(maker, mode="animated")
    story8_tasks.run(job_id, _deps(store))
    with maker() as s:
        story = s.get(Job, job_id)
        shot = s.get(Job, story.params["_shots"]["0"])
        assert shot.params["video_model"] == "bytedance/seedance-2.0-r2v-ark"


def test_story8_shots_keep_the_old_contract(maker):
    store = FakeStore()
    price = story8.quote()["animated"]
    _fund(maker, standard=price["standard_credits"], ai_video=price["ai_video_credits"])
    uid = _uid(maker)
    script = " ".join(f"Sentence {n} of the story goes here." for n in range(8))
    with maker() as s:
        job = story8.start(s, uid, lines=story8.split_script(script), mode="animated", quoted=price)
        s.commit()
        job_id = job.id
    story8_tasks.run(job_id, _deps(store))
    with maker() as s:
        story = s.get(Job, job_id)
        assert story.params["preset"] == "story8"
        shot = s.get(Job, story.params["_shots"]["0"])
        assert shot.params["duration_s"] == 5.0
        assert not {"video_model", "references", "brief"} & set(shot.params)


def test_default_frame_lane_uses_the_job_lane_models(maker):
    """v2: the host sheet comes from the text lane (Ideogram), the stills from the reference lane with it."""
    from app.domains.film import very_time_worker

    text, ref = [], []
    store = FakeStore()
    job_id = _started(maker)
    vt = very_time_worker.VtDeps(
        presign=lambda key: f"https://bucket.example.com/{key}",
        text_image=lambda prompt, negative, seed, model: text.append(model) or _png(),
        ref_image=lambda prompt, negative, seed, urls, model: ref.append((model, urls)) or _png(),
        ocr=_no_ocr)
    deps = _deps(store, frame_image=story8_tasks.house_frame_image, very_time=vt)
    with maker() as s:
        job = s.get(Job, job_id)
        story8_tasks.make_frames(s, job, str(Path("/tmp")), deps)
    assert text == ["ideogram/ideogram-v3"]
    assert [m for m, _ in ref] == ["bytedance-seed/seedream-4.5-edit"] * 5
    assert all(urls == [f"https://bucket.example.com/jobs/{job_id}/story8/sheet.png"] for _, urls in ref)


# --------------------------------------------------------------------------- #
# Static captions and the speech plan
# --------------------------------------------------------------------------- #
def test_static_game_yellow_ass_is_whole_sentence_in_the_safe_zone():
    ass = build_static_ass([("you met me at a very {Türk} time\\N in my life.", 10.5, 15.0)], "game_yellow",
                           720, 1280)
    style = next(line for line in ass.splitlines() if line.startswith("Style:"))
    fields = style.split(",")
    assert fields[0] == "Style: Static" and fields[3] == "&H004DE1FF"  # #FFE14D as &HAABBGGRR
    assert fields[18] == "2" and fields[21] == "467"  # bottom-centre, MarginV 700 scaled to 1280
    assert "PlayResX: 720" in ass and "PlayResY: 1280" in ass
    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) == 1
    text = dialogues[0].split(",,", 1)[1].split(",", 3)[-1] if ",," in dialogues[0] else dialogues[0]
    assert "0:00:10.50,0:00:15.00" in dialogues[0]
    assert "You met me at a very (Türk) time" in dialogues[0]  # sentence case, braces neutralised
    assert "\\N" not in dialogues[0].replace("\\⁠N", "")  # no line-break escape survives
    for tag in ("\\k", "\\t(", "\\fscx", "\\c&"):
        assert tag not in ass
    assert text
    full = build_static_ass([("very Türk time", 0, 1)], "game_yellow")
    assert ",700,1" in full.splitlines()[9]


def test_serif_lower_third_and_turkish_letters():
    ass = build_static_ass([("ılık çay, şeker ve İstanbul ğ ü ö", 0.0, 2.0)], "serif_lower_third", 720, 1280)
    style = next(line for line in ass.splitlines() if line.startswith("Style:")).split(",")
    assert style[1] == "Georgia" and style[18] == "1" and float(style[17]) > 0  # bottom-left, soft shadow
    assert "ılık çay, şeker ve İstanbul ğ ü ö" in ass
    yellow = build_static_ass([("istanbul", 0, 1)], "game_yellow", language="tr")
    assert "İstanbul" in yellow
    with pytest.raises(ValueError):
        build_static_ass([("x", 0, 1)], "nope")


def test_render_captions_keep_karaoke_default_and_take_a_style():
    words = [[w, n * 0.3, n * 0.3 + 0.25] for n, w in enumerate("one two three four five".split())]
    assert "\\k" in story8_render.captions_ass(words)
    static = story8_render.captions_ass(words, "game_yellow", lines=[(LINE, 10.5, 15.0)])
    assert "\\k" not in static and LINE in static
    derived = story8_render.captions_ass(words, "serif_lower_third")
    assert "one two three four five" in derived and "0:00:00.00,0:00:01.45" in derived


def test_speech_plan_places_the_line_on_the_payoff_beat():
    rows = very_time.build_frames(_inputs())
    data = story8.preset("very-time")
    plan = story8_tasks._speech_plan(data, {"look": "console", "preset": "very-time"}, rows)
    assert plan["text"] == LINE and plan["style"] == "game_yellow"
    assert plan["lines"] == [(LINE, 10.5, 15.0)] and abs(plan["delay_s"] - 10.7) < 1e-9
    story = story8_tasks._speech_plan(story8.preset(), {}, [{"index": 0, "line": "a b", "seconds": 3.5}])
    assert story == {"text": "a b", "style": "karaoke", "lines": None, "delay_s": 0.0}


# --------------------------------------------------------------------------- #
# LUTs and vfx
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["console-480.cube", "flash-lookbook.cube", "atelier-film.cube"])
def test_shipped_luts_parse(name):
    path = API_DIR / "assets" / "luts" / name
    assert path.stat().st_size < 150_000
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "LUT_3D_SIZE 17" in lines[:6]
    rows = [line for line in lines if line and (line[0].isdigit() or line[0] == "-")]
    assert len(rows) == 17 ** 3 == 4913
    for row in rows:
        values = [float(v) for v in row.split()]
        assert len(values) == 3 and all(0.0 <= v <= 1.0 for v in values)


def test_lut_script_is_deterministic_and_matches_the_shipped_files():
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_luts", API_DIR / "tools" / "luts" / "make_luts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_luts"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("make_luts", None)
    assert module.main(["--check"]) == 0
    look = module.LOOKS[0]
    assert module.cube_text(look) == module.cube_text(look)
    assert {f"{lk.id}.cube" for lk in module.LOOKS} == set(vfx.LUT_FILES.values())


def test_vfx_lut_fragment_and_path_escaping():
    frag = vfx.lut_fragment("flash-lookbook")
    assert frag.startswith("lut3d=file=") and frag.endswith(":interp=tetrahedral")
    assert "flash-lookbook.cube" in frag
    odd = vfx.lut_fragment("x", path="/tmp/we:ird,dir's [luts]/a;b.cube")
    assert odd == "lut3d=file=/tmp/we\\:ird\\,dir\\'s \\[luts\\]/a\\;b.cube:interp=tetrahedral"
    assert vfx.lut_fragment("unknown-look") is None
    assert vfx.console_degrade_fragment(720, 1280) == \
        "scale=270:480:flags=neighbor,scale=720:1280:flags=neighbor,setsar=1"
    fragments = vfx.build_vfx_filters(None, ["lut:console-480"], width=720, height=1280)
    assert fragments[0].startswith("lut3d=") and fragments[1].startswith("scale=270:480")
    assert vfx.build_vfx_filters(None, ["lut:flash-lookbook"])[0].startswith("lut3d=")
    assert vfx.build_vfx_filters(None, ["lut:nope"]) == []
    assert vfx.build_vfx_filters(None, ["glow"]) == ["gblur=sigma=3,eq=brightness=0.06:contrast=1.05"]


def test_render_skips_the_lut_when_ffmpeg_lacks_lut3d(monkeypatch):
    looks = story8.preset("very-time")["looks"]
    monkeypatch.setattr(story8_render, "has_filter", lambda name, ffmpeg=None: name != "lut3d")
    console = story8_render.look_filters(looks["console"])
    assert len(console) == 1 and console[0].startswith("scale=270:480")  # degrade only, no LUT
    assert story8_render.look_filters(looks["flash"]) == []
    monkeypatch.setattr(story8_render, "has_filter", lambda name, ffmpeg=None: True)
    flash = story8_render.look_filters(looks["flash"])
    assert len(flash) == 1 and flash[0].startswith("lut3d=")
    assert story8_render.look_filters(None) == []


def test_mux_grades_before_captions_and_delays_the_line():
    mux = story8_render.mux_command("v.mp4", "a.mp3", "o.mp4", ass_path="/tmp/c.ass", ffmpeg="ff",
                                    video_filters=["lut3d=file=/x.cube:interp=tetrahedral"], audio_delay_s=10.7)
    graph = mux[mux.index("-filter_complex") + 1]
    assert graph.startswith("[0:v]lut3d=file=/x.cube:interp=tetrahedral,ass=")
    assert "loudnorm=I=-15" in graph and "adelay=delays=10700:all=1,apad[a]" in graph
    plain = story8_render.mux_command("v.mp4", "a.mp3", "o.mp4", ffmpeg="ff")
    assert plain[plain.index("-filter_complex") + 1] == \
        "[0:v]null[v];[1:a]loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100[a]"
    hold = " ".join(story8_render.ken_burns_command("f.png", "o.mp4", seconds=2, camera="hold", ffmpeg="ff"))
    assert "zoompan=z='1'" in hold


def _lut3d() -> bool:
    return bool(shutil.which("ffmpeg")) and story8_render.has_filter("lut3d")


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_one_second_clip_renders_through_each_lut(tmp_path):
    if not _lut3d():
        pytest.skip("this ffmpeg has no lut3d filter")
    ffmpeg = story8_render.ffmpeg_bin()
    src, audio = tmp_path / "src.mp4", tmp_path / "a.wav"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=30:duration=1",
                    "-pix_fmt", "yuv420p", str(src)], check=True)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                    str(audio)], check=True)
    for look in story8.preset("very-time")["looks"].values():
        out = tmp_path / f"{look['lut']}.mp4"
        filters = story8_render.look_filters(look, ffmpeg=ffmpeg)
        assert filters[0].startswith("lut3d=")
        story8_render.run(story8_render.mux_command(str(src), str(audio), str(out), ffmpeg=ffmpeg,
                                                    video_filters=filters, audio_delay_s=0.3))
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height",
                                "-of", "json", str(out)], capture_output=True, check=True, text=True)
        info = json.loads(probe.stdout)
        video = next(st for st in info["streams"] if st.get("width"))
        assert (video["width"], video["height"]) == (720, 1280)
        assert abs(float(info["format"]["duration"]) - 1.0) < 0.2


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
@pytest.mark.parametrize("grade", [None, False])
def test_very_time_frames_render_fifteen_seconds(maker, monkeypatch, grade):
    store = FakeStore()
    job_id = _started(maker, look="console")
    from app.domains.film import very_time_audio, very_time_worker

    seen, mixes = {}, []
    real_final, real_mix = very_time_worker.final_command, very_time_audio.mix_command

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real_final(*args, **kwargs)

    monkeypatch.setattr(very_time_worker, "final_command", spy)
    monkeypatch.setattr(very_time_audio, "mix_command", lambda **kw: mixes.append(kw) or real_mix(**kw))
    result = story8_tasks.run(job_id, _deps(store, grade=grade))
    assert result["stage"] == "finished", result
    assert abs(mixes[0]["vo_delay_s"] - 10.7) < 1e-9  # the take starts 0.2 s into the payoff beat
    has_lut = any(f.startswith("lut3d=") for f in seen["grade"])
    assert has_lut == (grade is None and _lut3d())
    assert any(f.startswith("scale=270:480") for f in seen["grade"])
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                            "-of", "json", "-"], input=store.objects[f"jobs/{job_id}/story8/final.mp4"],
                           capture_output=True, check=True)
    info = json.loads(probe.stdout)
    assert abs(float(info["format"]["duration"]) - 15.0) < 0.3
    assert any(st["codec_type"] == "audio" for st in info["streams"])


# --------------------------------------------------------------------------- #
# Cross-lane: the template's shot params run through the B-roll gateway path
# --------------------------------------------------------------------------- #
class _GatewayResp:
    def __init__(self, body):
        self.status_code, self._body, self.headers, self.text = 200, body, {}, str(body)

    def json(self):
        return self._body


class _GatewayHttp:
    def __init__(self, script):
        self._script, self.calls = list(script), []

    def request(self, method, url, *, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json})
        return self._script.pop(0)


@pytest.mark.parametrize("with_character", [True, False])
def test_template_shots_run_on_the_gateway_without_a_400(maker, monkeypatch, with_character):
    from app.domains.broll import service
    from app.domains.gateway.provider_execution import MediaProviderExecutor

    store = FakeStore()
    character_id = _real_face_character(maker, store) if with_character else None
    job_id = _started(maker, mode="animated", character_id=character_id)
    story8_tasks.run(job_id, _deps(store))
    with maker() as s:
        story = s.get(Job, job_id)
        params = dict(s.get(Job, story.params["_shots"]["4"]).params)

    http = _GatewayHttp([
        _GatewayResp({"request_id": "req-9", "status_url": "https://q/s", "response_url": "https://q/r"}),
        _GatewayResp({"status": "COMPLETED"}), _GatewayResp({"video": {"url": "https://cdn/shot.mp4"}})])
    persisted = []
    monkeypatch.setenv("FAL_KEY", "fal-test-key")
    monkeypatch.setattr(service, "_load_job_context", lambda jid: ("u1", dict(params)))
    monkeypatch.setattr(service, "_set_progress", lambda jid, p: None)
    monkeypatch.setattr(service, "_sleep", lambda s: None)
    monkeypatch.setattr(service, "_presign_key", lambda key: f"https://bucket.r2.example.com/{key}")
    monkeypatch.setattr(service, "_download_to_temp", lambda url: "/nonexistent.mp4")
    monkeypatch.setattr(service, "_rehost_clip", lambda jid, path: f"jobs/{jid}/broll/x.mp4")
    monkeypatch.setattr(service, "_persist_and_complete", lambda **kw: persisted.append(kw))
    monkeypatch.setattr(service, "_executor", lambda: MediaProviderExecutor(session_http=http))

    out = service.run_broll_generation("shot-5")
    body = http.calls[0]["json"]
    assert out["video_model"] == params["video_model"] and persisted
    assert body["prompt"].startswith("Format: 9:16, 4.5 s, 720p")
    identity = "uploads/u/ref.png" if with_character else f"jobs/{job_id}/story8/sheet.png"
    assert len(body["image_urls"]) == 2 and body["image_urls"][1].endswith(identity)
    assert "frame-5" in body["image_urls"][0]
