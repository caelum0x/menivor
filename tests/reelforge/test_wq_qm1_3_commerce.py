"""Wave Q QM1.3: creator commerce end to end (U28, U29, U31, U38).

1. Studio prices: the existing SVOD offer stays, and a creator sets a per-title
   buy and a rental with two fields each (price, and rental hours).
2. Coupons are the creator's own Dodo discounts (percent or amount, plus
   expiry). Mint's seller contract (Wave P 5.5) has no discount type, so a
   small seller-client interface and a fake stand in. Menivor stores only the
   code reference, never the discount amount.
3. The watch app opens the creator's hosted checkout and unlocks on return.
   There is no in-app store purchase for web-merchant content.
4. The dashboard shows gross sales per title from grant events. The ledger
   gains no column that holds buyer funds.
5. Purchase, refund, rental and renewal run against a fake processor only.
   The live Dodo test purchase is owner-only and was not run.
"""

from __future__ import annotations

import ast
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.domains.ott.models import OttChannel, OttTitle
from app.domains.ott_access import limits, router as access_router, tokens
from app.domains.ott_analytics import router as analytics_router
from app.domains.ott_analytics import service as analytics
from app.domains.ott_commerce import entitlements, products, router as commerce_router, webhooks
from app.domains.ott_commerce.models import OttCoupon, OttEntitlement, OttOffer
from app.domains.ott_commerce.processor import FakeProcessor, LiveProcessorRefused
from app.domains.ott_viewers import auth, router as viewers_router, session as viewer_session
from app.services.billing import standard_webhooks

from tests.reelforge import _wp_p3_ott as h

WHSEC = "whsec_" + "bWludC1zZWxsZXItd2ViaG9vay1zZWNyZXQtZm9yLW1lbml2b3I="
REPO = Path(__file__).resolve().parents[2]
WATCH = REPO / "apps/watch/src/checkout"
FUND_NAMES = {"amount", "amount_cents", "balance", "payout", "fee", "net", "funds", "transfer"}


