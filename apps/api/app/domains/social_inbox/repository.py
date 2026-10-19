"""Owner-scoped persistence for the social inbox.

Every query filters on ``user_id``; a guessed id from another creator resolves to
``None``. Thread upserts merge the platform's view with local reply/done state:
a new inbound message after the creator replied (or marked done) reopens the
thread as ``needs_reply``; a reply the creator made directly on the platform
closes it as ``replied``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func, select

from .models import (
    MAX_THREAD_MESSAGES,
    STATUS_DONE,
    STATUS_NEEDS_REPLY,
    STATUS_REPLIED,
    InboxPost,
    InboxThread,
)
from .platform_types import FetchedThread

# External-id prefix of the per-account "Direct messages" channel row. It rides
# in ``social_inbox_posts`` so DMs share the poll schedule and state machinery.
DM_CHANNEL_PREFIX = "dm:"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def is_dm_channel(post: InboxPost) -> bool:
    return str(post.external_id or "").startswith(DM_CHANNEL_PREFIX)


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #
def get_post(session: Any, user_id: str, post_id: str) -> InboxPost | None:
    row = session.get(InboxPost, post_id)
    return row if row is not None and row.user_id == user_id else None


def find_post(session: Any, user_id: str, platform: str, external_id: str) -> InboxPost | None:
    return session.execute(
        select(InboxPost).where(
            InboxPost.user_id == user_id, InboxPost.platform == platform, InboxPost.external_id == external_id
        )
    ).scalar_one_or_none()


def ensure_post(
    session: Any,
    *,
    user_id: str,
    platform: str,
    external_id: str,
    job_id: str | None,
    url: str,
    title: str,
    posted_at: datetime | None,
    now: datetime,
) -> tuple[InboxPost, bool]:
    """Create the tracked post when missing; returns ``(row, created)``."""
    row = find_post(session, user_id, platform, external_id)
    if row is not None:
        if url and not row.url:
            row.url = url
        return row, False
    row = InboxPost(
        user_id=user_id,
        job_id=job_id,
        platform=platform,
        external_id=external_id,
        url=url or "",
        title=(title or "")[:300],
        posted_at=posted_at,
        next_poll_at=now,
    )
    session.add(row)
    session.flush()
    return row, True


def list_posts(session: Any, user_id: str, *, limit: int = 100) -> list[InboxPost]:
    return list(session.execute(
        select(InboxPost)
        .where(InboxPost.user_id == user_id)
        .order_by(InboxPost.posted_at.desc().nullslast(), InboxPost.created_at.desc())
        .limit(max(1, min(limit, 200)))
    ).scalars().all())


def due_post_ids(session: Any, now: datetime, *, limit: int) -> list[tuple[str, str]]:
    """Claim up to ``limit`` due posts (``(post_id, user_id)``), skipping locked rows."""
    rows = session.execute(
        select(InboxPost)
        .where(InboxPost.next_poll_at.is_not(None), InboxPost.next_poll_at <= now)
        .order_by(InboxPost.next_poll_at.asc())
        .limit(max(1, limit))
        .with_for_update(skip_locked=True)
    ).scalars().all()
    return [(r.id, r.user_id) for r in rows]


def refresh_post_counts(session: Any, post: InboxPost) -> None:
    """Recompute thread-derived counters on ``post`` from its stored threads."""
    threads = session.execute(select(InboxThread).where(InboxThread.post_id == post.id)).scalars().all()
    inbound = 0
    needs = 0
    replied = 0
    for t in threads:
        inbound += sum(1 for m in (t.messages or []) if isinstance(m, dict) and not m.get("from_me"))
        if t.status == STATUS_NEEDS_REPLY:
            needs += 1
        elif t.status == STATUS_REPLIED:
            replied += 1
    post.synced_comment_count = inbound
    post.needs_reply_count = needs
    post.replied_count = replied


def observed_comments_for_job(session: Any, user_id: str, job_id: str) -> int:
    """Comments actually observed across every tracked post of ``job_id``.

    Per post the larger of the platform-reported count and the comments we
    pulled ourselves (they differ when a platform hides some, or when the count
    endpoint is not permitted but the comment list is).
    """
    rows = session.execute(
        select(InboxPost).where(InboxPost.user_id == user_id, InboxPost.job_id == job_id)
    ).scalars().all()
    return sum(max(int(r.platform_comment_count or 0), int(r.synced_comment_count or 0)) for r in rows)


# --------------------------------------------------------------------------- #
# Threads
# --------------------------------------------------------------------------- #
def get_thread(session: Any, user_id: str, thread_id: str) -> InboxThread | None:
    row = session.get(InboxThread, thread_id)
    return row if row is not None and row.user_id == user_id else None


def _merge_messages(existing: Iterable[Any], fetched: FetchedThread) -> list[dict]:
    by_id: dict[str, dict] = {}
    for m in existing or []:
        if isinstance(m, dict) and m.get("id"):
            by_id[str(m["id"])] = dict(m)
    for m in fetched.messages:
        record = m.to_record()
        prior = by_id.get(m.external_id)
        # Keep the "sent from Menivor" marker set when we posted this reply.
        if prior and prior.get("via") == "menivor":
            record["via"] = "menivor"
        by_id[m.external_id] = record
    ordered = sorted(by_id.values(), key=lambda r: str(r.get("at") or ""))
    return ordered[-MAX_THREAD_MESSAGES:]


def _next_status(row: InboxThread | None, fetched: FetchedThread) -> str:
    last_in = _aware(fetched.last_inbound_at)
    if row is None:
        return STATUS_REPLIED if fetched.last_from_me else STATUS_NEEDS_REPLY
    handled_at = max(_aware(row.replied_at) or _EPOCH, _aware(row.done_at) or _EPOCH)
    if row.status in (STATUS_REPLIED, STATUS_DONE):
        if last_in is not None and last_in > handled_at:
            return STATUS_NEEDS_REPLY
        return row.status
    # needs_reply: a reply made directly on the platform closes the thread.
    return STATUS_REPLIED if fetched.last_from_me else STATUS_NEEDS_REPLY


def upsert_thread(
    session: Any, *, user_id: str, platform: str, post_id: str | None, fetched: FetchedThread, now: datetime
) -> InboxThread:
    row = session.execute(
        select(InboxThread).where(
            InboxThread.user_id == user_id,
            InboxThread.platform == platform,
            InboxThread.kind == fetched.kind,
            InboxThread.external_thread_id == fetched.external_thread_id,
        )
    ).scalar_one_or_none()
    status = _next_status(row, fetched)
    if row is None:
        row = InboxThread(
            user_id=user_id,
            post_id=post_id,
            platform=platform,
            kind=fetched.kind,
            external_thread_id=fetched.external_thread_id,
            messages=[],
        )
        session.add(row)
    previous_status = row.status
    row.post_id = post_id or row.post_id
    row.author_name = (fetched.author_name or row.author_name or "")[:200]
    row.author_external_id = (fetched.author_id or row.author_external_id or "")[:128]
    row.text = fetched.text or row.text or ""
    row.permalink = fetched.permalink or row.permalink or ""
    row.like_count = max(0, int(fetched.like_count or 0))
    row.messages = _merge_messages(row.messages, fetched)
    row.last_inbound_at = _aware(fetched.last_inbound_at) or row.last_inbound_at
    row.last_message_at = _aware(fetched.last_message_at) or row.last_message_at
    row.status = status
    if status == STATUS_REPLIED and previous_status == STATUS_NEEDS_REPLY and row.replied_at is None:
        row.replied_at = now
        row.reply_via = row.reply_via or "platform"
    session.flush()
    return row


def list_threads(
    session: Any,
    user_id: str,
    *,
    platform: str = "",
    post_id: str = "",
    status: str = "",
    kind: str = "",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[InboxThread], int]:
    conditions = [InboxThread.user_id == user_id]
    if platform:
        conditions.append(InboxThread.platform == platform)
    if post_id:
        conditions.append(InboxThread.post_id == post_id)
    if status:
        conditions.append(InboxThread.status == status)
    if kind:
        conditions.append(InboxThread.kind == kind)
    total = int(session.execute(select(func.count()).select_from(InboxThread).where(*conditions)).scalar() or 0)
    rows = session.execute(
        select(InboxThread)
        .where(*conditions)
        .order_by(InboxThread.last_message_at.desc().nullslast(), InboxThread.created_at.desc())
        .limit(max(1, min(limit, 100)))
        .offset(max(0, offset))
    ).scalars().all()
    return list(rows), total


def status_totals(session: Any, user_id: str) -> dict[str, dict[str, int]]:
    """``{platform: {status: n}}`` across every thread of the owner."""
    rows = session.execute(
        select(InboxThread.platform, InboxThread.status, func.count())
        .where(InboxThread.user_id == user_id)
        .group_by(InboxThread.platform, InboxThread.status)
    ).all()
    out: dict[str, dict[str, int]] = {}
    for platform, status, count in rows:
        out.setdefault(str(platform), {})[str(status)] = int(count)
    return out
