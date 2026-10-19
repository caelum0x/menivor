"""Facebook Page video comments: read, reply, like, hide (Graph API, Page token).

* Read   - ``GET /{video-id}/comments`` (newest first) with nested replies.
  ``pages_read_engagement`` + ``pages_read_user_content``.
* Reply  - ``POST /{comment-id}/comments`` (``pages_manage_engagement``).
* Like   - ``POST /{comment-id}/likes`` (the Page likes the comment).
* Hide   - ``POST /{comment-id}?is_hidden=true`` (visible only to its author
  and their friends).

Facebook only returns the commenter's name/id when the app has the right
permissions; otherwise the author shows as "Facebook user".
"""

from __future__ import annotations

from .models import KIND_COMMENT
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

PLATFORM = "facebook"
GRAPH = "https://graph.facebook.com/v21.0"
MAX_REPLY_CHARS = 8_000
_FIELDS = (
    "id,message,from{id,name},created_time,like_count,permalink_url,"
    "comments.limit(25){id,message,from{id,name},created_time}"
)
_RATE_CODES = frozenset({4, 17, 32, 613})


def _raise_for(resp, action: str) -> None:
    status = status_of(resp)
    err = json_of(resp).get("error") or {}
    code = int(err.get("code") or 0) if isinstance(err, dict) else 0
    if code in _RATE_CODES or status == 429 or status >= 500:
        raise InboxPlatformError(PLATFORM, f"Facebook {action} is rate limited right now; will retry.", retryable=True)
    if code == 100 and status == 400 and "does not exist" in str(err.get("message") or ""):
        raise InboxPlatformError(PLATFORM, "Facebook no longer returns this video.", not_available=True)
    if code in (190, 10) or 200 <= code <= 299 or status in (401, 403):
        raise InboxPlatformError(
            PLATFORM, "Facebook refused this for the connected Page. Reconnect Facebook and allow managing "
                      "engagement on the Page.",
            permission=True,
        )
    raise InboxPlatformError(PLATFORM, f"Facebook {action} failed (HTTP {status}).")


def _message(item: dict, page_id: str) -> FetchedMessage | None:
    if not isinstance(item, dict) or not item.get("id"):
        return None
    sender = item.get("from") if isinstance(item.get("from"), dict) else {}
    author_id = str(sender.get("id") or "")
    return FetchedMessage(
        external_id=str(item["id"]),
        author_name=str(sender.get("name") or "Facebook user"),
        author_id=author_id,
        text=str(item.get("message") or ""),
        at=parse_time(item.get("created_time")),
        from_me=bool(page_id) and author_id == page_id,
    )


def fetch_comment_threads(page_token: str, video_id: str, page_id: str, *, transport: Transport,
                          max_pages: int = 2) -> list[FetchedThread]:
    if not page_token or not video_id:
        raise InboxPlatformError(PLATFORM, "missing Page token or video id")
    params: dict = {"fields": _FIELDS, "order": "reverse_chronological", "limit": "50", "access_token": page_token}
    url = f"{GRAPH}/{video_id}/comments"
    threads: list[FetchedThread] = []
    for _ in range(max(1, max_pages)):
        resp = transport.request("GET", url, params=params)
        if not is_ok(resp):
            _raise_for(resp, "comment read")
        body = json_of(resp)
        for item in body.get("data") or []:
            top = _message(item, page_id)
            if top is None:
                continue
            replies = [m for m in (_message(r, page_id) for r in ((item.get("comments") or {}).get("data") or []))
                       if m is not None]
            threads.append(FetchedThread(
                kind=KIND_COMMENT,
                external_thread_id=top.external_id,
                author_name=top.author_name,
                author_id=top.author_id,
                text=top.text,
                permalink=str(item.get("permalink_url") or ""),
                like_count=max(0, int(item.get("like_count") or 0)),
                messages=(top, *replies),
            ))
        after = str(((body.get("paging") or {}).get("cursors") or {}).get("after") or "")
        if not after or not (body.get("paging") or {}).get("next"):
            break
        params = {**params, "after": after}
    return threads


def reply_to_comment(page_token: str, comment_id: str, text: str, *, transport: Transport) -> str:
    resp = transport.request("POST", f"{GRAPH}/{comment_id}/comments",
                             data={"message": text[:MAX_REPLY_CHARS], "access_token": page_token})
    if not is_ok(resp):
        _raise_for(resp, "reply")
    reply_id = str(json_of(resp).get("id") or "")
    if not reply_id:
        raise InboxPlatformError(PLATFORM, "Facebook accepted the reply but returned no id.")
    return reply_id


def like_comment(page_token: str, comment_id: str, *, transport: Transport) -> str:
    resp = transport.request("POST", f"{GRAPH}/{comment_id}/likes", data={"access_token": page_token})
    if not is_ok(resp):
        _raise_for(resp, "like")
    return comment_id


def hide_comment(page_token: str, comment_id: str, *, transport: Transport) -> str:
    resp = transport.request("POST", f"{GRAPH}/{comment_id}", data={"is_hidden": "true", "access_token": page_token})
    if not is_ok(resp):
        _raise_for(resp, "hide")
    return comment_id
