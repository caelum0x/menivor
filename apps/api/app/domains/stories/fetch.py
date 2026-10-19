"""Injectable Reddit HTTP transport (network only in ``default_fetch``).

The fetcher is a ``Callable[[str], str]`` seam so the whole story flow is testable
without touching the network — tests inject a fake that returns canned Reddit JSON.
``normalize_thread_url`` enforces the boundary (reddit host + http(s), ``.json``
suffix); ``default_fetch`` is a guarded ``httpx`` GET copied from the ingest
transport but with a stories-specific User-Agent and a byte cap.
"""

from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse

Fetcher = Callable[[str], str]

_MAX_FETCH_BYTES = 2_000_000
_USER_AGENT = "ReelForgeBot/1.0 (+stories)"


class RedditFetchError(Exception):
    """Fetch/normalization failure carrying an HTTP-ish status (mirrors IngestError)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _host(url: str) -> str:
    return (urlparse(url).netloc or "").lower().split(":")[0]


def normalize_thread_url(url: str) -> str:
    """Validate a Reddit thread URL and return its ``.json`` API form.

    Rejects non-http(s) schemes and non-reddit hosts with a 400
    :class:`RedditFetchError`; strips any query/fragment and appends ``.json`` so
    the fetch hits Reddit's public JSON listing endpoint.
    """
    raw = (url or "").strip()
    lowered = raw.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise RedditFetchError(400, "a valid http(s) reddit URL is required")

    parsed = urlparse(raw)
    host = _host(raw)
    if not (host == "reddit.com" or host.endswith(".reddit.com")):
        raise RedditFetchError(400, "only reddit.com thread URLs are supported")

    path = (parsed.path or "").rstrip("/")
    if not path:
        raise RedditFetchError(400, "the reddit URL is missing a thread path")

    base = f"{parsed.scheme}://{parsed.netloc}{path}"
    if base.endswith(".json"):
        return base
    return f"{base}.json"


def default_fetch(url: str) -> str:
    """Guarded ``httpx`` GET returning the raw JSON text (raises on failure)."""
    try:
        import httpx
    except Exception as exc:  # pragma: no cover - only without httpx
        raise RedditFetchError(503, "reddit fetching is unavailable") from exc
    try:
        resp = httpx.get(
            url,
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
    except Exception as exc:
        raise RedditFetchError(502, f"could not fetch the reddit thread: {exc}") from exc
    if resp.status_code >= 400:
        raise RedditFetchError(502, f"the reddit thread returned {resp.status_code}")
    return resp.text[:_MAX_FETCH_BYTES]
