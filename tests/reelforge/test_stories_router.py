"""Integration: POST /stories/reddit via TestClient (fetcher + auth stubbed)."""

from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

stories_mod = importlib.import_module("app.domains.stories.router")

_LISTING = json.dumps(
    [
        {
            "kind": "Listing",
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "title": "AITA for eating the cake?",
                            "subreddit": "AmItheAsshole",
                            "author": "op",
                            "selftext": "It was in the fridge with no name. I ate it. Was I wrong?",
                            "selftext_html": "",
                        },
                    }
                ]
            },
        },
        {"kind": "Listing", "data": {"children": []}},
    ]
)


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with Factory() as s:
        s.add(User(email="a@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest()))
        s.commit()

    @contextmanager
    def _gs():
        s = Factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(stories_mod, "get_session", _gs)
    monkeypatch.setattr(stories_mod, "_DB_IMPORT_ERROR", None)

    # Inject a fake fetcher on the service so no network is touched.
    import app.domains.stories.service as svc

    monkeypatch.setattr(svc, "default_fetch", lambda _u: _LISTING)

    app = FastAPI()
    app.include_router(stories_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app)


def test_reddit_endpoint_returns_draft(client):
    resp = client.post(
        "/api/v1/stories/reddit",
        json={"url": "https://www.reddit.com/r/AmItheAsshole/comments/abc/t/"},
        headers={"x-api-key": "k"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["reel_draft"]["background_id"] == "voxel-parkour"
    assert data["reel_draft"]["layout"] == "split"
    assert data["thread"]["subreddit"] == "AmItheAsshole"
    assert data["url"].endswith(".json")


def test_reddit_endpoint_requires_auth(client):
    resp = client.post(
        "/api/v1/stories/reddit",
        json={"url": "https://www.reddit.com/r/x/comments/abc/t/"},
    )
    assert resp.status_code == 401


def test_reddit_endpoint_rejects_malformed_url(client):
    resp = client.post(
        "/api/v1/stories/reddit",
        json={"url": "not-a-url"},
        headers={"x-api-key": "k"},
    )
    assert resp.status_code == 400, resp.text


def test_reddit_endpoint_forbids_extra_fields(client):
    resp = client.post(
        "/api/v1/stories/reddit",
        json={"url": "https://reddit.com/r/x/comments/abc/t/", "bogus": 1},
        headers={"x-api-key": "k"},
    )
    assert resp.status_code == 422


def test_reddit_endpoint_503_when_db_import_missing(client, monkeypatch):
    monkeypatch.setattr(stories_mod, "_DB_IMPORT_ERROR", RuntimeError("no db"))
    resp = client.post(
        "/api/v1/stories/reddit",
        json={"url": "https://reddit.com/r/x/comments/abc/t/"},
        headers={"x-api-key": "k"},
    )
    assert resp.status_code == 503
