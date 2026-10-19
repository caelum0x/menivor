"""Product URL -> normalized product dict (fetch + store-aware parsing).

The fetcher is an injectable seam (defaults to the SSRF-guarded
:func:`app.domains.adstudio.fetch.safe_get`) so the full flow is testable
offline. Store detection:

* Trendyol  -> :mod:`app.domains.adstudio.trendyol` initial-state parser;
* Amazon    -> DOM parser, with an explicit bot-wall detection that tells the
  user to enter the product manually instead of silently returning junk;
* Shopify   -> the storefront's public ``/products/<handle>.json`` document;
* anything else -> JSON-LD ``Product`` + OpenGraph + DOM fallbacks.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app.domains.adstudio import extract
from app.domains.adstudio.fetch import FetchError, FetchResult, normalize_public_url, safe_get
from app.domains.adstudio.trendyol import gateway_url, is_trendyol, parse_gateway, parse_trendyol

Fetcher = Callable[..., FetchResult]
_KNOWN_SOURCES = frozenset({"trendyol", "amazon", "shopify", "generic", "manual"})


def _fetch_shopify(url: str, fetcher: Fetcher) -> dict[str, Any]:
    json_url = extract.shopify_json_url(url)
    if not json_url:
        return {}
    try:
        result = fetcher(json_url, accept="application/json")
        return extract.parse_shopify_json(json.loads(result.text()))
    except (FetchError, ValueError, TypeError):
        # The HTML layers still produce a product; the JSON is an enrichment.
        return {}


def _trendyol_gateway(url: str, fetcher: Fetcher) -> dict[str, Any]:
    endpoint = gateway_url(url)
    if not endpoint:
        return {}
    try:
        result = fetcher(endpoint, accept="application/json")
        fields = parse_gateway(json.loads(result.text()))
    except (FetchError, ValueError, TypeError):
        return {}
    if not fields:
        return {}
    product = extract.merge(extract.empty_product(url), fields)
    return extract.finalize(product, url)


def with_fallback_bullets(product: dict[str, Any], dom_bullets: list[str]) -> dict[str, Any]:
    """Bullets from structured data first, then description sentences, and
    only then page list items (which are often navigation on generic pages)."""
    if product.get("bullets"):
        return product
    sentences = extract.description_sentences(str(product.get("description") or ""))
    return {**product, "bullets": sentences or list(dom_bullets)}


def parse_page(source: str, url: str) -> dict[str, Any]:
    """Pure: parse an already-fetched page into a product dict."""
    layers: list[dict[str, Any]] = []
    if is_trendyol(url):
        layers.append(parse_trendyol(source))
    elif extract.is_amazon(url):
        layers.append(extract.parse_amazon(source))
    layers.append(extract.product_from_json_ld(source))
    layers.append(extract.product_from_meta(source))
    dom = extract.product_from_dom(source)
    layers.append({"title": dom.get("title", "")})
    product = extract.merge(extract.empty_product(url), *layers)
    product = with_fallback_bullets(product, dom.get("bullets") or [])
    if product.get("source") == "generic" and is_trendyol(url):
        product["source"] = "trendyol"
    if not product.get("language"):
        product["language"] = extract.detect_language(source, url)
    return extract.finalize(product, url)


def scrape_product(raw_url: str, *, fetcher: Fetcher | None = None) -> dict[str, Any]:
    """Fetch ``raw_url`` and return a normalized product dict.

    Raises :class:`FetchError` with a user-presentable message when the page is
    unreachable, blocked, or yields no usable product.
    """
    fetch = fetcher or safe_get
    url = normalize_public_url(raw_url)
    try:
        result = fetch(url)
    except FetchError:
        if is_trendyol(url):
            product = _trendyol_gateway(url, fetch)
            if product.get("title"):
                return product
        raise
    source = result.text()
    final_url = result.url or url
    if extract.is_amazon(final_url) and extract.amazon_blocked(source):
        raise FetchError(
            424,
            "Amazon showed a robot check instead of the product page; "
            "enter the product details manually instead",
        )
    product = parse_page(source, final_url)
    if extract.is_shopify(source):
        shopify = _fetch_shopify(final_url, fetch)
        if shopify:
            merged = extract.merge(extract.empty_product(final_url), shopify, {**product, "bullets": []})
            product = extract.finalize(with_fallback_bullets(merged, product.get("bullets") or []), final_url)
            product["source"] = "shopify"
    if is_trendyol(final_url) and not product.get("price"):
        gateway = _trendyol_gateway(final_url, fetch)
        if gateway:
            product = extract.finalize(extract.merge(gateway, product), final_url)
    product["url"] = final_url
    if not product.get("title"):
        raise FetchError(422, "no product could be found on that page")
    return product


def manual_product(fields: dict[str, Any], url: str = "") -> dict[str, Any]:
    """Build a product dict from user-entered fields (no fetch)."""
    product = extract.empty_product(url)
    source = str(fields.get("source") or "").lower()
    product["source"] = source if source in _KNOWN_SOURCES else "manual"
    product["title"] = extract.clean_text(fields.get("title"), 200)
    product["brand"] = extract.clean_text(fields.get("brand"), 80)
    product["description"] = extract.clean_text(fields.get("description"))
    product["price"] = extract.parse_price(fields.get("price"))
    product["original_price"] = extract.parse_price(fields.get("original_price"))
    product["currency"] = str(fields.get("currency") or "").upper()[:3]
    product["images"] = [str(i) for i in fields.get("images") or [] if str(i).strip()]
    product["bullets"] = [str(b) for b in fields.get("bullets") or []]
    product["reviews"] = [str(r) for r in fields.get("reviews") or []]
    rating = extract.parse_price(fields.get("rating"))
    product["rating"] = rating
    count = extract.parse_price(fields.get("review_count"))
    product["review_count"] = int(count) if count else None
    product["language"] = str(fields.get("language") or "").lower()[:2] or "en"
    finalized = extract.finalize(product, url)
    if not finalized["title"]:
        raise FetchError(422, "a product title is required")
    return finalized


__all__ = ["manual_product", "parse_page", "scrape_product"]
