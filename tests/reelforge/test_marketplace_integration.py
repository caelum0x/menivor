"""Integration tests: safe live promotion, BYOK routing, marketplace pipeline."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.byok.service import BYOKService
from app.domains.catalog.admin import CatalogAdmin, PromotionError
from app.domains.catalog.seed_data import seed_default_catalog
from app.domains.routing.base import (
    RUN_COMPLETED,
    NormalizedUsage,
    ProviderRegistry,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.runtime import run_marketplace_pipeline
from app.models.db.base import Base
from app.models.db.marketplace import PaymentIntent
from app.models.db.models import Job, User
from app.domains.wallet.service import WalletService


@pytest.fixture(autouse=True)
def _fernet_key(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", Fernet.generate_key().decode())


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


class KeyCapturingAdapter:
    """Records the api_key it was built with (to prove BYOK swaps the key)."""

    def __init__(self, provider_key: str, api_key: str = "PLATFORM") -> None:
        self._key = provider_key
        self.api_key = api_key
        self.used_key: str | None = None

    @property
    def provider_key(self) -> str:
        return self._key

    def catalog(self):
        return []

    def quote(self, request, price_version):
        return QuoteResult(max_cost_micros=0, expires_at=None)

    def submit(self, request, snapshot, correlation_id):
        self.used_key = self.api_key
        return ProviderRun(
            provider_key=self._key,
            run_id="r",
            state=RUN_COMPLETED,
            usage=NormalizedUsage(unit="seconds", quantity_units=3, cost_micros=0),
        )

    def poll(self, run):
        return run

    def cancel(self, run):
        return True

    def normalize_usage(self, payload):
        return NormalizedUsage(unit="seconds", quantity_units=3, cost_micros=0)


# --------------------------------------------------------------------------- #
# #1 Safe live promotion
# --------------------------------------------------------------------------- #
def test_promotion_refused_without_adapter(factory):
    with factory() as s:
        seed_default_catalog(s)  # all shadow, manual prices
        s.commit()
    with factory() as s:
        admin = CatalogAdmin(s)
        reg = ProviderRegistry()  # no adapters registered
        readiness = admin.promotion_readiness("pixelle/wan-i2v", provider_registry=reg)
        assert readiness["has_price"] is True  # seeded price is 'manual'
        assert readiness["has_adapter"] is False
        assert readiness["ready"] is False
        with pytest.raises(PromotionError):
            admin.promote_model_live("pixelle/wan-i2v", provider_registry=reg)


def test_promotion_succeeds_with_adapter_and_price(factory):
    with factory() as s:
        seed_default_catalog(s)
        s.commit()
    with factory() as s:
        admin = CatalogAdmin(s)
        reg = ProviderRegistry()
        reg.register(KeyCapturingAdapter("pixelle"))
        out = admin.promote_model_live("pixelle/wan-i2v", provider_registry=reg)
        s.commit()
        assert out["release_status"] == "ga"
    with factory() as s:
        from app.domains.catalog.repository import CatalogRepository

        from app.models.db.marketplace import ProviderCatalog

        entry = CatalogRepository(s).get_model("pixelle/wan-i2v")
        assert entry.release_status == "ga"
        # Provider enabled by promotion.
        assert s.get(ProviderCatalog, entry.provider_id).enabled is True


# --------------------------------------------------------------------------- #
# #3 BYOK routing consumption
# --------------------------------------------------------------------------- #
def _seed_live(factory) -> None:
    with factory() as s:
        seed_default_catalog(s, live_models={"pixelle/wan-i2v"})
        s.commit()


def test_pipeline_uses_byok_key_when_present(factory):
    _seed_live(factory)
    with factory() as s:
        u = User(email="a@example.com", api_key_hash="h")
        s.add(u)
        s.flush()
        uid = u.id
        # Store a BYOK key for pixelle + grant explicit BYOK consent.
        BYOKService(s).add_key(uid, provider_key="pixelle", secret="CUSTOMER-KEY")
        from app.domains.spend.service import SpendPolicyService

        SpendPolicyService(s).upsert_policy(uid, byok_allowed=True)
        s.commit()

    platform = KeyCapturingAdapter("pixelle", api_key="PLATFORM")
    reg = ProviderRegistry()
    reg.register(platform)

    # Patch build_adapter so BYOK constructs a capturing adapter with the secret.

    captured = {}

    def _fake_build(provider_key, api_key):
        a = KeyCapturingAdapter(provider_key, api_key=api_key)
        captured["adapter"] = a
        return a

    import app.domains.routing.providers.registry as reg_mod

    orig = reg_mod.build_adapter
    reg_mod.build_adapter = _fake_build
    try:
        with factory() as s:
            out = run_marketplace_pipeline(
                s,
                job_id="jobB",
                stages={"broll": "pixelle/wan-i2v"},
                user_id=uid,
                use_byok=True,
                provider_registry=reg,
            )
            s.commit()
    finally:
        reg_mod.build_adapter = orig

    # BYOK: the customer paid the provider directly, so ReelForge charges the
    # routing fee (default 10% of the equivalent $0.12 provider cost = $0.012),
    # NOT the pass-through provider price.
    assert out["total_cost_micros"] == 12_000
    # The BYOK adapter (customer key) ran, NOT the platform adapter.
    assert captured["adapter"].used_key == "CUSTOMER-KEY"
    assert platform.used_key is None
    # The BYOK key's use was audited.
    with factory() as s:
        from app.models.db.marketplace import ProviderKey

        row = s.query(ProviderKey).first()
        assert row.use_count == 1


# --------------------------------------------------------------------------- #
# #2 Multi-stage marketplace pipeline + aggregate settlement
# --------------------------------------------------------------------------- #
def _grant(factory, uid: str, micros: int) -> None:
    with factory() as s:
        svc = WalletService(s)
        acct = svc._repo.get_or_create_personal_account(uid)
        intent = PaymentIntent(
            account_id=acct.id, user_id=uid, idempotency_key=f"g{micros}",
            credit_micros=micros, total_charge_micros=micros, status="pending",
        )
        s.add(intent)
        s.flush()
        svc.confirm_intent(intent.id)
        s.commit()


def test_multi_stage_pipeline_accumulates_and_settles(factory):
    with factory() as s:
        seed_default_catalog(
            s, live_models={"pixelle/wan-i2v", "elevenlabs/eleven_multilingual_v2"}
        )
        u = User(email="c@example.com", api_key_hash="h")
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    _grant(factory, uid, 5_000_000)

    # Reserve $1.00 for the job (over the real cost so we can prove a release).
    marker = {"_wallet": {"reserved_micros": 1_000_000, "correlation_id": "c"}}
    with factory() as s:
        WalletService(s).reserve(uid, amount_micros=1_000_000, job_id="jobM")
        s.add(Job(id="jobM", user_id=uid, kind="reel", params=marker))
        s.commit()

    reg = ProviderRegistry()
    reg.register(KeyCapturingAdapter("pixelle"))
    reg.register(KeyCapturingAdapter("elevenlabs"))

    with factory() as s:
        out = run_marketplace_pipeline(
            s,
            job_id="jobM",
            stages={
                "broll": "pixelle/wan-i2v",   # 40_000/sec * 3s = 120_000
                "voice": "elevenlabs/eleven_multilingual_v2",  # 300/char * 3 = 900
            },
            provider_registry=reg,
        )
        s.commit()
    assert out["total_cost_micros"] == 120_900
    assert set(out["stages"]) == {"broll", "voice"}

    # Terminal settlement charges the aggregate actual, releasing the rest.
    from app.domains.reels import wallet_bridge as bridge

    with factory() as s:
        job = s.get(Job, "jobM")
        assert job.params["_wallet"]["actual_micros"] == 120_900
        bridge.settle_job(s, user_id=uid, job_id="jobM", params=job.params)
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(uid)
        assert bal["reserved_micros"] == 0
        # 4_000_000 left after reserve + (1_000_000 - 120_900) released.
        assert bal["available_micros"] == 4_000_000 + (1_000_000 - 120_900)
