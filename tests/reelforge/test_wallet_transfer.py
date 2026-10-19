"""Person-to-person AI-token transfer journey over the real Mint client."""

from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.wallet.service import WalletError, WalletService
from app.models.db.base import Base
from app.models.db.marketplace import (
    WalletTransfer,
    WalletTransferChallenge,
    WalletTransferPolicy,
)
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.exception import HttpException
from app.utils import utils
from tests.reelforge.conftest_mint import (
    MINT_ATTESTATION_TEST_KEY_ID,
    MINT_ATTESTATION_TEST_PUBLIC_KEY_HEX,
    FakeMint,
    make_mint_client,
)


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
def transfer_env(factory, monkeypatch):
    from app.config import config
    from app.domains.wallet import mint_client as mint_client_mod
    from app.domains.wallet import mint_stage

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
            email="alice@example.com",
            display_name="Alice",
            handle="alice",
            api_key_hash=_key_hash("alice-key"),
        )
        bob = User(
            email="bob-private@example.com",
            display_name="Bob Creator",
            handle="bob",
            api_key_hash=_key_hash("bob-key"),
        )
        no_handle = User(
            email="private@example.com",
            api_key_hash=_key_hash("private-key"),
        )
        session.add_all((alice, bob, no_handle))
        session.flush()
        alice_wallet = WalletService(session)._repo.get_or_create_personal_account(
            alice.id
        )
        alice_wallet.mint_account_id = client.create_account(
            kind="User", owner_ref=alice.id
        )
        fake.fund(alice_wallet.mint_account_id, 20_000_000)
        ids = {"alice": alice.id, "bob": bob.id, "private": no_handle.id}
        session.commit()
    return factory, fake, client, ids


def test_transfer_moves_mint_balance_once_and_mirrors_safe_activity(transfer_env):
    factory, fake, _client, ids = transfer_env
    with factory() as session:
        result = WalletService(session).transfer(
            ids["alice"],
            recipient_handle="@BoB",
            amount_micros=7_000_000,
            idempotency_key="send-1",
        )
        session.commit()

    assert result["status"] == "completed"
    assert result["recipient"] == {
        "handle": "bob",
        "display_name": "Bob Creator",
        "kind": "personal",
    }
    assert result["amount_usd"] == "7.00"
    assert result["sender_balance"]["available_micros"] == 13_000_000
    assert result["idempotent_replay"] is False
    assert result["receipt_proof"] == {
        "sequence": result["mint_first_seq"],
        "operation": "Transfer",
        "operation_hash": "ab" * 32,
        "amount_micros": 7_000_000,
        "receipt_hash": "cd" * 32,
        "signature": "ef" * 64,
        "signer": "mint-test-key-1",
        "timestamp_ms": 1_777_777_777_000 + result["mint_first_seq"],
    }

    with factory() as session:
        svc = WalletService(session)
        alice_wallet = svc._repo.get_personal_account(ids["alice"])
        bob_wallet = svc._repo.get_personal_account(ids["bob"])
        assert fake.accounts[alice_wallet.mint_account_id]["available"] == 13_000_000
        assert fake.accounts[bob_wallet.mint_account_id]["available"] == 7_000_000
        # Local balances are deliberately untouched: Mint is the sole ledger.
        assert alice_wallet.available_micros == 0
        assert bob_wallet.available_micros == 0
        alice_activity = svc.activity(ids["alice"])
        bob_activity = svc.activity(ids["bob"])
        stored = session.get(WalletTransfer, result["transfer_id"])
        assert stored is not None
        # Complete raw receipt is retained for offline signature/hash-chain
        # verification, not merely the old first_seq projection.
        assert stored.mint_receipt["body"]["account_id"] == alice_wallet.mint_account_id
        assert stored.mint_receipt["body"]["to"] == bob_wallet.mint_account_id
        assert stored.mint_receipt["sig"] == "ef" * 64
        assert stored.attestation is not None
        assert stored.attestation.format == "mint-transfer-attestation-v1"
        assert stored.attestation.signer_key_id == MINT_ATTESTATION_TEST_KEY_ID
        assert result["verification"]["status"] == "verified"

    assert alice_activity[0]["transfer"]["direction"] == "sent"
    assert alice_activity[0]["transfer"]["counterparty_handle"] == "bob"
    assert bob_activity[0]["transfer"]["direction"] == "received"
    assert bob_activity[0]["transfer"]["counterparty_handle"] == "alice"
    serialized = repr(alice_activity) + repr(bob_activity)
    assert "bob-private@example.com" not in serialized
    assert "acct_" not in serialized
    assert "'ref':" not in serialized
    assert "ref" not in result["source"]

    with factory() as session:
        replay = WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=7_000_000,
            idempotency_key="send-1",
        )
        session.commit()
    assert replay["transfer_id"] == result["transfer_id"]
    with factory() as session:
        alice_wallet = WalletService(session)._repo.get_personal_account(ids["alice"])
        assert fake.accounts[alice_wallet.mint_account_id]["available"] == 13_000_000


