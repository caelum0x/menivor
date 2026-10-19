"""Minimal MCP (Model Context Protocol) client for OpenSEO's hosted server.

OpenSEO exposes its research/audit/backlink/rank-tracking tools over MCP
(Streamable HTTP transport, JSON-RPC 2.0) at ``https://app.openseo.so/mcp``
rather than a classic REST API -- see
``~/products/oss-project-you-must/open-seo/web/content/docs/mcp.md`` (the
self-hosted clone's own docs; the hosted service runs the same server). The
documented way to call it headlessly is an API key as
``Authorization: Bearer oseo_...`` (OpenSEO Settings -> API keys); that is
the credential a Menivor workspace pastes in to connect its own account.

Every call here is one self-contained MCP session: ``initialize`` to get a
session id (returned in the ``Mcp-Session-Id`` response header), then exactly
one ``tools/call``. OpenSEO answers either a plain JSON body or a single
``text/event-stream`` frame; both are handled.
"""

from __future__ import annotations

import json
import os
from typing import Any

MCP_URL_DEFAULT = "https://app.openseo.so/mcp"
#: MCP protocol revision this client speaks (OpenSEO's docs link the current spec).
PROTOCOL_VERSION = "2026-06-18"
CLIENT_INFO = {"name": "menivor", "version": "1.0"}
HTTP_TIMEOUT_S = 45.0


class OpenSeoError(Exception):
    """An OpenSEO MCP call failed; ``message`` is safe to show the workspace."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def mcp_url() -> str:
    return (os.environ.get("OPENSEO_MCP_URL") or "").strip() or MCP_URL_DEFAULT


def _headers(api_key: str, session_id: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
              "Accept": "application/json, text/event-stream"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _header_value(resp: Any, name: str) -> str | None:
    headers = getattr(resp, "headers", None) or {}
    for key in (name, name.lower(), name.title()):
        value = headers.get(key) if hasattr(headers, "get") else None
        if value:
            return str(value)
    return None


def _body_of(resp: Any) -> dict:
    """OpenSEO answers either a plain JSON object or one SSE ``data:`` frame."""
    content_type = _header_value(resp, "content-type") or ""
    text = resp.text if hasattr(resp, "text") else ""
    if "text/event-stream" in content_type:
        for line in (text or "").splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[len("data:"):].strip())
                except ValueError as exc:
                    raise OpenSeoError("OpenSEO sent a response Menivor could not read.") from exc
        raise OpenSeoError("OpenSEO sent an empty response.")
    try:
        return resp.json()
    except ValueError as exc:
        raise OpenSeoError("OpenSEO sent a response Menivor could not read.") from exc


def _rpc(transport: Any, url: str, headers: dict, method: str, params: dict, msg_id: str) -> tuple[dict, Any]:
    payload = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
    try:
        resp = transport.request("POST", url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        raise OpenSeoError(f"OpenSEO is unreachable ({exc.__class__.__name__}).") from exc
    if resp.status_code in (401, 403):
        raise OpenSeoError("OpenSEO rejected this API key. Reconnect it.", status_code=401)
    if resp.status_code >= 400:
        raise OpenSeoError(f"OpenSEO: HTTP {resp.status_code}", status_code=502)
    body = _body_of(resp)
    if body.get("error"):
        message = (body.get("error") or {}).get("message") or "the call failed"
        raise OpenSeoError(f"OpenSEO: {message}", status_code=400)
    return body.get("result") or {}, resp


def _extract(result: dict) -> Any:
    """Tool results carry either ``structuredContent`` or a text content block
    (often JSON-encoded); fall back to the raw result for anything else."""
    if "structuredContent" in result:
        return result["structuredContent"]
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            try:
                return json.loads(text)
            except ValueError:
                return text
    return result


def call_tool(transport: Any, api_key: str, name: str, arguments: dict, *, url: str = "") -> Any:
    """Run one OpenSEO MCP tool end to end. Raises :class:`OpenSeoError`."""
    key = (api_key or "").strip()
    if not key:
        raise OpenSeoError("Connect an OpenSEO API key first.", status_code=401)
    target = url or mcp_url()
    _, init_resp = _rpc(transport, target, _headers(key), "initialize", {
        "protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO,
    }, "init")
    session_id = _header_value(init_resp, "mcp-session-id")
    result, _ = _rpc(transport, target, _headers(key, session_id), "tools/call",
                     {"name": name, "arguments": arguments}, "call-1")
    if result.get("isError"):
        text = "; ".join(str(c.get("text") or "") for c in result.get("content") or [] if isinstance(c, dict))
        raise OpenSeoError(text or "OpenSEO reported an error running that tool.", status_code=400)
    return _extract(result)


__all__ = ["OpenSeoError", "call_tool", "mcp_url"]
