//! Golden-fixture parity: the Rust port must produce output byte-identical to
//! the shared `@reelforge/comfy-workflow-schema` package. The TS and Python
//! ports are already golden-tested against the same `workflows.json`, so passing
//! this suite makes the guarantee three-way (TS ≡ Python ≡ Rust).
//!
//! The fixture is loaded at runtime from the package via a manifest-relative
//! path (never copied), so a drift in the golden file fails this test.

use rf_workflows::{get_workflow, graph_hash, validate_inputs};
use serde_json::{Map, Value};

/// Load and parse the shared golden fixture straight from the package.
fn golden() -> Value {
    // `CARGO_MANIFEST_DIR` = apps/desktop/crates/rf-workflows; four `..`
    // segments reach the repo root, where `packages/...` resolves.
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../../packages/comfy-workflow-schema/test/fixtures/golden/workflows.json"
    );
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("failed to read golden fixture at {path}: {e}"));
    serde_json::from_str(&raw).expect("golden fixture must be valid JSON")
}

fn as_object(v: &Value) -> &Map<String, Value> {
    v.as_object().expect("expected a JSON object")
}

/// Every workflow's descriptor, category, input-name list, and FNV-1a pin must
/// match the golden fixture exactly. Mirrors the `getWorkflow` + `graphHash`
/// checks in `test/parity.mjs`.
#[test]
fn workflows_match_golden() {
    let golden = golden();
    let workflows = as_object(&golden["workflows"]);
    assert!(!workflows.is_empty(), "fixture has no workflows");

    let mut checked = 0usize;
    for (slug, case) in workflows {
        let w = get_workflow(slug).unwrap_or_else(|e| panic!("get_workflow({slug}): {e}"));

        // Descriptor: serialize the Rust DTO and compare structurally (order-
        // independent) against the golden descriptor.
        let got = serde_json::to_value(&w).expect("descriptor serializes");
        assert_eq!(
            got, case["descriptor"],
            "descriptor mismatch for {slug}\n  rust:   {got}\n  golden: {}",
            case["descriptor"]
        );

        // FNV-1a-32 pin.
        let hash = graph_hash(&w);
        assert_eq!(
            Value::String(hash.clone()),
            case["hash"],
            "hash mismatch for {slug}: rust={hash} golden={}",
            case["hash"]
        );

        // Category convenience field on the fixture.
        assert_eq!(
            Value::String(w.category.clone()),
            case["category"],
            "category mismatch for {slug}"
        );

        // Ordered input names.
        let names: Vec<Value> = w
            .inputs
            .iter()
            .map(|s| Value::String(s.name.clone()))
            .collect();
        assert_eq!(
            Value::Array(names),
            case["inputs"],
            "input-name order mismatch for {slug}"
        );

        checked += 4;
    }
    eprintln!(
        "workflows_match_golden: {checked} assertions across {} slugs",
        workflows.len()
    );
}

/// Every validation case must yield the exact error list. Mirrors the
/// `validateInputs` checks in `test/parity.mjs`.
#[test]
fn validation_matches_golden() {
    let golden = golden();
    let cases = as_object(&golden["validation"]);
    assert!(!cases.is_empty(), "fixture has no validation cases");

    for (name, case) in cases {
        let slug = case["slug"].as_str().expect("validation.slug is a string");
        let w = get_workflow(slug).unwrap_or_else(|e| panic!("get_workflow({slug}): {e}"));
        let values = as_object(&case["values"]);

        let errors = validate_inputs(&w, values);
        let got = serde_json::to_value(&errors).expect("errors serialize");
        assert_eq!(
            got, case["errors"],
            "validation mismatch for '{name}' (slug={slug})\n  rust:   {got}\n  golden: {}",
            case["errors"]
        );
    }
    eprintln!("validation_matches_golden: {} cases", cases.len());
}
