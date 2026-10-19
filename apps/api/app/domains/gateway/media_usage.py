"""Gateway credit + usage aggregation (OpenRouter ``/credits`` + ``/generation``).

Mirrors OpenRouter's cost-visibility surface over the media gateway's own data:

* **credits** — the wallet balance (available/reserved) = spendable credits, plus
  lifetime gateway spend.
* **usage** — spend + counts grouped by model (which models the customer runs).
* **generation** — per-job cost/status detail (OpenRouter's ``/generation?id=``).

Pure aggregation over ``media_jobs`` + the wallet; session-injected + testable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func

from app.models.db.media_jobs import MediaJob


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _iso(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _settlement_receipt_proof(row: MediaJob) -> dict | None:
    """Return only a complete Mint capture/release proof; never fill missing facts."""
    receipt = dict(row.settlement_receipt or {})
    operation = str(receipt.get("op", "") or "")
    sequence = int(receipt.get("seq", 0) or 0)
    operation_hash = str(receipt.get("op_hash", "") or "")
    receipt_hash = str(receipt.get("hash", "") or "")
    signature = str(receipt.get("sig", "") or "")
    amount = int(receipt.get("amount_micros", 0) or 0)
    if (
        operation not in {"hold.capture", "hold.release"}
        or sequence <= 0
        or amount < 0
        or not operation_hash
        or not receipt_hash
        or not signature
    ):
        return None
    return {
        "sequence": sequence,
        "operation": operation,
        "operation_hash": operation_hash,
        "amount_micros": amount,
        "receipt_hash": receipt_hash,
        "signature": signature,
    }


def _settlement_attestation_view(row: MediaJob) -> dict | None:
    """Return the exact verified Mint envelope, never a reconstructed proof."""
    envelope = dict(getattr(row, "settlement_attestation", {}) or {})
    expected_keys = {
        "format",
        "payload_base64url",
        "digest_sha256",
        "signer_key_id",
        "signature_hex",
    }
    if set(envelope) != expected_keys:
        return None
    if envelope.get("format") != "mint-hold-settlement-attestation-v1":
        return None
    if any(not isinstance(envelope.get(key), str) or not envelope[key] for key in expected_keys):
        return None
    return {key: envelope[key] for key in (
        "format",
        "payload_base64url",
        "digest_sha256",
        "signer_key_id",
        "signature_hex",
    )}


def _settlement_rail(row: MediaJob) -> str:
    """Read the stamped rail; old Mint rows remain recognizable by their hold."""
    if str(row.mint_hold_id or ""):
        return "mint"
    rail = str(getattr(row, "settlement_rail", "") or "local")
    return rail if rail in {"mint", "local"} else "local"


def _settlement_status(row: MediaJob) -> str:
    outcome = str(getattr(row, "settlement_outcome", "") or "")
    proof = _settlement_receipt_proof(row)
    if _settlement_rail(row) == "mint":
        attestation = _settlement_attestation_view(row)
        verified_at_ms = int(getattr(row, "settlement_verified_at_ms", 0) or 0)
        if proof is not None and attestation is not None and verified_at_ms > 0:
            return "settled" if proof["operation"] == "hold.capture" else "released"
        # Provider-terminal and money-terminal are separate facts. Even a
        # locally stamped terminal outcome is not public Mint evidence until
        # the exact signed command attestation has passed pinned-key verification.
        return "held"
    if outcome == "captured":
        return "settled"
    if outcome == "released":
        return "released"
    status = str(row.status or "queued")
    if status == "completed":
        return "settled"
    if status in {"failed", "cancelled"}:
        return "released"
    return "held"


def identity_view(row: MediaJob) -> dict | None:
    """Safe owner-scoped proof that a job used one immutable passport version."""
    passport_id = str(row.identity_passport_id or "")
    if not passport_id:
        return None
    proof = _settlement_receipt_proof(row)
    return {
        "passport_id": passport_id,
        "version": int(row.identity_version or 0),
        "content_digest": str(row.identity_content_digest or ""),
        "provider": str(row.identity_provider or ""),
        "status": str(row.identity_status or "resolved"),
        "provenance_id": str(row.identity_provenance_id or ""),
        "request_id": str(row.settlement_request_id or ""),
        "payer_account": str(row.settlement_payer_account or ""),
        "settled_at_ms": int(row.settlement_settled_at_ms or 0),
        "receipt": proof,
    }


def settlement_evidence_view(row: MediaJob) -> dict | None:
    """Portable Relay/Passport/Abacus/Ledgerline proof, never synthesized."""
    proof = _settlement_receipt_proof(row)
    attestation = _settlement_attestation_view(row)
    verified_at_ms = int(getattr(row, "settlement_verified_at_ms", 0) or 0)
    if (
        _settlement_rail(row) != "mint"
        or proof is None
        or attestation is None
        or verified_at_ms <= 0
    ):
        return None
    request_id = str(row.settlement_request_id or row.correlation_id or "")
    payer = str(row.settlement_payer_account or "")
    settled_at_ms = int(row.settlement_settled_at_ms or 0)
    outcome = (
        "captured" if proof["operation"] == "hold.capture" else "released"
    )
    if not request_id or not payer or settled_at_ms <= 0:
        return None
    return {
        "rail": "mint",
        "outcome": outcome,
        "verified": True,
        "request_id": request_id,
        "principal": payer,
        "payer_account": payer,
        "receipt": proof,
        "attestation": attestation,
        "settled_at_ms": settled_at_ms,
        "verified_at_ms": verified_at_ms,
    }


def margin_source_view(row: MediaJob) -> dict | None:
    """Signed source facts a downstream margin event can project without guessing."""
    evidence = settlement_evidence_view(row)
    if (
        evidence is None
        or evidence["outcome"] != "captured"
        or str(row.status) != "completed"
    ):
        return None
    return {
        "request_id": evidence["request_id"],
        "source": "reelforge",
        "outcome": "succeeded",
        "model": str(row.model),
        "provider": str(row.provider),
        "cogs_micros": int(row.actual_cost_micros or row.held_cost_micros or 0),
        "source_settlement_receipt": {
            "request_id": evidence["request_id"],
            "payer_account": evidence["payer_account"],
            **dict(evidence["receipt"]),
        },
    }


def generation_view(row: MediaJob) -> dict:
    """Canonical safe timeline DTO shared by every first-party client."""
    status = str(row.status or "queued")
    actual = int(row.actual_cost_micros or 0)
    held = int(row.held_cost_micros or 0)
    output_url = str(row.output_url or "")
    effective_cost = (
        actual if status == "completed"
        else 0 if status in {"failed", "cancelled"}
        else held
    )
    provider = str(row.provider or "")
    return {
        "id": row.id,
        "model": row.model,
        "modality": row.modality,
        "provider": row.provider,
        "status": status,
        "seconds": int(row.seconds or 0),
        "held_cost_micros": held,
        "actual_cost_micros": actual,
        "effective_cost_micros": effective_cost,
        # Compatibility aliases make submit/poll/detail one DTO rather than
        # forcing first-party clients to maintain a second lossy job shape.
        "cost_micros": effective_cost,
        "settlement_status": _settlement_status(row),
        "settlement_rail": _settlement_rail(row),
        "output_url": output_url,
        "url": output_url,
        "error": str(row.error or ""),
        "correlation_id": str(row.correlation_id or f"gateway_{row.id}"),
        "provider_request_id": str(row.provider_ref or ""),
        "execution": {
            "kind": "prism" if provider.startswith("prism:") else "direct",
            "provider_request_id": str(row.provider_ref or ""),
            "resumable": status not in TERMINAL_STATUSES and bool(row.provider_ref),
        },
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "is_terminal": status in TERMINAL_STATUSES,
        "identity": identity_view(row),
        "settlement_evidence": settlement_evidence_view(row),
        "margin_source": margin_source_view(row),
    }


def credits(session: Any, user_id: str) -> dict:
    """Spendable credits (wallet balance) + lifetime gateway spend (micros)."""
    from app.domains.wallet.service import WalletService

    balance = WalletService(session).balance_view(user_id)
    spent = (
        session.query(func.coalesce(func.sum(MediaJob.actual_cost_micros), 0))
        .filter(MediaJob.user_id == user_id, MediaJob.status == "completed")
        .scalar()
    )
    return {
        "available_micros": balance["available_micros"],
        "reserved_micros": balance["reserved_micros"],
        "total_gateway_spend_micros": int(spent or 0),
        "currency": balance.get("currency", "USD"),
    }


def usage_by_model(session: Any, user_id: str, *, limit: int = 50) -> list[dict]:
    """Spend + job counts grouped by model (most-spent first)."""
    rows = (
        session.query(
            MediaJob.model,
            MediaJob.modality,
            func.count(MediaJob.id).label("jobs"),
            func.coalesce(func.sum(MediaJob.actual_cost_micros), 0).label("spend"),
            func.coalesce(func.sum(MediaJob.seconds), 0).label("seconds"),
        )
        .filter(MediaJob.user_id == user_id)
        .group_by(MediaJob.model, MediaJob.modality)
        .order_by(func.coalesce(func.sum(MediaJob.actual_cost_micros), 0).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "model": model, "modality": modality, "jobs": int(jobs),
            "spend_micros": int(spend), "seconds": int(seconds),
        }
        for model, modality, jobs, spend, seconds in rows
    ]


def generation(session: Any, user_id: str, job_id: str) -> dict | None:
    """Per-generation cost/status detail (owner-scoped), or None if not found."""
    row = session.get(MediaJob, job_id)
    if row is None or str(row.user_id) != str(user_id):
        return None
    return generation_view(row)


def provenance_export(session: Any, user_id: str, job_id: str) -> dict | None:
    """Canonical, owner-scoped provenance document suitable for JSON export."""
    row = session.get(MediaJob, job_id)
    if row is None or str(row.user_id) != str(user_id):
        return None
    identity = identity_view(row)
    if identity is None:
        return None
    return {
        "schema": "menivor.media-provenance/v1",
        "generation_id": str(row.id),
        "modality": str(row.modality),
        "model": str(row.model),
        "provider": str(row.provider),
        "status": str(row.status),
        "output_url": str(row.output_url or ""),
        "correlation_id": str(row.correlation_id or f"gateway_{row.id}"),
        "identity": identity,
        "settlement_evidence": settlement_evidence_view(row),
        "margin_source": margin_source_view(row),
    }


def settlement_evidence(session: Any, user_id: str, job_id: str) -> dict | None:
    row = session.get(MediaJob, job_id)
    if row is None or str(row.user_id) != str(user_id):
        return None
    evidence = settlement_evidence_view(row)
    if evidence is None:
        return None
    return {
        "schema": "railyard.settlement-evidence/v1",
        **evidence,
        "generation_id": str(row.id),
        "provider_request_id": str(row.provider_ref or ""),
        "output_ref": str(row.output_url or ""),
        "provenance_id": str(row.identity_provenance_id or ""),
        "margin_source": margin_source_view(row),
    }


def generations(
    session: Any,
    user_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str = "",
    modality: str = "",
) -> dict:
    """Return a stable, owner-scoped generation page, newest first."""
    query = session.query(MediaJob).filter(MediaJob.user_id == user_id)
    if status:
        query = query.filter(MediaJob.status == status)
    if modality:
        query = query.filter(MediaJob.modality == modality)
    bounded = max(1, min(100, int(limit)))
    start = max(0, int(offset))
    rows = (
        query.order_by(MediaJob.created_at.desc(), MediaJob.id.desc())
        .offset(start)
        .limit(bounded + 1)
        .all()
    )
    return {
        "generations": [generation_view(row) for row in rows[:bounded]],
        "limit": bounded,
        "offset": start,
        "has_more": len(rows) > bounded,
    }


def pending_generation_ids(
    session: Any, user_id: str, *, limit: int = 10
) -> list[str]:
    """Oldest accepted unfinished jobs, bounded for opportunistic recovery."""
    rows = (
        session.query(MediaJob.id)
        .filter(
            MediaJob.user_id == user_id,
            MediaJob.status.notin_(TERMINAL_STATUSES),
        )
        .order_by(MediaJob.created_at.asc(), MediaJob.id.asc())
        .limit(max(0, min(20, int(limit))))
        .all()
    )
    return [str(row[0]) for row in rows]
