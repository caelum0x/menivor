"""SEO HTTP routes: connect, overview, audit, keyword research, rank tracker."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.domains.seo import router as seo_router
from app.models.exception import HttpException
from tests.reelforge._integrations_fakes import FakeTransport, Resp, add_user, add_workspace
from tests.reelforge.test_seo import MCP, _init_resp, _rpc_result, _make_db


@pytest.fixture()
def ctx(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-seo-router-key")
    db = _make_db()
    monkeypatch.setattr(seo_router, "get_session", db.scope)
    monkeypatch.setattr(seo_router, "require_database", lambda rid: None)
    monkeypatch.setattr(seo_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(seo_router, "resolve_principal",
                        lambda request, session, rid: SimpleNamespace(id=request.headers["x-test-user"]))
    transport = FakeTransport()
    seo_router.set_transport(transport)
    app = FastAPI()
    app.add_exception_handler(HttpException, lambda request, exc: JSONResponse(
        status_code=exc.status_code, content={"status": exc.status_code, "message": exc.message}))
    app.include_router(seo_router.router)
    owner = add_user(db, "owner@example.com")
    member = add_user(db, "member@example.com")
    ws = add_workspace(db, owner, members=[(member, "member")])
    return SimpleNamespace(db=db, client=TestClient(app), t=transport, owner=owner, member=member, ws=ws)


def _get(ctx, path, user, **params):
    return ctx.client.get(f"/api/v1{path}", params=params, headers={"x-test-user": user})


def _post(ctx, path, user, body=None, **params):
    return ctx.client.post(f"/api/v1{path}", params=params, json=body, headers={"x-test-user": user})


def _delete(ctx, path, user, **params):
    return ctx.client.delete(f"/api/v1{path}", params=params, headers={"x-test-user": user})


def test_overview_before_connect(ctx):
    res = _get(ctx, "/seo/overview", ctx.owner, workspace_id=ctx.ws)
    assert res.status_code == 200 and res.json()["data"] == {"connected": False, "can_manage": True}


def test_connect_overview_and_disconnect_round_trip(ctx):
    ctx.t.add("POST", MCP, _init_resp(), Resp(200, _rpc_result([{"id": "proj_1", "domain": "shop.example.com"}])))
    res = _post(ctx, "/seo/connect", ctx.owner, {"api_key": "oseo_live_key_12345", "domain": "shop.example.com"},
               workspace_id=ctx.ws)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["project_id"] == "proj_1"
    assert "oseo_live_key_12345" not in res.text

    res2 = _get(ctx, "/seo/overview", ctx.owner, workspace_id=ctx.ws)
    assert res2.json()["data"]["connected"] is True

    out = _delete(ctx, "/seo", ctx.owner, workspace_id=ctx.ws)
    assert out.status_code == 200 and out.json()["data"]["disconnected"] is True


def test_member_cannot_connect(ctx):
    res = _post(ctx, "/seo/connect", ctx.member, {"api_key": "oseo_live_key_12345"}, workspace_id=ctx.ws)
    assert res.status_code == 403


def test_research_and_rank_tracker_routes(ctx):
    # The MCP endpoint answers both the ``initialize`` and ``tools/call`` legs of
    # each tool call on the same URL; each network-touching step below gets its
    # own fresh transport so one round's responses never leak into the next.
    seo_router.set_transport(FakeTransport().add(
        "POST", MCP, _init_resp(), Resp(200, _rpc_result([{"id": "proj_1", "domain": ""}]))))
    _post(ctx, "/seo/connect", ctx.owner, {"api_key": "oseo_live_key_12345"}, workspace_id=ctx.ws)

    seo_router.set_transport(FakeTransport().add(
        "POST", MCP, _init_resp(), Resp(200, _rpc_result([
            {"keyword": "project tracker", "volume": 500, "cpc": 2.5}]))))
    res = _post(ctx, "/seo/keywords/research", ctx.owner, {"seeds": ["project tracker"]}, workspace_id=ctx.ws)
    assert res.status_code == 200 and res.json()["data"]["keywords"][0]["keyword"] == "project tracker"

    listed = _get(ctx, "/seo/keywords/research", ctx.owner, workspace_id=ctx.ws)
    assert len(listed.json()["data"]["keywords"]) == 1

    seo_router.set_transport(FakeTransport().add(
        "POST", MCP, *([_init_resp(), Resp(200, _rpc_result({}))] * 2)))
    added = _post(ctx, "/seo/rank-tracker/keywords", ctx.owner, {"keywords": ["project tracker"], "country": "us"},
                 workspace_id=ctx.ws)
    assert added.status_code == 200
    keyword_id = added.json()["data"]["keywords"][0]["id"]

    removed = _delete(ctx, f"/seo/rank-tracker/keywords/{keyword_id}", ctx.owner, workspace_id=ctx.ws)
    assert removed.status_code == 200 and removed.json()["data"]["removed"] is True


def test_research_route_rejects_too_many_seeds(ctx):
    ctx.t.add("POST", MCP, _init_resp(), Resp(200, _rpc_result([{"id": "proj_1", "domain": ""}])))
    _post(ctx, "/seo/connect", ctx.owner, {"api_key": "oseo_live_key_12345"}, workspace_id=ctx.ws)
    res = _post(ctx, "/seo/keywords/research", ctx.owner,
               {"seeds": [f"kw{i}" for i in range(service_max() + 1)]}, workspace_id=ctx.ws)
    assert res.status_code == 422


def service_max() -> int:
    from app.domains.seo import service

    return service.MAX_RESEARCH_SEEDS
