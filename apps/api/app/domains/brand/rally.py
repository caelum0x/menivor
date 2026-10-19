"""Rally brand-kit share import (Rally -> Menivor bridge).

A Rally user can share their brand kit as a URL or a bare token. Menivor only
ever fetches from the CONFIGURED Rally origin (``RALLY_WEB_URL``, default
``https://vcpeer.com``): a pasted URL is used solely to read the token, and a
URL pointing at any other host is rejected, so this endpoint can never be used
to make the API fetch an arbitrary URL.

Accepted inputs (``<token>`` = 16-128 chars of ``[A-Za-z0-9_-]``):

* ``<token>``
* ``https://vcpeer.com/rally/brand-kit/<token>``
* ``https://vcpeer.com/rally/brand-kit?token=<token>``
* ``https://vcpeer.com/api/autogtm/brand/public/<token>`` (Rally's share URL)
* ``https://vcpeer.com/api/autogtm/brand-kit/share/<token>`` (legacy form)

Fetched contract (Rally ``lib/autogtm/brand-kit.ts``, format
``rally.brand-kit`` v1): ``GET {RALLY_WEB_URL}/api/autogtm/brand/public/<token>``
returning ``{success, data: {format, version, brand: {name, tagline, website,
logoUrl, iconUrl, colors: {primary, ..., palette}, fonts: {heading, body},
voice: {summary, tone, avoid}}, provenance}}``. Flatter shapes (kit at the top
level or under ``data`` / ``brandKit`` / ``brand_kit`` / ``kit``, list-valued
colors/fonts, camelCase or snake_case keys) are also accepted.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from app.domains.adstudio.extract import clean_text
from app.domains.brand.extract import (
    MAX_COLORS,
    MAX_DESCRIPTION,
    MAX_FIELD,
    MAX_FONTS,
    MAX_NAME,
    MAX_TAGLINE,
    empty_brand,
    normalize_hex,
)

DEFAULT_RALLY_WEB_URL = "https://vcpeer.com"
SHARE_API_PATH = "/api/autogtm/brand/public/"
SHARE_MAX_BYTES = 256_000
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_PATH_TOKEN_RE = re.compile(r"/(?:rally|autogtm)/brand-kit/([A-Za-z0-9_-]{16,128})/?$")
_API_TOKEN_RE = re.compile(r"/api/autogtm/(?:brand/public|brand-kit/share)/([A-Za-z0-9_-]{16,128})/?$")


class RallyShareError(Exception):
    """A user-presentable Rally share failure carrying an HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def rally_web_url() -> str:
    """The configured Rally origin (scheme + host, no trailing slash)."""
    raw = (os.environ.get("RALLY_WEB_URL") or DEFAULT_RALLY_WEB_URL).strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return DEFAULT_RALLY_WEB_URL
    return f"{parsed.scheme}://{parsed.netloc}"


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def parse_share_token(raw: str, *, rally_origin: str | None = None) -> str:
    """Return the share token from a token or a Rally share URL, else raise 422."""
    value = (raw or "").strip()
    if not value or len(value) > 2048:
        raise RallyShareError(422, "paste a Rally brand kit share link or token")
    if _TOKEN_RE.match(value):
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RallyShareError(422, "paste a Rally brand kit share link or token")
    origin = rally_origin or rally_web_url()
    if _host(value) != _host(origin):
        raise RallyShareError(422, "that link is not a Rally brand kit share link")
    for pattern in (_API_TOKEN_RE, _PATH_TOKEN_RE):
        match = pattern.search(parsed.path)
        if match:
            return match.group(1)
    token = (parse_qs(parsed.query).get("token") or [""])[0].strip()
    if _TOKEN_RE.match(token):
        return token
    raise RallyShareError(422, "the Rally link does not contain a brand kit share token")


def share_api_url(token: str, *, rally_origin: str | None = None) -> str:
    return f"{rally_origin or rally_web_url()}{SHARE_API_PATH}{token}"


def _pick(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _text(payload: dict[str, Any], limit: int, *keys: str) -> str:
    value = _pick(payload, *keys)
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value if isinstance(v, (str, int, float)))
    return clean_text(value, limit) if isinstance(value, (str, int, float)) else ""


def _http_url(value: Any) -> str:
    text = str(value or "").strip()
    return text if urlparse(text).scheme in {"http", "https"} and len(text) <= 2048 else ""


_COLOR_ROLES = ("primary", "secondary", "accent", "background", "text")


def _colors(value: Any) -> list[dict[str, str]]:
    if isinstance(value, dict):
        # Rally v1: {primary, secondary, accent, background, text, palette: [...]}
        palette = value.get("palette")
        items = [value.get(role) for role in _COLOR_ROLES] + (palette if isinstance(palette, list) else [])
    else:
        items = value if isinstance(value, list) else []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        raw = item.get("hex") or item.get("value") if isinstance(item, dict) else item
        hex_color = normalize_hex(raw)
        if hex_color and hex_color not in seen:
            seen.add(hex_color)
            out.append({"hex": hex_color, "origin": "rally"})
        if len(out) >= MAX_COLORS:
            break
    return out


