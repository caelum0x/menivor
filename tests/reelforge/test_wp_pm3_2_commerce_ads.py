"""Wave P PM3.2: MV13 SVOD, TVOD and rentals with the creator as merchant; MV14 AVOD.

1. Through the Mint seller-own contract (5.5), a test purchase on a connected
   test account unlocks exactly the bought title or tier; refund or dispute
   revokes; a rental expires on time.
2. Menivor never receives or forwards viewer funds (no ledger rows; events
   carrying fund fields are refused; the package imports no ledger code).
3. House ads and creator-sold sponsor slots, skippable after 5 s, never on
   paid tiers unless the creator sets it; programmatic stays off.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import func, select

from app.domains.ott.models import OttTitle
from app.domains.ott_access import limits, router as access_router, tokens
from app.domains.ott_ads import router as ads_router, service as ads, vast
from app.domains.ott_commerce import entitlements, products, router as commerce_router, tasks, webhooks
from app.domains.ott_commerce.models import OttAd, OttEntitlement, OttOffer
from app.domains.ott_viewers import auth, router as viewers_router, session as viewer_session
from app.services.billing import standard_webhooks

from tests.reelforge import _wp_p3_ott as h

WHSEC = "whsec_" + "bWludC1zZWxsZXItd2ViaG9vay1zZWNyZXQtZm9yLW1lbml2b3I="
REPO = Path(__file__).resolve().parents[2]


class FakeMint:
    """Mint's seller API as the contract (5.5) describes it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.connected = True
        self.events: list[dict] = []

    def __call__(self, method, url, body, headers):
        assert headers["x-api-key"] == "menivor-seller-key-0123456789abcdef"
        path = url.split("https://mint.example", 1)[1]
        self.calls.append((method, path, body))
        seller = path.split("/")[4] if path.startswith("/mint/v1/sellers/") else ""
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", seller)
        if path.endswith("/connect"):
            return 201, {"connect_url": f"https://mint.example/mint/connect/{'a' * 64}", "expires_in": 900,
                         "stripe": False}
        if method == "GET" and path.endswith(seller):
            return 200, {"seller": seller, "connected": self.connected, "provider": "dodo", "mode": "test"}
        if path.endswith("/products"):
            if not self.connected:
                return 409, {"error": {"code": "not_connected", "message": "x"}}
            return 201, {"product": body, "created": True}
        if path.endswith("/checkout-sessions"):
            return 201, {"url": "https://test.checkout.dodopayments.com/buy/cs_1", "id": "cs_1"}
        if "/entitlements" in path:
            return 200, {"entitlements": self.events}
        return 404, {}


@pytest.fixture()
def env(monkeypatch):
    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (viewers_router, access_router, commerce_router, ads_router))
    h.enable(monkeypatch, "viewers", "storefront", "access", "commerce", "ads")
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
    monkeypatch.setattr(commerce_router, "mint", lambda: products.MintSellers(transport=fake))
    owner = h.owner(factory)
    cid, ids = h.channel(factory, owner, "maya", titles=3, access_tier="paid")
    with factory() as s:
        free = s.get(OttTitle, ids[2])
        free.access_tier = "free"
        s.commit()
    other_owner = h.owner(factory, "o@example.com", "other-key")
    other_cid, other_ids = h.channel(factory, other_owner, "zed", titles=1, access_tier="paid")
    client = h.app_client(viewers_router.router, access_router.router, commerce_router.router, ads_router.router)
    viewer = client.post("/api/v1/ott/viewers/maya/session",
                         json={"access_token": h.auth_token("sub-v", "v@example.com")}).json()["data"]
    return {"factory": factory, "client": client, "mint": fake, "cid": cid, "ids": ids, "viewer": viewer,
            "other": (other_cid, other_ids), "owner": owner}


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


def _event(env, eid, sku, *, kind="granted", reason=None, occurred=None, expires=None, buyer=None):
    return {"id": eid, "seller": products.seller_id(env["cid"]), "kind": kind, "reason": reason,
            "buyer_ref": buyer or env["viewer"]["viewer"]["id"], "sku": sku, "provider": "dodo",
            "provider_event_id": f"pay_{eid}", "occurred_at_ms": occurred or int(time.time() * 1000),
            "expires_at_ms": expires}


