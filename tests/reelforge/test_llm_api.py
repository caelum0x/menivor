"""Auth regression tests for ``app.controllers.v1.llm``.

Every LLM endpoint spends the operator's paid Anthropic quota, so all three
routes MUST be gated behind the shared ``base.verify_token`` check
(``x-api-key`` / Clerk JWT). These tests pin that gate closed: an anonymous
request never reaches the LLM service (no token drain), while a request with a
valid ``x-api-key`` succeeds.

No network is hit: the LLM service functions are monkeypatched, so a leaked
route would be caught by both the ``401`` assertion *and* the "LLM was called"
spy.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.llm as llm_mod
from app.config import config
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "test-llm-key"
_HEADERS = {"x-api-key": _API_KEY}

# Every guarded route -> a minimal valid body (all schema fields have defaults).
_ROUTES = (
    "/api/v1/scripts",
    "/api/v1/terms",
    "/api/v1/social-metadata",
)


@pytest.fixture()
def llm_client(monkeypatch):
    """TestClient wired to the llm router with the LLM service spied/stubbed.

    ``called`` records every time an LLM service function is invoked so a test
    can assert the paid provider was *never* touched on an unauthenticated call.
    Returns ``(client, called)``.
    """
    # Pin the shared api-key gate to a known value for the whole test.
    monkeypatch.setitem(config.app, "api_key", _API_KEY)

    called: dict[str, int] = {"n": 0}

    def _spy_script(*args, **kwargs) -> str:
        called["n"] += 1
        return "generated script"

    def _spy_terms(*args, **kwargs) -> list[str]:
        called["n"] += 1
        return ["term one", "term two"]

    def _spy_social(*args, **kwargs) -> dict:
        called["n"] += 1
        return {"title": "t", "description": "d", "hashtags": ["#a"]}

    monkeypatch.setattr(llm_mod.llm, "generate_script", _spy_script)
    monkeypatch.setattr(llm_mod.llm, "generate_terms", _spy_terms)
    monkeypatch.setattr(llm_mod.llm, "generate_social_metadata", _spy_social)

    app = FastAPI()
    app.include_router(llm_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), called


@pytest.mark.parametrize("route", _ROUTES)
def test_llm_route_requires_auth_401(llm_client, route):
    client, called = llm_client
    resp = client.post(route, json={})  # no x-api-key
    assert resp.status_code == 401, resp.text
    # The paid provider must never be reached on an unauthenticated request.
    assert called["n"] == 0


@pytest.mark.parametrize("route", _ROUTES)
def test_llm_route_rejects_wrong_key_401(llm_client, route):
    client, called = llm_client
    resp = client.post(route, json={}, headers={"x-api-key": "not-the-key"})
    assert resp.status_code == 401, resp.text
    assert called["n"] == 0


@pytest.mark.parametrize("route", _ROUTES)
def test_llm_route_allows_valid_key_200(llm_client, route):
    client, called = llm_client
    resp = client.post(route, json={}, headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    # Auth passed -> the (stubbed) LLM service was invoked exactly once.
    assert called["n"] == 1