def test_real_mint_byte_array_operation_hash_finalizes_and_projects_hex(transfer_env):
    factory, _fake, client, ids = transfer_env
    real_transfer = client.transfer

    def rust_wire_transfer(*args, **kwargs):
        result = real_transfer(*args, **kwargs)
        result["receipt"]["body"]["op_hash"] = list(bytes.fromhex("ab" * 32))
        return result

    client.transfer = rust_wire_transfer
    with factory() as session:
        result = WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=3_000_000,
            idempotency_key="rust-operation-hash",
        )
        assert result["status"] == "completed"
        assert result["receipt_proof"]["operation_hash"] == "ab" * 32
        transfer = session.get(WalletTransfer, result["transfer_id"])
        assert transfer is not None
        assert transfer.mint_receipt["body"]["op_hash"] == [171] * 32


@pytest.mark.parametrize(
    "invalid_hash",
    ([1] * 31, [256] * 32, [True] * 32, "AB" * 32),
)
def test_malformed_real_mint_operation_hash_stays_pending(transfer_env, invalid_hash):
    factory, _fake, client, ids = transfer_env
    real_transfer = client.transfer

    def invalid_wire_transfer(*args, **kwargs):
        result = real_transfer(*args, **kwargs)
        result["receipt"]["body"]["op_hash"] = invalid_hash
        return result

    client.transfer = invalid_wire_transfer
    with factory() as session, pytest.raises(WalletError) as error:
        WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=1_000_000,
            idempotency_key="invalid-operation-hash",
        )
    assert error.value.status_code == 503
    with factory() as session:
        transfer = session.query(WalletTransfer).one()
        assert transfer.status == "pending"
        assert transfer.attestation is None
        assert WalletService(session).activity(ids["alice"]) == []


def test_transfer_status_is_sender_only_and_returns_persisted_proof(transfer_env):
    factory, _fake, _client, ids = transfer_env
    with factory() as session:
        sent = WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=2_000_000,
            idempotency_key="proof-lookup",
        )

    with factory() as session:
        looked_up = WalletService(session).transfer_status(
            ids["alice"], sent["transfer_id"]
        )
        assert looked_up["status"] == "completed"
        assert looked_up["receipt_proof"] == sent["receipt_proof"]
        assert "sender_balance" not in looked_up

        # The receipt body contains both account-chain counterparties. Only the
        # sender owns this private proof; recipient and strangers get the same
        # non-enumerable 404 response.
        for other in (ids["bob"], ids["private"]):
            with pytest.raises(WalletError) as error:
                WalletService(session).transfer_status(other, sent["transfer_id"])
            assert error.value.status_code == 404


def test_ambiguous_mint_success_retries_same_operation_without_double_debit(
    transfer_env,
):
    factory, fake, client, ids = transfer_env
    real_transfer = client.transfer
    lost_once = False

    def transfer_then_lose_response(*args, **kwargs):
        nonlocal lost_once
        result = real_transfer(*args, **kwargs)
        if not lost_once:
            lost_once = True
            raise OSError("connection closed after Mint committed")
        return result

    client.transfer = transfer_then_lose_response
    with factory() as session, pytest.raises(WalletError) as error:
        WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=4_000_000,
            idempotency_key="ambiguous-response",
        )
    assert error.value.status_code == 502

    with factory() as session:
        pending = session.query(WalletTransfer).one()
        assert pending.status == "pending"
        assert pending.mint_operation.startswith("menivor:p2p:")
        pending_id = pending.id
        pending_view = WalletService(session).transfer_status(ids["alice"], pending_id)
        assert pending_view["receipt_proof"] is None

        # Handle ownership is mutable, but this already-committed transfer
        # command must continue to mean the original recipient snapshot.
        bob = session.get(User, ids["bob"])
        bob.handle = "renamed-bob"
        session.commit()

    with factory() as session, pytest.raises(WalletError) as conflict:
        WalletService(session).transfer(
            ids["alice"],
            recipient_handle="renamed-bob",
            amount_micros=4_000_000,
            idempotency_key="ambiguous-response",
        )
    assert conflict.value.status_code == 409

    # Exact original request resolves through persisted ids/mappings without
    # looking up the old handle, and reaches the same Mint operation.
    with factory() as session:
        recovered = WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=4_000_000,
            idempotency_key="ambiguous-response",
        )
    assert recovered["transfer_id"] == pending_id
    assert recovered["status"] == "completed"
    assert recovered["idempotent_replay"] is True
    with factory() as session:
        service = WalletService(session)
        alice = service._repo.get_personal_account(ids["alice"])
        bob = service._repo.get_personal_account(ids["bob"])
        assert fake.accounts[alice.mint_account_id]["available"] == 16_000_000
        assert fake.accounts[bob.mint_account_id]["available"] == 4_000_000
        assert len(service.activity(ids["alice"])) == 1
        assert len(service.activity(ids["bob"])) == 1


