"""Wave P PM1.3 (MH3): the opt-in gallery and Recreate.

Only opt-in items appear; an item keeps the preset id and safe params, never
the script, prompt or anyone's references. Recreate opens Create prefilled;
``remix_count`` goes up once per kept remix. A takedown hides the item at
once (the public list is cached for at most 30 s). The MN5 provenance tag is
read, never written. The landing wall can pull up to 6 owner-approved items.
"""

from __future__ import annotations

import hashlib
import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.compliance import takedown
from app.domains.gallery import router as gallery_router
from app.domains.gallery import service
from app.domains.gallery.models import GalleryItem, GalleryRemix
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.exception import HttpException
from app.utils import utils

OWNER_KEY = "gallery-owner-key"
FAN_KEY = "gallery-fan-key"
REPO = Path(__file__).resolve().parents[2]

PRIVATE_PARAMS = {
    "video_script": "PRIVATE SCRIPT the owner typed",
    "video_subject": "private subject line",
    "source_url": "https://private.example/page",
    "avatar_id": "my-own-face",
    "voice_name": "elevenlabs:clone123",
    "screen_recording_key": "uploads/u1/screen.mp4",
    "voiceover_key": "uploads/u1/voice.mp3",
    "webhook_secret": "shh",
}
SAFE_PARAMS = {"style": "pov_text", "camera_motion": "crash_zoom_in", "effects": ["glitch"],
               "caption_style": "clean_white", "layout": "captions_only", "background_id": "block-runner"}


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
    monkeypatch.setattr(gallery_router, "get_session", _session)
    monkeypatch.setattr(service, "media_url", lambda key: f"https://signed.example/{key}" if key else "")
    with factory() as s:
        for key, email in ((OWNER_KEY, "owner@example.com"), (FAN_KEY, "fan@example.com")):
            s.add(User(email=email, api_key_hash=hashlib.sha256(key.encode()).hexdigest()))
        s.commit()
    return factory


def _user_id(maker, email):
    with maker() as s:
        return s.query(User).filter_by(email=email).one().id


def _job(maker, email="owner@example.com", *, state=1, params=None, kind="avatar_reel") -> str:
    with maker() as s:
        job = Job(user_id=_user_id(maker, email), kind=kind, state=state,
                  params={**SAFE_PARAMS, **PRIVATE_PARAMS, **(params or {})},
                  result_key="jobs/x/final.mp4", preview_key="jobs/x/preview.mp4", poster_key="jobs/x/poster.jpg")
        s.add(job)
        s.commit()
        return job.id


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(gallery_router.router)

    def handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code,
                            content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, handler)
    return TestClient(app)


def _publish(client, job_id, key=OWNER_KEY, title="Espresso bar opening"):
    return client.post("/api/v1/gallery", json={"job_id": job_id, "title": title}, headers={"x-api-key": key})


# --------------------------------------------------------------------------- #
# Opt-in publish: preset id + safe params only
# --------------------------------------------------------------------------- #
def test_nothing_appears_until_the_owner_opts_in(maker):
    _job(maker)
    client = _client()
    assert client.get("/api/v1/gallery").json()["data"]["items"] == []


def test_publish_stores_the_preset_and_safe_params_only(maker):
    job_id = _job(maker, params={"preset_run": {"preset_id": "crash-zoom", "opened_at": "2026-09-30T10:00:00+00:00"}})
    client = _client()
    res = _publish(client, job_id)
    assert res.status_code == 200, res.text
    with maker() as s:
        item = s.query(GalleryItem).one()
    assert item.preset_id == "shelf:crash-zoom"
    assert item.safe_params == {**{k: v for k, v in SAFE_PARAMS.items()}}
    listing = client.get("/api/v1/gallery").json()["data"]["items"]
    assert [i["id"] for i in listing] == [item.id]
    blob = str(listing) + str(client.get(f"/api/v1/gallery/{item.id}").json())
    for secret in PRIVATE_PARAMS.values():
        assert secret not in blob
    assert listing[0]["preview_url"] == "https://signed.example/jobs/x/preview.mp4"


def test_style_reel_without_a_shelf_preset_uses_its_style_as_preset(maker):
    job_id = _job(maker)
    _publish(_client(), job_id)
    with maker() as s:
        assert s.query(GalleryItem).one().preset_id == "style:pov_text"


