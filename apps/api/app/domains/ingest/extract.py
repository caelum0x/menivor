"""Pure, dependency-free HTML/text content extraction (no network, no LLM).

Pulls a page's title, description, and key points from raw HTML using regex only
(no bs4/lxml dependency), so it is fast, deterministic, and unit-testable. Plain
text is tolerated too. Output feeds the reel-draft template.
"""

from __future__ import annotations

import html as _html
import re

_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE,
)
_H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE,
)
_OG_DESC_RE = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE,
)
_LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_H2_RE = re.compile(r"<h[23]\b[^>]*>(.*?)</h[23]>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
# Blocks whose text is never page content: code, styles, and site chrome (menus, footers).
_NON_CONTENT_RE = re.compile(
    r"<(script|style|noscript|svg|template|nav|header|footer)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_WS_RE = re.compile(r"\s+")

_MAX_FEATURES = 6
_MAX_FEATURE_LEN = 140


def _clean(text: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    without_tags = _TAG_RE.sub(" ", text or "")
    unescaped = _html.unescape(without_tags)
    return _WS_RE.sub(" ", unescaped).strip()


def _first(patterns: list[re.Pattern], source: str) -> str:
    for pat in patterns:
        m = pat.search(source)
        if m:
            value = _clean(m.group(1))
            if value:
                return value
    return ""


def extract_content(source: str, url: str = "") -> dict:
    """Extract ``{title, description, features[], url}`` from HTML or text.

    Falls back gracefully: a plain-text body with no HTML yields its first line as
    the title and the rest as the description.
    """
    source = source or ""
    has_html = "<" in source and ">" in source

    if not has_html:
        lines = [ln.strip() for ln in source.splitlines() if ln.strip()]
        title = lines[0] if lines else ""
        description = " ".join(lines[1:])[:500]
        return {"title": title, "description": description, "features": [], "url": url}

    title = _first([_OG_TITLE_RE, _TITLE_RE, _H1_RE], source)
    description = _first([_DESC_RE, _OG_DESC_RE], source)

    body = _NON_CONTENT_RE.sub(" ", source)
    features: list[str] = []
    seen: set[str] = set()
    for pat in (_LI_RE, _H2_RE):
        for m in pat.finditer(body):
            item = _clean(m.group(1))
            if not item or len(item) < 3:
                continue
            item = item[:_MAX_FEATURE_LEN]
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            features.append(item)
            if len(features) >= _MAX_FEATURES:
                break
        if len(features) >= _MAX_FEATURES:
            break

    return {
        "title": title,
        "description": description,
        "features": features,
        "url": url,
    }
