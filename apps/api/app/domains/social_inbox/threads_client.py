"""Threads replies on Menivor posts: read, reply, hide (Threads API).

* Read  - ``GET /{media-id}/replies`` (``threads_read_replies``), top-level
  replies with their text, username and time.
* Reply - two steps like any Threads post: ``POST /{user-id}/threads`` with
  ``media_type=TEXT`` + ``reply_to_id``, then ``POST /{user-id}/threads_publish``
  (``threads_manage_replies``).
* Hide  - ``POST /{reply-id}/manage_reply?hide=true``.

The Threads API has no endpoint for an account to like a reply, and no DMs.
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

PLATFORM = "threads"
API = "https://graph.threads.net/v1.0"
MAX_REPLY_CHARS = 500
_FIELDS = "id,text,username,timestamp,permalink,hide_status"


def _raise_for(resp, action: str) -> None:
    status = status_of(resp)
    err = json_of(resp).get("error") or {}
    code = int(err.get("code") or 0) if isinstance(err, dict) else 0
    if code in (4, 17, 32, 613) or status == 429 or status >= 500:
        raise InboxPlatformError(PLATFORM, f"Threads {action} is rate limited right now; will retry.", retryable=True)
    if code in (190, 10) or 200 <= code <= 299 or status in (401, 403):
        raise InboxPlatformError(PLATFORM, "Threads refused this for the connected account. Reconnect Threads and "
                                           "allow reading and managing replies.", permission=True)
    if status == 404:
        raise InboxPlatformError(PLATFORM, "Threads no longer returns this post.", not_available=True)
    raise InboxPlatformError(PLATFORM, f"Threads {action} failed (HTTP {status}).")


def fetch_comment_threads(token: str, media_id: str, own_username: str, *, transport: Transport) -> list[FetchedThread]:
    if not token or not media_id:
        raise InboxPlatformError(PLATFORM, "missing token or post id")
    resp = transport.request("GET", f"{API}/{media_id}/replies",
                             params={"fields": _FIELDS, "reverse": "false", "access_token": token})
    if not is_ok(resp):
        _raise_for(resp, "reply read")
    me = own_username.lstrip("@").lower()
    out: list[FetchedThread] = []
    for item in json_of(resp).get("data") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if str(item.get("hide_status") or "").upper() == "HIDDEN":
            continue
        username = str(item.get("username") or "")
        msg = FetchedMessage(
            external_id=str(item["id"]),
            author_name=username,
            author_id=username,
            text=str(item.get("text") or ""),
            at=parse_time(item.get("timestamp")),
            from_me=bool(me) and username.lower() == me,
        )
        if msg.from_me:
            continue
        out.append(FetchedThread(
            kind=KIND_COMMENT, external_thread_id=msg.external_id, author_name=username, author_id=username,
            text=msg.text, permalink=str(item.get("permalink") or ""), messages=(msg,),
        ))
    return out


def reply_to_comment(token: str, user_id: str, reply_id: str, text: str, *, transport: Transport) -> str:
    create = transport.request("POST", f"{API}/{user_id}/threads", params={
        "media_type": "TEXT", "text": text[:MAX_REPLY_CHARS], "reply_to_id": reply_id, "access_token": token,
    })
    if not is_ok(create):
        _raise_for(create, "reply")
    container = str(json_of(create).get("id") or "")
    if not container:
        raise InboxPlatformError(PLATFORM, "Threads returned no reply container.")
    pub = transport.request("POST", f"{API}/{user_id}/threads_publish",
                            params={"creation_id": container, "access_token": token})
    if not is_ok(pub):
        _raise_for(pub, "reply")
    new_id = str(json_of(pub).get("id") or "")
    if not new_id:
        raise InboxPlatformError(PLATFORM, "Threads published the reply but returned no id.")
    return new_id


def hide_comment(token: str, reply_id: str, *, transport: Transport) -> str:
    resp = transport.request("POST", f"{API}/{reply_id}/manage_reply", params={"hide": "true", "access_token": token})
    if not is_ok(resp):
        _raise_for(resp, "hide")
    return reply_id
