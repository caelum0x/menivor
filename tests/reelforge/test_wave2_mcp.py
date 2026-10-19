"""Hosted MCP connector: workspace tokens, session binding, tools, and spending only through approvals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domains.brand_agent import memory, spaces
from app.domains.brand_agent.models import AgentAction
from app.domains.mcp_hosted import router as mcp_router
from app.domains.mcp_hosted import server, tokens, tools
from app.domains.mcp_hosted.models import McpToken
from app.models.db.models import Workspace, WorkspaceMember
from tests.reelforge._wave2_support import H, OTHER, client_for, data, make_env


@pytest.fixture()
def env(monkeypatch):
    env = make_env(monkeypatch, extra=("app.domains.mcp_hosted.router",))
    with env.db.scope() as s:
        space = spaces.ensure_default(s, env.uid)
        memory.write(s, env.uid, space.id, "positioning", {"name": "Brewly", "one_liner": "Coffee that costs less"})
        ws = Workspace(name="Brewly team", owner_id=env.uid)
        s.add(ws)
        s.flush()
        s.add(WorkspaceMember(workspace_id=ws.id, user_id=env.uid, role="owner"))
        s.add(WorkspaceMember(workspace_id=ws.id, user_id=env.other, role="member"))
        env.ws = ws.id
    env.client = client_for(mcp_router, monkeypatch=monkeypatch, db=env.db)
    return env


def _mint(env, headers=H, **body):
    return data(env.client.post("/api/v1/mcp/tokens", headers=headers, json={"name": "Claude", **body}))["token"]


def _rpc(env, token, method, params=None, msg_id=1, session_id=None):
    headers = {"Authorization": f"Bearer {token}"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return env.client.post("/api/v1/mcp", headers=headers,
                           json={"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})


def _open(env, token):
    resp = _rpc(env, token, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                           "clientInfo": {"name": "test", "version": "1"}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["protocolVersion"] == "2025-03-26"
    return resp.headers["Mcp-Session-Id"]


def _tool(env, token, sid, name, args=None):
    resp = _rpc(env, token, "tools/call", {"name": name, "arguments": args or {}}, session_id=sid)
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


def test_token_is_shown_once_and_only_its_digest_is_stored(env):
    minted = _mint(env)
    assert minted["token"].startswith("mnv_mcp_") and minted["prefix"] == minted["token"][:12]
    with env.db.scope() as s:
        row = s.query(McpToken).one()
        assert row.token_digest == tokens.digest(minted["token"]) and minted["token"] not in str(row.__dict__)
    listed = data(env.client.get("/api/v1/mcp/tokens", headers=H))["tokens"]
    assert "token" not in listed[0] and listed[0]["scopes"] == ["read", "write"]


def test_workspace_tokens_need_owner_or_admin(env):
    assert _mint(env, workspace_id=env.ws)["workspace_id"] == env.ws
    resp = env.client.post("/api/v1/mcp/tokens", headers=OTHER, json={"name": "x", "workspace_id": env.ws})
    assert resp.status_code == 403


def test_auth_session_binding_and_transport_rules(env):
    token = _mint(env)["token"]
    assert env.client.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    assert _rpc(env, "mnv_mcp_wrong", "initialize").status_code == 401
    sid = _open(env, token)
    assert _rpc(env, token, "ping").status_code == 400  # no session id
    other = _mint(env, headers=OTHER)["token"]
    assert _rpc(env, other, "tools/list", session_id=sid).status_code == 400  # foreign session id
    assert _rpc(env, token, "ping", session_id=sid).json()["result"] == {}
    note = env.client.post("/api/v1/mcp", headers={"Authorization": f"Bearer {token}", "Mcp-Session-Id": sid},
                           json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202
    assert env.client.get("/api/v1/mcp").status_code == 405
    evil = env.client.post("/api/v1/mcp", headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.test"},
                           json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert evil.status_code == 403
    assert _rpc(env, token, "nope/method", session_id=sid).json()["error"]["code"] == server.METHOD_NOT_FOUND


def test_revoked_and_expired_tokens_stop_working(env):
    minted = _mint(env)
    sid = _open(env, minted["token"])
    data(env.client.delete(f"/api/v1/mcp/tokens/{minted['id']}", headers=H))
    assert _rpc(env, minted["token"], "tools/list", session_id=sid).status_code == 401
    second = _mint(env)
    with env.db.scope() as s:
        s.get(McpToken, second["id"]).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert _rpc(env, second["token"], "initialize").status_code == 401


def test_read_scope_hides_write_tools(env):
    token = _mint(env, scopes=["read"])["token"]
    sid = _open(env, token)
    names = {t["name"] for t in _rpc(env, token, "tools/list", session_id=sid).json()["result"]["tools"]}
    assert "brand_memory_get" in names and "generate_video" not in names
    out = _tool(env, token, sid, "generate_video", {"prompt": "x"})
    assert out["isError"] is True


def test_brand_memory_tools(env):
    token = _mint(env)["token"]
    sid = _open(env, token)
    got = _tool(env, token, sid, "brand_memory_get")
    assert got["structuredContent"]["sections"]["positioning"]["name"] == "Brewly"
    saved = _tool(env, token, sid, "brand_memory_update",
                  {"section": "positioning", "data": {"name": "Brewly", "one_liner": "Better coffee for less"}})
    assert saved["structuredContent"]["version"] == 2
    bad = _tool(env, token, sid, "brand_memory_update", {"section": "secrets", "data": {}})
    assert bad["isError"] and "section must be one of" in bad["content"][0]["text"]


def test_generate_only_creates_pending_approvals(env):
    token = _mint(env)["token"]
    sid = _open(env, token)
    out = _tool(env, token, sid, "generate_video", {"prompt": "UGC ad for Brewly", "count": 3})
    payload = out["structuredContent"]
    assert payload["status"] == "pending_approval" and payload["credits_estimate"] == 15
    with env.db.scope() as s:
        action = s.get(AgentAction, payload["action_id"])
        assert action.status == "pending" and action.payload["requested_via"] == "mcp"
    assert env.deps.generation.calls == []
    waiting = _tool(env, token, sid, "approvals_list")["structuredContent"]
    assert waiting["agent_actions"][0]["id"] == payload["action_id"]
    assert not any("approve" == t.name.split("_")[-1] for t in tools.TOOLS)  # no tool can approve a spend


def test_ad_clone_tools_are_free_steps(env, monkeypatch):
    from app.domains.adclone import tracked_source

    brief = tracked_source.brief_from_copy(url="https://www.tiktok.com/@a/video/1", platform="tiktok",
                                           source_ref="tt:1", advertiser="Rival", body="Stop overpaying. Try us.")
    monkeypatch.setattr(mcp_router, "TOOL_OVERRIDES", {
        "analyze_link": lambda url, llm=None: brief,
        "clone": lambda b, preset_name, options: {"variations": [{"plan": {"slug": "oxhan-a"},
                                                                  "engine": {"engine": "kling", "usd": 2.1},
                                                                  "ai_video_credits": 630}]}})
    token = _mint(env)["token"]
    sid = _open(env, token)
    got = _tool(env, token, sid, "ad_clone_brief", {"url": "https://www.tiktok.com/@a/video/1"})
    assert got["structuredContent"]["spent"] == 0
    plan = _tool(env, token, sid, "ad_clone_plan", {"brief": got["structuredContent"]["brief"]})
    assert plan["structuredContent"]["variations"][0]["ai_video_credits"] == 630
    assert "paid renders need a person" in plan["structuredContent"]["next"]


def test_analytics_tools_respect_scope(env):
    token = _mint(env)["token"]
    sid = _open(env, token)
    fatigue = _tool(env, token, sid, "ad_fatigue")
    assert fatigue["structuredContent"]["creatives"] == []
    winners = _tool(env, token, sid, "competitor_winners")
    assert winners["structuredContent"]["ads"] == []
    report = _tool(env, token, sid, "analytics_report")
    assert report["isError"] is False


def test_batch_and_connector_info(env):
    token = _mint(env)["token"]
    sid = _open(env, token)
    resp = env.client.post("/api/v1/mcp", headers={"Authorization": f"Bearer {token}", "Mcp-Session-Id": sid},
                           json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                 {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
    assert [r["id"] for r in resp.json()] == [1, 2]
    info = data(env.client.get("/api/v1/mcp/connector", headers=H))
    assert info["url"].endswith("/api/v1/mcp") and "claude mcp add" in info["claude_code"]
    assert len(info["tools"]) == len([t for t in tools.TOOLS if t.on()])


# --------------------------------------------------------------------------- #
# Preset shelf on the hosted connector (behind MCP_PRESETS_LIVE)
# --------------------------------------------------------------------------- #
def _shelf(monkeypatch):
    from app.domains.presets_hub import previews
    from tests.reelforge.test_wp_pm3_0_steward import _entry

    monkeypatch.setattr(previews, "load_manifest", lambda: {"crash-zoom": _entry("crash-zoom", None)})


def test_presets_tools_hidden_and_refused_while_flag_off(env, monkeypatch):
    monkeypatch.delenv("MCP_PRESETS_LIVE", raising=False)
    token = _mint(env)["token"]
    sid = _open(env, token)
    names = {t["name"] for t in _rpc(env, token, "tools/list", session_id=sid).json()["result"]["tools"]}
    assert "presets_list" not in names and "presets_recreate" not in names
    out = _tool(env, token, sid, "presets_list")
    assert out["isError"] is True and "unknown tool" in out["content"][0]["text"]
    info = data(env.client.get("/api/v1/mcp/connector", headers=H))
    assert "presets_list" not in {t["name"] for t in info["tools"]}


def test_presets_tools_list_and_recreate_when_live(env, monkeypatch):
    monkeypatch.setenv("MCP_PRESETS_LIVE", "1")
    _shelf(monkeypatch)
    token = _mint(env, scopes=["read"])["token"]  # read-only tokens get the shelf: nothing is spent
    sid = _open(env, token)
    listed = {t["name"]: t for t in _rpc(env, token, "tools/list", session_id=sid).json()["result"]["tools"]}
    assert listed["presets_list"]["annotations"]["readOnlyHint"] is True
    assert listed["presets_recreate"]["inputSchema"]["required"] == ["subject"]
    shelf = _tool(env, token, sid, "presets_list")["structuredContent"]["presets"]
    assert [t["id"] for t in shelf] == ["crash-zoom"] and "prompt_template" not in shelf[0]
    plan = _tool(env, token, sid, "presets_recreate", {"preset_id": "crash-zoom", "subject": "espresso"})
    assert plan["isError"] is False and plan["structuredContent"]["route"] == "jobs"
    missing = _tool(env, token, sid, "presets_recreate", {"preset_id": "orbit", "subject": "x"})
    assert missing["isError"] is True and "preset not found" in missing["content"][0]["text"]
    assert env.deps.generation.calls == []
