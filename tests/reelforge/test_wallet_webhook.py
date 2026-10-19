"""Wallet Creem webhook tests — verified grant + idempotency + router gating."""

from __future__ import annotations

import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.wallet.service import WalletError, WalletService
from app.domains.wallet.webhooks import (
    process_creem_wallet_webhook,
    process_wallet_webhook,
)
from app.models.db.base import Base
from app.models.db.marketplace import PaymentIntent
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

wallet_mod = importlib.import_module("app.domains.wallet.router")


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


def _pending_intent(
    factory,
    credit_micros: int = 20_000_000,
    *,
    provider: str = "creem",
    provider_ref: str = "",
) -> tuple[str, str]:
    with factory() as s:
        u = User(email="a@example.com", api_key_hash="h")
        s.add(u)
        s.flush()
        intent = PaymentIntent(
            account_id=WalletService(s)._repo.get_or_create_personal_account(u.id).id,
            user_id=u.id,
            idempotency_key="chk-1",
            credit_micros=credit_micros,
            total_charge_micros=credit_micros + 1_000_000,
            payment_provider=provider,
            provider_ref=provider_ref,
            status="pending",
        )
        s.add(intent)
        s.flush()
        uid, intent_id = u.id, intent.id
        s.commit()
    return uid, intent_id


def _event(
    intent_id: str,
    *,
    event_type: str = "checkout.completed",
    mint_account_id: str = "",
) -> dict:
    metadata = {"payment_intent_id": intent_id}
    if mint_account_id:
        metadata.update(
            {"account_id": mint_account_id, "mint_account_id": mint_account_id}
        )
    return {
        "eventType": event_type,
        "object": {"id": "creem_chk_123", "metadata": metadata},
    }


def _stripe_event(
    intent_id: str,
    *,
    amount_total: int = 2_100,
    provider_ref: str = "cs_wallet_123",
    mint_account_id: str = "",
    currency: str = "usd",
    credit_micros: str = "20000000",
) -> dict:
    metadata = {
        "payment_intent_id": intent_id,
        "kind": "wallet_topup",
        "credit_micros": credit_micros,
        "total_charge_micros": "21000000",
        "currency": "USD",
    }
    if mint_account_id:
        metadata.update(
            {"account_id": mint_account_id, "mint_account_id": mint_account_id}
        )
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": provider_ref,
                "amount_total": amount_total,
                "currency": currency,
                "metadata": metadata,
            }
        },
    }


# --------------------------------------------------------------------------- #
# Processor
# --------------------------------------------------------------------------- #
def test_webhook_grants_credit_once(factory):
    uid, intent_id = _pending_intent(factory)
    verify = lambda _p, _s: _event(intent_id)  # noqa: E731 - test stub

    with factory() as s:
        result = process_creem_wallet_webhook(s, b"{}", "sig", verify_fn=verify)
        s.commit()
    assert result["status"] == "granted"
    with factory() as s:
        assert WalletService(s).balance_view(uid)["available_micros"] == 20_000_000

    # Duplicate delivery -> idempotent, no double grant.
    with factory() as s:
        process_creem_wallet_webhook(s, b"{}", "sig", verify_fn=verify)
        s.commit()
    with factory() as s:
        assert WalletService(s).balance_view(uid)["available_micros"] == 20_000_000


def test_webhook_mints_credit_once_without_local_double_ledger(factory):
    from tests.reelforge.conftest_mint import FakeMint, make_mint_client

    uid, intent_id = _pending_intent(factory)
    fake = FakeMint(default_balance=0)
    client = make_mint_client(fake)
    mint_account_id = client.create_account(owner_ref=uid)
    with factory() as s:
        intent = s.get(PaymentIntent, intent_id)
        account = WalletService(s)._repo.get_personal_account(uid)
        account.mint_account_id = mint_account_id
        intent.meta = {
            "settlement_rail": "mint",
            "mint_account_id": mint_account_id,
        }
        s.commit()
    verify = lambda _p, _s: _event(  # noqa: E731 - test stub
        intent_id, mint_account_id=mint_account_id
    )

    with factory() as s:
        first = process_creem_wallet_webhook(
            s, b"{}", "sig", verify_fn=verify, mint_client=client
        )
        s.commit()
    with factory() as s:
        replay = process_creem_wallet_webhook(
            s, b"{}", "sig", verify_fn=verify, mint_client=client
        )
        s.commit()

    assert first["status"] == "granted"
    assert replay["status"] == "granted"
    assert fake.accounts[mint_account_id]["available"] == 20_000_000
    with factory() as s:
        account = WalletService(s)._repo.get_personal_account(uid)
        assert account.available_micros == 0
        entries = WalletService(s)._repo.list_activity(account.id)
        assert len(entries) == 1
        assert entries[0].reason == "purchase_mint"
        assert entries[0].available_delta == 0


