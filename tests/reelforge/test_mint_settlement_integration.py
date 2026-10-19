"""REAL end-to-end settlement test against a live mint-server over HTTP.

Unlike ``test_mint_client.py`` (which uses an in-memory ``MockTransport``), this
test stands up the *actual* railyard ``mint-server`` as a separate process
listening on a real TCP socket, points the production :class:`MintClient` at it,
and drives the full money surface — create account -> fund -> reserve (hold) ->
capture / release — asserting that **real balances move exactly once** through
real HTTP calls. It also exercises the wallet-bridge settlement helpers
(``_mint_capture`` / ``_mint_release``) against the same live server so the
production settlement code path — not just the client — is verified end to end.

How the live server is obtained (first that works wins):
1. ``MINT_SERVER_URL`` set  -> test runs against that already-running server
   (``MINT_API_KEY`` / ``MINT_TREASURY_ACCOUNT`` optional overrides).
2. else the ``mint-devserver`` dev binary is spawned from the railyard build
   (``MINT_DEVSERVER_BIN`` overrides the path). The binary runs the REAL router /
   handlers / auth / ledger with an in-memory store + auto-confirm funding ramp.
3. else the test is SKIPPED (no live rail obtainable) — never silently mocked.

Run: ``pytest tests/reelforge/test_mint_settlement_integration.py -v``
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.domains.wallet.mint_client import MintClient
from app.domains.reels.wallet_bridge import WalletBridgeError
from app.domains.wallet.transfer_attestation import (
    TransferAttestationExpected,
    load_pinned_public_keys,
    verify_transfer_attestation,
)

pytestmark = pytest.mark.integration

# Default location of the dev binary inside the sibling railyard checkout.
# Override with MINT_DEVSERVER_PATH for your own checkout layout.
_DEFAULT_DEVSERVER = Path(
    os.environ.get("MINT_DEVSERVER_PATH")
    or "../railyard/apps/mint/target/debug/mint-devserver"
)
_READY_PREFIX = "MINT_DEVSERVER_LISTENING"
_API_KEY = "dev-mint-key"
_DEV_SIGNER_KEY_ID = "mint-verifier-key-1"
_DEV_SIGNER_PUBLIC_KEY_HEX = (
    "74e0be0d9692f0817482d8f3930b51d334db23d11665ca8ee52fe9e8c29715e8"
)


def _wait_listening(proc: subprocess.Popen[str], timeout_s: float = 15.0) -> str:
    """Return the devserver's announced URL without a racy pre-bound port."""
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout_s
    output: list[str] = []
    while time.monotonic() < deadline:
        readable, _, _ = select.select([proc.stdout], [], [], 0.1)
        if readable:
            line = proc.stdout.readline()
            if line:
                output.append(line)
                if line.startswith(_READY_PREFIX):
                    return line.removeprefix(_READY_PREFIX).strip().rstrip("/")
        if proc.poll() is not None:
            output.append(proc.stdout.read())
            detail = "".join(output).strip()
            if "Operation not permitted" in detail:
                pytest.skip(
                    "sandbox forbids loopback sockets required by mint-devserver"
                )
            raise RuntimeError(f"mint-devserver exited before readiness: {detail}")
    raise RuntimeError(
        "mint-devserver did not announce readiness: " + "".join(output).strip()
    )


def _wait_healthy(base_url: str, timeout_s: float = 15.0) -> None:
    """Poll ``/healthz`` until the server answers or the deadline passes."""
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/healthz", timeout=1.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:  # not up yet
            last_exc = exc
        time.sleep(0.1)
    raise RuntimeError(f"mint-server never became healthy at {base_url}: {last_exc}")


