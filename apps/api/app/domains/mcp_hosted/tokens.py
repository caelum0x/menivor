"""Workspace tokens for the hosted MCP connector (``mnv_mcp_...``).

The raw token is shown once at creation; only its SHA-256 digest is stored. A token
acts as the user who minted it, inside that workspace (or personally). Workspace
tokens can only be minted by the workspace's owners and admins. Tokens expire
(default 90 days) and can be revoked at any time.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.domains.adstudio.extract import clean_text
from app.domains.mcp_hosted.models import McpToken

PREFIX = "mnv_mcp_"
SCOPES = ("read", "write")
DEFAULT_TTL_DAYS = 90
MAX_TTL_DAYS = 365
MAX_TOKENS = 20


class TokenError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def digest(raw: str) -> str:
    return hashlib.sha256(str(raw or "").encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def view(row: McpToken) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "prefix": row.prefix, "workspace_id": row.workspace_id,
            "scopes": list(row.scopes or []), "expires_at": _aware(row.expires_at).isoformat() if row.expires_at else None,
            "revoked": row.revoked_at is not None,
            "last_used_at": _aware(row.last_used_at).isoformat() if row.last_used_at else None,
            "created_at": _aware(row.created_at).isoformat() if row.created_at else None}


def mint(session: Any, user_id: str, *, name: str, workspace_id: str | None = None,
         scopes: list[str] | None = None, ttl_days: int = DEFAULT_TTL_DAYS) -> dict[str, Any]:
    if workspace_id:
        from app.domains.integrations.errors import IntegrationError
        from app.domains.integrations.scope import resolve

        try:
            resolve(session, user_id, workspace_id=workspace_id).require_manage()
        except IntegrationError as exc:
            raise TokenError(exc.message, exc.status_code) from exc
    wanted = [s for s in (scopes or list(SCOPES)) if s in SCOPES] or ["read"]
    active = session.execute(select(McpToken).where(McpToken.user_id == user_id,
                                                    McpToken.revoked_at.is_(None))).scalars().all()
    if len(active) >= MAX_TOKENS:
        raise TokenError(f"You can have up to {MAX_TOKENS} active connector tokens; revoke one first.")
    raw = PREFIX + secrets.token_urlsafe(32)
    days = max(1, min(int(ttl_days or DEFAULT_TTL_DAYS), MAX_TTL_DAYS))
    row = McpToken(user_id=user_id, workspace_id=workspace_id, name=clean_text(name, 120) or "MCP connector",
                   token_digest=digest(raw), prefix=raw[:12], scopes=sorted(set(wanted)),
                   expires_at=_now() + timedelta(days=days), meta={})
    session.add(row)
    session.flush()
    return {**view(row), "token": raw}


def list_tokens(session: Any, user_id: str) -> list[dict[str, Any]]:
    rows = session.execute(select(McpToken).where(McpToken.user_id == user_id)
                           .order_by(McpToken.created_at.desc())).scalars().all()
    return [view(r) for r in rows]


def revoke(session: Any, user_id: str, token_id: str) -> dict[str, Any]:
    row = session.get(McpToken, token_id) if token_id else None
    if row is None or row.user_id != user_id:
        raise TokenError("token not found", 404)
    if row.revoked_at is None:
        row.revoked_at = _now()
        session.flush()
    return view(row)


def verify(session: Any, raw: str, *, now: datetime | None = None) -> McpToken | None:
    """The live token for ``raw`` (not revoked, not expired), touching ``last_used_at``; else None."""
    if not str(raw or "").startswith(PREFIX):
        return None
    row = session.execute(select(McpToken).where(McpToken.token_digest == digest(raw))).scalar_one_or_none()
    moment = now or _now()
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at is not None and _aware(row.expires_at) <= moment:
        return None
    row.last_used_at = moment
    session.flush()
    return row


__all__ = ["PREFIX", "SCOPES", "TokenError", "digest", "list_tokens", "mint", "revoke", "verify", "view"]
