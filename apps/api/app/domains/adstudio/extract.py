"""Pure product extraction from a fetched product page (no network).

Sources, merged in priority order (first non-empty value wins per field):

1. a store-specific parser (Trendyol initial state, Amazon DOM, Shopify JSON);
2. schema.org ``Product`` JSON-LD (most modern storefronts, incl. Hepsiburada);
3. OpenGraph / product meta tags;
4. generic DOM fallbacks (``<title>``, ``<h1>``, list items as bullets).

Output is a plain ``dict`` (see :func:`empty_product`) so it round-trips through
JSON columns and API responses unchanged.
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

MAX_IMAGES = 10
MAX_BULLETS = 8
MAX_REVIEWS = 6
MAX_TEXT = 600
MAX_BULLET = 180
MAX_REVIEW = 280

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')')
_LDJSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_HTML_LANG_RE = re.compile(r"<html[^>]*\blang=[\"']([a-zA-Z-]+)", re.IGNORECASE)
_NUM_RE = re.compile(r"[\d.,]+")
_NON_CONTENT_RE = re.compile(r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_CODE_MARKERS = ("{", "}", "window.", "function(", "=>", "@media")


def empty_product(url: str = "") -> dict[str, Any]:
    return {
        "url": url,
        "source": "",
        "title": "",
        "brand": "",
        "description": "",
        "price": None,
        "original_price": None,
        "currency": "",
        "images": [],
        "bullets": [],
        "rating": None,
        "review_count": None,
        "reviews": [],
        "language": "",
    }


def clean_text(value: Any, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    text = _html.unescape(_TAG_RE.sub(" ", str(value)))
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit].strip()


def parse_price(value: Any) -> float | None:
    """Parse ``"1.299,90 TL"`` / ``"$1,299.90"`` / ``1299.9`` into a float."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    match = _NUM_RE.search(str(value))
    if not match:
        return None
    raw = match.group(0).strip(".,")
    if "," in raw and "." in raw:
        # The right-most separator is the decimal one.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        head, _, tail = raw.rpartition(",")
        raw = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else raw.replace(",", "")
    elif raw.count(".") > 1 or (raw.count(".") == 1 and len(raw.rpartition(".")[2]) == 3):
        raw = raw.replace(".", "")
    try:
        number = float(raw)
    except ValueError:
        return None
    return number if number > 0 else None


def absolutize(url: str, base: str) -> str:
    value = (url or "").strip()
    if not value or value.startswith("data:"):
        return ""
    if value.startswith("//"):
        value = "https:" + value
    absolute = urljoin(base, value)
    return absolute if urlparse(absolute).scheme in {"http", "https"} else ""


def meta_tags(source: str) -> dict[str, str]:
    """Map ``property``/``name``/``itemprop`` -> ``content`` (first wins)."""
    out: dict[str, str] = {}
    for tag in _META_RE.findall(source):
        attrs = {m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4)) for m in _ATTR_RE.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        content = attrs.get("content")
        if key and content and key not in out:
            out[key] = _html.unescape(content).strip()
    return out


