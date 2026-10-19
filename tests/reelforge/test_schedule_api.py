"""Scheduled Publishing API tests.

Covers ``app.controllers.v1.schedule`` — the three auth-gated, strictly
owner-scoped endpoints that let a creator queue a *finished* reel to
auto-publish at a future UTC time:

* ``POST   /jobs/{job_id}/schedule`` — queue a completed, owned job. ``404``
  unknown/foreign job, ``409`` job not done, ``400`` empty/invalid platforms or
  a past/unparseable ``scheduled_at``.
* ``GET    /me/scheduled``           — the caller's schedules only (owner-scoped).
* ``DELETE /me/scheduled/{id}``      — cancel a still-``pending`` schedule
  (``404`` unknown/foreign, ``409`` no longer pending).

No external I/O: Postgres is replaced by an in-memory SQLite DB behind a
``TestClient`` and the scheduler's *creation* entrypoint is monkeypatched,
mirroring ``tests/reelforge/test_notifications_api.py``.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.schedule as sched_mod
from app.models import const
from app.models.db.base import Base
from app.models.db.models import Job, ScheduledPublish, User
from app.models.db.repositories import (
    SCHEDULE_STATUS_CANCELED,
    SCHEDULE_STATUS_PENDING,
    SCHEDULE_STATUS_PUBLISHED,
    ScheduledPublishRepository,
)
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "sched-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

# A far-future UTC instant so "future" tests never race the wall clock.
_FUTURE = "2999-01-01T12:00:00+00:00"
# A definitively-past UTC instant.
_PAST = "2000-01-01T12:00:00+00:00"


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture(autouse=True)
def _grant_pro_entitlement(monkeypatch):
    """Grant RevenueCat Pro so these tests exercise the scheduling logic. The
    paid-entitlement gate itself is covered by test_schedule_requires_pro_402."""
    from app.services.billing import revenuecat_client

    monkeypatch.setattr(
        revenuecat_client, "require_pro_entitlement", lambda *a, **k: None
    )


@pytest.fixture(autouse=True)
def _connected_accounts(monkeypatch):
    """Treat every requested platform as connected. Scheduling verifies native
    OAuth connections up front (their own DB session); the not-connected path
    is covered by test_schedule_not_connected_409."""
    from app.domains.publishing import native_service

    monkeypatch.setattr(
        native_service, "require_native_connections", lambda *a, **k: None
    )


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


def _make_user(Factory, email="sched@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_job(
    Factory, user_id: str, *, state: int = const.TASK_STATE_COMPLETE
) -> str:
    with Factory() as s:
        job = Job(
            user_id=user_id,
            kind="avatar_reel",
            state=state,
            progress=100 if state == const.TASK_STATE_COMPLETE else 0,
            stages={},
            params={},
            result_key="outputs/final.mp4",
        )
        s.add(job)
        s.flush()
        jid = job.id
        s.commit()
    return jid


def _make_schedule(
    Factory,
    user_id: str,
    job_id: str,
    *,
    platforms=None,
    scheduled_at: datetime | None = None,
    status: str = SCHEDULE_STATUS_PENDING,
) -> str:
    when = scheduled_at or datetime(2999, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    with Factory() as s:
        row = ScheduledPublishRepository(s).create(
            user_id=user_id,
            job_id=job_id,
            platforms=platforms or ["tiktok"],
            scheduled_at=when,
        )
        if status != SCHEDULE_STATUS_PENDING:
            row.status = status
        sid = row.id
        s.commit()
    return sid


@pytest.fixture()
def sched_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the schedule router + in-memory SQLite.

    Returns ``(client, Factory)``. Both ``get_session`` (used directly by the
    controller) and the session factory behind the monkeypatched
    ``scheduler.schedule_publish`` share the same engine, so a row created via
    the service is visible to a later list/cancel call.
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

    monkeypatch.setattr(sched_mod, "get_session", _fake_get_session)
    # Paid-access checks (app.services.user_entitlements) read the ledger and
    # plan rows through the shared session factory: point it at this DB too.
    import app.models.db.base as db_base

    monkeypatch.setattr(db_base, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(sched_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# =========================================================================== #
# POST /jobs/{job_id}/schedule
# =========================================================================== #
def test_schedule_done_owned_job_succeeds(sched_client, monkeypatch):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_COMPLETE)

    # Monkeypatch the scheduler's creation entrypoint: assert it receives the
    # controller-validated args and return a lightweight row-like object.
    calls: list[dict] = []

    def _fake_schedule_publish(session, **kwargs):
        calls.append(kwargs)

        class _Row:
            id = "sched-123"
            job_id = kwargs["job_id"]
            platforms = kwargs["platforms"]
            scheduled_at = kwargs["scheduled_at"]
            status = SCHEDULE_STATUS_PENDING
            youtube_privacy_status = kwargs["youtube_privacy_status"]
            attempts = 0
            error = ""

        return _Row()

    monkeypatch.setattr(
        sched_mod.scheduler, "schedule_publish", _fake_schedule_publish
    )

    resp = client.post(
        f"/api/v1/jobs/{jid}/schedule",
        headers=_HEADERS,
        json={"platforms": ["tiktok", "instagram"], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"] == "sched-123"
    assert data["status"] == SCHEDULE_STATUS_PENDING
    assert data["scheduled_at"].startswith("2999-01-01T12:00:00")

    # The controller resolved the owner and forwarded validated args.
    assert len(calls) == 1
    assert calls[0]["job_id"] == jid
    assert calls[0]["user_id"] == uid
    assert calls[0]["platforms"] == ["tiktok", "instagram"]
    assert isinstance(calls[0]["scheduled_at"], datetime)


def test_schedule_persists_via_real_service(sched_client):
    """End-to-end (no monkeypatch): the real service writes a pending row."""
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_COMPLETE)

    resp = client.post(
        f"/api/v1/jobs/{jid}/schedule",
        headers=_HEADERS,
        json={"platforms": ["youtube_shorts"], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 200, resp.text
    sid = resp.json()["data"]["id"]

    with Factory() as s:
        row = s.get(ScheduledPublish, sid)
        assert row is not None
        assert row.user_id == uid
        assert row.job_id == jid
        assert row.status == SCHEDULE_STATUS_PENDING
        assert row.platforms == ["youtube_shorts"]


def test_schedule_past_time_400(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_COMPLETE)

    resp = client.post(
        f"/api/v1/jobs/{jid}/schedule",
        headers=_HEADERS,
        json={"platforms": ["tiktok"], "scheduled_at": _PAST},
    )
    assert resp.status_code == 400, resp.text
    # Nothing was persisted.
    with Factory() as s:
        assert s.query(ScheduledPublish).count() == 0


def test_schedule_unparseable_time_400(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_COMPLETE)

    resp = client.post(
        f"/api/v1/jobs/{jid}/schedule",
        headers=_HEADERS,
        json={"platforms": ["tiktok"], "scheduled_at": "not-a-date"},
    )
    assert resp.status_code == 400, resp.text


def test_schedule_empty_platforms_400(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_COMPLETE)

    resp = client.post(
        f"/api/v1/jobs/{jid}/schedule",
        headers=_HEADERS,
        json={"platforms": [], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 400, resp.text


def test_schedule_invalid_platform_400(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_COMPLETE)

    resp = client.post(
        f"/api/v1/jobs/{jid}/schedule",
        headers=_HEADERS,
        json={"platforms": ["myspace"], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 400, resp.text


def test_schedule_foreign_job_404(sched_client):
    client, Factory = sched_client
    # Job owned by a DIFFERENT user; the caller must not be able to schedule it.
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    foreign_jid = _make_job(Factory, other_id, state=const.TASK_STATE_COMPLETE)
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.post(
        f"/api/v1/jobs/{foreign_jid}/schedule",
        headers=_HEADERS,
        json={"platforms": ["tiktok"], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 404, resp.text
    with Factory() as s:
        assert s.query(ScheduledPublish).count() == 0


def test_schedule_unknown_job_404(sched_client):
    client, Factory = sched_client
    _make_user(Factory)
    resp = client.post(
        "/api/v1/jobs/does-not-exist/schedule",
        headers=_HEADERS,
        json={"platforms": ["tiktok"], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 404, resp.text


def test_schedule_job_not_done_409(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_PROCESSING)

    resp = client.post(
        f"/api/v1/jobs/{jid}/schedule",
        headers=_HEADERS,
        json={"platforms": ["tiktok"], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 409, resp.text


def test_schedule_requires_auth_401(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_COMPLETE)
    resp = client.post(  # no x-api-key
        f"/api/v1/jobs/{jid}/schedule",
        json={"platforms": ["tiktok"], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# GET /me/scheduled
# =========================================================================== #
def test_list_scoped_to_caller(sched_client):
    client, Factory = sched_client
    caller_id = _make_user(Factory, email="caller@x.com")
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    caller_job = _make_job(Factory, caller_id)
    other_job = _make_job(Factory, other_id)
    sid_a = _make_schedule(Factory, caller_id, caller_job, platforms=["tiktok"])
    sid_b = _make_schedule(
        Factory, caller_id, caller_job, platforms=["instagram"]
    )
    _make_schedule(Factory, other_id, other_job)  # must NOT appear

    resp = client.get("/api/v1/me/scheduled", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    ids = {r["id"] for r in rows}
    assert ids == {sid_a, sid_b}
    for r in rows:
        assert r["status"] == SCHEDULE_STATUS_PENDING
        assert r["job_id"] == caller_job


def test_list_status_filter(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)
    pending_sid = _make_schedule(Factory, uid, jid)
    _make_schedule(
        Factory, uid, jid, status=SCHEDULE_STATUS_PUBLISHED
    )

    resp = client.get(
        "/api/v1/me/scheduled?status=pending", headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert [r["id"] for r in rows] == [pending_sid]


def test_list_empty_ok(sched_client):
    client, Factory = sched_client
    _make_user(Factory)
    resp = client.get("/api/v1/me/scheduled", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json().get("data", []) in ([], None)


def test_list_requires_auth_401(sched_client):
    client, Factory = sched_client
    resp = client.get("/api/v1/me/scheduled")  # no key
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# DELETE /me/scheduled/{id}
# =========================================================================== #
def test_cancel_pending_succeeds(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)
    sid = _make_schedule(Factory, uid, jid)

    resp = client.delete(f"/api/v1/me/scheduled/{sid}", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == SCHEDULE_STATUS_CANCELED

    with Factory() as s:
        assert s.get(ScheduledPublish, sid).status == (
            SCHEDULE_STATUS_CANCELED
        )


def test_cancel_foreign_404_and_untouched(sched_client):
    client, Factory = sched_client
    # Schedule owned by a DIFFERENT user; the caller must not cancel it.
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    other_job = _make_job(Factory, other_id)
    victim_sid = _make_schedule(Factory, other_id, other_job)
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.delete(
        f"/api/v1/me/scheduled/{victim_sid}", headers=_HEADERS
    )
    assert resp.status_code == 404, resp.text
    # The foreign schedule survives, still pending.
    with Factory() as s:
        assert s.get(ScheduledPublish, victim_sid).status == (
            SCHEDULE_STATUS_PENDING
        )


def test_cancel_unknown_404(sched_client):
    client, Factory = sched_client
    _make_user(Factory)
    resp = client.delete(
        "/api/v1/me/scheduled/does-not-exist", headers=_HEADERS
    )
    assert resp.status_code == 404, resp.text


def test_cancel_non_pending_409(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)
    sid = _make_schedule(
        Factory, uid, jid, status=SCHEDULE_STATUS_PUBLISHED
    )

    resp = client.delete(f"/api/v1/me/scheduled/{sid}", headers=_HEADERS)
    assert resp.status_code == 409, resp.text
    # Unchanged.
    with Factory() as s:
        assert s.get(ScheduledPublish, sid).status == (
            SCHEDULE_STATUS_PUBLISHED
        )


def test_cancel_requires_auth_401(sched_client):
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)
    sid = _make_schedule(Factory, uid, jid)
    resp = client.delete(f"/api/v1/me/scheduled/{sid}")  # no key
    assert resp.status_code == 401, resp.text


def test_schedule_requires_pro_402(sched_client, monkeypatch):
    from app.services.billing import revenuecat_client

    def _deny(*_a, **_k):
        raise revenuecat_client.RevenueCatAccessDenied("Pro required")

    monkeypatch.setattr(revenuecat_client, "require_pro_entitlement", _deny)
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_COMPLETE)

    resp = client.post(
        f"/api/v1/jobs/{jid}/schedule",
        headers=_HEADERS,
        json={"platforms": ["tiktok"], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 402, resp.text
    with Factory() as s:
        assert s.query(ScheduledPublish).count() == 0


def test_schedule_not_connected_409(sched_client, monkeypatch):
    from app.domains.publishing import native_service

    def _not_connected(user_id, platforms):
        raise native_service.NativePublishError(
            "connect tiktok before scheduling", status_code=409
        )

    monkeypatch.setattr(native_service, "require_native_connections", _not_connected)
    client, Factory = sched_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid, state=const.TASK_STATE_COMPLETE)

    resp = client.post(
        f"/api/v1/jobs/{jid}/schedule",
        headers=_HEADERS,
        json={"platforms": ["tiktok"], "scheduled_at": _FUTURE},
    )
    assert resp.status_code == 409, resp.text
    assert "connect tiktok" in resp.text
