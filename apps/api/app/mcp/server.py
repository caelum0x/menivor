"""Stdio MCP server exposing ReelForge tools to agents.

Thin wrapper over :mod:`app.mcp.tools`: authenticates the operator (a ReelForge
user API key in ``REELFORGE_MCP_API_KEY``) to a user, opens a DB session per
call, and dispatches. The ``mcp`` SDK import is guarded so this module imports
even when the SDK is absent; ``main()`` then exits with a clear message.

Run:  ``REELFORGE_MCP_API_KEY=sk-... python -m app.mcp.server``
"""

from __future__ import annotations

import hashlib
import os
import sys

from loguru import logger

from app.mcp.tools import MCPToolError, dispatch, tool_specs


def _resolve_user_id(session, api_key: str) -> str:
    """Resolve a ReelForge user id from an API key (sha256 of the raw key)."""
    from app.models.db.models import User

    key_hash = hashlib.sha256(str(api_key or "").encode("utf-8")).hexdigest()
    user = session.query(User).filter(User.api_key_hash == key_hash).first()
    if user is None:
        raise MCPToolError("invalid REELFORGE_MCP_API_KEY")
    return user.id


def run_tool(name: str, args: dict | None = None, *, api_key: str | None = None) -> dict:
    """Auth + open a session + dispatch a single tool call (used by the server)."""
    from app.models.db.base import get_session

    key = api_key or os.getenv("REELFORGE_MCP_API_KEY", "")
    with get_session() as session:
        user_id = _resolve_user_id(session, key)
        return dispatch(session, user_id, name, args or {})


def main() -> int:  # pragma: no cover - requires the mcp SDK + a live stdio client
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as types
    except Exception as exc:
        logger.error(
            f"the 'mcp' SDK is required to run the stdio server: {exc}. "
            "Install it (pip install mcp) or call app.mcp.tools.dispatch in-process."
        )
        return 1

    import anyio

    server = Server("reelforge")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=spec["name"],
                description=spec["description"],
                inputSchema=spec["input_schema"],
            )
            for spec in tool_specs()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        import json

        try:
            result = await anyio.to_thread.run_sync(lambda: run_tool(name, arguments))
        except MCPToolError as exc:
            result = {"error": str(exc)}
        return [types.TextContent(type="text", text=json.dumps(result, default=str))]

    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(_serve)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