def _play(env, title_id):
    return env["client"].post(f"/api/v1/ott/play/{title_id}", json={},
                              headers={"x-ott-viewer": env["viewer"]["session"]})


# --------------------------------------------------------------------------- #
# MV13
# --------------------------------------------------------------------------- #
def test_connect_uses_mints_page_and_no_request_asks_for_a_key(env):
    res = env["client"].post("/api/v1/ott/studio/commerce/connect", headers=OWNER)
    assert res.json()["data"]["connect_url"].startswith("https://mint.example/mint/connect/")
    method, path, body = env["mint"].calls[-1]
    assert path == f"/mint/v1/sellers/menivor.ch_{env['cid']}/connect"
    assert body["return_url"].endswith("/studio-ott?connected=1")
    for model in (commerce_router.OfferCreate, commerce_router.Checkout, ads_router.AdCreate, ads_router.Settings):
        assert not [f for f in model.model_fields if re.search(r"key|secret|token|password", f)], model
    view = env["client"].get("/api/v1/ott/studio/commerce", headers=OWNER).json()["data"]
    assert view["account"] == {"connected": True, "provider": "dodo", "mode": "test"}


def test_offers_become_products_on_the_creators_account(env):
    svod = _offer(env, kind="svod", name="Members", price_cents=500, interval="month")
    tvod = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    rent = _offer(env, kind="rental", name="Rent the film", price_cents=299, title_id=env["ids"][1], rental_hours=48)
    assert [c[2] for c in env["mint"].calls if c[1].endswith("/products")] == [
        {"sku": "svod.month", "name": "Members", "price_cents": 500, "currency": "USD", "interval": "month"},
        {"sku": f"tvod.{env['ids'][0]}", "name": "Own the film", "price_cents": 999, "currency": "USD"},
        {"sku": f"rental.{env['ids'][1]}", "name": "Rent the film", "price_cents": 299, "currency": "USD"},
    ]
    assert rent["rental_hours"] == 48 and svod["interval"] == "month" and tvod["title_id"] == env["ids"][0]
    public = env["client"].get("/api/v1/ott/c/maya/offers").json()["data"]
    assert len(public["offers"]) == 3 and public["checkout_open"] is True
    other_title = env["other"][1][0]
    bad = env["client"].post("/api/v1/ott/studio/commerce/offers", headers=OWNER,
                             json={"kind": "tvod", "name": "x", "price_cents": 100, "title_id": other_title})
    assert bad.status_code == 404
    env["mint"].connected = False
    refused = env["client"].post("/api/v1/ott/studio/commerce/offers", headers=OWNER,
                                 json={"kind": "svod", "name": "Yearly", "price_cents": 5000, "interval": "year"})
    assert refused.status_code == 409 and "Connect your payment account" in refused.json()["message"]


def test_checkout_is_a_hosted_page_on_the_creators_processor(env):
    tvod = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    res = env["client"].post("/api/v1/ott/viewers/maya/checkout", json={"offer_id": tvod["id"]},
                             headers={"x-ott-viewer": env["viewer"]["session"]})
    assert res.status_code == 200 and res.json()["data"]["url"].startswith("https://test.checkout.")
    _m, path, body = env["mint"].calls[-1]
    assert path.endswith("/checkout-sessions")
    assert body["buyer_ref"] == env["viewer"]["viewer"]["id"] and body["sku"] == tvod["sku"]
    assert body["success_url"].startswith("https://") and body["success_url"].endswith("?purchase=done")
    assert env["client"].post("/api/v1/ott/viewers/maya/checkout", json={"offer_id": tvod["id"]}
                              ).status_code == 401


def test_checkout_waits_for_the_viewer_terms(env, monkeypatch):
    tvod = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    monkeypatch.delenv(commerce_router.TERMS_ENV)
    res = env["client"].post("/api/v1/ott/viewers/maya/checkout", json={"offer_id": tvod["id"]},
                             headers={"x-ott-viewer": env["viewer"]["session"]})
    assert res.status_code == 503 and res.json()["data"]["code"] == "terms_pending"


