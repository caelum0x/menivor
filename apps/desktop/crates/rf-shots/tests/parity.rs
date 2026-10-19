//! Golden-fixture parity: `rf-shots` must produce bit/byte-identical output to
//! the shared `@reelforge/shot-template-schema` package. The TS and Python ports
//! are already golden-tested against the same `templates.json`, so asserting the
//! Rust port here makes it a 3-way parity guarantee.
//!
//! The fixture is loaded at runtime from the package via a manifest-relative
//! path — it is never copied into the crate.

use rf_shots::{
    content_hash, get_preset, total_duration_ms, validate_template, ShotTemplate, ROLE_ORDER,
};
use serde_json::Value;

/// Load the shared golden fixture straight from the package (single source of
/// truth). `CARGO_MANIFEST_DIR` is `apps/desktop/crates/rf-shots`, so `../../../..`
/// reaches the repo root and `packages/shot-template-schema/...` resolves.
fn load_golden() -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../../packages/shot-template-schema/test/fixtures/golden/templates.json"
    );
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("failed to read golden fixture at {path}: {e}"));
    serde_json::from_str(&raw).unwrap_or_else(|e| panic!("golden fixture is not valid JSON: {e}"))
}

fn string_array(v: &Value) -> Vec<String> {
    v.as_array()
        .expect("expected a JSON array")
        .iter()
        .map(|e| e.as_str().expect("expected a JSON string").to_string())
        .collect()
}

/// `ROLE_ORDER` mirrors the golden `role_order` exactly (order-sensitive).
#[test]
fn role_order_matches_golden() {
    let golden = load_golden();
    let want = string_array(&golden["role_order"]);
    let got: Vec<String> = ROLE_ORDER.iter().map(|r| (*r).to_string()).collect();
    assert_eq!(got, want, "ROLE_ORDER diverged from golden fixture");
}

/// Every preset the fixture describes must match the Rust port byte-for-byte:
/// the serialized template, the FNV-1a-32 content hash, the total duration, the
/// validation result, and the ordered slot roles.
#[test]
fn presets_match_golden() {
    let golden = load_golden();
    let presets = golden["presets"]
        .as_object()
        .expect("golden.presets must be an object");

    assert!(!presets.is_empty(), "golden fixture has no presets");

    for (slug, case) in presets {
        let t = get_preset(slug).unwrap_or_else(|e| panic!("get_preset({slug}) failed: {e}"));

        // 1. Full template structure (serde snake_case) must equal the golden
        //    template. serde_json::Value object comparison is key-order agnostic.
        let got_template = serde_json::to_value(&t)
            .unwrap_or_else(|e| panic!("serializing {slug} template failed: {e}"));
        assert_eq!(
            got_template, case["template"],
            "template structure mismatch for {slug}"
        );

        // 2. Deterministic FNV-1a-32 content hash — the byte-identical guarantee.
        assert_eq!(
            content_hash(&t),
            case["hash"].as_str().expect("hash must be a string"),
            "content_hash mismatch for {slug}"
        );

        // 3. Total duration (integer ms).
        assert_eq!(
            total_duration_ms(&t),
            case["total_ms"].as_i64().expect("total_ms must be an int"),
            "total_duration_ms mismatch for {slug}"
        );

        // 4. Validation errors (order-sensitive) and the derived valid flag.
        let errs = validate_template(&t);
        let want_errs = string_array(&case["errors"]);
        assert_eq!(
            errs, want_errs,
            "validate_template errors mismatch for {slug}"
        );
        assert_eq!(
            errs.is_empty(),
            case["valid"].as_bool().expect("valid must be a bool"),
            "valid flag mismatch for {slug}"
        );

        // 5. Ordered slot roles.
        let got_roles: Vec<String> = t.slots.iter().map(|s| s.role.clone()).collect();
        assert_eq!(
            got_roles,
            string_array(&case["roles"]),
            "slot roles mismatch for {slug}"
        );

        // 6. Round-trip the golden template JSON back through the Rust type and
        //    confirm the hash still matches — proves deserialization parity too.
        let parsed: ShotTemplate = serde_json::from_value(case["template"].clone())
            .unwrap_or_else(|e| panic!("deserializing golden {slug} template failed: {e}"));
        assert_eq!(
            parsed, t,
            "deserialized golden template != Rust preset for {slug}"
        );
        assert_eq!(
            content_hash(&parsed),
            case["hash"].as_str().unwrap(),
            "hash of deserialized golden template mismatch for {slug}"
        );
    }
}
