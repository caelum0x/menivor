"""Brand Agent HTTP surface: sessions, messages, chips, SSE stream, Brain, actions,
routines, inspirations, skills, folders, library, connectors and the credits meter.

In-memory SQLite behind a FastAPI TestClient; every port is a fake.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.brand_agent import router as router_mod
from app.domains.brand_agent import setup_flow
from app.models.db.models import CreditLedger
from app.models.exception import HttpException
from app.utils import utils
from tests.reelforge._brand_agent_support import SITE_URL, make_deps, make_factory, make_user

H = {"x-api-key": "owner@example.com"}
OTHER = {"x-api-key": "other@example.com"}


@pytest.fixture()
def env(monkeypatch):
    db = make_factory()
    deps = make_deps()
    monkeypatch.setattr(router_mod, "get_session", db.scope)
    monkeypatch.setattr(router_mod, "build_deps", lambda request=None: deps)
    app = FastAPI()
    app.include_router(router_mod.router)
    app.add_exception_handler(HttpException, lambda request, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    uid = make_user(db, "owner@example.com")
    make_user(db, "other@example.com")
    return TestClient(app), db, deps, uid


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _setup(client):
    sid = _data(client.post("/api/v1/agent/sessions", headers=H, json={}))["session"]["id"]
    _data(client.post(f"/api/v1/agent/sessions/{sid}/messages", headers=H,
                      json={"text": f"set up my brand from my website: {SITE_URL}"}))
    for step in (setup_flow.STEP_POSITIONING, setup_flow.STEP_PRODUCT, setup_flow.STEP_MARKET, setup_flow.STEP_VOICE):
        _data(client.post(f"/api/v1/agent/sessions/{sid}/chips", headers=H, json={"step": step, "choice": "yes"}))
    _data(client.post(f"/api/v1/agent/sessions/{sid}/chips", headers=H,
                      json={"step": setup_flow.STEP_META, "choice": "skip"}))
    return sid


def test_setup_over_http_fills_the_brain(env):
    client, *_ = env
    sid = _setup(client)
    overview = _data(client.get("/api/v1/agent/overview", headers=H))
    space_id = overview["space"]["id"]
    assert overview["brain"]["unseen"] == 4 and overview["brain"]["version"] == 4
    assert overview["recents"][0]["id"] == sid
    brain = _data(client.get(f"/api/v1/agent/spaces/{space_id}/memory", headers=H))
    assert set(brain["sections"]) == {"positioning", "product", "market", "voice_audience"}
    _data(client.post(f"/api/v1/agent/spaces/{space_id}/memory/seen", headers=H))
    assert _data(client.get("/api/v1/agent/overview", headers=H))["brain"]["unseen"] == 0


def test_brain_edit_creates_a_version(env):
    client, *_ = env
    _setup(client)
    space_id = _data(client.get("/api/v1/agent/overview", headers=H))["space"]["id"]
    pos = _data(client.get(f"/api/v1/agent/spaces/{space_id}/memory", headers=H))["sections"]["positioning"]
    edited = _data(client.put(f"/api/v1/agent/spaces/{space_id}/memory/positioning", headers=H,
                              json={"data": {**pos, "pricing_hook": "Flat $25 a project"}}))
    assert edited["version"] == 5
    history = _data(client.get(f"/api/v1/agent/spaces/{space_id}/memory/history?section=positioning", headers=H))
    assert [h["version"] for h in history["versions"]] == [5, 1]
    bad = client.put(f"/api/v1/agent/spaces/{space_id}/memory/nope", headers=H, json={"data": {}})
    assert bad.status_code == 400
    assert client.get(f"/api/v1/agent/spaces/{space_id}/memory", headers=OTHER).status_code == 404


def test_actions_need_approval_over_http(env):
    client, _, deps, _ = env
    sid = _setup(client)
    out = _data(client.post(f"/api/v1/agent/sessions/{sid}/messages", headers=H, json={"text": "make a video ad"}))
    action = next(m["action"] for m in out["messages"] if m.get("action"))
    pending = _data(client.get("/api/v1/agent/actions?status=pending", headers=H))["actions"]
    assert [a["id"] for a in pending] == [action["id"]]
    assert client.post(f"/api/v1/agent/actions/{action['id']}/approve", headers=OTHER).status_code == 404
    assert deps.generation.calls == []
    done = _data(client.post(f"/api/v1/agent/actions/{action['id']}/approve", headers=H))
    assert done["action"]["status"] == "executed" and len(deps.generation.calls) == 1
    library = _data(client.get("/api/v1/agent/library", headers=H))["items"]
    assert library[0]["action_id"] == action["id"]


def test_stream_emits_events_and_persists(env):
    client, *_ = env
    sid = _data(client.post("/api/v1/agent/sessions", headers=H, json={}))["session"]["id"]
    with client.stream("POST", f"/api/v1/agent/sessions/{sid}/stream", headers=H,
                       json={"text": f"set up my brand from my website: {SITE_URL}"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    events = [line[len("event: "):] for line in body.splitlines() if line.startswith("event: ")]
    assert events[0] == "start" and events[-1] == "done"
    assert "delta" in events and "message" in events
    datas = [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]
    assert any(d.get("card", {}) and d["card"].get("step") == "positioning" for d in datas if isinstance(d, dict))
    stored = _data(client.get(f"/api/v1/agent/sessions/{sid}", headers=H))["messages"]
    assert stored[0]["role"] == "user" and stored[-1]["card"]["step"] == "positioning"


def test_stream_chip_and_validation(env):
    client, *_ = env
    sid = _data(client.post("/api/v1/agent/sessions", headers=H, json={}))["session"]["id"]
    assert client.post(f"/api/v1/agent/sessions/{sid}/stream", headers=H, json={}).status_code == 422
    assert client.post(f"/api/v1/agent/sessions/{sid}/messages", headers=OTHER, json={"text": "hi"}).status_code == 404


def test_routines_inspirations_skills_folders(env):
    client, *_ = env
    _setup(client)
    r = _data(client.post("/api/v1/agent/routines", headers=H,
                          json={"text": "3 new ad variations every Monday"}))["routine"]
    assert r["count"] == 3 and r["requires_approval"] is True
    _data(client.patch(f"/api/v1/agent/routines/{r['id']}", headers=H, json={"enabled": False}))
    assert _data(client.get("/api/v1/agent/routines", headers=H))["routines"][0]["enabled"] is False
    assert client.post("/api/v1/agent/routines", headers=H, json={"text": "whenever"}).status_code == 400

    ins = _data(client.post("/api/v1/agent/inspirations", headers=H,
                            json={"url": "https://www.tiktok.com/@a/video/1", "title": "Great hook"}))["inspiration"]
    assert ins["kind"] == "tiktok"
    assert client.post("/api/v1/agent/inspirations", headers=H, json={"url": "javascript:alert(1)"}).status_code == 422
    assert len(_data(client.get("/api/v1/agent/inspirations", headers=H))["inspirations"]) == 1

    skills = _data(client.get("/api/v1/agent/skills", headers=H))["skills"]
    ids = {s["id"] for s in skills}
    assert {"ugc_script", "ad_clone", "hook_variations"} <= ids
    custom = _data(client.post("/api/v1/agent/skills", headers=H,
                               json={"name": "Founder story", "instructions": "Open with the founder's problem."}))
    assert custom["skill"]["builtin"] is False

    folder = _data(client.post("/api/v1/agent/folders", headers=H, json={"name": "Launch week"}))["folder"]
    assert _data(client.get("/api/v1/agent/folders", headers=H))["folders"][0]["id"] == folder["id"]


def test_library_items_move_into_folders(env):
    client, _, deps, _ = env
    sid = _setup(client)
    out = _data(client.post(f"/api/v1/agent/sessions/{sid}/messages", headers=H, json={"text": "make an image"}))
    action = next(m["action"] for m in out["messages"] if m.get("action"))
    _data(client.post(f"/api/v1/agent/actions/{action['id']}/approve", headers=H))
    item = _data(client.get("/api/v1/agent/library", headers=H))["items"][0]
    folder = _data(client.post("/api/v1/agent/folders", headers=H, json={"name": "Ads"}))["folder"]
    moved = _data(client.patch(f"/api/v1/agent/library/{item['id']}", headers=H, json={"folder_id": folder["id"]}))
    assert moved["item"]["folder_id"] == folder["id"]
    in_folder = _data(client.get(f"/api/v1/agent/library?folder_id={folder['id']}", headers=H))["items"]
    assert len(in_folder) == 1


def test_credits_meter_reads_the_ledger(env):
    client, db, _, uid = env
    with db() as s:
        s.add(CreditLedger(user_id=uid, delta=3, reason="signup", balance_after=3))
        s.add(CreditLedger(user_id=uid, delta=-1, reason="job_debit", balance_after=2))
        s.commit()
    credits = _data(client.get("/api/v1/agent/credits", headers=H))
    assert credits["balance"] == 2 and credits["trial_grant"] == 3 and credits["used"] == 1


def test_connectors_report_honest_state(env):
    client, *_ = env
    connectors = _data(client.get("/api/v1/agent/connectors", headers=H))["connectors"]
    by_id = {c["id"]: c for c in connectors}
    assert by_id["meta_ads"]["status"] in {"not_connected", "connected", "unavailable"}
    assert {"meta_ads", "tiktok", "web_search", "ad_clone"} <= set(by_id)


def test_requires_auth(env):
    client, *_ = env
    assert client.get("/api/v1/agent/overview").status_code in {401, 403}
