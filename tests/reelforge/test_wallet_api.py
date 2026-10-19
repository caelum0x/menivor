"""Wallet domain tests — balance/activity/quote + reservation invariants.

Exercises ``app.domains.wallet`` over a FastAPI ``TestClient`` (SQLite in place
of Postgres, no external I/O) for the HTTP surface, and the service directly for
the internal reserve/settle/release/refund lifecycle. Identity is switched via
the ``x-api-key`` header.

Covered
-------
* balance starts at zero; purchase-quote math (credit + 5% fee, $0.80 minimum)
* checkout is launch-gated (403 in pilot); webhook is fail-closed (403/501)
* webhook-confirmed grant is the only credit path and is idempotent
* reserve moves available->reserved; over-spend -> 402
* settle charges actual + frees the hold; actual>reserved -> 409
* release returns the full hold; refund is an append-only compensating credit
* cached account balances always equal the ledger sum (reconciliation)
"""

from __future__ import annotations

import hashlib
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
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

wallet_mod = importlib.import_module("app.domains.wallet.router")


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


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
def env(monkeypatch, factory):
    @contextmanager
    def _fake_get_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

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


@pytest.fixture()
def user_id(factory):
    with factory() as s:
        u = User(email="alice@example.com", api_key_hash=_key_hash("alice-key"))
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


# =========================================================================== #
# HTTP: balance / quote / gates
# =========================================================================== #
def test_balance_starts_zero(env, user_id):
    resp = env.get("/api/v1/wallet", headers=_headers("alice-key"))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["available_micros"] == 0
    assert data["reserved_micros"] == 0
    assert data["available_usd"] == "0.00"


def test_balance_requires_auth(env, user_id):
    assert env.get("/api/v1/wallet").status_code == 401


