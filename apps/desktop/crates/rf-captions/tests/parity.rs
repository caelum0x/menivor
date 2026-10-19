//! Golden-fixture parity: `rf-captions` must produce byte-identical ASS output
//! to the shared `@reelforge/caption-engine` package.
//!
//! The TS and Python ports are already golden-tested against the same fixtures
//! under `packages/caption-engine/test/fixtures/golden/`, so asserting the Rust
//! port here makes it a 3-way (TS ≡ Python ≡ Rust) byte-parity guarantee.
//!
//! Fixture layout (mirrors `packages/caption-engine/test/parity.mjs`):
//! - `words.json` — the shared INPUT: `Vec<Word>` word timestamps.
//! - `<preset>.ass` — the EXPECTED output of `buildAss(words, getPreset(<preset>))`
//!   for each preset name (file stem == preset name).
//!
//! The fixtures are read at runtime from the package via a manifest-relative
//! path — they are NOT copied into this crate, so the three ports assert against
//! the exact same bytes.

use rf_captions::{build_ass, get_preset, Word};

/// Repo-root-relative fixtures dir. `CARGO_MANIFEST_DIR` is this crate
/// (`apps/desktop/crates/rf-captions`); `../../../..` reaches the repo root.
const GOLDEN_DIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../../packages/caption-engine/test/fixtures/golden"
);

/// Load the shared INPUT words (`words.json`) exactly as the TS/Python ports do.
fn load_words() -> Vec<Word> {
    let path = format!("{GOLDEN_DIR}/words.json");
    let raw = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("read golden words.json at {path}: {e}"));
    serde_json::from_str(&raw).unwrap_or_else(|e| panic!("parse golden words.json: {e}"))
}

/// Every `<preset>.ass` golden file, sorted for a deterministic report order.
fn golden_ass_presets() -> Vec<String> {
    let mut presets: Vec<String> = std::fs::read_dir(GOLDEN_DIR)
        .unwrap_or_else(|e| panic!("read golden dir {GOLDEN_DIR}: {e}"))
        .map(|entry| entry.expect("golden dir entry").path())
        .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("ass"))
        .map(|p| {
            p.file_stem()
                .and_then(|s| s.to_str())
                .expect("golden .ass file stem")
                .to_string()
        })
        .collect();
    presets.sort();
    presets
}

/// Assert `build_ass(words, getPreset(preset))` reproduces every golden `.ass`
/// fixture byte-for-byte. Covers `get_preset` + `build_ass` (which in turn
/// exercises `format_time`, `hex_to_ass`, and the style/dialogue assembly) —
/// the full surface the fixtures touch, identical to `parity.mjs`.
#[test]
fn build_ass_matches_every_golden_fixture() {
    let words = load_words();
    let presets = golden_ass_presets();
    assert!(
        !presets.is_empty(),
        "no golden .ass fixtures found in {GOLDEN_DIR}"
    );

    for preset_name in &presets {
        let expected_path = format!("{GOLDEN_DIR}/{preset_name}.ass");
        let expected = std::fs::read_to_string(&expected_path)
            .unwrap_or_else(|e| panic!("read golden {expected_path}: {e}"));

        let style =
            get_preset(preset_name).unwrap_or_else(|e| panic!("get_preset({preset_name}): {e}"));
        let got = build_ass(&words, Some(&style));

        assert_eq!(
            got, expected,
            "\nRust `build_ass` output for preset `{preset_name}` differs from the \
             golden `@reelforge/caption-engine` fixture — parity bug in rf-captions.\n\
             Fixture: {expected_path}\n"
        );
    }
}

/// The `hormozi` preset is also `build_ass`'s default (`style == None`); the
/// golden fixture must match that path too, mirroring the TS default arg.
#[test]
fn build_ass_default_matches_hormozi_golden() {
    let words = load_words();
    let expected_path = format!("{GOLDEN_DIR}/hormozi.ass");
    let expected = std::fs::read_to_string(&expected_path)
        .unwrap_or_else(|e| panic!("read golden {expected_path}: {e}"));

    assert_eq!(
        build_ass(&words, None),
        expected,
        "default (None) style must equal the hormozi golden fixture"
    );
}
