"""Wallet domain DTOs (Pydantic v2) + public view builders.

Request models for the purchase-quote / checkout endpoints plus typed builders
for the balance and activity ``data`` payloads. Responses go through the shared
MPT envelope, so these describe the ``data`` payloads only. All money is shown
as both integer microdollars and a display USD string.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.money import micros_to_usd_str


class PurchaseQuoteRequest(BaseModel):
    """Request a checkout quote for a wallet top-up (no charge is made)."""

    model_config = ConfigDict(extra="forbid")

    amount_usd: str = Field(..., description="Wallet credit to add, decimal USD string")


class CheckoutRequest(BaseModel):
    """Start a wallet top-up checkout (launch-gated)."""

    model_config = ConfigDict(extra="forbid")

    amount_usd: str = Field(..., description="Wallet credit to add, decimal USD string")
    provider: Literal["creem", "stripe"] = Field(
        default="creem",
        description="Configured hosted payment rail",
    )
    workspace_id: str | None = Field(
        default=None, description="Fund a workspace shared pool (requires topup role)"
    )


class TransferRequest(BaseModel):
    """Send Mint-backed AI tokens to a public handle or Mint address."""

    model_config = ConfigDict(extra="forbid")

    source_account_id: str = Field(..., min_length=1, max_length=32)
    challenge_id: str = Field(..., min_length=1, max_length=32)
    recipient_handle: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Public Menivor handle or ait1 Mint receive address",
    )
    amount_micros: int = Field(..., gt=0, le=1_000_000_000)


class TransferChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account_id: str = Field(..., min_length=1, max_length=32)
    recipient_handle: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Public Menivor handle or ait1 Mint receive address",
    )
    saved_recipient_id: str | None = Field(default=None, max_length=32)
    amount_micros: int = Field(..., gt=0, le=1_000_000_000)


class SavedRecipientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account_id: str = Field(..., min_length=1, max_length=32)
    recipient_handle: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=100)


class TransferPolicyRequest(BaseModel):
    """Configure account-keyed send limits; zero disables that policy limit."""

    model_config = ConfigDict(extra="forbid")

    source_account_id: str = Field(..., min_length=1, max_length=32)
    per_transfer_limit_micros: int = Field(..., ge=0, le=1_000_000_000)
    daily_limit_micros: int = Field(..., ge=0, le=1_000_000_000_000)


class ReceiveAddressRequest(BaseModel):
    """Provision or replay the stable public address for one wallet source."""

    model_config = ConfigDict(extra="forbid")

    source_account_id: str = Field(..., min_length=1, max_length=32)


class DestinationProfileRequest(BaseModel):
    """Create a shareable workspace, agent, or service receive identity."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["workspace", "agent", "service"]
    slug: str = Field(..., min_length=3, max_length=48)
    display_name: str = Field(..., min_length=1, max_length=200)
    workspace_source_account_id: str | None = Field(
        default=None,
        max_length=32,
        description="Authorized workspace wallet source that owns this destination",
    )


class DestinationProfileStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool


def account_view(account: object | None) -> dict:
    """Balance snapshot: available/reserved in micros + display USD."""
    available = int(getattr(account, "available_micros", 0) or 0)
    reserved = int(getattr(account, "reserved_micros", 0) or 0)
    return {
        "account_id": getattr(account, "id", ""),
        "currency": getattr(account, "currency", "USD"),
        "available_micros": available,
        "reserved_micros": reserved,
        "available_usd": micros_to_usd_str(available),
        "reserved_usd": micros_to_usd_str(reserved),
    }


def entry_view(entry: object) -> dict:
    """One ledger activity row in client-facing shape."""
    available_after = int(getattr(entry, "available_after", 0) or 0)
    reserved_after = int(getattr(entry, "reserved_after", 0) or 0)
    created = getattr(entry, "created_at", None)
    out = {
        "id": getattr(entry, "id", None),
        "entry_type": getattr(entry, "entry_type", ""),
        "reason": getattr(entry, "reason", ""),
        "available_delta": int(getattr(entry, "available_delta", 0) or 0),
        "reserved_delta": int(getattr(entry, "reserved_delta", 0) or 0),
        "available_after": available_after,
        "reserved_after": reserved_after,
        "available_after_usd": micros_to_usd_str(available_after),
        "job_id": getattr(entry, "job_id", None),
        "payment_intent_id": getattr(entry, "payment_intent_id", None),
        "correlation_id": getattr(entry, "correlation_id", ""),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
    }
    meta = getattr(entry, "meta", {}) or {}
    if getattr(entry, "entry_type", "") == "transfer" and isinstance(meta, dict):
        out["transfer"] = {
            "transfer_id": str(meta.get("transfer_id", "")),
            "direction": str(meta.get("direction", "")),
            "counterparty_handle": str(meta.get("counterparty_handle", "")),
            "amount_micros": int(meta.get("amount_micros", 0) or 0),
            "status": str(meta.get("status", "")),
            "mint_first_seq": meta.get("mint_first_seq"),
            "source": meta.get("source"),
        }
    return out


