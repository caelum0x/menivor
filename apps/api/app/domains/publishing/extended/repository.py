"""Owner-scoped persistence for extended-platform connections, OAuth states and posts.

Every read filters on ``user_id``; a guessed id from another creator resolves
to ``None``. Token columns are written only with ``crypto_tokens`` blobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import delete, func, select

from .models import (
    ACTIVE_POST_STATUSES,
    POST_PROCESSING,
    POST_PUBLISHED,
    POST_SCHEDULED,
    PlatformConnection,
    PlatformOAuthState,
    PlatformPost,
)

OAUTH_STATE_TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class StateSnapshot:
    platform: str
    code_verifier_enc: str | None
    scopes: str
    expires_at: datetime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #
def get_connection(session: Any, user_id: str, platform: str) -> PlatformConnection | None:
    return session.execute(
        select(PlatformConnection).where(
            PlatformConnection.user_id == user_id, PlatformConnection.platform == platform
        )
    ).scalar_one_or_none()


def list_connections(session: Any, user_id: str) -> list[PlatformConnection]:
    return list(session.execute(
        select(PlatformConnection).where(PlatformConnection.user_id == user_id)
    ).scalars().all())


def upsert_connection(session: Any, *, user_id: str, platform: str, values: dict) -> PlatformConnection:
    row = get_connection(session, user_id, platform)
    if row is None:
        row = PlatformConnection(user_id=user_id, platform=platform, **{"targets": [], "meta": {}, **values})
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return row


def delete_connection(session: Any, user_id: str, platform: str) -> bool:
    row = get_connection(session, user_id, platform)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


# --------------------------------------------------------------------------- #
# OAuth states (single use, bound to the creator)
# --------------------------------------------------------------------------- #
def add_state(session: Any, *, state_hash: str, user_id: str, platform: str, verifier_enc: str | None,
              scopes: str, now: datetime | None = None) -> None:
    moment = now or utcnow()
    session.execute(delete(PlatformOAuthState).where(PlatformOAuthState.expires_at < moment))
    session.add(PlatformOAuthState(
        state_hash=state_hash, user_id=user_id, platform=platform,
        code_verifier_enc=verifier_enc, scopes=scopes or "", expires_at=moment + OAUTH_STATE_TTL,
    ))
    session.flush()


def consume_state(session: Any, *, state_hash: str, user_id: str,
                  now: datetime | None = None) -> StateSnapshot | None:
    """Delete and return the state when it exists, belongs to ``user_id`` and is fresh."""
    row = session.get(PlatformOAuthState, state_hash)
    if row is None or row.user_id != user_id:
        return None  # unknown, replayed, or another creator's state (left untouched)
    snapshot = StateSnapshot(
        platform=row.platform,
        code_verifier_enc=row.code_verifier_enc,
        scopes=row.scopes or "",
        expires_at=aware(row.expires_at) or utcnow(),
    )
    session.delete(row)
    session.flush()
    if snapshot.expires_at < (now or utcnow()):
        return None
    return snapshot


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #
def add_post(session: Any, **values: Any) -> PlatformPost:
    row = PlatformPost(progress={}, **values)
    session.add(row)
    session.flush()
    return row


def get_post(session: Any, user_id: str, post_id: str) -> PlatformPost | None:
    row = session.get(PlatformPost, post_id)
    return row if row is not None and row.user_id == user_id else None


def list_posts(session: Any, user_id: str, *, statuses: Iterable[str] = (), job_id: str = "",
               limit: int = 50, offset: int = 0) -> tuple[list[PlatformPost], int]:
    conditions = [PlatformPost.user_id == user_id]
    wanted = [s for s in statuses if s]
    if wanted:
        conditions.append(PlatformPost.status.in_(wanted))
    if job_id:
        conditions.append(PlatformPost.job_id == job_id)
    total = int(session.execute(select(func.count()).select_from(PlatformPost).where(*conditions)).scalar() or 0)
    rows = session.execute(
        select(PlatformPost).where(*conditions)
        .order_by(PlatformPost.scheduled_at.desc(), PlatformPost.created_at.desc())
        .limit(max(1, min(limit, 100))).offset(max(0, offset))
    ).scalars().all()
    return list(rows), total


def claim_due(session: Any, now: datetime, *, lease: timedelta, limit: int) -> list[tuple[str, str]]:
    """Claim due scheduled/processing posts (``(post_id, user_id)``), pushing them past a lease."""
    rows = session.execute(
        select(PlatformPost)
        .where(
            PlatformPost.status.in_([POST_SCHEDULED, POST_PROCESSING]),
            PlatformPost.next_attempt_at.is_not(None),
            PlatformPost.next_attempt_at <= now,
        )
        .order_by(PlatformPost.next_attempt_at.asc())
        .limit(max(1, limit))
        .with_for_update(skip_locked=True)
    ).scalars().all()
    for row in rows:
        row.next_attempt_at = now + lease
    session.flush()
    return [(r.id, r.user_id) for r in rows]


def published_count_since(session: Any, platform: str, since: datetime) -> int:
    """Posts published to ``platform`` across all creators since ``since`` (operator spend guard)."""
    return int(session.execute(
        select(func.count()).select_from(PlatformPost).where(
            PlatformPost.platform == platform,
            PlatformPost.status.in_([POST_PUBLISHED, *ACTIVE_POST_STATUSES]),
            PlatformPost.created_at >= since,
        )
    ).scalar() or 0)