def test_pending_retry_ignores_rollout_disabled_after_mint_success(
    transfer_env, monkeypatch
):
    factory, fake, client, ids = transfer_env
    real_transfer = client.transfer
    lost_once = False

    def transfer_then_lose_response(*args, **kwargs):
        nonlocal lost_once
        result = real_transfer(*args, **kwargs)
        if not lost_once:
            lost_once = True
            raise OSError("connection closed after Mint committed")
        return result

    client.transfer = transfer_then_lose_response
    with factory() as session, pytest.raises(WalletError):
        WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=6_000_000,
            idempotency_key="rollout-changed",
        )

    from app.domains.wallet import mint_stage

    monkeypatch.setattr(mint_stage, "should_use_mint", lambda _owner: False)
    with factory() as session:
        recovered = WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=6_000_000,
            idempotency_key="rollout-changed",
        )
    assert recovered["status"] == "completed"
    assert recovered["idempotent_replay"] is True
    with factory() as session:
        service = WalletService(session)
        alice = service._repo.get_personal_account(ids["alice"])
        bob = service._repo.get_personal_account(ids["bob"])
        assert fake.accounts[alice.mint_account_id]["available"] == 14_000_000
        assert fake.accounts[bob.mint_account_id]["available"] == 6_000_000
        assert len(service.activity(ids["alice"])) == 1


def test_mint_success_then_result_commit_failure_recovers_on_retry(transfer_env):
    factory, fake, _client, ids = transfer_env
    with factory() as session:
        real_commit = session.commit
        commit_count = 0

        def fail_result_commit_once():
            nonlocal commit_count
            commit_count += 1
            if commit_count == 2:
                raise OSError("database acknowledgement lost")
            return real_commit()

        session.commit = fail_result_commit_once
        with pytest.raises(WalletError) as error:
            WalletService(session).transfer(
                ids["alice"],
                recipient_handle="bob",
                amount_micros=5_000_000,
                idempotency_key="ambiguous-db",
            )
        assert error.value.status_code == 503

    with factory() as session:
        pending = session.query(WalletTransfer).one()
        assert pending.status == "pending"
        assert pending.mint_receipt is None

    with factory() as session:
        recovered = WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=5_000_000,
            idempotency_key="ambiguous-db",
        )
        assert recovered["idempotent_replay"] is True
        assert recovered["receipt_proof"]["signature"] == "ef" * 64

    with factory() as session:
        service = WalletService(session)
        alice = service._repo.get_personal_account(ids["alice"])
        assert fake.accounts[alice.mint_account_id]["available"] == 15_000_000
        assert len(service.activity(ids["alice"])) == 1


def test_transfer_rejects_key_reuse_self_unknown_and_sender_without_handle(
    transfer_env,
):
    factory, _fake, _client, ids = transfer_env
    with factory() as session:
        service = WalletService(session)
        service.transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=1_000_000,
            idempotency_key="same-key",
        )
        session.commit()

    cases = (
        (ids["alice"], "bob", 2_000_000, "same-key", 409),
        (ids["alice"], "alice", 1, "self", 409),
        (ids["alice"], "missing", 1, "unknown", 404),
        (ids["private"], "bob", 1, "no-handle", 409),
    )
    for sender, handle, amount, key, status in cases:
        with factory() as session, pytest.raises(WalletError) as error:
            WalletService(session).transfer(
                sender,
                recipient_handle=handle,
                amount_micros=amount,
                idempotency_key=key,
            )
        assert error.value.status_code == status


def test_transfer_reports_insufficient_mint_balance(transfer_env):
    factory, _fake, _client, ids = transfer_env
    with factory() as session, pytest.raises(WalletError) as error:
        WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=21_000_000,
            idempotency_key="too-much",
        )
    assert error.value.status_code == 402


@pytest.mark.parametrize("failure", ["missing", "bad-signature", "unpinned"])
def test_transfer_stays_pending_when_attestation_cannot_be_verified(
    transfer_env, failure
):
    factory, fake, client, ids = transfer_env
    from app.config import config

    real_transfer = client.transfer

    def invalid_transfer(*args, **kwargs):
        result = real_transfer(*args, **kwargs)
        if failure == "missing":
            result.pop("attestation", None)
        elif failure == "bad-signature":
            result["attestation"]["signature_hex"] = "00" * 64
        return result

    client.transfer = invalid_transfer
    if failure == "unpinned":
        config.mint["attestation_public_keys_json"] = "{}"

    with factory() as session, pytest.raises(WalletError) as error:
        WalletService(session).transfer(
            ids["alice"],
            recipient_handle="bob",
            amount_micros=2_000_000,
            idempotency_key=f"attestation-{failure}",
        )
    assert error.value.status_code == 503

    with factory() as session:
        service = WalletService(session)
        transfer = session.query(WalletTransfer).one()
        assert transfer.status == "pending"
        assert transfer.attestation is None
        assert service.transfer_status(ids["alice"], transfer.id)["verification"] == {
            "status": "pending"
        }
        alice = service._repo.get_personal_account(ids["alice"])
        assert fake.accounts[alice.mint_account_id]["available"] == 18_000_000


