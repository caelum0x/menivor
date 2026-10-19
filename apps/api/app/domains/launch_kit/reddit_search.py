"""Reddit's public search JSON endpoints (read-only, no login, no API key).

``https://www.reddit.com/search.json`` and ``https://www.reddit.com/r/<sub>/search.json``
are the same endpoints old.reddit.com's search box calls; they are public and
unauthenticated (Reddit requires a descriptive ``User-Agent`` or it 429s, same
rule as any anonymous API client). This module only ever reads: it has no
function that posts, comments or votes, by design -- see
:mod:`app.domains.launch_kit.service`'s module docstring for why.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

USER_AGENT = "menivor-launch-kit/1.0 (+https://menivor.com)"
BASE = "https://www.reddit.com"
HTTP_TIMEOUT_S = 15.0
MAX_SUBREDDITS = 10
MAX_LIMIT = 25


class RedditSearchError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class RedditThread:
    url: str
    title: str
    snippet: str
    subreddit: str
    upvotes: int
    age_days: int
    permalink: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def _snippet(selftext: str, limit: int = 400) -> str:
    text = " ".join(str(selftext or "").split())
    return text[:limit]


def _age_days(created_utc: Any, *, now: float) -> int:
    try:
        created = float(created_utc or 0)
    except (TypeError, ValueError):
        return 0
    if created <= 0:
        return 0
    return max(0, int((now - created) // 86400))


def _to_thread(child: dict[str, Any], *, now: float) -> RedditThread | None:
    data = child.get("data") or {}
    permalink = str(data.get("permalink") or "").strip()
    if not permalink:
        return None
    return RedditThread(
        url=f"{BASE}{permalink}",
        title=str(data.get("title") or "")[:500],
        snippet=_snippet(data.get("selftext")),
        subreddit=str(data.get("subreddit") or "").strip(),
        upvotes=int(data.get("ups") or 0),
        age_days=_age_days(data.get("created_utc"), now=now),
        permalink=permalink,
        raw={"id": data.get("id"), "num_comments": data.get("num_comments"), "author": data.get("author")},
    )


def _fetch_one(transport: Any, *, subreddit: str, query: str, limit: int, now: float) -> list[RedditThread]:
    if subreddit:
        url = f"{BASE}/r/{subreddit}/search.json"
        params = {"q": query, "restrict_sr": "1", "sort": "relevance", "limit": str(limit)}
    else:
        url = f"{BASE}/search.json"
        params = {"q": query, "sort": "relevance", "limit": str(limit)}
    try:
        resp = transport.request("GET", url, params=params, headers={"User-Agent": USER_AGENT})
    except Exception as exc:  # noqa: BLE001 - network boundary
        raise RedditSearchError(f"Reddit search is unreachable ({type(exc).__name__}).") from exc
    status = getattr(resp, "status_code", 200)
    if status == 429:
        raise RedditSearchError("Reddit rate-limited this search; try again shortly.", 429)
    if status >= 400:
        raise RedditSearchError(f"Reddit search error {status}.", 502)
    try:
        body = resp.json() or {}
    except ValueError:
        body = {}
    children = ((body.get("data") or {}).get("children")) or []
    out = [t for t in (_to_thread(c, now=now) for c in children) if t is not None]
    return out


def search(transport: Any, *, query: str, subreddits: list[str] | None = None, limit: int = 10,
           now: float | None = None) -> list[RedditThread]:
    """Search Reddit for ``query``, globally or restricted to ``subreddits``. One call per
    subreddit (Reddit's search API has no "search these N subs at once" parameter); results are
    merged and re-sorted by upvotes, highest first, deduped by permalink."""
    q = str(query or "").strip()
    if not q:
        raise RedditSearchError("query is required", 422)
    moment = now if now is not None else time.time()
    per_sub_limit = max(1, min(int(limit or 10), MAX_LIMIT))
    subs = [s.strip().lstrip("r/").strip() for s in (subreddits or []) if str(s or "").strip()][:MAX_SUBREDDITS]
    seen: dict[str, RedditThread] = {}
    for sub in subs or [""]:
        for thread in _fetch_one(transport, subreddit=sub, query=q, limit=per_sub_limit, now=moment):
            seen.setdefault(thread.permalink, thread)
    out = sorted(seen.values(), key=lambda t: t.upvotes, reverse=True)
    return out[:max(per_sub_limit, MAX_LIMIT)]


__all__ = ["MAX_LIMIT", "MAX_SUBREDDITS", "RedditSearchError", "RedditThread", "search"]
