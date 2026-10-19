"""Integration tests for the reel<->wallet bridge **Mint settlement** path.

Proves the additive Mint branch end to end against the in-memory fake mint:

* reserve -> HOLD on the resolved Mint account (local ledger untouched);
* settle on success -> CAPTURE the measured actual to treasury + RELEASE the
  uncaptured remainder;
* full-consume settle -> CAPTURE only (no remainder release);
* terminal failure -> RELEASE (failed job nets zero — ADR-0002);
* duplicate worker hooks -> idem_key replay, single net money movement;
* Mint-disabled regression -> the byte-for-byte local microdollar ledger path,
  no ``mint_hold_id`` marker, no HTTP call.

In-memory SQLite + ``httpx.MockTransport``; no network, no live server.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.catalog.service import CatalogService
from app.domains.reels import wallet_bridge as bridge
from app.domains.wallet import mint_client as mint_client_mod
from app.domains.wallet.mint_accounts import resolve_mint_account
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

from tests.reelforge.conftest_mint import FakeMint, make_mint_client


# --------------------------------------------------------------------------- #
# Fixtures (mirror test_wallet_bridge so the local baseline is identical)
# --------------------------------------------------------------------------- #
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
    with factory() as s:
        user = User(email="a@example.com", api_key_hash="h")
        s.add(user)
        s.flush()
        uid = user.id
        prov = ProviderCatalog(
            provider_key="pixelle", display_name="Pixelle", enabled=True
        )
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


def _intent(factory, uid: str):
    quote = _fresh_quote(factory, uid)
    return bridge.extract_wallet_intent(
        {"generation_profile_id": "broll-fast", "quote": quote}
    )


def _enable_mint(monkeypatch, client) -> None:
    """Force the bridge onto the Mint path with ``client`` as the resolver.

    Routing now flows through the launch-flag stage machine
    (``mint_stage.should_use_mint``), so stub that to route every owner to Mint
    and point the client factory at the fake-backed ``client``.
    """
    from app.domains.wallet import mint_stage

    monkeypatch.setattr(mint_stage, "should_use_mint", lambda *a, **k: True)
    monkeypatch.setattr(mint_client_mod, "mint_enabled", lambda: True)
    monkeypatch.setattr(mint_client_mod, "mint_client_from_config", lambda: client)


def _patch_get_session(monkeypatch, factory) -> None:
    """Point the bridge's worker-hook ``get_session`` at the test factory."""
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

    monkeypatch.setattr(base_mod, "get_session", _gs)


# --------------------------------------------------------------------------- #
# RESERVE -> HOLD on Mint
# --------------------------------------------------------------------------- #
def test_reserve_holds_on_mint_and_skips_local_ledger(factory, seeded, monkeypatch):
    fake = FakeMint()
    client = make_mint_client(fake)
    _enable_mint(monkeypatch, client)
    intent = _intent(factory, seeded)

    with factory() as s:
        marker = bridge.reserve_for_job(
            s, user_id=seeded, intent=intent, job_id="job1", request_id="rid"
        )
        s.commit()

    m = marker["_wallet"]
    assert m["mint_hold_id"].startswith("hold_")
    assert m["mint_account"].startswith("acct_")
    assert m["reserved_micros"] == 600_000
    # Money is held on Mint, NOT on the local ledger (no double charge).
    assert fake.accounts[m["mint_account"]]["held"] == 600_000
    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        # Mint is the authoritative balance for owners routed to that rail.
        assert bal["settlement_rail"] == "mint"
        assert bal["reserved_micros"] == 600_000
        assert bal["available_micros"] == fake.default_balance - 600_000


def test_reserve_insufficient_on_mint_raises_402(factory, seeded, monkeypatch):
    fake = FakeMint(default_balance=100)  # far below the $0.60 quote
    client = make_mint_client(fake)
    _enable_mint(monkeypatch, client)
    intent = _intent(factory, seeded)

    with factory() as s:
        with pytest.raises(bridge.WalletBridgeError) as ei:
            bridge.reserve_for_job(
                s, user_id=seeded, intent=intent, job_id="job2", request_id="rid"
            )
        assert ei.value.status_code == 402


# --------------------------------------------------------------------------- #
# SETTLE -> CAPTURE actual (+ RELEASE remainder)
# --------------------------------------------------------------------------- #
def _reserve_and_persist_job(factory, seeded, client, job_id, *, actual=None):
    intent = _intent(factory, seeded)
    with factory() as s:
        marker = bridge.reserve_for_job(
            s, user_id=seeded, intent=intent, job_id=job_id, request_id="rid"
        )
        wallet = dict(marker["_wallet"])
        if actual is not None:
            wallet["actual_micros"] = actual
        job = Job(id=job_id, user_id=seeded, kind="reel", params={"_wallet": wallet})
        s.add(job)
        s.commit()
    return marker["_wallet"]


