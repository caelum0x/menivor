"""Editor timeline (EDL) tests — pure policy + service + profile wiring."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.editor.service import EditorDomainError, create_timeline_export_job
from app.domains.editor.timeline import (
    Overlay,
    Segment,
    Timeline,
    TimelineError,
    normalize_edl,
    validate_timeline,
)
from app.models.const import TASK_STATE_COMPLETE
from app.models.db.base import Base
from app.models.db.models import Job, User


# --------------------------------------------------------------------------- #
# Pure timeline policy
# --------------------------------------------------------------------------- #
def test_output_duration_accounts_for_speed():
    tl = Timeline(
        segments=[
            Segment(0, 30),           # 30s @ 1x
            Segment(60, 90, speed=2), # 30s @ 2x -> 15s
        ]
    )
    assert validate_timeline(tl) == 45.0


def test_segments_may_reuse_source_ranges():
    tl = Timeline(segments=[Segment(0, 10), Segment(0, 10)])  # repeat b-roll
    assert validate_timeline(tl) == 20.0


@pytest.mark.parametrize(
    "seg",
    [
        Segment(10, 5),            # out <= in
        Segment(0, 0.05),          # too short
        Segment(0, 10, speed=10),  # speed out of range
    ],
)
def test_invalid_segments_raise(seg):
    with pytest.raises(TimelineError):
        validate_timeline(Timeline(segments=[seg]))


def test_overlay_must_fit_output():
    tl = Timeline(
        segments=[Segment(0, 20)],
        overlays=[Overlay("Buy now", start_s=0, end_s=30)],  # past 20s output
    )
    with pytest.raises(TimelineError):
        validate_timeline(tl)


def test_source_duration_bound_enforced():
    with pytest.raises(TimelineError):
        validate_timeline(Timeline(segments=[Segment(0, 40)]), source_duration_s=30)


def test_normalize_edl_shape():
    tl = Timeline(
        segments=[Segment(0, 12.3456, caption="Hook")],
        overlays=[Overlay("CTA", 0, 5, position="top")],
    )
    edl = normalize_edl(tl)
    assert edl["segments"][0]["source_out"] == 12.346
    assert edl["segments"][0]["caption"] == "Hook"
    assert edl["overlays"][0]["position"] == "top"
    assert edl["output_duration_s"] == 12.346


# --------------------------------------------------------------------------- #
# Service (ownership + validation + persistence)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _completed_reel(factory, user_id: str) -> str:
    with factory() as s:
        job = Job(
            user_id=user_id,
            kind="reel",
            state=TASK_STATE_COMPLETE,
            result_key="jobs/x/final.mp4",
        )
        s.add(job)
        s.flush()
        jid = job.id
        s.commit()
    return jid


def test_timeline_export_persists_edl(factory):
    with factory() as s:
        u = User(email="a@example.com", api_key_hash="h")
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    source_id = _completed_reel(factory, uid)

    with factory() as s:
        response, replay = create_timeline_export_job(
            s,
            user_id=uid,
            source_job_id=source_id,
            segments=[
                {"source_in": 0, "source_out": 30},
                {"source_in": 60, "source_out": 90, "speed": 2, "caption": "Part 2"},
            ],
            overlays=[{"text": "Subscribe", "start_s": 0, "end_s": 3, "position": "bottom"}],
            idempotency_key=None,
            request_id="r",
        )
        s.commit()
    assert replay is False
    assert response["output_duration_s"] == 45.0
    assert response["segments"] == 2
    assert response["overlays"] == 1
    with factory() as s:
        job = s.get(Job, response["job_id"])
        assert job.kind == "editor_timeline_export"
        assert job.params["edl"]["segments"][1]["caption"] == "Part 2"


def test_timeline_export_foreign_source_404(factory):
    with factory() as s:
        a = User(email="a@example.com", api_key_hash="h")
        b = User(email="b@example.com", api_key_hash="h2")
        s.add_all([a, b])
        s.flush()
        aid, bid = a.id, b.id
        s.commit()
    source_id = _completed_reel(factory, aid)
    with factory() as s:
        with pytest.raises(EditorDomainError) as ei:
            create_timeline_export_job(
                s, user_id=bid, source_job_id=source_id,
                segments=[{"source_in": 0, "source_out": 5}], overlays=[],
                idempotency_key=None, request_id="r",
            )
        assert ei.value.status_code == 404


def test_timeline_export_invalid_edl_422(factory):
    with factory() as s:
        u = User(email="a@example.com", api_key_hash="h")
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    source_id = _completed_reel(factory, uid)
    with factory() as s:
        with pytest.raises(EditorDomainError) as ei:
            create_timeline_export_job(
                s, user_id=uid, source_job_id=source_id,
                segments=[{"source_in": 0, "source_out": 20}],
                overlays=[{"text": "x", "start_s": 0, "end_s": 40}],  # past output
                idempotency_key=None, request_id="r",
            )
        assert ei.value.status_code == 422


# --------------------------------------------------------------------------- #
# Generation profile wiring for the new adapters
# --------------------------------------------------------------------------- #
def test_self_hosted_and_photo_avatar_profiles_seeded(factory):
    from app.domains.catalog.repository import CatalogRepository
    from app.domains.catalog.seed_data import seed_default_catalog

    with factory() as s:
        seed_default_catalog(s)
        s.commit()
    with factory() as s:
        repo = CatalogRepository(s)
        photo = repo.get_profile("photo-avatar-v1")
        assert photo.stages["avatar"]["model_id"] == "sadtalker/photo-avatar"
        assert photo.stages["voice"]["model_id"] == "chatterbox/tts"
        selfhosted = repo.get_profile("self-hosted-v1")
        assert selfhosted.stages["voice"]["model_id"] == "edge/tts"
