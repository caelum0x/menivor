"""Unit tests for :class:`MintClient` against an injected ``MockTransport``.

Covers: the ``{success, data}`` envelope parse, the ``x-api-key`` header,
each ``/v1`` route (accounts/holds/capture/release/balance), bare-int amounts,
and the status -> :class:`WalletBridgeError` mapping (402/409/422/403/502).
No network and no live server — the transport is in-memory.
"""

from __future__ import annotations

import httpx
import pytest

from app.domains.reels.wallet_bridge import WalletBridgeError
from app.domains.wallet.mint_client import MintClient

from tests.reelforge.conftest_mint import FakeMint, make_mint_client


@pytest.fixture()
def fake() -> FakeMint:
    return FakeMint()


@pytest.fixture()
def client(fake: FakeMint) -> MintClient:
    return make_mint_client(fake)


# --------------------------------------------------------------------------- #
# Routes + envelope
# --------------------------------------------------------------------------- #
def test_create_account_returns_acct_id_and_sends_kind_owner(fake, client):
    account_id = client.create_account(kind="Org", owner_ref="ws_1")
    assert account_id.startswith("acct_")
    assert fake.accounts[account_id]["kind"] == "Org"
    assert fake.accounts[account_id]["owner_ref"] == "ws_1"


def test_public_address_routes_are_exposed_without_treating_address_as_auth():
    requests: list[tuple[str, str, dict | None]] = []
    account_id = "acct_recipient"
    address = "ait1qpublicrecipient"

    def handler(request: httpx.Request) -> httpx.Response:
        body = None
        if request.content:
            import json

            body = json.loads(request.content)
        requests.append((request.method, request.url.path, body))
        if request.method == "POST":
            return httpx.Response(
                201, json={"success": True, "data": {"address": address}}
            )
        return httpx.Response(
            200, json={"success": True, "data": {"account_id": account_id}}
        )

    c = MintClient(
        "http://mint.test",
        "secret-key",
        "acct_treasury",
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://mint.test"
        ),
    )
    assert c.create_address(account_id) == address
    assert c.lookup_address(address) == account_id
    assert requests == [
        ("POST", f"/v1/accounts/{account_id}/addresses", {"purpose": "receive"}),
        ("GET", f"/v1/addresses/{address}", None),
    ]


def test_transfer_preserves_public_destination_and_signed_evidence():
    captured: dict = {}
    address = "ait1qpublicrecipient"
    evidence = {
        "first_seq": 9,
        "from_balance": {"available_micros": 7_500_000, "held_micros": 0},
        "to_balance": {"available_micros": 2_500_000, "held_micros": 0},
        "idempotent_replay": False,
        "receipt": {"body": {"from": "acct_alice", "to": "acct_bob"}, "hash": "aa"},
        "attestation": {"format": "mint-transfer-attestation-v1"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "data": evidence})

    c = MintClient(
        "http://mint.test",
        "secret-key",
        "acct_treasury",
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://mint.test"
        ),
    )
    result = c.transfer("acct_alice", address, 2_500_000, "p2p:1", "menivor:p2p:1")
    assert captured == {
        "from": "acct_alice",
        "to": address,
        "amount_micros": 2_500_000,
        "idem_key": "p2p:1",
        "ref": "menivor:p2p:1",
    }
    assert result == evidence


def test_create_hold_moves_available_to_held(fake, client):
    acct = client.create_account()
    receipt = client.create_hold(
        from_account=acct, amount_micros=600_000, idem_key="job1", ref="q1"
    )
    assert receipt["hold_id"].startswith("hold_")
    assert receipt["status"] == "open"
    assert fake.accounts[acct]["held"] == 600_000
    assert fake.accounts[acct]["available"] == fake.default_balance - 600_000


def test_capture_hold_moves_to_treasury(fake, client):
    acct = client.create_account()
    receipt = client.create_hold(
        from_account=acct, amount_micros=600_000, idem_key="job1"
    )
    hold_id = receipt["hold_id"]
    cap = client.capture_hold(
        hold_id, amount_micros=400_000, to=fake.treasury_id, idem_key="job1:capture"
    )
    assert cap["captured_micros"] == 400_000
    assert fake.accounts[fake.treasury_id]["available"] == 400_000
    # A single capture settles the whole hold: the uncaptured 200_000 remainder
    # is atomically returned to the payer and the hold is closed (real Mint
    # semantics — no separate release is needed).
    assert fake.accounts[acct]["held"] == 0
    assert fake.accounts[acct]["available"] == fake.default_balance - 400_000


def test_release_hold_returns_remainder(fake, client):
    acct = client.create_account()
    receipt = client.create_hold(
        from_account=acct, amount_micros=600_000, idem_key="job1"
    )
    hold_id = receipt["hold_id"]
    rel = client.release_hold(hold_id, idem_key="job1:release")
    assert rel["status"] == "released"
    assert rel["released_micros"] == 600_000
    assert fake.accounts[acct]["held"] == 0
    assert fake.accounts[acct]["available"] == fake.default_balance


