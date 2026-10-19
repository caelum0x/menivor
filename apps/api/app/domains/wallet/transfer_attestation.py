"""Strict verification for Mint's privacy-safe transfer attestation.

The signed payload deliberately contains commitments, never Mint account IDs.
Menivor recomputes those commitments from its own durable account mappings and
only then treats the transfer as complete.  This proves one Mint-signed
transfer result; it does not claim chain-wide or global supply conservation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


FORMAT = "mint-transfer-attestation-v1"
_DIGEST_DOMAIN = b"mint-transfer-attestation-v1\0"
_REFERENCE_DOMAIN = b"mint-transfer-reference-v1\0"
_PARTY_DOMAIN = b"mint-transfer-party-v1\0"
_CLAIM_KEYS = (
    "version",
    "asset",
    "unit",
    "sequence",
    "operation",
    "operation_hash",
    "amount_micros",
    "receipt_hash",
    "timestamp_ms",
    "reference_hash",
    "sender_commitment",
    "recipient_commitment",
    "signer_key_id",
)
_ENVELOPE_KEYS = (
    "format",
    "payload_base64url",
    "digest_sha256",
    "signer_key_id",
    "signature_hex",
)


class TransferAttestationError(ValueError):
    """The Mint attestation is absent, malformed, untrusted, or mismatched."""


def normalize_receipt_operation_hash(value: object) -> str:
    """Return Mint's 32-byte operation hash as canonical lowercase hex.

    Rust serializes its byte-array newtype as 32 JSON integers while older
    fakes and persisted rows use lowercase hex. Supporting both exact wire
    forms keeps the boundary compatible without accepting lossy ``str(list)``
    values or mutating the signed receipt body before it is persisted.
    """
    if isinstance(value, str):
        return _lower_hex(value, "receipt operation_hash", 32)
    if (
        isinstance(value, list)
        and len(value) == 32
        and all(
            isinstance(byte, int) and not isinstance(byte, bool) and 0 <= byte <= 255
            for byte in value
        )
    ):
        return bytes(value).hex()
    raise TransferAttestationError(
        "receipt operation_hash must be lowercase 32-byte hex or 32 bytes"
    )


@dataclass(frozen=True)
class TransferAttestationExpected:
    """Values anchored in Menivor's command, Mint mapping, and signed receipt."""

    sender_mint_id: str
    recipient_mint_id: str
    mint_operation: str
    amount_micros: int
    sequence: int
    operation: str
    operation_hash: str
    receipt_hash: str
    timestamp_ms: int


@dataclass(frozen=True)
class VerifiedTransferAttestation:
    format: str
    key_id: str
    payload_base64url: str
    signature_hex: str
    digest_sha256: str
    claims: dict[str, Any]


