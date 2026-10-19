//! 3-way golden-fixture parity: this Rust crate vs the shared
//! `@reelforge/provider-adapter-kit` package (which the TS and Python ports are
//! already golden-tested against).
//!
//! The fixture is loaded at runtime from the package via a manifest-relative
//! path — it is NOT copied into this crate. Every entry maps an INPUT to its
//! EXPECTED output; each case is asserted against the corresponding Rust
//! function so all three ports emit byte-identical metadata.

use rf_provider::{
    can_use_for_paid, is_terminal, license_class, migrate, normalize_state, normalized_usage,
};
use serde_json::Value;

/// Load and parse the shared golden fixture from the package (no copy).
fn golden() -> Value {
    // CARGO_MANIFEST_DIR = apps/desktop/crates/rf-provider; `../../../..` = repo root.
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../../packages/provider-adapter-kit/test/fixtures/golden/adapter.json"
    );
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("failed to read golden fixture at {path}: {e}"));
    serde_json::from_str(&raw).unwrap_or_else(|e| panic!("failed to parse golden fixture: {e}"))
}

fn obj<'a>(v: &'a Value, key: &str) -> &'a serde_json::Map<String, Value> {
    v.get(key)
        .unwrap_or_else(|| panic!("golden missing `{key}` section"))
        .as_object()
        .unwrap_or_else(|| panic!("golden `{key}` is not an object"))
}

/// Asserts every golden case matches the Rust port and returns the case count.
#[test]
fn golden_fixture_three_way_parity() {
    let g = golden();
    let mut cases = 0usize;

    // license.ts — licenseClass(modelId) → kebab-case class string.
    for (model, want) in obj(&g, "license") {
        let got = serde_json::to_value(license_class(model)).unwrap();
        assert_eq!(&got, want, "license.{model}");
        cases += 1;
    }

    // license.ts — canUseForPaid(modelId) → bool.
    for (model, want) in obj(&g, "paid") {
        let got = Value::Bool(can_use_for_paid(model));
        assert_eq!(&got, want, "paid.{model}");
        cases += 1;
    }

    // deprecation.ts — migrate(modelId, today) → MigrationHint object.
    for (model, by_date) in obj(&g, "deprecation") {
        for (date, want) in by_date
            .as_object()
            .unwrap_or_else(|| panic!("deprecation.{model} is not an object"))
        {
            let got = serde_json::to_value(migrate(model, date)).unwrap();
            assert_eq!(&got, want, "migrate.{model}.{date}");
            cases += 1;
        }
    }

    // envelope.ts — normalizeState(raw) → state, isTerminal(state) → bool.
    for (raw, want) in obj(&g, "envelope") {
        let want_state = &want["state"];
        let want_terminal = &want["terminal"];
        let state = normalize_state(raw);
        let got_state = serde_json::to_value(state).unwrap();
        assert_eq!(&got_state, want_state, "state.{raw:?}");
        assert_eq!(
            &Value::Bool(is_terminal(state)),
            want_terminal,
            "terminal.{raw:?}"
        );
        cases += 2;
    }

    // envelope.ts — normalizedUsage(units, costMicros, success) → NormalizedUsage.
    // The parity harness fixes inputs at units=5.0, cost_micros=420000.
    let usage = obj(&g, "usage");
    let got_ok = serde_json::to_value(normalized_usage(5.0, 420000.0, true)).unwrap();
    assert_eq!(
        &got_ok,
        &Value::Object(usage["ok"].as_object().unwrap().clone()),
        "usage.ok"
    );
    cases += 1;
    let got_fail = serde_json::to_value(normalized_usage(5.0, 420000.0, false)).unwrap();
    assert_eq!(
        &got_fail,
        &Value::Object(usage["fail"].as_object().unwrap().clone()),
        "usage.fail"
    );
    cases += 1;

    // Sanity: the fixture must actually exercise every function group.
    assert!(cases >= 51, "expected >=51 golden cases, got {cases}");
    eprintln!("rf-provider 3-way golden parity OK ({cases} cases)");
}
