"""Fixture-parity tests for the Mint hold-settlement attestation verifier.

Drives a REAL, end-to-end signed ``mint-hold-settlement-attestation-v1`` vector
through the in-memory :class:`FakeMint` (which signs with the RFC 8032 known test
ed25519 key, key id ``mint-test-key-1``, and computes the canonical BLAKE3
operation hash exactly like the live Mint) and then feeds it to the SAME
production verifier and pinned-key loader the media gateway uses at settlement
(``verify_hold_settlement_attestation`` + ``load_pinned_public_keys``).

No live server, no network -- a fixed test vector, exactly per the hardening
brief. Locks four properties of the verifier:

  (a) it recomputes the canonical BLAKE3 operation hash and binds the receipt;
  (b) it verifies the ed25519 signature against the *pinned* public key;
  (c) it is ORDER-INSENSITIVE on the transport envelope (the earlier
      key-order attestation-drift bug); and
  (d) it fails CLOSED on a tampered receipt, wrong signing key, unpinned signer,
      tampered digest, and a tampered payload.
"""

from __future__ import annotations

import base64
import json

import blake3
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.domains.wallet.hold_settlement_attestation import (
    HoldSettlementAttestationError,
    HoldSettlementExpected,
    verify_hold_settlement_attestation,
)
from app.domains.wallet.transfer_attestation import load_pinned_public_keys

from tests.reelforge.conftest_mint import (
    MINT_ATTESTATION_TEST_KEY_ID,
    MINT_ATTESTATION_TEST_PUBLIC_KEY_HEX,
    FakeMint,
    make_mint_client,
)


def _drive_capture_vector():
    """Return ``(envelope, expected, pinned_keys, receipt)`` for a real capture.

    Exercises the production ``capture_hold_with_receipt`` decode path against a
    freshly-signed FakeMint attestation, so the envelope, digest, signature,
    canonical claims, BLAKE3 op-hash and AITP receipt are all genuine.
    """
    fake = FakeMint()
    client = make_mint_client(fake)
    payer = client.create_account()
    hold = client.create_hold(
        from_account=payer, amount_micros=600_000, idem_key="media:job_1:hold"
    )
    data, receipt = client.capture_hold_with_receipt(
        hold["hold_id"],
        amount_micros=420_000,
        to=fake.treasury_id,
        idem_key="media:job_1:capture",
        ref="gateway_job_1",
    )
    envelope = data["attestation"]
    expected = HoldSettlementExpected(
        operation="hold.capture",
        hold_id=hold["hold_id"],
        payer_account=payer,
        payee_account=fake.treasury_id,
        amount_micros=420_000,
        idempotency_key="media:job_1:capture",
        reference="gateway_job_1",
        receipt=receipt,
    )
    # Pin exactly like production: config JSON of key id -> lowercase pub hex.
    pinned_keys = load_pinned_public_keys(
        json.dumps({MINT_ATTESTATION_TEST_KEY_ID: MINT_ATTESTATION_TEST_PUBLIC_KEY_HEX})
    )
    return envelope, expected, pinned_keys, receipt


def _decode_claims(envelope: dict) -> dict:
    payload_b64 = envelope["payload_base64url"]
    payload = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
    return json.loads(payload)


# --------------------------------------------------------------------------- #
# (a) canonical BLAKE3 recompute + receipt binding, (b) pinned-key ed25519
# --------------------------------------------------------------------------- #
def test_valid_capture_recomputes_blake3_and_verifies_against_pinned_key():
    envelope, expected, pinned_keys, receipt = _drive_capture_vector()

    verified = verify_hold_settlement_attestation(envelope, expected, pinned_keys)
    assert verified.claims["operation"] == "hold.capture"
    assert verified.claims["amount_micros"] == 420_000
    assert verified.claims["signer_key_id"] == MINT_ATTESTATION_TEST_KEY_ID

    # (a) The verifier's own canonical BLAKE3 operation hash independently
    # matches what Mint signed AND what the AITP receipt carries.
    canonical_op = json.dumps(
        {
            "op": "hold.capture",
            "hold_id": expected.hold_id,
            "amount_micros": 420_000,
            "to": expected.payee_account,
            "idem_key": expected.idempotency_key,
            "ref": expected.reference,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    recomputed = blake3.blake3(canonical_op).hexdigest()
    assert verified.claims["operation_hash"] == recomputed
    assert receipt["op_hash"] == recomputed
    assert verified.claims["receipt_hash"] == receipt["hash"]


# --------------------------------------------------------------------------- #
# (c) envelope key-order insensitivity (the earlier attestation-drift bug)
# --------------------------------------------------------------------------- #
def test_envelope_is_order_insensitive():
    envelope, expected, pinned_keys, _ = _drive_capture_vector()

    # Rebuild the envelope with its keys in REVERSED insertion order. The signed
    # payload is byte-identical; only the unsigned transport wrapper's key order
    # changes. The verifier must accept it (it validates the key SET, not order).
    reordered = {key: envelope[key] for key in reversed(list(envelope))}
    assert list(reordered) != list(envelope)  # order genuinely differs

    verified = verify_hold_settlement_attestation(reordered, expected, pinned_keys)
    assert verified.claims["operation_hash"] == _decode_claims(envelope)["operation_hash"]


# --------------------------------------------------------------------------- #
# (d) fail-closed rejections
# --------------------------------------------------------------------------- #
def test_rejects_tampered_receipt_hash():
    envelope, expected, pinned_keys, receipt = _drive_capture_vector()
    from dataclasses import replace

    tampered = replace(expected, receipt={**receipt, "hash": "44" * 32})
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(envelope, tampered, pinned_keys)


def test_rejects_wrong_signing_key():
    envelope, expected, _pinned, _receipt = _drive_capture_vector()
    # Same key id, but pinned to a DIFFERENT public key -> signature invalid.
    wrong_pub = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(
            envelope, expected, {MINT_ATTESTATION_TEST_KEY_ID: wrong_pub}
        )


def test_rejects_unpinned_signer():
    envelope, expected, _pinned, _receipt = _drive_capture_vector()
    # No key pinned under the envelope's signer id -> "signer is not pinned".
    other = load_pinned_public_keys(
        json.dumps({"some-other-key": MINT_ATTESTATION_TEST_PUBLIC_KEY_HEX})
    )
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(envelope, expected, other)
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(envelope, expected, {})


def test_rejects_tampered_digest():
    envelope, expected, pinned_keys, _receipt = _drive_capture_vector()
    tampered = {**envelope, "digest_sha256": "00" * 32}
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(tampered, expected, pinned_keys)


def test_rejects_tampered_payload():
    envelope, expected, pinned_keys, _receipt = _drive_capture_vector()
    # Flip the last base64url char so the payload no longer matches the signature.
    payload_b64 = envelope["payload_base64url"]
    flipped = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B")
    tampered = {**envelope, "payload_base64url": flipped}
    with pytest.raises(HoldSettlementAttestationError):
        verify_hold_settlement_attestation(tampered, expected, pinned_keys)