def test_transfer_http_contract(transfer_env, monkeypatch):
    factory, _fake, _client, _ids = transfer_env
    wallet_router = importlib.import_module("app.domains.wallet.router")

    @contextmanager
    def get_test_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(wallet_router, "get_session", get_test_session)
    monkeypatch.setattr(wallet_router, "_DB_IMPORT_ERROR", None)
    app = FastAPI()
    app.include_router(wallet_router.router)

    def http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, http_handler)
    browser = TestClient(app)
    headers = {"x-api-key": "alice-key", "Idempotency-Key": "http-send-1"}

    resolved = browser.get(
        "/api/v1/wallet/recipients/bob", headers={"x-api-key": "alice-key"}
    )
    assert resolved.status_code == 200
    assert resolved.json()["data"] == {
        "handle": "bob",
        "display_name": "Bob Creator",
        "kind": "personal",
        "can_receive": True,
    }
    sources = browser.get("/api/v1/wallet/sources", headers={"x-api-key": "alice-key"})
    assert sources.status_code == 200
    source_account_id = sources.json()["data"]["sources"][0]["source_account_id"]
    source_json = sources.json()["data"]["sources"][0]
    assert source_json["limits"]["daily_used_micros"] == 0
    assert source_json["limits"]["daily_remaining_micros"] is None
    assert "mint_account_id" not in sources.text
    assert '"ref"' not in sources.text
    receive = browser.post(
        "/api/v1/wallet/receive-addresses",
        headers={"x-api-key": "alice-key"},
        json={"source_account_id": source_account_id},
    )
    assert receive.status_code == 200, receive.text
    assert receive.json()["data"]["address"].startswith("ait1")
    assert receive.json()["data"]["source"]["source_account_id"] == source_account_id
    assert "acct_" not in receive.text
    replayed_receive = browser.post(
        "/api/v1/wallet/receive-addresses",
        headers={"x-api-key": "alice-key"},
        json={"source_account_id": source_account_id},
    )
    assert (
        replayed_receive.json()["data"]["address"] == receive.json()["data"]["address"]
    )
    policy = browser.put(
        "/api/v1/wallet/transfer-policy",
        headers={"x-api-key": "alice-key"},
        json={
            "source_account_id": source_account_id,
            "per_transfer_limit_micros": 5_000_000,
            "daily_limit_micros": 10_000_000,
        },
    )
    assert policy.status_code == 200, policy.text
    assert policy.json()["data"]["limits"]["daily_remaining_micros"] == 10_000_000
    invalid_policy = browser.put(
        "/api/v1/wallet/transfer-policy",
        headers={"x-api-key": "alice-key"},
        json={
            "source_account_id": source_account_id,
            "per_transfer_limit_micros": -1,
            "daily_limit_micros": 0,
        },
    )
    assert invalid_policy.status_code == 422
    created_destination = browser.post(
        "/api/v1/wallet/destinations",
        headers={"x-api-key": "alice-key"},
        json={
            "kind": "agent",
            "slug": "http-caption-bot",
            "display_name": "HTTP Caption Bot",
        },
    )
    assert created_destination.status_code == 201, created_destination.text
    destination = created_destination.json()["data"]
    assert destination["handle"] == "agent:http-caption-bot"
    assert destination["address"].startswith("ait1")
    assert "acct_" not in created_destination.text
    listed_destinations = browser.get(
        "/api/v1/wallet/destinations", headers={"x-api-key": "alice-key"}
    )
    assert listed_destinations.json()["data"]["destinations"] == [destination]
    destination_balance = browser.get(
        f"/api/v1/wallet/destinations/{destination['destination_id']}/balance",
        headers={"x-api-key": "alice-key"},
    )
    assert destination_balance.status_code == 200
    assert destination_balance.json()["data"]["available_micros"] == 0
    disabled_destination = browser.patch(
        f"/api/v1/wallet/destinations/{destination['destination_id']}",
        headers={"x-api-key": "alice-key"},
        json={"active": False},
    )
    assert disabled_destination.json()["data"]["active"] is False
    disabled_resolution = browser.get(
        "/api/v1/wallet/recipients/agent:http-caption-bot",
        headers={"x-api-key": "alice-key"},
    )
    assert disabled_resolution.status_code == 404
    reviewed = browser.post(
        "/api/v1/wallet/transfer-challenges",
        headers=headers,
        json={
            "source_account_id": source_account_id,
            "recipient_handle": "bob",
            "amount_micros": 3_000_000,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["data"]["recipient"] == {
        "handle": "bob",
        "display_name": "Bob Creator",
        "kind": "personal",
    }
    challenge_id = reviewed.json()["data"]["challenge_id"]
    sent = browser.post(
        "/api/v1/wallet/transfers",
        headers=headers,
        json={
            "source_account_id": source_account_id,
            "challenge_id": challenge_id,
            "recipient_handle": "bob",
            "amount_micros": 3_000_000,
        },
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["data"]["amount_micros"] == 3_000_000
    transfer_id = sent.json()["data"]["transfer_id"]

    status = browser.get(
        f"/api/v1/wallet/transfers/{transfer_id}",
        headers={"x-api-key": "alice-key"},
    )
    assert status.status_code == 200
    assert status.json()["data"]["receipt_proof"]["operation"] == "Transfer"
    assert status.json()["data"]["verification"]["status"] == "verified"
    assert "acct_" not in status.text

    recipient_read = browser.get(
        f"/api/v1/wallet/transfers/{transfer_id}",
        headers={"x-api-key": "bob-key"},
    )
    assert recipient_read.status_code == 404


def test_review_binding_rejects_mutation_and_only_replays_its_command(transfer_env):
    factory, _fake, _client, ids = transfer_env
    with factory() as session:
        service = WalletService(session)
        source = service._repo.get_personal_account(ids["alice"])
        review = service.create_transfer_challenge(
            ids["alice"],
            source_account_id=source.id,
            recipient_handle="bob",
            amount_micros=1_000_000,
            idempotency_key="bound-review",
        )

        for handle, amount, key in (
            ("bob", 2_000_000, "bound-review"),
            ("alice", 1_000_000, "bound-review"),
            ("bob", 1_000_000, "another-command"),
        ):
            with pytest.raises(WalletError) as mismatch:
                service.transfer(
                    ids["alice"],
                    source_account_id=source.id,
                    challenge_id=review["challenge_id"],
                    recipient_handle=handle,
                    amount_micros=amount,
                    idempotency_key=key,
                )
            assert mismatch.value.status_code == 409

        result = service.transfer(
            ids["alice"],
            source_account_id=source.id,
            challenge_id=review["challenge_id"],
            recipient_handle="bob",
            amount_micros=1_000_000,
            idempotency_key="bound-review",
        )
        replay = service.transfer(
            ids["alice"],
            source_account_id=source.id,
            challenge_id=review["challenge_id"],
            recipient_handle="bob",
            amount_micros=1_000_000,
            idempotency_key="bound-review",
        )
        assert replay["transfer_id"] == result["transfer_id"]
        assert session.query(WalletTransfer).count() == 1
        with pytest.raises(WalletError) as foreign_retry:
            service.transfer(
                ids["bob"],
                source_account_id=source.id,
                challenge_id=review["challenge_id"],
                recipient_handle="bob",
                amount_micros=1_000_000,
                idempotency_key="bound-review",
            )
        assert foreign_retry.value.status_code == 404


def test_workspace_source_owner_send_and_member_denied(transfer_env):
    factory, fake, client, ids = transfer_env
    from app.services import workspaces as ws_service

    with factory() as session:
        workspace = ws_service.create_workspace(session, ids["alice"], "Acme Studio")
        ws_service.invite_member(
            session,
            workspace.id,
            ids["alice"],
            "bob-private@example.com",
            role=ws_service.ROLE_MEMBER,
        )
        workspace_id = workspace.id
        workspace_account = WalletService(
            session
        )._repo.get_or_create_workspace_account(workspace_id)
        workspace_account.mint_account_id = client.create_account(
            kind="Org", owner_ref=workspace_id
        )
        fake.fund(workspace_account.mint_account_id, 5_000_000)
        source_account_id = workspace_account.id
        session.commit()

    with factory() as session:
        sources = WalletService(session).source_views(ids["alice"])
        workspace_source = next(row for row in sources if row["kind"] == "workspace")
        assert workspace_source["source_account_id"] == source_account_id
        assert workspace_source["can_send"] is True
        review = WalletService(session).create_transfer_challenge(
            ids["alice"],
            source_account_id=source_account_id,
            recipient_handle="alice",
            amount_micros=1_000_000,
            idempotency_key="workspace-to-actor",
        )
        result = WalletService(session).transfer(
            ids["alice"],
            source_account_id=source_account_id,
            challenge_id=review["challenge_id"],
            recipient_handle="alice",
            amount_micros=1_000_000,
            idempotency_key="workspace-to-actor",
        )
        assert result["source"]["kind"] == "workspace"
        assert result["source"]["label"] == "Acme Studio"
        challenge = session.get(WalletTransferChallenge, review["challenge_id"])
        challenge.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        workspace = session.get(Workspace, workspace_id)
        workspace.owner_user_id = ids["private"]
        membership = (
            session.query(WorkspaceMember)
            .filter_by(workspace_id=workspace_id, user_id=ids["alice"])
            .one()
        )
        membership.role = ws_service.ROLE_MEMBER
        session.commit()
        replay = WalletService(session).transfer(
            ids["alice"],
            source_account_id=source_account_id,
            challenge_id=review["challenge_id"],
            recipient_handle="alice",
            amount_micros=1_000_000,
            idempotency_key="workspace-to-actor",
        )
        assert replay["transfer_id"] == result["transfer_id"]

    with factory() as session:
        with pytest.raises(WalletError) as denied:
            WalletService(session).create_transfer_challenge(
                ids["bob"],
                source_account_id=source_account_id,
                recipient_handle="alice",
                amount_micros=1,
                idempotency_key="member-denied",
            )
        assert denied.value.status_code == 403
        with pytest.raises(WalletError) as policy_denied:
            WalletService(session).set_transfer_policy(
                ids["bob"],
                source_account_id=source_account_id,
                per_transfer_limit_micros=1,
                daily_limit_micros=1,
            )
        assert policy_denied.value.status_code == 403


def test_personal_and_workspace_receive_addresses_are_stable_and_account_bound(
    transfer_env,
):
    factory, fake, client, ids = transfer_env
    from app.services import workspaces as ws_service

    with factory() as session:
        service = WalletService(session)
        personal = service._repo.get_personal_account(ids["alice"])
        first = service.receive_address_view(ids["alice"], personal.id)
        second = service.receive_address_view(ids["alice"], personal.id)
        assert first == second
        assert first["address"].startswith("ait1")
        assert first["source"]["kind"] == "personal"
        assert fake.addresses[first["address"]] == personal.mint_account_id

        workspace = ws_service.create_workspace(session, ids["alice"], "Receive Studio")
        workspace_account = service._repo.get_or_create_workspace_account(workspace.id)
        workspace_view = service.receive_address_view(
            ids["alice"], workspace_account.id
        )
        assert workspace_view["source"]["kind"] == "workspace"
        assert workspace_view["source"]["label"] == "Receive Studio"
        assert workspace_view["address"] != first["address"]
        assert client.lookup_address(workspace_view["address"]) == str(
            workspace_account.mint_account_id
        )
        session.commit()

    with factory() as session:
        service = WalletService(session)
        workspace_account = service._repo.get_workspace_account(workspace.id)
        replay = service.receive_address_view(ids["alice"], workspace_account.id)
        assert replay["address"] == workspace_view["address"]
        with pytest.raises(WalletError) as hidden:
            service.receive_address_view(ids["private"], workspace_account.id)
        assert hidden.value.status_code == 404


def test_public_address_sends_to_workspace_account_and_replays_exactly(transfer_env):
    factory, fake, _client, ids = transfer_env
    from app.services import workspaces as ws_service

    with factory() as session:
        service = WalletService(session)
        workspace = ws_service.create_workspace(session, ids["bob"], "Bob Studio")
        workspace_account = service._repo.get_or_create_workspace_account(workspace.id)
        address_view = service.receive_address_view(ids["bob"], workspace_account.id)
        address = address_view["address"]
        workspace_mint_id = str(workspace_account.mint_account_id)
        alice_account = service._repo.get_personal_account(ids["alice"])
        source_id = alice_account.id
        session.commit()

    with factory() as session:
        service = WalletService(session)
        resolved = service.resolve_recipient(ids["alice"], address)
        assert resolved == {
            "handle": address,
            "display_name": "Bob Studio",
            "kind": "workspace",
            "can_receive": True,
        }
        review = service.create_transfer_challenge(
            ids["alice"],
            source_account_id=source_id,
            recipient_handle=address,
            amount_micros=4_000_000,
            idempotency_key="address-to-workspace",
        )
        assert review["recipient"] == {
            "handle": address,
            "display_name": "Bob Studio",
            "kind": "workspace",
        }
        result = service.transfer(
            ids["alice"],
            source_account_id=source_id,
            challenge_id=review["challenge_id"],
            recipient_handle=address,
            amount_micros=4_000_000,
            idempotency_key="address-to-workspace",
        )
        assert result["recipient"] == {
            "handle": address,
            "display_name": "Bob Studio",
            "kind": "workspace",
        }
        assert "acct_" not in repr(result)
        stored = session.get(WalletTransfer, result["transfer_id"])
        assert stored.recipient_user_id is None
        assert stored.recipient_kind == "workspace"
        assert stored.recipient_ref == workspace.id
        assert stored.recipient_label == "Bob Studio"
        session.commit()

    assert fake.accounts[workspace_mint_id]["available"] == 4_000_000
    with factory() as session:
        service = WalletService(session)
        replay = service.transfer(
            ids["alice"],
            source_account_id=source_id,
            challenge_id=review["challenge_id"],
            recipient_handle=address,
            amount_micros=4_000_000,
            idempotency_key="address-to-workspace",
        )
        assert replay["transfer_id"] == result["transfer_id"]
        workspace_activity = service.activity_for_source(
            ids["bob"], workspace_account.id
        )
        assert workspace_activity[0]["transfer"]["direction"] == "received"
        assert workspace_activity[0]["transfer"]["counterparty_handle"] == "alice"

        with pytest.raises(WalletError) as unknown:
            service.create_transfer_challenge(
                ids["alice"],
                source_account_id=source_id,
                recipient_handle="ait1qdoesnotexist",
                amount_micros=1,
                idempotency_key="unknown-address",
            )
        assert unknown.value.status_code == 404
        assert session.query(WalletTransfer).count() == 1


def test_public_address_routes_to_personal_account_without_private_identity(
    transfer_env,
):
    factory, fake, _client, ids = transfer_env
    with factory() as session:
        service = WalletService(session)
        alice = service._repo.get_personal_account(ids["alice"])
        bob = service._repo.get_or_create_personal_account(ids["bob"])
        bob_address = service.receive_address_view(ids["bob"], bob.id)["address"]
        review = service.create_transfer_challenge(
            ids["alice"],
            source_account_id=alice.id,
            recipient_handle=bob_address,
            amount_micros=2_000_000,
            idempotency_key="address-to-person",
        )
        result = service.transfer(
            ids["alice"],
            source_account_id=alice.id,
            challenge_id=review["challenge_id"],
            recipient_handle=bob_address,
            amount_micros=2_000_000,
            idempotency_key="address-to-person",
        )
        assert result["recipient"] == {
            "handle": bob_address,
            "display_name": "Bob Creator",
            "kind": "personal",
        }
        assert "bob-private@example.com" not in repr(review) + repr(result)
        assert "acct_" not in repr(review) + repr(result)
        assert fake.accounts[bob.mint_account_id]["available"] == 2_000_000


def test_workspace_agent_and_service_destinations_receive_and_are_owner_visible(
    transfer_env,
):
    factory, fake, _client, ids = transfer_env
    from app.services import workspaces as ws_service

    with factory() as session:
        service = WalletService(session)
        workspace = ws_service.create_workspace(session, ids["bob"], "Automation Lab")
        workspace_destination = service.create_destination_profile(
            ids["bob"],
            kind="workspace",
            slug="automation-lab",
            display_name="Automation Lab",
            workspace_id=workspace.id,
        )
        agent_destination = service.create_destination_profile(
            ids["bob"],
            kind="agent",
            slug="caption-bot",
            display_name="Caption Bot",
            workspace_id=workspace.id,
        )
        service_destination = service.create_destination_profile(
            ids["bob"],
            kind="service",
            slug="render-api",
            display_name="Render API",
        )
        alice = service._repo.get_personal_account(ids["alice"])
        source_id = alice.id
        session.commit()

    destinations = (
        (workspace_destination, "workspace", 1_000_000),
        (agent_destination, "agent", 2_000_000),
        (service_destination, "service", 3_000_000),
    )
    for index, (destination, kind, amount) in enumerate(destinations):
        with factory() as session:
            service = WalletService(session)
            resolved = service.resolve_recipient(ids["alice"], destination["handle"])
            assert resolved["kind"] == kind
            assert resolved["display_name"] == destination["display_name"]
            review = service.create_transfer_challenge(
                ids["alice"],
                source_account_id=source_id,
                recipient_handle=destination["handle"],
                amount_micros=amount,
                idempotency_key=f"typed-destination-{index}",
            )
            sent = service.transfer(
                ids["alice"],
                source_account_id=source_id,
                challenge_id=review["challenge_id"],
                recipient_handle=destination["handle"],
                amount_micros=amount,
                idempotency_key=f"typed-destination-{index}",
            )
            assert sent["recipient"]["kind"] == kind
            assert sent["verification"]["status"] == "verified"
            session.commit()

        with factory() as session:
            service = WalletService(session)
            balance = service.destination_profile_balance(
                ids["bob"], destination["destination_id"]
            )
            assert balance["available_micros"] == amount
            activity = service.destination_profile_activity(
                ids["bob"], destination["destination_id"]
            )
            assert activity[0]["transfer"]["direction"] == "received"
            assert "acct_" not in repr(balance) + repr(activity)

    assert fake.accounts[
        next(
            account_id
            for address, account_id in fake.addresses.items()
            if address == agent_destination["address"]
        )
    ]["kind"] == "Agent"
    assert fake.accounts[
        next(
            account_id
            for address, account_id in fake.addresses.items()
            if address == service_destination["address"]
        )
    ]["kind"] == "Provider"


def test_deactivated_agent_destination_fails_closed_for_new_reviews(transfer_env):
    factory, _fake, _client, ids = transfer_env
    with factory() as session:
        service = WalletService(session)
        agent = service.create_destination_profile(
            ids["bob"],
            kind="agent",
            slug="retired-bot",
            display_name="Retired Bot",
        )
        service.set_destination_profile_active(
            ids["bob"], agent["destination_id"], active=False
        )
        source = service._repo.get_personal_account(ids["alice"])
        with pytest.raises(WalletError) as missing:
            service.create_transfer_challenge(
                ids["alice"],
                source_account_id=source.id,
                recipient_handle=agent["handle"],
                amount_micros=1,
                idempotency_key="retired-destination",
            )
        assert missing.value.status_code == 404
        with pytest.raises(WalletError) as hidden:
            service.destination_profile_balance(
                ids["alice"], agent["destination_id"]
            )
        assert hidden.value.status_code == 404


def test_deactivated_workspace_destination_invalidates_unconsumed_review(transfer_env):
    factory, _fake, _client, ids = transfer_env
    from app.services import workspaces as ws_service

    with factory() as session:
        service = WalletService(session)
        workspace = ws_service.create_workspace(session, ids["bob"], "Retired Studio")
        destination = service.create_destination_profile(
            ids["bob"],
            kind="workspace",
            slug="retired-studio",
            display_name="Retired Studio",
            workspace_id=workspace.id,
        )
        source = service._repo.get_personal_account(ids["alice"])
        review = service.create_transfer_challenge(
            ids["alice"],
            source_account_id=source.id,
            recipient_handle=destination["handle"],
            amount_micros=1_000_000,
            idempotency_key="disabled-workspace-after-review",
        )
        service.set_destination_profile_active(
            ids["bob"], destination["destination_id"], active=False
        )

        with pytest.raises(WalletError) as stale:
            service.transfer(
                ids["alice"],
                source_account_id=source.id,
                challenge_id=review["challenge_id"],
                recipient_handle=destination["handle"],
                amount_micros=1_000_000,
                idempotency_key="disabled-workspace-after-review",
            )

        assert stale.value.status_code == 409
        assert session.query(WalletTransfer).count() == 0


def test_legacy_challenge_binding_ignores_new_destination_projection(transfer_env):
    factory, _fake, _client, ids = transfer_env
    with factory() as session:
        service = WalletService(session)
        source = service._repo.get_personal_account(ids["alice"])
        recipient = service._repo.get_or_create_personal_account(ids["bob"])
        challenge = WalletTransferChallenge(
            actor_user_id=ids["alice"],
            source_account_id=source.id,
            recipient_user_id=ids["bob"],
            recipient_account_id=recipient.id,
            recipient_handle="bob",
            recipient_display_name="Bob Creator",
            recipient_kind="personal",
            recipient_ref=ids["bob"],
            recipient_label="Bob Creator",
            binding_version=1,
            amount_micros=1,
            idempotency_key="legacy-review",
            binding_sha256="",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        before = service._challenge_digest(challenge)
        challenge.recipient_kind = "workspace"
        challenge.recipient_ref = "mutated-new-column"
        challenge.recipient_label = "Mutated projection"
        assert service._challenge_digest(challenge) == before


def test_account_daily_limit_and_identity_bound_saved_recipient(transfer_env):
    factory, _fake, _client, ids = transfer_env
    with factory() as session:
        service = WalletService(session)
        source = service._repo.get_personal_account(ids["alice"])
        session.add(
            WalletTransferPolicy(
                account_id=source.id,
                per_transfer_limit_micros=1_000_000,
                daily_limit_micros=1_500_000,
            )
        )
        saved = service.save_recipient(
            ids["alice"],
            source_account_id=source.id,
            recipient_handle="bob",
            label="Bob payout",
        )
        assert (
            service.list_saved_recipients(ids["alice"], source_account_id=source.id)[0][
                "saved_recipient_id"
            ]
            == saved["saved_recipient_id"]
        )
        review = service.create_transfer_challenge(
            ids["alice"],
            source_account_id=source.id,
            recipient_handle="bob",
            saved_recipient_id=saved["saved_recipient_id"],
            amount_micros=1_000_000,
            idempotency_key="limited-1",
        )
        service.transfer(
            ids["alice"],
            source_account_id=source.id,
            challenge_id=review["challenge_id"],
            recipient_handle="bob",
            amount_micros=1_000_000,
            idempotency_key="limited-1",
        )
        source_view = next(
            row
            for row in service.source_views(ids["alice"])
            if row["source_account_id"] == source.id
        )
        assert source_view["limits"]["daily_used_micros"] == 1_000_000
        assert source_view["limits"]["daily_remaining_micros"] == 500_000

    with factory() as session:
        service = WalletService(session)
        source = service._repo.get_personal_account(ids["alice"])
        bob = session.get(User, ids["bob"])
        bob.handle = "bob-renamed"
        session.flush()
        renamed = service.list_saved_recipients(
            ids["alice"], source_account_id=source.id
        )
        assert renamed[0]["saved_recipient_id"] == saved["saved_recipient_id"]
        assert renamed[0]["handle"] == "bob-renamed"
        with pytest.raises(WalletError) as limited:
            service.create_transfer_challenge(
                ids["alice"],
                source_account_id=source.id,
                recipient_handle="bob-renamed",
                saved_recipient_id=saved["saved_recipient_id"],
                amount_micros=600_000,
                idempotency_key="limited-2",
            )
        assert limited.value.status_code == 422
        service.delete_saved_recipient(
            ids["alice"],
            saved["saved_recipient_id"],
            source_account_id=source.id,
        )
        assert (
            service.list_saved_recipients(ids["alice"], source_account_id=source.id)
            == []
        )
