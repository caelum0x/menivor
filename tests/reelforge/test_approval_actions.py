"""Approving Wave L items acts on the source (design posts, capture reels, catalog ads).

Runs the real approvals service, producers, image scheduling, reel job
creation (credits ledger) and Ad Studio persistence on in-memory SQLite. Only
the network, R2, the Celery enqueue and connection look-ups are faked. Also
covers the retry format re-check (``app.core.launch.formats``).
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.launch import formats
from app.domains.adstudio.catalog_models import StoreCatalogImport, StoreCatalogProduct
from app.domains.adstudio.models import AdStudioProject, AdVariant
from app.domains.approvals import adapters, producers, reel_jobs, service
from app.domains.approvals import settings as feed_settings
from app.domains.capture.models import CaptureJob
from app.domains.design import service as design_service
from app.domains.design.models import DesignDoc
from app.domains.publishing.extended import images as image_media
from app.domains.publishing.extended import posts as post_service
from app.domains.publishing.extended.catalog import AVAILABLE
from app.domains.publishing.extended.models import PlatformPost
from app.models import const
from app.models.db import marketplace, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.db.repositories import CreditRepository


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    for module in (service, adapters, producers, reel_jobs, image_media, post_service, design_service, feed_settings):
        monkeypatch.setattr(module, "get_session", _session)
    monkeypatch.setattr("app.domains.adstudio.store_catalog.service.adstudio_service.get_session", _session,
                        raising=False)
    enqueued: list[str] = []
    monkeypatch.setattr(post_service, "_enqueue", lambda post_id: enqueued.append(post_id))
    # Approving a publishing source follows the launch gate; these tests run it open.
    monkeypatch.setattr(service, "_publishing_open", lambda: True)
    with _session() as s:
        user = User(email="owner@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest(), credits=0)
        s.add(user)
        s.flush()
        uid = user.id
        CreditRepository(s).grant(uid, 5, reason="signup")
    return SimpleNamespace(session=_session, user=uid, enqueued=enqueued)


def _balance(db) -> int:
    with db.session() as s:
        return CreditRepository(s).balance(db.user)


def _pending(db, source: str) -> dict:
    listing = service.list_items(db.user, source=source)
    assert listing["items"], listing
    return listing["items"][0]


# --------------------------------------------------------------------------- #
# design_publish
# --------------------------------------------------------------------------- #
@pytest.fixture()
def design(db, monkeypatch):
    monkeypatch.setattr(image_media, "server_availability", lambda platform: (AVAILABLE, ""))
    monkeypatch.setattr(image_media, "_oauth_state", lambda user_id, platform: "")
    monkeypatch.setattr(image_media, "_instagram_ready", lambda user_id: "")
    monkeypatch.setattr(image_media, "_channel_destinations",
                        lambda user_id, kind, ids: ([image_media.Destination(kind, "chan1", "Launch channel")], ""))
    monkeypatch.setattr(image_media, "jpeg_copies", lambda keys, r2=None: [k.replace(".png", ".jpg") for k in keys])
    with db.session() as s:
        doc = DesignDoc(user_id=db.user, title="Launch", size_preset="square", canvas_json={"pages": [{}, {}]},
                        status="exported", exported_keys=["uploads/d-1.png", "uploads/d-2.png"])
        s.add(doc)
        s.flush()
        return doc.id


def test_approving_a_design_schedules_image_posts_per_platform(db, design):
    when = datetime.now(timezone.utc) + timedelta(days=2)
    out = design_service.schedule(db.user, design, platforms=["instagram", "linkedin", "telegram", "tiktok"],
                                  caption="Launch week #drills", scheduled_at=when)
    item = out["approval"]
    decided = service.decide(db.user, item["id"], "approve", edits={"caption": "Launch week, edited"})
    result = decided["item"]["result"]
    assert decided["item"]["status"] == "executed" and result["action"] == "design_scheduled"
    assert sorted(p["platform"] for p in result["posts"]) == ["instagram", "linkedin", "telegram"]
    assert result["skipped"] == [{"platform": "tiktok", "message": image_media.UNSUPPORTED["tiktok"]}]
    with db.session() as s:
        rows = {r.platform: r for r in s.query(PlatformPost).all()}
    assert rows["linkedin"].progress["image_keys"] == ["uploads/d-1.png", "uploads/d-2.png"]
    assert rows["instagram"].progress["image_keys"] == ["uploads/d-1.jpg", "uploads/d-2.jpg"]
    assert rows["telegram"].target_id == "chan1" and rows["linkedin"].job_id == ""
    assert rows["instagram"].text == "Launch week, edited"
    assert all(r.status == "scheduled" for r in rows.values())
    assert db.enqueued == []  # scheduled two days ahead: the due-runner posts it then


def test_design_with_only_unsupported_platforms_fails_clearly_and_reject_unschedules(db, design):
    item = design_service.schedule(db.user, design, platforms=["youtube", "app_store"])["approval"]
    with pytest.raises(service.ApprovalError) as exc:
        service.decide(db.user, item["id"], "approve")
    assert exc.value.status_code == 409
    assert "YouTube does not accept image posts" in exc.value.item["error"]
    assert exc.value.item["status"] == "failed"
    with db.session() as s:
        assert s.query(PlatformPost).count() == 0
    rejected = service.decide(db.user, item["id"], "reject")
    assert rejected["item"]["status"] == "rejected"
    with db.session() as s:
        assert s.get(DesignDoc, design).status == "exported"
    # Re-scheduling after a rejection reopens the same item for a new decision.
    again = design_service.schedule(db.user, design, platforms=["linkedin"])["approval"]
    assert again["id"] == item["id"] and again["status"] == "pending"


def test_design_posted_now_when_approved_after_its_slot(db, design):
    item = design_service.schedule(db.user, design, platforms=["linkedin"])["approval"]
    service.decide(db.user, item["id"], "approve")
    assert len(db.enqueued) == 1


# --------------------------------------------------------------------------- #
# capture_publish
# --------------------------------------------------------------------------- #
@pytest.fixture()
def capture(db, monkeypatch):
    started: list[tuple[str, object]] = []
    import sys

    monkeypatch.setitem(sys.modules, "app.workers.pipeline",
                        SimpleNamespace(start_pipeline=lambda jid, params: started.append((jid, params)) or "task-1"))
    with db.session() as s:
        row = CaptureJob(user_id=db.user, source_url="https://acme.test", source_kind="website", status="succeeded",
                         options={"formats": ["9:16", "16:9"]}, screenshots=[],
                         meta={"page": {"title": "Acme drills", "description": "Cordless drills. Built to last."},
                               "outputs": [{"aspect": "9:16", "key": "uploads/cap-916.mp4", "duration_ms": 20000},
                                           {"aspect": "16:9", "key": "uploads/cap-169.mp4", "duration_ms": 20000}]})
        s.add(row)
        s.flush()
        return SimpleNamespace(id=row.id, started=started)


def _opt_in(db, *sources: str) -> None:
    feed_settings.update_settings(db.user, {source: True for source in sources})


def test_capture_and_catalog_suggestions_are_off_by_default_and_toggle(db, capture):
    # Default OFF: a finished capture does not become a pending item.
    assert service.list_items(db.user, source="capture_publish")["total"] == 0
    view = feed_settings.get_settings(db.user)
    assert view["auto_sources"] == {"capture_publish": False, "catalog_import": False} and view["stored"] is False
    # Opting in surfaces it; opting out again expires the pending suggestion.
    assert feed_settings.update_settings(db.user, {"capture_publish": True})["auto_sources"]["capture_publish"]
    item = _pending(db, "capture_publish")
    after = feed_settings.update_settings(db.user, {"capture_publish": False})
    assert after["auto_sources"] == {"capture_publish": False, "catalog_import": False}
    assert service.list_items(db.user, source="capture_publish")["total"] == 0
    assert service.get_item(db.user, item["id"])["status"] == "expired"
    with pytest.raises(feed_settings.SettingsError):
        feed_settings.update_settings(db.user, {"design_publish": False})


def test_approving_a_capture_queues_captions_reels_once(db, capture):
    _opt_in(db, "capture_publish")
    item = _pending(db, "capture_publish")
    assert item["payload"]["credits"] == 2 and item["payload"]["aspects"] == ["9:16", "16:9"]
    out = service.decide(db.user, item["id"], "approve", edits={"script": "Meet Acme.\nDrills that last."})
    result = out["item"]["result"]
    assert out["item"]["status"] == "executed" and result["action"] == "reels_queued" and result["credits"] == 2
    assert _balance(db) == 3
    with db.session() as s:
        jobs = s.query(Job).all()
        meta = s.get(CaptureJob, capture.id).meta
    keys = sorted(j.params["screen_recording_key"] for j in jobs)
    assert keys == ["uploads/cap-169.mp4", "uploads/cap-916.mp4"]
    assert all(j.params["layout"] == "captions_only" and j.params["video_script"].startswith("Meet Acme")
               for j in jobs)
    assert all(j.params["source_context"] == {"kind": "capture", "id": capture.id} for j in jobs)
    assert meta["approval"]["job_ids"] == result["job_ids"] and len(capture.started) == 2
    # The capture no longer shows as pending, and a replayed approval never debits again.
    assert service.list_items(db.user, source="capture_publish")["total"] == 0
    assert producers._approve_capture(db.user, capture.id, {})["replayed"] is True
    assert _balance(db) == 3


def test_capture_approval_without_credits_creates_nothing(db, capture):
    with db.session() as s:
        CreditRepository(s).debit(db.user, 5, "drain", "drain")
    _opt_in(db, "capture_publish")
    item = _pending(db, "capture_publish")
    with pytest.raises(service.ApprovalError) as exc:
        service.decide(db.user, item["id"], "approve")
    assert exc.value.status_code == 402 and exc.value.item["status"] == "failed"
    with db.session() as s:
        assert s.query(Job).count() == 0
    assert capture.started == []


def test_capture_reel_refused_when_format_is_locked(monkeypatch):
    params = SimpleNamespace(layout="pip", avatar_provider="heygen", voiceover_key="", screen_recording_key="k",
                             voice_name="en-US-AriaNeural-Female", video_script="Hi")
    monkeypatch.setattr(formats, "avatar_provider_enabled", lambda provider="heygen": False)
    with pytest.raises(adapters.ApprovalExecError) as exc:
        reel_jobs.check_available(params)
    assert exc.value.status_code == 402 and "AI avatars are not switched on" in str(exc.value)


# --------------------------------------------------------------------------- #
# catalog_import
# --------------------------------------------------------------------------- #
def test_approving_a_catalog_product_creates_the_project_and_default_ads(db, monkeypatch):
    stored = [{"key": "uploads/prod-1.jpg", "origin_url": "https://cdn.test/a.jpg", "width": 800, "height": 800,
               "size": 100}]
    monkeypatch.setattr("app.domains.adstudio.service.store_remote_images", lambda urls: stored)
    rendered: list[str] = []
    monkeypatch.setattr("app.domains.adstudio.worker.dispatch_render", lambda vid: rendered.append(vid))
    with db.session() as s:
        imp = StoreCatalogImport(user_id=db.user, provider="shopify", store_url="https://shop.test",
                                 store_name="Acme Store", status="succeeded", options={})
        s.add(imp)
        s.flush()
        product = StoreCatalogProduct(import_id=imp.id, user_id=db.user, external_id="101", title="Linen Shirt",
                                      description="Breathable linen.", price_minor=4990, currency="USD",
                                      url="https://shop.test/products/linen-shirt",
                                      image_urls=["https://cdn.test/a.jpg"], tags=[], raw={"position": 1})
        s.add(product)
        s.flush()
        product_id = product.id
    _opt_in(db, "catalog_import")
    item = _pending(db, "catalog_import")
    assert item["external_ref"] == product_id and "49.90 USD" in item["summary"] and item["risk"] == "low"
    out = service.decide(db.user, item["id"], "approve")
    result = out["item"]["result"]
    assert out["item"]["status"] == "executed" and result["action"] == "adstudio_project_created"
    with db.session() as s:
        project = s.get(AdStudioProject, result["project_id"])
        variants = s.query(AdVariant).filter(AdVariant.project_id == project.id).all()
        assert s.get(StoreCatalogProduct, product_id).adstudio_project_id == project.id
    assert project.title == "Linen Shirt" and project.user_id == db.user
    assert len(variants) == producers.DEFAULT_ANGLES
    assert {v.format for v in variants} == {"showcase"} and {v.aspect for v in variants} == {"9:16"}
    assert sorted(rendered) == sorted(result["variant_ids"])
    # The product is no longer offered for approval.
    assert service.list_items(db.user, source="catalog_import")["total"] == 0


# --------------------------------------------------------------------------- #
# Format availability (free tier) + retry re-check
# --------------------------------------------------------------------------- #
_CAPS_FREE = {"avatar": False, "script_llm": False, "premium_voice": False, "free_tts": True, "ai_broll": False}


def _p(**kw):
    base = dict(layout="captions_only", avatar_provider="", voiceover_key="", screen_recording_key="",
                voice_name="", video_script="", translate_source_script="")
    base.update(kw)
    return SimpleNamespace(**base)


def test_params_lock_matches_the_free_tier():
    own_video = _p(screen_recording_key="uploads/v.mp4", video_script="Hello")
    assert formats.params_lock(own_video, needs_script_llm=False, capabilities=_CAPS_FREE) is None
    avatar = _p(layout="pip", video_script="Hello", voice_name="en-US-AriaNeural-Female")
    assert formats.params_lock(avatar, needs_script_llm=False, capabilities=_CAPS_FREE)[0] == "avatar_reel"
    faceless = _p(voice_name="en-US-AriaNeural-Female")
    assert formats.params_lock(faceless, needs_script_llm=True, capabilities=_CAPS_FREE)[0] == "generated_script"
    typed = _p(voice_name="elevenlabs:abc", video_script="Hi")
    assert formats.params_lock(typed, needs_script_llm=False, capabilities=_CAPS_FREE) is None
    no_tts = {**_CAPS_FREE, "free_tts": False}
    assert formats.params_lock(typed, needs_script_llm=False, capabilities=no_tts)[0] == "faceless_free_voice"
    assert formats.params_lock(typed, needs_script_llm=False,
                               capabilities={**no_tts, "premium_voice": True}) is None
    byov = _p(voiceover_key="uploads/vo.mp3", screen_recording_key="uploads/v.mp4")
    assert formats.needs_tts(byov) is False


def test_reuse_persisted_script_only_when_no_typed_script():
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class P:
        video_script: str = ""
        translate_source_script: str = ""

    assert formats.reuse_persisted_script(P(), "Written before").video_script == "Written before"
    assert formats.reuse_persisted_script(P(video_script="Typed"), "Other").video_script == "Typed"
    assert formats.reuse_persisted_script(P(translate_source_script="x"), "S").video_script == ""
    assert formats.reuse_persisted_script(P(), "").video_script == ""


def test_retry_of_an_old_avatar_job_is_refused_before_any_debit(monkeypatch):
    from fastapi import FastAPI
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient

    import app.controllers.v1.jobs as jobs_mod
    from app.models.db.repositories import JobRepository
    from app.models.exception import HttpException
    from app.utils import utils

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    retries: list = []
    pipeline = SimpleNamespace(retry_pipeline=lambda *a: retries.append(a) or "t", start_pipeline=lambda *a: "t")
    monkeypatch.setattr(jobs_mod, "get_session", _session)
    monkeypatch.setattr(jobs_mod, "_import_pipeline", lambda rid: pipeline)
    monkeypatch.setattr(formats, "avatar_provider_enabled", lambda provider="heygen": False)
    key = "retrykey"
    with _session() as s:
        user = User(email="r@example.com", api_key_hash=hashlib.sha256(key.encode()).hexdigest(), credits=0)
        s.add(user)
        s.flush()
        uid = user.id
        CreditRepository(s).grant(uid, 5, reason="signup")
        avatar = JobRepository(s).create(user_id=uid, kind="avatar_reel",
                                         params={"video_subject": "cats", "video_script": "Cats are great."})
        JobRepository(s).mark_failed(avatar.id, "avatar", "heygen key removed")
        free = JobRepository(s).create(user_id=uid, kind="avatar_reel", params={
            "video_subject": "cats", "layout": "captions_only", "screen_recording_key": "uploads/v.mp4"})
        JobRepository(s).mark_failed(free.id, "compose", "boom")
        JobRepository(s).set_script(free.id, "A script the job already wrote.")
        ids = (avatar.id, free.id)

    app = FastAPI()
    app.include_router(jobs_mod.router)
    app.add_exception_handler(HttpException, lambda request, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    client = TestClient(app)
    headers = {"x-api-key": key}

    locked = client.post(f"/api/v1/jobs/{ids[0]}/retry", headers=headers)
    assert locked.status_code == 402, locked.text
    assert locked.json()["data"]["code"] == "format_locked" and retries == []
    with _session() as s:
        assert CreditRepository(s).balance(uid) == 5
        assert s.get(Job, ids[0]).state == const.TASK_STATE_FAILED

    ok = client.post(f"/api/v1/jobs/{ids[1]}/retry", headers=headers)
    assert ok.status_code == 200, ok.text
    assert retries and retries[0][1].video_script == "A script the job already wrote."
    with _session() as s:
        assert CreditRepository(s).balance(uid) == 4
