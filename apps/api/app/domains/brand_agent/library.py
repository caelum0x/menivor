"""Library (assets the agent generated after approval) and folders."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.domains.adstudio.extract import clean_text
from app.domains.brand_agent.models import AgentFolder, AgentLibraryItem

MAX_FOLDERS = 100


class LibraryError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def item_view(row: AgentLibraryItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "space_id": row.space_id,
        "folder_id": row.folder_id,
        "action_id": row.action_id,
        "kind": row.kind,
        "ref": row.ref,
        "url": row.url,
        "title": row.title,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def folder_view(row: AgentFolder) -> dict[str, Any]:
    return {"id": row.id, "space_id": row.space_id, "name": row.name,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def add_item(session: Any, *, user_id: str, space_id: str, action_id: str | None, kind: str, ref: str,
             url: str = "", title: str = "") -> dict[str, Any]:
    safe_url = url if str(url or "").startswith(("https://", "http://")) else ""
    row = AgentLibraryItem(user_id=user_id, space_id=space_id, action_id=action_id, kind=kind[:16],
                           ref=str(ref or "")[:200], url=safe_url, title=clean_text(title, 300))
    session.add(row)
    session.flush()
    return item_view(row)


def list_items(session: Any, user_id: str, space_id: str | None = None, *,
               folder_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(AgentLibraryItem).where(AgentLibraryItem.user_id == user_id)
    if space_id:
        stmt = stmt.where(AgentLibraryItem.space_id == space_id)
    if folder_id:
        stmt = stmt.where(AgentLibraryItem.folder_id == folder_id)
    rows = session.execute(stmt.order_by(AgentLibraryItem.created_at.desc(), AgentLibraryItem.id)).scalars().all()
    return [item_view(r) for r in rows]


def _folder(session: Any, user_id: str, folder_id: str) -> AgentFolder:
    row = session.get(AgentFolder, folder_id)
    if row is None or row.user_id != user_id:
        raise LibraryError("folder not found", 404)
    return row


def move(session: Any, user_id: str, item_id: str, folder_id: str | None) -> dict[str, Any]:
    row = session.get(AgentLibraryItem, item_id)
    if row is None or row.user_id != user_id:
        raise LibraryError("library item not found", 404)
    if folder_id:
        folder = _folder(session, user_id, folder_id)
        if folder.space_id != row.space_id:
            raise LibraryError("that folder belongs to another brand", 400)
    row.folder_id = folder_id or None
    session.flush()
    return item_view(row)


def create_folder(session: Any, user_id: str, space_id: str, name: str) -> dict[str, Any]:
    title = clean_text(name, 120)
    if not title:
        raise LibraryError("Give the folder a name.", 422)
    if len(list_folders(session, user_id, space_id)) >= MAX_FOLDERS:
        raise LibraryError(f"You can have up to {MAX_FOLDERS} folders.")
    row = AgentFolder(user_id=user_id, space_id=space_id, name=title)
    session.add(row)
    session.flush()
    return folder_view(row)


def list_folders(session: Any, user_id: str, space_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(AgentFolder).where(AgentFolder.user_id == user_id)
    if space_id:
        stmt = stmt.where(AgentFolder.space_id == space_id)
    return [folder_view(r) for r in session.execute(stmt.order_by(AgentFolder.created_at)).scalars().all()]


__all__ = ["LibraryError", "add_item", "create_folder", "item_view", "list_folders", "list_items", "move"]
