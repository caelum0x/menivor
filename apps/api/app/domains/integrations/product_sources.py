"""Product sources: feed a real catalog into Products (the existing ``store_catalog_*`` tables).

* **Shopify Admin API** with a custom-app token (scope ``read_products``):
  ``GET /admin/api/<ver>/shop.json`` + ``products.json`` (Link-header paging).
  Only ``<shop>.myshopify.com`` hosts are accepted.
* **Medusa** (v2 Store API, e.g. Oxhan Atelier): ``GET /store/regions`` then
  ``GET /store/products?region_id=..&fields=*variants.calculated_price`` with the
  ``x-publishable-api-key`` header. The base URL must be a public host.
* **CSV** text or CSV URL (Shopier and any spreadsheet export); columns are
  matched by name in English or Turkish.

Imports are written with the Ad Studio catalog service, so URL to Video / Image
Ad start from them exactly like a public-feed import. Shopify tokens and Medusa
publishable keys are stored encrypted (``IntegrationConnection`` kind
``product_source``) so a re-sync needs no re-paste.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from typing import Any, Callable
from urllib.parse import urlparse

from app.domains.adstudio.catalog_models import MAX_PRODUCTS_PER_IMPORT
from app.domains.adstudio.extract import clean_text, parse_price
from app.domains.adstudio.fetch import FetchError, normalize_public_url
from app.domains.adstudio.store_catalog import parsing
from app.domains.adstudio.store_catalog import service as catalog
from app.domains.adstudio.store_catalog.fetching import StoreFeed
from app.domains.integrations.connectors.base import Grant, RequestsTransport, body_of, env
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import KIND_PRODUCT_SOURCE, IntegrationConnection
from app.domains.integrations.scope import Scope
from app.domains.integrations.service import store_connection

PROVIDER_SHOPIFY = "shopify"
PROVIDER_MEDUSA = "medusa"
PROVIDER_CSV = "csv"
DEFAULT_SHOPIFY_VERSION = "2025-10"
_SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.myshopify\.com$")
_NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')
CSV_MAX_BYTES = 2_000_000
MEDUSA_PAGE = 100


# --------------------------------------------------------------------------- transport
class PinnedTransport:
    """HTTP for user-supplied hosts: public-host check, DNS pinned to the checked IP, no redirects."""

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        from app.domains.adstudio.fetch import _pinned_ip
        from app.services import webhooks

        normalize_public_url(url)
        pinned = _pinned_ip(url)
        if webhooks.requests is None or webhooks._PinnedHTTPAdapter is None:
            raise FetchError(503, "URL fetching is unavailable on this server")
        session = webhooks.requests.Session()
        session.trust_env = False
        adapter = webhooks._PinnedHTTPAdapter(pinned)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session.request(method, url, headers=headers, params=params, json=json, data=data,
                               timeout=(5, 30), allow_redirects=False)


# --------------------------------------------------------------------------- shared
def _limit(value: int) -> int:
    return max(1, min(int(value or 50), MAX_PRODUCTS_PER_IMPORT))


def _record(session: Any, scope: Scope, feed: StoreFeed, *, store_url: str, limit: int, mode: str) -> dict:
    if not feed.products:
        raise IntegrationError(422, "No products were found in this source.")
    row = catalog.record_import(session, user_id=scope.user_id, store_url=store_url, provider=feed.provider,
                                limit=limit, feed=feed, error="")
    row.workspace_id = scope.workspace_id
    row.options = {**dict(row.options or {}), "mode": mode}
    session.flush()
    return catalog.import_detail(session, scope.user_id, row.id)


def _save_credential(session: Any, scope: Scope, provider: str, secret: str, external_id: str, meta: dict) -> None:
    store_connection(session, owner_scope=scope.owner_scope, workspace_id=scope.workspace_id, user_id=scope.user_id,
                     kind=KIND_PRODUCT_SOURCE, provider=provider, grant=Grant(access_token=secret),
                     display_name=external_id, meta=meta, external_id=external_id)


# --------------------------------------------------------------------------- Shopify
def shop_domain(raw: str) -> str:
    host = (raw or "").strip().lower()
    host = re.sub(r"^https?://", "", host).split("/")[0]
    if host and "." not in host:
        host = f"{host}.myshopify.com"
    if not _SHOP_RE.match(host):
        raise IntegrationError(422, "Use your store's myshopify.com address, e.g. my-store.myshopify.com.")
    return host


def _shopify_get(transport: Any, url: str, token: str) -> tuple[dict, Any]:
    try:
        resp = transport.request("GET", url, headers={"X-Shopify-Access-Token": token, "Accept": "application/json"})
    except Exception as exc:  # noqa: BLE001
        raise IntegrationError(502, "Shopify is unreachable. Try again.") from exc
    if resp.status_code in (401, 403):
        raise IntegrationError(400, "Shopify did not accept this Admin API token (it needs read_products).")
    if resp.status_code >= 400:
        raise IntegrationError(502, f"Shopify answered HTTP {resp.status_code}.")
    body = body_of(resp)
    return (body if isinstance(body, dict) else {}), resp


def fetch_shopify_admin(transport: Any, shop: str, token: str, limit: int) -> StoreFeed:
    version = env("SHOPIFY_ADMIN_API_VERSION") or DEFAULT_SHOPIFY_VERSION
    base = f"https://{shop}/admin/api/{version}"
    info = _shopify_get(transport, f"{base}/shop.json", token)[0].get("shop") or {}
    currency = str(info.get("currency") or "").upper()[:3]
    origin = f"https://{info.get('domain') or shop}"
    products: list[dict] = []
    url: str | None = f"{base}/products.json?limit=250&status=active"
    while url and len(products) < limit:
        body, resp = _shopify_get(transport, url, token)
        parsed = parsing.parse_shopify(body, origin, currency)
        if parsed is None:
            raise IntegrationError(502, "Shopify returned an unexpected product list.")
        products.extend(parsed)
        match = _NEXT_LINK.search(str((getattr(resp, "headers", None) or {}).get("Link") or ""))
        nxt = urlparse(match.group(1)) if match else None
        same = nxt is not None and nxt.scheme == "https" and nxt.netloc == shop and \
            nxt.path == f"/admin/api/{version}/products.json"
        url = match.group(1) if same else None
    return StoreFeed(PROVIDER_SHOPIFY, origin, str(info.get("name") or shop)[:200], currency, products[:limit])


def import_shopify_admin(session: Any, scope: Scope, *, shop: str, token: str, limit: int = 50,
                         transport: Any = None, save: bool = True) -> dict:
    scope.require_manage()
    host = shop_domain(shop)
    secret = (token or "").strip()
    if not 10 <= len(secret) <= 200 or any(ch.isspace() for ch in secret):
        raise IntegrationError(422, "Paste the Admin API access token from your Shopify custom app.")
    feed = fetch_shopify_admin(transport or RequestsTransport(), host, secret, _limit(limit))
    if save:
        _save_credential(session, scope, PROVIDER_SHOPIFY, secret, host, {"shop": host})
    return _record(session, scope, feed, store_url=f"https://{host}", limit=_limit(limit), mode="admin_api")


# --------------------------------------------------------------------------- Medusa
def _medusa_get(transport: Any, url: str, key: str, params: dict | None = None) -> dict:
    try:
        resp = transport.request("GET", url, headers={"x-publishable-api-key": key, "Accept": "application/json"},
                                 params=params or {})
    except FetchError as exc:
        raise IntegrationError(exc.status_code, exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        raise IntegrationError(502, "The Medusa store is unreachable. Try again.") from exc
    if resp.status_code in (400, 401, 403):
        raise IntegrationError(400, "The Medusa store did not accept this publishable key.")
    if resp.status_code >= 400:
        raise IntegrationError(502, f"The Medusa store answered HTTP {resp.status_code}.")
    body = body_of(resp)
    return body if isinstance(body, dict) else {}


def _medusa_product(item: dict, storefront: str, currency: str) -> dict | None:
    title = clean_text(item.get("title"), 500)
    if not item.get("id") or not title:
        return None
    prices = [((v or {}).get("calculated_price") or {}) for v in item.get("variants") or []]
    price = next((p for p in prices if p.get("calculated_amount") is not None), {})
    cur = str(price.get("currency_code") or currency or "").upper()[:3]
    amount = parsing.major_to_minor(price.get("calculated_amount"), cur)
    original = parsing.major_to_minor(price.get("original_amount"), cur)
    handle = str(item.get("handle") or "").strip()
    images = [item.get("thumbnail")] + [(i or {}).get("url") for i in item.get("images") or []]
    return {
        "external_id": str(item["id"])[:128], "title": title,
        "description": clean_text(item.get("description"), parsing.MAX_DESCRIPTION),
        "price_minor": amount, "compare_at_minor": original if original and amount and original > amount else None,
        "currency": cur, "url": f"{storefront}/products/{handle}" if handle and storefront else storefront,
        "image_urls": parsing._images(images),
        "tags": parsing._tags([(t or {}).get("value") for t in item.get("tags") or []]),
        "raw": {"handle": handle[:200], "source": "medusa"},
    }


def fetch_medusa(transport: Any, base_url: str, key: str, storefront_url: str, limit: int) -> StoreFeed:
    try:
        base = normalize_public_url(base_url).rstrip("/")
        storefront = normalize_public_url(storefront_url).rstrip("/") if storefront_url else ""
    except FetchError as exc:
        raise IntegrationError(422, f"{exc.message}.") from exc
    regions = _medusa_get(transport, f"{base}/store/regions", key).get("regions") or []
    region = regions[0] if regions else {}
    currency = str(region.get("currency_code") or "").upper()[:3]
    products: list[dict] = []
    offset = 0
    while len(products) < limit:
        params = {"limit": min(MEDUSA_PAGE, limit), "offset": offset, "fields": "*variants.calculated_price"}
        if region.get("id"):
            params["region_id"] = region["id"]
        body = _medusa_get(transport, f"{base}/store/products", key, params)
        page = [p for p in body.get("products") or [] if isinstance(p, dict)]
        products.extend(x for x in (_medusa_product(p, storefront, currency) for p in page) if x)
        offset += len(page)
        if not page or offset >= int(body.get("count") or 0):
            break
    host = urlparse(storefront or base).hostname or base
    return StoreFeed(PROVIDER_MEDUSA, storefront or base, host, currency, products[:limit])


def import_medusa(session: Any, scope: Scope, *, base_url: str, publishable_key: str, storefront_url: str = "",
                  limit: int = 50, transport: Any = None, save: bool = True) -> dict:
    scope.require_manage()
    key = (publishable_key or "").strip()
    if not 8 <= len(key) <= 300 or any(ch.isspace() for ch in key):
        raise IntegrationError(422, "Paste the Medusa publishable API key (starts with pk_).")
    feed = fetch_medusa(transport or PinnedTransport(), base_url, key, storefront_url, _limit(limit))
    if save:
        _save_credential(session, scope, PROVIDER_MEDUSA, key, urlparse(feed.origin).hostname or "",
                         {"base_url": base_url.strip(), "storefront_url": storefront_url.strip()})
    return _record(session, scope, feed, store_url=feed.origin, limit=_limit(limit), mode="store_api")


# --------------------------------------------------------------------------- CSV
_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "sku", "product_id", "stok_kodu", "urun_kodu", "barkod", "handle"),
    "title": ("title", "name", "product_name", "product_title", "urun_adi", "urun_ismi", "baslik", "ad", "isim"),
    "description": ("description", "body", "body_html", "aciklama", "urun_aciklamasi"),
    "price": ("price", "fiyat", "satis_fiyati", "regular_price", "list_price"),
    "sale": ("sale_price", "indirimli_fiyat", "discounted_price", "special_price", "kampanyali_fiyat"),
    "compare": ("compare_at_price", "original_price", "liste_fiyati", "eski_fiyat"),
    "currency": ("currency", "para_birimi", "doviz", "kur"),
    "url": ("url", "link", "product_url", "urun_linki", "urun_url"),
    "image": ("image", "image_url", "images", "image_link", "image_src", "gorsel", "gorsel_url", "resim",
              "resim_url", "fotograf"),
    "tags": ("tags", "category", "categories", "kategori", "etiketler", "etiket"),
}
_SYMBOLS = (("₺", "TRY"), (" TL", "TRY"), ("TL", "TRY"), ("€", "EUR"), ("£", "GBP"), ("$", "USD"))


def _norm_header(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().replace("ı", "i")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _columns(header: list[str]) -> dict[str, int]:
    normalized = [_norm_header(h) for h in header]
    found: dict[str, int] = {}
    for field, names in _ALIASES.items():
        for name in names:
            if name in normalized:
                found[field] = normalized.index(name)
                break
    return found


def _currency(raw_price: str, explicit: str, default: str) -> str:
    code = explicit.strip().upper()
    if code in ("TL", "₺"):
        return "TRY"
    if re.fullmatch(r"[A-Z]{3}", code):
        return code
    for symbol, cur in _SYMBOLS:
        if symbol in raw_price:
            return cur
    return default


def _split(value: str) -> list[str]:
    return [p for p in re.split(r"[|;,\s]+", value or "") if p]


def parse_csv(text: str, *, default_currency: str = "USD", limit: int = MAX_PRODUCTS_PER_IMPORT) -> list[dict]:
    body = (text or "").lstrip("﻿")
    if not body.strip():
        raise IntegrationError(422, "The CSV is empty.")
    first = body.splitlines()[0]
    delimiter = max((",", ";", "\t", "|"), key=first.count)
    reader = csv.reader(io.StringIO(body), delimiter=delimiter)
    header = next(reader, [])
    cols = _columns(header)
    if "title" not in cols:
        raise IntegrationError(422, "The CSV needs a product name column (title, name or Ürün Adı).")

    def cell(row: list[str], field: str) -> str:
        idx = cols.get(field)
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    out: list[dict] = []
    seen: set[str] = set()
    for row in reader:
        title = clean_text(cell(row, "title"), 500)
        if not title:
            continue
        raw_price, raw_sale = cell(row, "price"), cell(row, "sale")
        currency = _currency(raw_sale or raw_price, cell(row, "currency"), default_currency.upper()[:3])
        listed = parsing.major_to_minor(raw_price, currency) if parse_price(raw_price) else None
        sale = parsing.major_to_minor(raw_sale, currency) if parse_price(raw_sale) else None
        explicit = parsing.major_to_minor(cell(row, "compare"), currency) if parse_price(cell(row, "compare")) else None
        price = sale or listed
        compare = explicit or (listed if sale else None)
        url = cell(row, "url")
        url = url if url.startswith(("http://", "https://")) else ""
        external = (cell(row, "id") or url or title)[:128]
        if external in seen:
            continue
        seen.add(external)
        out.append({
            "external_id": external, "title": title,
            "description": clean_text(cell(row, "description"), parsing.MAX_DESCRIPTION),
            "price_minor": price, "compare_at_minor": compare if compare and price and compare > price else None,
            "currency": currency, "url": url[:2000], "image_urls": parsing._images(_split(cell(row, "image"))),
            "tags": parsing._tags(re.split(r"[|;,]", cell(row, "tags"))), "raw": {"source": "csv"},
        })
        if len(out) >= limit:
            break
    return out


Fetcher = Callable[..., Any]


def import_csv(session: Any, scope: Scope, *, text: str | None = None, url: str | None = None,
               store_name: str = "", default_currency: str = "USD", limit: int = MAX_PRODUCTS_PER_IMPORT,
               fetch: Fetcher | None = None) -> dict:
    scope.require_manage()
    source = ""
    if text and text.strip():
        if len(text.encode("utf-8")) > CSV_MAX_BYTES:
            raise IntegrationError(413, "The CSV is larger than 2 MB.")
        body = text
    elif url and url.strip():
        from app.domains.adstudio.fetch import safe_get

        try:
            result = (fetch or safe_get)(url.strip(), max_bytes=CSV_MAX_BYTES, accept="text/csv,text/plain,*/*;q=0.5")
        except FetchError as exc:
            raise IntegrationError(exc.status_code, exc.message) from exc
        body, source = result.text(), url.strip()
    else:
        raise IntegrationError(422, "Paste CSV text or a link to a CSV file.")
    rows = parse_csv(body, default_currency=default_currency, limit=_limit(limit))
    origin = source or "csv://upload"
    feed = StoreFeed(PROVIDER_CSV, origin, (store_name or urlparse(source).hostname or "CSV import")[:200],
                     next((r["currency"] for r in rows if r["currency"]), default_currency), rows)
    return _record(session, scope, feed, store_url=origin, limit=_limit(limit), mode="csv_url" if source else "csv")


# --------------------------------------------------------------------------- sources + resync
def list_sources(session: Any, scope: Scope) -> list[dict]:
    from sqlalchemy import select

    rows = session.execute(select(IntegrationConnection).where(
        IntegrationConnection.owner_scope == scope.owner_scope,
        IntegrationConnection.kind == KIND_PRODUCT_SOURCE)).scalars()
    return [{"provider": r.provider, "name": r.display_name, "token_hint": r.token_hint,
             "connected_at": r.connected_at.isoformat() if r.connected_at else None} for r in rows]


def resync(session: Any, scope: Scope, provider: str, *, limit: int = 50, transport: Any = None) -> dict:
    from sqlalchemy import select

    from app.services import crypto_tokens

    scope.require_manage()
    row = session.execute(select(IntegrationConnection).where(
        IntegrationConnection.owner_scope == scope.owner_scope, IntegrationConnection.provider == provider,
        IntegrationConnection.kind == KIND_PRODUCT_SOURCE)).scalar_one_or_none()
    if row is None:
        raise IntegrationError(404, "This product source is not connected.")
    secret = crypto_tokens.decrypt(row.access_token_enc)
    meta = dict(row.meta or {})
    if provider == PROVIDER_SHOPIFY:
        return import_shopify_admin(session, scope, shop=meta.get("shop", ""), token=secret, limit=limit,
                                    transport=transport, save=False)
    if provider == PROVIDER_MEDUSA:
        return import_medusa(session, scope, base_url=meta.get("base_url", ""), publishable_key=secret,
                             storefront_url=meta.get("storefront_url", ""), limit=limit, transport=transport,
                             save=False)
    raise IntegrationError(400, "This source cannot be re-synced.")


def remove_source(session: Any, scope: Scope, provider: str) -> bool:
    from sqlalchemy import select

    scope.require_manage()
    row = session.execute(select(IntegrationConnection).where(
        IntegrationConnection.owner_scope == scope.owner_scope, IntegrationConnection.provider == provider,
        IntegrationConnection.kind == KIND_PRODUCT_SOURCE)).scalar_one_or_none()
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


__all__ = [
    "PinnedTransport", "fetch_medusa", "fetch_shopify_admin", "import_csv", "import_medusa", "import_shopify_admin",
    "list_sources", "parse_csv", "remove_source", "resync", "shop_domain",
]
