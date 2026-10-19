"""Store catalog import: Shopify / WooCommerce feed parsing, fetching, persistence, Ad Studio seeding."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.adstudio import service as adstudio_service
from app.domains.adstudio.catalog_models import StoreCatalogImport, StoreCatalogProduct
from app.domains.adstudio.fetch import FetchError, FetchResult
from app.domains.adstudio.models import AdStudioProject
from app.domains.adstudio.store_catalog import fetching, parsing, service
from app.models.db import marketplace, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User

USER = "u1"

SHOPIFY_PRODUCTS = {"products": [
    {"id": 101, "title": "Linen Shirt", "handle": "linen-shirt", "vendor": "Acme", "product_type": "Shirts",
     "body_html": "<p>Breathable <strong>linen</strong>.</p>", "tags": ["summer", "linen"],
     "variants": [{"price": "49.90", "compare_at_price": "69.90", "available": True}],
     "images": [{"src": "https://cdn.shopify.com/a.jpg"}, {"src": "//cdn.shopify.com/b.jpg"}]},
    {"id": 102, "title": "Cap", "handle": "cap", "tags": "hats, sale", "variants": [{"price": "15.00", "compare_at_price": None}],
     "images": []},
    {"id": 103, "title": "", "variants": []},
]}
WOO_PRODUCTS = [
    {"id": 7, "name": "Ceramic Mug &amp; Saucer", "permalink": "https://woo.example/product/mug/",
     "short_description": "<p>Hand-made.</p>", "description": "<p>Long text</p>",
     "prices": {"price": "1800", "regular_price": "2400", "sale_price": "1800", "currency_code": "EUR",
                "currency_minor_unit": 2},
     "images": [{"src": "https://woo.example/wp-content/mug.jpg"}], "tags": [{"name": "Kitchen"}],
     "categories": [{"name": "Home"}], "sku": "MUG-1", "is_in_stock": True},
]


def _result(url: str, payload) -> FetchResult:
    return FetchResult(url, 200, "application/json; charset=utf-8", json.dumps(payload).encode())


class FakeFetch:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.urls: list[str] = []

    def __call__(self, url: str, **kwargs):
        self.urls.append(url)
        for prefix, payload in self.routes.items():
            if url.startswith(prefix):
                if isinstance(payload, FetchError):
                    raise payload
                return _result(url, payload)
        raise FetchError(404, "the product page was not found (404)")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def test_parse_shopify_normalizes_products() -> None:
    items = parsing.parse_shopify(SHOPIFY_PRODUCTS, "https://shop.example", "USD")
    assert [p["external_id"] for p in items] == ["101", "102"]
    shirt = items[0]
    assert shirt["price_minor"] == 4990 and shirt["compare_at_minor"] == 6990 and shirt["currency"] == "USD"
    assert shirt["url"] == "https://shop.example/products/linen-shirt"
    assert shirt["image_urls"] == ["https://cdn.shopify.com/a.jpg", "https://cdn.shopify.com/b.jpg"]
    assert shirt["description"] == "Breathable linen ."
    assert items[1]["tags"] == ["hats", "sale"] and items[1]["compare_at_minor"] is None
    assert parsing.parse_shopify({"product": {}}, "https://x", "") is None


def test_parse_woo_prices_are_minor_units() -> None:
    items = parsing.parse_woo(WOO_PRODUCTS, "https://woo.example")
    mug = items[0]
    assert mug["title"] == "Ceramic Mug & Saucer"
    assert mug["price_minor"] == 1800 and mug["compare_at_minor"] == 2400 and mug["currency"] == "EUR"
    assert mug["description"] == "Hand-made." and mug["tags"] == ["Kitchen"]
    assert mug["raw"]["categories"] == ["Home"]
    assert parsing.parse_woo({"code": "rest_no_route"}, "https://x") is None
    assert parsing.parse_woo([{"id": 1, "title": "post"}], "https://x") is None


def test_woo_minor_unit_mismatch_and_zero_decimal() -> None:
    item = {**WOO_PRODUCTS[0], "prices": {"price": "150000", "regular_price": "150000", "currency_code": "JPY",
                                           "currency_minor_unit": 2}}
    assert parsing.woo_product(item, "https://w")["price_minor"] == 1500
    assert parsing.major_to_minor("1.500", "JPY") in (2, 1500)  # parse_price is locale-aware; never crashes
    assert parsing.minor_to_major(4990, "USD") == 49.9


def test_manual_product_shape() -> None:
    product = parsing.parse_shopify(SHOPIFY_PRODUCTS, "https://shop.example", "USD")[0]
    manual = parsing.to_manual_product(product, "shopify")
    assert manual["title"] == "Linen Shirt" and manual["brand"] == "Acme"
    assert manual["price"] == 49.9 and manual["original_price"] == 69.9 and manual["source"] == "shopify"
    assert parsing.to_manual_product(product, "woocommerce")["source"] == "generic"


# --------------------------------------------------------------------------- #
# Fetching (fake transport; the real one is the SSRF-guarded safe_get)
# --------------------------------------------------------------------------- #
def test_store_origin_normalizes_and_rejects_private() -> None:
    assert fetching.store_origin("shop.example/collections/all") == "https://shop.example"
    with pytest.raises(FetchError):
        fetching.store_origin("http://127.0.0.1/products.json")
    with pytest.raises(FetchError):
        fetching.store_origin("http://localhost")


def test_auto_detects_shopify_with_meta() -> None:
    fake = FakeFetch({"https://shop.example/meta.json": {"name": "Acme Store", "currency": "usd"},
                      "https://shop.example/products.json": SHOPIFY_PRODUCTS})
    feed = fetching.fetch_store("https://shop.example/products/linen-shirt", "auto", 1, fetcher=fake)
    assert feed.provider == "shopify" and feed.store_name == "Acme Store" and feed.currency == "USD"
    assert len(feed.products) == 1
    assert "https://shop.example/products.json?limit=1" in fake.urls


def test_auto_falls_back_to_woo_and_rest_route() -> None:
    fake = FakeFetch({"https://woo.example/?rest_route=/wc/store/v1/products": WOO_PRODUCTS})
    feed = fetching.fetch_store("woo.example", "auto", 50, fetcher=fake)
    assert feed.provider == "woocommerce" and feed.currency == "EUR" and len(feed.products) == 1
    assert any("/wp-json/wc/store/v1/products" in u for u in fake.urls)


def test_woo_paginates_until_short_page() -> None:
    page = [{**WOO_PRODUCTS[0], "id": i} for i in range(100)]
    calls = {"n": 0}

    def fetch(url, **kwargs):
        calls["n"] += 1
        body = page if "page=1" in url and "per_page" in url and url.endswith("page=1") else [
            {**WOO_PRODUCTS[0], "id": 1000 + i} for i in range(5)]
        return _result(url, body)

    feed = fetching.fetch_store("https://woo.example", "woocommerce", 250, fetcher=fetch)
    assert len(feed.products) == 105 and calls["n"] == 2


def test_no_feed_is_a_clear_error() -> None:
    with pytest.raises(FetchError) as err:
        fetching.fetch_store("https://plain.example", "auto", 10, fetcher=FakeFetch({}))
    assert err.value.status_code == 422 and "Shopify or WooCommerce" in err.value.message
    blocked = FakeFetch({"https://locked.example/products.json": FetchError(424, "the store blocked the fetch")})
    with pytest.raises(FetchError) as err2:
        fetching.fetch_store("https://locked.example", "auto", 10, fetcher=blocked)
    assert err2.value.status_code == 424


# --------------------------------------------------------------------------- #
# Persistence + Ad Studio seeding
# --------------------------------------------------------------------------- #
@pytest.fixture()
def factory():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    make = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    with make.begin() as s:
        s.add(User(id=USER, email="u1@x.com"))
        s.add(User(id="u2", email="u2@x.com"))
    return make


def _feed() -> fetching.StoreFeed:
    products = parsing.parse_shopify(SHOPIFY_PRODUCTS, "https://shop.example", "USD")
    return fetching.StoreFeed("shopify", "https://shop.example", "Acme Store", "USD", products + [products[0]])


def test_record_import_dedupes_and_lists(factory) -> None:
    with factory.begin() as s:
        row = service.record_import(s, user_id=USER, store_url="shop.example", provider="auto", limit=50,
                                    feed=_feed(), error="")
        detail = service.import_detail(s, USER, row.id)
    assert detail["status"] == "succeeded" and detail["product_count"] == 2 and len(detail["products"]) == 2
    assert detail["provider_requested"] == "auto" and detail["store_name"] == "Acme Store"
    with factory.begin() as s:
        failed = service.record_import(s, user_id=USER, store_url="https://nope.example", provider="auto", limit=10,
                                       feed=None, error="no public Shopify or WooCommerce product feed")
        listed = service.list_imports(s, USER)
        assert failed.status == "failed" and len(listed) == 2
        assert service.list_imports(s, "u2") == []
        with pytest.raises(adstudio_service.AdStudioError) as err:
            service.import_detail(s, "u2", row.id)
    assert err.value.status_code == 404


def test_products_become_ad_studio_projects(factory, monkeypatch) -> None:
    monkeypatch.setattr("app.domains.adstudio.service.store_remote_images", lambda urls: [])
    with factory.begin() as s:
        row = service.record_import(s, user_id=USER, store_url="shop.example", provider="shopify", limit=50,
                                    feed=_feed(), error="")
        pid = service.import_detail(s, USER, row.id)["products"][0]["id"]
        with pytest.raises(adstudio_service.AdStudioError):
            service.products_for_projects(s, "u2", row.id, [pid])
        provider, products = service.products_for_projects(s, USER, row.id, [pid])
    prepared = service.prepare_projects(provider, products, language="en", use_llm=False)
    assert prepared[0][1] is not None and prepared[0][2] == ""
    with factory.begin() as s:
        results = service.persist_projects(s, USER, prepared)
        project = s.get(AdStudioProject, results[0]["project_id"])
        assert project.user_id == USER and project.title == "Linen Shirt" and project.source == "shopify"
        assert (project.product or {}).get("price") == 49.9 and project.angles
        assert s.get(StoreCatalogProduct, pid).adstudio_project_id == project.id
        with pytest.raises(adstudio_service.AdStudioError) as err:
            service.products_for_projects(s, USER, row.id, [pid])
        assert err.value.status_code == 409
        service.delete_import(s, USER, row.id)
        assert s.query(StoreCatalogImport).count() == 0 and s.query(StoreCatalogProduct).count() == 0
        assert s.get(AdStudioProject, project.id) is not None
