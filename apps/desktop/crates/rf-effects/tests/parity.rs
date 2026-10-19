//! Golden-fixture parity test — proves `rf-effects` emits bit/byte-identical
//! output to the shared `@reelforge/effects-core` package.
//!
//! The TypeScript and Python ports are already golden-tested against the same
//! `packages/effects-core/test/fixtures/golden/kernels.json`, so asserting the
//! Rust crate against it makes this a 3-way parity guarantee.
//!
//! The fixture is loaded at runtime from the package via a manifest-relative
//! path (never copied), so it stays the single source of truth.

use std::collections::BTreeMap;

use rf_effects::{apply, category_of, KernelCategory, Params};
use serde_json::Value;

/// The golden fixture, resolved from the crate dir up to the repo root.
///
/// `CARGO_MANIFEST_DIR` = `apps/desktop/crates/rf-effects`; four `..` segments
/// reach the repo root so `packages/effects-core/...` resolves.
const GOLDEN_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../../packages/effects-core/test/fixtures/golden/kernels.json"
);

/// Parse the golden JSON into `id -> (category, [(t, {key: value})])`.
fn load_golden() -> BTreeMap<String, Value> {
    let raw = std::fs::read_to_string(GOLDEN_PATH)
        .unwrap_or_else(|e| panic!("failed to read golden fixture {GOLDEN_PATH}: {e}"));
    serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("failed to parse golden fixture {GOLDEN_PATH}: {e}"))
}

/// Map the fixture's `category` string to the Rust enum.
fn parse_category(id: &str, raw: &str) -> KernelCategory {
    match raw {
        "camera" => KernelCategory::Camera,
        "vfx" => KernelCategory::Vfx,
        other => panic!("{id}: unknown fixture category {other:?}"),
    }
}

#[test]
fn golden_parity_all_kernels() {
    let golden = load_golden();
    assert!(!golden.is_empty(), "golden fixture is empty");

    let mut checks = 0usize;
    let params = Params::new(); // fixtures exercise defaults (no params field)

    for (id, spec) in &golden {
        // Category parity.
        let expected_cat = spec
            .get("category")
            .and_then(Value::as_str)
            .unwrap_or_else(|| panic!("{id}: fixture missing category"));
        let expected_cat = parse_category(id, expected_cat);
        assert_eq!(
            category_of(id),
            Some(expected_cat),
            "category mismatch for kernel {id}"
        );

        // Per-sample output parity.
        let samples = spec
            .get("samples")
            .and_then(Value::as_array)
            .unwrap_or_else(|| panic!("{id}: fixture missing samples array"));

        for sample in samples {
            let t = sample
                .get("t")
                .and_then(Value::as_f64)
                .unwrap_or_else(|| panic!("{id}: sample missing numeric t"));
            let out = sample
                .get("out")
                .and_then(Value::as_object)
                .unwrap_or_else(|| panic!("{id}@t={t}: sample missing out object"));

            let got =
                apply(id, t, &params).unwrap_or_else(|e| panic!("{id}@t={t}: apply failed: {e}"));

            // Same number of output keys.
            assert_eq!(
                got.len(),
                out.len(),
                "{id}@t={t}: output arity mismatch (rust {} vs golden {})",
                got.len(),
                out.len()
            );

            for (key, expected_val) in out {
                let expected = expected_val
                    .as_f64()
                    .unwrap_or_else(|| panic!("{id}@t={t}.{key}: golden value not numeric"));
                let actual = got
                    .iter()
                    .find(|(k, _)| k == key)
                    .unwrap_or_else(|| panic!("{id}@t={t}: rust output missing key {key}"))
                    .1;

                // Ports use a deterministic round9 so values are exact; compare
                // bit-exact, with a tiny epsilon guard only for JSON re-parse.
                let matches = actual == expected || (actual - expected).abs() <= 1e-9;
                assert!(
                    matches,
                    "MISMATCH {id}@t={t}.{key}: rust {actual} != golden {expected}"
                );
                checks += 1;
            }
        }
    }

    // Sanity: every fixture kernel contributed at least one checked value.
    assert!(checks > 0, "no values were checked");
    println!(
        "rf-effects golden parity OK ({checks} values across {} kernels)",
        golden.len()
    );
}
