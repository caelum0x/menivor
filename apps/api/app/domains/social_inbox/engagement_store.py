"""Owner-scoped queries for the engagement autopilot (settings, actions, leads)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .engagement_models import (
    ACTOR_AUTOPILOT,
    AS_DONE,
    AS_PENDING,
    CAPPED_KINDS,
    LEAD_NEW,
    EngagementAction,
    EngagementLead,
    EngagementSettings,
)
from .models import STATUS_NEEDS_REPLY, InboxThread


def utc_midnight(now: datetime) -> datetime:
    moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def settings_rows(session: Any, user_id: str) -> dict[str, EngagementSettings]:
    rows = session.execute(select(EngagementSettings).where(EngagementSettings.user_id == user_id)).scalars().all()
    return {r.platform: r for r in rows}


def get_or_create_settings(session: Any, user_id: str, platform: str) -> EngagementSettings:
    row = session.execute(
        select(EngagementSettings).where(EngagementSettings.user_id == user_id, EngagementSettings.platform == platform)
    ).scalar_one_or_none()
    if row is None:
        row = EngagementSettings(user_id=user_id, platform=platform, blocked_words=[])
        session.add(row)
        session.flush()
    return row


def users_with_autopilot(session: Any, *, limit: int) -> list[str]:
    rows = session.execute(
        select(EngagementSettings.user_id)
        .where(EngagementSettings.enabled.is_(True))
        .group_by(EngagementSettings.user_id)
        .order_by(func.min(EngagementSettings.last_run_at).asc().nullsfirst())
        .limit(max(1, limit))
    ).scalars().all()
    return [str(r) for r in rows]


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def try_add_action(session: Any, **values: Any) -> EngagementAction | None:
    """Insert unless the (user, thread, kind, message) action already exists; returns the row or ``None``."""
    row = EngagementAction(**{"detail": {}, **values})
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        return None
    return row


def processed_keys(session: Any, user_id: str, thread_ids: Iterable[str]) -> set[tuple[str, str]]:
    ids = [t for t in thread_ids if t]
    if not ids:
        return set()
    rows = session.execute(
        select(EngagementAction.thread_id, EngagementAction.message_key)
        .where(EngagementAction.user_id == user_id, EngagementAction.thread_id.in_(ids))
    ).all()
    return {(str(t), str(k)) for t, k in rows}


def used_today(session: Any, user_id: str, now: datetime) -> dict[str, int]:
    """Platform-touching autopilot actions executed since UTC midnight, per platform."""
    rows = session.execute(
        select(EngagementAction.platform, func.count())
        .where(
            EngagementAction.user_id == user_id,
            EngagementAction.actor == ACTOR_AUTOPILOT,
            EngagementAction.status == AS_DONE,
            EngagementAction.kind.in_(list(CAPPED_KINDS)),
            EngagementAction.created_at >= utc_midnight(now),
        )
        .group_by(EngagementAction.platform)
    ).all()
    return {str(p): int(c) for p, c in rows}


def get_action(session: Any, user_id: str, action_id: str) -> EngagementAction | None:
    row = session.get(EngagementAction, action_id)
    return row if row is not None and row.user_id == user_id else None


def list_actions(session: Any, user_id: str, *, statuses: Iterable[str] = (), kinds: Iterable[str] = (),
                 platform: str = "", limit: int = 50, offset: int = 0) -> tuple[list[EngagementAction], int]:
    conditions = [EngagementAction.user_id == user_id]
    wanted_status = [s for s in statuses if s]
    wanted_kind = [k for k in kinds if k]
    if wanted_status:
        conditions.append(EngagementAction.status.in_(wanted_status))
    if wanted_kind:
        conditions.append(EngagementAction.kind.in_(wanted_kind))
    if platform:
        conditions.append(EngagementAction.platform == platform)
    total = int(session.execute(select(func.count()).select_from(EngagementAction).where(*conditions)).scalar() or 0)
    rows = session.execute(
        select(EngagementAction).where(*conditions)
        .order_by(EngagementAction.created_at.desc(), EngagementAction.id.desc())
        .limit(max(1, min(limit, 100))).offset(max(0, offset))
    ).scalars().all()
    return list(rows), total


def pending_count(session: Any, user_id: str) -> int:
    return int(session.execute(
        select(func.count()).select_from(EngagementAction)
        .where(EngagementAction.user_id == user_id, EngagementAction.status == AS_PENDING)
    ).scalar() or 0)


# --------------------------------------------------------------------------- #
# Leads
# --------------------------------------------------------------------------- #
def upsert_lead(session: Any, *, user_id: str, thread: InboxThread, source: str, excerpt: str,
                signals: list[str], score: int) -> tuple[EngagementLead, bool]:
    row = session.execute(
        select(EngagementLead).where(EngagementLead.user_id == user_id, EngagementLead.thread_id == thread.id)
    ).scalar_one_or_none()
    created = row is None
    if row is None:
        row = EngagementLead(user_id=user_id, thread_id=thread.id, platform=thread.platform, source=source,
                             signals=[], status=LEAD_NEW)
        session.add(row)
    row.author_name = (thread.author_name or "")[:200]
    row.author_external_id = (thread.author_external_id or "")[:128]
    row.excerpt = excerpt[:1000]
    row.signals = sorted(set(list(row.signals or []) + signals))[:12]
    row.score = max(int(row.score or 0), score)
    row.permalink = thread.permalink or row.permalink or ""
    row.last_message_at = thread.last_inbound_at or thread.last_message_at
    session.flush()
    return row, created


def get_lead(session: Any, user_id: str, lead_id: str) -> EngagementLead | None:
    row = session.get(EngagementLead, lead_id)
    return row if row is not None and row.user_id == user_id else None


def list_leads(session: Any, user_id: str, *, status: str = "", limit: int = 50,
               offset: int = 0) -> tuple[list[EngagementLead], int]:
    conditions = [EngagementLead.user_id == user_id]
    if status:
        conditions.append(EngagementLead.status == status)
    total = int(session.execute(select(func.count()).select_from(EngagementLead).where(*conditions)).scalar() or 0)
    rows = session.execute(
        select(EngagementLead).where(*conditions)
        .order_by(EngagementLead.score.desc(), EngagementLead.last_message_at.desc().nullslast())
        .limit(max(1, min(limit, 100))).offset(max(0, offset))
    ).scalars().all()
    return list(rows), total


def new_lead_count(session: Any, user_id: str) -> int:
    return int(session.execute(
        select(func.count()).select_from(EngagementLead)
        .where(EngagementLead.user_id == user_id, EngagementLead.status == LEAD_NEW)
    ).scalar() or 0)


# --------------------------------------------------------------------------- #
# Candidate threads
# --------------------------------------------------------------------------- #
def candidate_threads(session: Any, user_id: str, platform: str, since: datetime, *, limit: int) -> list[InboxThread]:
    return list(session.execute(
        select(InboxThread)
        .where(
            InboxThread.user_id == user_id,
            InboxThread.platform == platform,
            InboxThread.status == STATUS_NEEDS_REPLY,
            InboxThread.last_inbound_at.is_not(None),
            InboxThread.last_inbound_at >= since,
        )
        .order_by(InboxThread.last_inbound_at.desc())
        .limit(max(1, limit))
    ).scalars().all())
