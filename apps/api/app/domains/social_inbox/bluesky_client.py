"""Bluesky replies on Menivor posts: read, reply, like (AT Protocol via the PDS).

* Read  - ``app.bsky.feed.getPostThread?uri=<post>&depth=2`` (the PDS proxies
  the read to the Bluesky AppView).
* Reply - ``com.atproto.repo.createRecord`` of an ``app.bsky.feed.post`` with
  ``reply.root`` / ``reply.parent`` (uri + cid from ``app.bsky.feed.getPosts``).
* Like  - ``createRecord`` of an ``app.bsky.feed.like`` for the reply.

Bluesky has no "hide a reply" call for app-password clients here, so spam and
abuse are flagged in Menivor instead.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.domains.publishing.extended.connectors import bluesky as bsky
from app.domains.publishing.extended.connectors.base import PublishError

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

PLATFORM = "bluesky"
MAX_REPLY_GRAPHEMES = 300
_SESSION_TTL_S = 20 * 60
_CACHE: dict[str, tuple[float, "Session"]] = {}
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Session:
    access_jwt: str
    did: str
    handle: str
    pds: str


def session_for(identifier: str, app_password: str, pds: str, *, transport: Transport) -> Session:
    """A cached app-password session (Bluesky rate-limits logins per account)."""
    key = f"{pds}|{identifier}"
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]
    try:
        raw = bsky.create_session(identifier, app_password, pds, transport=transport)
    except PublishError as exc:
        message = str(exc).split("] ", 1)[-1]
        raise InboxPlatformError(PLATFORM, message, permission="rejected" in message,
                                 retryable=bool(exc.retryable)) from exc
    session = Session(access_jwt=raw.access_jwt, did=raw.did, handle=raw.handle, pds=raw.pds)
    with _LOCK:
        _CACHE[key] = (now + _SESSION_TTL_S, session)
    return session


def _headers(session: Session, *, json_body: bool = False) -> dict:
    out = {"Authorization": f"Bearer {session.access_jwt}"}
    if json_body:
        out["Content-Type"] = "application/json"
    return out


def _raise_for(resp, action: str) -> None:
    status = status_of(resp)
    err = str(json_of(resp).get("error") or "")
    if status == 429 or status >= 500:
        raise InboxPlatformError(PLATFORM, f"Bluesky {action} is rate limited right now; will retry.", retryable=True)
    if err == "NotFound" or status == 404:
        raise InboxPlatformError(PLATFORM, "Bluesky no longer returns this post.", not_available=True)
    if status in (401, 403) or err in ("ExpiredToken", "InvalidToken", "AuthRequired"):
        with _LOCK:
            _CACHE.clear()
        raise InboxPlatformError(PLATFORM, "Bluesky refused this login. Reconnect Bluesky with a new app password.",
                                 permission=True)
    raise InboxPlatformError(PLATFORM, f"Bluesky {action} failed (HTTP {status}).")


def _message(node: dict, own_did: str) -> FetchedMessage | None:
    post = node.get("post") if isinstance(node, dict) else None
    if not isinstance(post, dict) or not post.get("uri"):
        return None
    author = post.get("author") if isinstance(post.get("author"), dict) else {}
    record = post.get("record") if isinstance(post.get("record"), dict) else {}
    did = str(author.get("did") or "")
    return FetchedMessage(
        external_id=str(post["uri"]),
        author_name=str(author.get("displayName") or author.get("handle") or ""),
        author_id=did,
        text=str(record.get("text") or ""),
        at=parse_time(record.get("createdAt") or post.get("indexedAt")),
        from_me=bool(own_did) and did == own_did,
    )


def fetch_comment_threads(session: Session, post_uri: str, *, transport: Transport) -> list[FetchedThread]:
    resp = transport.request(
        "GET", f"{session.pds}/xrpc/app.bsky.feed.getPostThread",
        headers=_headers(session), params={"uri": post_uri, "depth": "2"},
    )
    if not is_ok(resp):
        _raise_for(resp, "reply read")
    thread = json_of(resp).get("thread") or {}
    out: list[FetchedThread] = []
    for node in thread.get("replies") or []:
        top = _message(node, session.did)
        if top is None or top.from_me:
            continue
        nested = [m for m in (_message(n, session.did) for n in (node.get("replies") or [])) if m is not None]
        author = (node.get("post") or {}).get("author") or {}
        out.append(FetchedThread(
            kind=KIND_COMMENT,
            external_thread_id=top.external_id,
            author_name=top.author_name,
            author_id=top.author_id,
            text=top.text,
            permalink=bsky.post_url(str(author.get("handle") or top.author_id), top.external_id),
            like_count=max(0, int((node.get("post") or {}).get("likeCount") or 0)),
            messages=(top, *nested),
        ))
    return out


def _refs(session: Session, uris: list[str], transport: Transport) -> dict[str, str]:
    """``{uri: cid}`` for the given post uris."""
    resp = transport.request("GET", f"{session.pds}/xrpc/app.bsky.feed.getPosts",
                             headers=_headers(session), params={"uris": uris})
    if not is_ok(resp):
        _raise_for(resp, "post lookup")
    return {str(p.get("uri")): str(p.get("cid") or "") for p in (json_of(resp).get("posts") or [])
            if isinstance(p, dict) and p.get("uri")}


def _create(session: Session, collection: str, record: dict, transport: Transport, action: str) -> str:
    resp = transport.request(
        "POST", f"{session.pds}/xrpc/com.atproto.repo.createRecord",
        headers=_headers(session, json_body=True),
        json={"repo": session.did, "collection": collection, "record": record},
    )
    if not is_ok(resp):
        _raise_for(resp, action)
    uri = str(json_of(resp).get("uri") or "")
    if not uri:
        raise InboxPlatformError(PLATFORM, f"Bluesky accepted the {action} but returned no id.")
    return uri


def reply_to_comment(session: Session, root_uri: str, parent_uri: str, text: str, *, transport: Transport) -> str:
    refs = _refs(session, list(dict.fromkeys([root_uri, parent_uri])), transport)
    if not refs.get(root_uri) or not refs.get(parent_uri):
        raise InboxPlatformError(PLATFORM, "Bluesky no longer returns this post.", not_available=True)
    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": bsky.now_iso(),
        "reply": {
            "root": {"uri": root_uri, "cid": refs[root_uri]},
            "parent": {"uri": parent_uri, "cid": refs[parent_uri]},
        },
    }
    facets = bsky.tag_facets(text)
    if facets:
        record["facets"] = facets
    return _create(session, "app.bsky.feed.post", record, transport, "reply")


def like_comment(session: Session, uri: str, *, transport: Transport) -> str:
    refs = _refs(session, [uri], transport)
    if not refs.get(uri):
        raise InboxPlatformError(PLATFORM, "Bluesky no longer returns this reply.", not_available=True)
    record = {"$type": "app.bsky.feed.like", "subject": {"uri": uri, "cid": refs[uri]}, "createdAt": bsky.now_iso()}
    return _create(session, "app.bsky.feed.like", record, transport, "like")
