"""Strict verification of Mint's signed hold-settlement evidence.

The verifier binds Mint's exact signed payload bytes to Menivor's durable
settlement intent, hold, payer/payee mappings, and flat AITP receipt. Nothing in
this module performs I/O or consults the current rollout stage.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Mapping

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


FORMAT = "mint-hold-settlement-attestation-v1"
_DIGEST_DOMAIN = b"mint-hold-settlement-attestation-v1\0"
_REFERENCE_DOMAIN = b"mint-hold-settlement-reference-v1\0"
_HOLD_DOMAIN = b"mint-hold-settlement-hold-v1\0"
_PARTY_DOMAIN = b"mint-hold-settlement-party-v1\0"
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
    "hold_commitment",
    "payer_commitment",
    "payee_commitment",
    "signer_key_id",
)
_ENVELOPE_KEYS = (
    "format",
    "payload_base64url",
    "digest_sha256",
    "signer_key_id",
    "signature_hex",
)


class HoldSettlementAttestationError(ValueError):
    """Attestation is absent, malformed, untrusted, or intent-mismatched."""


@dataclass(frozen=True)
class HoldSettlementExpected:
    operation: str
    hold_id: str
    payer_account: str
    payee_account: str
    amount_micros: int
    idempotency_key: str
    reference: str
    receipt: Mapping[str, Any]


@dataclass(frozen=True)
class VerifiedHoldSettlementAttestation:
    envelope: dict[str, Any]
    claims: dict[str, Any]


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise HoldSettlementAttestationError(f"{field} must be a non-empty string")
    return value


def _require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HoldSettlementAttestationError(f"{field} must be an integer")
    return value


def _lower_hex(value: Any, field: str, byte_length: int) -> str:
    text = _require_text(value, field)
    if len(text) != byte_length * 2 or text != text.lower():
        raise HoldSettlementAttestationError(
            f"{field} must be lowercase {byte_length}-byte hex"
        )
    try:
        bytes.fromhex(text)
    except ValueError as exc:
        raise HoldSettlementAttestationError(f"{field} must be lowercase hex") from exc
    return text


def _strict_claims(payload: bytes) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HoldSettlementAttestationError(
                    f"duplicate settlement attestation claim: {key}"
                )
            result[key] = value
        return result

    try:
        claims = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs_hook)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldSettlementAttestationError(
            "settlement attestation payload is not UTF-8 JSON"
        ) from exc
    if not isinstance(claims, dict) or tuple(claims) != _CLAIM_KEYS:
        raise HoldSettlementAttestationError(
            "settlement attestation claims are missing, extra, or out of order"
        )
    canonical = json.dumps(
        claims, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if canonical != payload:
        raise HoldSettlementAttestationError(
            "settlement attestation payload is not canonical JSON"
        )
    return claims


def _operation_hash(expected: HoldSettlementExpected) -> str:
    if expected.operation == "hold.capture":
        body = {
            "op": "hold.capture",
            "hold_id": expected.hold_id,
            "amount_micros": expected.amount_micros,
            "to": expected.payee_account,
            "idem_key": expected.idempotency_key,
            "ref": expected.reference or None,
        }
    elif expected.operation == "hold.release":
        body = {
            "op": "hold.release",
            "hold_id": expected.hold_id,
            "idem_key": expected.idempotency_key,
            "ref": expected.reference or None,
        }
    else:
        raise HoldSettlementAttestationError("unsupported hold settlement operation")
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return blake3.blake3(canonical).hexdigest()


def _commit(domain: bytes, *parts: str) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    for index, part in enumerate(parts):
        if index:
            digest.update(b"\0")
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()


def _party(role: str, account: str, operation_hash: str) -> str:
    return _commit(_PARTY_DOMAIN, role, account, operation_hash)


def verify_hold_settlement_attestation(
    envelope: object,
    expected: HoldSettlementExpected,
    pinned_keys: Mapping[str, Ed25519PublicKey],
) -> VerifiedHoldSettlementAttestation:
    """Verify signature, exact claims, receipt, and durable command bindings."""
    for value, field in (
        (expected.hold_id, "hold_id"),
        (expected.payer_account, "payer_account"),
        (expected.idempotency_key, "idempotency_key"),
        (expected.reference, "reference"),
    ):
        _require_text(value, field)
    if expected.operation == "hold.capture":
        _require_text(expected.payee_account, "payee_account")
    elif expected.payee_account:
        raise HoldSettlementAttestationError("release must not declare a payee")
    amount = _require_int(expected.amount_micros, "amount_micros")
    if amount <= 0:
        raise HoldSettlementAttestationError("amount_micros must be positive")

    # The envelope is an unsigned transport wrapper: its five fields are each
    # validated individually below (format, pinned signer, canonical payload,
    # recomputed digest, verified signature). JSON object key ORDER is not part
    # of the wire contract — Mint serializes the envelope in its own (struct/
    # serde) order — so require the exact SET of keys (no missing, no extra)
    # rather than a fixed tuple order. The SIGNED payload's canonical ordering is
    # still strictly enforced in ``_strict_claims``.
    if not isinstance(envelope, dict) or set(envelope) != set(_ENVELOPE_KEYS):
        raise HoldSettlementAttestationError(
            "settlement attestation envelope is missing or has unexpected keys"
        )
    if envelope.get("format") != FORMAT:
        raise HoldSettlementAttestationError("unsupported settlement attestation format")
    key_id = _require_text(envelope.get("signer_key_id"), "signer_key_id")
    public_key = pinned_keys.get(key_id)
    if public_key is None:
        raise HoldSettlementAttestationError("Mint settlement signer is not pinned")

    payload_b64 = _require_text(envelope.get("payload_base64url"), "payload_base64url")
    if "=" in payload_b64:
        raise HoldSettlementAttestationError("payload_base64url must be unpadded")
    try:
        payload = base64.b64decode(
            payload_b64 + "=" * (-len(payload_b64) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise HoldSettlementAttestationError("payload_base64url is invalid") from exc
    if base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii") != payload_b64:
        raise HoldSettlementAttestationError("payload_base64url is not canonical")

    digest = hashlib.sha256(_DIGEST_DOMAIN + payload).digest()
    digest_hex = _lower_hex(envelope.get("digest_sha256"), "digest_sha256", 32)
    if not hmac.compare_digest(digest.hex(), digest_hex):
        raise HoldSettlementAttestationError("attestation digest does not match payload")
    signature_hex = _lower_hex(envelope.get("signature_hex"), "signature_hex", 64)
    try:
        public_key.verify(bytes.fromhex(signature_hex), digest)
    except InvalidSignature as exc:
        raise HoldSettlementAttestationError(
            "Mint settlement attestation signature is invalid"
        ) from exc

    claims = _strict_claims(payload)
    if (
        claims["version"] != 1
        or claims["asset"] != "AIT"
        or claims["unit"] != "micro_usd"
        or claims["signer_key_id"] != key_id
    ):
        raise HoldSettlementAttestationError("settlement asset identity is invalid")
    for field in ("sequence", "amount_micros", "timestamp_ms"):
        _require_int(claims[field], field)
    if claims["sequence"] <= 0 or claims["timestamp_ms"] < 0:
        raise HoldSettlementAttestationError("settlement numeric claims are invalid")
    for field in (
        "operation_hash",
        "receipt_hash",
        "reference_hash",
        "hold_commitment",
        "payer_commitment",
        "payee_commitment",
    ):
        _lower_hex(claims[field], field, 32)

    receipt = expected.receipt
    if not isinstance(receipt, Mapping):
        raise HoldSettlementAttestationError("settlement receipt must be an object")
    operation_hash = _operation_hash(expected)
    receipt_values = {
        "sequence": receipt.get("seq"),
        "operation": receipt.get("op"),
        "operation_hash": receipt.get("op_hash"),
        "amount_micros": receipt.get("amount_micros"),
        "receipt_hash": receipt.get("hash"),
    }
    expected_values = {
        "sequence": claims["sequence"],
        "operation": expected.operation,
        "operation_hash": operation_hash,
        "amount_micros": amount,
        "receipt_hash": claims["receipt_hash"],
    }
    for field, expected_value in expected_values.items():
        if claims[field] != expected_value or receipt_values[field] != expected_value:
            raise HoldSettlementAttestationError(
                f"settlement {field} does not match durable intent and receipt"
            )

    expected_commitments = {
        "reference_hash": _commit(_REFERENCE_DOMAIN, expected.reference),
        "hold_commitment": _commit(_HOLD_DOMAIN, expected.hold_id, operation_hash),
        "payer_commitment": _party("payer", expected.payer_account, operation_hash),
        "payee_commitment": (
            _party("payee", expected.payee_account, operation_hash)
            if expected.operation == "hold.capture"
            else _commit(_PARTY_DOMAIN, "no-payee", operation_hash)
        ),
    }
    for field, expected_value in expected_commitments.items():
        if claims[field] != expected_value:
            raise HoldSettlementAttestationError(
                f"settlement {field} does not match durable intent"
            )

    return VerifiedHoldSettlementAttestation(
        envelope=dict(envelope),
        claims=claims,
    )


__all__ = [
    "FORMAT",
    "HoldSettlementAttestationError",
    "HoldSettlementExpected",
    "VerifiedHoldSettlementAttestation",
    "verify_hold_settlement_attestation",
]
