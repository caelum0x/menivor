"""Repurposing engine tests — highlight-selection policy + HTTP flow."""

from __future__ import annotations

import hashlib
import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.repurpose.policy import Candidate, select_highlights
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

repurpose_mod = importlib.import_module("app.domains.repurpose.router")


# --------------------------------------------------------------------------- #
# Pure policy
# --------------------------------------------------------------------------- #
def _c(start, end, score, **kw):
    return Candidate(start_s=start, end_s=end, score=score, **kw)


def test_select_highlights_picks_top_nonoverlapping():
    cands = [
        _c(0, 30, 90),    # best
        _c(20, 50, 80),   # overlaps the best -> skipped
        _c(60, 90, 85),   # next best, no overlap -> picked
        _c(100, 130, 70),
    ]
    out = select_highlights(cands, max_clips=2, min_len_s=15, max_len_s=60, min_score=50)
    assert [(c.start_s, c.score) for c in out] == [(0, 90), (60, 85)]


def test_select_highlights_filters_length_and_score():
    cands = [
        _c(0, 5, 99),     # too short (5s < 15)
        _c(0, 200, 99),   # too long (200s > 60)
        _c(0, 30, 40),    # score below floor
        _c(0, 30, 60),    # qualifies
    ]
    out = select_highlights(cands, min_len_s=15, max_len_s=60, min_score=50)
    assert len(out) == 1
    assert out[0].score == 60


def test_select_highlights_respects_max_clips():
    cands = [_c(i * 40, i * 40 + 30, 80) for i in range(10)]
    out = select_highlights(cands, max_clips=3, min_score=50)
    assert len(out) == 3


# --------------------------------------------------------------------------- #
# HTTP flow
# --------------------------------------------------------------------------- #
def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture()
def env(monkeypatch, factory):
    @contextmanager
    def _fake_get_session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(repurpose_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(repurpose_mod, "_DB_IMPORT_ERROR", None)
    app = FastAPI()
    app.include_router(repurpose_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), factory


@pytest.fixture()
def users(factory):
    out = {}
    with factory() as s:
        for label, raw in (("alice", "alice-key"), ("bob", "bob-key")):
            u = User(email=f"{label}@example.com", api_key_hash=_key_hash(raw))
            s.add(u)
            s.flush()
            out[label] = raw
        s.commit()
    return out


def _h(raw: str) -> dict:
    return {"x-api-key": raw}


def test_full_repurpose_flow(env, users):
    client, _ = env
    # 1. Create a job.
    created = client.post(
        "/api/v1/repurpose",
        json={"source_kind": "url", "source_ref": "https://youtu.be/abc", "title": "Podcast #1"},
        headers=_h(users["alice"]),
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "created"

    # 2. Rank a pre-scored transcript (deterministic, no LLM).
    ranked = client.post(
        f"/api/v1/repurpose/{job_id}/rank",
        json={
            "segments": [
                {"start_s": 0, "end_s": 30, "text": "big hook here", "score": 92, "title": "The hook", "hook": "You won't believe"},
                {"start_s": 20, "end_s": 50, "text": "overlaps", "score": 88},
                {"start_s": 60, "end_s": 90, "text": "second best", "score": 80, "title": "Part 2"},
                {"start_s": 95, "end_s": 100, "text": "too short", "score": 99},
            ],
            "max_clips": 5,
        },
        headers=_h(users["alice"]),
    )
    assert ranked.status_code == 200, ranked.text
    clips = ranked.json()["data"]["clips"]
    # 92 picked; 88 overlaps -> skipped; 80 picked; too-short filtered.
    assert [c["virality_score"] for c in clips] == [92, 80]
    assert clips[0]["title"] == "The hook"

    # 3. Job is now ready with the clip count.
    job = client.get(f"/api/v1/repurpose/{job_id}", headers=_h(users["alice"])).json()["data"]
    assert job["status"] == "ready"
    assert job["clip_count"] == 2

    # 4. List clips (owner-scoped) + promote the top one.
    listed = client.get(f"/api/v1/repurpose/{job_id}/clips", headers=_h(users["alice"]))
    top_clip_id = listed.json()["data"]["clips"][0]["id"]
    promoted = client.post(
        f"/api/v1/repurpose/clips/{top_clip_id}/promote", headers=_h(users["alice"])
    )
    assert promoted.status_code == 200
    draft = promoted.json()["data"]["reel_draft"]
    assert draft["video_script"] == "big hook here"
    assert draft["source_ref"] == "https://youtu.be/abc"
    assert promoted.json()["data"]["clip"]["status"] == "promoted"


def test_repurpose_owner_scoping(env, users):
    client, _ = env
    created = client.post(
        "/api/v1/repurpose",
        json={"source_kind": "url", "source_ref": "https://youtu.be/key123"},
        headers=_h(users["alice"]),
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["data"]["id"]
    # Bob cannot see Alice's job or its clips.
    assert client.get(f"/api/v1/repurpose/{job_id}", headers=_h(users["bob"])).status_code == 404
    assert client.get(f"/api/v1/repurpose/{job_id}/clips", headers=_h(users["bob"])).status_code == 404


def test_rank_uses_injected_ranker_when_unscored(env, users):
    client, factory = env
    from app.domains.repurpose.service import RepurposeService

    created = client.post(
        "/api/v1/repurpose",
        json={"source_kind": "url", "source_ref": "https://youtu.be/k"},
        headers=_h(users["alice"]),
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["data"]["id"]

    def fake_ranker(segments, *, language="auto"):
        # Score everything 75 so it passes the default floor.
        return [{**s, "score": 75, "title": "auto"} for s in segments]

    with factory() as s:
        uid = s.query(User).filter(User.email == "alice@example.com").first().id
        clips = RepurposeService(s).rank(
            job_id,
            uid,
            segments=[{"start_s": 0, "end_s": 30, "text": "x"}],  # no score
            ranker=fake_ranker,
        )
        s.commit()
    assert len(clips) == 1
    assert clips[0]["virality_score"] == 75
    assert clips[0]["title"] == "auto"


def test_create_requires_source_ref(env, users):
    client, _ = env
    resp = client.post("/api/v1/repurpose", json={"source_ref": ""}, headers=_h(users["alice"]))
    assert resp.status_code == 400


def test_upload_source_must_be_owned_by_caller(env, users):
    client, _ = env
    resp = client.post(
        "/api/v1/repurpose",
        json={"source_kind": "upload", "source_ref": "uploads/not-mine.mp4"},
        headers=_h(users["alice"]),
    )
    assert resp.status_code == 403, resp.text
