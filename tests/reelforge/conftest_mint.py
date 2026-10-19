"""In-memory fake mint-server as an ``httpx.MockTransport`` handler.

Implements the subset of the Mint ``/v1`` HTTP surface the ReelForge wallet
bridge talks to — accounts, holds, capture, release, balance — with the real
``{success, data}`` / ``{success, error}`` envelope, integer microdollars, and
idem_key replay. No network and no live server: :class:`FakeMint` keeps all
state in Python dicts so tests can both drive the client and assert the exact
money movements it caused.

Enforced money rules (mirroring the live Mint):

* a hold that exceeds the payer's available balance → **402** InsufficientFunds;
* a capture that exceeds the still-held remainder → **422** CaptureExceedsHold;
* a write whose ``idem_key`` was already seen replays the same receipt with
  ``idempotent_replay=true`` (never a second money movement).
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import blake3
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MINT_ATTESTATION_TEST_PRIVATE_KEY_HEX = (
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
MINT_ATTESTATION_TEST_PUBLIC_KEY_HEX = (
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
MINT_ATTESTATION_TEST_KEY_ID = "mint-test-key-1"

# Default balance auto-granted to every freshly-created payer account so holds
# succeed without a separate funding call. Tests that exercise the
# insufficient-funds path set ``FakeMint.default_balance`` to a small number.
_DEFAULT_BALANCE = 1_000_000_000


class FakeMint:
    """A tiny in-memory Mint used as an ``httpx.MockTransport`` handler."""

    def __init__(self, *, default_balance: int = _DEFAULT_BALANCE) -> None:
        self.default_balance = default_balance
        self.accounts: dict[str, dict[str, Any]] = {}
        self.addresses: dict[str, str] = {}
        self.holds: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, tuple[int, dict, dict[str, str]]] = {}
        self._acct_seq = 0
        self._hold_seq = 0
        self._address_seq = 0
        self._seq = 0
        # Capture destination (treasury) account, created on first capture.
        self.treasury_id = "acct_treasury"
        self.accounts[self.treasury_id] = {
            "available": 0,
            "held": 0,
            "kind": "Treasury",
            "owner_ref": None,
        }

    # ------------------------------------------------------------------ #
    # Test helpers
    # ------------------------------------------------------------------ #
    def fund(self, account_id: str, micros: int) -> None:
        self._ensure_account(account_id)["available"] += int(micros)

    def _ensure_account(self, account_id: str) -> dict[str, Any]:
        return self.accounts.setdefault(
            account_id,
            {"available": 0, "held": 0, "kind": "User", "owner_ref": None},
        )

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ------------------------------------------------------------------ #
    # Envelope helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _ok(
        data: Any,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return httpx.Response(
            status,
            json={"success": True, "data": data},
            headers=headers,
        )

    @staticmethod
    def _err(status: int, code: str, message: str) -> httpx.Response:
        return httpx.Response(
            status,
            json={"success": False, "error": {"code": code, "message": message}},
        )

    # ------------------------------------------------------------------ #
    # MockTransport entrypoint
    # ------------------------------------------------------------------ #
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method.upper()
        body: dict[str, Any] = {}
        if request.content:
            try:
                body = json.loads(request.content.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = {}

        if method == "POST" and path == "/v1/accounts":
            return self._create_account(body)
        if (
            method == "POST"
            and path.startswith("/v1/accounts/")
            and path.endswith("/addresses")
        ):
            account_id = path[len("/v1/accounts/") : -len("/addresses")]
            return self._create_address(account_id, body)
        if method == "GET" and path.startswith("/v1/addresses/"):
            return self._lookup_address(path[len("/v1/addresses/") :])
        if method == "POST" and path == "/v1/mint":
            return self._mint(body)
        if method == "POST" and path == "/v1/transfers":
            return self._transfer(body)
        if method == "POST" and path == "/v1/holds":
            return self._create_hold(body)
        if (
            method == "POST"
            and path.startswith("/v1/holds/")
            and path.endswith("/capture")
        ):
            hold_id = path[len("/v1/holds/") : -len("/capture")]
            return self._capture_hold(hold_id, body)
        if (
            method == "POST"
            and path.startswith("/v1/holds/")
            and path.endswith("/release")
        ):
            hold_id = path[len("/v1/holds/") : -len("/release")]
            return self._release_hold(hold_id, body)
        if method == "GET" and path.startswith("/v1/holds/"):
            return self._get_hold(path[len("/v1/holds/") :])
        if (
            method == "GET"
            and path.startswith("/v1/accounts/")
            and path.endswith("/balance")
        ):
            acct = path[len("/v1/accounts/") : -len("/balance")]
            return self._balance(acct)
        return self._err(404, "NotFound", f"no route for {method} {path}")

    # ------------------------------------------------------------------ #
    # Routes
    # ------------------------------------------------------------------ #
    def _create_account(self, body: dict) -> httpx.Response:
        self._acct_seq += 1
        account_id = f"acct_{self._acct_seq}"
        self.accounts[account_id] = {
            "available": self.default_balance,
            "held": 0,
            "kind": body.get("kind", "User"),
            "owner_ref": body.get("owner_ref"),
        }
        return self._ok({"account_id": account_id})

    def _create_address(self, account_id: str, body: dict) -> httpx.Response:
        if account_id not in self.accounts:
            return self._err(404, "AccountNotFound", f"no account {account_id}")
        self._address_seq += 1
        address = f"ait1qtest{self._address_seq:08d}"
        self.addresses[address] = account_id
        return self._ok(
            {
                "address": address,
                "account_id": account_id,
                "purpose": str(body.get("purpose", "receive")),
            },
            201,
        )

    def _lookup_address(self, address: str) -> httpx.Response:
        account_id = self.addresses.get(address)
        if account_id is None:
            return self._err(404, "AddressNotFound", "address not found")
        return self._ok({"address": address, "account_id": account_id})

    def _mint(self, body: dict) -> httpx.Response:
        deposit_ref = str(body.get("deposit_ref", ""))
        replay = self._replay(f"mint:{deposit_ref}")
        if replay is not None:
            return replay
        account_id = str(body.get("to", ""))
        account = self.accounts.get(account_id)
        if account is None:
            return self._err(404, "AccountNotFound", f"no account {account_id}")
        amount = int(body.get("amount_micros", 0) or 0)
        if amount <= 0:
            return self._err(422, "InvalidAmount", "amount_micros must be positive")
        account["available"] += amount
        data = {
            "to_balance": {
                "available_micros": account["available"],
                "held_micros": account["held"],
            },
            "deposit_ref": deposit_ref,
            "idempotent_replay": False,
        }
        self._remember(f"mint:{deposit_ref}", data)
        return self._ok(data, 201)

    def _transfer(self, body: dict) -> httpx.Response:
        idem_key = str(body.get("idem_key", ""))
        replay = self._replay(idem_key)
        if replay is not None:
            return replay
        from_id = str(body.get("from", ""))
        to_id = str(body.get("to", ""))
        if from_id == to_id:
            return self._err(422, "SelfTransfer", "source and destination must differ")
        sender = self.accounts.get(from_id)
        recipient = self.accounts.get(to_id)
        if sender is None or recipient is None:
            return self._err(404, "AccountNotFound", "transfer account not found")
        amount = int(body.get("amount_micros", 0) or 0)
        if amount <= 0:
            return self._err(422, "InvalidAmount", "amount_micros must be positive")
        if sender["available"] < amount:
            return self._err(402, "InsufficientFunds", "insufficient available balance")
        sender["available"] -= amount
        recipient["available"] += amount
        first_seq = self._next_seq()
        operation_hash = "ab" * 32
        receipt_hash = "cd" * 32
        timestamp_ms = 1_777_777_777_000 + first_seq
        data = {
            "first_seq": first_seq,
            "from_balance": {
                "available_micros": sender["available"],
                "held_micros": sender["held"],
            },
            "to_balance": {
                "available_micros": recipient["available"],
                "held_micros": recipient["held"],
            },
            "idempotent_replay": False,
            "receipt": {
                "body": {
                    "account_id": from_id,
                    "account_seq": first_seq,
                    "journal_seq": first_seq,
                    "op": "Transfer",
                    "op_hash": operation_hash,
                    "amount_micros": amount,
                    "from": from_id,
                    "to": to_id,
                    "balance_after_available_micros": sender["available"],
                    "balance_after_held_micros": sender["held"],
                    "ts": timestamp_ms,
                    "prev_hash": "00" * 32,
                    "signer": "mint-test-key-1",
                },
                "hash": receipt_hash,
                "sig": "ef" * 64,
            },
        }
        data["attestation"] = self._transfer_attestation(
            sender=from_id,
            recipient=to_id,
            mint_operation=str(body.get("ref", "")),
            amount_micros=amount,
            sequence=first_seq,
            operation_hash=operation_hash,
            receipt_hash=receipt_hash,
            timestamp_ms=timestamp_ms,
        )
        self._remember(idem_key, data)
        return self._ok(data)

    @staticmethod
    def _transfer_attestation(
        *,
        sender: str,
        recipient: str,
        mint_operation: str,
        amount_micros: int,
        sequence: int,
        operation_hash: str,
        receipt_hash: str,
        timestamp_ms: int,
    ) -> dict[str, str]:
        def party(role: str, account_id: str) -> str:
            return hashlib.sha256(
                b"mint-transfer-party-v1\0"
                + role.encode("ascii")
                + b"\0"
                + account_id.encode("utf-8")
                + b"\0"
                + operation_hash.encode("ascii")
            ).hexdigest()

        claims = {
            "version": 1,
            "asset": "AIT",
            "unit": "micro_usd",
            "sequence": sequence,
            "operation": "Transfer",
            "operation_hash": operation_hash,
            "amount_micros": amount_micros,
            "receipt_hash": receipt_hash,
            "timestamp_ms": timestamp_ms,
            "reference_hash": hashlib.sha256(
                b"mint-transfer-reference-v1\0" + mint_operation.encode("utf-8")
            ).hexdigest(),
            "sender_commitment": party("sender", sender),
            "recipient_commitment": party("recipient", recipient),
            "signer_key_id": MINT_ATTESTATION_TEST_KEY_ID,
        }
        payload = json.dumps(claims, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        digest = hashlib.sha256(b"mint-transfer-attestation-v1\0" + payload).digest()
        private_key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(MINT_ATTESTATION_TEST_PRIVATE_KEY_HEX)
        )
        return {
            "format": "mint-transfer-attestation-v1",
            "payload_base64url": base64.urlsafe_b64encode(payload)
            .rstrip(b"=")
            .decode("ascii"),
            "digest_sha256": digest.hex(),
            "signer_key_id": MINT_ATTESTATION_TEST_KEY_ID,
            "signature_hex": private_key.sign(digest).hex(),
        }

    def _replay(self, idem_key: str | None) -> httpx.Response | None:
        if idem_key and idem_key in self._idem:
            status, data, headers = self._idem[idem_key]
            replayed = {**data, "idempotent_replay": True}
            return self._ok(replayed, status, headers)
        return None

    def _remember(
        self,
        idem_key: str | None,
        data: dict,
        headers: dict[str, str] | None = None,
    ) -> None:
        if idem_key:
            self._idem[idem_key] = (200, data, dict(headers or {}))

    @staticmethod
    def _hold_operation_hash(
        operation: str,
        *,
        hold_id: str,
        idem_key: str,
        reference: str,
        amount_micros: int,
        payee: str,
    ) -> str:
        body: dict[str, Any] = {
            "op": operation,
            "hold_id": hold_id,
        }
        if operation == "hold.capture":
            body.update(amount_micros=amount_micros, to=payee)
        body.update(idem_key=idem_key, ref=reference or None)
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        return blake3.blake3(canonical).hexdigest()

    @staticmethod
    def _hold_settlement_evidence(
        *,
        operation: str,
        hold_id: str,
        payer: str,
        payee: str,
        amount_micros: int,
        idem_key: str,
        reference: str,
        sequence: int,
    ) -> tuple[dict[str, str], dict[str, str]]:
        operation_hash = FakeMint._hold_operation_hash(
            operation,
            hold_id=hold_id,
            idem_key=idem_key,
            reference=reference,
            amount_micros=amount_micros,
            payee=payee,
        )
        receipt_hash = hashlib.sha256(
            (
                "mint-test-receipt-v1\0"
                f"{sequence}\0{operation}\0{operation_hash}\0{amount_micros}"
            ).encode()
        ).hexdigest()
        private_key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(MINT_ATTESTATION_TEST_PRIVATE_KEY_HEX)
        )
        receipt = {
            "seq": sequence,
            "op": operation,
            "op_hash": operation_hash,
            "amount_micros": amount_micros,
            "hash": receipt_hash,
            "sig": private_key.sign(bytes.fromhex(receipt_hash)).hex(),
        }

        def commit(domain: bytes, *parts: str) -> str:
            digest = hashlib.sha256()
            digest.update(domain)
            for index, part in enumerate(parts):
                if index:
                    digest.update(b"\0")
                digest.update(part.encode())
            return digest.hexdigest()

        claims = {
            "version": 1,
            "asset": "AIT",
            "unit": "micro_usd",
            "sequence": sequence,
            "operation": operation,
            "operation_hash": operation_hash,
            "amount_micros": amount_micros,
            "receipt_hash": receipt_hash,
            "timestamp_ms": 1_777_777_777_000 + sequence,
            "reference_hash": commit(b"mint-hold-settlement-reference-v1\0", reference),
            "hold_commitment": commit(
                b"mint-hold-settlement-hold-v1\0", hold_id, operation_hash
            ),
            "payer_commitment": commit(
                b"mint-hold-settlement-party-v1\0",
                "payer",
                payer,
                operation_hash,
            ),
            "payee_commitment": (
                commit(
                    b"mint-hold-settlement-party-v1\0",
                    "payee",
                    payee,
                    operation_hash,
                )
                if operation == "hold.capture"
                else commit(
                    b"mint-hold-settlement-party-v1\0",
                    "no-payee",
                    operation_hash,
                )
            ),
            "signer_key_id": MINT_ATTESTATION_TEST_KEY_ID,
        }
        payload = json.dumps(claims, ensure_ascii=False, separators=(",", ":")).encode()
        digest = hashlib.sha256(
            b"mint-hold-settlement-attestation-v1\0" + payload
        ).digest()
        attestation = {
            "format": "mint-hold-settlement-attestation-v1",
            "payload_base64url": base64.urlsafe_b64encode(payload)
            .rstrip(b"=")
            .decode(),
            "digest_sha256": digest.hex(),
            "signer_key_id": MINT_ATTESTATION_TEST_KEY_ID,
            "signature_hex": private_key.sign(digest).hex(),
        }
        receipt_header = (
            base64.urlsafe_b64encode(
                json.dumps(receipt, separators=(",", ":")).encode()
            )
            .rstrip(b"=")
            .decode()
        )
        return attestation, {"AITP-Receipt": receipt_header}

    def _create_hold(self, body: dict) -> httpx.Response:
        idem_key = body.get("idem_key")
        replay = self._replay(idem_key)
        if replay is not None:
            return replay
        from_account = str(body.get("from", ""))
        amount = int(body.get("amount_micros", 0) or 0)
        account = self.accounts.get(from_account)
        if account is None:
            return self._err(404, "AccountNotFound", f"no account {from_account}")
        if amount <= 0:
            return self._err(422, "InvalidAmount", "amount_micros must be positive")
        if account["available"] < amount:
            return self._err(
                402, "InsufficientFunds", "insufficient available balance for hold"
            )
        account["available"] -= amount
        account["held"] += amount
        self._hold_seq += 1
        hold_id = f"hold_{self._hold_seq}"
        self.holds[hold_id] = {
            "hold_id": hold_id,
            "from": from_account,
            "amount_micros": amount,
            "captured_micros": 0,
            "status": "open",
            "ref": body.get("ref"),
        }
        data = {
            "hold_id": hold_id,
            "first_seq": self._next_seq(),
            "holder_balance": {
                "available_micros": account["available"],
                "held_micros": account["held"],
            },
            "status": "open",
            "captured_micros": 0,
            "idempotent_replay": False,
        }
        self._remember(idem_key, data)
        return self._ok(data)

    def _capture_hold(self, hold_id: str, body: dict) -> httpx.Response:
        idem_key = body.get("idem_key")
        replay = self._replay(idem_key)
        if replay is not None:
            return replay
        hold = self.holds.get(hold_id)
        if hold is None:
            return self._err(404, "HoldNotFound", f"no hold {hold_id}")
        amount = int(body.get("amount_micros", 0) or 0)
        remaining = hold["amount_micros"] - hold["captured_micros"]
        if amount < 0:
            return self._err(
                422, "InvalidAmount", "capture amount must be non-negative"
            )
        if amount > remaining:
            return self._err(
                422, "CaptureExceedsHold", "capture exceeds remaining held amount"
            )
        payer = self.accounts[hold["from"]]
        to = str(body.get("to", "")) or self.treasury_id
        treasury = self._ensure_account(to)
        # Faithful to the real mint-server: a single capture settles the WHOLE
        # hold. It credits `amount` to the treasury AND atomically returns the
        # uncaptured remainder to the payer, clearing the held funds and closing
        # the hold (verified against the live server — a later release of a
        # captured hold is HoldNotFound, see `_release_hold`).
        uncaptured = remaining - amount
        payer["held"] -= remaining
        payer["available"] += uncaptured
        treasury["available"] += amount
        hold["captured_micros"] += amount
        hold["status"] = "captured"
        data = {
            "hold_id": hold_id,
            "captured_micros": hold["captured_micros"],
            "status": "captured",
            "idempotent_replay": False,
        }
        sequence = self._next_seq()
        attestation, headers = self._hold_settlement_evidence(
            operation="hold.capture",
            hold_id=hold_id,
            payer=str(hold["from"]),
            payee=to,
            amount_micros=amount,
            idem_key=str(idem_key or ""),
            reference=str(body.get("ref", "") or ""),
            sequence=sequence,
        )
        data["attestation"] = attestation
        self._remember(idem_key, data, headers)
        return self._ok(data, headers=headers)

    def _release_hold(self, hold_id: str, body: dict) -> httpx.Response:
        idem_key = body.get("idem_key")
        replay = self._replay(idem_key)
        if replay is not None:
            return replay
        hold = self.holds.get(hold_id)
        if hold is None:
            return self._err(404, "HoldNotFound", f"no hold {hold_id}")
        # A captured hold is already closed (capture returned the remainder). The
        # real mint-server reports HoldNotFound for a release against it, so the
        # production settle path must never chase a capture with a release.
        if hold["status"] == "captured":
            return self._err(404, "HoldNotFound", f"hold {hold_id} already captured")
        remaining = hold["amount_micros"] - hold["captured_micros"]
        payer = self.accounts[hold["from"]]
        if remaining > 0:
            payer["held"] -= remaining
            payer["available"] += remaining
        hold["status"] = "released"
        data = {
            "hold_id": hold_id,
            "released_micros": remaining,
            "status": "released",
            "idempotent_replay": False,
        }
        sequence = self._next_seq()
        attestation, headers = self._hold_settlement_evidence(
            operation="hold.release",
            hold_id=hold_id,
            payer=str(hold["from"]),
            payee="",
            amount_micros=remaining,
            idem_key=str(idem_key or ""),
            reference=str(body.get("ref", "") or ""),
            sequence=sequence,
        )
        data["attestation"] = attestation
        self._remember(idem_key, data, headers)
        return self._ok(data, headers=headers)

    def _get_hold(self, hold_id: str) -> httpx.Response:
        hold = self.holds.get(hold_id)
        if hold is None:
            return self._err(404, "HoldNotFound", f"no hold {hold_id}")
        return self._ok(dict(hold))

    def _balance(self, account_id: str) -> httpx.Response:
        account = self.accounts.get(account_id)
        if account is None:
            return self._err(404, "AccountNotFound", f"no account {account_id}")
        return self._ok(
            {
                "account_id": account_id,
                "available_micros": account["available"],
                "held_micros": account["held"],
                "updated_seq": self._next_seq(),
            }
        )


def make_mint_client(fake: FakeMint, *, treasury_account: str | None = None):
    """Build a real :class:`MintClient` wired to ``fake`` via ``MockTransport``.

    Uses an actual ``httpx.Client`` (real client object, no network) so the
    production code path — headers, JSON encoding, envelope parsing — is
    exercised end to end against the in-memory Mint.
    """
    from app.domains.wallet.mint_client import MintClient

    transport = httpx.MockTransport(fake.handler)
    client = httpx.Client(transport=transport, base_url="http://mint.test")
    return MintClient(
        "http://mint.test",
        "test-api-key",
        treasury_account or fake.treasury_id,
        client=client,
    )
