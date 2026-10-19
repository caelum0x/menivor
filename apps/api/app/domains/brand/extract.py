"""Pure brand-kit extraction from a fetched website homepage (no network).

Reuses the Ad Studio page parsing primitives (meta tags, JSON-LD, text
cleaning, language detection) so a brand kit is read from a site exactly the way
a product is. Only what the page actually publishes is returned: a field that
cannot be found is left empty rather than guessed, and every colour / font
carries the ``origin`` it was read from so the UI can show where it came from.

Output (see :func:`empty_brand`) is a plain JSON-safe ``dict`` so it can be
stored verbatim inside a brand kit's opaque ``config`` blob.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.domains.adstudio.extract import (
    _is_type,
    _walk_ld,
    absolutize,
    clean_text,
    detect_language,
    find_json_objects,
    meta_tags,
)

MAX_COLORS = 6
MAX_FONTS = 4
MAX_NAME = 120
MAX_TAGLINE = 200
MAX_DESCRIPTION = 600
MAX_FIELD = 400

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')')
_STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_STYLE_ATTR_RE = re.compile(r'\bstyle\s*=\s*"([^"]*)"', re.IGNORECASE)
_HEX_RE = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_BRAND_VAR_RE = re.compile(
    r"--(?:[a-z0-9-]*?)(?:brand|primary|accent|secondary)[a-z0-9-]*\s*:\s*(#[0-9a-fA-F]{3,6})\b",
    re.IGNORECASE,
)
_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}\"]+)", re.IGNORECASE)
_TITLE_SPLIT_RE = re.compile(r"\s+[|\-–—:·]\s+")

_GENERIC_FONTS = frozenset(
    {
        "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
        "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded", "inherit",
        "initial", "unset", "-apple-system", "blinkmacsystemfont", "segoe ui",
        "helvetica", "helvetica neue", "arial", "roboto", "noto sans",
        "apple color emoji", "segoe ui emoji", "segoe ui symbol", "noto color emoji",
        "times new roman", "courier new", "menlo", "monaco", "consolas",
        "liberation mono", "sfmono-regular", "var",
    }
)


def empty_brand(url: str = "") -> dict[str, Any]:
    """The canonical brand-kit shape (every field present, empty by default)."""
    return {
        "name": "",
        "tagline": "",
        "description": "",
        "website_url": url,
        "logo_url": "",
        "image_url": "",
        "colors": [],
        "fonts": [],
        "voice": "",
        "audience": "",
        "offer": "",
        "language": "",
    }


def _expand_hex(value: str) -> str:
    raw = value.lstrip("#").lower()
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return f"#{raw}" if len(raw) == 6 and all(c in "0123456789abcdef" for c in raw) else ""


def normalize_hex(value: Any) -> str:
    """Return ``#rrggbb`` for a 3/6-digit hex colour string, else ''."""
    text = str(value or "").strip()
    if not text.startswith("#"):
        text = f"#{text}" if text else ""
    return _expand_hex(text) if text else ""


