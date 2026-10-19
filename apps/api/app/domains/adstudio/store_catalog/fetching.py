"""Store URL -> product feed pages, through the Ad Studio SSRF guard.

Shopify: ``/products.json?limit=250`` (one page covers the per-import cap) plus
``/meta.json`` for the store name and currency (best effort). WooCommerce:
the public Store API ``/wp-json/wc/store/v1/products`` (100 per page), with
the ``?rest_route=`` form as a fallback for sites without pretty permalinks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from app.domains.adstudio.catalog_models import MAX_PRODUCTS_PER_IMPORT, PROVIDER_SHOPIFY, PROVIDER_WOOCOMMERCE
from app.domains.adstudio.fetch import FetchError, FetchResult, normalize_public_url, safe_get
from app.domains.adstudio.store_catalog import parsing

FEED_MAX_BYTES = 8_000_000
SHOPIFY_PAGE = 250
WOO_PAGE = 100
JSON_ACCEPT = "application/json"

Fetcher = Callable[..., FetchResult]


@dataclass(frozen=True)
class StoreFeed:
    provider: str
    origin: str
    store_name: str
    currency: str
    products: list[dict] = field(default_factory=list)


def store_origin(raw_url: str) -> str:
    """``shop.example/collections/x`` -> ``https://shop.example`` (422 when not public)."""
    url = (raw_url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    parsed = urlparse(normalize_public_url(url))
    return f"{parsed.scheme}://{parsed.netloc}"


def _json(fetch: Fetcher, url: str) -> Any:
    result = fetch(url, max_bytes=FEED_MAX_BYTES, accept=JSON_ACCEPT, accept_language="en-US,en;q=0.9")
    try:
        return json.loads(result.text())
    except ValueError as exc:
        raise FetchError(422, "the store did not return a JSON product feed") from exc


def fetch_shopify(origin: str, limit: int, fetch: Fetcher) -> StoreFeed:
    name, currency = urlparse(origin).hostname or origin, ""
    try:
        meta = _json(fetch, f"{origin}/meta.json")
        if isinstance(meta, dict):
            name = str(meta.get("name") or name)[:200]
            currency = str(meta.get("currency") or "").upper()[:3]
    except FetchError:
        pass  # meta.json is optional; the product feed decides
    payload = _json(fetch, f"{origin}/products.json?limit={min(limit, SHOPIFY_PAGE)}")
    products = parsing.parse_shopify(payload, origin, currency)
    if products is None:
        raise FetchError(422, "this URL does not expose a Shopify products.json feed")
    return StoreFeed(PROVIDER_SHOPIFY, origin, name, currency, products[:limit])


def _woo_page(origin: str, page: int, fetch: Fetcher) -> list[dict]:
    query = f"per_page={WOO_PAGE}&page={page}"
    try:
        payload = _json(fetch, f"{origin}/wp-json/wc/store/v1/products?{query}")
    except FetchError as exc:
        if exc.status_code != 404:
            raise
        payload = _json(fetch, f"{origin}/?rest_route=/wc/store/v1/products&{query}")
    products = parsing.parse_woo(payload, origin)
    if products is None:
        raise FetchError(422, "this URL does not expose the WooCommerce Store API")
    return products


def fetch_woocommerce(origin: str, limit: int, fetch: Fetcher) -> StoreFeed:
    products: list[dict] = []
    page = 1
    while len(products) < limit:
        batch = _woo_page(origin, page, fetch)
        products.extend(batch)
        if len(batch) < WOO_PAGE:
            break
        page += 1
    currency = next((p["currency"] for p in products if p.get("currency")), "")
    name = urlparse(origin).hostname or origin
    return StoreFeed(PROVIDER_WOOCOMMERCE, origin, name, currency, products[:limit])


def fetch_store(raw_url: str, provider: str = "auto", limit: int = 50, *, fetcher: Fetcher | None = None) -> StoreFeed:
    """Read up to ``limit`` products. ``provider='auto'`` tries Shopify, then WooCommerce."""
    fetch = fetcher or safe_get
    limit = max(1, min(int(limit), MAX_PRODUCTS_PER_IMPORT))
    origin = store_origin(raw_url)
    if provider == PROVIDER_SHOPIFY:
        return fetch_shopify(origin, limit, fetch)
    if provider == PROVIDER_WOOCOMMERCE:
        return fetch_woocommerce(origin, limit, fetch)
    errors: list[FetchError] = []
    for attempt in (fetch_shopify, fetch_woocommerce):
        try:
            return attempt(origin, limit, fetch)
        except FetchError as exc:
            errors.append(exc)
    blocked = next((e for e in errors if e.status_code in (413, 424, 502, 503)), None)
    if blocked is not None:
        raise FetchError(blocked.status_code, f"could not read the store feed: {blocked.message}")
    raise FetchError(422, "no public Shopify or WooCommerce product feed was found at this URL")


__all__ = ["StoreFeed", "fetch_shopify", "fetch_store", "fetch_woocommerce", "store_origin"]