def _strict_object(raw: bytes) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise TransferAttestationError(f"duplicate attestation claim: {key}")
            out[key] = value
        return out

    try:
        text = raw.decode("utf-8")
        parsed = json.loads(text, object_pairs_hook=pairs_hook)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransferAttestationError(
            "attestation payload is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise TransferAttestationError("attestation payload must be a JSON object")
    if tuple(parsed) != _CLAIM_KEYS:
        raise TransferAttestationError(
            "attestation claims are missing, extra, or out of order"
        )
    canonical = json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if canonical != raw:
        raise TransferAttestationError("attestation payload is not canonical JSON")
    return parsed


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise TransferAttestationError(f"{field} must be a non-empty string")
    return value


def _require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TransferAttestationError(f"{field} must be an integer")
    return value


def _lower_hex(value: Any, field: str, byte_length: int) -> str:
    text = _require_text(value, field)
    if len(text) != byte_length * 2 or text != text.lower():
        raise TransferAttestationError(
            f"{field} must be lowercase {byte_length}-byte hex"
        )
    try:
        bytes.fromhex(text)
    except ValueError as exc:
        raise TransferAttestationError(f"{field} must be lowercase hex") from exc
    return text


def _commit_party(role: str, account_id: str, operation_hash: str) -> str:
    return hashlib.sha256(
        _PARTY_DOMAIN
        + role.encode("ascii")
        + b"\0"
        + account_id.encode("utf-8")
        + b"\0"
        + operation_hash.encode("ascii")
    ).hexdigest()


def _reference_hash(mint_operation: str) -> str:
    return hashlib.sha256(
        _REFERENCE_DOMAIN + mint_operation.encode("utf-8")
    ).hexdigest()


def load_pinned_public_keys(raw: object) -> dict[str, Ed25519PublicKey]:
    """Parse a config JSON object of ``key id -> lowercase public-key hex``."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TransferAttestationError(
                "Mint attestation public-key config is not valid JSON"
            ) from exc
    if not isinstance(raw, dict) or not raw:
        raise TransferAttestationError("no Mint attestation public keys are pinned")
    keys: dict[str, Ed25519PublicKey] = {}
    for key_id, encoded in raw.items():
        key_name = _require_text(key_id, "pinned key id")
        public_hex = _lower_hex(encoded, f"public key {key_name}", 32)
        keys[key_name] = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
    return keys


def verify_transfer_attestation(
    envelope: object,
    expected: TransferAttestationExpected,
    pinned_keys: Mapping[str, Ed25519PublicKey],
) -> VerifiedTransferAttestation:
    """Verify exact payload bytes, signature, privacy commitments and mappings."""
    for value, field in (
        (expected.sender_mint_id, "expected sender Mint mapping"),
        (expected.recipient_mint_id, "expected recipient Mint mapping"),
        (expected.mint_operation, "expected mint_operation"),
    ):
        _require_text(value, field)
    for value, field in (
        (expected.sequence, "expected sequence"),
        (expected.amount_micros, "expected amount_micros"),
        (expected.timestamp_ms, "expected timestamp_ms"),
    ):
        _require_int(value, field)
    if (
        expected.sequence <= 0
        or expected.amount_micros <= 0
        or expected.timestamp_ms < 0
    ):
        raise TransferAttestationError("expected numeric transfer fields are invalid")
    if expected.operation != "Transfer":
        raise TransferAttestationError("expected operation must be Transfer")
    _lower_hex(expected.operation_hash, "expected operation_hash", 32)
    _lower_hex(expected.receipt_hash, "expected receipt_hash", 32)

    # The envelope is an unsigned transport wrapper whose fields are each
    # validated individually below; JSON object key ORDER is not part of the
    # wire contract (Mint serializes it in its own order). Require the exact SET
    # of keys, not a fixed order. The SIGNED payload's canonical ordering is
    # still strictly enforced when the claims are parsed.
    if not isinstance(envelope, dict) or set(envelope) != set(_ENVELOPE_KEYS):
        raise TransferAttestationError(
            "attestation envelope is missing or has unexpected keys"
        )
    if envelope.get("format") != FORMAT:
        raise TransferAttestationError("unsupported transfer attestation format")
    key_id = _require_text(envelope.get("signer_key_id"), "signer_key_id")
    public_key = pinned_keys.get(key_id)
    if public_key is None:
        raise TransferAttestationError("Mint attestation signer is not pinned")

    payload_b64 = _require_text(envelope.get("payload_base64url"), "payload_base64url")
    if "=" in payload_b64:
        raise TransferAttestationError("payload_base64url must be unpadded")
    try:
        payload = base64.b64decode(
            payload_b64 + "=" * (-len(payload_b64) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise TransferAttestationError("payload_base64url is invalid") from exc
    if base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii") != payload_b64:
        raise TransferAttestationError("payload_base64url is not canonical")

    digest_hex = _lower_hex(envelope.get("digest_sha256"), "digest_sha256", 32)
    digest = hashlib.sha256(_DIGEST_DOMAIN + payload).digest()
    if not hmac.compare_digest(digest.hex(), digest_hex):
        raise TransferAttestationError(
            "attestation digest does not match payload bytes"
        )
    signature_hex = _lower_hex(envelope.get("signature_hex"), "signature_hex", 64)
    try:
        public_key.verify(bytes.fromhex(signature_hex), digest)
    except InvalidSignature as exc:
        raise TransferAttestationError("Mint attestation signature is invalid") from exc

    claims = _strict_object(payload)
    if claims["signer_key_id"] != key_id:
        raise TransferAttestationError("payload and envelope signer key ids differ")
    if (
        claims["version"] != 1
        or claims["asset"] != "AIT"
        or claims["unit"] != "micro_usd"
    ):
        raise TransferAttestationError("attestation asset identity is invalid")

    for field in ("sequence", "amount_micros", "timestamp_ms"):
        _require_int(claims[field], field)
    for field in (
        "operation",
        "operation_hash",
        "receipt_hash",
        "reference_hash",
        "sender_commitment",
        "recipient_commitment",
        "signer_key_id",
    ):
        _require_text(claims[field], field)
    for field in (
        "operation_hash",
        "receipt_hash",
        "reference_hash",
        "sender_commitment",
        "recipient_commitment",
    ):
        _lower_hex(claims[field], field, 32)

    expected_claims: dict[str, Any] = {
        "sequence": expected.sequence,
        "operation": expected.operation,
        "operation_hash": expected.operation_hash,
        "amount_micros": expected.amount_micros,
        "receipt_hash": expected.receipt_hash,
        "timestamp_ms": expected.timestamp_ms,
        "reference_hash": _reference_hash(expected.mint_operation),
        "sender_commitment": _commit_party(
            "sender", expected.sender_mint_id, expected.operation_hash
        ),
        "recipient_commitment": _commit_party(
            "recipient", expected.recipient_mint_id, expected.operation_hash
        ),
    }
    for field, expected_value in expected_claims.items():
        if claims[field] != expected_value:
            raise TransferAttestationError(
                f"attestation {field} does not match transfer"
            )

    return VerifiedTransferAttestation(
        format=FORMAT,
        key_id=key_id,
        payload_base64url=payload_b64,
        signature_hex=signature_hex,
        digest_sha256=digest_hex,
        claims=claims,
    )
