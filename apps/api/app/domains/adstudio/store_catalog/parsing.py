"""Pure normalizers for public store product feeds (no network, no DB)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.domains.adstudio.extract import clean_text, parse_price
from app.domains.ads.platforms import minor_factor

MAX_DESCRIPTION = 2000
MAX_IMAGES = 8
MAX_TAGS = 20


def _digits(currency: str) -> int:
    return 0 if minor_factor(currency or "USD") == 1 else 2


def major_to_minor(value: Any, currency: str) -> int | None:
    """``"19.99"`` -> ``1999`` (zero-decimal currencies stay whole)."""
    amount = parse_price(value)
    if amount is None:
        return None
    return int(round(amount * (10 ** _digits(currency))))


def minor_to_major(value: int | None, currency: str) -> float | None:
    if value is None:
        return None
    return round(value / (10 ** _digits(currency)), _digits(currency))


def _images(urls: list[Any]) -> list[str]:
    out: list[str] = []
    for raw in urls:
        url = str(raw or "").strip()
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith(("http://", "https://")) and url not in out:
            out.append(url)
        if len(out) >= MAX_IMAGES:
            break
    return out


def _tags(values: list[Any]) -> list[str]:
    out = []
    for value in values:
        tag = clean_text(value, 60)
        if tag and tag not in out:
            out.append(tag)
    return out[:MAX_TAGS]


def shopify_product(item: Any, origin: str, currency: str) -> dict | None:
    if not isinstance(item, dict) or item.get("id") is None:
        return None
    title = clean_text(item.get("title"), 500)
    if not title:
        return None
    variants = [v for v in item.get("variants") or [] if isinstance(v, dict)]
    first = next((v for v in variants if v.get("available", True)), variants[0] if variants else {})
    price = major_to_minor(first.get("price"), currency)
    compare = major_to_minor(first.get("compare_at_price"), currency)
    raw_tags = item.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [t for t in raw_tags.split(",")]
    handle = str(item.get("handle") or "").strip()
    return {
        "external_id": str(item["id"])[:128],
        "title": title,
        "description": clean_text(item.get("body_html"), MAX_DESCRIPTION),
        "price_minor": price,
        "compare_at_minor": compare if compare and price and compare > price else None,
        "currency": (currency or "")[:3],
        "url": f"{origin}/products/{quote(handle)}" if handle else origin,
        "image_urls": _images([i.get("src") for i in item.get("images") or [] if isinstance(i, dict)]),
        "tags": _tags(list(raw_tags)),
        "raw": {"vendor": clean_text(item.get("vendor"), 80), "product_type": clean_text(item.get("product_type"), 80),
                "handle": handle[:200], "available": any(bool(v.get("available", True)) for v in variants)},
    }


def parse_shopify(payload: Any, origin: str, currency: str) -> list[dict] | None:
    """``None`` when the payload is not a Shopify ``products.json`` document."""
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        return None
    return [p for p in (shopify_product(i, origin, currency) for i in payload["products"]) if p]


def _woo_minor(value: Any, minor_unit: int, currency: str) -> int | None:
    """Store API prices are integer strings in the store's own minor unit."""
    try:
        amount = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    shift = _digits(currency) - minor_unit
    return amount * (10 ** shift) if shift >= 0 else amount // (10 ** -shift)


def woo_product(item: Any, origin: str) -> dict | None:
    if not isinstance(item, dict) or item.get("id") is None:
        return None
    title = clean_text(item.get("name"), 500)
    if not title:
        return None
    prices = item.get("prices") if isinstance(item.get("prices"), dict) else {}
    currency = str(prices.get("currency_code") or "").upper()[:3]
    try:
        minor_unit = int(prices.get("currency_minor_unit", 2))
    except (TypeError, ValueError):
        minor_unit = 2
    price = _woo_minor(prices.get("price"), minor_unit, currency)
    regular = _woo_minor(prices.get("regular_price"), minor_unit, currency)
    description = item.get("short_description") or item.get("description")
    return {
        "external_id": str(item["id"])[:128],
        "title": title,
        "description": clean_text(description, MAX_DESCRIPTION),
        "price_minor": price,
        "compare_at_minor": regular if regular and price and regular > price else None,
        "currency": currency,
        "url": str(item.get("permalink") or origin)[:2000],
        "image_urls": _images([i.get("src") for i in item.get("images") or [] if isinstance(i, dict)]),
        "tags": _tags([t.get("name") for t in item.get("tags") or [] if isinstance(t, dict)]),
        "raw": {"categories": _tags([c.get("name") for c in item.get("categories") or [] if isinstance(c, dict)]),
                "sku": clean_text(item.get("sku"), 80), "in_stock": bool(item.get("is_in_stock", True))},
    }


def parse_woo(payload: Any, origin: str) -> list[dict] | None:
    """``None`` when the payload is not a Store API product list."""
    if not isinstance(payload, list):
        return None
    if payload and not all(isinstance(i, dict) and "prices" in i for i in payload[:3]):
        return None
    return [p for p in (woo_product(i, origin) for i in payload) if p]


def to_manual_product(product: dict, provider: str) -> dict:
    """Shape an imported product as the Ad Studio manual-product input."""
    currency = str(product.get("currency") or "")
    raw = product.get("raw") or {}
    return {
        "title": str(product.get("title") or "")[:200],
        "brand": str(raw.get("vendor") or "")[:80],
        "description": str(product.get("description") or "")[:2000],
        "price": minor_to_major(product.get("price_minor"), currency),
        "original_price": minor_to_major(product.get("compare_at_minor"), currency),
        "currency": currency,
        "images": list(product.get("image_urls") or [])[:MAX_IMAGES],
        "bullets": [],
        "source": "shopify" if provider == "shopify" else "generic",
    }


__all__ = ["major_to_minor", "minor_to_major", "parse_shopify", "parse_woo", "shopify_product", "to_manual_product",
           "woo_product"]
