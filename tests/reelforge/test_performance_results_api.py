"""Results page API: auth, pasted links, typed numbers, owner scoping."""

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

import app.domains.performance.router as router_mod
from app.domains.performance import fetchers, tracker
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

_KEYS = {"owner": "owner-key", "other": "other-key"}


class _NoNetwork:
    def request(self, *args, **kwargs):  # pragma: no cover - asserts the test stays offline
        raise AssertionError("no network in API tests")


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with Factory() as s:
        for name, key in _KEYS.items():
            s.add(User(email=f"{name}@example.com", api_key_hash=hashlib.sha256(key.encode()).hexdigest(),
                       credits=0))
        s.commit()

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

    monkeypatch.setattr(router_mod, "get_session", _session)
    monkeypatch.setattr(router_mod, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(router_mod, "_connected", lambda session, user_id: {})
    monkeypatch.setattr(tracker, "_default_session_factory", lambda: _session)
    monkeypatch.setattr(tracker, "default_access", lambda user_id, platform: fetchers.NO_ACCESS)
    monkeypatch.setattr(fetchers, "default_transport", lambda: _NoNetwork())

    app = FastAPI()
    app.include_router(router_mod.router)
    app.add_exception_handler(
        HttpException,
        lambda request, exc: JSONResponse(status_code=exc.status_code,
                                          content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app)


def _h(who: str) -> dict:
    return {"x-api-key": _KEYS[who]}


def test_results_require_auth(client):
    assert client.get("/api/v1/me/results").status_code == 401


def test_empty_results(client):
    resp = client.get("/api/v1/me/results", headers=_h("owner"))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["has_data"] is False and data["posts"] == []


def test_bad_link_is_a_plain_400(client):
    resp = client.post("/api/v1/me/tracked-posts", json={"url": "https://example.com/x"}, headers=_h("owner"))
    assert resp.status_code == 400
    assert "TikTok" in resp.json()["message"]


def test_paste_link_type_numbers_and_owner_scoping(client, monkeypatch):
    # TikTok is not connected, so the post waits for access (no network call is made).
    resp = client.post("/api/v1/me/tracked-posts",
                       json={"url": "https://www.tiktok.com/@maker/video/7300000000000000001"}, headers=_h("owner"))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    post = data["posts"][0]
    assert post["id"] == data["added_post_id"] and post["state"] == "needs_access"
    assert post["views"] is None and post["can_type_numbers"] is True

    other = client.post(f"/api/v1/me/tracked-posts/{post['id']}/numbers", json={"views": 5}, headers=_h("other"))
    assert other.status_code == 404

    typed = client.post(f"/api/v1/me/tracked-posts/{post['id']}/numbers", json={"views": 1500, "likes": 90},
                        headers=_h("owner"))
    assert typed.status_code == 200
    result = typed.json()["data"]
    assert result["totals"]["views"] == 1500 and result["has_data"] is True

    assert client.post(f"/api/v1/me/tracked-posts/{post['id']}/numbers", json={"views": -1},
                       headers=_h("owner")).status_code == 422
    assert client.delete(f"/api/v1/me/tracked-posts/{post['id']}", headers=_h("other")).status_code == 404
    gone = client.delete(f"/api/v1/me/tracked-posts/{post['id']}", headers=_h("owner"))
    assert gone.status_code == 200 and gone.json()["data"]["posts"] == []
