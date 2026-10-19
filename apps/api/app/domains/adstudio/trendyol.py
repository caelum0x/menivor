"""Trendyol product page parser (pure, no network).

Trendyol server-renders the product-detail app and embeds its initial state as
a JavaScript assignment, e.g.::

    window["__PRODUCT_DETAIL_APP_INITIAL_STATE__"]={"product":{...}, ...};

The exact global name has changed across storefront releases, so the parser
looks for every known marker, extracts the balanced JSON object that follows
it (string/escape aware, no ``eval``), and reads the product fields defensively.
Relative media paths are resolved against Trendyol's public CDN. The page's
schema.org ``Product`` JSON-LD is merged by the caller as a second layer, so a
storefront change that drops the initial state still yields a usable product.
When the page itself is unavailable (bot wall), the public product-detail
gateway JSON for the URL's ``-p-<id>`` content id is tried as a fallback.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from app.domains.adstudio.extract import MAX_BULLET, MAX_REVIEW, clean_text, parse_price

TRENDYOL_CDN = "https://cdn.dsmcdn.com"
PRODUCT_GATEWAY = "https://apigw.trendyol.com/discovery-web-productgw-service/api/productDetail"
_STATE_MARKERS = (
    "__PRODUCT_DETAIL_APP_INITIAL_STATE__",
    "__envoy_product-detail__PROPS",
    "__PRODUCT_DETAIL_INITIAL_STATE__",
)
_CONTENT_ID_RE = re.compile(r"-p-(\d+)")
_MAX_STATE_CHARS = 3_000_000


def is_trendyol(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "trendyol.com" or host.endswith(".trendyol.com") or host == "ty.gl"


def content_id(url: str) -> str:
    match = _CONTENT_ID_RE.search(urlparse(url).path or "")
    return match.group(1) if match else ""


def balanced_json_after(source: str, start: int) -> Any | None:
    """Parse the first balanced ``{...}`` object at or after ``start``."""
    open_at = source.find("{", start)
    if open_at < 0 or open_at - start > 64:
        return None
    depth = 0
    in_string = False
    escaped = False
    limit = min(len(source), open_at + _MAX_STATE_CHARS)
    for index in range(open_at, limit):
        ch = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(source[open_at : index + 1])
                except (ValueError, TypeError):
                    return None
    return None


def _initial_state(source: str) -> dict | None:
    for marker in _STATE_MARKERS:
        position = source.find(marker)
        while position >= 0:
            state = balanced_json_after(source, position + len(marker))
            if isinstance(state, dict):
                return state
            position = source.find(marker, position + len(marker))
    return None


def _find_product(state: dict) -> dict | None:
    """Locate the product object inside an initial-state tree."""
    candidates = [state.get("product"), (state.get("props") or {}).get("product") if isinstance(state.get("props"), dict) else None]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("name"):
            return candidate
    # Breadth-first fallback over a bounded number of nodes.
    queue: list[Any] = [state]
    visited = 0
    while queue and visited < 5000:
        node = queue.pop(0)
        visited += 1
        if isinstance(node, dict):
            if node.get("name") and ("images" in node or "price" in node) and "id" in node:
                return node
            queue.extend(v for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            queue.extend(v for v in node if isinstance(v, (dict, list)))
    return None


def _cdn(path: Any) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"{TRENDYOL_CDN}/{value.lstrip('/')}"


def _price_block(product: dict) -> tuple[float | None, float | None, str]:
    price = product.get("price")
    if isinstance(price, dict):
        selling = price.get("sellingPrice") or price.get("discountedPrice") or {}
        original = price.get("originalPrice") or {}
        current = parse_price(selling.get("value") if isinstance(selling, dict) else selling)
        before = parse_price(original.get("value") if isinstance(original, dict) else original)
        currency = str(price.get("currency") or "TRY").upper()[:3]
        return current, before, currency
    return parse_price(price), None, "TRY"


def _bullets(product: dict) -> list[str]:
    bullets: list[str] = []
    for item in product.get("contentDescriptions") or product.get("descriptions") or []:
        text = clean_text(item.get("description") if isinstance(item, dict) else item, MAX_BULLET)
        if len(text) >= 8 and text not in bullets:
            bullets.append(text)
    # Structured attributes read well as short feature lines ("Materyal: Pamuk").
    for attr in product.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        key = attr.get("key", {})
        value = attr.get("value", {})
        name = clean_text(key.get("name") if isinstance(key, dict) else key, 60)
        val = clean_text(value.get("name") if isinstance(value, dict) else value, 80)
        line = f"{name}: {val}" if name and val else ""
        if line and line not in bullets and len(bullets) < 12:
            bullets.append(line)
    return bullets


def _rating(product: dict) -> tuple[float | None, int | None]:
    score = product.get("ratingScore")
    if isinstance(score, dict):
        average = parse_price(score.get("averageRating"))
        count = score.get("totalCount") or score.get("totalRatingCount") or score.get("totalCommentCount")
        parsed = parse_price(count)
        return average, int(parsed) if parsed else None
    return None, None


def _reviews(state: dict, product: dict) -> list[str]:
    reviews: list[str] = []
    sources = [product.get("reviews"), state.get("reviews"), (state.get("productReviews") or {}).get("content") if isinstance(state.get("productReviews"), dict) else None]
    for block in sources:
        if isinstance(block, dict):
            block = block.get("content") or block.get("items")
        for item in block or []:
            if isinstance(item, dict):
                text = clean_text(item.get("comment") or item.get("text") or item.get("reviewBody"), MAX_REVIEW)
                if len(text) >= 12 and text not in reviews:
                    reviews.append(text)
    return reviews


def product_fields(product: dict, state: dict | None = None) -> dict[str, Any]:
    """Map one Trendyol product object (page state or gateway JSON) to fields."""
    price, original, currency = _price_block(product)
    rating, review_count = _rating(product)
    brand = product.get("brand")
    images = [_cdn(i) for i in product.get("images") or [] if _cdn(i)]
    return {
        "source": "trendyol",
        "title": clean_text(product.get("name"), 200),
        "brand": clean_text(brand.get("name") if isinstance(brand, dict) else brand, 80),
        "description": clean_text(product.get("description") or ""),
        "price": price,
        "original_price": original,
        "currency": currency or "TRY",
        "images": images,
        "bullets": _bullets(product),
        "rating": rating,
        "review_count": review_count,
        "reviews": _reviews(state or {}, product),
        "language": "tr",
    }


def parse_trendyol(source: str) -> dict[str, Any]:
    """Extract a product dict from a Trendyol product page (``{}`` if absent)."""
    state = _initial_state(source or "")
    if not state:
        return {}
    product = _find_product(state)
    if not product:
        return {}
    return product_fields(product, state)


def gateway_url(url: str) -> str | None:
    """Trendyol's public product-detail JSON for a ``...-p-<id>`` URL."""
    cid = content_id(url)
    return f"{PRODUCT_GATEWAY}/{cid}" if cid else None


def parse_gateway(payload: Any) -> dict[str, Any]:
    """Parse the product-detail gateway response (``{"result": {...}}``)."""
    product = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(product, dict) or not product.get("name"):
        return {}
    return product_fields(product)


__all__ = [
    "TRENDYOL_CDN",
    "balanced_json_after",
    "content_id",
    "gateway_url",
    "is_trendyol",
    "parse_gateway",
    "parse_trendyol",
    "product_fields",
]
