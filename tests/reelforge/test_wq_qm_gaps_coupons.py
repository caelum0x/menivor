"""Wave Q verifier gaps on coupons (QM1.3 follow-up).

(a) Stopping a coupon ends the discount on the creator's processor (PATCH
    ``expires_at`` to now, never DELETE), and switching the same code back on
    reuses that discount id instead of creating a second one with the same
    code (which Dodo refuses). Legacy rows without an id stay local only. A
    processor that does not confirm the stop leaves the code on and answers 503.
(b) A flat coupon's currency follows the channel's prices: omitted means the
    offers' currency, a different one is refused, several need an explicit one.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.domains.ott.models import OttChannel
from app.domains.ott_commerce import products
from app.domains.ott_commerce.models import OttCoupon
from app.domains.ott_commerce.processor import MintDiscounts, dodo_discount_patch
from tests.reelforge.test_wq_qm1_3_commerce import OWNER, REPO, _offer, env  # noqa: F401

COUPONS = "/api/v1/ott/studio/commerce/coupons"
LATER = "2026-12-31T00:00:00Z"
MINT_ENV = {"MINT_URL": "https://mint.example", products.KEY_ENV: "menivor-seller-key-0123456789abcdef"}


def _coupon(env, **body):  # noqa: F811
    return env["client"].post(COUPONS, headers=OWNER, json={"expires_at": LATER, **body})


def _stop(env, code):  # noqa: F811
    return env["client"].post(f"{COUPONS}/{code}/stop", headers=OWNER)


def _row(env, code):  # noqa: F811
    with env["factory"]() as s:
        return s.execute(select(OttCoupon).where(OttCoupon.channel_id == env["cid"],
                                                 OttCoupon.code == code)).scalar_one()


def _error_code(res):
    body = res.json()
    return (body.get("data") or {}).get("code")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# (a) stop and re-enable reuse the processor discount
# --------------------------------------------------------------------------- #
def test_stop_ends_the_processor_discount_and_deactivates(env):  # noqa: F811
    assert _coupon(env, code="save20", kind="percent", percent=20).status_code == 200
    assert _row(env, "SAVE20").processor_discount_id == "dsc_fake_1"
    before = datetime.now(timezone.utc)
    res = _stop(env, "save20")
    assert res.status_code == 200, res.text
    assert res.json()["data"]["active"] is False
    sent = env["processor"].updated[-1]
    assert set(sent) == {"discount_id", "expires_at"} and sent["discount_id"] == "dsc_fake_1"
    assert before.replace(microsecond=0) <= _parse(sent["expires_at"]) <= datetime.now(timezone.utc)
    assert _row(env, "SAVE20").active is False
    with env["factory"]() as s, pytest.raises(products.CommerceError):
        products.usable_coupon(s, env["cid"], "SAVE20")


def test_reenable_reuses_the_same_discount(env):  # noqa: F811
    assert _coupon(env, code="save20", kind="percent", percent=20).status_code == 200
    assert _stop(env, "SAVE20").status_code == 200
    again = _coupon(env, code="save20", kind="percent", percent=10, expires_at="2027-01-31T00:00:00Z")
    assert again.status_code == 200, again.text
    assert again.json()["data"]["active"] is True
    assert len(env["processor"].created) == 1, "no second discount with the same code"
    patch = env["processor"].updated[-1]
    assert patch["discount_id"] == "dsc_fake_1"
    assert patch["type"] == "percentage" and patch["amount"] == 1000
    assert patch["expires_at"] == "2027-01-31T00:00:00Z" and patch["code"] == "SAVE20"
    row = _row(env, "SAVE20")
    assert row.active is True and row.processor_discount_id == "dsc_fake_1"
    with env["factory"]() as s:
        assert products.usable_coupon(s, env["cid"], "save20") == "SAVE20"
    assert _coupon(env, code="save20", kind="percent", percent=5).status_code == 409


def test_reenable_as_flat_sends_currency_options(env):  # noqa: F811
    assert _coupon(env, code="save20", kind="percent", percent=20).status_code == 200
    assert _stop(env, "save20").status_code == 200
    assert _coupon(env, code="save20", kind="amount", amount_cents=300).status_code == 200
    patch = env["processor"].updated[-1]
    assert patch["type"] == "flat" and patch["amount"] == 300
    assert patch["currency_options"] == [{"currency": "USD", "max_amount_possible": 300, "is_default": True}]


def test_legacy_row_without_discount_id(env):  # noqa: F811
    with env["factory"]() as s:
        s.add(OttCoupon(channel_id=env["cid"], code="OLD10", active=True,
                        expires_at=datetime(2026, 12, 31, tzinfo=timezone.utc)))
        s.commit()
    stopped = _stop(env, "old10")
    assert stopped.status_code == 200 and stopped.json()["data"]["active"] is False
    assert env["processor"].updated == [], "nothing to end on the processor"
    back = _coupon(env, code="old10", kind="percent", percent=10)
    assert back.status_code == 200, back.text
    assert [c["code"] for c in env["processor"].created] == ["OLD10"]
    assert _row(env, "OLD10").processor_discount_id == "dsc_fake_1"


def test_stop_failure_keeps_the_code_on_and_answers_503(env):  # noqa: F811
    assert _coupon(env, code="save20", kind="percent", percent=20).status_code == 200
    env["processor"].fail_updates = True
    res = _stop(env, "save20")
    assert res.status_code == 503, res.text
    assert _error_code(res) == "coupon_not_stopped"
    assert _row(env, "SAVE20").active is True
    with env["factory"]() as s:
        assert products.usable_coupon(s, env["cid"], "SAVE20") == "SAVE20"
    env["processor"].fail_updates = False
    assert _stop(env, "save20").status_code == 200


def test_stop_unknown_code_is_404(env):  # noqa: F811
    assert _stop(env, "nope").status_code == 404


def test_stop_through_mint_404_is_503_and_stays_on(env):  # noqa: F811
    """Mint does not serve the PATCH yet: the stop is refused plainly, not faked."""
    with env["factory"]() as s:
        channel = s.get(OttChannel, env["cid"])
        s.add(OttCoupon(channel_id=channel.id, code="SAVE20", active=True, processor_discount_id="dsc_1",
                        expires_at=datetime(2026, 12, 31, tzinfo=timezone.utc)))
        s.flush()
        missing = MintDiscounts(products.MintSellers(env=MINT_ENV, transport=lambda *a: (404, {})))
        with pytest.raises(products.CommerceError) as err:
            products.stop_coupon(s, channel, "save20", processor=missing)
        assert err.value.status_code == 503 and err.value.code == "coupon_not_stopped"
        assert isinstance(err.value.__cause__, products.CommerceError)
        assert err.value.__cause__.code == "discounts_unavailable"
        assert s.execute(select(OttCoupon.active).where(OttCoupon.code == "SAVE20")).scalar_one() is True


def test_mint_discounts_patch_contract():
    calls = []

    def served(method, url, body, headers):
        calls.append((method, url, body))
        if method == "POST":
            return 201, {"discount": {"discount_id": "dsc_9", "code": "SAVE20"}}
        return 200, {"discount": {"discount_id": "dsc_9", "code": "SAVE20"}}

    client = MintDiscounts(products.MintSellers(env=MINT_ENV, transport=served))
    base = {"seller": "menivor.ch_abc", "code": "SAVE20", "type": "percentage", "amount": 2000,
            "expires_at": LATER}
    assert client.create_discount(base) == {"code": "SAVE20", "discount_id": "dsc_9"}
    stop = client.update_discount({"seller": "menivor.ch_abc", "discount_id": "dsc_9",
                                   "expires_at": "2026-10-05T12:00:00Z"})
    assert stop == {"code": "SAVE20", "discount_id": "dsc_9"}
    method, url, body = calls[-1]
    assert method == "PATCH" and url.endswith("/mint/v1/sellers/menivor.ch_abc/discounts/dsc_9")
    assert body == {"expires_at": "2026-10-05T12:00:00Z"}
    client.update_discount({**base, "discount_id": "dsc_9", "type": "flat", "amount": 300, "currency": "eur",
                            "name": "maya SAVE20"})
    body = calls[-1][2]
    assert set(body) <= {"amount", "type", "code", "currency_options", "expires_at", "name"}
    assert body["currency_options"] == [{"currency": "EUR", "max_amount_possible": 300, "is_default": True}]

    missing = MintDiscounts(products.MintSellers(env=MINT_ENV, transport=lambda *a: (404, {})))
    with pytest.raises(products.CommerceError) as off:
        missing.update_discount({"seller": "menivor.ch_abc", "discount_id": "dsc_9", "expires_at": LATER})
    assert off.value.status_code == 503 and off.value.code == "discounts_unavailable"
    with pytest.raises(products.CommerceError):
        client.update_discount({"seller": "menivor.ch_abc", "expires_at": LATER})
    with pytest.raises(ValueError):
        dodo_discount_patch({})
    assert "DELETE" not in {c[0] for c in calls}


# --------------------------------------------------------------------------- #
# (b) flat coupon currency follows the channel's prices
# --------------------------------------------------------------------------- #
def test_flat_coupon_currency_must_match_prices(env):  # noqa: F811
    _offer(env, kind="svod", name="Members", price_cents=500, currency="EUR", interval="month")
    res = _coupon(env, code="fiveoff", kind="amount", amount_cents=500, currency="USD")
    assert res.status_code == 400, res.text
    assert _error_code(res) == "currency"
    assert "must match your prices (EUR)" in res.text
    assert env["processor"].created == []
    ok = _coupon(env, code="fiveoff", kind="amount", amount_cents=500, currency="eur")
    assert ok.status_code == 200, ok.text
    assert env["processor"].created[-1]["currency"] == "EUR"


def test_flat_coupon_currency_defaults_to_offer_currency(env):  # noqa: F811
    _offer(env, kind="svod", name="Members", price_cents=500, currency="EUR", interval="month")
    res = _coupon(env, code="fiveoff", kind="amount", amount_cents=500)
    assert res.status_code == 200, res.text
    assert env["processor"].created[-1]["currency"] == "EUR"


def test_flat_coupon_without_offers_defaults_to_usd(env):  # noqa: F811
    assert _coupon(env, code="fiveoff", kind="amount", amount_cents=500).status_code == 200
    assert env["processor"].created[-1]["currency"] == "USD"


def test_multi_currency_channel_needs_an_explicit_matching_currency(env):  # noqa: F811
    _offer(env, kind="svod", name="Members", price_cents=500, currency="EUR", interval="month")
    _offer(env, kind="tvod", name="Own", price_cents=999, currency="USD", title_id=env["ids"][0])
    omitted = _coupon(env, code="fiveoff", kind="amount", amount_cents=500)
    assert omitted.status_code == 400 and _error_code(omitted) == "currency"
    assert "EUR, USD" in omitted.text
    other = _coupon(env, code="fiveoff", kind="amount", amount_cents=500, currency="GBP")
    assert other.status_code == 400 and _error_code(other) == "currency"
    usd = _coupon(env, code="fiveoff", kind="amount", amount_cents=500, currency="USD")
    assert usd.status_code == 200, usd.text
    assert env["processor"].created[-1]["currency"] == "USD"


def test_percent_coupon_ignores_offer_currency(env):  # noqa: F811
    _offer(env, kind="svod", name="Members", price_cents=500, currency="EUR", interval="month")
    res = _coupon(env, code="save20", kind="percent", percent=20)
    assert res.status_code == 200, res.text
    assert env["processor"].created[-1]["currency"] is None


def test_inactive_offers_do_not_set_the_currency(env):  # noqa: F811
    offer = _offer(env, kind="svod", name="Members", price_cents=500, currency="EUR", interval="month")
    env["client"].post(f"/api/v1/ott/studio/commerce/offers/{offer['id']}/deactivate", headers=OWNER)
    assert _coupon(env, code="fiveoff", kind="amount", amount_cents=500, currency="USD").status_code == 200


def test_coupon_spec_currency_rules():
    body = {"code": "fiveoff", "kind": "amount", "amount_cents": 500, "expires_at": LATER}
    at = datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert products.coupon_spec(body, at=at, offer_currencies=["eur", "EUR"])["currency"] == "EUR"
    assert products.coupon_spec(body, at=at)["currency"] == "USD"
    with pytest.raises(products.CommerceError) as err:
        products.coupon_spec({**body, "currency": "US"}, at=at)
    assert err.value.code == "currency"


# --------------------------------------------------------------------------- #
# migration
# --------------------------------------------------------------------------- #
def test_discount_id_migration_is_additive_and_idempotent():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    path = next((REPO / "migrations/versions").glob("*_e3a5c7d9f1b2_ott_coupon_discount_id.py"))
    spec = importlib.util.spec_from_file_location("ott_coupon_discount_id_mig", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "e3a5c7d9f1b2" and module.down_revision == "d2f4a6c8e0b5"
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn))
        module.op = ops
        module.upgrade()  # no table yet: nothing to do
        assert "ott_coupons" not in inspect(conn).get_table_names()
        conn.execute(text("CREATE TABLE ott_coupons (id VARCHAR(32) PRIMARY KEY)"))
        module.upgrade()
        module.upgrade()
        columns = {c["name"] for c in inspect(conn).get_columns("ott_coupons")}
        assert columns == {"id", "processor_discount_id"}
        module.downgrade()
        module.downgrade()
        assert {c["name"] for c in inspect(conn).get_columns("ott_coupons")} == {"id"}


@pytest.mark.parametrize("status,code,want_status,want_code", [
    (404, "unknown_discount", 404, "unknown_discount"),
    (409, "discounts_unsupported", 409, "discounts_unsupported"),
    (404, "not_found", 503, "discounts_unavailable"),
])
def test_mint_discount_errors_map_distinctly(status, code, want_status, want_code):
    answer = lambda *a: (status, {"error": {"code": code, "message": "x"}})  # noqa: E731
    client = MintDiscounts(products.MintSellers(env=MINT_ENV, transport=answer))
    with pytest.raises(products.CommerceError) as err:
        client.update_discount({"seller": "menivor.ch_abc", "discount_id": "dsc_gone", "expires_at": LATER})
    assert (err.value.status_code, err.value.code) == (want_status, want_code)
