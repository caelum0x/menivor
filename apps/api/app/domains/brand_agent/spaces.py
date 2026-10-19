"""Brand spaces: one brand per space, owner-scoped. A default space is made on first use."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.domains.adstudio.extract import clean_text
from app.domains.brand_agent.models import AgentBrandSpace

DEFAULT_NAME = "My brand"
MAX_SPACES = 20


class SpaceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def view(space: AgentBrandSpace) -> dict[str, Any]:
    return {
        "id": space.id,
        "name": space.name,
        "website_url": space.website_url,
        "workspace_id": space.workspace_id,
        "created_at": space.created_at.isoformat() if space.created_at else None,
    }


def list_spaces(session: Any, user_id: str) -> list[AgentBrandSpace]:
    return list(session.execute(
        select(AgentBrandSpace).where(AgentBrandSpace.user_id == user_id).order_by(AgentBrandSpace.created_at)
    ).scalars().all())


def get(session: Any, user_id: str, space_id: str) -> AgentBrandSpace:
    space = session.get(AgentBrandSpace, space_id) if space_id else None
    if space is None or space.user_id != user_id:
        raise SpaceError("brand space not found", 404)
    return space


def create(session: Any, user_id: str, *, name: str = "", website_url: str = "") -> AgentBrandSpace:
    if len(list_spaces(session, user_id)) >= MAX_SPACES:
        raise SpaceError(f"you can have up to {MAX_SPACES} brand spaces")
    space = AgentBrandSpace(user_id=user_id, name=clean_text(name, 200) or DEFAULT_NAME,
                            website_url=clean_text(website_url, 2048))
    session.add(space)
    session.flush()
    return space


def ensure_default(session: Any, user_id: str) -> AgentBrandSpace:
    spaces = list_spaces(session, user_id)
    return spaces[0] if spaces else create(session, user_id)


def resolve(session: Any, user_id: str, space_id: str | None) -> AgentBrandSpace:
    return get(session, user_id, space_id) if space_id else ensure_default(session, user_id)


def rename_from_brand(session: Any, space: AgentBrandSpace, *, name: str, website_url: str) -> None:
    """Name a still-default space after the brand it was set up from."""
    if name and space.name == DEFAULT_NAME:
        space.name = clean_text(name, 200)
    if website_url:
        space.website_url = clean_text(website_url, 2048)
    session.flush()


__all__ = ["SpaceError", "create", "ensure_default", "get", "list_spaces", "rename_from_brand", "resolve", "view"]
