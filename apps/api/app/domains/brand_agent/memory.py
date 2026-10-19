"""Versioned brand memory ("Brain") per brand space.

Every write appends a new :class:`AgentBrandMemory` row whose ``version`` is the
space's next number; nothing is ever updated in place, so the full history is
kept and any version can be shown or restored. The current memory is the newest
row per section. Writes are normalized per section (bounded strings, hex
colours, http(s) URLs only, unknown keys dropped) and scrubbed by the copy rules.

The Brain badge counts agent-written versions newer than the space's
``brain_seen_version``; the user's own edits never light it up.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.domains.adstudio.extract import clean_text
from app.domains.brand.extract import normalize_hex
from app.domains.brand_agent import copy_rules
from app.domains.brand_agent.models import AgentBrandMemory, AgentBrandSpace

SECTION_POSITIONING = "positioning"
SECTION_PRODUCT = "product"
SECTION_MARKET = "market"
SECTION_VOICE = "voice_audience"
SECTIONS: tuple[str, ...] = (SECTION_POSITIONING, SECTION_PRODUCT, SECTION_MARKET, SECTION_VOICE)

SOURCE_AGENT = "agent"
SOURCE_USER = "user"
SOURCES = frozenset({SOURCE_AGENT, SOURCE_USER})

_TEXT = 400
_SHORT = 160
MAX_HISTORY = 50


class MemoryError_(Exception):  # noqa: N801 - avoid shadowing the builtin MemoryError
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _s(value: Any, limit: int = _TEXT) -> str:
    return clean_text(value, limit) if isinstance(value, (str, int, float)) else ""


def _strings(value: Any, limit: int, size: int = _TEXT) -> list[str]:
    items = value if isinstance(value, (list, tuple)) else []
    out: list[str] = []
    for item in items:
        text = _s(item, size)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _url(value: Any) -> str:
    text = _s(value, 2048)
    return text if text.startswith(("https://", "http://")) else ""


def _dicts(value: Any, limit: int) -> list[dict[str, Any]]:
    return [v for v in (value if isinstance(value, (list, tuple)) else []) if isinstance(v, dict)][:limit]


def _colors(value: Any) -> list[str]:
    out: list[str] = []
    for item in value if isinstance(value, (list, tuple)) else []:
        raw = item.get("hex") if isinstance(item, dict) else item
        hex_value = normalize_hex(raw)
        if hex_value and hex_value not in out:
            out.append(hex_value)
    return out[:6]


def _fonts(value: Any) -> list[str]:
    items = [(v.get("family") if isinstance(v, dict) else v) for v in (value if isinstance(value, list) else [])]
    return _strings(items, 4, 60)


def normalize(section: str, data: Any) -> dict[str, Any]:
    """A bounded, scrubbed copy of ``data`` for ``section`` (unknown keys dropped)."""
    if section not in SECTIONS:
        raise MemoryError_(f"unknown brand memory section: {section}")
    raw = data if isinstance(data, dict) else {}
    if section == SECTION_POSITIONING:
        out: dict[str, Any] = {
            "name": _s(raw.get("name"), 120),
            "category": _s(raw.get("category"), _SHORT),
            "one_liner": _s(raw.get("one_liner")),
            "pricing_hook": _s(raw.get("pricing_hook")),
            "colors": _colors(raw.get("colors")),
            "fonts": _fonts(raw.get("fonts")),
            "logo_url": _url(raw.get("logo_url")),
        }
    elif section == SECTION_PRODUCT:
        out = {"products": [
            {"name": _s(p.get("name"), 120), "what_it_is": _s(p.get("what_it_is")),
             "key_features": _strings(p.get("key_features"), 10, 160)}
            for p in _dicts(raw.get("products"), 5) if _s(p.get("name"), 120)
        ]}
    elif section == SECTION_MARKET:
        out = {
            "competitors": [
                {"name": _s(c.get("name"), 120), "url": _url(c.get("url")), "note": _s(c.get("note")),
                 "relationship": _s(c.get("relationship"), 32) or "competitor"}
                for c in _dicts(raw.get("competitors"), 10) if _s(c.get("name"), 120)
            ],
            "insights": _strings(raw.get("insights"), 8),
            "sources": [u for u in (_url(x) for x in raw.get("sources") or []) if u][:10],
        }
    else:
        out = {
            "sample_lines": _strings(raw.get("sample_lines"), 8, 220),
            "tone": _strings(raw.get("tone"), 6, 60),
            "segments": [
                {"name": _s(seg.get("name"), 120), "pains": _strings(seg.get("pains"), 6, 200)}
                for seg in _dicts(raw.get("segments"), 6) if _s(seg.get("name"), 120)
            ],
        }
    return copy_rules.scrub_obj(out)


def _space(session: Any, user_id: str, space_id: str) -> AgentBrandSpace:
    space = session.get(AgentBrandSpace, space_id)
    if space is None or space.user_id != user_id:
        raise MemoryError_("brand space not found", 404)
    return space


def latest_version(session: Any, space_id: str) -> int:
    value = session.execute(
        select(func.max(AgentBrandMemory.version)).where(AgentBrandMemory.space_id == space_id)
    ).scalar()
    return int(value or 0)


def _view(row: AgentBrandMemory) -> dict[str, Any]:
    return {
        "version": row.version,
        "section": row.section,
        "data": dict(row.data or {}),
        "source": row.source,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def write(session: Any, user_id: str, space_id: str, section: str, data: Any,
          *, source: str = SOURCE_AGENT) -> dict[str, Any]:
    """Append a new version of ``section``. Returns the version view."""
    if source not in SOURCES:
        raise MemoryError_(f"unknown memory source: {source}")
    clean = normalize(section, data)
    _space(session, user_id, space_id)
    row = AgentBrandMemory(space_id=space_id, user_id=user_id, version=latest_version(session, space_id) + 1,
                           section=section, data=clean, source=source)
    session.add(row)
    session.flush()
    if source == SOURCE_USER:
        # The owner's own edit is "seen" by definition, so it never lights the badge.
        space = session.get(AgentBrandSpace, space_id)
        if space is not None and unseen_count(session, space_id) == 0:
            space.brain_seen_version = row.version
    return _view(row)


def current(session: Any, space_id: str) -> dict[str, Any]:
    """``{"version", "sections": {section: data}, "updated": {section: version}}``."""
    rows = session.execute(
        select(AgentBrandMemory).where(AgentBrandMemory.space_id == space_id)
        .order_by(AgentBrandMemory.version.desc())
    ).scalars().all()
    sections: dict[str, Any] = {}
    updated: dict[str, int] = {}
    for row in rows:
        if row.section not in sections:
            sections[row.section] = dict(row.data or {})
            updated[row.section] = row.version
    return {"version": rows[0].version if rows else 0, "sections": sections, "updated": updated}


def history(session: Any, space_id: str, *, section: str | None = None,
            limit: int = MAX_HISTORY) -> list[dict[str, Any]]:
    stmt = select(AgentBrandMemory).where(AgentBrandMemory.space_id == space_id)
    if section:
        stmt = stmt.where(AgentBrandMemory.section == section)
    rows = session.execute(stmt.order_by(AgentBrandMemory.version.desc()).limit(limit)).scalars().all()
    return [_view(r) for r in rows]


def unseen_count(session: Any, space_id: str) -> int:
    space = session.get(AgentBrandSpace, space_id)
    seen = int(space.brain_seen_version or 0) if space is not None else 0
    value = session.execute(
        select(func.count()).select_from(AgentBrandMemory).where(
            AgentBrandMemory.space_id == space_id,
            AgentBrandMemory.version > seen,
            AgentBrandMemory.source == SOURCE_AGENT,
        )
    ).scalar()
    return int(value or 0)


def mark_seen(session: Any, user_id: str, space_id: str) -> int:
    space = _space(session, user_id, space_id)
    space.brain_seen_version = latest_version(session, space_id)
    session.flush()
    return space.brain_seen_version


__all__ = [
    "MemoryError_",
    "SECTIONS",
    "SECTION_MARKET",
    "SECTION_POSITIONING",
    "SECTION_PRODUCT",
    "SECTION_VOICE",
    "SOURCE_AGENT",
    "SOURCE_USER",
    "current",
    "history",
    "latest_version",
    "mark_seen",
    "normalize",
    "unseen_count",
    "write",
]
