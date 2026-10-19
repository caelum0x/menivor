"""Pure Reddit JSON → :class:`RedditThread` (no network, no LLM).

Reads Reddit's 2-element listing (``listing[0]`` = the post, ``listing[1]`` = the
comment forest), cleans the self-text HTML through the shared ingest cleaner, and
drops the ``[removed]``/``[deleted]``/``more`` stubs Reddit sprinkles in. Raises
:class:`RedditParseError` on malformed input or an empty story body so the caller
surfaces a clean 422 before any credit is spent.
"""

from __future__ import annotations

import html as _htmllib
import json
from dataclasses import dataclass

from app.domains.ingest.extract import _clean

_STUB_BODIES = {"[removed]", "[deleted]", "[removed by reddit]"}
_MAX_COMMENTS = 5
_MAX_COMMENT_LEN = 280


class RedditParseError(Exception):
    """Malformed Reddit JSON or an empty/unusable story body (surfaced as 422)."""


@dataclass(frozen=True)
class RedditThread:
    """An immutable, cleaned Reddit thread ready for narration."""

    title: str
    subreddit: str
    author: str
    body: str
    top_comments: tuple[str, ...] = ()


def _coerce(raw: str | list | dict) -> list:
    """Return the 2-element listing array from any accepted input shape."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise RedditParseError(f"thread JSON is not parseable: {exc}") from exc
    if isinstance(raw, dict):
        # A single listing dict (or an API error envelope) — wrap it so indexing
        # below can still find the post children, else fail cleanly.
        if raw.get("error") is not None:
            raise RedditParseError(f"reddit returned an error: {raw.get('error')}")
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise RedditParseError("thread JSON must be a non-empty listing array")
    return raw


def _post_data(listing: list) -> dict:
    try:
        children = listing[0]["data"]["children"]
        data = children[0]["data"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RedditParseError("thread JSON is missing the post listing") from exc
    if not isinstance(data, dict):
        raise RedditParseError("thread post data is malformed")
    return data


def _body(data: dict) -> str:
    """Cleaned story body — prefer the rich HTML, fall back to plain self-text."""
    html_body = str(data.get("selftext_html") or "").strip()
    if html_body:
        # Reddit entity-escapes selftext_html (``&lt;div&gt;...``); unescape FIRST so
        # the shared ingest cleaner (which strips tags before unescaping) actually
        # removes the real markup instead of resurrecting it.
        cleaned = _clean(_htmllib.unescape(html_body))
        if cleaned:
            return cleaned
    return str(data.get("selftext") or "").strip()


def _comments(listing: list) -> tuple[str, ...]:
    """Top real comments, dropping ``more`` stubs and removed/deleted bodies."""
    if len(listing) < 2:
        return ()
    try:
        children = listing[1]["data"]["children"]
    except (KeyError, IndexError, TypeError):
        return ()
    out: list[str] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        if child.get("kind") != "t1":  # 'more' / non-comment stubs
            continue
        body = str((child.get("data") or {}).get("body") or "").strip()
        if not body or body.lower() in _STUB_BODIES:
            continue
        out.append(body[:_MAX_COMMENT_LEN])
        if len(out) >= _MAX_COMMENTS:
            break
    return tuple(out)


def parse_thread(raw: str | list | dict) -> RedditThread:
    """Parse Reddit's thread JSON into a cleaned, frozen :class:`RedditThread`."""
    listing = _coerce(raw)
    data = _post_data(listing)

    body = _body(data)
    if not body or body.lower() in _STUB_BODIES:
        raise RedditParseError("the thread has no usable story body")

    return RedditThread(
        title=str(data.get("title") or "").strip(),
        subreddit=str(data.get("subreddit") or "").strip(),
        author=str(data.get("author") or "").strip(),
        body=body,
        top_comments=_comments(listing),
    )
