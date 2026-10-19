"""In-app notifications API tests (bell + unread badge + notification center).

Covers ``app.controllers.v1.notifications`` — the four auth-gated, strictly
owner-scoped endpoints:

* ``GET  /me/notifications``               — the caller's notifications only,
  plus the live ``unread_count``; ``unread_only`` / ``limit`` filters honoured.
* ``GET  /me/notifications/unread_count``  — cheap count-only bell-badge poll.
* ``POST /me/notifications/{id}/read``     — mark one read (ownership: a foreign
  id is a ``404`` and the foreign row is untouched).
* ``POST /me/notifications/read_all``      — mark every caller notification read
  so their ``unread_count`` drops to ``0``.

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

import app.controllers.v1.notifications as notif_mod
from app.models.db.base import Base
from app.models.db.models import Notification, User
from app.models.db.repositories import NotificationRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "notif-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


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


def _make_user(Factory, email="notif@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_notification(
    Factory,
    user_id: str,
    kind: str = "job_complete",
    title: str = "Your video is ready",
    body: str = "",
    data: dict | None = None,
) -> str:
    with Factory() as s:
        row = NotificationRepository(s).create(
            user_id=user_id, kind=kind, title=title, body=body, data=data or {}
        )
        rid = row.id
        s.commit()
    return rid


@pytest.fixture()
def notif_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the notifications router + in-memory SQLite.

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

    monkeypatch.setattr(notif_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(notif_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# =========================================================================== #
# GET /me/notifications  (list + unread_count)
# =========================================================================== #
def test_list_scoped_to_caller_with_unread_count(notif_client):
    client, Factory = notif_client
    caller_id = _make_user(Factory, email="caller@x.com")
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    _make_notification(Factory, caller_id, kind="job_complete")
    _make_notification(Factory, caller_id, kind="low_credits")
    _make_notification(Factory, other_id, kind="job_failed")  # must NOT appear

    resp = client.get("/api/v1/me/notifications", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["unread_count"] == 2
    assert len(data["notifications"]) == 2
    kinds = {n["kind"] for n in data["notifications"]}
    assert kinds == {"job_complete", "low_credits"}
    for n in data["notifications"]:
        assert n["id"]
        assert n["read"] is False
        assert "data" in n


def test_list_unread_only_filter(notif_client):
    client, Factory = notif_client
    uid = _make_user(Factory)
    read_id = _make_notification(Factory, uid, kind="job_complete")
    _make_notification(Factory, uid, kind="low_credits")  # stays unread
    # Flip one to read out of band.
    with Factory() as s:
        NotificationRepository(s).mark_read(read_id, uid)
        s.commit()

    resp = client.get(
        "/api/v1/me/notifications?unread_only=true", headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # Only the still-unread row is listed, but unread_count reflects the total.
    assert len(data["notifications"]) == 1
    assert data["notifications"][0]["kind"] == "low_credits"
    assert data["unread_count"] == 1


def test_list_limit_is_honoured(notif_client):
    client, Factory = notif_client
    uid = _make_user(Factory)
    for _ in range(5):
        _make_notification(Factory, uid)

    resp = client.get("/api/v1/me/notifications?limit=2", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # The page is capped, but the unread_count still counts every unread row.
    assert len(data["notifications"]) == 2
    assert data["unread_count"] == 5


def test_list_requires_auth_401(notif_client):
    client, Factory = notif_client
    resp = client.get("/api/v1/me/notifications")  # no x-api-key
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# GET /me/notifications/unread_count
# =========================================================================== #
def test_unread_count_endpoint(notif_client):
    client, Factory = notif_client
    uid = _make_user(Factory)
    _make_notification(Factory, uid)
    _make_notification(Factory, uid)

    resp = client.get(
        "/api/v1/me/notifications/unread_count", headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["unread_count"] == 2


def test_unread_count_requires_auth_401(notif_client):
    client, Factory = notif_client
    resp = client.get("/api/v1/me/notifications/unread_count")
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# POST /me/notifications/{id}/read
# =========================================================================== #
def test_mark_one_read_flips_and_decrements_count(notif_client):
    client, Factory = notif_client
    uid = _make_user(Factory)
    rid = _make_notification(Factory, uid)
    _make_notification(Factory, uid)  # a second, still-unread row

    resp = client.post(
        f"/api/v1/me/notifications/{rid}/read", headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["read"] is True

    # The flipped row is persisted read; only the other row remains unread.
    with Factory() as s:
        assert s.get(Notification, rid).read is True
        assert NotificationRepository(s).unread_count(uid) == 1


def test_mark_foreign_read_404_and_untouched(notif_client):
    client, Factory = notif_client
    # Notification owned by a DIFFERENT user; the caller must not flip it.
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    victim_rid = _make_notification(Factory, other_id)
    _make_user(Factory, email="caller@x.com")  # the x-api-key caller

    resp = client.post(
        f"/api/v1/me/notifications/{victim_rid}/read", headers=_HEADERS
    )
    assert resp.status_code == 404, resp.text
    # The foreign row survives unread.
    with Factory() as s:
        assert s.get(Notification, victim_rid).read is False


def test_mark_unknown_read_404(notif_client):
    client, Factory = notif_client
    _make_user(Factory)
    resp = client.post(
        "/api/v1/me/notifications/does-not-exist/read", headers=_HEADERS
    )
    assert resp.status_code == 404, resp.text


def test_mark_read_requires_auth_401(notif_client):
    client, Factory = notif_client
    uid = _make_user(Factory)
    rid = _make_notification(Factory, uid)
    resp = client.post(f"/api/v1/me/notifications/{rid}/read")  # no key
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# POST /me/notifications/read_all
# =========================================================================== #
def test_read_all_zeroes_unread(notif_client):
    client, Factory = notif_client
    caller_id = _make_user(Factory, email="caller@x.com")
    other_id = _make_user(
        Factory, email="other@x.com", key_hash=hashlib.sha256(b"o").hexdigest()
    )
    for _ in range(3):
        _make_notification(Factory, caller_id)
    _make_notification(Factory, other_id)  # another user's — must stay unread

    resp = client.post("/api/v1/me/notifications/read_all", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["updated"] == 3
    assert body["unread_count"] == 0

    # The caller is fully read; the other user's notification is untouched.
    with Factory() as s:
        repo = NotificationRepository(s)
        assert repo.unread_count(caller_id) == 0
        assert repo.unread_count(other_id) == 1


def test_read_all_requires_auth_401(notif_client):
    client, Factory = notif_client
    resp = client.post("/api/v1/me/notifications/read_all")  # no key
    assert resp.status_code == 401, resp.text