@pytest.mark.parametrize("case", ["foreign", "rendering", "unkept", "blocked", "twice"])
def test_publish_refuses_what_is_not_yours_or_not_ready(maker, case):
    client = _client()
    if case == "foreign":
        job_id = _job(maker)
        assert _publish(client, job_id, key=FAN_KEY).status_code == 404
    elif case == "rendering":
        assert _publish(client, _job(maker, state=4)).status_code == 409
    elif case == "unkept":
        job_id = _job(maker, params={"_keep": {"credits": 1, "workspace_id": None, "kept": False}})
        assert _publish(client, job_id).status_code == 409
    elif case == "blocked":
        job_id = _job(maker)
        with maker() as s:
            s.add(takedown.TakedownReport(job_id=job_id, content_ref=job_id, reason="other",
                                          reporter_email="r@example.com", status=takedown.STATUS_BLOCKED))
            s.commit()
        assert _publish(client, job_id).status_code == 409
    else:
        job_id = _job(maker)
        assert _publish(client, job_id).status_code == 200
        assert _publish(client, job_id).status_code == 200  # idempotent: same item
        with maker() as s:
            assert s.query(GalleryItem).count() == 1


def test_title_is_cleaned_and_checked_for_vendor_names(maker):
    client = _client()
    res = _publish(client, _job(maker), title="Made with Kling and ElevenLabs")
    assert res.status_code == 400


def test_owner_can_unpublish(maker):
    client = _client()
    job_id = _job(maker)
    item_id = _publish(client, job_id).json()["data"]["id"]
    assert client.delete(f"/api/v1/gallery/{item_id}", headers={"x-api-key": FAN_KEY}).status_code == 404
    assert client.delete(f"/api/v1/gallery/{item_id}", headers={"x-api-key": OWNER_KEY}).status_code == 200
    assert client.get("/api/v1/gallery").json()["data"]["items"] == []


# --------------------------------------------------------------------------- #
# Provenance: read, never written
# --------------------------------------------------------------------------- #
def test_item_shows_the_mn5_provenance_without_writing_it(maker, monkeypatch):
    from app.services import provenance

    monkeypatch.setattr(provenance, "tag", lambda *a, **k: pytest.fail("gallery must not write the tag"))
    client = _client()
    job_id = _job(maker)
    item_id = _publish(client, job_id).json()["data"]["id"]
    view = client.get(f"/api/v1/gallery/{item_id}").json()["data"]
    assert view["provenance"] == {"ai_generated": True, "content_id": job_id,
                                  "report_url": provenance.REPORT_URL, "generator": "Menivor"}


# --------------------------------------------------------------------------- #
# Recreate and remix_count
# --------------------------------------------------------------------------- #
def test_recreate_prefills_create_with_the_items_safe_params(maker):
    client = _client()
    item_id = _publish(client, _job(maker)).json()["data"]["id"]
    body = {"subject": "My bakery opening"}
    assert client.post(f"/api/v1/gallery/{item_id}/recreate", json=body).status_code == 401
    res = client.post(f"/api/v1/gallery/{item_id}/recreate", json=body, headers={"x-api-key": FAN_KEY})
    assert res.status_code == 200, res.text
    plan = res.json()["data"]
    assert plan["route"] == "jobs"
    params = plan["body"]["params"]
    assert params["video_subject"] == "My bakery opening"
    assert params["camera_motion"] == "crash_zoom_in" and params["style"] == "pov_text"
    for key in PRIVATE_PARAMS:
        if key != "video_subject":
            assert key not in params


def test_recreate_of_a_shelf_preset_item_uses_the_preset(maker):
    client = _client()
    job_id = _job(maker, params={"preset_run": {"preset_id": "crash-zoom", "opened_at": "2026-09-30T10:00:00+00:00"}})
    item_id = _publish(client, job_id).json()["data"]["id"]
    plan = client.post(f"/api/v1/gallery/{item_id}/recreate", json={"subject": "Tacos"},
                       headers={"x-api-key": FAN_KEY}).json()["data"]
    assert plan["route"] == "jobs" and plan["body"]["params"]["camera_motion"] == "crash_zoom_in"


