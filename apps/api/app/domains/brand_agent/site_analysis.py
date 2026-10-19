"""Brand Agent site analysis: a website -> the facts the setup steps propose.

Builds on :func:`app.domains.brand.extract.brand_from_html` (name, tagline,
description, logo icons, colours, fonts, language) and adds what the agent
needs on top: sample lines, headings, feature bullets, a pricing hook, a
category guess, brand colours from linked stylesheets (HSL CSS variables such
as ``--brand: 239 44% 43%``), ``next/font`` family names, and logo detection
from ``<img>`` / inline ``<svg>``.

:func:`analyze_html` is pure (no network). :func:`analyze_site` fetches the page
and up to :data:`MAX_STYLESHEETS` same-origin stylesheets through the Ad Studio
SSRF guard. Only what the site publishes is returned; nothing is invented.
"""

from __future__ import annotations

import colorsys
import re
from collections import Counter
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from app.domains.adstudio.extract import absolutize, clean_text
from app.domains.brand.extract import (
    _GENERIC_FONTS,
    _is_neutral,
    _link_tags,
    brand_from_html,
    normalize_hex,
)

MAX_STYLESHEETS = 2
MAX_COLORS = 6
MAX_FONTS = 4
MAX_LINES = 8
MAX_FEATURES = 8
MAX_HEADINGS = 10
MAX_LINE = 220
CSS_MAX_BYTES = 1_500_000

_NON_CONTENT_RE = re.compile(r"<(script|style|noscript|template|head)\b[^>]*>.*?</\1>", re.I | re.S)
_SVG_BODY_RE = re.compile(r"(<svg\b[^>]*>).*?</svg>", re.I | re.S)
_CHROME_RE = re.compile(r"<(nav|header|footer|aside)\b[^>]*>.*?</\1>", re.I | re.S)
_HEADING_RE = re.compile(r"<h([1-3])[^>]*>(.*?)</h\1>", re.I | re.S)
_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.I | re.S)
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.I | re.S)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_SVG_TAG_RE = re.compile(r"<svg\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')')
_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.I | re.S)
_HSL_VAR_RE = re.compile(
    r"--([a-z0-9-]*?(?:brand|primary|accent)[a-z0-9-]*)\s*:\s*([0-9.]+(?:deg)?\s+[0-9.]+%\s+[0-9.]+%)", re.I
)
_HEX_VAR_RE = re.compile(r"--([a-z0-9-]*?(?:brand|primary|accent)[a-z0-9-]*)\s*:\s*(#[0-9a-f]{3,6})\b", re.I)
_HEX_RE = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}\"]+)", re.I)
_FONT_FACE_RE = re.compile(r"@font-face\s*{[^}]*}", re.I)
_NEXT_FONT_RE = re.compile(r"^__([A-Za-z0-9_]+?)_[0-9a-f]{6}$")
_PRICE_RE = re.compile(r"(?:[$€£₺]\s?\d[\d.,]*|\d[\d.,]*\s?(?:USD|EUR|TL)\b)", re.I)
_FREE_RE = re.compile(r"\bfree (?:trial|plan|tier|forever)\b|\bstart (?:for )?free\b", re.I)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

#: Ordered (category, keywords). The first category with >= 2 keyword hits wins.
CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Developer tools: backend platform",
     ("postgres", "database", "backend", "auth", "storage", "realtime", "api", "sdk", "cli", "mcp")),
    ("Marketing: AI video and ads",
     ("ugc", "video", "ads", "creative", "avatar", "reels", "tiktok")),
    ("E-commerce store", ("shop", "cart", "shipping", "checkout", "collection", "add to bag")),
    ("Mobile app", ("app store", "google play", "download the app", "ios", "android")),
    ("Education", ("course", "lesson", "exam", "students", "learn")),
    ("Finance", ("payments", "invoice", "banking", "card", "wallet")),
    ("Health and fitness", ("workout", "health", "fitness", "sleep", "nutrition")),
)
DEFAULT_CATEGORY = "Software"


