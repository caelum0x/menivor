"""JSON views for the social inbox (token-free, owner-scoped inputs only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import repository as repo
from .capabilities import PLATFORM_LABELS, PLATFORMS, PlatformCapabilities, capabilities_for
from .models import STATUS_DONE, STATUS_NEEDS_REPLY, STATUS_REPLIED, InboxPost, InboxThread
from .replies import publishing_open, reply_mode
from .sync import connected_platforms

_PREVIEW_CHARS = 280


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def capability_map(session: Any, user_id: str) -> dict[str, PlatformCapabilities]:
    connected = connected_platforms(session, user_id)
    return {
        plat: capabilities_for(plat, connected=plat in connected, scopes=connected.get(plat, ""))
        for plat in PLATFORMS
    }


def post_record(post: InboxPost) -> dict:
    is_dm = repo.is_dm_channel(post)
    return {
        "id": post.id,
        "platform": post.platform,
        "platform_label": PLATFORM_LABELS.get(post.platform, post.platform),
        "kind": "dm_channel" if is_dm else "post",
        "job_id": post.job_id,
        "external_id": "" if is_dm else post.external_id,
        "title": post.title or "",
        "url": post.url or "",
        "posted_at": _iso(post.posted_at),
        "inbox_state": post.inbox_state,
        "state_note": post.state_note or "",
        "counts": {
            "platform_comments": post.platform_comment_count,
            "platform_likes": post.platform_like_count,
            "platform_views": post.platform_view_count,
            "synced_comments": int(post.synced_comment_count or 0),
            "needs_reply": int(post.needs_reply_count or 0),
            "replied": int(post.replied_count or 0),
        },
        "last_polled_at": _iso(post.last_polled_at),
        "next_poll_at": _iso(post.next_poll_at),
    }


def thread_record(
    thread: InboxThread,
    post: InboxPost | None,
    caps: PlatformCapabilities | None,
    *,
    publishing: bool,
    full: bool = False,
) -> dict:
    mode = reply_mode(thread, post, caps, publishing=publishing)
    messages = [m for m in (thread.messages or []) if isinstance(m, dict)]
    record = {
        "id": thread.id,
        "platform": thread.platform,
        "platform_label": PLATFORM_LABELS.get(thread.platform, thread.platform),
        "kind": thread.kind,
        "post_id": thread.post_id,
        "post_title": (post.title if post is not None else "") or "",
        "author_name": thread.author_name or "",
        "text": (thread.text or "") if full else (thread.text or "")[:_PREVIEW_CHARS],
        "like_count": int(thread.like_count or 0),
        "message_count": len(messages),
        "status": thread.status,
        "last_message_at": _iso(thread.last_message_at),
        "last_inbound_at": _iso(thread.last_inbound_at),
        "replied_at": _iso(thread.replied_at),
        "reply_via": thread.reply_via or "",
        "reply_text": thread.reply_text or "",
        "reply": mode.to_record(),
    }
    if full:
        record["messages"] = [
            {
                "id": str(m.get("id") or ""),
                "author": str(m.get("author") or ""),
                "text": str(m.get("text") or ""),
                "at": m.get("at"),
                "from_me": bool(m.get("from_me")),
                "via": str(m.get("via") or ""),
            }
            for m in messages
        ]
    return record


def overview(session: Any, user_id: str) -> dict:
    caps = capability_map(session, user_id)
    posts = repo.list_posts(session, user_id)
    totals = repo.status_totals(session, user_id)
    by_status = {STATUS_NEEDS_REPLY: 0, STATUS_REPLIED: 0, STATUS_DONE: 0}
    for per_platform in totals.values():
        for status, count in per_platform.items():
            by_status[status] = by_status.get(status, 0) + count
    last_polled = [p.last_polled_at for p in posts if p.last_polled_at]
    return {
        "platforms": [caps[p].to_record() for p in PLATFORMS],
        "posts": [post_record(p) for p in posts],
        "totals": {
            "by_status": by_status,
            "needs_reply_by_platform": {
                plat: int(totals.get(plat, {}).get(STATUS_NEEDS_REPLY, 0)) for plat in PLATFORMS
            },
        },
        "sending_enabled": publishing_open(),
        "last_synced_at": _iso(max(last_polled)) if last_polled else None,
    }


def thread_list(session: Any, user_id: str, rows: list[InboxThread], total: int, *, limit: int, offset: int) -> dict:
    caps = capability_map(session, user_id)
    publishing = publishing_open()
    post_ids = {r.post_id for r in rows if r.post_id}
    posts = {pid: repo.get_post(session, user_id, pid) for pid in post_ids}
    return {
        "threads": [
            thread_record(r, posts.get(r.post_id) if r.post_id else None, caps.get(r.platform), publishing=publishing)
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def thread_detail(session: Any, user_id: str, thread: InboxThread) -> dict:
    caps = capability_map(session, user_id)
    post = repo.get_post(session, user_id, thread.post_id) if thread.post_id else None
    record = thread_record(thread, post, caps.get(thread.platform), publishing=publishing_open(), full=True)
    record["post"] = post_record(post) if post is not None else None
    return record
