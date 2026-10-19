"""Mastodon inbox: mentions (replies to our posts) and direct messages.

* Read  - ``GET /api/v1/notifications?types[]=mention&since_id=<last>``. A
  ``direct`` status is a DM (one thread per account); any other mention is a
  comment. A mention that replies to a status already in a thread (including
  our own reply) joins that thread; otherwise it starts one.
* Reply - ``POST /api/v1/statuses`` with ``in_reply_to_id`` and the person's
  handle prepended (Mastodon only notifies mentioned accounts). DMs are
  answered as ``direct``.
"""

from __future__ import annotations

from app.domains.publishing.extended.connectors import mastodon as md

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

PLATFORM = "mastodon"
PAGE = 40


def _raise_for(resp, action: str) -> None:
    code = status_of(resp)
    if code in (401, 403):
        raise InboxPlatformError(PLATFORM, "Mastodon refused the access token (it needs the 'read' and 'write' "
                                           "scopes). Reconnect the account.", permission=True)
    if code == 404:
        raise InboxPlatformError(PLATFORM, "Mastodon no longer has this post.", not_available=True)
    if code == 429 or code >= 500:
        raise InboxPlatformError(PLATFORM, f"Mastodon {action} is rate limited right now; will retry.",
                                 retryable=True)
    raise InboxPlatformError(PLATFORM, f"Mastodon {action} failed (HTTP {code}).")


def _call(transport: Transport, method: str, url: str, **kwargs):
    try:
        return transport.request(method, url, **kwargs)
    except Exception:  # noqa: BLE001
        raise InboxPlatformError(PLATFORM, "The Mastodon instance could not be reached; will retry.",
                                 retryable=True) from None


def fetch_mentions(instance_url: str, token: str, since_id: str, *, transport: Transport) -> list[dict]:
    params = {"types[]": "mention", "limit": str(PAGE)}
    if since_id:
        params["since_id"] = since_id
    resp = _call(transport, "GET", f"{instance_url}/api/v1/notifications",
                 headers={"Authorization": f"Bearer {token}"}, params=params)
    if not is_ok(resp):
        _raise_for(resp, "read")
    body = json_of(resp)
    data = body.get("data") if "data" in body else []
    return [n for n in (data or []) if isinstance(n, dict)]


def _num(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def newest_id(notifications: list[dict], current: str) -> str:
    best = _num(current)
    for n in notifications:
        best = max(best, _num(str(n.get("id") or "")))
    return str(best) if best else current


def threads_from_notifications(notifications: list[dict], *, known: dict[str, str]) -> list[FetchedThread]:
    index = dict(known)
    grouped: dict[str, dict] = {}
    for n in sorted(notifications, key=lambda x: _num(str(x.get("id") or ""))):
        status = n.get("status") if isinstance(n.get("status"), dict) else None
        if status is None or not status.get("id"):
            continue
        account = status.get("account") if isinstance(status.get("account"), dict) else {}
        acct = str(account.get("acct") or "")
        sid = str(status["id"])
        parent = str(status.get("in_reply_to_id") or "")
        if str(status.get("visibility") or "") == "direct":
            kind, key = KIND_DM, f"dm:{acct}"
        elif parent and parent in index:
            kind, key = KIND_COMMENT, index[parent]
        else:
            kind, key = KIND_COMMENT, sid
        index[sid] = key
        message = FetchedMessage(
            external_id=sid,
            author_name=str(account.get("display_name") or acct or "Mastodon user"),
            author_id=acct,
            text=md.strip_html(str(status.get("content") or ""))[:4000] or "[media]",
            at=parse_time(status.get("created_at")),
            from_me=False,
        )
        bucket = grouped.setdefault(key, {"kind": kind, "messages": {}, "first": message,
                                          "url": str(status.get("url") or "")})
        bucket["messages"][sid] = message
    out: list[FetchedThread] = []
    for key, bucket in grouped.items():
        msgs = tuple(sorted(bucket["messages"].values(), key=lambda x: _num(x.external_id)))
        out.append(FetchedThread(
            kind=bucket["kind"], external_thread_id=key[:160], author_name=bucket["first"].author_name,
            author_id=bucket["first"].author_id, text=msgs[-1].text, permalink=bucket["url"], messages=msgs,
        ))
    return out


def reply(instance_url: str, token: str, *, acct: str, in_reply_to: str, text: str, direct: bool,
          transport: Transport) -> str:
    mention = f"@{acct}" if acct else ""
    body_text = text if not mention or text.lstrip().startswith(mention) else f"{mention} {text}"
    body: dict = {"status": body_text, "visibility": "direct" if direct else "public"}
    if in_reply_to:
        body["in_reply_to_id"] = in_reply_to
    resp = _call(transport, "POST", f"{instance_url}/api/v1/statuses",
                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=body)
    if not is_ok(resp):
        _raise_for(resp, "reply")
    status_id = str(json_of(resp).get("id") or "")
    if not status_id:
        raise InboxPlatformError(PLATFORM, "Mastodon accepted the reply but returned no id.")
    return status_id
