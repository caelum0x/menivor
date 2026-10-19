"""Search visibility: rank the app in the top 50 App Store results for a list
of generic terms (public, keyless iTunes Search API), and surface the
competitors that show up most often across those terms.

Results are cached in-process for 24h per ``(term, country)`` so repeated
audits (and the landing-page preview + the standalone tool page hitting the
same app) do not re-query the Search API on every request. The cache is a
simple bounded dict, not Redis: losing it on a process restart just means the
next lookup is a live call, which is an acceptable cost for a free tool.

Google Play has no public keyword-rank API, so this module only ever runs
for App Store listings; callers check ``source == "app_store"`` first.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.domains.capture.store import StoreError, fetch_app_store_search

CACHE_TTL_S = 24 * 60 * 60
MAX_CACHE_KEYS = 2000
SearchFn = Callable[..., list[dict[str, str]]]

_cache_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, list[dict[str, str]]]] = {}


def reset_cache() -> None:
    """Forget every cached search result (tests only)."""
    with _cache_lock:
        _cache.clear()


def _prune(now: float) -> None:
    if len(_cache) < MAX_CACHE_KEYS:
        return
    expired = [key for key, (stamp, _rows) in _cache.items() if now - stamp >= CACHE_TTL_S]
    for key in expired:
        _cache.pop(key, None)


def cached_search(term: str, country: str, *, search: SearchFn = fetch_app_store_search,
                   now: float | None = None) -> tuple[list[dict[str, str]], bool]:
    """Search results for ``term``, from the 24h cache when fresh. Returns ``(rows, cached)``."""
    key = (term.strip().lower(), (country or "us").lower())
    clock = now if now is not None else time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and clock - hit[0] < CACHE_TTL_S:
            return hit[1], True
    rows = search(term, country=country)
    with _cache_lock:
        _prune(clock)
        _cache[key] = (clock, rows)
    return rows, False


@dataclass(frozen=True)
class TermRank:
    term: str
    position: int | None
    checked_count: int


def rank_in_results(rows: list[dict[str, str]], app_id: str) -> int | None:
    for index, row in enumerate(rows, start=1):
        if str(row.get("app_id")) == str(app_id):
            return index
    return None


def top_competitors(by_term: list[tuple[str, list[dict[str, str]]]], app_id: str, limit: int = 3) -> list[dict[str, object]]:
    """The apps (other than ``app_id``) that appear most often across every term's results."""
    tally: dict[str, dict[str, object]] = {}
    for _term, rows in by_term:
        for row in rows:
            other_id = str(row.get("app_id") or "")
            if not other_id or other_id == str(app_id):
                continue
            entry = tally.setdefault(other_id, {"app_id": other_id, "title": row.get("title") or other_id, "count": 0})
            entry["count"] = int(entry["count"]) + 1
    ranked = sorted(tally.values(), key=lambda e: (-int(e["count"]), str(e["title"])))
    return ranked[:limit]


def check_visibility(terms: list[str], app_id: str, *, country: str = "us",
                      search: SearchFn = fetch_app_store_search, now: float | None = None) -> dict:
    """Run every term through the cached Search API and summarize rank + competitors."""
    results: list[TermRank] = []
    by_term: list[tuple[str, list[dict[str, str]]]] = []
    any_cached = False
    errors: list[str] = []
    for term in terms:
        try:
            rows, cached = cached_search(term, country, search=search, now=now)
        except StoreError as exc:
            errors.append(f'{term}: {exc.message}')
            continue
        any_cached = any_cached or cached
        by_term.append((term, rows))
        results.append(TermRank(term=term, position=rank_in_results(rows, app_id), checked_count=len(rows)))
    return {
        "available": True,
        "terms": terms,
        "results": [{"term": r.term, "position": r.position, "checked_count": r.checked_count} for r in results],
        "top_competitors": top_competitors(by_term, app_id),
        "cached": any_cached,
        "errors": errors,
    }


def unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason, "terms": [], "results": [], "top_competitors": [], "cached": False, "errors": []}


__all__ = [
    "CACHE_TTL_S",
    "TermRank",
    "cached_search",
    "check_visibility",
    "rank_in_results",
    "reset_cache",
    "top_competitors",
    "unavailable",
]
