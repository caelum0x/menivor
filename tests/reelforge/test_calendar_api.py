"""Publishing Calendar API tests.

Covers ``app.controllers.v1.calendar`` — the two auth-gated, strictly
owner-scoped endpoints that back a creator's publishing calendar:

* ``GET   /me/calendar?start=&end=`` — the caller's schedules whose
  ``scheduled_at`` falls inside the UTC window (owner-scoped; range clamped to
  <=92 days; ``400`` on an inverted / unparseable range; ``401`` no auth).
* ``PATCH /me/calendar/{id}``        — move a still-``pending`` schedule to a new
  future time (``200``); ``404`` unknown/foreign, ``409`` non-pending, ``400`` a
  past/unparseable time, ``401`` no auth.

No external I/O: Postgres is replaced by an in-memory SQLite DB behind a
``TestClient``, mirroring ``tests/reelforge/test_schedule_api.py``.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.calendar as cal_mod
from app.models import const
from app.models.db.base import Base
from app.models.db.models import Job, ScheduledPublish, User
from app.models.db.repositories import (
    SCHEDULE_STATUS_PENDING,
    SCHEDULE_STATUS_PUBLISHED,
    ScheduledPublishRepository,
)
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "cal-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

# A far-future UTC instant so "future" reschedules never race the wall clock.
_FUTURE = "2999-01-01T12:00:00+00:00"
# A definitively-past UTC instant.
_PAST = "2000-01-01T12:00:00+00:00"


# =========================================================================== #
# Fixtures
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


def _make_user(Factory, email="cal@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_job(Factory, user_id: str) -> str:
    with Factory() as s:
        job = Job(
            user_id=user_id,
            kind="avatar_reel",
            state=const.TASK_STATE_COMPLETE,
            progress=100,
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
    scheduled_at: datetime,
    status: str = SCHEDULE_STATUS_PENDING,
) -> str:
    with Factory() as s:
        row = ScheduledPublishRepository(s).create(
            user_id=user_id,
            job_id=job_id,
            platforms=platforms or ["tiktok"],
            scheduled_at=scheduled_at,
        )
        if status != SCHEDULE_STATUS_PENDING:
            row.status = status
        sid = row.id
        s.commit()
    return sid


@pytest.fixture()
def cal_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the calendar router + in-memory SQLite.

    Returns ``(client, Factory)``. ``get_session`` (used by the controller) and
    the fixtures share the same engine, so rows arranged directly are visible to
    a later GET/PATCH call.
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

    monkeypatch.setattr(cal_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(cal_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


def _win(start: datetime, end: datetime) -> dict:
    return {"start": start.isoformat(), "end": end.isoformat()}


_BASE = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


# =========================================================================== #
# GET /me/calendar
# =========================================================================== #
def test_calendar_scoped_to_caller(cal_client):
    client, Factory = cal_client
    caller_id = _make_user(Factory, email="caller@x.com")
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    caller_job = _make_job(Factory, caller_id)
    other_job = _make_job(Factory, other_id)

    sid_a = _make_schedule(
        Factory, caller_id, caller_job, scheduled_at=_BASE + timedelta(hours=2)
    )
    sid_b = _make_schedule(
        Factory, caller_id, caller_job, scheduled_at=_BASE + timedelta(hours=1)
    )
    # Another user's row inside the window — must NOT leak.
    _make_schedule(
        Factory, other_id, other_job, scheduled_at=_BASE + timedelta(hours=1)
    )

    resp = client.get(
        "/api/v1/me/calendar",
        headers=_HEADERS,
        params=_win(_BASE, _BASE + timedelta(days=1)),
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    # Owner-scoped + soonest-first ordering.
    assert [r["id"] for r in rows] == [sid_b, sid_a]
    for r in rows:
        assert r["job_id"] == caller_job
        # Safe DTO only — never a private / cross-tenant field.
        assert set(r.keys()) == {
            "id",
            "job_id",
            "platforms",
            "scheduled_at",
            "status",
        }


def test_calendar_excludes_out_of_window_and_clamps(cal_client):
    client, Factory = cal_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)

    inside = _make_schedule(
        Factory, uid, jid, scheduled_at=_BASE + timedelta(hours=1)
    )
    # Beyond the 92-day clamp measured from ``start`` — excluded even though the
    # requested end is a year out.
    _make_schedule(
        Factory, uid, jid, scheduled_at=_BASE + timedelta(days=120)
    )
    # Before the window — excluded.
    _make_schedule(
        Factory, uid, jid, scheduled_at=_BASE - timedelta(hours=1)
    )

    resp = client.get(
        "/api/v1/me/calendar",
        headers=_HEADERS,
        params=_win(_BASE, _BASE + timedelta(days=365)),
    )
    assert resp.status_code == 200, resp.text
    ids = [r["id"] for r in resp.json()["data"]]
    assert ids == [inside]


def test_calendar_inverted_range_400(cal_client):
    client, Factory = cal_client
    _make_user(Factory)
    resp = client.get(
        "/api/v1/me/calendar",
        headers=_HEADERS,
        params=_win(_BASE + timedelta(days=1), _BASE),
    )
    assert resp.status_code == 400, resp.text


def test_calendar_unparseable_range_400(cal_client):
    client, Factory = cal_client
    _make_user(Factory)
    resp = client.get(
        "/api/v1/me/calendar",
        headers=_HEADERS,
        params={"start": "not-a-date", "end": _FUTURE},
    )
    assert resp.status_code == 400, resp.text


def test_calendar_empty_ok(cal_client):
    client, Factory = cal_client
    _make_user(Factory)
    resp = client.get(
        "/api/v1/me/calendar",
        headers=_HEADERS,
        params=_win(_BASE, _BASE + timedelta(days=1)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("data", []) in ([], None)


def test_calendar_requires_auth_401(cal_client):
    client, Factory = cal_client
    resp = client.get(
        "/api/v1/me/calendar",
        params=_win(_BASE, _BASE + timedelta(days=1)),
    )
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# PATCH /me/calendar/{id}
# =========================================================================== #
def test_reschedule_pending_succeeds(cal_client):
    client, Factory = cal_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)
    sid = _make_schedule(
        Factory, uid, jid, scheduled_at=datetime(2998, 1, 1, tzinfo=timezone.utc)
    )

    resp = client.patch(
        f"/api/v1/me/calendar/{sid}",
        headers=_HEADERS,
        json={"scheduled_at": _FUTURE},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"] == sid
    assert data["status"] == SCHEDULE_STATUS_PENDING
    assert data["scheduled_at"].startswith("2999-01-01T12:00:00")

    with Factory() as s:
        row = s.get(ScheduledPublish, sid)
        moved = row.scheduled_at
        if moved.tzinfo is None:
            moved = moved.replace(tzinfo=timezone.utc)
        assert moved == datetime(2999, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_reschedule_foreign_404_and_untouched(cal_client):
    client, Factory = cal_client
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    other_job = _make_job(Factory, other_id)
    when = datetime(2998, 1, 1, tzinfo=timezone.utc)
    victim_sid = _make_schedule(Factory, other_id, other_job, scheduled_at=when)
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.patch(
        f"/api/v1/me/calendar/{victim_sid}",
        headers=_HEADERS,
        json={"scheduled_at": _FUTURE},
    )
    assert resp.status_code == 404, resp.text
    # The foreign schedule is untouched.
    with Factory() as s:
        row = s.get(ScheduledPublish, victim_sid)
        got = row.scheduled_at
        if got.tzinfo is None:
            got = got.replace(tzinfo=timezone.utc)
        assert got == when


def test_reschedule_unknown_404(cal_client):
    client, Factory = cal_client
    _make_user(Factory)
    resp = client.patch(
        "/api/v1/me/calendar/does-not-exist",
        headers=_HEADERS,
        json={"scheduled_at": _FUTURE},
    )
    assert resp.status_code == 404, resp.text


def test_reschedule_non_pending_409(cal_client):
    client, Factory = cal_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)
    when = datetime(2998, 1, 1, tzinfo=timezone.utc)
    sid = _make_schedule(
        Factory, uid, jid, scheduled_at=when, status=SCHEDULE_STATUS_PUBLISHED
    )

    resp = client.patch(
        f"/api/v1/me/calendar/{sid}",
        headers=_HEADERS,
        json={"scheduled_at": _FUTURE},
    )
    assert resp.status_code == 409, resp.text
    # Unchanged.
    with Factory() as s:
        row = s.get(ScheduledPublish, sid)
        assert row.status == SCHEDULE_STATUS_PUBLISHED
        got = row.scheduled_at
        if got.tzinfo is None:
            got = got.replace(tzinfo=timezone.utc)
        assert got == when


def test_reschedule_past_time_400(cal_client):
    client, Factory = cal_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)
    sid = _make_schedule(
        Factory, uid, jid, scheduled_at=datetime(2998, 1, 1, tzinfo=timezone.utc)
    )

    resp = client.patch(
        f"/api/v1/me/calendar/{sid}",
        headers=_HEADERS,
        json={"scheduled_at": _PAST},
    )
    assert resp.status_code == 400, resp.text


def test_reschedule_unparseable_time_400(cal_client):
    client, Factory = cal_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)
    sid = _make_schedule(
        Factory, uid, jid, scheduled_at=datetime(2998, 1, 1, tzinfo=timezone.utc)
    )

    resp = client.patch(
        f"/api/v1/me/calendar/{sid}",
        headers=_HEADERS,
        json={"scheduled_at": "not-a-date"},
    )
    assert resp.status_code == 400, resp.text


def test_reschedule_requires_auth_401(cal_client):
    client, Factory = cal_client
    uid = _make_user(Factory)
    jid = _make_job(Factory, uid)
    sid = _make_schedule(
        Factory, uid, jid, scheduled_at=datetime(2998, 1, 1, tzinfo=timezone.utc)
    )
    resp = client.patch(  # no x-api-key
        f"/api/v1/me/calendar/{sid}",
        json={"scheduled_at": _FUTURE},
    )
    assert resp.status_code == 401, resp.text
