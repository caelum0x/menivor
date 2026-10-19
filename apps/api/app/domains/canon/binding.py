"""Canon provenance binding — stamp generation with the lock, then verify it.

Provenance is threaded onto BOTH the job (request-time) and every final asset
(artifact-time) so an ad is reconstructable end-to-end:

* :func:`stamp_job_params` writes ``params['canon']`` beside the existing
  ``params['character']`` at reel/job-create time.
* :func:`stamp_asset_meta` writes ``canon_hash`` / ``canon_version`` /
  ``canon_id`` into the opaque ``Asset.meta`` JSON at the worker's final-asset
  write (no migration — ``meta`` is a JSON blob).

Both stamps return NEW dicts (the immutability rule — never mutate the caller's
params/meta).

:func:`verify_asset` is a provenance + integrity check with three ordered gates:

1. INTEGRITY  — recompute ``canon_hash`` from the stored locked values; if it
   does not equal the stored hash, the canon row itself was tampered/forged.
2. UNVERIFIABLE — the asset carries no ``canon_hash`` (produced outside the
   canon regime).
3. PROVENANCE — the asset's stamped hash does not equal the version's hash (the
   asset was produced under a different locked version).

Only when all three pass is the asset proven to have been produced under exactly
this immutable, untampered locked version. String comparisons use
``hmac.compare_digest`` (constant-time, like ``policy.verify_quote``).
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from app.domains.canon.canon_hash import CanonValues
from app.domains.canon.canon_hash import canon_hash as _compute_canon_hash

# Reasons are stable strings so callers/tests can assert on them.
_REASON_OK = "ok"
_REASON_TAMPERED = "canon row tampered"
_REASON_UNSTAMPED = "asset not stamped"
_REASON_WRONG = "wrong/edited canon"


@dataclass(frozen=True)
class VerifyResult:
    """The outcome of :func:`verify_asset` — verified flag + human reason."""

    verified: bool
    reason: str


def stamp_job_params(
    params: dict | None, *, canon_id: str, canon_hash: str, canon_version: int
) -> dict:
    """Return a NEW params dict carrying the canon lock beside ``character``.

    Written at reel/image/ad job-create time when a job is bound to a canon.
    """
    return {
        **(params or {}),
        "canon": {
            "canon_id": canon_id,
            "canon_hash": canon_hash,
            "canon_version": canon_version,
        },
    }


def stamp_asset_meta(
    meta: dict | None, *, canon_id: str, canon_hash: str, canon_version: int
) -> dict:
    """Return a NEW asset-meta dict recording the canon this file was made under."""
    return {
        **(meta or {}),
        "canon_hash": canon_hash,
        "canon_version": canon_version,
        "canon_id": canon_id,
    }


def stamp_asset_from_params(meta: dict | None, params: dict | None) -> dict:
    """Thread a job's ``params['canon']`` lock onto an asset's meta (new dict).

    The generation worker's final-asset write calls this so every produced file
    carries the canon it was made under. If the job was not bound to a canon (no
    ``params['canon']`` block) the meta is returned unchanged — canon is
    strictly optional and never fabricated.
    """
    canon = (params or {}).get("canon")
    if not isinstance(canon, dict) or not canon.get("canon_hash"):
        return dict(meta or {})
    return stamp_asset_meta(
        meta,
        canon_id=canon.get("canon_id", ""),
        canon_hash=canon["canon_hash"],
        canon_version=canon.get("canon_version"),
    )


def _row_get(row: Any, key: str) -> Any:
    """Read ``key`` from an ORM row or a mapping (test-double friendly)."""
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def verify_asset(asset_meta: dict | None, canon_version_row: Any) -> VerifyResult:
    """Run the three-gate integrity + provenance check for one asset.

    ``canon_version_row`` is any object exposing ``values`` (the stored
    normalized payload) and ``canon_hash`` (its stored content address) — an ORM
    ``CanonVersion`` row or a mapping.
    """
    stored_values = _row_get(canon_version_row, "values") or {}
    stored_hash = str(_row_get(canon_version_row, "canon_hash") or "")

    # Gate 1 — INTEGRITY: the stored hash must match a fresh recompute of the
    # stored values. Any mutation of the row (or a mismatched hash) fails here.
    try:
        recomputed = _compute_canon_hash(CanonValues(**stored_values))
    except (TypeError, ValueError):
        return VerifyResult(False, _REASON_TAMPERED)
    if not stored_hash or not hmac.compare_digest(recomputed, stored_hash):
        return VerifyResult(False, _REASON_TAMPERED)

    # Gate 2 — UNVERIFIABLE: the asset must carry a canon stamp at all.
    asset_hash = str((asset_meta or {}).get("canon_hash") or "")
    if not asset_hash:
        return VerifyResult(False, _REASON_UNSTAMPED)

    # Gate 3 — PROVENANCE: the asset's stamp must match this locked version.
    if not hmac.compare_digest(asset_hash, stored_hash):
        return VerifyResult(False, _REASON_WRONG)

    return VerifyResult(True, _REASON_OK)
