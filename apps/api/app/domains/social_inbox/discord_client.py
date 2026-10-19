"""Discord inbox: replies to our webhook posts, read with the optional bot token.

Webhooks can only post, so reading needs a bot the creator adds to their
server (free; the Message Content intent is a toggle in the Developer Portal
for bots in fewer than 100 servers).

* Read  - ``GET /channels/{id}/messages?after=<last seen>`` (newest first).
  A message that replies to one of our webhook posts starts a thread; a reply
  to a message already in a thread joins it. Plain chatter that replies to
  nothing we posted is ignored: this is an inbox, not a channel mirror.
* Reply - ``POST /channels/{id}/messages`` as the bot with a
  ``message_reference`` to the person's message; mentions are disabled except
  for pinging the person being answered.
"""

from __future__ import annotations

from app.domains.publishing.extended.connectors import discord as dc

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

PLATFORM = "discord"
PAGE = 100


def _raise_for(resp, action: str) -> None:
    code = status_of(resp)
    if code == 401:
        raise InboxPlatformError(PLATFORM, "Discord rejected the bot token. Reconnect the channel.", permission=True)
    if code in (403, 404):
        raise InboxPlatformError(PLATFORM, "The bot cannot read this channel. Give it 'View Channel' and 'Read "
                                           "Message History'.", permission=True)
    if code == 429 or code >= 500:
        raise InboxPlatformError(PLATFORM, f"Discord {action} is rate limited right now; will retry.",
                                 retryable=True)
    raise InboxPlatformError(PLATFORM, f"Discord {action} failed (HTTP {code}).")


def _get(transport: Transport, url: str, **kwargs):
    try:
        return transport.request("GET", url, **kwargs)
    except Exception:  # noqa: BLE001
        raise InboxPlatformError(PLATFORM, "Discord could not be reached; will retry.", retryable=True) from None


def fetch_messages(bot_token: str, channel_id: str, after: str, *, transport: Transport) -> list[dict]:
    params = {"limit": str(PAGE)}
    if after:
        params["after"] = after
    resp = _get(transport, f"{dc.API_BASE}/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {bot_token}"}, params=params)
    if not is_ok(resp):
        _raise_for(resp, "read")
    body = json_of(resp)
    data = body.get("data") if "data" in body else []
    return [m for m in (data or []) if isinstance(m, dict)]


def _snowflake(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def newest_id(messages: list[dict], current: str) -> str:
    best = _snowflake(current)
    for m in messages:
        best = max(best, _snowflake(str(m.get("id") or "")))
    return str(best) if best else current


def threads_from_messages(messages: list[dict], *, webhook_id: str, bot_user_id: str, guild_id: str,
                          channel_id: str, known: dict[str, str]) -> list[FetchedThread]:
    """``known`` maps message ids already in stored threads to their thread id."""
    ordered = sorted(messages, key=lambda m: _snowflake(str(m.get("id") or "")))
    index = dict(known)
    grouped: dict[str, dict] = {}
    for m in ordered:
        mid = str(m.get("id") or "")
        if not mid or str(m.get("webhook_id") or "") == webhook_id:
            continue
        author = m.get("author") if isinstance(m.get("author"), dict) else {}
        from_me = bool(bot_user_id) and str(author.get("id") or "") == bot_user_id
        ref = m.get("referenced_message") if isinstance(m.get("referenced_message"), dict) else None
        ref_id = str((m.get("message_reference") or {}).get("message_id") or (ref or {}).get("id") or "")
        if not ref_id:
            continue
        if ref_id in index:
            key = index[ref_id]
        elif ref is not None and str(ref.get("webhook_id") or "") == webhook_id and not from_me:
            key = mid  # a new comment on one of our posts
        else:
            continue
        index[mid] = key
        message = FetchedMessage(
            external_id=mid,
            author_name=str(author.get("global_name") or author.get("username") or "Discord user"),
            author_id=str(author.get("id") or ""),
            text=(str(m.get("content") or "").strip() or ("[attachment]" if m.get("attachments") else ""))[:4000],
            at=parse_time(m.get("edited_timestamp") or m.get("timestamp")),
            from_me=from_me,
        )
        bucket = grouped.setdefault(key, {"messages": {}, "first": message})
        bucket["messages"][mid] = message
    out: list[FetchedThread] = []
    for key, bucket in grouped.items():
        msgs = tuple(sorted(bucket["messages"].values(), key=lambda x: _snowflake(x.external_id)))
        inbound = [x for x in msgs if not x.from_me]
        first = inbound[0] if inbound else bucket["first"]
        out.append(FetchedThread(
            kind=KIND_COMMENT, external_thread_id=key, author_name=first.author_name, author_id=first.author_id,
            text=(inbound[-1] if inbound else msgs[-1]).text,
            permalink=dc.message_url(guild_id, channel_id, key), messages=msgs,
        ))
    return out


def reply(bot_token: str, channel_id: str, reply_to: str, text: str, *, transport: Transport) -> str:
    body = {
        "content": text[: dc.CONTENT_MAX],
        "allowed_mentions": {"parse": [], "replied_user": True},
    }
    if reply_to:
        body["message_reference"] = {"message_id": reply_to, "fail_if_not_exists": False}
    try:
        resp = transport.request("POST", f"{dc.API_BASE}/channels/{channel_id}/messages",
                                 headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
                                 json=body)
    except Exception:  # noqa: BLE001
        raise InboxPlatformError(PLATFORM, "Discord could not be reached; try again.", retryable=True) from None
    if not is_ok(resp):
        _raise_for(resp, "reply")
    message_id = str(json_of(resp).get("id") or "")
    if not message_id:
        raise InboxPlatformError(PLATFORM, "Discord accepted the reply but returned no id.")
    return message_id
