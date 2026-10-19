"""Approvals feed preferences: which scanned producers may add items on their own.

Design posts, reply drafts, held posts and budget proposals are always queued
(each one is something the owner or the autopilot asked for). Suggestions made
from finished captures (``capture_publish``) and imported store products
(``catalog_import``) are opt-in and default OFF.

If the settings table is missing (migration not applied yet) every opt-in
source reads as off, which is the safe default.
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from app.domains.approvals.models import (
    SOURCE_CAPTURE_PUBLISH,
    SOURCE_CATALOG_IMPORT,
    STATUS_EXPIRED,
    STATUS_PENDING,
    ApprovalItem,
)
from app.domains.approvals.settings_models import ApprovalFeedSettings

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - the service reports the import failure
    get_session = None  # type: ignore[assignment]

#: Scanned producers that only add items when the owner opted in.
AUTO_SOURCES: tuple[str, ...] = (SOURCE_CAPTURE_PUBLISH, SOURCE_CATALOG_IMPORT)
AUTO_SOURCE_LABELS = {
    SOURCE_CAPTURE_PUBLISH: "Suggest reel ads from finished captures",
    SOURCE_CATALOG_IMPORT: "Suggest ads for newly imported store products",
}
TURNED_OFF_NOTE = "Automatic suggestions from this source were turned off."


class SettingsError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.status_code = status_code
        super().__init__(message)


def _view(enabled: set[str], *, stored: bool) -> dict:
    return {
        "auto_sources": {source: source in enabled for source in AUTO_SOURCES},
        "labels": dict(AUTO_SOURCE_LABELS),
        "stored": stored,
    }


def enabled_auto_sources(user_id: str) -> set[str]:
    """Opted-in scanned sources; empty (all off) on any read failure."""
    if get_session is None:
        return set()
    try:
        with get_session() as session:  # type: ignore[misc]
            row = session.get(ApprovalFeedSettings, user_id)
            return {s for s in (row.auto_sources if row else []) or [] if s in AUTO_SOURCES}
    except Exception as exc:  # noqa: BLE001 - e.g. the table is not migrated yet
        logger.warning(f"approvals settings: read failed for {user_id}: {exc}")
        return set()


def get_settings(user_id: str) -> dict:
    if get_session is None:
        raise SettingsError("approvals persistence is not available", status_code=503)
    with get_session() as session:  # type: ignore[misc]
        row = session.get(ApprovalFeedSettings, user_id)
        enabled = {s for s in (row.auto_sources if row else []) or [] if s in AUTO_SOURCES}
        return _view(enabled, stored=row is not None)


def update_settings(user_id: str, auto_sources: dict[str, bool]) -> dict:
    """Turn opt-in sources on or off. Turning one off expires its pending suggestions."""
    if get_session is None:
        raise SettingsError("approvals persistence is not available", status_code=503)
    unknown = sorted(k for k in auto_sources if k not in AUTO_SOURCES)
    if unknown:
        raise SettingsError(f"unknown auto source(s): {', '.join(unknown)}; allowed: {', '.join(AUTO_SOURCES)}")
    with get_session() as session:  # type: ignore[misc]
        row = session.get(ApprovalFeedSettings, user_id)
        current = {s for s in (row.auto_sources if row else []) or [] if s in AUTO_SOURCES}
        wanted = {s for s in current if auto_sources.get(s, True)} | {s for s, on in auto_sources.items() if on}
        if row is None:
            row = ApprovalFeedSettings(user_id=user_id, auto_sources=sorted(wanted))
            session.add(row)
        else:
            row.auto_sources = sorted(wanted)
        turned_off = current - wanted
        if turned_off:
            moment = datetime.now(timezone.utc)
            pending = session.execute(
                select(ApprovalItem).where(ApprovalItem.user_id == user_id, ApprovalItem.status == STATUS_PENDING,
                                           ApprovalItem.source.in_(sorted(turned_off)))
            ).scalars().all()
            for item in pending:
                item.status = STATUS_EXPIRED
                item.decision_note = TURNED_OFF_NOTE
                item.decided_at = moment
        session.flush()
        return _view(wanted, stored=True)


__all__ = [
    "AUTO_SOURCES",
    "SettingsError",
    "enabled_auto_sources",
    "get_settings",
    "update_settings",
]