def transfer_view(transfer: object, receipt: dict | None = None) -> dict:
    """Sender-only result with one opaque Menivor source id and no Mint ids."""
    created = getattr(transfer, "created_at", None)
    completed = getattr(transfer, "completed_at", None)
    attestation = getattr(transfer, "attestation", None)
    stored_status = str(getattr(transfer, "status", ""))
    # Legacy receipt-only rows must replay and pass the stronger verifier before
    # this surface represents them as complete.
    public_status = (
        "pending"
        if stored_status == "completed" and attestation is None
        else stored_status
    )
    out = {
        "transfer_id": getattr(transfer, "id", ""),
        "source": {
            "source_account_id": getattr(transfer, "sender_account_id", ""),
            "kind": getattr(transfer, "sender_source_kind", "personal"),
            "label": getattr(transfer, "sender_source_label", ""),
        },
        "recipient": {
            "handle": getattr(transfer, "recipient_handle", ""),
            "kind": getattr(transfer, "recipient_kind", "personal"),
            "display_name": (
                getattr(transfer, "recipient_label", "")
                or getattr(transfer, "recipient_handle", "")
            ),
        },
        "amount_micros": int(getattr(transfer, "amount_micros", 0) or 0),
        "amount_usd": micros_to_usd_str(
            int(getattr(transfer, "amount_micros", 0) or 0)
        ),
        "status": public_status,
        "receipt_proof": None,
        "verification": {"status": "pending"},
        "mint_first_seq": getattr(transfer, "mint_first_seq", None),
        "idempotent_replay": bool(getattr(transfer, "mint_idempotent_replay", False)),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
        "completed_at": (
            completed.isoformat() if hasattr(completed, "isoformat") else None
        )
        if public_status == "completed"
        else None,
    }
    raw_proof = getattr(transfer, "mint_receipt", None)
    if attestation is not None and isinstance(raw_proof, dict):
        body = raw_proof.get("body")
        if isinstance(body, dict):
            # Stable product vocabulary over Mint's complete persisted receipt.
            # Account-chain details remain stored for offline verification but
            # are not copied into this sender-facing status DTO.
            from app.domains.wallet.transfer_attestation import (
                TransferAttestationError,
                normalize_receipt_operation_hash,
            )

            try:
                operation_hash = normalize_receipt_operation_hash(body.get("op_hash"))
            except TransferAttestationError:
                # Completed rows only exist after strict verification, but keep
                # the projection fail-closed if a historical row is corrupted.
                operation_hash = ""
            out["receipt_proof"] = {
                "sequence": int(body.get("journal_seq", 0) or 0),
                "operation": str(body.get("op", "") or ""),
                "operation_hash": operation_hash,
                "amount_micros": int(body.get("amount_micros", 0) or 0),
                "receipt_hash": str(raw_proof.get("hash", "") or ""),
                "signature": str(raw_proof.get("sig", "") or ""),
                "signer": str(body.get("signer", "") or ""),
                "timestamp_ms": int(body.get("ts", 0) or 0),
            }
    if isinstance(receipt, dict):
        sender_balance = receipt.get("from_balance")
        if isinstance(sender_balance, dict):
            out["sender_balance"] = {
                "available_micros": int(sender_balance.get("available_micros", 0) or 0),
                "held_micros": int(sender_balance.get("held_micros", 0) or 0),
            }
    if attestation is not None:
        verified_at = getattr(attestation, "verified_at", None)
        out["verification"] = {
            "status": "verified",
            "format": str(getattr(attestation, "format", "")),
            "signer_key_id": str(getattr(attestation, "signer_key_id", "")),
            "digest_sha256": str(getattr(attestation, "digest_sha256", "")),
            "verified_at": (
                verified_at.isoformat() if hasattr(verified_at, "isoformat") else None
            ),
        }
    return out


def intent_view(intent: object) -> dict:
    """Checkout intent snapshot returned by quote/checkout responses."""
    fields = (
        "credit_micros",
        "fee_micros",
        "tax_micros",
        "processor_micros",
        "total_charge_micros",
        "fee_rate_bps",
    )
    out: dict = {name: int(getattr(intent, name, 0) or 0) for name in fields}
    out.update(
        {
            "payment_intent_id": getattr(intent, "id", ""),
            "status": getattr(intent, "status", ""),
            "currency": getattr(intent, "currency", "USD"),
            "fee_schedule_version": getattr(intent, "fee_schedule_version", ""),
            "payment_provider": getattr(intent, "payment_provider", ""),
            "credit_usd": micros_to_usd_str(
                int(getattr(intent, "credit_micros", 0) or 0)
            ),
            "total_charge_usd": micros_to_usd_str(
                int(getattr(intent, "total_charge_micros", 0) or 0)
            ),
        }
    )
    meta = getattr(intent, "meta", {}) or {}
    if isinstance(meta, dict):
        out["settlement_rail"] = str(meta.get("settlement_rail", "local") or "local")
        checkout_url = str(meta.get("checkout_url", "") or "").strip()
        if checkout_url and out["status"] == "pending":
            out["checkout_url"] = checkout_url
    return out