class SiteAnalysisError(Exception):
    """A user-presentable analysis failure (fetch blocked, not a page...)."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def hsl_to_hex(triplet: str) -> str:
    """``"239 44% 43%"`` -> ``"#3d3f9e"``; '' when it is not an HSL triplet."""
    parts = str(triplet or "").replace("deg", "").replace(",", " ").split()
    if len(parts) != 3 or not parts[1].endswith("%") or not parts[2].endswith("%"):
        return ""
    try:
        h = float(parts[0]) % 360 / 360
        s = float(parts[1].rstrip("%")) / 100
        lightness = float(parts[2].rstrip("%")) / 100
    except ValueError:
        return ""
    r, g, b = colorsys.hls_to_rgb(h, lightness, s)
    return "#" + "".join(f"{round(c * 255):02x}" for c in (r, g, b))


def font_family_name(raw: str) -> str:
    """A display family name from a CSS value; '' for generic / variable families."""
    name = str(raw or "").strip().strip("'\"").strip()
    if not name or name.lower().startswith("var("):
        return ""
    match = _NEXT_FONT_RE.match(name)
    if match:
        name = match.group(1).replace("_", " ").strip()
        if name.lower().endswith(" fallback"):
            return ""
    if name.lower() in _GENERIC_FONTS:
        return ""
    return clean_text(name, 60)


def _attrs(tag: str) -> dict[str, str]:
    return {
        m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4)) or ""
        for m in _ATTR_RE.finditer(tag)
    }


def _text(fragment: str, limit: int = MAX_LINE) -> str:
    return clean_text(_TAG_RE.sub(" ", fragment or ""), limit)


def _content_html(source: str) -> str:
    body = _NON_CONTENT_RE.sub(" ", source or "")
    return _SVG_BODY_RE.sub(r"\1", body)


def stylesheet_links(source: str, base_url: str, limit: int = MAX_STYLESHEETS) -> list[str]:
    """Same-origin ``<link rel="stylesheet">`` URLs (third-party CSS is never fetched)."""
    host = (urlparse(base_url).hostname or "").lower()
    out: list[str] = []
    for attrs in _link_tags(source):
        if "stylesheet" not in (attrs.get("rel") or "").lower() or not attrs.get("href"):
            continue
        url = absolutize(attrs["href"], base_url)
        if url and (urlparse(url).hostname or "").lower() == host and url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def _logo(source: str, base_url: str, fallback_icon: str, icon_origin: str) -> dict[str, str]:
    for tag in _IMG_RE.findall(source):
        attrs = _attrs(tag)
        hint = " ".join(attrs.get(k, "") for k in ("alt", "class", "id", "src")).lower()
        if "logo" in hint and attrs.get("src"):
            url = absolutize(attrs["src"], base_url)
            if url:
                return {"url": url, "origin": "img"}
    for tag in _SVG_TAG_RE.findall(source):
        attrs = _attrs(tag)
        hint = " ".join(attrs.get(k, "") for k in ("aria-label", "class", "id")).lower()
        if "logo" in hint:
            return {"url": "", "origin": "inline-svg"}
    if fallback_icon:
        return {"url": fallback_icon, "origin": icon_origin}
    return {"url": "", "origin": ""}


def _icon_origin(source: str, url: str, base_url: str) -> str:
    for attrs in _link_tags(source):
        if attrs.get("href") and absolutize(attrs["href"], base_url) == url:
            return (attrs.get("rel") or "icon").lower().strip()
    return "json-ld"


def _colors(source: str, stylesheets: Iterable[str], declared: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []

    def add(hex_value: str, origin: str) -> None:
        value = normalize_hex(hex_value)
        if value and value not in seen and not _neutral(value) and len(out) < MAX_COLORS:
            seen.add(value)
            out.append({"hex": value, "origin": origin})

    css_all = " ".join(stylesheets)
    for match in _HSL_VAR_RE.finditer(css_all):
        name = match.group(1).lower()
        if any(s in name for s in ("foreground", "muted", "ink", "fg")):
            continue
        add(hsl_to_hex(match.group(2)), "css-variable")
    for match in _HEX_VAR_RE.finditer(css_all):
        add(match.group(2), "css-variable")
    for color in declared:
        add(color.get("hex", ""), color.get("origin", "stylesheet"))
    counts: Counter[str] = Counter(normalize_hex(m.group(0)) for m in _HEX_RE.finditer(css_all))
    for value, _ in counts.most_common(MAX_COLORS * 2):
        add(value, "stylesheet")
    return out


def _neutral(hex_value: str) -> bool:
    """Near-white, near-black and greys (low saturation) are not brand colours."""
    if _is_neutral(hex_value):
        return True
    r, g, b = (int(hex_value[i:i + 2], 16) / 255 for i in (1, 3, 5))
    _, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    return saturation < 0.18 or lightness > 0.94 or lightness < 0.08


def _fonts(stylesheets: Iterable[str], declared: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []

    def add(raw: str, origin: str) -> None:
        name = font_family_name(raw)
        if name and name.lower() not in seen and len(out) < MAX_FONTS:
            seen.add(name.lower())
            out.append({"family": name, "origin": origin})

    for font in declared:
        if font.get("origin") == "google-fonts":
            add(font["family"], "google-fonts")
    css_all = " ".join(stylesheets)
    faces = " ".join(_FONT_FACE_RE.findall(css_all))
    # Fonts in use first (body text, then display), then any other @font-face.
    for match in _FONT_FAMILY_RE.finditer(_FONT_FACE_RE.sub(" ", css_all)):
        add(match.group(1).split(",")[0], "stylesheet")
    for match in _FONT_FAMILY_RE.finditer(faces):
        add(match.group(1).split(",")[0], "font-face")
    for font in declared:
        add(font.get("family", ""), font.get("origin", "stylesheet"))
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text or "") if s.strip()]


def _price_clause(sentence: str) -> str:
    """The clause that carries the price, plus a short tail ("$25 a project, flat")."""
    parts = [p.strip() for p in re.split(r"[,:;]\s+", sentence.rstrip(".")) if p.strip()]
    for i, part in enumerate(parts):
        if _PRICE_RE.search(part) or _FREE_RE.search(part):
            tail = parts[i + 1] if i + 1 < len(parts) and len(parts[i + 1].split()) <= 2 else ""
            return f"{part}, {tail}" if tail else part
    return sentence


def _pricing_hook(candidates: Iterable[str]) -> str:
    for text in candidates:
        for sentence in _sentences(text) or [text]:
            if _PRICE_RE.search(sentence) or _FREE_RE.search(sentence):
                return clean_text(_price_clause(sentence), MAX_LINE)
    return ""


def _category(corpus: str) -> str:
    text = corpus.lower()
    best = (0, DEFAULT_CATEGORY)
    for name, words in CATEGORIES:
        hits = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", text))
        if hits >= 2 and hits > best[0]:
            best = (hits, name)
    return best[1]


def _dedupe(values: Iterable[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) >= limit:
            break
    return out


def analyze_html(source: str, url: str, *, stylesheets: Iterable[str] = ()) -> dict[str, Any]:
    """Pure analysis of a homepage (plus already-fetched stylesheet texts)."""
    sheets = [*_STYLE_BLOCK_RE.findall(source or ""), *[s for s in stylesheets if s]]
    brand = brand_from_html(source or "", url)
    content = _content_html(source or "")
    # Navigation, header and footer chrome are not copy: read text from the page body only.
    body = _CHROME_RE.sub(" ", content)
    headings = _dedupe((_text(m.group(2)) for m in _HEADING_RE.finditer(body)), MAX_HEADINGS)
    h1 = [_text(m.group(2)) for m in _HEADING_RE.finditer(body) if m.group(1) == "1"]
    paragraphs = [_text(p) for p in _P_RE.findall(body)]
    features = _dedupe((_text(li, 120) for li in _LI_RE.findall(body) if "<a " not in li.lower()[:40]),
                       MAX_FEATURES)
    sample_lines = _dedupe([*h1, *paragraphs], MAX_LINES)
    icon = brand.get("logo_url", "")
    logo = _logo(content, url, icon, _icon_origin(source or "", icon, url) if icon else "")
    one_liner = brand.get("description") or (h1[0] if h1 else brand.get("tagline", ""))
    corpus = " ".join([brand.get("description", ""), *headings, *paragraphs, *features])
    return {
        "name": brand.get("name", ""),
        "website_url": url,
        "tagline": brand.get("tagline", ""),
        "description": brand.get("description", ""),
        "one_liner": clean_text(one_liner, MAX_LINE),
        "language": brand.get("language", ""),
        "image_url": brand.get("image_url", ""),
        "logo": logo,
        "colors": _colors(source or "", sheets, brand.get("colors", [])),
        "fonts": _fonts(sheets, brand.get("fonts", [])),
        "headings": headings,
        "sample_lines": sample_lines,
        "features": features,
        "pricing_hook": _pricing_hook([brand.get("description", ""), *paragraphs, *headings]),
        "category": _category(corpus),
    }


Getter = Callable[..., Any]


def _fetch_text(get: Getter, url: str, **kw: Any) -> tuple[str, str, str]:
    from app.domains.adstudio.fetch import FetchError

    try:
        result = get(url, accept_language="en-US,en;q=0.9", **kw)
    except FetchError as exc:
        if exc.status_code == 424:
            raise SiteAnalysisError(
                "the website blocked the automated visit; paste your brand details instead", 424
            ) from exc
        raise SiteAnalysisError(exc.message, exc.status_code) from exc
    return result.url, (result.content_type or "").lower(), result.text()


def analyze_site(url: str, *, getter: Getter | None = None) -> dict[str, Any]:
    """Fetch the homepage + same-origin stylesheets through the SSRF guard and analyze."""
    from app.domains.adstudio.fetch import FetchError, safe_get

    get = getter or safe_get
    final_url, content_type, html = _fetch_text(get, url)
    if content_type and "html" not in content_type and "xml" not in content_type:
        raise SiteAnalysisError("that address is not a web page")
    sheets: list[str] = []
    for css_url in stylesheet_links(html, final_url):
        try:
            sheets.append(get(css_url, accept="text/css,*/*;q=0.1", max_bytes=CSS_MAX_BYTES).text())
        except (FetchError, Exception):  # noqa: BLE001 - a stylesheet is optional
            continue
    result = analyze_html(html, final_url, stylesheets=sheets)
    if not result["name"] and not result["description"]:
        raise SiteAnalysisError("could not find a brand name or description on that page; try your homepage")
    return result


__all__ = [
    "SiteAnalysisError",
    "analyze_html",
    "analyze_site",
    "font_family_name",
    "hsl_to_hex",
    "stylesheet_links",
]
