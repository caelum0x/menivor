"""Automatic recovery of durable person-to-person Mint transfer commands."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.wallet.service import WalletError, WalletService
from app.domains.wallet.transfer_reconciliation import (
    claim_pending_transfers,
    finish_transfer_lease,
    reconcile_pending_transfers,
)
from app.models.db.base import Base
from app.models.db.marketplace import WalletLedgerEntry, WalletTransfer
from app.models.db.models import User
from tests.reelforge.conftest_mint import (
    MINT_ATTESTATION_TEST_KEY_ID,
    MINT_ATTESTATION_TEST_PUBLIC_KEY_HEX,
    FakeMint,
    make_mint_client,
)


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@pytest.fixture()
def reconciliation_env(monkeypatch):
    from app.config import config
    from app.domains.wallet import mint_client as mint_client_mod
    from app.domains.wallet import mint_stage

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    fake = FakeMint(default_balance=0)
    client = make_mint_client(fake)
    monkeypatch.setattr(mint_stage, "should_use_mint", lambda _owner: True)
    monkeypatch.setattr(mint_client_mod, "mint_client_from_config", lambda: client)
    monkeypatch.setitem(
        config.mint,
        "attestation_public_keys_json",
        json.dumps(
            {MINT_ATTESTATION_TEST_KEY_ID: MINT_ATTESTATION_TEST_PUBLIC_KEY_HEX}
        ),
    )

    with factory() as session:
        alice = User(
            email="alice-reconcile@example.com",
            display_name="Alice",
            handle="alice-reconcile",
            api_key_hash=_key_hash("alice-reconcile-key"),
        )
        bob = User(
            email="bob-reconcile@example.com",
            display_name="Bob",
            handle="bob-reconcile",
            api_key_hash=_key_hash("bob-reconcile-key"),
        )
        session.add_all((alice, bob))
        session.flush()
        wallet = WalletService(session)._repo.get_or_create_personal_account(alice.id)
        wallet.mint_account_id = client.create_account(kind="User", owner_ref=alice.id)
        fake.fund(wallet.mint_account_id, 10_000_000)
        ids = {"alice": alice.id, "bob": bob.id}
        session.commit()

    @contextmanager
    def test_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr("app.models.db.base.get_session", test_session)
    return factory, fake, client, ids


def _leave_ambiguous_pending(factory, client, alice_id: str) -> str:
    real_transfer = client.transfer

    def commit_then_drop(*args, **kwargs):
        real_transfer(*args, **kwargs)
        raise OSError("response lost after Mint committed")

    client.transfer = commit_then_drop
    try:
        with factory() as session, pytest.raises(WalletError):
            WalletService(session).transfer(
                alice_id,
                recipient_handle="bob-reconcile",
                amount_micros=3_000_000,
                idempotency_key="automatic-recovery",
            )
    finally:
        client.transfer = real_transfer
    with factory() as session:
        transfer = session.execute(select(WalletTransfer)).scalar_one()
        assert transfer.status == "pending"
        return transfer.id


def test_reconciler_replays_mint_once_and_projects_activity_once(reconciliation_env):
    factory, fake, client, ids = reconciliation_env
    transfer_id = _leave_ambiguous_pending(factory, client, ids["alice"])

    first = reconcile_pending_transfers(limit=10, owner="worker-a")
    second = reconcile_pending_transfers(limit=10, owner="worker-b")

    assert first == {
        "claimed": 1,
        "completed": 1,
        "rejected": 0,
        "pending": 0,
        "errored": 0,
        "lost_lease": 0,
    }
    assert second["claimed"] == 0
    with factory() as session:
        transfer = session.get(WalletTransfer, transfer_id)
        assert transfer is not None
        assert transfer.status == "completed"
        assert transfer.attestation is not None
        assert transfer.reconcile_lease_owner is None
        activity_count = session.scalar(
            select(func.count(WalletLedgerEntry.id)).where(
                WalletLedgerEntry.correlation_id == transfer_id
            )
        )
        assert activity_count == 2
        sender = WalletService(session)._repo.get_personal_account(ids["alice"])
        recipient = WalletService(session)._repo.get_personal_account(ids["bob"])
        assert fake.accounts[sender.mint_account_id]["available"] == 7_000_000
        assert fake.accounts[recipient.mint_account_id]["available"] == 3_000_000


def test_lease_is_exclusive_then_expires_with_bounded_backoff(reconciliation_env):
    factory, _fake, client, ids = reconciliation_env
    transfer_id = _leave_ambiguous_pending(factory, client, ids["alice"])
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    with factory() as session:
        first = claim_pending_transfers(
            session, owner="worker-a", limit=1, now=now
        )
    with factory() as session:
        competing = claim_pending_transfers(
            session, owner="worker-b", limit=1, now=now + timedelta(seconds=1)
        )
    assert len(first) == 1
    assert competing == []

    with factory() as session:
        assert finish_transfer_lease(
            session, first[0], error="temporary Mint outage", now=now
        )
    with factory() as session:
        transfer = session.get(WalletTransfer, transfer_id)
        assert transfer.reconcile_lease_owner is None
        assert transfer.reconcile_last_error == "temporary Mint outage"
        assert transfer.reconcile_attempts == 1
        assert transfer.reconcile_after.replace(tzinfo=timezone.utc) == now + timedelta(
            seconds=15
        )
        blocked = claim_pending_transfers(
            session, owner="worker-b", limit=1, now=now + timedelta(seconds=14)
        )
        assert blocked == []
        retry = claim_pending_transfers(
            session, owner="worker-b", limit=1, now=now + timedelta(seconds=16)
        )
        assert len(retry) == 1


def test_expired_worker_cannot_clear_new_owner_lease(reconciliation_env):
    factory, _fake, client, ids = reconciliation_env
    transfer_id = _leave_ambiguous_pending(factory, client, ids["alice"])
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    with factory() as session:
        stale = claim_pending_transfers(session, owner="stale", limit=1, now=now)[0]
    with factory() as session:
        current = claim_pending_transfers(
            session,
            owner="current",
            limit=1,
            now=now + timedelta(minutes=3),
        )[0]
    with factory() as session:
        assert not finish_transfer_lease(
            session,
            stale,
            error="late stale result",
            now=now + timedelta(minutes=3, seconds=1),
        )
    with factory() as session:
        transfer = session.get(WalletTransfer, transfer_id)
        assert transfer.reconcile_lease_owner == current.owner
        assert transfer.reconcile_last_error is None


def test_definitive_insufficient_funds_never_executes_after_later_top_up(
    reconciliation_env,
):
    factory, fake, _client, ids = reconciliation_env
    with factory() as session, pytest.raises(WalletError) as rejected:
        WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob-reconcile",
            amount_micros=11_000_000,
            idempotency_key="rejected-insufficient",
        )
    assert rejected.value.status_code == 402

    with factory() as session:
        transfer = session.execute(select(WalletTransfer)).scalar_one()
        assert transfer.status == "rejected"
        sender = WalletService(session)._repo.get_personal_account(ids["alice"])
        recipient = WalletService(session)._repo.get_personal_account(ids["bob"])
        fake.fund(sender.mint_account_id, 20_000_000)
        sender_mint_id = sender.mint_account_id
        recipient_mint_id = recipient.mint_account_id

    assert reconcile_pending_transfers(limit=10)["claimed"] == 0
    with factory() as session, pytest.raises(WalletError) as replay:
        WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob-reconcile",
            amount_micros=11_000_000,
            idempotency_key="rejected-insufficient",
        )
    assert replay.value.status_code == 409
    assert fake.accounts[sender_mint_id]["available"] == 30_000_000
    assert fake.accounts[recipient_mint_id]["available"] == 0


def test_reconciler_reports_terminal_rejection_without_lost_lease(
    reconciliation_env,
):
    factory, _fake, client, ids = reconciliation_env
    real_transfer = client.transfer

    def unavailable_before_mint(*_args, **_kwargs):
        raise OSError("Mint unavailable before request")

    client.transfer = unavailable_before_mint
    try:
        with factory() as session, pytest.raises(WalletError):
            WalletService(session).transfer(
                ids["alice"],
                recipient_handle="bob-reconcile",
                amount_micros=11_000_000,
                idempotency_key="reconcile-to-rejected",
            )
    finally:
        client.transfer = real_transfer

    result = reconcile_pending_transfers(limit=1, owner="rejecting-worker")
    assert result == {
        "claimed": 1,
        "completed": 0,
        "rejected": 1,
        "pending": 0,
        "errored": 0,
        "lost_lease": 0,
    }
    with factory() as session:
        assert session.execute(select(WalletTransfer.status)).scalar_one() == "rejected"
