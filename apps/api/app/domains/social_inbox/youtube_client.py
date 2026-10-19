"""YouTube Data API v3 comment reads + replies for the social inbox.

* Read  - ``GET /youtube/v3/commentThreads?part=snippet,replies&videoId=...``
  (1 quota unit per page). Newest first; at most ``max_pages`` pages per poll.
* Reply - ``POST /youtube/v3/comments?part=snippet`` with ``parentId`` (50 units).

A 403 is split by the API's ``reason``: ``commentsDisabled`` means the creator
turned comments off (not a permission problem); ``quotaExceeded`` /
``rateLimitExceeded`` are retryable; anything else is a scope refusal.
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

PLATFORM = "youtube"
_API = "https://www.googleapis.com/youtube/v3"
_PAGE_SIZE = 50
MAX_REPLY_CHARS = 10_000


def comment_url(video_id: str, comment_id: str = "") -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    return f"{base}&lc={comment_id}" if comment_id else base


def _reason(body: dict) -> str:
    err = body.get("error") if isinstance(body, dict) else None
    if not isinstance(err, dict):
        return ""
    errors = err.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("reason") or "")
    return str(err.get("status") or "")


def _raise_for(resp, action: str) -> None:
    status = status_of(resp)
    body = json_of(resp)
    reason = _reason(body)
    if reason == "commentsDisabled":
        raise InboxPlatformError(PLATFORM, "Comments are turned off for this video.", not_available=True)
    if reason in ("videoNotFound",) or status == 404:
        raise InboxPlatformError(PLATFORM, "YouTube no longer returns this video (deleted or private).",
                                 not_available=True)
    if reason in ("quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded") or status == 429 or status >= 500:
        raise InboxPlatformError(PLATFORM, f"YouTube {action} is rate limited right now; will retry.",
                                 retryable=True)
    if status in (401, 403):
        raise InboxPlatformError(
            PLATFORM, "YouTube refused comment access for this connection. Reconnect and allow managing comments.",
            permission=True,
        )
    raise InboxPlatformError(PLATFORM, f"YouTube {action} failed (HTTP {status}).")


def _message(item: dict, own_channel_id: str) -> FetchedMessage | None:
    if not isinstance(item, dict):
        return None
    snippet = item.get("snippet") or {}
    author_id = str((snippet.get("authorChannelId") or {}).get("value") or "")
    text = str(snippet.get("textOriginal") or snippet.get("textDisplay") or "")
    comment_id = str(item.get("id") or "")
    if not comment_id:
        return None
    return FetchedMessage(
        external_id=comment_id,
        author_name=str(snippet.get("authorDisplayName") or ""),
        author_id=author_id,
        text=text,
        at=parse_time(snippet.get("publishedAt")),
        from_me=bool(own_channel_id) and author_id == own_channel_id,
    )


def _thread(item: dict, video_id: str, own_channel_id: str) -> FetchedThread | None:
    snippet = item.get("snippet") or {}
    top = _message(snippet.get("topLevelComment") or {}, own_channel_id)
    if top is None:
        return None
    replies = [
        m for m in (_message(r, own_channel_id) for r in ((item.get("replies") or {}).get("comments") or []))
        if m is not None
    ]
    like_count = int(((snippet.get("topLevelComment") or {}).get("snippet") or {}).get("likeCount") or 0)
    return FetchedThread(
        kind=KIND_COMMENT,
        external_thread_id=top.external_id,
        author_name=top.author_name,
        author_id=top.author_id,
        text=top.text,
        permalink=comment_url(video_id, top.external_id),
        like_count=max(0, like_count),
        messages=(top, *replies),
    )


def fetch_comment_threads(
    token: str, video_id: str, own_channel_id: str, *, transport: Transport, max_pages: int = 2
) -> list[FetchedThread]:
    """Newest comment threads on ``video_id`` (bounded to ``max_pages`` pages)."""
    if not token or not video_id:
        raise InboxPlatformError(PLATFORM, "missing token or video id")
    headers = {"Authorization": f"Bearer {token}"}
    threads: list[FetchedThread] = []
    page_token = ""
    for _ in range(max(1, max_pages)):
        params = {
            "part": "snippet,replies",
            "videoId": video_id,
            "maxResults": str(_PAGE_SIZE),
            "order": "time",
            "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token
        resp = transport.request("GET", f"{_API}/commentThreads", headers=headers, params=params)
        if not is_ok(resp):
            _raise_for(resp, "comment read")
        body = json_of(resp)
        for item in body.get("items") or []:
            thread = _thread(item, video_id, own_channel_id) if isinstance(item, dict) else None
            if thread is not None:
                threads.append(thread)
        page_token = str(body.get("nextPageToken") or "")
        if not page_token:
            break
    return threads


def reply_to_comment(token: str, parent_comment_id: str, text: str, *, transport: Transport) -> str:
    """Post ``text`` as a reply under ``parent_comment_id``; returns the new comment id."""
    if not token or not parent_comment_id:
        raise InboxPlatformError(PLATFORM, "missing token or comment id")
    resp = transport.request(
        "POST",
        f"{_API}/comments",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        params={"part": "snippet"},
        json={"snippet": {"parentId": parent_comment_id, "textOriginal": text[:MAX_REPLY_CHARS]}},
    )
    if not is_ok(resp):
        _raise_for(resp, "reply")
    reply_id = str(json_of(resp).get("id") or "")
    if not reply_id:
        raise InboxPlatformError(PLATFORM, "YouTube accepted the reply but returned no id.")
    return reply_id


def hide_comment(token: str, comment_id: str, *, transport: Transport) -> str:
    """Hide a comment from the channel's public view (``comments.setModerationStatus``).

    ``moderationStatus=rejected`` removes it from public display; only the
    channel owner can do this and it needs the ``youtube.force-ssl`` scope.
    Returns the comment id. YouTube has no API to like a comment.
    """
    if not token or not comment_id:
        raise InboxPlatformError(PLATFORM, "missing token or comment id")
    resp = transport.request(
        "POST",
        f"{_API}/comments/setModerationStatus",
        headers={"Authorization": f"Bearer {token}"},
        params={"id": comment_id, "moderationStatus": "rejected"},
    )
    if not is_ok(resp):
        _raise_for(resp, "hide")
    return comment_id
