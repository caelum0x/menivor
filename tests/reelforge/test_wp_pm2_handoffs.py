"""Wave P1 hand-offs closed in P2 (DEPLOY-CHECKLIST-WAVE-P1 section C).

* P-M2: a gallery remix counts only when it is a real Recreate of the item
  (made after the item was published, linked right after create, carrying the
  item's recipe); the landing wall reads ``galleryWallMedia`` (web test).
* P-M3: ``menivor.lora.train`` reaches ``railyard_meter_outbox`` when a
  My-characters training starts. SQLite proves the code path with the outbox
  table present; ``MENIVOR_PG_TEST_URL`` (a scratch Postgres migrated to head
  with ``alembic upgrade head``) proves it on Postgres.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.gallery import service as gallery
from app.domains.gallery.models import GalleryItem, GalleryRemix
from app.models.db.models import Job

from tests.reelforge.test_wp_pm1_3_gallery import (  # noqa: F401 - fixture reuse
    FAN_KEY,
    _client,
    _job,
    _publish,
    maker,
)


def _link(client, item_id, job_id):
    return client.post(f"/api/v1/gallery/{item_id}/remixes", json={"job_id": job_id},
                       headers={"x-api-key": FAN_KEY})


def _kept(extra=None):
    return {"_keep": {"credits": 1, "workspace_id": None, "kept": True}, **(extra or {})}


def _age(maker, job_id, delta):  # noqa: F811 - fixture name reused as a parameter
    with maker() as s:
        job = s.get(Job, job_id)
        job.created_at = datetime.now(timezone.utc) - delta
        s.commit()


# --------------------------------------------------------------------------- #
# P-M2: only a real Recreate counts
# --------------------------------------------------------------------------- #
def test_a_finished_job_with_another_recipe_is_not_a_remix(maker):  # noqa: F811
    client = _client()
    item_id = _publish(client, _job(maker)).json()["data"]["id"]
    other = _job(maker, "fan@example.com", params=_kept({"style": "story_time", "camera_motion": "none",
                                                          "effects": []}))
    res = _link(client, item_id, other)
    assert res.status_code == 409
    assert res.json()["data"]["code"] == "not_a_recreate"
    with maker() as s:
        assert s.query(GalleryRemix).count() == 0


def test_a_job_made_before_the_item_was_published_is_not_a_remix(maker):  # noqa: F811
    client = _client()
    item_id = _publish(client, _job(maker)).json()["data"]["id"]
    old = _job(maker, "fan@example.com", params=_kept())
    with maker() as s:
        item = s.get(GalleryItem, item_id)
        job = s.get(Job, old)
        job.created_at = (item.published_at if item.published_at.tzinfo
                          else item.published_at.replace(tzinfo=timezone.utc)) - timedelta(minutes=5)
        s.commit()
    assert _link(client, item_id, old).status_code == 409


def test_a_late_link_is_not_a_remix(maker):  # noqa: F811
    client = _client()
    item_id = _publish(client, _job(maker)).json()["data"]["id"]
    late = _job(maker, "fan@example.com", params=_kept())
    with maker() as s:
        item = s.get(GalleryItem, item_id)
        item.published_at = datetime.now(timezone.utc) - timedelta(hours=3)
        s.commit()
    _age(maker, late, gallery.REMIX_LINK_WINDOW + timedelta(minutes=1))
    assert _link(client, item_id, late).status_code == 409


def test_a_real_recreate_still_counts_once(maker):  # noqa: F811
    client = _client()
    item_id = _publish(client, _job(maker)).json()["data"]["id"]
    remix = _job(maker, "fan@example.com", params=_kept())
    assert _link(client, item_id, remix).status_code == 200
    with maker() as s:
        assert gallery.settle_remixes(s) == 1
        s.commit()
    with maker() as s:
        assert s.get(GalleryItem, item_id).remix_count == 1


def test_a_shelf_item_counts_a_job_started_from_the_same_preset(maker):  # noqa: F811
    client = _client()
    run = {"preset_run": {"preset_id": "crash-zoom", "opened_at": "2026-09-30T10:00:00+00:00"}}
    item_id = _publish(client, _job(maker, params=run)).json()["data"]["id"]
    with maker() as s:
        assert s.get(GalleryItem, item_id).preset_id == "shelf:crash-zoom"
    same = _job(maker, "fan@example.com", params=_kept({"style": "other", **run}))
    assert _link(client, item_id, same).status_code == 200
    different = _job(maker, "fan@example.com",
                     params=_kept({"preset_run": {"preset_id": "orbit", "opened_at": "2026-09-30T10:00:00+00:00"},
                                   "camera_motion": "none", "effects": []}))
    assert _link(client, item_id, different).status_code == 409


def test_settlement_rechecks_the_recipe(maker):  # noqa: F811
    """A remix row whose job no longer carries the recipe is never counted."""
    client = _client()
    item_id = _publish(client, _job(maker)).json()["data"]["id"]
    remix = _job(maker, "fan@example.com", params=_kept())
    assert _link(client, item_id, remix).status_code == 200
    with maker() as s:
        job = s.get(Job, remix)
        job.params = {**job.params, "style": "changed_later"}
        s.commit()
    with maker() as s:
        assert gallery.settle_remixes(s) == 0


# --------------------------------------------------------------------------- #
# P-M3: the LoRA training meter reaches the outbox
# --------------------------------------------------------------------------- #
def _hub_flow(factory, monkeypatch, email: str) -> tuple[str, str]:
    """Run the real hub routes for a funded real-face training; returns (user id, job id)."""
    from fastapi import FastAPI
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient

    import app.controllers.v1.jobs as jobs_mod
    import app.models.db.base as db_base
    from app.domains.characters import hub
    from app.models.db.models import User
    from app.models.exception import HttpException
    from app.services.billing import premium_credits as pc
    from app.utils import utils

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

    key = f"pm3-{uuid.uuid4().hex}"
    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(jobs_mod, "get_session", _session)
    monkeypatch.setattr(hub, "get_session", _session)
    monkeypatch.setattr(hub, "require_owned", lambda session, user_id, k: k.startswith("uploads/u/"))
    monkeypatch.setattr(hub, "locked_passports", lambda session, user_id: [
        {"passport_id": "pp_1", "version": 2, "kind": "identity", "content_digest": "d", "status": "locked"}])
    monkeypatch.setattr(hub, "enqueue_training", lambda job_id, request_id: "celery-1")
    monkeypatch.setenv("REELFORGE_VOICE_VERIFY_SECRET", "test-secret-for-phrases")
    monkeypatch.setenv("CHARACTER_LORA_PROVIDER_USD", "1.00")
    with factory() as s:
        user = User(email=email, api_key_hash=hashlib.sha256(key.encode()).hexdigest())
        s.add(user)
        s.commit()
        user_id = user.id

    app = FastAPI()
    app.include_router(hub.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    client = TestClient(app)
    headers = {"x-api-key": key}
    challenge = client.post("/api/v1/my/characters/consent-phrase", headers=headers).json()["data"]
    monkeypatch.setattr(hub, "transcribe_key", lambda k: f"um {challenge['phrase']} okay")
    body = {"name": "Me", "reference_keys": [f"uploads/u/face-{n}.jpg" for n in range(12)],
            "consent_token": challenge["token"], "recording_key": "uploads/u/consent.m4a",
            "passport_id": "pp_1", "passport_version": 2, "self_declared": True}
    created = client.post("/api/v1/my/characters/real-face", json=body, headers=headers)
    assert created.status_code == 200, created.text
    cid = created.json()["data"]["id"]
    credits = client.post(f"/api/v1/my/characters/{cid}/train/quote", headers=headers).json()["data"]["credits"]
    with factory() as s:
        pc.grant(s, user_id, pc.KIND_AI_VIDEO, credits, f"test_grant:{user_id}")
        s.commit()
    res = client.post(f"/api/v1/my/characters/{cid}/train", json={"quoted_credits": credits}, headers=headers)
    assert res.status_code == 200, res.text
    return user_id, res.json()["data"]["job_id"]


def _outbox_row(factory, job_id):
    from app.integrations.railyard.meters import MeterOutbox

    with factory() as s:
        return s.execute(select(MeterOutbox).where(
            MeterOutbox.transaction_id == f"menivor:lora.train:{job_id}")).scalar_one_or_none()


def test_lora_training_meter_lands_in_the_outbox_sqlite(monkeypatch):
    from app.domains.characters import hub  # noqa: F401 - registers the hub tables
    from app.integrations.railyard import meters  # noqa: F401 - registers railyard_meter_outbox
    from app.models.db import character_refs, characters  # noqa: F401 - registers characters
    from app.models.db.base import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    assert "railyard_meter_outbox" in Base.metadata.tables
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    _user, job_id = _hub_flow(factory, monkeypatch, "lora-sqlite@example.com")
    row = _outbox_row(factory, job_id)
    assert row is not None and row.sent_at is None
    assert row.payload["code"] == "menivor.lora.train"
    assert row.payload["properties"]["ai_video_credits"] > 0


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("MENIVOR_PG_TEST_URL"), reason="set MENIVOR_PG_TEST_URL to a scratch Postgres")
def test_lora_training_meter_lands_in_the_outbox_postgres(monkeypatch):
    """P-M3 on Postgres: the schema comes from ``alembic upgrade head`` (not create_all)."""
    from sqlalchemy import inspect

    from app.domains.characters import hub
    from app.integrations.railyard.meters import MeterOutbox
    from app.models.db.models import User
    from app.models.db.premium_credit import PremiumCreditLedger

    engine = create_engine(os.environ["MENIVOR_PG_TEST_URL"], future=True)
    assert "railyard_meter_outbox" in inspect(engine).get_table_names(), "run alembic upgrade head first"
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    email = f"lora-pg-{uuid.uuid4().hex[:8]}@example.com"
    user_id, job_id = _hub_flow(factory, monkeypatch, email)
    try:
        row = _outbox_row(factory, job_id)
        assert row is not None, "menivor.lora.train did not reach railyard_meter_outbox on Postgres"
        assert row.channel == "rago" and row.payload["external_customer_id"] == str(user_id)
    finally:
        with factory() as s:
            s.execute(delete(MeterOutbox).where(MeterOutbox.transaction_id == f"menivor:lora.train:{job_id}"))
            s.execute(delete(PremiumCreditLedger).where(PremiumCreditLedger.user_id == user_id))
            s.execute(delete(hub.CharacterHubProfile).where(hub.CharacterHubProfile.user_id == user_id))
            s.execute(delete(Job).where(Job.user_id == user_id))
            from app.models.db.character_refs import CharacterReference
            from app.models.db.characters import Character

            owned = select(Character.id).where(Character.user_id == user_id)
            s.execute(delete(CharacterReference).where(CharacterReference.character_id.in_(owned)))
            s.execute(delete(Character).where(Character.user_id == user_id))
            s.execute(delete(User).where(User.id == user_id))
            s.commit()