def test_receipted_capture_and_release_bind_exact_economic_amount(fake, client):
    capture_account = client.create_account()
    capture_hold = client.create_hold(
        from_account=capture_account, amount_micros=600_000, idem_key="cap:hold"
    )
    capture_data, capture_receipt = client.capture_hold_with_receipt(
        capture_hold["hold_id"],
        amount_micros=420_000,
        to=fake.treasury_id,
        idem_key="cap:terminal",
        ref="gateway_capture",
    )
    assert capture_data["attestation"]["format"] == (
        "mint-hold-settlement-attestation-v1"
    )
    assert capture_receipt["op"] == "hold.capture"
    assert capture_receipt["amount_micros"] == 420_000

    release_account = client.create_account()
    release_hold = client.create_hold(
        from_account=release_account, amount_micros=600_000, idem_key="rel:hold"
    )
    release_data, release_receipt = client.release_hold_with_receipt(
        release_hold["hold_id"],
        amount_micros=600_000,
        idem_key="rel:terminal",
        ref="gateway_release",
    )
    assert release_data["attestation"]["format"] == (
        "mint-hold-settlement-attestation-v1"
    )
    assert release_receipt["op"] == "hold.release"
    assert release_receipt["amount_micros"] == 600_000


def test_receipted_release_rejects_zero_expected_amount(fake, client):
    account = client.create_account()
    hold = client.create_hold(
        from_account=account, amount_micros=600_000, idem_key="zero:hold"
    )
    with pytest.raises(WalletBridgeError, match="does not match"):
        client.release_hold_with_receipt(
            hold["hold_id"],
            amount_micros=0,
            idem_key="zero:terminal",
            ref="gateway_release",
        )


def test_read_balance(fake, client):
    acct = client.create_account()
    client.create_hold(from_account=acct, amount_micros=100_000, idem_key="j")
    bal = client.read_balance(acct)
    assert bal["account_id"] == acct
    assert bal["available_micros"] == fake.default_balance - 100_000
    assert bal["held_micros"] == 100_000


def test_mint_deposit_credits_once(fake):
    fake.default_balance = 0
    client = make_mint_client(fake)
    acct = client.create_account()
    first = client.mint_deposit(acct, 20_000_000, "creem:chk_1", "wallet:pi_1")
    replay = client.mint_deposit(acct, 20_000_000, "creem:chk_1", "retry:pi_1")
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert fake.accounts[acct]["available"] == 20_000_000


def test_get_hold(fake, client):
    acct = client.create_account()
    receipt = client.create_hold(from_account=acct, amount_micros=100_000, idem_key="j")
    got = client.get_hold(receipt["hold_id"])
    assert got["hold_id"] == receipt["hold_id"]
    assert got["amount_micros"] == 100_000


def test_amounts_sent_as_bare_ints():
    """The client must send integer microdollars — never floats or strings."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content.decode())
        captured["header"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={"success": True, "data": {"hold_id": "h1"}})

    transport = httpx.MockTransport(handler)
    c = MintClient(
        "http://mint.test",
        "secret-key",
        "acct_treasury",
        client=httpx.Client(transport=transport, base_url="http://mint.test"),
    )
    c.create_hold(from_account="acct_1", amount_micros=600_000, idem_key="j")
    assert captured["body"]["amount_micros"] == 600_000
    assert isinstance(captured["body"]["amount_micros"], int)
    # x-api-key header must be present on every write.
    assert captured["header"] == "secret-key"


# --------------------------------------------------------------------------- #
# Error mapping
# --------------------------------------------------------------------------- #
def _error_client(status: int, code: str, message: str) -> MintClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json={"success": False, "error": {"code": code, "message": message}}
        )

    transport = httpx.MockTransport(handler)
    return MintClient(
        "http://mint.test",
        "k",
        "acct_treasury",
        client=httpx.Client(transport=transport, base_url="http://mint.test"),
    )


@pytest.mark.parametrize(
    "status,code",
    [
        (402, "InsufficientFunds"),
        (409, "IdempotencyConflict"),
        (422, "CaptureExceedsHold"),
        (403, "AccountFrozen"),
    ],
)
def test_error_status_maps_to_wallet_bridge_error(status, code):
    client = _error_client(status, code, f"{code} happened")
    with pytest.raises(WalletBridgeError) as ei:
        client.create_hold(from_account="a", amount_micros=1, idem_key="j")
    assert ei.value.status_code == status
    assert code in ei.value.message  # message carried through from the envelope


def test_insufficient_funds_from_fake_maps_402(fake):
    fake.default_balance = 100
    client = make_mint_client(fake)
    acct = client.create_account()
    with pytest.raises(WalletBridgeError) as ei:
        client.create_hold(from_account=acct, amount_micros=1_000, idem_key="j")
    assert ei.value.status_code == 402


def test_capture_exceeds_hold_maps_422(fake, client):
    acct = client.create_account()
    receipt = client.create_hold(from_account=acct, amount_micros=500, idem_key="j")
    with pytest.raises(WalletBridgeError) as ei:
        client.capture_hold(
            receipt["hold_id"], amount_micros=999, to=fake.treasury_id, idem_key="j:cap"
        )
    assert ei.value.status_code == 422


def test_transport_error_maps_to_502():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    transport = httpx.MockTransport(handler)
    client = MintClient(
        "http://mint.test",
        "k",
        "acct_treasury",
        client=httpx.Client(transport=transport, base_url="http://mint.test"),
    )
    with pytest.raises(WalletBridgeError) as ei:
        client.create_hold(from_account="a", amount_micros=1, idem_key="j")
    assert ei.value.status_code == 502
    assert "unreachable" in ei.value.message


def test_idempotent_replay_returns_same_receipt(fake, client):
    acct = client.create_account()
    r1 = client.create_hold(from_account=acct, amount_micros=500, idem_key="dup")
    r2 = client.create_hold(from_account=acct, amount_micros=500, idem_key="dup")
    assert r1["hold_id"] == r2["hold_id"]
    assert r2["idempotent_replay"] is True
    # Only one hold effect: held moved once, not twice.
    assert fake.accounts[acct]["held"] == 500