def test_purchase_quote_math(env, user_id):
    resp = env.post(
        "/api/v1/wallet/purchase-quotes",
        json={"amount_usd": "20.00"},
        headers=_headers("alice-key"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # $20 credit + 5% fee ($1.00) = $21.00 total; wallet still receives $20.
    assert data["credit_micros"] == 20_000_000
    assert data["fee_micros"] == 1_000_000
    assert data["total_charge_micros"] == 21_000_000
    assert data["fee_rate_bps"] == 500


def test_purchase_quote_minimum_fee(env, user_id):
    # $5 * 5% = $0.25, but the $0.80 minimum fee applies.
    resp = env.post(
        "/api/v1/wallet/purchase-quotes",
        json={"amount_usd": "5.00"},
        headers=_headers("alice-key"),
    )
    data = resp.json()["data"]
    assert data["fee_micros"] == 800_000
    assert data["total_charge_micros"] == 5_800_000


def test_purchase_quote_below_minimum_topup_422(env, user_id):
    resp = env.post(
        "/api/v1/wallet/purchase-quotes",
        json={"amount_usd": "1.00"},
        headers=_headers("alice-key"),
    )
    assert resp.status_code == 422


def test_checkout_launch_gated_in_pilot(env, user_id, monkeypatch):
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "internal_pilot")
    monkeypatch.delenv("REELFORGE_PUBLIC_LAUNCH_APPROVED", raising=False)
    resp = env.post(
        "/api/v1/wallet/checkout",
        json={"amount_usd": "20.00", "provider": "stripe"},
        headers={**_headers("alice-key"), "Idempotency-Key": "abc123"},
    )
    assert resp.status_code == 403  # pilot: checkout disabled


def test_webhook_fail_closed(env, user_id):
    resp = env.post("/api/v1/wallet/webhooks/stripe", headers=_headers("alice-key"))
    # Fail-closed, never a grant: pilot launch gate (403) or, with checkout
    # enabled but the Stripe verifier unconfigured, a clean 503.
    assert resp.status_code in (403, 501, 503)


# =========================================================================== #
# Service: grant + reservation lifecycle + reconciliation
# =========================================================================== #
def _reconciles(factory, user_id: str) -> bool:
    """Assert the cached account balances equal the ledger delta sums."""
    from app.domains.wallet.repository import WalletRepository

    with factory() as s:
        repo = WalletRepository(s)
        account = repo.get_personal_account(user_id)
        if account is None:
            return True
        avail_sum, reserved_sum = repo.ledger_sum(account.id)
        return (
            account.available_micros == avail_sum
            and account.reserved_micros == reserved_sum
        )


def _grant(factory, user_id: str, amount_micros: int) -> None:
    """Grant credit via a confirmed intent (the only credit path)."""
    from app.models.db.marketplace import PaymentIntent

    with factory() as s:
        svc = WalletService(s)
        account = svc._repo.get_or_create_personal_account(user_id)
        intent = PaymentIntent(
            account_id=account.id,
            user_id=user_id,
            idempotency_key=f"grant-{amount_micros}",
            credit_micros=amount_micros,
            total_charge_micros=amount_micros,
            status="pending",
        )
        s.add(intent)
        s.flush()
        svc.confirm_intent(intent.id)
        s.commit()


def test_confirm_intent_grants_once(factory, user_id):
    _grant(factory, user_id, 20_000_000)
    with factory() as s:
        assert WalletService(s).balance_view(user_id)["available_micros"] == 20_000_000
    assert _reconciles(factory, user_id)

    # Re-confirming the same intent must NOT double-grant.
    from app.domains.wallet.repository import WalletRepository

    with factory() as s:
        repo = WalletRepository(s)
        intent = repo.get_intent_by_key(
            repo.get_personal_account(user_id).id, "grant-20000000"
        )
        WalletService(s).confirm_intent(intent.id)
        s.commit()
    with factory() as s:
        assert WalletService(s).balance_view(user_id)["available_micros"] == 20_000_000


def test_confirm_intent_no_double_grant_on_concurrent_delivery(factory, user_id):
    """Two overlapping webhook deliveries for one intent grant credit ONCE.

    Reproduces the at-least-once webhook race: a provider (or a duplicate
    ``checkout.completed`` + ``payment.succeeded`` pair) delivers the same
    payment twice, and two workers each load the intent while it is still
    ``pending`` — before either commits. The in-memory ``intent.status`` guard
    alone cannot stop the second delivery from appending a second GRANT entry
    (a double-grant of spendable wallet credit). The fix locks the account row
    and re-reads the committed status before granting, so the second delivery
    observes ``confirmed`` and no-ops.
    """
    from app.models.db.marketplace import PaymentIntent
    from app.domains.wallet.repository import WalletRepository

    with factory() as s:
        account = WalletService(s)._repo.get_or_create_personal_account(user_id)
        intent = PaymentIntent(
            account_id=account.id,
            user_id=user_id,
            idempotency_key="race-key",
            credit_micros=10_000_000,
            total_charge_micros=10_000_000,
            status="pending",
        )
        s.add(intent)
        s.flush()
        intent_id = intent.id
        s.commit()

    # Two concurrent deliveries each load the intent as ``pending`` up front,
    # modelling both webhook workers reading before either grants.
    s1 = factory()
    s2 = factory()
    try:
        svc1 = WalletService(s1)
        svc2 = WalletService(s2)
        # Each delivery reads the intent up front (still ``pending``). Keep the
        # references so both sessions retain the stale row in their identity map
        # — modelling two workers that each read before either grants (the second
        # must not act on its own stale ``pending`` read).
        i1 = svc1._repo.get_intent(intent_id)
        i2 = svc2._repo.get_intent(intent_id)
        assert i1.status == "pending"
        assert i2.status == "pending"

        # First delivery confirms + commits the grant.
        svc1.confirm_intent(intent_id)
        s1.commit()

        # Second delivery — still holding a stale ``pending`` view — must NOT
        # re-grant. Reference i2 so it is not GC'd out of the identity map.
        assert i2.status == "pending"
        svc2.confirm_intent(intent_id)
        s2.commit()
    finally:
        s1.close()
        s2.close()

    with factory() as s:
        assert (
            WalletService(s).balance_view(user_id)["available_micros"] == 10_000_000
        )
        repo = WalletRepository(s)
        account = repo.get_personal_account(user_id)
        grants = [
            e
            for e in repo.list_activity(account.id, limit=200)
            if e.entry_type == "grant"
        ]
        assert len(grants) == 1
    assert _reconciles(factory, user_id)


def test_reserve_settle_charges_actual(factory, user_id):
    _grant(factory, user_id, 20_000_000)
    with factory() as s:
        WalletService(s).reserve(user_id, amount_micros=5_000_000, job_id="job1")
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(user_id)
        assert bal["available_micros"] == 15_000_000
        assert bal["reserved_micros"] == 5_000_000
    # Actual cost $3 < $5 reserved: charge 3, free 2.
    with factory() as s:
        WalletService(s).settle(
            user_id, reserved_micros=5_000_000, actual_micros=3_000_000, job_id="job1"
        )
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(user_id)
        assert bal["available_micros"] == 17_000_000
        assert bal["reserved_micros"] == 0
    assert _reconciles(factory, user_id)


def test_reserve_over_balance_402(factory, user_id):
    _grant(factory, user_id, 2_000_000)
    with factory() as s:
        with pytest.raises(WalletError) as ei:
            WalletService(s).reserve(user_id, amount_micros=5_000_000, job_id="jobX")
        assert ei.value.status_code == 402


def test_settle_above_reserved_409(factory, user_id):
    _grant(factory, user_id, 20_000_000)
    with factory() as s:
        WalletService(s).reserve(user_id, amount_micros=5_000_000, job_id="job2")
        s.commit()
    with factory() as s:
        with pytest.raises(WalletError) as ei:
            WalletService(s).settle(
                user_id,
                reserved_micros=5_000_000,
                actual_micros=6_000_000,
                job_id="job2",
            )
        assert ei.value.status_code == 409


def test_release_returns_hold(factory, user_id):
    _grant(factory, user_id, 20_000_000)
    with factory() as s:
        WalletService(s).reserve(user_id, amount_micros=5_000_000, job_id="job3")
        s.commit()
    with factory() as s:
        WalletService(s).release(user_id, reserved_micros=5_000_000, job_id="job3")
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(user_id)
        assert bal["available_micros"] == 20_000_000
        assert bal["reserved_micros"] == 0
    assert _reconciles(factory, user_id)


def test_refund_is_compensating_credit(factory, user_id):
    _grant(factory, user_id, 10_000_000)
    with factory() as s:
        WalletService(s).refund(user_id, amount_micros=2_500_000, reason="provider_refund")
        s.commit()
    with factory() as s:
        assert WalletService(s).balance_view(user_id)["available_micros"] == 12_500_000
    assert _reconciles(factory, user_id)


def test_activity_lists_newest_first(factory, user_id):
    _grant(factory, user_id, 10_000_000)
    with factory() as s:
        WalletService(s).reserve(user_id, amount_micros=1_000_000, job_id="jobA")
        s.commit()
    with factory() as s:
        rows = WalletService(s).activity(user_id)
        assert [r["entry_type"] for r in rows][:2] == ["reserve", "grant"]
