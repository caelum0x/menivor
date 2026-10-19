"""JSON-RPC 2.0 handling for the hosted MCP connector (protocol 2025-06-18 / 2025-03-26 / 2024-11-05).

Pure: takes one parsed message and a :class:`~.tools.ToolContext` factory, returns
the response dict (or ``None`` for a notification). Transport, auth and sessions
live in :mod:`.router`.
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from app.domains.mcp_hosted import tools

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "menivor", "title": "Menivor", "version": "2026.10.06"}
INSTRUCTIONS = (
    "Menivor makes ads and short videos for a brand. Start with brand_memory_get. Find what works with "
    "competitor_winners, ad_fatigue and analytics_report. Copy a winning structure with ad_clone_brief then "
    "ad_clone_plan (both free). generate_image and generate_video only queue a request: nothing is spent until "
    "a person approves it in the Menivor app; approvals_list shows what is waiting. Never claim something was "
    "generated or published before it was approved.")

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = -32700, -32600, -32601, -32602, -32603


def negotiate(params: dict[str, Any] | None) -> str:
    wanted = (params or {}).get("protocolVersion")
    return wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]


def error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def result(msg_id: Any, value: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": value}


def handle(message: Any, ctx_factory: Callable[[], tools.ToolContext]) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST,
                     "every message must be JSON-RPC 2.0 with a method")
    method, msg_id, params = message["method"], message.get("id"), message.get("params") or {}
    if "id" not in message:  # notification (e.g. notifications/initialized): no answer
        return None
    if method == "initialize":
        return result(msg_id, {"protocolVersion": negotiate(params), "serverInfo": SERVER_INFO,
                               "capabilities": {"tools": {"listChanged": False}}, "instructions": INSTRUCTIONS})
    if method == "ping":
        return result(msg_id, {})
    ctx = ctx_factory()
    if method == "tools/list":
        return result(msg_id, {"tools": tools.listing(ctx.scopes)})
    if method == "tools/call":
        name = params.get("name") if isinstance(params, dict) else None
        if not isinstance(name, str):
            return error(msg_id, INVALID_PARAMS, "tools/call needs a tool name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return error(msg_id, INVALID_PARAMS, "arguments must be an object")
        try:
            return result(msg_id, tools.call(ctx, name, args))
        except tools.ToolError as exc:
            return result(msg_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception as exc:  # noqa: BLE001 - never leak internals to the agent
            logger.warning(f"mcp tool {name} failed: {type(exc).__name__}")
            return result(msg_id, {"content": [{"type": "text", "text": "That tool failed on our side."}],
                                   "isError": True})
    return error(msg_id, METHOD_NOT_FOUND, f"unknown method: {method}")


__all__ = ["INSTRUCTIONS", "PROTOCOL_VERSIONS", "handle", "negotiate"]
