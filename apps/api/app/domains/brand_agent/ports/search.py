"""Market search port: ``search(query, limit) -> [{"title", "url", "snippet"}]``.

Off by default (no outbound search without an explicit choice). ``BRAND_AGENT_SEARCH``:

* ``searxng:https://your-searx`` - a self-hosted SearXNG (OSS, free) JSON API;
* ``searxng`` - the same, at ``SEARXNG_URL``;
* ``duckduckgo`` - DuckDuckGo's no-JS HTML results page (free, no key; light use only;
  it bot-checks some server IPs, so prefer SearXNG);
* unset - SearXNG when ``SEARXNG_URL`` is set (configuring it is the explicit
  choice), else :class:`NoSearch`; ``none`` always switches search off.

SearXNG runs next to the API (``deploy/searxng``), usually on a private address,
so its operator-configured base URL is fetched directly with a timeout, no
redirects and a size cap; DuckDuckGo goes through the Ad Studio SSRF guard.
Results are plain data; the agent treats them as unverified leads and labels
them with their source URL.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, urlencode, urlparse

from loguru import logger

ENV = "BRAND_AGENT_SEARCH"
SEARXNG_URL_ENV = "SEARXNG_URL"
MAX_RESULTS = 8
SEARXNG_MAX_BYTES = 1_000_000
SEARXNG_TIMEOUT_S = (3.0, 10.0)
_TAG_RE = re.compile(r"<[^>]+>")
_DDG_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]*class="result__a"|$)',
    re.I | re.S,
)
_DDG_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</(?:a|div|td)>', re.I | re.S)


class SearchPort(Protocol):
    def search(self, query: str, limit: int = 6) -> list[dict[str, str]]: ...


def _clean(value: str, limit: int = 300) -> str:
    text = html_lib.unescape(_TAG_RE.sub("", value or ""))
    return " ".join(text.split())[:limit]


def _result(title: str, url: str, snippet: str) -> dict[str, str] | None:
    title, url, snippet = _clean(title, 200), (url or "").strip(), _clean(snippet)
    if not title or not url.startswith(("http://", "https://")):
        return None
    return {"title": title, "url": url, "snippet": snippet}


class NoSearch:
    enabled = False

    def search(self, query: str, limit: int = 6) -> list[dict[str, str]]:
        return []


class _Body:
    def __init__(self, body: str) -> None:
        self._body = body

    def text(self) -> str:
        return self._body


def operator_get(url: str, *, accept: str = "application/json") -> _Body:
    """GET the operator-configured SearXNG (private address allowed; no redirects; capped body)."""
    import requests

    with requests.get(url, headers={"Accept": accept, "User-Agent": "menivor-brand-agent"},
                      timeout=SEARXNG_TIMEOUT_S, allow_redirects=False, stream=True) as resp:
        if resp.status_code != 200:  # redirects included: never follow one off the configured host
            raise ValueError(f"searxng answered HTTP {resp.status_code}")
        chunks, size = [], 0
        for chunk in resp.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > SEARXNG_MAX_BYTES:
                raise ValueError("searxng response too large")
            chunks.append(chunk)
    return _Body(b"".join(chunks).decode("utf-8", errors="replace"))


def _valid_base(base_url: str) -> str:
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{SEARXNG_URL_ENV} must be an http(s) URL")
    return base_url.strip().rstrip("/")


class SearxngSearch:
    enabled = True

    def __init__(self, base_url: str, *, getter: Callable[..., Any] | None = None) -> None:
        self.base_url = _valid_base(base_url)
        self._getter = getter

    def search(self, query: str, limit: int = 6) -> list[dict[str, str]]:
        get = self._getter or operator_get
        url = f"{self.base_url}/search?{urlencode({'q': query, 'format': 'json', 'safesearch': 1})}"
        try:
            payload = json.loads(get(url, accept="application/json").text())
        except Exception as exc:  # noqa: BLE001 - search is optional
            logger.warning(f"brand agent searxng search failed: {type(exc).__name__}")
            return []
        out = []
        for row in payload.get("results", []) if isinstance(payload, dict) else []:
            item = _result(str(row.get("title", "")), str(row.get("url", "")), str(row.get("content", "")))
            if item:
                out.append(item)
            if len(out) >= min(limit, MAX_RESULTS):
                break
        return out


def _ddg_target(href: str) -> str:
    raw = html_lib.unescape(href)
    if raw.startswith("//"):
        raw = "https:" + raw
    parsed = urlparse(raw)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        return parse_qs(parsed.query).get("uddg", [""])[0]
    return raw


def parse_duckduckgo_html(page: str, limit: int = 6) -> list[dict[str, str]]:
    """Results from DuckDuckGo's HTML endpoint (pure; ads and junk are skipped)."""
    out: list[dict[str, str]] = []
    for href, title, rest in _DDG_RESULT_RE.findall(page or ""):
        snippet = _DDG_SNIPPET_RE.search(rest)
        item = _result(title, _ddg_target(href), snippet.group(1) if snippet else "")
        if item and "duckduckgo.com/y.js" not in item["url"]:
            out.append(item)
        if len(out) >= min(limit, MAX_RESULTS):
            break
    return out


class DuckDuckGoSearch:
    enabled = True
    ENDPOINT = "https://html.duckduckgo.com/html/"

    def __init__(self, *, getter: Callable[..., Any] | None = None) -> None:
        self._getter = getter
        self.last_status = ""

    def search(self, query: str, limit: int = 6) -> list[dict[str, str]]:
        from app.domains.adstudio.fetch import safe_get

        get = self._getter or safe_get
        try:
            page = get(f"{self.ENDPOINT}?{urlencode({'q': query})}", accept_language="en-US,en;q=0.9").text()
        except Exception as exc:  # noqa: BLE001 - search is optional
            logger.warning(f"brand agent duckduckgo search failed: {type(exc).__name__}")
            return []
        results = parse_duckduckgo_html(page, limit)
        self.last_status = "ok" if results else ("blocked" if "anomaly" in page.lower() else "empty")
        if self.last_status == "blocked":
            logger.warning("brand agent duckduckgo search was blocked by a bot check")
        return results


def _searxng(base_url: str) -> SearchPort:
    try:
        return SearxngSearch(base_url)
    except ValueError as exc:
        logger.warning(f"brand agent search off: {exc}")
        return NoSearch()


def get_port() -> SearchPort:
    raw = (os.environ.get(ENV) or "").strip()
    kind, _, arg = raw.partition(":")
    kind = kind.lower()
    searxng_url = (os.environ.get(SEARXNG_URL_ENV) or "").strip()
    if kind == "searxng" and (arg.strip() or searxng_url):
        return _searxng(arg.strip() or searxng_url)
    if kind == "duckduckgo":
        return DuckDuckGoSearch()
    if not kind and searxng_url:
        return _searxng(searxng_url)
    return NoSearch()


__all__ = ["DuckDuckGoSearch", "NoSearch", "SearchPort", "SearxngSearch", "get_port", "operator_get",
           "parse_duckduckgo_html"]
