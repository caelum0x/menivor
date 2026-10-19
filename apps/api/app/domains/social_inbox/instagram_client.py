"""Instagram API (Instagram Login) comment + DM reads and replies.

The account-connect flow authorizes at ``api.instagram.com`` (Instagram Login),
so its tokens are Instagram User tokens served by ``graph.instagram.com``. The
host is configurable (``[app] social_inbox_instagram_graph_base``) for accounts
connected through Facebook Login instead.

* Media      - ``GET /{media-id}?fields=permalink,comments_count,like_count``
* Comments   - ``GET /{media-id}/comments`` (+ nested ``replies``), newest pages first
* Reply      - ``POST /{comment-id}/replies?message=...``
* DMs        - ``GET /me/conversations?platform=instagram`` with nested messages
* DM reply   - ``POST /me/messages`` (only inside the 24h messaging window)

Graph error codes are mapped: 190/10/200-299 are permission refusals; 4/17/32/613
are rate limits (retryable); 100 with subcode 33 means the object is gone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import config

from .models import KIND_COMMENT, KIND_DM
from .platform_types import (
    FetchedMessage,
    FetchedThread,
    InboxPlatformError,
    Transport,
    is_ok,
    json_of,
    parse_time,
    status_of,
)

PLATFORM = "instagram"
_DEFAULT_GRAPH = "https://graph.instagram.com/v21.0"
_PAGE_SIZE = 50
MAX_COMMENT_CHARS = 2_200
MAX_DM_CHARS = 1_000
DM_WINDOW = timedelta(hours=24)
DM_INBOX_URL = "https://www.instagram.com/direct/inbox/"

_COMMENT_FIELDS = "id,text,username,timestamp,like_count,from,replies{id,text,username,timestamp,from}"
_DM_FIELDS = "id,updated_time,participants,messages.limit(20){id,created_time,from,to,message}"
_RATE_CODES = frozenset({4, 17, 32, 613})


def graph_base() -> str:
    return str(config.app.get("social_inbox_instagram_graph_base", "") or _DEFAULT_GRAPH).rstrip("/")


def _raise_for(resp, action: str) -> None:
    status = status_of(resp)
    err = json_of(resp).get("error") or {}
    code = int(err.get("code") or 0) if isinstance(err, dict) else 0
    subcode = int(err.get("error_subcode") or 0) if isinstance(err, dict) else 0
    if code in _RATE_CODES or status == 429 or status >= 500:
        raise InboxPlatformError(PLATFORM, f"Instagram {action} is rate limited right now; will retry.",
                                 retryable=True)
    if code == 100 and subcode == 33:
        raise InboxPlatformError(PLATFORM, "Instagram no longer returns this post.", not_available=True)
    if code == 190 or code == 10 or 200 <= code <= 299 or status in (401, 403):
        raise InboxPlatformError(
            PLATFORM,
            "Instagram refused this request for the connected account. Reconnect Instagram and allow "
            "comment and message management.",
            permission=True,
        )
    raise InboxPlatformError(PLATFORM, f"Instagram {action} failed (HTTP {status}).")


def _message(item: dict, own_user_id: str) -> FetchedMessage | None:
    if not isinstance(item, dict) or not item.get("id"):
        return None
    sender = item.get("from") or {}
    author_id = str(sender.get("id") or "") if isinstance(sender, dict) else ""
    author_name = str(item.get("username") or (sender.get("username") if isinstance(sender, dict) else "") or "")
    return FetchedMessage(
        external_id=str(item["id"]),
        author_name=author_name,
        author_id=author_id,
        text=str(item.get("text") or item.get("message") or ""),
        at=parse_time(item.get("timestamp") or item.get("created_time")),
        from_me=bool(own_user_id) and author_id == own_user_id,
    )


def fetch_media_counts(token: str, media_id: str, *, transport: Transport) -> dict:
    """``{"permalink", "comments_count", "like_count"}`` for one media (basic scope)."""
    resp = transport.request(
        "GET",
        f"{graph_base()}/{media_id}",
        params={"fields": "permalink,comments_count,like_count", "access_token": token},
    )
    if not is_ok(resp):
        _raise_for(resp, "media read")
    return json_of(resp)


def fetch_comment_threads(
    token: str, media_id: str, own_user_id: str, *, post_url: str, transport: Transport, max_pages: int = 2
) -> list[FetchedThread]:
    """Top-level comments (with replies) on ``media_id``, bounded to ``max_pages`` pages."""
    if not token or not media_id:
        raise InboxPlatformError(PLATFORM, "missing token or media id")
    url = f"{graph_base()}/{media_id}/comments"
    params: dict | None = {"fields": _COMMENT_FIELDS, "limit": str(_PAGE_SIZE), "access_token": token}
    threads: list[FetchedThread] = []
    for _ in range(max(1, max_pages)):
        resp = transport.request("GET", url, params=params)
        if not is_ok(resp):
            _raise_for(resp, "comment read")
        body = json_of(resp)
        for item in body.get("data") or []:
            top = _message(item, own_user_id)
            if top is None:
                continue
            replies = [
                m for m in (_message(r, own_user_id) for r in ((item.get("replies") or {}).get("data") or []))
                if m is not None
            ]
            threads.append(FetchedThread(
                kind=KIND_COMMENT,
                external_thread_id=top.external_id,
                author_name=top.author_name,
                author_id=top.author_id,
                text=top.text,
                permalink=post_url,
                like_count=max(0, int(item.get("like_count") or 0)),
                messages=(top, *replies),
            ))
        after = str(((body.get("paging") or {}).get("cursors") or {}).get("after") or "")
        if not after or not (body.get("paging") or {}).get("next"):
            break
        params = {"fields": _COMMENT_FIELDS, "limit": str(_PAGE_SIZE), "access_token": token, "after": after}
    return threads


def reply_to_comment(token: str, comment_id: str, text: str, *, transport: Transport) -> str:
    resp = transport.request(
        "POST",
        f"{graph_base()}/{comment_id}/replies",
        params={"message": text[:MAX_COMMENT_CHARS], "access_token": token},
    )
    if not is_ok(resp):
        _raise_for(resp, "reply")
    reply_id = str(json_of(resp).get("id") or "")
    if not reply_id:
        raise InboxPlatformError(PLATFORM, "Instagram accepted the reply but returned no id.")
    return reply_id


def fetch_dm_threads(token: str, own_user_id: str, *, transport: Transport, limit: int = 25) -> list[FetchedThread]:
    """Recent DM conversations with their latest messages."""
    resp = transport.request(
        "GET",
        f"{graph_base()}/me/conversations",
        params={"platform": "instagram", "fields": _DM_FIELDS, "limit": str(limit), "access_token": token},
    )
    if not is_ok(resp):
        _raise_for(resp, "direct message read")
    threads: list[FetchedThread] = []
    for convo in json_of(resp).get("data") or []:
        if not isinstance(convo, dict) or not convo.get("id"):
            continue
        messages = [
            m for m in (_message(x, own_user_id) for x in ((convo.get("messages") or {}).get("data") or []))
            if m is not None
        ]
        participants = [
            p for p in ((convo.get("participants") or {}).get("data") or [])
            if isinstance(p, dict) and str(p.get("id") or "") != own_user_id
        ]
        other = participants[0] if participants else {}
        inbound = [m for m in messages if not m.from_me]
        latest_in = max(inbound, key=lambda m: m.at or datetime.min.replace(tzinfo=timezone.utc)) if inbound else None
        threads.append(FetchedThread(
            kind=KIND_DM,
            external_thread_id=str(convo["id"]),
            author_name=str(other.get("username") or (latest_in.author_name if latest_in else "")),
            author_id=str(other.get("id") or (latest_in.author_id if latest_in else "")),
            text=latest_in.text if latest_in else "",
            permalink=DM_INBOX_URL,
            messages=tuple(sorted(messages, key=lambda m: m.at or datetime.min.replace(tzinfo=timezone.utc))),
        ))
    return threads


def within_dm_window(last_inbound_at: datetime | None, now: datetime | None = None) -> bool:
    if last_inbound_at is None:
        return False
    moment = now or datetime.now(timezone.utc)
    stamp = last_inbound_at if last_inbound_at.tzinfo else last_inbound_at.replace(tzinfo=timezone.utc)
    return moment - stamp <= DM_WINDOW


def send_dm(token: str, recipient_id: str, text: str, *, transport: Transport) -> str:
    if not recipient_id:
        raise InboxPlatformError(PLATFORM, "missing recipient id for this conversation")
    resp = transport.request(
        "POST",
        f"{graph_base()}/me/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"recipient": {"id": recipient_id}, "message": {"text": text[:MAX_DM_CHARS]}},
    )
    if not is_ok(resp):
        _raise_for(resp, "direct message")
    message_id = str(json_of(resp).get("message_id") or json_of(resp).get("id") or "")
    if not message_id:
        raise InboxPlatformError(PLATFORM, "Instagram accepted the message but returned no id.")
    return message_id


def hide_comment(token: str, comment_id: str, *, transport: Transport) -> str:
    """Hide a comment on the creator's media (``POST /{comment-id}?hide=true``).

    Hidden comments stay visible to their author only. The Instagram API has
    no endpoint for an account to like a comment.
    """
    resp = transport.request(
        "POST",
        f"{graph_base()}/{comment_id}",
        params={"hide": "true", "access_token": token},
    )
    if not is_ok(resp):
        _raise_for(resp, "hide")
    return comment_id
