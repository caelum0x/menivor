"""Product sources: Shopify Admin API token, Medusa Store API, CSV text / CSV URL (Shopier exports).

Imports land in the existing ``store_catalog_*`` tables so Ad Studio (URL to Video / Image Ad) uses them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domains.adstudio.catalog_models import StoreCatalogImport, StoreCatalogProduct
from app.domains.adstudio.fetch import FetchResult
from app.domains.adstudio.store_catalog import service as catalog_service
from app.domains.integrations import product_sources as ps
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import IntegrationConnection
from app.domains.integrations.scope import resolve
from app.services import crypto_tokens
from tests.reelforge._integrations_fakes import FakeTransport, Resp, add_user, add_workspace, make_db

SHOP = "oxhan-test.myshopify.com"
ADMIN = f"https://{SHOP}/admin/api/2025-10"
MEDUSA = "https://api.oxhan.example"


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-integrations-key")
    monkeypatch.delenv("SHOPIFY_ADMIN_API_VERSION", raising=False)
    return make_db()


@pytest.fixture()
def owner_scope(db):
    owner = add_user(db)
    ws = add_workspace(db, owner)
    with db.scope() as s:
        return resolve(s, owner, workspace_id=ws)


def _products(db):
    with db.scope() as s:
        return s.execute(select(StoreCatalogProduct).order_by(StoreCatalogProduct.title)).scalars().all()


# --------------------------------------------------------------------- Shopify
def _shopify_transport(second_page=True):
    t = FakeTransport()
    t.add("GET", f"{ADMIN}/shop.json", Resp(200, {"shop": {"name": "Oxhan", "currency": "TRY",
                                                            "domain": "oxhan.example"}}))
    first = Resp(200, {"products": [
        {"id": 1, "title": "Silk Scarf", "body_html": "<p>Hand made</p>", "handle": "silk-scarf",
         "tags": "silk, scarf", "vendor": "Oxhan", "status": "active",
         "variants": [{"price": "1299.90", "compare_at_price": "1599.90"}],
         "images": [{"src": "https://cdn.shopify.com/a.jpg"}]}]},
        headers={"Link": f'<{ADMIN}/products.json?limit=250&page_info=abc>; rel="next"'} if second_page else {})
    t.add("GET", f"{ADMIN}/products.json?limit", first)
    t.add("GET", f"{ADMIN}/products.json?limit=250&page_info=abc", Resp(200, {"products": [
        {"id": 2, "title": "Wool Shawl", "handle": "wool-shawl", "tags": "", "variants": [{"price": "899"}],
         "images": []}]}))
    return t


def test_shopify_admin_import_paginates_and_stores_token_encrypted(db, owner_scope):
    t = _shopify_transport()
    with db.scope() as s:
        out = ps.import_shopify_admin(s, owner_scope, shop="oxhan-test", token="shpat_secret_token_123",
                                      limit=50, transport=t)
    assert out["provider"] == "shopify" and out["product_count"] == 2 and out["currency"] == "TRY"
    assert t.calls[0]["headers"]["X-Shopify-Access-Token"] == "shpat_secret_token_123"
    scarf = next(p for p in _products(db) if p.title == "Silk Scarf")
    assert scarf.price_minor == 129990 and scarf.compare_at_minor == 159990 and scarf.currency == "TRY"
    assert scarf.url == "https://oxhan.example/products/silk-scarf" and scarf.image_urls == ["https://cdn.shopify.com/a.jpg"]
    with db.scope() as s:
        conn = s.execute(select(IntegrationConnection).where(IntegrationConnection.provider == "shopify")).scalar_one()
        assert conn.kind == "product_source" and conn.external_id == SHOP
        assert crypto_tokens.decrypt(conn.access_token_enc) == "shpat_secret_token_123"
        row = s.execute(select(StoreCatalogImport)).scalar_one()
        assert row.workspace_id == owner_scope.workspace_id and row.options["mode"] == "admin_api"
    # The existing Ad Studio catalog reads it (URL to Video / Image Ad start from it).
    with db.scope() as s:
        detail = catalog_service.import_detail(s, owner_scope.user_id, out["id"])
    assert {p["title"] for p in detail["products"]} == {"Silk Scarf", "Wool Shawl"}


def test_shopify_rejects_non_myshopify_domains_and_bad_tokens(db, owner_scope):
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        ps.import_shopify_admin(s, owner_scope, shop="evil.example.com", token="shpat_x_123456", transport=FakeTransport())
    assert err.value.status_code == 422
    t = FakeTransport().add("GET", f"{ADMIN}/shop.json", Resp(401, {"errors": "[API] Invalid API key"}))
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        ps.import_shopify_admin(s, owner_scope, shop=SHOP, token="shpat_bad_123456", transport=t)
    assert err.value.status_code == 400
    with db.scope() as s:
        assert s.execute(select(IntegrationConnection)).scalars().all() == []


def test_member_cannot_add_a_product_source(db, owner_scope):
    member = add_user(db, "m@example.com")
    from app.models.db.models import WorkspaceMember

    with db.scope() as s:
        s.add(WorkspaceMember(workspace_id=owner_scope.workspace_id, user_id=member, role="member"))
    with db.scope() as s:
        scope = resolve(s, member, workspace_id=owner_scope.workspace_id)
        with pytest.raises(IntegrationError) as err:
            ps.import_csv(s, scope, text="title,price\nA,1")
    assert err.value.status_code == 403


# ---------------------------------------------------------------------- Medusa
def test_medusa_store_api_import(db, owner_scope):
    t = FakeTransport()
    t.add("GET", f"{MEDUSA}/store/regions", Resp(200, {"regions": [{"id": "reg_tr", "currency_code": "try"}]}))
    t.add("GET", f"{MEDUSA}/store/products", Resp(200, {"products": [
        {"id": "prod_1", "title": "Linen Shirt", "description": "Breathable", "handle": "linen-shirt",
         "thumbnail": "https://cdn.oxhan.example/t.jpg", "images": [{"url": "https://cdn.oxhan.example/1.jpg"}],
         "tags": [{"value": "summer"}],
         "variants": [{"calculated_price": {"calculated_amount": 750, "original_amount": 900,
                                            "currency_code": "try"}}]},
    ], "count": 1, "offset": 0, "limit": 50}))
    with db.scope() as s:
        out = ps.import_medusa(s, owner_scope, base_url=MEDUSA, publishable_key="pk_live_publishable_123",
                               storefront_url="https://oxhan.example/tr", limit=50, transport=t)
    assert out["provider"] == "medusa" and out["product_count"] == 1
    call = t.find("GET", f"{MEDUSA}/store/products")[0]
    assert call["headers"]["x-publishable-api-key"] == "pk_live_publishable_123"
    assert call["params"]["region_id"] == "reg_tr" and "calculated_price" in call["params"]["fields"]
    shirt = _products(db)[0]
    assert shirt.price_minor == 75000 and shirt.compare_at_minor == 90000 and shirt.currency == "TRY"
    assert shirt.url == "https://oxhan.example/tr/products/linen-shirt"
    assert shirt.image_urls[0] == "https://cdn.oxhan.example/t.jpg" and shirt.tags == ["summer"]


def test_medusa_refuses_private_hosts(db, owner_scope):
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        ps.import_medusa(s, owner_scope, base_url="http://127.0.0.1:9000", publishable_key="pk_123456789",
                         transport=FakeTransport())
    assert err.value.status_code == 422


# ------------------------------------------------------------------------- CSV
SHOPIER_CSV = (
    "Ürün Adı;Fiyat;İndirimli Fiyat;Görsel;Ürün Linki;Açıklama;Stok Kodu\n"
    "Keten Gömlek;1.299,90 TL;999,90 TL;https://cdn.shopier.com/a.jpg|https://cdn.shopier.com/b.jpg;"
    "https://www.shopier.com/123;Yazlık;SKU-1\n"
    "İpek Eşarp;750 TL;;https://cdn.shopier.com/c.jpg;https://www.shopier.com/456;;SKU-2\n"
    ";;;;;;\n"
)


def test_parse_csv_handles_turkish_shopier_headers():
    rows = ps.parse_csv(SHOPIER_CSV, default_currency="USD")
    assert [r["external_id"] for r in rows] == ["SKU-1", "SKU-2"]
    shirt = rows[0]
    assert shirt["title"] == "Keten Gömlek" and shirt["currency"] == "TRY"
    assert shirt["price_minor"] == 99990 and shirt["compare_at_minor"] == 129990
    assert shirt["image_urls"] == ["https://cdn.shopier.com/a.jpg", "https://cdn.shopier.com/b.jpg"]
    assert rows[1]["price_minor"] == 75000 and rows[1]["compare_at_minor"] is None


def test_parse_csv_english_headers_and_errors():
    rows = ps.parse_csv("title,price,currency,url,image\nMug,12.50,USD,https://shop.example/mug,"
                        "https://shop.example/mug.jpg\n", default_currency="USD")
    assert rows[0]["price_minor"] == 1250 and rows[0]["url"] == "https://shop.example/mug"
    with pytest.raises(IntegrationError):
        ps.parse_csv("foo,bar\n1,2\n", default_currency="USD")
    with pytest.raises(IntegrationError):
        ps.parse_csv("", default_currency="USD")


def test_csv_text_and_url_imports(db, owner_scope):
    with db.scope() as s:
        out = ps.import_csv(s, owner_scope, text=SHOPIER_CSV, store_name="Shopier")
    assert out["provider"] == "csv" and out["product_count"] == 2

    seen = []

    def fake_fetch(url, **kwargs):
        seen.append(url)
        return FetchResult(url=url, status=200, content_type="text/csv",
                           body="name,price\nCandle,5\n".encode("utf-8"))

    with db.scope() as s:
        out2 = ps.import_csv(s, owner_scope, url="https://shop.example/feed.csv", fetch=fake_fetch)
    assert out2["product_count"] == 1 and seen == ["https://shop.example/feed.csv"]
    with db.scope() as s, pytest.raises(IntegrationError):
        ps.import_csv(s, owner_scope)