def test_a_purchase_unlocks_exactly_the_bought_title_and_a_refund_revokes(env):
    tvod = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    assert _play(env, env["ids"][0]).status_code == 402
    assert _deliver(env, "entitlement.granted", _event(env, "ent_1", tvod["sku"])).json()["data"] == {
        "outcome": "granted"}
    assert _play(env, env["ids"][0]).status_code == 200
    assert _play(env, env["ids"][1]).status_code == 402  # another paid title stays locked
    assert _deliver(env, "entitlement.granted", _event(env, "ent_1", tvod["sku"])).json()["data"]["outcome"] == \
        "duplicate"
    assert _deliver(env, "entitlement.revoked", _event(env, "ent_2", tvod["sku"], kind="revoked",
                                                       reason="refund")).json()["data"]["outcome"] == "revoked"
    assert _play(env, env["ids"][0]).status_code == 402
    mine = env["client"].get("/api/v1/ott/viewers/maya/entitlements",
                             headers={"x-ott-viewer": env["viewer"]["session"]}).json()["data"]["items"]
    assert [(i["kind"], i["status"]) for i in mine] == [("tvod", "revoked")]


def test_a_subscription_unlocks_the_tier_and_a_dispute_revokes(env):
    svod = _offer(env, kind="svod", name="Members", price_cents=500, interval="month")
    period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp() * 1000)
    _deliver(env, "entitlement.granted", _event(env, "ent_s1", svod["sku"], expires=period_end))
    assert _play(env, env["ids"][0]).status_code == 200 and _play(env, env["ids"][1]).status_code == 200
    # Another channel's paid title is not part of this subscription.
    other_title = env["other"][1][0]
    assert _play(env, other_title).status_code == 402
    renewed = _deliver(env, "entitlement.granted", _event(env, "ent_s2", svod["sku"], expires=period_end + 10))
    assert renewed.json()["data"]["outcome"] == "renewed"
    with env["factory"]() as s:
        assert s.execute(select(func.count(OttEntitlement.id))).scalar_one() == 1
    _deliver(env, "entitlement.revoked", _event(env, "ent_s3", svod["sku"], kind="revoked", reason="dispute"))
    assert _play(env, env["ids"][0]).status_code == 402


def test_a_rental_expires_on_time(env):
    rent = _offer(env, kind="rental", name="Rent", price_cents=299, title_id=env["ids"][1], rental_hours=48)
    granted = datetime.now(timezone.utc) - timedelta(hours=47)
    _deliver(env, "entitlement.granted", _event(env, "ent_r1", rent["sku"],
                                               occurred=int(granted.timestamp() * 1000)))
    assert _play(env, env["ids"][1]).status_code == 200
    with env["factory"]() as s:
        title = s.get(OttTitle, env["ids"][1])
        viewer_id = env["viewer"]["viewer"]["id"]
        assert entitlements.can_watch(s, title, viewer_id=viewer_id, at=granted + timedelta(hours=47, minutes=59))
        assert not entitlements.can_watch(s, title, viewer_id=viewer_id, at=granted + timedelta(hours=48, seconds=1))
        assert entitlements.viewer_entitlements(s, viewer_id)[0]["expires_at"].startswith(
            (granted + timedelta(hours=48)).strftime("%Y-%m-%dT%H"))


def test_webhook_signature_and_foreign_events(env):
    tvod = _offer(env, kind="tvod", name="Own", price_cents=999, title_id=env["ids"][0])
    bad = _deliver(env, "entitlement.granted", _event(env, "ent_x", tvod["sku"]),
                   secret="whsec_" + "b3RoZXItc2VjcmV0LXRoYXQtaXMtbG9uZy1lbm91Z2g=")
    assert bad.status_code == 401
    stranger = _deliver(env, "entitlement.granted", _event(env, "ent_y", tvod["sku"], buyer="someone-else"))
    assert stranger.json()["data"]["outcome"] == "ignored:unknown_viewer"
    unknown = _deliver(env, "entitlement.granted", _event(env, "ent_z", "tvod.nothing"))
    assert unknown.json()["data"]["outcome"] == "ignored:unknown_offer"
    assert _play(env, env["ids"][0]).status_code == 402


