from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace

import blake3
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.domains.wallet.hold_settlement_attestation import (
    HoldSettlementAttestationError,
    HoldSettlementExpected,
    verify_hold_settlement_attestation,
)


def _commit(domain: bytes, *parts: str) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    for index, part in enumerate(parts):
        if index:
            digest.update(b"\0")
        digest.update(part.encode())
    return digest.hexdigest()


def _fixture(operation: str = "hold.capture", amount: int = 420_000):
    private = Ed25519PrivateKey.generate()
    payee = "acct_treasury" if operation == "hold.capture" else ""
    idem_key = "media:job_1:capture" if payee else "media:job_1:release"
    body = {"op": operation, "hold_id": "hold_123"}
    if operation == "hold.capture":
        body.update(amount_micros=amount, to=payee)
    body.update(idem_key=idem_key, ref="gateway_job_1")
    op_hash = blake3.blake3(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt = {
        "seq": 7,
        "op": operation,
        "op_hash": op_hash,
        "amount_micros": amount,
        "hash": "22" * 32,
        "sig": "33" * 64,
    }
    expected = HoldSettlementExpected(
        operation=operation,
        hold_id="hold_123",
        payer_account="acct_payer",
        payee_account=payee,
        amount_micros=amount,
        idempotency_key=idem_key,
        reference="gateway_job_1",
        receipt=receipt,
    )
    party_domain = b"mint-hold-settlement-party-v1\0"
    claims = {
        "version": 1,
        "asset": "AIT",
        "unit": "micro_usd",
        "sequence": 7,
        "operation": operation,
        "operation_hash": op_hash,
        "amount_micros": amount,
        "receipt_hash": receipt["hash"],
        "timestamp_ms": 1_700_000_000_123,
        "reference_hash": _commit(
            b"mint-hold-settlement-reference-v1\0", expected.reference
        ),
        "hold_commitment": _commit(
            b"mint-hold-settlement-hold-v1\0", expected.hold_id, op_hash
        ),
        "payer_commitment": _commit(
            party_domain, "payer", expected.payer_account, op_hash
        ),
        "payee_commitment": (
            _commit(party_domain, "payee", payee, op_hash)
            if payee
            else _commit(party_domain, "no-payee", op_hash)
        ),
        "signer_key_id": "mint-key-1",
    }
    payload = json.dumps(claims, separators=(",", ":")).encode()
    digest = hashlib.sha256(
        b"mint-hold-settlement-attestation-v1\0" + payload
    ).digest()
    envelope = {
        "format": "mint-hold-settlement-attestation-v1",
        "payload_base64url": base64.urlsafe_b64encode(payload).rstrip(b"=").decode(),
        "digest_sha256": digest.hex(),
        "signer_key_id": "mint-key-1",
        "signature_hex": private.sign(digest).hex(),
    }
    return envelope, expected, {"mint-key-1": private.public_key()}


@pytest.mark.parametrize("operation", ["hold.capture", "hold.release"])
def test_valid_terminal_attestation_binds_exact_positive_amount(operation):
    envelope, expected, keys = _fixture(operation)
    verified = verify_hold_settlement_attestation(envelope, expected, keys)
    assert verified.claims["operation"] == operation
    assert verified.claims["amount_micros"] == 420_000


@pytest.mark.parametrize(
    "field,value",
    [
        ("hold_id", "hold_other"),
        ("reference", "gateway_other"),
        ("payer_account", "acct_other"),
        ("payee_account", "acct_other"),
        ("amount_micros", 1),
        ("idempotency_key", "other-key"),
    ],
)
def test_signed_claims_fail_when_durable_intent_differs(field, value):
    envelope, expected, keys = _fixture()
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(
            envelope, replace(expected, **{field: value}), keys
        )


def test_release_amount_is_economic_amount_not_zero():
    envelope, expected, keys = _fixture("hold.release", 600_000)
    assert verify_hold_settlement_attestation(envelope, expected, keys).claims[
        "amount_micros"
    ] == 600_000
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(
            envelope, replace(expected, amount_micros=0), keys
        )


def test_receipt_substitution_tampering_and_unpinned_signer_fail_closed():
    envelope, expected, keys = _fixture()
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(
            envelope,
            replace(expected, receipt={**expected.receipt, "hash": "44" * 32}),
            keys,
        )
    tampered = dict(envelope)
    tampered["payload_base64url"] = tampered["payload_base64url"][:-1] + "A"
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(tampered, expected, keys)
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(envelope, expected, {})