def test_webhook_bad_signature_raises_value_error(factory):
    def _bad(_p, _s):
        raise ValueError("signature mismatch")

    with factory() as s:
        with pytest.raises(ValueError):
            process_creem_wallet_webhook(s, b"{}", "sig", verify_fn=_bad)


def test_webhook_unknown_intent_raises_wallet_error(factory):
    verify = lambda _p, _s: _event("does-not-exist")  # noqa: E731
    with factory() as s:
        with pytest.raises(WalletError) as ei:
            process_creem_wallet_webhook(s, b"{}", "sig", verify_fn=verify)
        assert ei.value.status_code == 404


def test_webhook_non_purchase_event_ignored(factory):
    _uid, intent_id = _pending_intent(factory)
    verify = lambda _p, _s: _event(intent_id, event_type="checkout.created")  # noqa: E731
    with factory() as s:
        result = process_creem_wallet_webhook(s, b"{}", "sig", verify_fn=verify)
        s.commit()
    assert result["status"] == "ignored"


def test_webhook_missing_metadata_raises(factory):
    verify = lambda _p, _s: {"eventType": "checkout.completed", "object": {"id": "x"}}  # noqa: E731
    with factory() as s:
        with pytest.raises(ValueError):
            process_creem_wallet_webhook(s, b"{}", "sig", verify_fn=verify)


def test_stripe_webhook_grants_only_its_bound_intent(factory):
    uid, intent_id = _pending_intent(
        factory, provider="stripe", provider_ref="cs_wallet_123"
    )
    verify = lambda _p, _s: _stripe_event(intent_id)  # noqa: E731

    with factory() as s:
        result = process_wallet_webhook(
            s,
            "stripe",
            b"{}",
            {"Stripe-Signature": "sig"},
            verify_fn=verify,
        )
        s.commit()

    assert result["provider"] == "stripe"
    with factory() as s:
        assert WalletService(s).balance_view(uid)["available_micros"] == 20_000_000


def test_stripe_webhook_mints_with_provider_namespaced_reference(factory):
    from tests.reelforge.conftest_mint import FakeMint, make_mint_client

    uid, intent_id = _pending_intent(
        factory, provider="stripe", provider_ref="cs_wallet_123"
    )
    fake = FakeMint(default_balance=0)
    client = make_mint_client(fake)
    mint_account_id = client.create_account(owner_ref=uid)
    with factory() as s:
        intent = s.get(PaymentIntent, intent_id)
        account = WalletService(s)._repo.get_personal_account(uid)
        account.mint_account_id = mint_account_id
        intent.meta = {
            "settlement_rail": "mint",
            "mint_account_id": mint_account_id,
        }
        s.commit()

    with factory() as s:
        process_wallet_webhook(
            s,
            "stripe",
            b"{}",
            {"stripe-signature": "sig"},
            verify_fn=lambda _p, _s: _stripe_event(
                intent_id, mint_account_id=mint_account_id
            ),
            mint_client=client,
        )
        s.commit()

    assert fake.accounts[mint_account_id]["available"] == 20_000_000
    assert "mint:stripe:cs_wallet_123" in fake._idem


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (lambda intent_id: _stripe_event(intent_id, amount_total=2_099), "paid amount"),
        (
            lambda intent_id: _stripe_event(intent_id, provider_ref="cs_other"),
            "checkout reference",
        ),
        (lambda intent_id: _stripe_event(intent_id, currency="eur"), "currency"),
        (
            lambda intent_id: _stripe_event(intent_id, credit_micros="19000000"),
            "credit amount",
        ),
    ],
)
def test_stripe_webhook_rejects_mismatched_payment(factory, event, message):
    _uid, intent_id = _pending_intent(
        factory, provider="stripe", provider_ref="cs_wallet_123"
    )
    with factory() as s:
        with pytest.raises(ValueError, match=message):
            process_wallet_webhook(
                s,
                "stripe",
                b"{}",
                {"stripe-signature": "sig"},
                verify_fn=lambda _p, _s: event(intent_id),
            )


