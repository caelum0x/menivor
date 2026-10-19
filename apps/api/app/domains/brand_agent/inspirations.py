"""Inspirations: saved reference ads and TikTok links (they feed Ad Clone)."""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import urlparse

from sqlalchemy import select

from app.domains.adstudio.extract import clean_text
from app.domains.brand_agent.models import AgentInspiration

MAX_ITEMS = 500
SOURCES = frozenset({"user", "meta_ads", "agent", "competitor"})


class InspirationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def kind_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("tiktok.com"):
        return "tiktok"
    if host.endswith(("facebook.com", "fb.com", "fb.watch")) or "/ads/library" in url:
        return "meta_ad"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith(("youtube.com", "youtu.be")):
        return "youtube"
    return "link"


def valid_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or len(value) > 2048:
        raise InspirationError("Paste a full link starting with https://", 422)
    return value


def view(row: AgentInspiration) -> dict[str, Any]:
    return {
        "id": row.id,
        "space_id": row.space_id,
        "kind": row.kind,
        "source": row.source,
        "url": row.url,
        "title": row.title,
        "notes": row.notes,
        "thumbnail_url": row.thumbnail_url,
        "metrics": dict(row.metrics or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def add(session: Any, user_id: str, space_id: str, url: str, *, title: str = "", notes: str = "",
        source: str = "user", thumbnail_url: str = "", metrics: dict | None = None) -> dict[str, Any]:
    link = valid_url(url)
    if source not in SOURCES:
        raise InspirationError("unknown inspiration source")
    existing = session.execute(
        select(AgentInspiration).where(AgentInspiration.space_id == space_id, AgentInspiration.url == link)
    ).scalars().first()
    if existing is not None:
        if title:
            existing.title = clean_text(title, 300)
        if metrics:
            existing.metrics = dict(metrics)
        session.flush()
        return view(existing)
    count = len(list_items(session, user_id, space_id))
    if count >= MAX_ITEMS:
        raise InspirationError(f"Inspirations are full ({MAX_ITEMS}); remove some first.")
    thumb = thumbnail_url if str(thumbnail_url or "").startswith("https://") else ""
    row = AgentInspiration(user_id=user_id, space_id=space_id, kind=kind_of(link), source=source, url=link,
                           title=clean_text(title, 300), notes=clean_text(notes, 2000), thumbnail_url=thumb,
                           metrics=dict(metrics or {}))
    session.add(row)
    session.flush()
    return view(row)


def save_creatives(session: Any, user_id: str, space_id: str, creatives: Iterable[dict[str, Any]],
                   *, source: str) -> int:
    saved = 0
    for item in creatives:
        if not isinstance(item, dict):
            continue
        try:
            add(session, user_id, space_id, str(item.get("url") or ""), title=str(item.get("title") or ""),
                source=source, thumbnail_url=str(item.get("thumbnail_url") or ""),
                metrics=item.get("metrics") if isinstance(item.get("metrics"), dict) else None)
        except InspirationError:
            continue
        saved += 1
    return saved


def list_items(session: Any, user_id: str, space_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(AgentInspiration).where(AgentInspiration.user_id == user_id)
    if space_id:
        stmt = stmt.where(AgentInspiration.space_id == space_id)
    rows = session.execute(stmt.order_by(AgentInspiration.created_at.desc())).scalars().all()
    return [view(r) for r in rows]


def delete(session: Any, user_id: str, item_id: str) -> None:
    row = session.get(AgentInspiration, item_id)
    if row is None or row.user_id != user_id:
        raise InspirationError("inspiration not found", 404)
    session.delete(row)
    session.flush()


__all__ = ["InspirationError", "add", "delete", "kind_of", "list_items", "save_creatives", "valid_url", "view"]
