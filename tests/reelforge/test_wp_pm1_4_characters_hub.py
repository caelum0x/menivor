"""Wave P PM1.4 (MH4): My characters and brands.

* Original characters come from the narrator roster; no consent needed.
* A real-face character needs 10-20 of your own photos, the spoken consent
  phrase (ASR) and a locked Identity Lock passport; it fails closed when
  Identity Lock is not configured. No third-party faces, no face swap, no
  InsightFace anywhere.
* LoRA training runs only on AI-video credits, quoted before it starts, and
  is refunded once if it fails.
* An identity score is recorded per render (preset x model).
* A brand kit (logo, colours, voice, product shots) is accepted by every preset.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import re
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from PIL import Image
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.characters import hub
from app.domains.presets_hub import catalog as presets_catalog
from app.domains.presets_hub import service as presets_service
from app.models.db.base import Base
from app.models.db.models import Job, User, UserPreset
from app.models.exception import HttpException
from app.services.billing import premium_credits as pc
from app.utils import utils

KEY = "hub-user-key"
REPO = Path(__file__).resolve().parents[2]
PHOTOS = [f"uploads/u/face-{n}.jpg" for n in range(12)]


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
    monkeypatch.setattr(hub, "get_session", _session)
    monkeypatch.setattr(hub, "require_owned", lambda session, user_id, key: key.startswith("uploads/u/"))
    monkeypatch.setattr(hub, "locked_passports", lambda session, user_id: [
        {"passport_id": "pp_1", "version": 2, "kind": "identity", "content_digest": "d", "status": "locked"}])
    monkeypatch.setattr(hub, "transcribe_key", lambda key: "")
    monkeypatch.setattr(hub, "enqueue_training", lambda job_id, request_id: "celery-1")
    monkeypatch.setenv("REELFORGE_VOICE_VERIFY_SECRET", "test-secret-for-phrases")
    with factory() as s:
        s.add(User(email="me@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    return factory


def _uid(maker) -> str:
    with maker() as s:
        return s.query(User).one().id


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(hub.router)

    def handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code,
                            content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, handler)
    return TestClient(app)


H = {"x-api-key": KEY}


def _real_face(client, monkeypatch, **over):
    challenge = client.post("/api/v1/my/characters/consent-phrase", headers=H).json()["data"]
    monkeypatch.setattr(hub, "transcribe_key", lambda key: f"um {challenge['phrase']} okay")
    body = {"name": "Me", "reference_keys": PHOTOS, "consent_token": challenge["token"],
            "recording_key": "uploads/u/consent.m4a", "passport_id": "pp_1", "passport_version": 2,
            "self_declared": True}
    body.update(over)
    return client.post("/api/v1/my/characters/real-face", json=body, headers=H)


# --------------------------------------------------------------------------- #
# Originals
# --------------------------------------------------------------------------- #
def test_original_character_comes_from_the_roster(maker):
    from app.domains.characters import narrators

    client = _client()
    narrator = narrators.list_narrators()[0]
    res = client.post("/api/v1/my/characters/original", json={"narrator_id": narrator.id}, headers=H)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["kind"] == "original" and data["name"] == narrator.name
    listing = client.get("/api/v1/my/characters", headers=H).json()["data"]["characters"]
    assert [c["id"] for c in listing] == [data["id"]]
    assert client.post("/api/v1/my/characters/original", json={"narrator_id": "nobody"},
                       headers=H).status_code == 404


# --------------------------------------------------------------------------- #
# Real faces: consent phrase + Identity Lock, own photos only
# --------------------------------------------------------------------------- #
def test_real_face_with_spoken_consent_and_identity_lock(maker, monkeypatch):
    client = _client()
    res = _real_face(client, monkeypatch)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["kind"] == "real_face"
    assert data["consent"]["verified"] is True and data["consent"]["words_heard"] >= 5
    assert data["identity_lock"] == {"passport_id": "pp_1", "version": 2}
    assert data["reference_count"] == 12


@pytest.mark.parametrize("over, code", [
    ({"self_declared": False}, "self_declaration"),
    ({"reference_keys": PHOTOS[:9]}, "photo_count"),
    ({"reference_keys": PHOTOS + [f"uploads/u/x{n}.jpg" for n in range(9)]}, "photo_count"),
    ({"reference_keys": PHOTOS[:11] + ["uploads/someone-else/face.jpg"]}, "not_your_upload"),
    ({"passport_id": "pp_other"}, "identity_lock"),
])
def test_real_face_refusals(maker, monkeypatch, over, code):
    res = _real_face(_client(), monkeypatch, **over)
    assert res.status_code in (400, 403, 409), res.text
    assert res.json()["data"]["code"] == code


def test_consent_phrase_must_be_spoken(maker, monkeypatch):
    client = _client()
    challenge = client.post("/api/v1/my/characters/consent-phrase", headers=H).json()["data"]
    monkeypatch.setattr(hub, "transcribe_key", lambda key: "hello this is a different sentence")
    body = {"name": "Me", "reference_keys": PHOTOS, "consent_token": challenge["token"],
            "recording_key": "uploads/u/consent.m4a", "passport_id": "pp_1", "passport_version": 2,
            "self_declared": True}
    res = client.post("/api/v1/my/characters/real-face", json=body, headers=H)
    assert res.status_code == 400 and res.json()["data"]["code"] == "consent_phrase"


def test_real_face_fails_closed_without_identity_lock(maker, monkeypatch):
    monkeypatch.setattr(hub, "locked_passports", lambda session, user_id: [])
    res = _real_face(_client(), monkeypatch)
    assert res.status_code == 409 and res.json()["data"]["code"] == "identity_lock"


def test_no_face_swap_route_and_no_insightface_dependency():
    from app.router import build_full_router

    paths = [r.path for r in build_full_router().routes if isinstance(r, APIRoute)]
    assert not [p for p in paths if re.search(r"face.?swap|swap.?face", p)]
    for manifest in ("requirements.txt", "pyproject.toml", "apps/api/pyproject.toml", "uv.lock"):
        path = REPO / manifest
        if path.is_file():
            assert "insightface" not in path.read_text(encoding="utf-8").lower(), manifest
    for py in (REPO / "apps" / "api" / "app").rglob("*.py"):
        assert "import insightface" not in py.read_text(encoding="utf-8", errors="ignore"), py


# --------------------------------------------------------------------------- #
# LoRA training: AI-video credits only, quoted first, refunded once on failure
# --------------------------------------------------------------------------- #
def _funded(maker, credits):
    with maker() as s:
        pc.grant(s, _uid(maker), pc.KIND_AI_VIDEO, credits, "test_grant")
        s.commit()


def test_training_is_quoted_then_charged_in_ai_video_credits(maker, monkeypatch):
    monkeypatch.setenv("CHARACTER_LORA_PROVIDER_USD", "1.00")
    client = _client()
    cid = _real_face(client, monkeypatch).json()["data"]["id"]
    quote = client.post(f"/api/v1/my/characters/{cid}/train/quote", headers=H).json()["data"]
    assert quote["credit_kind"] == "ai_video" and quote["credits"] == pc.ai_video_credits_for_usd(1.0)
    stale = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": quote["credits"] + 1},
                        headers=H)
    assert stale.status_code == 409
    short = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": quote["credits"]}, headers=H)
    assert short.status_code == 402
    with maker() as s:
        assert s.query(Job).filter_by(kind="character_lora").count() == 0
    _funded(maker, quote["credits"])
    res = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": quote["credits"]}, headers=H)
    assert res.status_code == 200, res.text
    job_id = res.json()["data"]["job_id"]
    with maker() as s:
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == 0
        job = s.get(Job, job_id)
        assert job.params["credits_cost"] == 0  # the standard-credit refund path stays a no-op
        assert job.params["hub_funding"] == "ai_video"


def test_original_characters_need_no_training(maker):
    from app.domains.characters import narrators

    client = _client()
    cid = client.post("/api/v1/my/characters/original", json={"narrator_id": narrators.list_narrators()[0].id},
                      headers=H).json()["data"]["id"]
    assert client.post(f"/api/v1/my/characters/{cid}/train/quote", headers=H).status_code == 400


def test_enqueue_failure_and_failed_training_refund_once(maker, monkeypatch):
    monkeypatch.setenv("CHARACTER_LORA_PROVIDER_USD", "1.00")
    client = _client()
    cid = _real_face(client, monkeypatch).json()["data"]["id"]
    credits = client.post(f"/api/v1/my/characters/{cid}/train/quote", headers=H).json()["data"]["credits"]
    _funded(maker, credits)

    def boom(job_id, request_id):
        raise RuntimeError("broker down")

    monkeypatch.setattr(hub, "enqueue_training", boom)
    res = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": credits}, headers=H)
    assert res.status_code == 502
    with maker() as s:
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == credits
    # A worker-side failure is refunded by the sweep, once.
    monkeypatch.setattr(hub, "enqueue_training", lambda job_id, request_id: "celery-2")
    job_id = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": credits},
                         headers=H).json()["data"]["job_id"]
    with maker() as s:
        s.get(Job, job_id).state = -1
        s.commit()
    uid = _uid(maker)
    with maker() as s:
        assert hub.refund_failed_trainings(s) == 1
        s.commit()
    with maker() as s:
        assert hub.refund_failed_trainings(s) == 0
        s.commit()
    with maker() as s:
        assert pc.balance(s, uid, pc.KIND_AI_VIDEO) == credits


# --------------------------------------------------------------------------- #
# Identity score per render (preset x model)
# --------------------------------------------------------------------------- #
def _png(color, box=None) -> bytes:
    image = Image.new("RGB", (128, 128), color)
    if box:
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                image.putpixel((x, y), (250, 250, 250))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_appearance_score_is_higher_for_the_same_look():
    ref = _png((200, 80, 40), (40, 40, 90, 90))
    same = _png((198, 82, 42), (42, 40, 92, 90))
    other = _png((20, 60, 200), (0, 0, 20, 20))
    assert hub.appearance_score(ref, same) > 0.9
    assert hub.appearance_score(ref, other) < hub.appearance_score(ref, same)


def test_scores_are_recorded_for_three_presets_and_three_models(maker, monkeypatch):
    client = _client()
    cid = _real_face(client, monkeypatch).json()["data"]["id"]
    ref = _png((200, 80, 40), (40, 40, 90, 90))
    monkeypatch.setattr(hub, "fetch_bytes", lambda key: ref)
    uid = _uid(maker)
    for preset in ("melt-away", "levitate", "hero-orbit"):
        for model in ("draft-a", "draft-b", "final-c"):
            with maker() as s:
                job = Job(user_id=uid, kind="broll_gen", state=1, params={}, poster_key=f"jobs/{preset}/{model}.jpg")
                s.add(job)
                s.commit()
                job_id = job.id
            res = client.post(f"/api/v1/my/characters/{cid}/identity-scores",
                              json={"job_id": job_id, "preset_id": preset, "model": model}, headers=H)
            assert res.status_code == 200, res.text
    scores = client.get(f"/api/v1/my/characters/{cid}/identity-scores", headers=H).json()["data"]
    assert len(scores["scores"]) == 9
    assert {s["method"] for s in scores["scores"]} == {hub.SCORE_METHOD}
    assert scores["summary"]["presets"] == 3 and scores["summary"]["models"] == 3
    assert scores["summary"]["min"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Brand kits: accepted by every preset
# --------------------------------------------------------------------------- #
def _kit(maker) -> str:
    with maker() as s:
        kit = UserPreset(user_id=_uid(maker), name="Cafe", config={
            "voice_name": "en-US-AriaNeural", "caption_style": "bold_violet", "music_id": "lofi-1",
            "brand": {"name": "Corner Cafe", "logo": "uploads/u/logo.png", "colors": ["#6b3fa0", "#f5e6c8"]},
        })
        s.add(kit)
        s.commit()
        return kit.id


def test_product_shots_accept_only_your_uploads(maker):
    client = _client()
    kit_id = _kit(maker)
    bad = client.put(f"/api/v1/my/brands/{kit_id}/product-shots",
                     json={"keys": ["uploads/someone-else/p.jpg"]}, headers=H)
    assert bad.status_code == 403
    ok = client.put(f"/api/v1/my/brands/{kit_id}/product-shots", json={"keys": ["uploads/u/p1.jpg"]}, headers=H)
    assert ok.status_code == 200, ok.text
    kits = client.get("/api/v1/my/brands", headers=H).json()["data"]["brands"]
    assert kits[0]["product_shots"] == ["uploads/u/p1.jpg"]
    assert kits[0]["colors"] == ["#6b3fa0", "#f5e6c8"] and kits[0]["logo"] == "uploads/u/logo.png"
    with maker() as s:
        assert s.get(UserPreset, kit_id).config["voice_name"] == "en-US-AriaNeural"  # nothing else changed


def test_every_preset_accepts_the_brand_kit(maker):
    kit_id = _kit(maker)
    with maker() as s:
        brand = hub.brand_for_user(s, _uid(maker), kit_id)
    brand = {**brand, "product_shots": ["uploads/u/p1.jpg"]}
    for preset in presets_catalog.all_presets():
        plan = presets_service.resolve(preset.id, subject="our new roast", brand=brand)
        body = plan["body"]
        if preset.kind == "filter":
            params = body["params"]
            assert params["caption_style"] == "bold_violet" and params["voice_name"] == "en-US-AriaNeural"
            assert params["watermark_key"] == "uploads/u/logo.png" and params["watermark_enabled"] is True
        else:
            assert "Corner Cafe" in body["prompt"] and "#6b3fa0" in body["prompt"]
            if preset.needs_image:
                assert body["image_key"] == "uploads/u/p1.jpg"  # the product shot fills the image slot


def test_model_presets_accept_a_character(maker, monkeypatch):
    client = _client()
    cid = _real_face(client, monkeypatch).json()["data"]["id"]
    with maker() as s:
        character = hub.character_for_user(s, _uid(maker), cid)
    plan = presets_service.resolve("levitate", subject="on a beach", character=character)
    assert plan["body"]["prompt"].startswith("Me")
    assert plan["body"]["image_key"] == PHOTOS[0]
    assert plan["character_id"] == cid


# --------------------------------------------------------------------------- #
# Migration
# --------------------------------------------------------------------------- #
def test_migration_is_idempotent_on_a_scratch_database():
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    path = REPO / "migrations" / "versions" / "20260930_1000_f3b5d7e9a1c2_character_hub.py"
    spec = importlib.util.spec_from_file_location("hub_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (module.revision, module.down_revision) == ("f3b5d7e9a1c2", "e2a4c6d8f0b1")
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()
            module.upgrade()
        assert {"character_hub_profiles", "character_identity_scores"} <= set(inspect(conn).get_table_names())
        with Operations.context(ctx):
            module.downgrade()
        assert "character_hub_profiles" not in set(inspect(conn).get_table_names())


@pytest.mark.integration
def test_a_render_without_a_poster_is_scored_from_a_video_frame(maker, monkeypatch, tmp_path):
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    video = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xC85028:s=128x128:d=2",
                    "-pix_fmt", "yuv420p", str(video)], check=True, timeout=60)
    ref = _png((200, 80, 40))
    blobs = {PHOTOS[0]: ref, "jobs/v/final.mp4": video.read_bytes()}
    client = _client()
    cid = _real_face(client, monkeypatch).json()["data"]["id"]
    monkeypatch.setattr(hub, "fetch_bytes", lambda key: blobs[key])
    with maker() as s:
        job = Job(user_id=_uid(maker), kind="broll_gen", state=1, params={}, result_key="jobs/v/final.mp4")
        s.add(job)
        s.commit()
        job_id = job.id
    res = client.post(f"/api/v1/my/characters/{cid}/identity-scores",
                      json={"job_id": job_id, "preset_id": "levitate", "model": "draft"}, headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["score"] > 0.8
