"""Tests for the additive reel<->wallet bridge (generation_profile_id path).

Covers quote extraction, signature/expiry validation, reserve->settle/release
against a real signed quote produced by the catalog service, the insufficient
balance path, and the DB-loading ``*_by_id`` worker hooks. In-memory SQLite; no
external I/O.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.catalog.service import CatalogService
from app.domains.reels import wallet_bridge as bridge
from app.domains.wallet.service import WalletService
from app.models.db.base import Base
from app.models.db.marketplace import (
    GenerationProfile,
    ModelCatalogEntry,
    PaymentIntent,
    PriceVersion,
    ProviderCatalog,
)
from app.models.db.models import Job, User


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
def seeded(factory):
    """A user + a broll-only curated profile priced at $0.60 (600_000 micros)."""
    with factory() as s:
        user = User(email="a@example.com", api_key_hash="h")
        s.add(user)
        s.flush()
        uid = user.id
        prov = ProviderCatalog(provider_key="pixelle", display_name="Pixelle", enabled=True)
        s.add(prov)
        s.flush()
        entry = ModelCatalogEntry(
            model_id="pixelle/wan-i2v",
            provider_id=prov.id,
            capability="broll",
            metering_unit="seconds",
            release_status="ga",
            availability_state="available",
        )
        s.add(entry)
        s.flush()
        s.add(
            PriceVersion(
                model_entry_id=entry.id,
                model_id=entry.model_id,
                unit="seconds",
                unit_price_micros=100_000,
                quote_rules={"default_units": 6},
                version=1,
            )
        )
        s.add(
            GenerationProfile(
                slug="broll-fast",
                display_name="Broll Fast",
                stages={"broll": {"model_id": "pixelle/wan-i2v"}},
                is_curated=True,
            )
        )
        s.commit()
    return uid


def _fresh_quote(factory, uid: str) -> dict:
    with factory() as s:
        from app.domains.catalog.schemas import GenerationQuoteRequest

        quote = CatalogService(s).quote_generation(
            GenerationQuoteRequest(profile="broll-fast"), user_id=uid
        )
    assert quote["max_cost_micros"] == 600_000
    return quote


def _grant(factory, uid: str, micros: int) -> None:
    with factory() as s:
        svc = WalletService(s)
        acct = svc._repo.get_or_create_personal_account(uid)
        intent = PaymentIntent(
            account_id=acct.id,
            user_id=uid,
            idempotency_key=f"g{micros}",
            credit_micros=micros,
            total_charge_micros=micros,
            status="pending",
        )
        s.add(intent)
        s.flush()
        svc.confirm_intent(intent.id)
        s.commit()


# --------------------------------------------------------------------------- #
# extract / validate
# --------------------------------------------------------------------------- #
def test_extract_wallet_intent_none_for_classic():
    assert bridge.extract_wallet_intent({"variants": 1}) is None
    assert bridge.extract_wallet_intent({"quote": {"max_cost_micros": 5}}) is None  # no profile
    assert (
        bridge.extract_wallet_intent(
            {"generation_profile_id": "p", "quote": {"max_cost_micros": 0}}
        )
        is None
    )


def test_extract_wallet_intent_parses(factory, seeded):
    quote = _fresh_quote(factory, seeded)
    intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": quote}
    )
    assert intent is not None
    assert intent.max_cost_micros == 600_000
    assert intent.profile == "broll-fast"


def test_validate_intent_rejects_tampered_and_expired(factory, seeded):
    quote = _fresh_quote(factory, seeded)
    intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": quote}
    )
    with factory() as s:
        bridge.validate_intent(s, intent, "rid")  # valid -> no raise

    tampered = dict(quote)
    tampered["max_cost_micros"] = 1
    t_intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": tampered}
    )
    with factory() as s:
        with pytest.raises(bridge.WalletBridgeError) as ei:
            bridge.validate_intent(s, t_intent, "rid")
        assert ei.value.status_code == 422

    expired = dict(quote)
    expired["expires_at"] = "2000-01-01T00:00:00+00:00"
    # Re-sign so the signature is valid but the quote is expired.
    from app.domains.catalog import policy as cat_policy
    from app.domains.catalog.service import _quote_signing_secret

    expired["signature"] = cat_policy.sign_quote(expired, _quote_signing_secret())
    e_intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": expired}
    )
    with factory() as s:
        with pytest.raises(bridge.WalletBridgeError) as ei:
            bridge.validate_intent(s, e_intent, "rid")
        assert ei.value.status_code == 422


# --------------------------------------------------------------------------- #
# reserve / settle / release
# --------------------------------------------------------------------------- #
def test_reserve_then_settle(factory, seeded):
    _grant(factory, seeded, 20_000_000)
    quote = _fresh_quote(factory, seeded)
    intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": quote}
    )
    with factory() as s:
        marker = bridge.reserve_for_job(
            s, user_id=seeded, intent=intent, job_id="job1", request_id="rid"
        )
        s.commit()
    assert marker["_wallet"]["reserved_micros"] == 600_000
    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["available_micros"] == 19_400_000
        assert bal["reserved_micros"] == 600_000
    # Settle (fixed-price: actual == reserved) clears the hold and charges $0.60.
    with factory() as s:
        assert bridge.settle_job(s, user_id=seeded, job_id="job1", params=marker) is True
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["available_micros"] == 19_400_000
        assert bal["reserved_micros"] == 0


def test_reserve_insufficient_raises_402(factory, seeded):
    _grant(factory, seeded, 100_000)  # only $0.10, quote needs $0.60
    quote = _fresh_quote(factory, seeded)
    intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": quote}
    )
    with factory() as s:
        with pytest.raises(bridge.WalletBridgeError) as ei:
            bridge.reserve_for_job(
                s, user_id=seeded, intent=intent, job_id="job2", request_id="rid"
            )
        assert ei.value.status_code == 402


def test_release_returns_hold(factory, seeded):
    _grant(factory, seeded, 20_000_000)
    quote = _fresh_quote(factory, seeded)
    intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": quote}
    )
    with factory() as s:
        marker = bridge.reserve_for_job(
            s, user_id=seeded, intent=intent, job_id="job3", request_id="rid"
        )
        s.commit()
    with factory() as s:
        assert bridge.release_job(s, user_id=seeded, job_id="job3", params=marker) is True
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["available_micros"] == 20_000_000
        assert bal["reserved_micros"] == 0


def test_settle_release_noop_for_classic_job(factory, seeded):
    # A job with no _wallet marker settles/releases to a no-op.
    with factory() as s:
        assert bridge.settle_job(s, user_id=seeded, job_id="j", params={"foo": 1}) is False
        assert bridge.release_job(s, user_id=seeded, job_id="j", params={}) is False


def test_double_settle_local_ledger_is_idempotent(factory, seeded):
    """A duplicate terminal settle hook must not re-charge the local ledger.

    The Mint path is idempotent via idem-keys; the local ledger must match it.
    Without a guard the second settle re-applies ``(reserved - actual)`` to
    available and frees the hold again, corrupting the balance.
    """
    _grant(factory, seeded, 20_000_000)
    quote = _fresh_quote(factory, seeded)
    intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": quote}
    )
    with factory() as s:
        marker = bridge.reserve_for_job(
            s, user_id=seeded, intent=intent, job_id="jobDS", request_id="rid"
        )
        # Record a measured actual below the reservation so a double settle would
        # visibly double-credit the freed remainder if it were not idempotent.
        wallet = {**marker["_wallet"], "actual_micros": 400_000}
        s.commit()

    with factory() as s:
        assert bridge.settle_job(s, user_id=seeded, job_id="jobDS", params={"_wallet": wallet}) is True
        s.commit()
    with factory() as s:
        # Duplicate terminal hook (Celery at-least-once redelivery).
        assert bridge.settle_job(s, user_id=seeded, job_id="jobDS", params={"_wallet": wallet}) is True
        s.commit()

    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        # Charged the actual $0.40 exactly once: 20_000_000 - 400_000.
        assert bal["available_micros"] == 19_600_000
        assert bal["reserved_micros"] == 0
        # Exactly one settle entry exists (idempotent replay, not a second charge).
        acct = WalletService(s)._repo.get_personal_account(seeded)
        settles = [
            e for e in WalletService(s)._repo.list_activity(acct.id, limit=200)
            if e.entry_type == "settle" and e.job_id == "jobDS"
        ]
        assert len(settles) == 1


def test_double_release_local_ledger_is_idempotent(factory, seeded):
    """A duplicate terminal release hook must not return the hold twice."""
    _grant(factory, seeded, 20_000_000)
    quote = _fresh_quote(factory, seeded)
    intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": quote}
    )
    with factory() as s:
        marker = bridge.reserve_for_job(
            s, user_id=seeded, intent=intent, job_id="jobDR", request_id="rid"
        )
        s.commit()

    with factory() as s:
        assert bridge.release_job(s, user_id=seeded, job_id="jobDR", params=marker) is True
        s.commit()
    with factory() as s:
        assert bridge.release_job(s, user_id=seeded, job_id="jobDR", params=marker) is True
        s.commit()

    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["available_micros"] == 20_000_000
        assert bal["reserved_micros"] == 0


def test_duplicate_settle_does_not_corrupt_shared_pool(factory, seeded):
    """The real corruption case: a duplicate settle for job A must not free
    job B's concurrent hold in a shared pool.

    Exercised directly against :class:`WalletService` (where the idempotency
    guard lives) so it isolates the ledger money math from the spend-role layer.
    Two jobs hold from one account; a duplicate settle of A previously re-freed
    A's remainder AND cleared B's reservation. Both must now be intact.
    """
    _grant(factory, seeded, 2_000_000)

    # Two concurrent jobs each reserve $0.60 from the same wallet.
    with factory() as s:
        svc = WalletService(s)
        svc.reserve(seeded, amount_micros=600_000, job_id="jobA", correlation_id="r")
        svc.reserve(seeded, amount_micros=600_000, job_id="jobB", correlation_id="r")
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["reserved_micros"] == 1_200_000
        assert bal["available_micros"] == 800_000

    # Job A settles at actual $0.40, then its terminal hook fires again.
    with factory() as s:
        WalletService(s).settle(
            seeded, reserved_micros=600_000, actual_micros=400_000, job_id="jobA"
        )
        s.commit()
    with factory() as s:
        WalletService(s).settle(  # duplicate terminal hook
            seeded, reserved_micros=600_000, actual_micros=400_000, job_id="jobA"
        )
        s.commit()

    # Job B's hold must survive: reserved still holds B's $0.60, and available
    # reflects A's single $0.40 charge only (not a phantom double-credit).
    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["reserved_micros"] == 600_000  # job B still held
        assert bal["available_micros"] == 1_000_000  # 800k + 200k freed once
        # Job B can still settle cleanly afterward.
        WalletService(s).settle(
            seeded, reserved_micros=600_000, actual_micros=600_000, job_id="jobB"
        )
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["reserved_micros"] == 0
        # 2.0M granted - 0.40 (A actual) - 0.60 (B actual) = 1.0M remaining.
        assert bal["available_micros"] == 1_000_000


def test_by_id_hooks_load_marker_from_job(factory, seeded):
    _grant(factory, seeded, 20_000_000)
    quote = _fresh_quote(factory, seeded)
    intent = bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": quote}
    )
    # Reserve and persist a Job row carrying the marker in its params.
    with factory() as s:
        marker = bridge.reserve_for_job(
            s, user_id=seeded, intent=intent, job_id="jobX", request_id="rid"
        )
        job = Job(id="jobX", user_id=seeded, kind="reel", params=marker)
        s.add(job)
        s.commit()

    # Monkeypatch the bridge's get_session to our test factory so the *_by_id
    # helpers load from the same in-memory DB.
    from contextlib import contextmanager

    import app.models.db.base as base_mod

    @contextmanager
    def _gs():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    orig = base_mod.get_session
    base_mod.get_session = _gs
    try:
        bridge.safe_settle_job_by_id("jobX")
    finally:
        base_mod.get_session = orig

    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["reserved_micros"] == 0
        assert bal["available_micros"] == 19_400_000
