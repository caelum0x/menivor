"""Golden and tamper tests for Mint transfer attestation verification."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.domains.wallet.transfer_attestation import (
    TransferAttestationError,
    TransferAttestationExpected,
    load_pinned_public_keys,
    verify_transfer_attestation,
)
from tests.reelforge.conftest_mint import (
    MINT_ATTESTATION_TEST_KEY_ID,
    MINT_ATTESTATION_TEST_PRIVATE_KEY_HEX,
    MINT_ATTESTATION_TEST_PUBLIC_KEY_HEX,
    FakeMint,
)


EXPECTED = TransferAttestationExpected(
    sender_mint_id="acct_sender",
    recipient_mint_id="acct_recipient",
    mint_operation="menivor:p2p:golden-001",
    amount_micros=1_234_567,
    sequence=42,
    operation="Transfer",
    operation_hash="11" * 32,
    receipt_hash="22" * 32,
    timestamp_ms=1_777_777_777_042,
)
GOLDEN = {
    "format": "mint-transfer-attestation-v1",
    "payload_base64url": "eyJ2ZXJzaW9uIjoxLCJhc3NldCI6IkFJVCIsInVuaXQiOiJtaWNyb191c2QiLCJzZXF1ZW5jZSI6NDIsIm9wZXJhdGlvbiI6IlRyYW5zZmVyIiwib3BlcmF0aW9uX2hhc2giOiIxMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExIiwiYW1vdW50X21pY3JvcyI6MTIzNDU2NywicmVjZWlwdF9oYXNoIjoiMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMiIsInRpbWVzdGFtcF9tcyI6MTc3Nzc3Nzc3NzA0MiwicmVmZXJlbmNlX2hhc2giOiJiNmM3MzM0OWE0ZGQ4NzE3ODJiMDg3N2E1MzcyYzM1ZDExYTYwY2U2M2ZkYTQ5NDk4NTdjZmIwOThkNGE1MzYwIiwic2VuZGVyX2NvbW1pdG1lbnQiOiI3M2I4MzEyOGE3ZDUxMWM5NmYxMWVhZGUxY2VkMzkzYmVkNmU0NDk1MWMzNGRjNmZhN2M2NTliYzk5MjMwMmRhIiwicmVjaXBpZW50X2NvbW1pdG1lbnQiOiIxOWNmOGUzYTdiMDVkOTRlZDBmMmJkNWE4ZGJmMzU0YWE0YWNjMDllN2E3OTgyNzdjZWM3NGQxOWJhZTc0ZDkzIiwic2lnbmVyX2tleV9pZCI6Im1pbnQtdGVzdC1rZXktMSJ9",
    "digest_sha256": "9ecc46ec21bc2b6890e2e4e5c687bd18be238d2448ebbaa6ca4522ad1caaa335",
    "signer_key_id": "mint-test-key-1",
    "signature_hex": "560496e8036f1e10a1458182c80c60626526e775b92669a8002954a035ff032dca4d3b6e83c23021c7a6a2cbc4e1e685b1f0d7cb5a1985ea49cfe8454870620d",
}

RUST_GOLDEN = {
    "format": "mint-transfer-attestation-v1",
    "payload_base64url": "eyJ2ZXJzaW9uIjoxLCJhc3NldCI6IkFJVCIsInVuaXQiOiJtaWNyb191c2QiLCJzZXF1ZW5jZSI6NDIsIm9wZXJhdGlvbiI6IlRyYW5zZmVyIiwib3BlcmF0aW9uX2hhc2giOiI0ODFjYmNiMTk3MjE1MTM5Y2E1MTU3YmE5MTJmMjUyZWEwYjI5NDNlNDQxY2E3MjhmOGJiZWExNzlhZjEyZWNlIiwiYW1vdW50X21pY3JvcyI6NDIwMDAwMCwicmVjZWlwdF9oYXNoIjoiYmNlZTdmNTI2NDlkYWIwZjU4Nzk1N2EyODNmOGNmMTg2MDgwNjI4MjgzNGFlNjNkZTc2MmUzZmNiMjY5NjE5NyIsInRpbWVzdGFtcF9tcyI6MTcwMDAwMDAwMDEyMywicmVmZXJlbmNlX2hhc2giOiIzNDgyZWE2MjVlNGYzYzkwOGYwMTI5ZTAwYjYzYzg3N2E0ZTAxMGExMmE4OTE5MzFiMTI1NDE0YTEwYWI1MDQxIiwic2VuZGVyX2NvbW1pdG1lbnQiOiIxNDU1ZmY1NzhhZTYwM2Y1YzlhYWU4MWYxMzdhZWY0NDFlNjdkNGRjNjA5MjAyMGNiZDA3OWRhZmM5ZDU2N2Y1IiwicmVjaXBpZW50X2NvbW1pdG1lbnQiOiI3MjYwYTAxNDkyNTRmOWJjZjYxZDA0MWU5OGJhMGZjNTA3YWQ5NDZhMGVkY2Q0MGZmOGQ0Y2ZkOGZiY2ExOTc3Iiwic2lnbmVyX2tleV9pZCI6Im1pbnQtdmVyaWZpZXIta2V5LTEifQ",
    "digest_sha256": "a365e20ff04403411ff2abc324fbfbba4cd8839f0f620fae9d6eae6c56848355",
    "signer_key_id": "mint-verifier-key-1",
    "signature_hex": "f8f7af24c68eca99bd5250e7aa44c8b0d4d617f44df8c5b1d274d1e5d4e18cc946308cd259134d8381d9b7357caee00c2566f19edb954876c303813216330c09",
}


def _keys():
    return load_pinned_public_keys(
        json.dumps({MINT_ATTESTATION_TEST_KEY_ID: MINT_ATTESTATION_TEST_PUBLIC_KEY_HEX})
    )


def _resign_claims(claims: dict) -> dict[str, str]:
    payload = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(b"mint-transfer-attestation-v1\0" + payload).digest()
    signer = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(MINT_ATTESTATION_TEST_PRIVATE_KEY_HEX)
    )
    return {
        "format": "mint-transfer-attestation-v1",
        "payload_base64url": base64.urlsafe_b64encode(payload)
        .rstrip(b"=")
        .decode("ascii"),
        "digest_sha256": digest.hex(),
        "signer_key_id": MINT_ATTESTATION_TEST_KEY_ID,
        "signature_hex": signer.sign(digest).hex(),
    }


def test_fixed_ed25519_golden_vector_matches_fake_mint_and_verifies():
    generated = FakeMint._transfer_attestation(
        sender=EXPECTED.sender_mint_id,
        recipient=EXPECTED.recipient_mint_id,
        mint_operation=EXPECTED.mint_operation,
        amount_micros=EXPECTED.amount_micros,
        sequence=EXPECTED.sequence,
        operation_hash=EXPECTED.operation_hash,
        receipt_hash=EXPECTED.receipt_hash,
        timestamp_ms=EXPECTED.timestamp_ms,
    )
    assert generated == GOLDEN
    verified = verify_transfer_attestation(GOLDEN, EXPECTED, _keys())
    assert verified.digest_sha256 == GOLDEN["digest_sha256"]
    decoded = base64.urlsafe_b64decode(
        GOLDEN["payload_base64url"] + "=" * (-len(GOLDEN["payload_base64url"]) % 4)
    ).decode("utf-8")
    assert "acct_sender" not in decoded
    assert "acct_recipient" not in decoded


def test_exact_rust_mint_cross_language_golden_vector_verifies():
    """Byte-for-byte fixture emitted by mint-server's Rust golden test."""
    expected = TransferAttestationExpected(
        sender_mint_id="acct_000000000000000000000000001",
        recipient_mint_id="acct_400000000000000000000000002",
        mint_operation="menivor:transfer:01",
        amount_micros=4_200_000,
        sequence=42,
        operation="Transfer",
        operation_hash="481cbcb197215139ca5157ba912f252ea0b2943e441ca728f8bbea179af12ece",
        receipt_hash="bcee7f52649dab0f587957a283f8cf1860806282834ae63de762e3fcb2696197",
        timestamp_ms=1_700_000_000_123,
    )
    rust_key = load_pinned_public_keys(
        {"mint-verifier-key-1": "74e0be0d9692f0817482d8f3930b51d334db23d11665ca8ee52fe9e8c29715e8"}
    )
    verified = verify_transfer_attestation(RUST_GOLDEN, expected, rust_key)
    assert verified.digest_sha256 == RUST_GOLDEN["digest_sha256"]