def test_settle_captures_actual_and_releases_remainder(factory, seeded, monkeypatch):
    fake = FakeMint()
    client = make_mint_client(fake)
    _enable_mint(monkeypatch, client)
    m = _reserve_and_persist_job(factory, seeded, client, "jobC", actual=400_000)
    _patch_get_session(monkeypatch, factory)

    bridge.safe_settle_job_by_id("jobC")

    hold_id = m["mint_hold_id"]
    mint_acct = m["mint_account"]
    assert fake.holds[hold_id]["captured_micros"] == 400_000
    assert (
        fake.accounts[fake.treasury_id]["available"] == 400_000
    )  # captured to treasury
    assert fake.accounts[mint_acct]["held"] == 0  # remainder released
    # Net effect on payer = -actual (400_000 gone, 200_000 returned).
    assert fake.accounts[mint_acct]["available"] == fake.default_balance - 400_000


def test_settle_full_consume_captures_without_release(factory, seeded, monkeypatch):
    fake = FakeMint()
    client = make_mint_client(fake)
    _enable_mint(monkeypatch, client)
    m = _reserve_and_persist_job(factory, seeded, client, "jobF", actual=600_000)
    _patch_get_session(monkeypatch, factory)

    bridge.safe_settle_job_by_id("jobF")

    hold_id = m["mint_hold_id"]
    assert fake.holds[hold_id]["captured_micros"] == 600_000
    assert fake.holds[hold_id]["status"] == "captured"  # not released
    assert fake.accounts[fake.treasury_id]["available"] == 600_000
    assert fake.accounts[m["mint_account"]]["held"] == 0


# --------------------------------------------------------------------------- #
# RELEASE on terminal failure
# --------------------------------------------------------------------------- #
def test_release_on_failure_nets_zero(factory, seeded, monkeypatch):
    fake = FakeMint()
    client = make_mint_client(fake)
    _enable_mint(monkeypatch, client)
    m = _reserve_and_persist_job(factory, seeded, client, "jobR")
    _patch_get_session(monkeypatch, factory)

    bridge.safe_release_job_by_id("jobR")

    hold_id = m["mint_hold_id"]
    mint_acct = m["mint_account"]
    assert fake.holds[hold_id]["status"] == "released"
    assert fake.accounts[mint_acct]["held"] == 0
    assert fake.accounts[mint_acct]["available"] == fake.default_balance  # nets zero
    assert fake.accounts[fake.treasury_id]["available"] == 0  # nothing captured


# --------------------------------------------------------------------------- #
# Idempotency — duplicate worker hooks fire more than once
# --------------------------------------------------------------------------- #
def test_double_settle_is_idempotent(factory, seeded, monkeypatch):
    fake = FakeMint()
    client = make_mint_client(fake)
    _enable_mint(monkeypatch, client)
    m = _reserve_and_persist_job(factory, seeded, client, "jobD", actual=400_000)
    _patch_get_session(monkeypatch, factory)

    bridge.safe_settle_job_by_id("jobD")
    bridge.safe_settle_job_by_id("jobD")  # duplicate terminal hook

    # Capture happened exactly once (idem_key replay), not twice.
    assert fake.accounts[fake.treasury_id]["available"] == 400_000
    assert fake.holds[m["mint_hold_id"]]["captured_micros"] == 400_000


def test_double_release_is_idempotent(factory, seeded, monkeypatch):
    fake = FakeMint()
    client = make_mint_client(fake)
    _enable_mint(monkeypatch, client)
    m = _reserve_and_persist_job(factory, seeded, client, "jobDR")
    _patch_get_session(monkeypatch, factory)

    bridge.safe_release_job_by_id("jobDR")
    bridge.safe_release_job_by_id("jobDR")  # duplicate

    mint_acct = m["mint_account"]
    assert fake.accounts[mint_acct]["held"] == 0
    assert fake.accounts[mint_acct]["available"] == fake.default_balance


