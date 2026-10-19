"""Winning Hook Ranker HTTP route: auth + per-user rate limit.

``POST /api/v1/growth/rank-hooks`` spends TypeSafe/Jev credits, so it must:

* reject a caller with no credential or an unknown ``x-api-key`` with ``401``
  (before the body is validated, so probes learn nothing);
* rank for an authenticated principal (``200``);
* return ``429`` once that user's hourly budget is exhausted, without the
  budget of one user affecting another.

The Jev call itself is stubbed (no network, no key) and the Redis limiter is
replaced by an in-memory fixed window, exercising the real
``enforce_rate_limit`` 429 path.
"""

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

from app.domains.growth.hook_ranker import HookRanking
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.services import ratelimit
from app.utils import utils

# The package re-exports the APIRouter as ``router``; load the module itself.
growth_router = importlib.import_module("app.domains.growth.router")

BODY = {"variants": [{"id": "h1", "text": "How I edited 30 reels in one afternoon"}]}


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as s:
        s.add_all(
            [
                User(email="a@ex.com", api_key_hash=_key_hash("alice-key")),
                User(email="b@ex.com", api_key_hash=_key_hash("bob-key")),
            ]
        )
        s.commit()

    @contextmanager
    def _session():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(growth_router, "get_session", _session)

    calls: list[int] = []

    async def _fake_rank(variants, context):
        calls.append(len(variants))
        return HookRanking(ranked=[], winner=None, recommended_angle="", degraded=True, note="stub")

    monkeypatch.setattr(growth_router, "rank_hooks", _fake_rank)

    counters: dict[str, int] = {}

    def _fake_rate_limit(key: str, limit: int, window_s: int):
        counters[key] = counters.get(key, 0) + 1
        current = counters[key]
        return ratelimit.RateLimitResult(
            allowed=current <= limit, remaining=max(0, limit - current), reset_s=window_s
        )

    monkeypatch.setattr(ratelimit, "rate_limit", _fake_rate_limit)
    monkeypatch.setattr(growth_router, "RANK_HOOKS_LIMIT_PER_HOUR", 2)

    app = FastAPI()
    app.include_router(growth_router.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), calls


def test_missing_credential_is_401_and_spends_nothing(client):
    tc, calls = client
    res = tc.post("/api/v1/growth/rank-hooks", json=BODY)
    assert res.status_code == 401
    assert calls == []


def test_missing_credential_is_401_even_with_invalid_body(client):
    tc, calls = client
    res = tc.post("/api/v1/growth/rank-hooks", json={"variants": []})
    assert res.status_code == 401
    assert calls == []


def test_unknown_api_key_is_401(client):
    tc, calls = client
    res = tc.post("/api/v1/growth/rank-hooks", json=BODY, headers={"x-api-key": "not-a-real-key"})
    assert res.status_code == 401
    assert calls == []


def test_authenticated_caller_is_ranked(client):
    tc, calls = client
    res = tc.post("/api/v1/growth/rank-hooks", json=BODY, headers={"x-api-key": "alice-key"})
    assert res.status_code == 200
    assert res.json()["data"]["degraded"] is True
    assert calls == [1]


def test_per_user_rate_limit_returns_429(client):
    tc, calls = client
    alice = {"x-api-key": "alice-key"}
    assert tc.post("/api/v1/growth/rank-hooks", json=BODY, headers=alice).status_code == 200
    assert tc.post("/api/v1/growth/rank-hooks", json=BODY, headers=alice).status_code == 200
    limited = tc.post("/api/v1/growth/rank-hooks", json=BODY, headers=alice)
    assert limited.status_code == 429
    assert len(calls) == 2
    # Another user's budget is independent.
    bob = tc.post("/api/v1/growth/rank-hooks", json=BODY, headers={"x-api-key": "bob-key"})
    assert bob.status_code == 200
    assert len(calls) == 3