def _walk_ld(node: Any) -> Iterable[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _walk_ld(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _walk_ld(node[key])


def _is_type(node: dict, name: str) -> bool:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return any(str(k).lower() == name.lower() for k in kinds if k)


def find_json_objects(source: str) -> list[Any]:
    objects: list[Any] = []
    for block in _LDJSON_RE.findall(source):
        text = block.strip().strip(";")
        if not text:
            continue
        try:
            objects.append(json.loads(text))
        except (ValueError, TypeError):
            try:
                objects.append(json.loads(_html.unescape(text)))
            except (ValueError, TypeError):
                continue
    return objects


def _images_from(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(value.get("url") or value.get("contentUrl") or "")]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_images_from(item))
        return out
    return []


def _review_text(review: Any) -> str:
    if not isinstance(review, dict):
        return ""
    return clean_text(review.get("reviewBody") or review.get("description") or "", MAX_REVIEW)


def product_from_json_ld(source: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for root in find_json_objects(source):
        for node in _walk_ld(root):
            if not _is_type(node, "Product") and not _is_type(node, "ProductGroup"):
                continue
            out["title"] = clean_text(node.get("name"), 200)
            brand = node.get("brand")
            out["brand"] = clean_text(brand.get("name") if isinstance(brand, dict) else brand, 80)
            out["description"] = clean_text(node.get("description"))
            out["images"] = _images_from(node.get("image"))
            offers = node.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                if price is None and isinstance(offers.get("priceSpecification"), dict):
                    price = offers["priceSpecification"].get("price")
                out["price"] = parse_price(price)
                out["currency"] = str(offers.get("priceCurrency") or "").upper()[:3]
            rating = node.get("aggregateRating")
            if isinstance(rating, dict):
                out["rating"] = parse_price(rating.get("ratingValue"))
                count = rating.get("reviewCount") or rating.get("ratingCount")
                parsed = parse_price(count)
                out["review_count"] = int(parsed) if parsed else None
            reviews = node.get("review")
            reviews = reviews if isinstance(reviews, list) else [reviews]
            out["reviews"] = [t for t in (_review_text(r) for r in reviews) if t]
            if out.get("title"):
                return out
    return out


def product_from_meta(source: str) -> dict[str, Any]:
    meta = meta_tags(source)
    price = meta.get("product:price:amount") or meta.get("og:price:amount") or meta.get("price")
    currency = meta.get("product:price:currency") or meta.get("og:price:currency") or meta.get("pricecurrency") or ""
    return {
        "title": clean_text(meta.get("og:title") or meta.get("twitter:title"), 200),
        "description": clean_text(meta.get("og:description") or meta.get("description") or meta.get("twitter:description")),
        "images": [v for v in (meta.get("og:image"), meta.get("og:image:secure_url"), meta.get("twitter:image")) if v],
        "price": parse_price(price),
        "currency": currency.upper()[:3],
        "brand": clean_text(meta.get("product:brand") or meta.get("og:brand"), 80),
    }


def product_from_dom(source: str) -> dict[str, Any]:
    source = _NON_CONTENT_RE.sub(" ", source)
    title_match = _H1_RE.search(source) or _TITLE_RE.search(source)
    bullets: list[str] = []
    for match in _LI_RE.finditer(source):
        text = clean_text(match.group(1), MAX_BULLET)
        # Navigation/menu items are short; product bullets are sentences.
        if any(marker in text for marker in _CODE_MARKERS):
            continue
        if 25 <= len(text) <= MAX_BULLET and text not in bullets:
            bullets.append(text)
        if len(bullets) >= MAX_BULLETS:
            break
    return {"title": clean_text(title_match.group(1), 200) if title_match else "", "bullets": bullets}


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def description_sentences(description: str, limit: int = 4) -> list[str]:
    out: list[str] = []
    for sentence in _SENTENCE_RE.split(description or ""):
        text = sentence.strip().rstrip(".")
        if 20 <= len(text) <= MAX_BULLET and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def detect_language(source: str, url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith(".tr") or any(s in host for s in ("trendyol", "hepsiburada", "n11.com")):
        return "tr"
    match = _HTML_LANG_RE.search(source[:4000])
    if match and match.group(1).lower().startswith("tr"):
        return "tr"
    return "en"


def merge(base: dict[str, Any], *layers: dict[str, Any]) -> dict[str, Any]:
    """Fill every empty field of ``base`` from ``layers`` (first wins); list
    fields are unioned in order and capped."""
    out = dict(base)
    caps = {"images": MAX_IMAGES, "bullets": MAX_BULLETS, "reviews": MAX_REVIEWS}
    for layer in layers:
        for key, value in (layer or {}).items():
            if key in caps:
                current = list(out.get(key) or [])
                for item in value or []:
                    if item and item not in current:
                        current.append(item)
                out[key] = current[: caps[key]]
            elif out.get(key) in (None, "", 0) and value not in (None, ""):
                out[key] = value
    return out


def finalize(product: dict[str, Any], base_url: str) -> dict[str, Any]:
    out = dict(product)
    out["source"] = str(out.get("source") or "generic")
    images: list[str] = []
    for raw in out.get("images") or []:
        absolute = absolutize(str(raw), base_url)
        if absolute and absolute not in images:
            images.append(absolute)
    out["images"] = images[:MAX_IMAGES]
    out["bullets"] = [clean_text(b, MAX_BULLET) for b in out.get("bullets") or [] if clean_text(b, MAX_BULLET)][:MAX_BULLETS]
    out["reviews"] = [clean_text(r, MAX_REVIEW) for r in out.get("reviews") or [] if clean_text(r, MAX_REVIEW)][:MAX_REVIEWS]
    if out.get("original_price") and out.get("price") and out["original_price"] <= out["price"]:
        out["original_price"] = None
    if out.get("rating") is not None and not (0 < float(out["rating"]) <= 5):
        out["rating"] = None
    return out


# --------------------------------------------------------------------------- #
# Amazon
# --------------------------------------------------------------------------- #
_AMZ_TITLE_RE = re.compile(r'id="productTitle"[^>]*>(.*?)</span>', re.IGNORECASE | re.DOTALL)
_AMZ_BULLETS_RE = re.compile(r'id="feature-bullets"(.*?)</ul>', re.IGNORECASE | re.DOTALL)
_AMZ_PRICE_RE = re.compile(r'class="a-offscreen"[^>]*>([^<]+)<', re.IGNORECASE)
_AMZ_DYN_IMG_RE = re.compile(r'data-a-dynamic-image="([^"]+)"', re.IGNORECASE)
_AMZ_HIRES_RE = re.compile(r'"hiRes"\s*:\s*"(https://[^"]+)"')
_AMZ_RATING_RE = re.compile(r"([0-9][.,][0-9]) (?:out of 5 stars|von 5 Sternen|5 yıldız üzerinden)", re.IGNORECASE)
_AMZ_COUNT_RE = re.compile(r'id="acrCustomerReviewText"[^>]*>([^<]+)<', re.IGNORECASE)
_AMZ_REVIEW_RE = re.compile(r'data-hook="review-body"[^>]*>(.*?)</(?:span|div)>', re.IGNORECASE | re.DOTALL)
_AMZ_BRAND_RE = re.compile(r'id="bylineInfo"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_AMZ_CAPTCHA_MARKERS = ("/errors/validateCaptcha", "Enter the characters you see below", "api-services-support@amazon.com")

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₺": "TRY", "TL": "TRY", "¥": "JPY"}


def is_amazon(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.startswith("amazon.") or ".amazon." in host or host == "amzn.to" or host.endswith(".amzn.to")


def amazon_blocked(source: str) -> bool:
    return any(marker in source for marker in _AMZ_CAPTCHA_MARKERS)


def _currency_from_text(text: str) -> str:
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    return ""


def parse_amazon(source: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "amazon"}
    title = _AMZ_TITLE_RE.search(source)
    if title:
        out["title"] = clean_text(title.group(1), 200)
    brand = _AMZ_BRAND_RE.search(source)
    if brand:
        text = clean_text(brand.group(1), 80)
        for prefix in ("Visit the ", "Brand: ", "Marka: "):
            text = text.replace(prefix, "")
        out["brand"] = text.replace(" Store", "").replace(" Mağazası", "").strip()
    block = _AMZ_BULLETS_RE.search(source)
    if block:
        out["bullets"] = [clean_text(m, MAX_BULLET) for m in _LI_RE.findall(block.group(1)) if len(clean_text(m)) > 8]
    price = _AMZ_PRICE_RE.search(source)
    if price:
        out["price"] = parse_price(price.group(1))
        out["currency"] = _currency_from_text(price.group(1))
    images = _AMZ_HIRES_RE.findall(source)
    if not images:
        dyn = _AMZ_DYN_IMG_RE.search(source)
        if dyn:
            try:
                images = list(json.loads(_html.unescape(dyn.group(1))).keys())
            except (ValueError, TypeError):
                images = []
    out["images"] = images
    rating = _AMZ_RATING_RE.search(source)
    if rating:
        out["rating"] = parse_price(rating.group(1).replace(",", "."))
    count = _AMZ_COUNT_RE.search(source)
    if count:
        parsed = parse_price(count.group(1))
        out["review_count"] = int(parsed) if parsed else None
    out["reviews"] = [clean_text(r, MAX_REVIEW) for r in _AMZ_REVIEW_RE.findall(source)]
    return out


# --------------------------------------------------------------------------- #
# Shopify
# --------------------------------------------------------------------------- #
_SHOPIFY_PATH_RE = re.compile(r"(/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:collections/[^/]+/)?products/[^/?#.]+)", re.IGNORECASE)


def is_shopify(source: str) -> bool:
    return "cdn.shopify.com" in source or "Shopify.theme" in source or "shopify-digital-wallet" in source


def shopify_json_url(url: str) -> str | None:
    parsed = urlparse(url)
    match = _SHOPIFY_PATH_RE.search(parsed.path or "")
    if not match:
        return None
    return f"{parsed.scheme}://{parsed.netloc}{match.group(1)}.json"


def parse_shopify_json(payload: Any) -> dict[str, Any]:
    product = payload.get("product") if isinstance(payload, dict) else None
    if not isinstance(product, dict):
        return {}
    variants = product.get("variants") or []
    first = variants[0] if variants and isinstance(variants[0], dict) else {}
    body = str(product.get("body_html") or "")
    bullets = [clean_text(m, MAX_BULLET) for m in _LI_RE.findall(body) if clean_text(m)]
    return {
        "source": "shopify",
        "title": clean_text(product.get("title"), 200),
        "brand": clean_text(product.get("vendor"), 80),
        "description": clean_text(body),
        "price": parse_price(first.get("price")),
        "original_price": parse_price(first.get("compare_at_price")),
        "images": [str(i.get("src") or "") for i in product.get("images") or [] if isinstance(i, dict)],
        "bullets": bullets,
    }


__all__ = [
    "absolutize",
    "amazon_blocked",
    "clean_text",
    "description_sentences",
    "detect_language",
    "empty_product",
    "finalize",
    "find_json_objects",
    "is_amazon",
    "is_shopify",
    "merge",
    "parse_amazon",
    "parse_price",
    "parse_shopify_json",
    "product_from_dom",
    "product_from_json_ld",
    "product_from_meta",
    "shopify_json_url",
]
