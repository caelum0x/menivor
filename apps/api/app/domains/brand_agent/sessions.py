"""Agent chat sessions and their ordered messages (owner-scoped)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.domains.adstudio.extract import clean_text
from app.domains.brand_agent import copy_rules
from app.domains.brand_agent.models import AgentMessage, AgentSession

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLES = frozenset({ROLE_USER, ROLE_ASSISTANT})
MAX_CONTENT = 8000
MAX_RECENTS = 20
DEFAULT_TITLE = "New session"


class SessionError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def view(row: AgentSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "space_id": row.space_id,
        "title": row.title or DEFAULT_TITLE,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def message_view(row: AgentMessage, action: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "seq": row.seq,
        "role": row.role,
        "content": row.content,
        "card": dict(row.card) if row.card else None,
        "chips": list(row.chips or []),
        "action_id": row.action_id,
        "action": action,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def create(session: Any, user_id: str, space_id: str, *, title: str = "") -> AgentSession:
    row = AgentSession(user_id=user_id, space_id=space_id, title=clean_text(title, 200), state={})
    session.add(row)
    session.flush()
    return row


def get(session: Any, user_id: str, session_id: str) -> AgentSession:
    row = session.get(AgentSession, session_id) if session_id else None
    if row is None or row.user_id != user_id:
        raise SessionError("session not found", 404)
    return row


def recents(session: Any, user_id: str, *, space_id: str | None = None,
            limit: int = MAX_RECENTS) -> list[AgentSession]:
    stmt = select(AgentSession).where(AgentSession.user_id == user_id)
    if space_id:
        stmt = stmt.where(AgentSession.space_id == space_id)
    stmt = stmt.order_by(AgentSession.updated_at.desc(), AgentSession.created_at.desc())
    return list(session.execute(stmt.limit(limit)).scalars().all())


def set_state(session: Any, row: AgentSession, state: dict[str, Any]) -> None:
    """Replace the session state with a new dict (JSON columns need reassignment)."""
    row.state = dict(state)
    session.flush()


def _next_seq(session: Any, session_id: str) -> int:
    value = session.execute(
        select(func.max(AgentMessage.seq)).where(AgentMessage.session_id == session_id)
    ).scalar()
    return int(value or 0) + 1


def add_message(session: Any, row: AgentSession, role: str, content: str, *, card: dict | None = None,
                chips: list[dict] | None = None, action_id: str | None = None) -> AgentMessage:
    if role not in ROLES:
        raise SessionError(f"unknown role: {role}")
    text = str(content or "")[:MAX_CONTENT]
    if role == ROLE_ASSISTANT:
        text = copy_rules.scrub(text)
        card = copy_rules.scrub_obj(card) if card else None
    message = AgentMessage(session_id=row.id, user_id=row.user_id, seq=_next_seq(session, row.id), role=role,
                           content=text, card=card, chips=list(chips or []), action_id=action_id)
    session.add(message)
    if role == ROLE_USER and not row.title:
        row.title = clean_text(text, 80)
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return message


def messages(session: Any, user_id: str, session_id: str) -> list[dict[str, Any]]:
    from app.domains.brand_agent import gate

    row = get(session, user_id, session_id)
    rows = session.execute(
        select(AgentMessage).where(AgentMessage.session_id == row.id).order_by(AgentMessage.seq)
    ).scalars().all()
    actions = gate.views_by_id(session, user_id, [m.action_id for m in rows if m.action_id])
    return [message_view(m, actions.get(m.action_id or "")) for m in rows]


__all__ = [
    "ROLE_ASSISTANT",
    "ROLE_USER",
    "SessionError",
    "add_message",
    "create",
    "get",
    "message_view",
    "messages",
    "recents",
    "set_state",
    "view",
]