def _is_neutral(hex_color: str) -> bool:
    """True for near-white, near-black and flat greys (not brand signals)."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    spread = max(r, g, b) - min(r, g, b)
    return spread < 18 or max(r, g, b) < 28 or min(r, g, b) > 235


def _link_tags(source: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for tag in _LINK_RE.findall(source):
        attrs = {
            m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4)) or ""
            for m in _ATTR_RE.finditer(tag)
        }
        out.append(attrs)
    return out


def _ld_organization(source: str) -> dict[str, Any]:
    for obj in find_json_objects(source):
        for node in _walk_ld(obj):
            if _is_type(node, "Organization") or _is_type(node, "Corporation") or _is_type(node, "Brand"):
                return node
    return {}


def _ld_logo(org: dict[str, Any]) -> str:
    logo = org.get("logo")
    if isinstance(logo, dict):
        logo = logo.get("url") or logo.get("contentUrl")
    return str(logo or "").strip()


def extract_logo(source: str, base_url: str, org: dict[str, Any] | None = None) -> str:
    """Best published logo: JSON-LD Organization.logo, then apple-touch-icon, then icon."""
    candidate = _ld_logo(org or {})
    if candidate:
        resolved = absolutize(candidate, base_url)
        if resolved:
            return resolved
    links = _link_tags(source)
    for wanted in ("apple-touch-icon", "apple-touch-icon-precomposed", "icon", "shortcut icon"):
        for attrs in links:
            rel = (attrs.get("rel") or "").lower().strip()
            if rel == wanted and attrs.get("href"):
                resolved = absolutize(attrs["href"], base_url)
                if resolved:
                    return resolved
    return ""


def extract_colors(source: str, meta: dict[str, str]) -> list[dict[str, str]]:
    """Brand colours in priority order, each tagged with where it was found.

    1. ``<meta name="theme-color">`` / ``msapplication-TileColor`` (declared by the site);
    2. CSS custom properties named like ``--brand`` / ``--primary`` / ``--accent``;
    3. the most frequent non-neutral hex colours in inline ``<style>`` / ``style=``.
    """
    seen: set[str] = set()
    colors: list[dict[str, str]] = []

    def add(value: str, origin: str) -> None:
        hex_color = normalize_hex(value)
        if hex_color and hex_color not in seen and len(colors) < MAX_COLORS:
            seen.add(hex_color)
            colors.append({"hex": hex_color, "origin": origin})

    for key in ("theme-color", "msapplication-tilecolor"):
        if meta.get(key):
            add(meta[key], "meta")

    css = " ".join(_STYLE_BLOCK_RE.findall(source)) + " " + " ".join(_STYLE_ATTR_RE.findall(source))
    for match in _BRAND_VAR_RE.finditer(css):
        add(match.group(1), "css-variable")

    counts: Counter[str] = Counter()
    for match in _HEX_RE.finditer(css):
        hex_color = _expand_hex(match.group(1))
        if hex_color and not _is_neutral(hex_color):
            counts[hex_color] += 1
    for hex_color, _ in counts.most_common(MAX_COLORS * 2):
        add(hex_color, "stylesheet")
    return colors


def _google_font_families(source: str) -> list[str]:
    families: list[str] = []
    for attrs in _link_tags(source):
        href = attrs.get("href") or ""
        if "fonts.googleapis.com" not in href:
            continue
        query = parse_qs(urlparse(href.replace("&amp;", "&")).query)
        for value in query.get("family", []):
            for part in value.split("|"):
                name = part.split(":", 1)[0].replace("+", " ").strip()
                if name:
                    families.append(name)
    return families


def extract_fonts(source: str) -> list[dict[str, str]]:
    """Declared brand fonts: Google Fonts links first, then CSS ``font-family``."""
    seen: set[str] = set()
    fonts: list[dict[str, str]] = []

    def add(name: str, origin: str) -> None:
        cleaned = clean_text(name.strip().strip("'\""), 60)
        key = cleaned.lower()
        if not cleaned or key in seen or key in _GENERIC_FONTS or key.startswith("var("):
            return
        if len(fonts) < MAX_FONTS:
            seen.add(key)
            fonts.append({"family": cleaned, "origin": origin})

    for family in _google_font_families(source):
        add(family, "google-fonts")
    css = " ".join(_STYLE_BLOCK_RE.findall(source)) + " " + " ".join(_STYLE_ATTR_RE.findall(source))
    for match in _FONT_FAMILY_RE.finditer(css):
        first = match.group(1).split(",")[0]
        add(first, "stylesheet")
    return fonts


def _site_name(meta: dict[str, str], org: dict[str, Any], title: str) -> str:
    for value in (meta.get("og:site_name"), meta.get("application-name"), org.get("name")):
        text = clean_text(value, MAX_NAME)
        if text:
            return text
    if title:
        return clean_text(_TITLE_SPLIT_RE.split(title)[0], MAX_NAME)
    return ""


def brand_from_html(source: str, url: str) -> dict[str, Any]:
    """Extract a brand kit from homepage HTML. Pure; never raises on odd markup."""
    brand = empty_brand(url)
    meta = meta_tags(source)
    org = _ld_organization(source)
    title_match = _TITLE_RE.search(source)
    title = clean_text(title_match.group(1), MAX_TAGLINE) if title_match else ""
    h1_match = _H1_RE.search(source)
    h1 = clean_text(h1_match.group(1), MAX_TAGLINE) if h1_match else ""

    name = _site_name(meta, org, title)
    description = clean_text(
        meta.get("og:description") or meta.get("description") or org.get("description") or "",
        MAX_DESCRIPTION,
    )
    tagline = ""
    for candidate in (org.get("slogan"), h1, meta.get("og:title"), title):
        text = clean_text(candidate, MAX_TAGLINE)
        if text and text.lower() != name.lower():
            tagline = text
            break

    image = absolutize(meta.get("og:image") or meta.get("twitter:image") or "", url)
    return {
        **brand,
        "name": name,
        "tagline": tagline,
        "description": description,
        "logo_url": extract_logo(source, url, org),
        "image_url": image,
        "colors": extract_colors(source, meta),
        "fonts": extract_fonts(source),
        "language": detect_language(source, url),
    }


__all__ = [
    "MAX_COLORS",
    "MAX_FONTS",
    "MAX_FIELD",
    "brand_from_html",
    "empty_brand",
    "extract_colors",
    "extract_fonts",
    "extract_logo",
    "normalize_hex",
]
