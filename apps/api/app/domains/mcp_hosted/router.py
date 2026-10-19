"""Hosted MCP connector: ``/api/v1/mcp`` (streamable HTTP) + token management for Settings.

    POST   /mcp                   JSON-RPC (one message or a batch); ``initialize`` returns ``Mcp-Session-Id``
    GET    /mcp                   405 (this server never starts messages)
    DELETE /mcp                   end the session
    GET    /mcp/connector         endpoint URL, tools and client setup snippets (signed in)
    GET    /mcp/tokens            my connector tokens (signed in)
    POST   /mcp/tokens            mint a token (shown once; workspace tokens: owners and admins)
    DELETE /mcp/tokens/{id}       revoke

Auth on ``/mcp``: ``Authorization: Bearer mnv_mcp_...``. The session id is an HMAC of
a nonce keyed by the token digest, so it is bound to that token: another bearer with
the same session id is refused. Browser ``Origin`` headers must be allow-listed
(``MENIVOR_MCP_ALLOWED_ORIGINS``); non-browser clients send none.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from typing import Any, Optional

from fastapi import Path, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse, Response

from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.domains._http import Call
from app.domains.mcp_hosted import models as _models  # noqa: F401  (registers tables)
from app.domains.mcp_hosted import server, tokens, tools
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()
SESSION_HEADER = "Mcp-Session-Id"
ORIGINS_ENV = "MENIVOR_MCP_ALLOWED_ORIGINS"
MAX_BODY = 512 * 1024
MAX_BATCH = 20
_CALLS_PER_HOUR = 1200


def _web_url() -> str:
    try:
        from app.domains.ads.config import web_url

        return web_url()
    except Exception:  # noqa: BLE001
        return "https://menivor.com"


def _api_url(request: Request) -> str:
    return (os.getenv("MENIVOR_PUBLIC_API_URL") or str(request.base_url).rstrip("/")).rstrip("/") + "/api/v1/mcp"


def _session_id(token_digest: str, nonce: str | None = None) -> str:
    value = nonce or secrets.token_hex(12)
    mac = hmac.new(token_digest.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{value}.{mac}"


def _session_ok(token_digest: str, session_id: str) -> bool:
    nonce, _, _mac = str(session_id or "").partition(".")
    return bool(nonce) and hmac.compare_digest(_session_id(token_digest, nonce), str(session_id))


def _rpc_error(status: int, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=server.error(None, -32000, message), headers=headers or {})


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    allowed = {o.strip().rstrip("/") for o in os.getenv(ORIGINS_ENV, "").split(",") if o.strip()}
    allowed.add(_web_url().rstrip("/"))
    return origin.rstrip("/") in allowed


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization") or ""
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


@router.post("/mcp", include_in_schema=False)
async def mcp_post(request: Request) -> Response:
    if not _origin_ok(request):
        return _rpc_error(403, "origin not allowed")
    raw_token = _bearer(request)
    challenge = {"WWW-Authenticate": 'Bearer realm="menivor-mcp"'}
    if not raw_token:
        return _rpc_error(401, "send Authorization: Bearer <Menivor connector token>", challenge)
    body = await request.body()
    if len(body) > MAX_BODY:
        return _rpc_error(413, "request too large")
    try:
        payload = json.loads(body or b"null")
    except ValueError:
        return JSONResponse(status_code=400, content=server.error(None, server.PARSE_ERROR, "body is not JSON"))
    batch = payload if isinstance(payload, list) else [payload]
    if not batch or len(batch) > MAX_BATCH:
        return JSONResponse(status_code=400, content=server.error(None, server.INVALID_REQUEST, "empty or huge batch"))
    with get_session() as session:
        token = tokens.verify(session, raw_token)
        if token is None:
            return _rpc_error(401, "this connector token is invalid, expired or revoked", challenge)
        enforce_rate_limit(request, f"mcp:{token.id}", limit=_CALLS_PER_HOUR, window_s=3600)
        initializing = any(isinstance(m, dict) and m.get("method") == "initialize" for m in batch)
        headers: dict[str, str] = {}
        if initializing:
            headers[SESSION_HEADER] = _session_id(token.token_digest)
        elif not _session_ok(token.token_digest, request.headers.get(SESSION_HEADER, "")):
            return _rpc_error(400, "missing or foreign Mcp-Session-Id; call initialize first")
        ctx = tools.ToolContext(session=session, user_id=token.user_id, workspace_id=token.workspace_id,
                                scopes=tuple(token.scopes or ()), web_url=_web_url(), overrides=dict(TOOL_OVERRIDES))
        replies = [r for r in (server.handle(m, lambda: ctx) for m in batch) if r is not None]
    if not replies:
        return Response(status_code=202, headers=headers)
    content: Any = replies if isinstance(payload, list) else replies[0]
    return JSONResponse(content=json.loads(json.dumps(content, default=str)), headers=headers)


#: Tests replace Ad Clone steps here; production leaves it empty.
TOOL_OVERRIDES: dict[str, Any] = {}


@router.get("/mcp", include_in_schema=False)
def mcp_get() -> Response:
    return Response(status_code=405, headers={"Allow": "POST, DELETE"})


@router.delete("/mcp", include_in_schema=False)
def mcp_delete(request: Request) -> Response:
    return Response(status_code=204 if _bearer(request) else 401)


class TokenBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="MCP connector", max_length=120)
    workspace_id: Optional[str] = Field(default=None, max_length=32)
    scopes: list[str] = Field(default_factory=lambda: ["read", "write"], max_length=2)
    ttl_days: int = Field(default=tokens.DEFAULT_TTL_DAYS, ge=1, le=tokens.MAX_TTL_DAYS)


def _call(request: Request, key: str = "") -> Call:
    return Call(request, (tokens.TokenError,), f"mcp:{key}" if key else "", get_session, limit=120)


@router.get("/mcp/connector", summary="Hosted MCP endpoint, its tools and client setup")
def connector(request: Request):
    with _call(request) as (_session, _user_id):
        url = _api_url(request)
        config = {"mcpServers": {"menivor": {"type": "http", "url": url,
                                             "headers": {"Authorization": "Bearer <your token>"}}}}
        return utils.get_response(200, {
            "url": url, "tools": tools.listing(tokens.SCOPES), "protocol_versions": list(server.PROTOCOL_VERSIONS),
            "claude_code": f"claude mcp add --transport http menivor {url} --header \"Authorization: Bearer <your token>\"",
            "json_config": config,
            "rules": ["Spending tools only create approvals; a person approves in Menivor.",
                      "Tokens act as you, in the workspace you pick. Revoke them any time."]})


@router.get("/mcp/tokens", summary="My MCP connector tokens")
def list_tokens(request: Request):
    with _call(request) as (session, user_id):
        return utils.get_response(200, {"tokens": tokens.list_tokens(session, user_id)})


@router.post("/mcp/tokens", summary="Mint a connector token (shown once)")
def mint_token(request: Request, body: TokenBody):
    with _call(request, "mint") as (session, user_id):
        return utils.get_response(200, {"token": tokens.mint(session, user_id, name=body.name,
                                                             workspace_id=body.workspace_id, scopes=body.scopes,
                                                             ttl_days=body.ttl_days)})


@router.delete("/mcp/tokens/{token_id}", summary="Revoke a connector token")
def revoke_token(request: Request, token_id: str = Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")):
    with _call(request, "revoke") as (session, user_id):
        return utils.get_response(200, {"token": tokens.revoke(session, user_id, token_id)})


__all__ = ["router"]