class FakeMint:
    """Mint's seller API as contract 5.5 describes it. No discount route."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.connected = True

    def __call__(self, method, url, body, headers):
        path = url.split("https://mint.example", 1)[1]
        self.calls.append((method, path, body))
        if "/discounts" in path or (body or {}).get("discount"):
            return 404, {"error": {"code": "unknown", "message": "no discount on contract 5.5"}}
        if path.endswith("/connect"):
            return 201, {"connect_url": f"https://mint.example/mint/connect/{'a' * 64}", "expires_in": 900}
        if method == "GET" and "/sellers/" in path and path.count("/") == 4:
            return 200, {"seller": path.rsplit("/", 1)[-1], "connected": self.connected,
                         "provider": "dodo", "mode": "test"}
        if path.endswith("/products"):
            return 201, {"product": body, "created": True}
        if path.endswith("/checkout-sessions"):
            return 201, {"url": "https://test.checkout.dodopayments.com/buy/cs_1", "id": "cs_1"}
        return 404, {}


@pytest.fixture()
def env(monkeypatch):
    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (viewers_router, access_router, commerce_router, analytics_router))
    h.enable(monkeypatch, "viewers", "storefront", "access", "commerce", "analytics")
    monkeypatch.setenv(auth.SECRET_ENV, h.AUTH_SECRET)
    monkeypatch.setenv(viewer_session.SECRET_ENV, h.VIEWER_SECRET)
    monkeypatch.setenv(tokens.SECRET_ENV, "x" * 40)
    monkeypatch.setenv("MINT_URL", "https://mint.example")
    monkeypatch.setenv(products.KEY_ENV, "menivor-seller-key-0123456789abcdef")
    monkeypatch.setenv(webhooks.SECRET_ENV, WHSEC)
    monkeypatch.setenv(commerce_router.TERMS_ENV, "1")
    monkeypatch.setattr(limits, "_STORE", limits.MemoryStore())
    monkeypatch.setattr(viewers_router, "enforce_rate_limit", lambda *a, **k: None)
    fake = FakeMint()
    processor = FakeProcessor()
    monkeypatch.setattr(commerce_router, "mint", lambda: products.MintSellers(transport=fake))
    monkeypatch.setattr(commerce_router, "processor", lambda: processor)
    owner = h.owner(factory)
    cid, ids = h.channel(factory, owner, "maya", titles=2, access_tier="paid")
    client = h.app_client(viewers_router.router, access_router.router, commerce_router.router,
                          analytics_router.router)
    viewer = client.post("/api/v1/ott/viewers/maya/session",
                         json={"access_token": h.auth_token("sub-v", "v@example.com")}).json()["data"]
    return {"factory": factory, "client": client, "mint": fake, "processor": processor, "cid": cid,
            "ids": ids, "viewer": viewer}


OWNER = {"x-api-key": h.OWNER_KEY}


def _offer(env, **body):
    res = env["client"].post("/api/v1/ott/studio/commerce/offers", json=body, headers=OWNER)
    assert res.status_code == 200, res.text
    return res.json()["data"]


def _deliver(env, event_type, data, *, msg_id=None, secret=WHSEC):
    payload = json.dumps({"type": event_type, "data": data}).encode()
    msg_id = msg_id or data["id"]
    ts = str(int(time.time()))
    headers = {"webhook-id": msg_id, "webhook-timestamp": ts,
               "webhook-signature": "v1," + standard_webhooks.sign(secret, msg_id, ts, payload),
               "content-type": "application/json"}
    return env["client"].post("/api/v1/ott/webhooks/mint", content=payload, headers=headers)


def _event(env, eid, sku, *, kind="granted", reason=None, occurred=None, expires=None):
    return {"id": eid, "seller": products.seller_id(env["cid"]), "kind": kind, "reason": reason,
            "buyer_ref": env["viewer"]["viewer"]["id"], "sku": sku, "provider": "dodo",
            "provider_event_id": f"pay_{eid}", "occurred_at_ms": occurred or int(time.time() * 1000),
            "expires_at_ms": expires}


def _play(env, title_id):
    return env["client"].post(f"/api/v1/ott/play/{title_id}", json={},
                              headers={"x-ott-viewer": env["viewer"]["session"]})


def test_studio_sets_buy_and_rent_prices(env):
    """U28 stays the SVOD flow; U29 is two fields for a buy and two for a rental."""
    svod = _offer(env, kind="svod", name="Members", price_cents=500, interval="month")
    title = env["ids"][0]
    bought = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=title)
    rented = _offer(env, kind="rental", name="Rent the film", price_cents=299, title_id=title, rental_hours=48)
    assert svod["kind"] == "svod" and svod["interval"] == "month" and svod["price_cents"] == 500
    assert {k for k in ("price_cents", "title_id") if bought[k]} == {"price_cents", "title_id"}
    assert rented["price_cents"] == 299 and rented["rental_hours"] == 48 and rented["title_id"] == title
    products_sent = [c[2] for c in env["mint"].calls if c[1].endswith("/products")]
    assert products_sent[0]["sku"] == "svod.month"
    assert products_sent[1]["sku"] == f"tvod.{title}"
    assert products_sent[2]["sku"] == f"rental.{title}"
    again = _offer(env, kind="tvod", name="Own the film", price_cents=1299, title_id=title)
    assert again["id"] == bought["id"] and again["price_cents"] == 1299


def test_coupons_are_the_creators_dodo_discounts(env):
    """Percent or amount, plus expiry. Stored as a code reference only."""
    percent = env["client"].post("/api/v1/ott/studio/commerce/coupons", headers=OWNER, json={
        "code": "save20", "kind": "percent", "percent": 20,
        "expires_at": "2026-12-31T00:00:00Z"})
    assert percent.status_code == 200, percent.text
    amount = env["client"].post("/api/v1/ott/studio/commerce/coupons", headers=OWNER, json={
        "code": "fiveoff", "kind": "amount", "amount_cents": 500, "currency": "USD",
        "expires_at": "2026-11-01T00:00:00Z"})
    assert amount.status_code == 200, amount.text
    listed = env["client"].get("/api/v1/ott/studio/commerce/coupons", headers=OWNER).json()["data"]["coupons"]
    assert [c["code"] for c in listed] == ["FIVEOFF", "SAVE20"]
    for row in listed:
        assert set(row) <= {"code", "expires_at", "active"}
        assert "percent" not in row and "amount_cents" not in row
    created = env["processor"].created
    assert created[0]["code"] == "SAVE20" and created[0]["type"] == "percentage" and created[0]["amount"] == 2000
    assert created[1]["type"] == "flat" and created[1]["amount"] == 500
    assert all(c["expires_at"] for c in created)
    assert not any("/discounts" in path or (body or {}).get("discount") for _, path, body in env["mint"].calls)
    with env["factory"]() as s:
        columns = {c.name for c in OttCoupon.__table__.columns}
        assert columns <= {"id", "channel_id", "code", "expires_at", "active", "created_at",
                           "processor_discount_id"}
        assert s.execute(select(func.count(OttCoupon.id))).scalar_one() == 2
    expired = env["client"].post("/api/v1/ott/studio/commerce/coupons", headers=OWNER, json={
        "code": "old", "kind": "percent", "percent": 10, "expires_at": "2020-01-01T00:00:00Z"})
    assert expired.status_code == 400
    both = env["client"].post("/api/v1/ott/studio/commerce/coupons", headers=OWNER, json={
        "code": "both", "kind": "percent", "percent": 10, "amount_cents": 100,
        "expires_at": "2026-12-31T00:00:00Z"})
    assert both.status_code == 400


def test_checkout_passes_only_the_coupon_code(env):
    env["client"].post("/api/v1/ott/studio/commerce/coupons", headers=OWNER, json={
        "code": "save20", "kind": "percent", "percent": 20, "expires_at": "2026-12-31T00:00:00Z"})
    offer = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    res = env["client"].post("/api/v1/ott/viewers/maya/checkout",
                             json={"offer_id": offer["id"], "coupon_code": "save20"},
                             headers={"x-ott-viewer": env["viewer"]["session"]})
    assert res.status_code == 200
    body = env["mint"].calls[-1][2]
    assert body["discount_code"] == "SAVE20"
    assert "amount" not in body and "percent" not in body
    unknown = env["client"].post("/api/v1/ott/viewers/maya/checkout",
                                 json={"offer_id": offer["id"], "coupon_code": "nope"},
                                 headers={"x-ott-viewer": env["viewer"]["session"]})
    assert unknown.status_code == 404


def test_watch_app_opens_hosted_checkout(env):
    """Return from hosted checkout unlocks; the app never buys inside a store."""
    offer = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    checkout = (WATCH / "hosted.ts").read_text()
    assert "openBrowserAsync" in checkout or "hosted checkout" in checkout
    assert "expo-in-app-purchases" not in checkout and "RevenueCat" not in checkout
    copy = (WATCH / "copy.ts").read_text()
    assert "3.1.3" in copy and "web-merchant" in copy
    returned = entitlements.return_state("https://watch.example/title?purchase=done")
    assert returned.done is True and returned.cancelled is False
    assert entitlements.return_state("https://watch.example/title").done is False
    assert _play(env, env["ids"][0]).status_code == 402
    _deliver(env, "entitlement.granted", _event(env, "ent_buy", offer["sku"]))
    unlocked = env["client"].get("/api/v1/ott/viewers/maya/entitlements",
                                 headers={"x-ott-viewer": env["viewer"]["session"]}).json()["data"]["items"]
    assert unlocked[0]["status"] == "active" and unlocked[0]["title_id"] == env["ids"][0]
    assert _play(env, env["ids"][0]).status_code == 200


def test_gross_sales_per_title_from_grant_events(env):
    first, second = env["ids"]
    own = _offer(env, kind="tvod", name="Own", price_cents=1000, title_id=first)
    rent = _offer(env, kind="rental", name="Rent", price_cents=300, title_id=first, rental_hours=48)
    other = _offer(env, kind="tvod", name="Other", price_cents=500, title_id=second)
    _deliver(env, "entitlement.granted", _event(env, "ent_a", own["sku"]))
    _deliver(env, "entitlement.granted", _event(env, "ent_b", rent["sku"]))
    _deliver(env, "entitlement.granted", _event(env, "ent_c", other["sku"]))
    _deliver(env, "entitlement.revoked", _event(env, "ent_d", other["sku"], kind="revoked", reason="refund"))
    dash = env["client"].get("/api/v1/ott/studio/analytics?days=30", headers=OWNER)
    assert dash.status_code == 200, dash.text
    sales = {row["title_id"]: row for row in dash.json()["data"]["sales"]}
    assert sales[first]["gross_cents"] == 1300 and sales[first]["grants"] == 2
    assert sales[second]["gross_cents"] == 0 and sales[second]["grants"] == 0
    assert dash.json()["data"]["sales_totals"] == {"gross_cents": 1300, "grants": 2, "currency": "USD"}
    with env["factory"]() as s:
        direct = analytics.sales_by_title(s, s.get(OttChannel, env["cid"]))
    assert {row["title_id"]: row["gross_cents"] for row in direct}[first] == 1300


def test_ledger_gains_no_fund_column(env):
    from app.models.db.marketplace import WalletLedgerEntry
    from app.models.db.models import CreditLedger

    own = _offer(env, kind="tvod", name="Own", price_cents=999, title_id=env["ids"][0])
    _deliver(env, "entitlement.granted", _event(env, "ent_1", own["sku"]))
    with env["factory"]() as s:
        assert s.execute(select(func.count()).select_from(CreditLedger)).scalar_one() == 0
        assert s.execute(select(func.count()).select_from(WalletLedgerEntry)).scalar_one() == 0
        names = {c.name for table in (OttOffer.__table__, OttEntitlement.__table__, OttCoupon.__table__)
                 for c in table.columns}
    assert not FUND_NAMES & names
    for path in (REPO / "migrations/versions").glob("*qm1_3*"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in FUND_NAMES, (path.name, node.value)


def test_fake_processor_purchase_refund_rental_and_renewal(env):
    """Item 5 against a fake. The live Dodo purchase was not run."""
    with pytest.raises(LiveProcessorRefused):
        env["processor"].purchase_live("sku")
    own = _offer(env, kind="tvod", name="Own", price_cents=999, title_id=env["ids"][0])
    rent = _offer(env, kind="rental", name="Rent", price_cents=299, title_id=env["ids"][1], rental_hours=24)
    members = _offer(env, kind="svod", name="Members", price_cents=500, interval="month")
    bought = env["processor"].purchase(own["sku"])
    assert bought["status"] == "paid" and _deliver(env, "entitlement.granted",
                                                   _event(env, bought["event_id"], own["sku"])).json()["data"]["outcome"] == "granted"
    refunded = env["processor"].refund(bought["id"])
    assert refunded["status"] == "refunded"
    assert _deliver(env, "entitlement.revoked", _event(env, refunded["event_id"], own["sku"], kind="revoked",
                                                       reason="refund")).json()["data"]["outcome"] == "revoked"
    assert _play(env, env["ids"][0]).status_code == 402
    rented = env["processor"].rent(rent["sku"], hours=24)
    granted = datetime.now(timezone.utc)
    _deliver(env, "entitlement.granted", _event(env, rented["event_id"], rent["sku"],
                                               occurred=int(granted.timestamp() * 1000)))
    with env["factory"]() as s:
        title = s.get(OttTitle, env["ids"][1])
        viewer_id = env["viewer"]["viewer"]["id"]
        assert entitlements.can_watch(s, title, viewer_id=viewer_id, at=granted + timedelta(hours=23))
        assert not entitlements.can_watch(s, title, viewer_id=viewer_id, at=granted + timedelta(hours=25))
    period = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp() * 1000)
    first = env["processor"].renew(members["sku"], expires_at_ms=period)
    second = env["processor"].renew(members["sku"], expires_at_ms=period + 86_400_000)
    assert _deliver(env, "entitlement.granted", _event(env, first["event_id"], members["sku"],
                                                       expires=period)).json()["data"]["outcome"] == "granted"
    assert _deliver(env, "entitlement.granted", _event(env, second["event_id"], members["sku"],
                                                       expires=period + 86_400_000)).json()["data"]["outcome"] == "renewed"
    with env["factory"]() as s:
        assert s.execute(select(func.count(OttEntitlement.id)).where(OttEntitlement.kind == "svod")).scalar_one() == 1
    assert env["processor"].live_calls == 0


def test_mint_discounts_send_dodo_shape_and_stay_off_until_mint_serves_them():
    """The production client: Dodo's POST /discounts shape through Mint; a 404 is an honest off state."""
    from app.domains.ott_commerce.processor import MintDiscounts, dodo_discount_body

    assert dodo_discount_body({"code": "SAVE20", "type": "percentage", "amount": 2000,
                               "expires_at": "2026-12-31T00:00:00Z"}) == {
        "code": "SAVE20", "type": "percentage", "amount": 2000, "expires_at": "2026-12-31T00:00:00Z",
        "name": "SAVE20"}
    flat = dodo_discount_body({"code": "FIVEOFF", "type": "flat", "amount": 500, "currency": "usd",
                               "expires_at": "2026-11-01T00:00:00Z"})
    assert flat["currency_options"] == [{"currency": "USD", "max_amount_possible": 500, "is_default": True}]
    with pytest.raises(ValueError):
        dodo_discount_body({"code": "X", "type": "percentage", "amount": 10_001})

    calls = []

    def served(method, url, body, headers):
        calls.append((method, url, body, headers))
        return 201, {"discount": {"code": "SAVE20"}}

    env = {"MINT_URL": "https://mint.example", products.KEY_ENV: "menivor-seller-key-0123456789abcdef"}
    client = MintDiscounts(products.MintSellers(env=env, transport=served))
    spec = {"seller": "menivor.ch_abc", "code": "SAVE20", "type": "percentage", "amount": 2000,
            "expires_at": "2026-12-31T00:00:00Z"}
    assert client.create_discount(spec) == {"code": "SAVE20", "discount_id": None}
    method, url, body, headers = calls[0]
    assert method == "POST" and url.endswith("/mint/v1/sellers/menivor.ch_abc/discounts")
    assert body["amount"] == 2000 and "seller" not in body and headers["x-api-key"]

    missing = MintDiscounts(products.MintSellers(env=env, transport=lambda *a: (404, {})))
    with pytest.raises(products.CommerceError) as off:
        missing.create_discount(spec)
    assert off.value.status_code == 503 and off.value.code == "discounts_unavailable"
    with pytest.raises(LiveProcessorRefused):
        client.purchase("tvod.t1")