@pytest.mark.parametrize("field", ["digest_sha256", "signature_hex"])
def test_rejects_digest_or_signature_tampering(field):
    tampered = dict(GOLDEN)
    tampered[field] = ("0" if tampered[field][0] != "0" else "1") + tampered[field][1:]
    with pytest.raises(TransferAttestationError):
        verify_transfer_attestation(tampered, EXPECTED, _keys())


def test_rejects_unpinned_key_even_when_envelope_is_otherwise_valid():
    with pytest.raises(TransferAttestationError, match="not pinned"):
        verify_transfer_attestation(GOLDEN, EXPECTED, {})


def test_rejects_validly_signed_but_wrong_party_and_amount_commitments():
    payload = base64.urlsafe_b64decode(
        GOLDEN["payload_base64url"] + "=" * (-len(GOLDEN["payload_base64url"]) % 4)
    )
    claims = json.loads(payload)
    claims["amount_micros"] += 1
    claims["sender_commitment"] = "33" * 32
    with pytest.raises(TransferAttestationError, match="amount_micros"):
        verify_transfer_attestation(_resign_claims(claims), EXPECTED, _keys())


def test_rejects_extra_claim_even_with_a_valid_signature():
    payload = base64.urlsafe_b64decode(
        GOLDEN["payload_base64url"] + "=" * (-len(GOLDEN["payload_base64url"]) % 4)
    )
    claims = json.loads(payload)
    claims["global_conservation"] = True
    with pytest.raises(TransferAttestationError, match="missing, extra, or out of order"):
        verify_transfer_attestation(_resign_claims(claims), EXPECTED, _keys())
