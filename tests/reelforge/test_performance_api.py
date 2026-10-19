"""Hook Performance Loop — API tests.

Covers ``app.controllers.v1.performance`` — the auth-gated, strictly
caller-scoped endpoints that log and rank self-reported reel outcomes:

* ``POST /jobs/{job_id}/performance`` — auth (401), validation (400 on a negative
  count / retention over 100), cannot-log-a-foreign-job (403), the happy path
  (upsert -> the stored row) and idempotency (re-log updates, never duplicates).
* ``GET /jobs/{job_id}/performance`` — owner-scoped read (404 for a foreign id).
* ``GET /me/performance`` — scoped to the caller; ``limit`` is clamped.
* ``GET /me/winning-hooks`` — deterministic win-score ranking shape.

No external I/O: Postgres is replaced by an in-memory SQLite DB behind a
``TestClient``, mirroring ``tests/reelforge/test_ideas_api.py``.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.performance as perf_mod
from app.models.db.base import Base
from app.models.db.models import Job, JobPerformance, User
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "perf-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


# =========================================================================== #
# Fixtures / helpers
# =========================================================================== #
@pytest.fixture()
def db_factory():
    """In-memory SQLite engine + session factory with the schema created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    return Factory


def _make_user(Factory, email="creator@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_job(Factory, user_id: str, hook: str = "hook one", template: str = "t1") -> str:
    with Factory() as s:
        job = Job(
            user_id=user_id,
            params={"video_subject": hook, "template": template},
            script="fallback script line\nsecond line",
        )
        s.add(job)
        s.flush()
        jid = job.id
        s.commit()
    return jid


@pytest.fixture()
def perf_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the performance router + in-memory SQLite.

    Returns ``(client, Factory)``.
    """
    Factory = db_factory

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(perf_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(perf_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# =========================================================================== #
# POST /jobs/{job_id}/performance  (log)
# =========================================================================== #
def test_log_performance_happy_path_and_read_back(perf_client):
    client, Factory = perf_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/performance",
        json={
            "platform": "TikTok",
            "views": 1000,
            "likes": 100,
            "comments": 10,
            "shares": 5,
            "saves": 20,
            "retention_pct": 55.5,
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["job_id"] == jid
    assert data["views"] == 1000
    assert data["platform"] == "tiktok"  # normalized/lower-cased at the boundary
    assert data["retention_pct"] == 55.5

    # Exactly one row persisted for the job.
    with Factory() as s:
        rows = s.query(JobPerformance).filter(JobPerformance.job_id == jid).all()
        assert len(rows) == 1
        assert rows[0].user_id == uid

    # And it reads back through the GET endpoint (owner-scoped).
    read = client.get(f"/api/v1/jobs/{jid}/performance", headers=_HEADERS)
    assert read.status_code == 200, read.text
    assert read.json()["data"]["likes"] == 100


def test_relog_updates_in_place_not_duplicate(perf_client):
    client, Factory = perf_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)

    client.post(
        f"/api/v1/jobs/{jid}/performance",
        json={"views": 100},
        headers=_HEADERS,
    )
    resp = client.post(
        f"/api/v1/jobs/{jid}/performance",
        json={"views": 999},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["views"] == 999

    with Factory() as s:
        rows = s.query(JobPerformance).filter(JobPerformance.job_id == jid).all()
        assert len(rows) == 1  # idempotent-ish: one row per job


def test_log_requires_auth_401(perf_client):
    client, Factory = perf_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/performance",
        json={"views": 10},
    )  # no x-api-key
    assert resp.status_code == 401, resp.text


def test_cannot_log_foreign_job_403(perf_client):
    client, Factory = perf_client
    # Job owned by a DIFFERENT creator; the caller must not be able to log it.
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    victim_jid = _make_job(Factory, other_id)
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.post(
        f"/api/v1/jobs/{victim_jid}/performance",
        json={"views": 10},
        headers=_HEADERS,
    )
    assert resp.status_code == 403, resp.text
    # No row was written against the foreign job.
    with Factory() as s:
        assert (
            s.query(JobPerformance)
            .filter(JobPerformance.job_id == victim_jid)
            .count()
            == 0
        )


def test_log_unknown_job_404(perf_client):
    client, Factory = perf_client
    _make_user(Factory)
    resp = client.post(
        "/api/v1/jobs/does-not-exist/performance",
        json={"views": 10},
        headers=_HEADERS,
    )
    assert resp.status_code == 404, resp.text


def test_log_negative_count_400(perf_client):
    client, Factory = perf_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/performance",
        json={"views": -5},
        headers=_HEADERS,
    )
    assert resp.status_code == 400, resp.text
    # The 400 tripped before any write.
    with Factory() as s:
        assert (
            s.query(JobPerformance).filter(JobPerformance.job_id == jid).count() == 0
        )


def test_log_retention_over_100_400(perf_client):
    client, Factory = perf_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)

    resp = client.post(
        f"/api/v1/jobs/{jid}/performance",
        json={"retention_pct": 150},
        headers=_HEADERS,
    )
    assert resp.status_code == 400, resp.text


# =========================================================================== #
# GET /jobs/{job_id}/performance
# =========================================================================== #
def test_get_foreign_performance_404(perf_client):
    client, Factory = perf_client
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    victim_jid = _make_job(Factory, other_id)
    # The foreign creator logs metrics for their own job.
    with Factory() as s:
        s.add(JobPerformance(job_id=victim_jid, user_id=other_id, views=42))
        s.commit()
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.get(f"/api/v1/jobs/{victim_jid}/performance", headers=_HEADERS)
    assert resp.status_code == 404, resp.text


def test_get_missing_performance_404(perf_client):
    client, Factory = perf_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)  # job exists but no outcome logged yet
    resp = client.get(f"/api/v1/jobs/{jid}/performance", headers=_HEADERS)
    assert resp.status_code == 404, resp.text


# =========================================================================== #
# GET /me/performance  (list + clamp)
# =========================================================================== #
def test_list_performance_scoped_to_caller(perf_client):
    client, Factory = perf_client
    caller_id = _make_user(Factory, email="caller@x.com")
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    j1 = _make_job(Factory, caller_id, hook="a")
    j2 = _make_job(Factory, caller_id, hook="b")
    jo = _make_job(Factory, other_id, hook="z")
    with Factory() as s:
        s.add(JobPerformance(job_id=j1, user_id=caller_id, views=1))
        s.add(JobPerformance(job_id=j2, user_id=caller_id, views=2))
        s.add(JobPerformance(job_id=jo, user_id=other_id, views=9))  # must NOT appear
        s.commit()

    resp = client.get("/api/v1/me/performance", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data) == 2
    job_ids = {row["job_id"] for row in data}
    assert job_ids == {j1, j2}


def test_list_performance_clamps_limit(perf_client):
    client, Factory = perf_client
    uid = _make_user(Factory)
    for i in range(3):
        jid = _make_job(Factory, uid, hook=f"h{i}")
        with Factory() as s:
            s.add(JobPerformance(job_id=jid, user_id=uid, views=i))
            s.commit()

    # An over-large limit is clamped to <= 100 (does not error); a garbage limit
    # falls back to the default. Both must return a 200 with the caller's rows.
    resp = client.get("/api/v1/me/performance?limit=9999", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["data"]) == 3

    resp2 = client.get("/api/v1/me/performance?limit=1", headers=_HEADERS)
    assert resp2.status_code == 200, resp2.text
    assert len(resp2.json()["data"]) == 1


def test_list_requires_auth_401(perf_client):
    client, Factory = perf_client
    resp = client.get("/api/v1/me/performance")  # no x-api-key
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# GET /me/winning-hooks  /  winning-templates
# =========================================================================== #
def test_winning_hooks_shape_and_ranking(perf_client):
    client, Factory = perf_client
    uid = _make_user(Factory)
    # A strong hook (high engagement + retention) and a weak one.
    strong = _make_job(Factory, uid, hook="strong hook", template="tpl_a")
    weak = _make_job(Factory, uid, hook="weak hook", template="tpl_b")
    with Factory() as s:
        s.add(
            JobPerformance(
                job_id=strong,
                user_id=uid,
                views=100,
                likes=90,
                comments=0,
                shares=0,
                saves=0,
                retention_pct=90.0,
            )
        )
        s.add(
            JobPerformance(
                job_id=weak,
                user_id=uid,
                views=100,
                likes=1,
                retention_pct=5.0,
            )
        )
        s.commit()

    resp = client.get("/api/v1/me/winning-hooks?limit=5", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data) == 2
    # Deterministic ranking: the strong hook wins.
    assert data[0]["hook"] == "strong hook"
    assert data[0]["win_score"] > data[1]["win_score"]
    for row in data:
        for key in ("hook", "win_score", "reels", "views", "engagements", "avg_retention_pct"):
            assert key in row


def test_winning_hooks_empty_when_no_data(perf_client):
    client, Factory = perf_client
    _make_user(Factory)
    resp = client.get("/api/v1/me/winning-hooks", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json().get("data", []) == []


def test_winning_templates_shape(perf_client):
    client, Factory = perf_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, hook="h", template="tpl_a")
    with Factory() as s:
        s.add(
            JobPerformance(
                job_id=jid, user_id=uid, views=100, likes=50, retention_pct=60.0
            )
        )
        s.commit()

    resp = client.get("/api/v1/me/winning-templates?limit=5", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["template"] == "tpl_a"
    assert "win_score" in data[0]


def test_winning_requires_auth_401(perf_client):
    client, Factory = perf_client
    resp = client.get("/api/v1/me/winning-hooks")  # no x-api-key
    assert resp.status_code == 401, resp.text