@pytest.fixture(scope="module")
def live_mint() -> Iterator[tuple[str, str]]:
    """Yield ``(base_url, api_key)`` for a live mint-server, spawning one if needed."""
    external = os.getenv("MINT_SERVER_URL")
    if external:
        api_key = os.getenv("MINT_API_KEY", _API_KEY)
        _wait_healthy(external)
        yield external.rstrip("/"), api_key
        return

    bin_path = Path(os.getenv("MINT_DEVSERVER_BIN", str(_DEFAULT_DEVSERVER)))
    if not bin_path.exists():
        pytest.skip(
            "no live mint-server: set MINT_SERVER_URL or build "
            f"mint-devserver ({bin_path} missing)"
        )

    env = {
        **os.environ,
        "MINT_BIND_ADDR": "127.0.0.1:0",
        "MINT_API_KEY": _API_KEY,
    }
    proc = subprocess.Popen(
        [str(bin_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base_url = _wait_listening(proc)
        _wait_healthy(base_url)
        yield base_url, _API_KEY
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _bootstrap_client(base_url: str, api_key: str, treasury: str) -> MintClient:
    """A production :class:`MintClient` over a REAL socket to ``base_url``."""
    return MintClient(base_url, api_key, treasury)


def _make_treasury(base_url: str, api_key: str) -> str:
    boot = _bootstrap_client(base_url, api_key, treasury="acct_placeholder")
    return boot.create_account(kind="Treasury", owner_ref="reelforge-treasury")


def _fund(client: MintClient, account_id: str, micros: int, ref: str) -> None:
    """Top up ``account_id`` by minting against the auto-confirmed dev deposit."""
    resp = client._post(  # exercised via the real HTTP client
        "/v1/mint",
        {
            "to": account_id,
            "amount_micros": int(micros),
            "deposit_ref": ref,
            "idem_key": ref,
        },
    )
    assert resp["to_balance"]["available_micros"] >= micros


# --------------------------------------------------------------------------- #
# Golden path: reserve -> capture (actual < reserved) moves money once.
# --------------------------------------------------------------------------- #
def test_reserve_then_capture_moves_real_balances(live_mint):
    base_url, api_key = live_mint
    treasury = _make_treasury(base_url, api_key)
    client = _bootstrap_client(base_url, api_key, treasury)

    payer = client.create_account(kind="User", owner_ref="user-capture")
    _fund(client, payer, 10_000_000, ref="dep-capture")

    reserved, actual = 6_000_000, 4_000_000
    treasury_before = client.read_balance(treasury)["available_micros"]

    receipt = client.create_hold(
        from_account=payer, amount_micros=reserved, idem_key="job-cap", ref="q-cap"
    )
    hold_id = receipt["hold_id"]
    held = client.read_balance(payer)
    assert held["held_micros"] == reserved
    assert held["available_micros"] == 10_000_000 - reserved

    # A single capture settles the whole hold: it credits the treasury the
    # measured `actual` AND atomically returns the uncaptured 2M remainder to the
    # payer, closing the hold (exactly what the production _mint_capture relies
    # on — no separate release is issued).
    cap = client.capture_hold(
        hold_id,
        amount_micros=actual,
        to=treasury,
        idem_key="job-cap:capture",
        ref="q-cap",
    )
    assert cap["captured_micros"] == actual

    payer_after = client.read_balance(payer)
    treasury_after = client.read_balance(treasury)["available_micros"]
    # Payer paid exactly `actual`; the unused 2M returned to available.
    assert payer_after["held_micros"] == 0
    assert payer_after["available_micros"] == 10_000_000 - actual
    # Treasury received exactly `actual` — once.
    assert treasury_after - treasury_before == actual


# --------------------------------------------------------------------------- #
# Failure path: reserve -> release returns the full hold, treasury untouched.
# --------------------------------------------------------------------------- #
def test_reserve_then_release_restores_balance(live_mint):
    base_url, api_key = live_mint
    treasury = _make_treasury(base_url, api_key)
    client = _bootstrap_client(base_url, api_key, treasury)

    payer = client.create_account(kind="User", owner_ref="user-release")
    _fund(client, payer, 8_000_000, ref="dep-release")

    reserved = 5_000_000
    treasury_before = client.read_balance(treasury)["available_micros"]

    receipt = client.create_hold(
        from_account=payer, amount_micros=reserved, idem_key="job-rel", ref="q-rel"
    )
    assert client.read_balance(payer)["held_micros"] == reserved

    client.release_hold(receipt["hold_id"], idem_key="job-rel:release", ref="q-rel")

    payer_after = client.read_balance(payer)
    assert payer_after["held_micros"] == 0
    assert payer_after["available_micros"] == 8_000_000  # fully restored
    # A failed job nets zero to the treasury.
    assert client.read_balance(treasury)["available_micros"] == treasury_before


# --------------------------------------------------------------------------- #
# Idempotency: a duplicate terminal capture must not charge twice.
# --------------------------------------------------------------------------- #
def test_capture_idempotent_no_double_charge(live_mint):
    base_url, api_key = live_mint
    treasury = _make_treasury(base_url, api_key)
    client = _bootstrap_client(base_url, api_key, treasury)

    payer = client.create_account(kind="User", owner_ref="user-idem")
    _fund(client, payer, 9_000_000, ref="dep-idem")

    reserved = 7_000_000
    treasury_before = client.read_balance(treasury)["available_micros"]
    receipt = client.create_hold(
        from_account=payer, amount_micros=reserved, idem_key="job-idem", ref="q-idem"
    )
    hold_id = receipt["hold_id"]

    # Same idem_key replayed (a duplicate worker terminal hook).
    client.capture_hold(
        hold_id, amount_micros=reserved, to=treasury, idem_key="job-idem:capture"
    )
    client.capture_hold(
        hold_id, amount_micros=reserved, to=treasury, idem_key="job-idem:capture"
    )

    treasury_after = client.read_balance(treasury)["available_micros"]
    assert treasury_after - treasury_before == reserved  # charged ONCE, not twice
    assert client.read_balance(payer)["held_micros"] == 0


# --------------------------------------------------------------------------- #
# Person-to-person: public receive address -> resolved account + signed proof.
# --------------------------------------------------------------------------- #
def test_public_address_transfer_is_exact_private_and_replay_safe(live_mint):
    """Production ``MintClient`` sends AIT to a person over a real TCP socket."""
    base_url, api_key = live_mint
    treasury = _make_treasury(base_url, api_key)
    client = _bootstrap_client(base_url, api_key, treasury)

    alice = client.create_account(kind="User", owner_ref="p2p-alice")
    bob = client.create_account(kind="User", owner_ref="p2p-bob")
    bob_address = client.create_address(bob)
    assert bob_address.startswith("ait1")
    assert client.lookup_address(bob_address) == bob
    _fund(client, alice, 10_000_000, ref="dep-p2p-address")

    idem_key = "p2p-address:01"
    mint_operation = "menivor:p2p:address:01"
    first = client.transfer(
        from_account=alice,
        to_account=bob_address,
        amount_micros=2_500_000,
        idem_key=idem_key,
        ref=mint_operation,
    )
    proof = first["receipt"]
    proof_body = proof["body"]
    assert first["idempotent_replay"] is False
    assert proof_body["from"] == alice
    assert proof_body["to"] == bob
    assert proof_body["account_id"] == alice
    assert proof_body["amount_micros"] == 2_500_000
    assert client.read_balance(alice)["available_micros"] == 7_500_000
    assert client.read_balance(bob)["available_micros"] == 2_500_000

    # The deterministic dev signer is an explicit test trust anchor. Discovery
    # proves the live process serves that same active key; it is not trusted
    # merely because the server returned it alongside the transfer.
    key_document = httpx.get(
        f"{base_url}/.well-known/mint-verification-keys.json", timeout=2.0
    ).json()
    active_key = key_document["keys"][0]
    assert active_key == {
        "key_id": _DEV_SIGNER_KEY_ID,
        "algorithm": "Ed25519",
        "public_key_hex": _DEV_SIGNER_PUBLIC_KEY_HEX,
        "status": "active",
    }
    operation_hash = bytes(proof_body["op_hash"]).hex()
    pinned_keys = load_pinned_public_keys(
        {_DEV_SIGNER_KEY_ID: _DEV_SIGNER_PUBLIC_KEY_HEX}
    )
    verified = verify_transfer_attestation(
        first["attestation"],
        TransferAttestationExpected(
            sender_mint_id=alice,
            recipient_mint_id=bob,
            mint_operation=mint_operation,
            amount_micros=2_500_000,
            sequence=int(first["first_seq"]),
            operation="Transfer",
            operation_hash=operation_hash,
            receipt_hash=str(proof["hash"]),
            timestamp_ms=int(proof_body["ts"]),
        ),
        pinned_keys,
    )
    assert verified.format == "mint-transfer-attestation-v1"
    attestation_bytes = json.dumps(
        first["attestation"], ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert alice.encode() not in attestation_bytes
    assert bob.encode() not in attestation_bytes
    assert bob_address.encode() not in attestation_bytes
    assert mint_operation.encode() not in attestation_bytes

    replay = client.transfer(
        from_account=alice,
        to_account=bob_address,
        amount_micros=2_500_000,
        idem_key=idem_key,
        ref=mint_operation,
    )
    assert replay["idempotent_replay"] is True
    assert replay["first_seq"] == first["first_seq"]
    assert replay["receipt"] == first["receipt"]
    assert replay["attestation"] == first["attestation"]
    assert client.read_balance(alice)["available_micros"] == 7_500_000
    assert client.read_balance(bob)["available_micros"] == 2_500_000

    with pytest.raises(WalletBridgeError) as conflict:
        client.transfer(
            from_account=alice,
            to_account=bob_address,
            amount_micros=2_500_001,
            idem_key=idem_key,
            ref=mint_operation,
        )
    assert conflict.value.status_code == 409
    assert client.read_balance(alice)["available_micros"] == 7_500_000
    assert client.read_balance(bob)["available_micros"] == 2_500_000


# --------------------------------------------------------------------------- #
# The production wallet-bridge settlement helpers against the live server.
# --------------------------------------------------------------------------- #
def test_bridge_mint_capture_and_release_against_live_server(live_mint, monkeypatch):
    """`_mint_capture` / `_mint_release` move real money via the real client."""
    from app.domains.reels import wallet_bridge

    base_url, api_key = live_mint
    treasury = _make_treasury(base_url, api_key)
    client = _bootstrap_client(base_url, api_key, treasury)

    # Route the bridge helpers at our live client. Both helpers import the factory
    # function-locally from app.domains.wallet.mint_client, so patch it there
    # (the same object the real factory returns once MINT_SERVER_URL is set).
    import app.domains.wallet.mint_client as mint_client_mod

    monkeypatch.setattr(
        mint_client_mod, "mint_client_from_config", lambda: client, raising=True
    )

    # Capture path: reserve 6M, actual 4M.
    payer = client.create_account(kind="User", owner_ref="bridge-cap")
    _fund(client, payer, 10_000_000, ref="dep-bridge-cap")
    hold = client.create_hold(
        from_account=payer, amount_micros=6_000_000, idem_key="bcap"
    )
    t_before = client.read_balance(treasury)["available_micros"]
    marker = {"mint_hold_id": hold["hold_id"], "quote_id": "q"}
    assert wallet_bridge._mint_capture(
        marker, job_id="bcap", reserved=6_000_000, actual=4_000_000
    )
    assert client.read_balance(treasury)["available_micros"] - t_before == 4_000_000
    assert client.read_balance(payer)["available_micros"] == 6_000_000  # 10M - 4M

    # Release path: reserve 5M, fail -> full refund.
    payer2 = client.create_account(kind="User", owner_ref="bridge-rel")
    _fund(client, payer2, 5_000_000, ref="dep-bridge-rel")
    hold2 = client.create_hold(
        from_account=payer2, amount_micros=5_000_000, idem_key="brel"
    )
    marker2 = {"mint_hold_id": hold2["hold_id"], "quote_id": "q"}
    assert wallet_bridge._mint_release(marker2, job_id="brel")
    bal = client.read_balance(payer2)
    assert bal["held_micros"] == 0
    assert bal["available_micros"] == 5_000_000
