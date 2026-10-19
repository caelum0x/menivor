"""Wallet integration for clipping jobs — reuses the reels wallet bridge.

The clipping pipeline funds jobs from the USD wallet exactly like reel jobs
(reserve the quoted max cost at create, settle on success, release on failure),
so rather than reinventing that logic this module re-exports the battle-tested
:mod:`app.domains.reels.wallet_bridge` helpers. Keeping a thin clipping-scoped
module means callers import ``domains.clipping.wallet_bridge`` (matching the
domain layout) while the single implementation lives in one place.
"""

from __future__ import annotations

from app.domains.reels.wallet_bridge import (
    WALLET_MARKER_KEY,
    WalletBridgeError,
    WalletIntent,
    extract_wallet_intent,
    read_marker,
    record_actual_micros,
    release_job,
    reserve_for_job,
    safe_release_job,
    safe_release_job_by_id,
    safe_settle_job,
    safe_settle_job_by_id,
    settle_job,
    settle_job_actual,
    validate_intent,
)

__all__ = [
    "WALLET_MARKER_KEY",
    "WalletBridgeError",
    "WalletIntent",
    "extract_wallet_intent",
    "read_marker",
    "record_actual_micros",
    "release_job",
    "reserve_for_job",
    "safe_release_job",
    "safe_release_job_by_id",
    "safe_settle_job",
    "safe_settle_job_by_id",
    "settle_job",
    "settle_job_actual",
    "validate_intent",
]
