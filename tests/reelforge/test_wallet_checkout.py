"""Wallet checkout session creation (Creem factory) tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.wallet.service import WalletError, WalletService
from app.models.db.base import Base
from app.models.db.models import User
from app.services.billing import creem_client, stripe_client


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture()
def uid(factory):
    with factory() as s:
        u = User(email="a@example.com", api_key_hash="h")
        s.add(u)
        s.flush()
        out = u.id
        s.commit()
    return out


# --------------------------------------------------------------------------- #
# WalletService.create_checkout with an injected session factory
# --------------------------------------------------------------------------- #
def test_checkout_uses_session_factory(factory, uid):
    calls: list = []

    def _factory(intent):
        calls.append(intent.id)
        return {"checkout_url": "https://creem/pay/abc", "session_id": "creem_abc"}

    with factory() as s:
        view = WalletService(s).create_checkout(
            uid,
            amount_usd="20.00",
            provider="creem",
            idempotency_key="k1",
            session_factory=_factory,
        )
        s.commit()
    assert view["checkout_url"] == "https://creem/pay/abc"
    assert view["total_charge_micros"] == 21_000_000
    assert len(calls) == 1


def test_checkout_idempotent_replay_skips_factory(factory, uid):
    calls: list = []

    def _factory(intent):
        calls.append(intent.id)
        return {"checkout_url": "https://creem/pay/abc", "session_id": "creem_abc"}

    with factory() as s:
        WalletService(s).create_checkout(
            uid,
            amount_usd="20.00",
            provider="creem",
            idempotency_key="k1",
            session_factory=_factory,
        )
        s.commit()
    # Same idempotency key -> returns the existing intent, factory NOT called again.
    with factory() as s:
        view = WalletService(s).create_checkout(
            uid,
            amount_usd="20.00",
            provider="creem",
            idempotency_key="k1",
            session_factory=_factory,
        )
        s.commit()
    assert len(calls) == 1
    assert view["payment_intent_id"]
    assert view["checkout_url"] == "https://creem/pay/abc"


def test_checkout_idempotency_key_cannot_change_amount_or_provider(factory, uid):
    def _factory(_intent):
        return {"checkout_url": "https://pay/abc", "session_id": "session_abc"}

    with factory() as s:
        WalletService(s).create_checkout(
            uid,
            amount_usd="20.00",
            provider="creem",
            idempotency_key="bound-key",
            session_factory=_factory,
        )
        s.commit()
    with factory() as s:
        with pytest.raises(WalletError) as changed_amount:
            WalletService(s).create_checkout(
                uid,
                amount_usd="21.00",
                provider="creem",
                idempotency_key="bound-key",
                session_factory=_factory,
            )
        assert changed_amount.value.status_code == 409
    with factory() as s:
        with pytest.raises(WalletError) as changed_provider:
            WalletService(s).create_checkout(
                uid,
                amount_usd="20.00",
                provider="stripe",
                idempotency_key="bound-key",
                session_factory=_factory,
            )
        assert changed_provider.value.status_code == 409


def test_checkout_rejects_fractional_card_cent(factory, uid):
    with factory() as s:
        with pytest.raises(WalletError) as exc:
            WalletService(s).create_checkout(
                uid,
                amount_usd="20.001",
                provider="stripe",
                idempotency_key="fractional-cent",
            )
        assert exc.value.status_code == 422


def test_checkout_factory_error_is_502(factory, uid):
    def _factory(_intent):
        raise RuntimeError("creem down")

    with factory() as s:
        with pytest.raises(WalletError) as ei:
            WalletService(s).create_checkout(
                uid,
                amount_usd="20.00",
                provider="creem",
                idempotency_key="k2",
                session_factory=_factory,
            )
        assert ei.value.status_code == 502


def test_checkout_provisions_and_persists_mint_account(factory, uid, monkeypatch):
    from app.domains.wallet import mint_client as mint_client_mod
    from app.domains.wallet import mint_stage
    from tests.reelforge.conftest_mint import FakeMint, make_mint_client

    fake = FakeMint(default_balance=0)
    client = make_mint_client(fake)
    monkeypatch.setattr(mint_stage, "should_use_mint", lambda _owner: True)
    monkeypatch.setattr(mint_client_mod, "mint_client_from_config", lambda: client)
    captured: dict = {}

    def _factory(intent):
        captured.update(intent.meta)
        return {"checkout_url": "https://creem/pay/mint", "session_id": "creem_mint"}

    with factory() as s:
        view = WalletService(s).create_checkout(
            uid,
            amount_usd="20.00",
            provider="creem",
            idempotency_key="mint-k1",
            session_factory=_factory,
        )
        s.commit()
    assert view["settlement_rail"] == "mint"
    assert captured["settlement_rail"] == "mint"
    assert captured["mint_account_id"].startswith("acct_")
    with factory() as s:
        account = WalletService(s)._repo.get_personal_account(uid)
        assert account.mint_account_id == captured["mint_account_id"]
    assert fake.accounts[captured["mint_account_id"]]["owner_ref"] == uid


# --------------------------------------------------------------------------- #
# creem_client.create_wallet_checkout_session
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self) -> dict:
        return self._body


class _FakeRequests:
    def __init__(self, resp: _Resp) -> None:
        self._resp = resp
        self.last: dict = {}

    def post(self, url, headers=None, json=None, timeout=None):
        self.last = {"url": url, "headers": headers, "json": json}
        return self._resp


class _Intent:
    id = "pi_123"
    user_id = "u1"
    total_charge_micros = 21_000_000
    credit_micros = 20_000_000
    meta = {"settlement_rail": "mint", "mint_account_id": "acct_user_1"}


def test_create_wallet_checkout_session_ok(monkeypatch):
    fake = _FakeRequests(
        _Resp(200, {"id": "creem_sess", "checkout_url": "https://c/pay"})
    )
    monkeypatch.setattr(creem_client, "_require_requests", lambda: None)
    monkeypatch.setattr(creem_client, "_require_api_key", lambda: "k")
    monkeypatch.setattr(
        creem_client, "_creem_config", lambda: {"wallet_product_id": "prod_1"}
    )
    monkeypatch.setattr(creem_client, "_success_url", lambda: "https://ok")
    monkeypatch.setattr(creem_client, "requests", fake)

    out = creem_client.create_wallet_checkout_session(_Intent())
    assert out == {"checkout_url": "https://c/pay", "session_id": "creem_sess"}
    # Intent id is threaded into metadata + request_id; amount is in cents.
    body = fake.last["json"]
    assert body["metadata"]["payment_intent_id"] == "pi_123"
    assert body["request_id"] == "pi_123"
    assert body["amount"] == 2100  # 21_000_000 micros -> 2100 cents
    assert body["metadata"]["settlement_rail"] == "mint"
    assert body["metadata"]["account_id"] == "acct_user_1"
    assert body["metadata"]["mint_account_id"] == "acct_user_1"


def test_create_wallet_checkout_session_requires_product(monkeypatch):
    monkeypatch.setattr(creem_client, "_require_requests", lambda: None)
    monkeypatch.setattr(creem_client, "_require_api_key", lambda: "k")
    monkeypatch.setattr(creem_client, "_creem_config", lambda: {})
    with pytest.raises(RuntimeError):
        creem_client.create_wallet_checkout_session(_Intent())


def test_create_stripe_wallet_checkout_session_binds_exact_intent(monkeypatch):
    captured: dict = {}

    class _Session:
        id = "cs_wallet_123"
        url = "https://checkout.stripe.test/cs_wallet_123"

    def _create(**kwargs):
        captured.update(kwargs)
        return _Session()

    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=SimpleNamespace(create=_create)),
    )
    monkeypatch.setattr(stripe_client, "stripe", fake_stripe)
    monkeypatch.setattr(stripe_client, "_require_sdk", lambda: None)
    monkeypatch.setattr(stripe_client, "_require_secret_key", lambda: "sk_test")
    monkeypatch.setattr(
        stripe_client,
        "_stripe_config",
        lambda: {"success_url": "https://app/ok", "cancel_url": "https://app/no"},
    )

    out = stripe_client.create_wallet_checkout_session(_Intent())

    assert out["session_id"] == "cs_wallet_123"
    price_data = captured["line_items"][0]["price_data"]
    assert price_data["unit_amount"] == 2100
    assert price_data["currency"] == "usd"
    assert captured["metadata"]["payment_intent_id"] == "pi_123"
    assert captured["metadata"]["total_charge_micros"] == "21000000"
    assert captured["metadata"]["mint_account_id"] == "acct_user_1"
    assert captured["payment_intent_data"]["metadata"] == captured["metadata"]
