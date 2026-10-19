//! GOLDEN-FIXTURE PARITY — `rf-growth` must reproduce every golden case from
//! `@reelforge/growth-analytics`, byte-for-byte.
//!
//! The same `analytics.json` fixture is asserted against the TypeScript source
//! and its Python port; asserting it here makes it a 3-way parity guarantee
//! (TS ≡ Python ≡ Rust). The fixture is loaded at runtime from the package via
//! a manifest-relative path — it is never copied into this crate.

use rf_growth::{
    dropoff, hook_score, normalize_curve, reach_tier, select_winner, HookSignals, Variant,
};
use serde_json::Value;

/// Load and parse the shared golden fixture from the `growth-analytics` package.
fn golden() -> Value {
    // `CARGO_MANIFEST_DIR` is this crate dir; `../../../..` reaches the repo root.
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../../packages/growth-analytics/test/fixtures/golden/analytics.json"
    );
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("failed to read golden fixture at {path}: {e}"));
    serde_json::from_str(&raw).expect("golden fixture is valid JSON")
}

/// Iterate every entry of a top-level fixture section as `(name, case)` pairs.
fn cases<'a>(g: &'a Value, section: &str) -> impl Iterator<Item = (String, &'a Value)> {
    g[section]
        .as_object()
        .unwrap_or_else(|| panic!("fixture section `{section}` is missing or not an object"))
        .iter()
        .map(|(k, v)| (k.clone(), v))
}

/// Serialize a Rust result and assert deep equality with the golden value.
/// serde_json `Value` compares numbers by their parsed representation and
/// objects by key (order-independent), so this is an exact structural match.
fn assert_parity<T: serde::Serialize>(label: &str, got: T, want: &Value) {
    let got = serde_json::to_value(got).expect("result serializes");
    assert_eq!(
        &got, want,
        "\nPARITY MISMATCH {label}\n  rust: {got}\n  gold: {want}\n"
    );
}

#[test]
fn retention_normalize_curve_matches_golden() {
    let g = golden();
    let mut checked = 0;
    for (name, case) in cases(&g, "retention") {
        let samples: Vec<f64> = serde_json::from_value(case["samples"].clone()).unwrap();
        assert_parity(
            &format!("retention.{name}"),
            normalize_curve(&samples),
            &case["curve"],
        );
        checked += 1;
    }
    assert_eq!(checked, 3, "expected 3 retention cases");
}

#[test]
fn reach_tier_matches_golden() {
    let g = golden();
    let mut checked = 0;
    for (name, case) in cases(&g, "reach") {
        let avg = case["avg"].as_f64().unwrap();
        assert_parity(&format!("reach.{name}"), reach_tier(avg), &case["tier"]);
        checked += 1;
    }
    assert_eq!(checked, 5, "expected 5 reach cases");
}

#[test]
fn dropoff_matches_golden() {
    let g = golden();
    let mut checked = 0;
    for (name, case) in cases(&g, "dropoff") {
        let curve: Vec<f64> = serde_json::from_value(case["curve"].clone()).unwrap();
        assert_parity(
            &format!("dropoff.{name}"),
            dropoff(&curve),
            &case["dropoff"],
        );
        checked += 1;
    }
    assert_eq!(checked, 3, "expected 3 dropoff cases");
}

#[test]
fn hook_score_matches_golden() {
    let g = golden();
    let mut checked = 0;
    for (name, case) in cases(&g, "hook") {
        let signals: HookSignals = serde_json::from_value(case["signals"].clone()).unwrap();
        assert_parity(
            &format!("hook.{name}"),
            hook_score(&signals),
            &case["result"],
        );
        checked += 1;
    }
    assert_eq!(checked, 3, "expected 3 hook cases");
}

#[test]
fn ab_select_winner_matches_golden() {
    let g = golden();
    let mut checked = 0;
    for (name, case) in cases(&g, "ab") {
        let variants: Vec<Variant> = serde_json::from_value(case["variants"].clone()).unwrap();
        assert_parity(
            &format!("ab.{name}"),
            select_winner(&variants),
            &case["result"],
        );
        checked += 1;
    }
    assert_eq!(checked, 1, "expected 1 ab case");
}