def test_stopped_or_ended_coupon_is_refused_at_checkout(env):
    env["client"].post("/api/v1/ott/studio/commerce/coupons", headers=OWNER, json={
        "code": "save20", "kind": "percent", "percent": 20, "expires_at": "2026-12-31T00:00:00Z"})
    dup = env["client"].post("/api/v1/ott/studio/commerce/coupons", headers=OWNER, json={
        "code": "SAVE20", "kind": "percent", "percent": 5, "expires_at": "2026-12-31T00:00:00Z"})
    assert dup.status_code == 409
    offer = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    stopped = env["client"].post("/api/v1/ott/studio/commerce/coupons/save20/stop", headers=OWNER)
    assert stopped.status_code == 200 and stopped.json()["data"]["active"] is False
    res = env["client"].post("/api/v1/ott/viewers/maya/checkout",
                             json={"offer_id": offer["id"], "coupon_code": "SAVE20"},
                             headers={"x-ott-viewer": env["viewer"]["session"]})
    assert res.status_code == 404
    with env["factory"]() as s:
        with pytest.raises(products.CommerceError):
            products.usable_coupon(s, env["cid"], "SAVE20")
    sales = env["client"].get("/api/v1/ott/studio/commerce/sales?days=30", headers=OWNER)
    assert sales.status_code == 200 and sales.json()["data"]["sales_totals"]["grants"] == 0


