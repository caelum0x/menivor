"""Hosted MCP tools for Buffer / Typefully stay off until the flag is on."""

from __future__ import annotations

import pytest

from app.domains.mcp_hosted import tools
from app.domains.mcp_hosted.tools import ToolContext
from app.domains.x_scheduler.flag import FLAG


def test_scheduler_tools_are_hidden_and_refused_while_the_flag_is_off(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    names = [tool["name"] for tool in tools.listing(("read", "write"))]
    assert "list_scheduler_accounts" not in names
    assert "schedule_to_buffer_or_typefully" not in names
    ctx = ToolContext(session=None, user_id="user", workspace_id=None, scopes=("read", "write"))
    with pytest.raises(tools.ToolError):
        tools.call(ctx, "schedule_to_buffer_or_typefully", {"provider": "buffer"})


def test_scheduler_tool_runs_when_the_flag_is_on(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    names = [tool["name"] for tool in tools.listing(("read", "write"))]
    assert "schedule_to_buffer_or_typefully" in names

    def fake_schedule(_session, user_id, **kwargs):
        assert user_id == "user-1"
        assert kwargs["provider"] == "typefully"
        assert kwargs["when"] == "queue"
        return {"provider": "typefully", "external_id": "42", "status": "queued",
                "message": "Added to your Typefully queue."}

    monkeypatch.setattr("app.domains.x_scheduler.service.schedule_post", fake_schedule)
    ctx = ToolContext(session=object(), user_id="user-1", workspace_id=None, scopes=("write",))
    out = tools.call(ctx, "schedule_to_buffer_or_typefully", {
        "provider": "typefully", "target_id": "9", "source": "render",
        "source_id": "render-1", "caption": "Hello", "when": "queue",
    })
    assert out["isError"] is False
    assert out["structuredContent"]["external_id"] == "42"


def test_flag_defaults_off():
    from app.domains.x_scheduler.flag import enabled

    assert enabled({}) is False
    assert enabled({FLAG: ""}) is False
    assert enabled({FLAG: "0"}) is False
    assert enabled({FLAG: "false"}) is False
    assert enabled({FLAG: "1"}) is True
    assert enabled({FLAG: " YES "}) is True
