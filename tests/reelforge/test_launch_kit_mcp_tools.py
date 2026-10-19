"""The 6 Launch Kit tools exposed through the hosted MCP connector (mirrors the
tool-level assertions in tests/reelforge/test_wave2_mcp.py, but calls
app.domains.mcp_hosted.tools.call directly instead of going through the full
JSON-RPC session, since these tools need no brand space / workspace setup).
"""

from __future__ import annotations

import pytest

from app.domains.mcp_hosted import tools
from app.domains.mcp_hosted.tools import ToolContext
from tests.reelforge._wave2_support import make_env

TOOL_NAMES = (
    "list_launch_platforms", "set_launch_platform_status", "find_pain_point_threads",
    "find_competitor_backlinks", "get_launch_checklist", "mark_playbook_step",
)


@pytest.fixture()
def env(monkeypatch):
    return make_env(monkeypatch)


def _ctx(env, session, scopes=("read", "write")):
    return ToolContext(session=session, user_id=env.uid, workspace_id=None, scopes=scopes)


def test_all_six_tools_are_registered_and_scoped():
    names = {t.name: t.scope for t in tools.TOOLS}
    assert names["list_launch_platforms"] == "read"
    assert names["set_launch_platform_status"] == "write"
    assert names["find_pain_point_threads"] == "write"
    assert names["find_competitor_backlinks"] == "read"
    assert names["get_launch_checklist"] == "read"
    assert names["mark_playbook_step"] == "write"
    for name in TOOL_NAMES:
        assert name in names


def test_list_launch_platforms_tool(env):
    with env.db.scope() as s:
        out = tools.call(_ctx(env, s), "list_launch_platforms", {"product_category": "ai"})
    assert out["isError"] is False
    assert out["structuredContent"]["platforms"]


def test_set_launch_platform_status_tool_requires_fields(env):
    with env.db.scope() as s:
        with pytest.raises(tools.ToolError):
            tools.call(_ctx(env, s), "set_launch_platform_status", {"product_name": "Menivor"})


def test_set_launch_platform_status_tool_persists(env):
    with env.db.scope() as s:
        out = tools.call(_ctx(env, s), "set_launch_platform_status",
                         {"product_name": "Menivor", "platform_id": "product_hunt", "status": "submitted"})
    assert out["structuredContent"]["status"] == "submitted"
    with env.db.scope() as s:
        again = tools.call(_ctx(env, s), "list_launch_platforms", {"product_name": "Menivor"})
    row = next(p for p in again["structuredContent"]["platforms"] if p["id"] == "product_hunt")
    assert row["status"] == "submitted"


def test_find_pain_point_threads_tool_never_posts(env, monkeypatch):
    def fake_search(_transport, *, query, subreddits=None, limit=10, now=None):
        from app.domains.launch_kit.reddit_search import RedditThread

        return [RedditThread(url="https://www.reddit.com/r/saas/comments/1/x/", title="Help with churn",
                             snippet="We lose users in week 2", subreddit="saas", upvotes=10, age_days=2,
                             permalink="/r/saas/comments/1/x/")]

    monkeypatch.setattr("app.domains.launch_kit.reddit_search.search", fake_search)
    with env.db.scope() as s:
        out = tools.call(_ctx(env, s), "find_pain_point_threads", {"query": "churn", "product_name": "Menivor"})
    assert out["isError"] is False
    threads = out["structuredContent"]["threads"]
    assert len(threads) == 1
    assert "nothing here posts" in out["structuredContent"]["note"].lower()


def test_find_pain_point_threads_tool_requires_query(env):
    with env.db.scope() as s:
        with pytest.raises(tools.ToolError):
            tools.call(_ctx(env, s), "find_pain_point_threads", {})


def test_find_competitor_backlinks_tool_defaults_to_fallback(env, monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    with env.db.scope() as s:
        out = tools.call(_ctx(env, s), "find_competitor_backlinks", {"domain": "rival.com"})
    assert out["structuredContent"]["live"] is False
    assert out["structuredContent"]["fallback_directories"]


def test_find_competitor_backlinks_tool_requires_domain(env):
    with env.db.scope() as s:
        with pytest.raises(tools.ToolError):
            tools.call(_ctx(env, s), "find_competitor_backlinks", {})


def test_get_launch_checklist_tool(env):
    with env.db.scope() as s:
        out = tools.call(_ctx(env, s), "get_launch_checklist", {"product_name": "Menivor"})
    assert out["structuredContent"]["done"] == 0
    assert out["structuredContent"]["total"] > 0


def test_mark_playbook_step_tool_persists_and_reflects_in_checklist(env):
    with env.db.scope() as s:
        tools.call(_ctx(env, s), "mark_playbook_step",
                  {"product_name": "Menivor", "step_key": "build_in_public", "status": "done"})
    with env.db.scope() as s:
        out = tools.call(_ctx(env, s), "get_launch_checklist", {"product_name": "Menivor"})
    assert out["structuredContent"]["done"] == 1


def test_write_scoped_tools_are_hidden_from_a_read_only_scope(env):
    with env.db.scope() as s:
        ctx = _ctx(env, s, scopes=("read",))
        with pytest.raises(tools.ToolError):
            tools.call(ctx, "mark_playbook_step", {"product_name": "Menivor", "step_key": "build_in_public",
                                                   "status": "done"})