def test_coupon_migration_is_additive_and_idempotent():
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = next((REPO / "migrations/versions").glob("*_f3c5e7a9b1d4_ott_coupons.py"))
    spec = importlib.util.spec_from_file_location("ott_coupons_mig", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn))
        module.op = ops
        module.upgrade()
        module.upgrade()
        columns = {c["name"] for c in inspect(conn).get_columns("ott_coupons")}
        assert columns == {"id", "channel_id", "code", "expires_at", "active", "created_at"}
        module.downgrade()
        module.downgrade()
        assert "ott_coupons" not in inspect(conn).get_table_names()


def test_gross_sales_keep_the_price_each_grant_landed_at(env):
    """QM verify: a later price change never rewrites past gross sales."""
    first = env["ids"][0]
    own = _offer(env, kind="tvod", name="Own", price_cents=1000, title_id=first)
    _deliver(env, "entitlement.granted", _event(env, "ent_old", own["sku"]))
    _offer(env, kind="tvod", name="Own", price_cents=2500, title_id=first)
    with env["factory"]() as s:
        rows = {r["title_id"]: r for r in analytics.sales_by_title(s, s.get(OttChannel, env["cid"]))}
        ent = s.execute(select(OttEntitlement)).scalars().one()
        assert ent.list_price_cents == 1000 and ent.list_currency == "USD"
    assert rows[first]["gross_cents"] == 1000 and rows[first]["currency"] == "USD"


