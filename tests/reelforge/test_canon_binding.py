"""Canon provenance binding — stamp job/asset + three-gate verify (pure)."""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.canon.binding import (
    stamp_asset_from_params,
    stamp_asset_meta,
    stamp_job_params,
    verify_asset,
)
from app.domains.canon.canon_hash import CanonValues, canon_hash


def _locked(**over):
    fields = {"style": "3D", "palette": ("#ff0000",), "product_name": "Nova"}
    fields.update(over)
    v = CanonValues(**fields)
    return v, canon_hash(v)


@dataclass
class _VersionRow:
    """A test double for a CanonVersion row (values + stored canon_hash)."""

    values: dict
    canon_hash: str


def _row(values: CanonValues, stored_hash: str) -> _VersionRow:
    return _VersionRow(values=values.normalized_dict(), canon_hash=stored_hash)


def test_stamp_job_params_returns_new_dict_without_mutation():
    original = {"character": {"shots": [1, 2]}}
    out = stamp_job_params(original, canon_id="c1", canon_hash="cv1|abc", canon_version=1)
    assert out is not original
    assert "canon" not in original  # original untouched
    assert out["canon"] == {"canon_id": "c1", "canon_hash": "cv1|abc", "canon_version": 1}
    assert out["character"] == {"shots": [1, 2]}


def test_stamp_asset_meta_returns_new_dict_without_mutation():
    original = {"foo": "bar"}
    out = stamp_asset_meta(original, canon_id="c1", canon_hash="cv1|abc", canon_version=2)
    assert out is not original and "canon_hash" not in original
    assert out["canon_hash"] == "cv1|abc"
    assert out["canon_version"] == 2
    assert out["canon_id"] == "c1"
    assert out["foo"] == "bar"
    # None meta is tolerated.
    assert stamp_asset_meta(None, canon_id="c1", canon_hash="cv1|x", canon_version=1)["canon_hash"] == "cv1|x"


def test_stamp_asset_from_params_threads_canon_block():
    params = stamp_job_params({"character": {"shots": []}},
                             canon_id="c1", canon_hash="cv1|abc", canon_version=3)
    meta = stamp_asset_from_params({"correlation_id": "r1"}, params)
    assert meta["canon_hash"] == "cv1|abc"
    assert meta["canon_version"] == 3
    assert meta["canon_id"] == "c1"
    assert meta["correlation_id"] == "r1"  # existing meta preserved


def test_stamp_asset_from_params_is_noop_without_canon():
    assert stamp_asset_from_params({"x": 1}, {"character": {}}) == {"x": 1}
    assert stamp_asset_from_params(None, None) == {}
    # A malformed canon block (no hash) is ignored, not fabricated.
    assert "canon_hash" not in stamp_asset_from_params({}, {"canon": {"canon_id": "c1"}})


def test_verify_passes_for_matching_stamp():
    values, h = _locked()
    meta = stamp_asset_meta({}, canon_id="c1", canon_hash=h, canon_version=1)
    res = verify_asset(meta, _row(values, h))
    assert res.verified is True


def test_verify_fails_provenance_on_flipped_hash():
    values, h = _locked()
    tampered = h[:-1] + ("0" if h[-1] != "0" else "1")
    meta = stamp_asset_meta({}, canon_id="c1", canon_hash=tampered, canon_version=1)
    res = verify_asset(meta, _row(values, h))
    assert res.verified is False and res.reason == "wrong/edited canon"


def test_verify_fails_integrity_on_tampered_stored_values():
    values, h = _locked()
    row = _row(values, h)
    row.values = {**row.values, "style": "HACKED"}  # mutate stored values, keep old hash
    meta = stamp_asset_meta({}, canon_id="c1", canon_hash=h, canon_version=1)
    res = verify_asset(meta, row)
    assert res.verified is False and res.reason == "canon row tampered"


def test_verify_fails_unverifiable_when_asset_not_stamped():
    values, h = _locked()
    res = verify_asset({"foo": "bar"}, _row(values, h))
    assert res.verified is False and res.reason == "asset not stamped"


def test_verify_fails_across_versions():
    v1, h1 = _locked(style="v1")
    v2, h2 = _locked(style="v2")
    # Asset stamped under v1, verified against the v2 row -> mismatch.
    meta = stamp_asset_meta({}, canon_id="c1", canon_hash=h1, canon_version=1)
    res = verify_asset(meta, _row(v2, h2))
    assert res.verified is False and res.reason == "wrong/edited canon"