def test_provider_cannot_confirm_another_providers_intent(factory):
    _uid, intent_id = _pending_intent(factory, provider="creem")
    with factory() as s:
        with pytest.raises(ValueError, match="provider does not match"):
            process_wallet_webhook(
                s,
                "stripe",
                b"{}",
                {"stripe-signature": "sig"},
                verify_fn=lambda _p, _s: _stripe_event(intent_id),
            )


def test_mint_webhook_rejects_another_account(factory):
    from tests.reelforge.conftest_mint import FakeMint, make_mint_client

    uid, intent_id = _pending_intent(
        factory, provider="stripe", provider_ref="cs_wallet_123"
    )
    fake = FakeMint(default_balance=0)
    client = make_mint_client(fake)
    mint_account_id = client.create_account(owner_ref=uid)
    with factory() as s:
        intent = s.get(PaymentIntent, intent_id)
        intent.meta = {
            "settlement_rail": "mint",
            "mint_account_id": mint_account_id,
        }
        s.commit()

    with factory() as s:
        with pytest.raises(ValueError, match="Mint account metadata"):
            process_wallet_webhook(
                s,
                "stripe",
                b"{}",
                {"stripe-signature": "sig"},
                verify_fn=lambda _p, _s: _stripe_event(
                    intent_id, mint_account_id="acct_attacker"
                ),
                mint_client=client,
            )
    assert fake.accounts[mint_account_id]["available"] == 0


# --------------------------------------------------------------------------- #
# Router gating
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch, factory):
    @contextmanager
    def _fake_get_session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(wallet_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(wallet_mod, "_DB_IMPORT_ERROR", None)
    app = FastAPI()
    app.include_router(wallet_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app)


def test_router_webhook_gated_in_pilot(client, monkeypatch):
    # Default launch phase = internal pilot -> checkout/webhook disabled (403).
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "internal_pilot")
    monkeypatch.delenv("REELFORGE_PUBLIC_LAUNCH_APPROVED", raising=False)
    resp = client.post("/api/v1/wallet/webhooks/creem", content=b"{}")
    assert resp.status_code == 403


def _enable_checkout(monkeypatch):
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "public")
    monkeypatch.setenv("REELFORGE_PUBLIC_LAUNCH_APPROVED", "true")
    monkeypatch.setenv("REELFORGE_CHECKOUT_ENABLED", "true")


def test_router_webhook_unsupported_provider(client, monkeypatch):
    _enable_checkout(monkeypatch)
    resp = client.post("/api/v1/wallet/webhooks/paypal", content=b"{}")
    assert resp.status_code == 422


def test_router_webhook_creem_grants(client, monkeypatch):
    _enable_checkout(monkeypatch)
    monkeypatch.setattr(
        wallet_mod,
        "process_wallet_webhook",
        lambda *a, **k: {"status": "granted", "payment_intent_id": "pi_1"},
    )
    resp = client.post(
        "/api/v1/wallet/webhooks/creem",
        content=b"{}",
        headers={"creem-signature": "sig"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "granted"


def test_router_webhook_bad_signature_400(client, monkeypatch):
    _enable_checkout(monkeypatch)

    def _raise(*_a, **_k):
        raise ValueError("signature mismatch")

    monkeypatch.setattr(wallet_mod, "process_wallet_webhook", _raise)
    resp = client.post(
        "/api/v1/wallet/webhooks/creem",
        content=b"{}",
        headers={"creem-signature": "bad"},
    )
    assert resp.status_code == 400