def test_menivor_never_receives_or_forwards_viewer_funds(env):
    from app.models.db.marketplace import WalletLedgerEntry
    from app.models.db.models import CreditLedger

    tvod = _offer(env, kind="tvod", name="Own", price_cents=999, title_id=env["ids"][0])
    _deliver(env, "entitlement.granted", _event(env, "ent_1", tvod["sku"]))
    refused = _deliver(env, "entitlement.granted", {**_event(env, "ent_2", tvod["sku"]), "amount": 999,
                                                    "funds_holder": "menivor"})
    assert refused.status_code == 422
    with env["factory"]() as s:
        assert s.execute(select(func.count()).select_from(CreditLedger)).scalar_one() == 0
        assert s.execute(select(func.count()).select_from(WalletLedgerEntry)).scalar_one() == 0
        columns = {c.name for t in (OttOffer.__table__, OttEntitlement.__table__) for c in t.columns}
    assert not {"amount", "balance", "payout", "fee", "net"} & columns
    import ast

    for path in (REPO / "apps/api/app/domains/ott_commerce").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                assert not re.search(r"wallet|credit|ledger|payout|marketplace", name, re.I), (path.name, name)


def test_reconcile_catches_a_missed_webhook_once(env):
    tvod = _offer(env, kind="tvod", name="Own", price_cents=999, title_id=env["ids"][0])
    env["mint"].events = [_event(env, "ent_m1", tvod["sku"])]
    mint = products.MintSellers(transport=env["mint"])
    with env["factory"]() as s:
        assert tasks.reconcile(s, mint) == {"channels": 1, "applied": 1}
        s.commit()
    with env["factory"]() as s:
        assert tasks.reconcile(s, mint) == {"channels": 1, "applied": 0}
    assert _play(env, env["ids"][0]).status_code == 200


def test_deleting_the_viewer_ends_their_purchases(env):
    tvod = _offer(env, kind="tvod", name="Own", price_cents=999, title_id=env["ids"][0])
    _deliver(env, "entitlement.granted", _event(env, "ent_1", tvod["sku"]))
    res = env["client"].delete("/api/v1/ott/viewers/maya/me", headers={"x-ott-viewer": env["viewer"]["session"]})
    assert res.json()["data"]["purchases_ended"] == 1
    with env["factory"]() as s:
        row = s.execute(select(OttEntitlement)).scalar_one()
        assert row.viewer_id == "deleted" and row.status == "revoked"


def test_commerce_routes_404_until_the_flag(env, monkeypatch):
    monkeypatch.delenv("OTT_COMMERCE_LIVE")
    assert env["client"].get("/api/v1/ott/c/maya/offers").status_code == 404


# --------------------------------------------------------------------------- #
# MV14
# --------------------------------------------------------------------------- #
def _ad_title(env, owner_cid=None) -> str:
    """A free, packaged title to make an ad from."""
    with env["factory"]() as s:
        title = OttTitle(channel_id=owner_cid or env["cid"], title="Sponsor spot", kind="short", genres=[],
                         geo_countries=[], status="published", package_status="ready", duration_s=15.0,
                         source_key="ott:src/spot.mp4", access_tier="free", manifest_key="ott/x/master.m3u8",
                         published_at=datetime.now(timezone.utc))
        s.add(title)
        s.commit()
        return title.id


def _free_title(env) -> str:
    return env["ids"][2]


def test_sponsor_slot_first_then_house_ads(env, monkeypatch):
    monkeypatch.setattr(ads_router, "media_url", lambda title: f"https://r2.example/{title.id}.mp4?sig=1")
    spot = _ad_title(env)
    created = env["client"].post("/api/v1/ott/studio/ads", headers=OWNER, json={
        "title_id": spot, "name": "Coffee week", "sponsor": "Bean Co", "click_url": "https://bean.example"})
    assert created.status_code == 200, created.text
    ours = h.owner(env["factory"], "house@example.com", "house-key")
    house_cid, _ = h.channel(env["factory"], ours, "menivor", titles=0)
    with env["factory"]() as s:
        s.add(OttAd(channel_id=None, kind="house", name="Make reels", title_id=_ad_title(env, house_cid),
                    duration_s=10))
        s.commit()
    doc = ET.fromstring(env["client"].get(f"/api/v1/ott/ads/vast/{_free_title(env)}").content)
    assert doc.get("version") == "4.2" and doc.find(".//AdTitle").text == "Coffee week"
    assert doc.find(".//Advertiser").text == "Bean Co"
    assert doc.find(".//Linear").get("skipoffset") == "00:00:05"
    assert doc.find(".//MediaFile").text.startswith("https://r2.example/")
    assert doc.find(".//Wrapper") is None and doc.find(".//VASTAdTagURI") is None  # programmatic stays off
    env["client"].post(f"/api/v1/ott/studio/ads/{created.json()['data']['id']}/deactivate", headers=OWNER)
    doc = ET.fromstring(env["client"].get(f"/api/v1/ott/ads/vast/{_free_title(env)}").content)
    assert doc.find(".//AdTitle").text == "Make reels"
    env["client"].put("/api/v1/ott/studio/ads/settings", headers=OWNER, json={"house_ads": False})
    assert ET.fromstring(env["client"].get(f"/api/v1/ott/ads/vast/{_free_title(env)}").content).find("Ad") is None