def _fonts(value: Any) -> list[dict[str, str]]:
    if isinstance(value, dict):
        # Rally v1: {heading, body}
        items: list[Any] = [value.get("heading"), value.get("body")]
    else:
        items = value if isinstance(value, list) else ([value] if isinstance(value, str) else [])
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        raw = item.get("family") or item.get("name") if isinstance(item, dict) else item
        family = clean_text(raw, 60)
        if family and family.lower() not in seen:
            seen.add(family.lower())
            out.append({"family": family, "origin": "rally"})
        if len(out) >= MAX_FONTS:
            break
    return out


def unwrap_payload(payload: Any) -> dict[str, Any]:
    """Return the kit object from the common envelope shapes, else raise 502."""
    node = payload
    for _ in range(3):
        if not isinstance(node, dict):
            break
        inner = _pick(node, "brandKit", "brand_kit", "data", "kit", "brand")
        if isinstance(inner, dict):
            node = inner
            continue
        break
    if not isinstance(node, dict):
        raise RallyShareError(502, "Rally returned an unexpected brand kit format")
    return node


def brand_from_rally(payload: Any) -> dict[str, Any]:
    """Normalize a Rally share payload into the Menivor brand-kit shape."""
    kit = unwrap_payload(payload)
    language = _text(kit, 8, "language", "lang", "locale").lower()[:2]
    voice_obj = kit.get("voice") if isinstance(kit.get("voice"), dict) else {}
    voice_tone = voice_obj.get("tone") if isinstance(voice_obj.get("tone"), list) else []
    brand = {
        **empty_brand(_http_url(_pick(kit, "websiteUrl", "website_url", "website", "url", "domainUrl"))),
        "name": _text(kit, MAX_NAME, "name", "brandName", "brand_name", "companyName", "company_name"),
        "tagline": _text(kit, MAX_TAGLINE, "tagline", "slogan", "headline"),
        "description": _text(kit, MAX_DESCRIPTION, "description", "summary", "about", "pitch")
        or _text(voice_obj, MAX_DESCRIPTION, "summary"),
        "logo_url": _http_url(_pick(kit, "logoUrl", "logo_url", "logo", "iconUrl", "icon_url")),
        "image_url": _http_url(_pick(kit, "imageUrl", "image_url", "ogImage", "og_image")),
        "colors": _colors(_pick(kit, "colors", "palette", "brandColors", "brand_colors")),
        "fonts": _fonts(_pick(kit, "fonts", "typography", "fontFamilies", "font_families")),
        "voice": (
            clean_text(", ".join(str(t) for t in voice_tone if isinstance(t, str)), MAX_FIELD)
            if voice_obj
            else _text(kit, MAX_FIELD, "voice", "tone", "brandVoice", "brand_voice")
        ),
        "audience": _text(kit, MAX_FIELD, "audience", "icp", "targetAudience", "target_audience"),
        "offer": _text(kit, MAX_FIELD, "offer", "valueProp", "value_prop", "valueProposition"),
        "language": language if language.isalpha() else "",
    }
    if not brand["name"] and not brand["website_url"]:
        raise RallyShareError(422, "the shared Rally brand kit has no name or website")
    return brand


def fetch_rally_brand(
    raw_share: str,
    *,
    getter: Callable[..., Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Resolve a share link/token against the configured Rally origin.

    Returns ``(token, brand)``. The HTTP GET goes through the Ad Studio SSRF
    guard (``safe_get``) so even a misconfigured ``RALLY_WEB_URL`` cannot reach
    internal addresses.
    """
    from app.domains.adstudio.fetch import FetchError, safe_get

    token = parse_share_token(raw_share)
    get = getter or safe_get
    try:
        result = get(
            share_api_url(token),
            max_bytes=SHARE_MAX_BYTES,
            accept="application/json",
            accept_language="en-US,en;q=0.9",
        )
    except FetchError as exc:
        if exc.status_code == 404:
            raise RallyShareError(404, "that Rally brand kit link was not found or has been revoked") from exc
        raise RallyShareError(502, "could not reach Rally to read the brand kit; try again") from exc
    try:
        payload = json.loads(result.text())
    except (ValueError, TypeError) as exc:
        raise RallyShareError(502, "Rally returned an unreadable brand kit") from exc
    return token, brand_from_rally(payload)


__all__ = [
    "DEFAULT_RALLY_WEB_URL",
    "RallyShareError",
    "brand_from_rally",
    "fetch_rally_brand",
    "parse_share_token",
    "rally_web_url",
    "share_api_url",
    "unwrap_payload",
]