def test_remix_count_goes_up_once_per_kept_remix(maker):
    client = _client()
    item_id = _publish(client, _job(maker)).json()["data"]["id"]
    remix_job = _job(maker, "fan@example.com", state=4,
                     params={"_keep": {"credits": 1, "workspace_id": None, "kept": False}})
    link = client.post(f"/api/v1/gallery/{item_id}/remixes", json={"job_id": remix_job},
                       headers={"x-api-key": FAN_KEY})
    assert link.status_code == 200, link.text
    # Rendering, then finished but not kept: not counted.
    with maker() as s:
        assert service.settle_remixes(s) == 0
        s.get(Job, remix_job).state = 1
        s.commit()
    with maker() as s:
        assert service.settle_remixes(s) == 0
        job = s.get(Job, remix_job)
        job.params = {**job.params, "_keep": {"credits": 1, "workspace_id": None, "kept": True}}
        s.commit()
    view = client.get(f"/api/v1/gallery/remixes/{remix_job}", headers={"x-api-key": FAN_KEY}).json()["data"]
    assert view["counted"] is True
    with maker() as s:
        assert service.settle_remixes(s) == 0  # already counted
        assert s.get(GalleryItem, item_id).remix_count == 1
    # Linking the same job again changes nothing.
    client.post(f"/api/v1/gallery/{item_id}/remixes", json={"job_id": remix_job}, headers={"x-api-key": FAN_KEY})
    with maker() as s:
        assert s.query(GalleryRemix).count() == 1


def test_self_remix_and_foreign_jobs_do_not_count(maker):
    client = _client()
    item_id = _publish(client, _job(maker)).json()["data"]["id"]
    own = _job(maker)
    assert client.post(f"/api/v1/gallery/{item_id}/remixes", json={"job_id": own},
                       headers={"x-api-key": OWNER_KEY}).status_code == 409
    fans = _job(maker, "fan@example.com")
    assert client.post(f"/api/v1/gallery/{item_id}/remixes", json={"job_id": fans},
                       headers={"x-api-key": OWNER_KEY}).status_code == 404


# --------------------------------------------------------------------------- #
# Takedown hides at once; the public list is edge-cached for at most 30 s
# --------------------------------------------------------------------------- #
def test_takedown_block_hides_the_item_immediately(maker):
    client = _client()
    job_id = _job(maker)
    item_id = _publish(client, job_id).json()["data"]["id"]
    with maker() as s:
        report = takedown.TakedownReport(job_id=job_id, content_ref=job_id, reason="copyright",
                                         reporter_email="r@example.com", status=takedown.STATUS_OPEN)
        s.add(report)
        s.flush()
        takedown.block(s, report.id, "staff:1")
        s.commit()
    with maker() as s:
        assert s.get(GalleryItem, item_id).hidden_at is not None
    assert client.get("/api/v1/gallery").json()["data"]["items"] == []
    assert client.get(f"/api/v1/gallery/{item_id}").status_code == 404


def test_public_list_cache_is_short_enough_for_a_60s_takedown(maker):
    res = _client().get("/api/v1/gallery")
    cache = res.headers["cache-control"]
    assert "s-maxage=30" in cache and "public" in cache


# --------------------------------------------------------------------------- #
# Landing wall: up to 6 owner-approved items
# --------------------------------------------------------------------------- #
def test_wall_serves_only_owner_approved_items_up_to_six(maker, monkeypatch):
    client = _client()
    ids = [_publish(client, _job(maker), title=f"Item {n}").json()["data"]["id"] for n in range(8)]
    assert client.get("/api/v1/gallery/wall").json()["data"]["items"] == []
    monkeypatch.setattr(gallery_router, "_require_staff", lambda request, request_id: None)
    for item_id in ids:
        assert client.post(f"/api/v1/admin/gallery/{item_id}/wall", json={"approved": True}).status_code == 200
    wall = client.get("/api/v1/gallery/wall").json()["data"]["items"]
    assert len(wall) == 6
    assert all(item["preview_url"].endswith("preview.mp4") for item in wall)


def test_wall_approval_is_staff_only(maker):
    client = _client()
    item_id = _publish(client, _job(maker)).json()["data"]["id"]
    res = client.post(f"/api/v1/admin/gallery/{item_id}/wall", json={"approved": True},
                      headers={"x-api-key": OWNER_KEY})
    assert res.status_code in (403, 404)


# --------------------------------------------------------------------------- #
# Migration: idempotent, one head
# --------------------------------------------------------------------------- #
def test_migration_is_idempotent_on_a_scratch_database():
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    path = REPO / "migrations" / "versions" / "20260930_0900_e2a4c6d8f0b1_gallery_items.py"
    spec = importlib.util.spec_from_file_location("gallery_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (module.revision, module.down_revision) == ("e2a4c6d8f0b1", "d8e1f3a5c7b9")
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()
            module.upgrade()  # second run is a no-op
        tables = set(inspect(conn).get_table_names())
        assert {"gallery_items", "gallery_remixes"} <= tables
        with Operations.context(ctx):
            module.downgrade()
        assert "gallery_items" not in set(inspect(conn).get_table_names())