def test_gross_sales_mark_mixed_currencies(env):
    first = env["ids"][0]
    own = _offer(env, kind="tvod", name="Own", price_cents=1000, title_id=first)
    rent = _offer(env, kind="rental", name="Rent", price_cents=300, currency="EUR", title_id=first)
    _deliver(env, "entitlement.granted", _event(env, "ent_usd", own["sku"]))
    _deliver(env, "entitlement.granted", _event(env, "ent_eur", rent["sku"]))
    with env["factory"]() as s:
        rows = {r["title_id"]: r for r in analytics.sales_by_title(s, s.get(OttChannel, env["cid"]))}
    assert rows[first]["currency"] == "mixed"
    assert rows[first]["by_currency"] == {"USD": 1000, "EUR": 300}
    assert analytics.sales_totals(list(rows.values()))["currency"] == "mixed"


def test_percent_that_rounds_to_zero_is_400_not_500(env):
    """QM verify: 0.001 percent passed the form check but rounded to 0 basis points and crashed in Dodo's body."""
    res = env["client"].post("/api/v1/ott/studio/commerce/coupons", headers=OWNER,
                             json={"code": "tiny", "kind": "percent", "percent": 0.001,
                                   "expires_at": "2026-12-31T00:00:00Z"})
    assert res.status_code == 400, res.text
    assert env["processor"].created == []


def test_price_snapshot_migration_is_additive_and_idempotent():
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    path = next((REPO / "migrations/versions").glob("*_b5e7a9c1d3f7_ott_entitlement_price_snapshot.py"))
    spec = importlib.util.spec_from_file_location("ott_price_snapshot_mig", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE ott_entitlements (id VARCHAR(32) PRIMARY KEY)"))
        ops = Operations(MigrationContext.configure(conn))
        module.op = ops
        module.upgrade()
        module.upgrade()
        columns = {c["name"] for c in inspect(conn).get_columns("ott_entitlements")}
        assert {"list_price_cents", "list_currency"} <= columns
        module.downgrade()
        module.downgrade()
        columns = {c["name"] for c in inspect(conn).get_columns("ott_entitlements")}
        assert columns == {"id"}