def test_reconcile_terminal_jobs_captures_and_releases(factory, seeded, monkeypatch):
    from app.models import const

    fake = FakeMint()
    client = make_mint_client(fake)
    _enable_mint(monkeypatch, client)
    complete = _reserve_and_persist_job(
        factory, seeded, client, "jobRC", actual=350_000
    )
    failed = _reserve_and_persist_job(factory, seeded, client, "jobRR")
    with factory() as s:
        s.get(Job, "jobRC").state = const.TASK_STATE_COMPLETE
        s.get(Job, "jobRR").state = const.TASK_STATE_FAILED
        s.commit()

    with factory() as s:
        summary = bridge.reconcile_terminal_mint_holds(s)
        s.commit()

    assert summary == {"scanned": 2, "captured": 1, "released": 1, "errored": 0}
    assert fake.holds[complete["mint_hold_id"]]["captured_micros"] == 350_000
    assert fake.holds[failed["mint_hold_id"]]["status"] == "released"
    with factory() as s:
        assert s.get(Job, "jobRC").params["_wallet"]["settlement_status"] == "captured"
        assert s.get(Job, "jobRR").params["_wallet"]["settlement_status"] == "released"
        replay = bridge.reconcile_terminal_mint_holds(s)
    assert replay == {"scanned": 0, "captured": 0, "released": 0, "errored": 0}


# --------------------------------------------------------------------------- #
# Account provisioning (resolve_mint_account)
# --------------------------------------------------------------------------- #
def test_personal_account_provisioned_once_and_persisted(factory, seeded):
    fake = FakeMint()
    client = make_mint_client(fake)
    with factory() as s:
        a1 = resolve_mint_account(s, seeded, None, client=client)
        s.commit()
    with factory() as s:
        a2 = resolve_mint_account(s, seeded, None, client=client)
        s.commit()
    assert a1 == a2
    assert fake._acct_seq == 1  # create_account called exactly once
    assert fake.accounts[a1]["kind"] == "User"
    with factory() as s:
        row = WalletService(s)._repo.get_personal_account(seeded)
        assert row.mint_account_id == a1  # persisted on wallet_accounts


def test_workspace_provisions_org_account(factory):
    from app.models.db.models import Workspace

    fake = FakeMint()
    client = make_mint_client(fake)
    with factory() as s:
        owner = User(id="u1", email="ws-owner@example.com", api_key_hash="h")
        s.add(owner)
        s.flush()
        s.add(Workspace(id="ws1", owner_id=owner.id, name="Acme"))
        s.commit()
    with factory() as s:
        acct = resolve_mint_account(s, "u1", "ws1", client=client)
        s.commit()
    assert fake.accounts[acct]["kind"] == "Org"
    assert fake.accounts[acct]["owner_ref"] == "ws1"


# --------------------------------------------------------------------------- #
# Mint DISABLED regression — legacy local ledger path unchanged
# --------------------------------------------------------------------------- #
def test_mint_disabled_uses_local_ledger(factory, seeded, monkeypatch):
    # Ensure the gate is OFF and the client would explode if ever called.
    monkeypatch.setattr(mint_client_mod, "mint_enabled", lambda: False)

    def _boom():  # pragma: no cover - must never be called on the disabled path
        raise AssertionError("mint_client_from_config called on the disabled path")

    monkeypatch.setattr(mint_client_mod, "mint_client_from_config", _boom)

    _grant(factory, seeded, 20_000_000)
    intent = _intent(factory, seeded)
    with factory() as s:
        marker = bridge.reserve_for_job(
            s, user_id=seeded, intent=intent, job_id="jobL", request_id="rid"
        )
        s.commit()
    # Local ledger path: NO mint marker; funds reserved on the local wallet.
    assert "mint_hold_id" not in marker["_wallet"]
    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["reserved_micros"] == 600_000
        assert bal["available_micros"] == 19_400_000
    with factory() as s:
        assert (
            bridge.settle_job(s, user_id=seeded, job_id="jobL", params=marker) is True
        )
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(seeded)
        assert bal["reserved_micros"] == 0
        assert bal["available_micros"] == 19_400_000


# --------------------------------------------------------------------------- #
# Config gate
# --------------------------------------------------------------------------- #
def test_config_gate_and_client_cache(monkeypatch):
    from app.config import config

    monkeypatch.setitem(config.mint, "server_url", "")
    assert mint_client_mod.mint_enabled() is False

    monkeypatch.setitem(config.mint, "server_url", "http://mint.test")
    assert mint_client_mod.mint_enabled() is True

    monkeypatch.setitem(config.mint, "api_key", "")
    monkeypatch.setitem(config.mint, "treasury_account", "")
    mint_client_mod.reset_mint_client_cache()
    assert mint_client_mod.mint_client_from_config() is None

    monkeypatch.setitem(config.mint, "api_key", "k")
    monkeypatch.setitem(config.mint, "treasury_account", "acct_t")
    mint_client_mod.reset_mint_client_cache()
    c1 = mint_client_mod.mint_client_from_config()
    c2 = mint_client_mod.mint_client_from_config()
    assert c1 is not None
    assert c1 is c2  # process-cached
    mint_client_mod.reset_mint_client_cache()