def test_no_ads_on_paid_tiers_unless_the_creator_sets_it(env, monkeypatch):
    monkeypatch.setattr(ads_router, "media_url", lambda title: "https://r2.example/a.mp4")
    env["client"].post("/api/v1/ott/studio/ads", headers=OWNER, json={"title_id": _ad_title(env), "name": "Spot"})
    paid = env["ids"][0]
    assert ET.fromstring(env["client"].get(f"/api/v1/ott/ads/vast/{paid}").content).find("Ad") is None
    svod = _offer(env, kind="svod", name="Members", price_cents=500, interval="month")
    _deliver(env, "entitlement.granted", _event(env, "ent_s", svod["sku"],
                                                expires=int(time.time() * 1000) + 30 * 86400 * 1000))
    member = {"x-ott-viewer": env["viewer"]["session"]}
    free_vast = env["client"].get(f"/api/v1/ott/ads/vast/{_free_title(env)}", headers=member)
    assert ET.fromstring(free_vast.content).find("Ad") is None  # members see no ads anywhere on the channel
    assert ET.fromstring(env["client"].get(f"/api/v1/ott/ads/vast/{_free_title(env)}").content).find("Ad") \
        is not None
    env["client"].put("/api/v1/ott/studio/ads/settings", headers=OWNER, json={"ads_on_paid": True})
    assert ET.fromstring(env["client"].get(f"/api/v1/ott/ads/vast/{paid}").content).find("Ad") is not None


def test_tracking_counts_only_signed_events(env, monkeypatch):
    monkeypatch.setattr(ads_router, "media_url", lambda title: "https://r2.example/a.mp4")
    ad_id = env["client"].post("/api/v1/ott/studio/ads", headers=OWNER,
                               json={"title_id": _ad_title(env), "name": "Spot"}).json()["data"]["id"]
    doc = ET.fromstring(env["client"].get(f"/api/v1/ott/ads/vast/{_free_title(env)}").content)
    impression = doc.find(".//Impression").text.split("/api/v1", 1)[1]
    skip = next(t.text for t in doc.iter("Tracking") if t.get("event") == "skip").split("/api/v1", 1)[1]
    for url in (impression, impression, skip):
        assert env["client"].get(f"/api/v1{url}").status_code == 204
    env["client"].get(f"/api/v1/ott/ads/track/{ad_id}/impression?t=forged")
    stats = env["client"].get("/api/v1/ott/studio/ads", headers=OWNER).json()["data"]
    # Wave Q QM1.0 (P-M12): the same play's impression URL counts once.
    assert stats["ads"][0]["stats"] == {"impressions": 1, "completes": 0, "skips": 1, "clicks": 0}
    assert stats["settings"]["skip_after_s"] == 5 and stats["settings"]["programmatic"] is False


def test_ad_media_must_be_the_creators_free_published_title(env):
    paid = env["ids"][0]
    res = env["client"].post("/api/v1/ott/studio/ads", headers=OWNER, json={"title_id": paid, "name": "Spot"})
    assert res.status_code == 400
    other = env["other"][1][0]
    assert env["client"].post("/api/v1/ott/studio/ads", headers=OWNER,
                              json={"title_id": other, "name": "Spot"}).status_code == 404
    assert env["client"].post("/api/v1/ott/studio/ads", headers=OWNER, json={
        "title_id": _ad_title(env), "name": "Spot", "click_url": "http://insecure.example"}).status_code == 400


def test_vast_empty_is_valid():
    doc = ET.fromstring(vast.empty())
    assert doc.tag == "VAST" and doc.get("version") == "4.2" and list(doc) == []
