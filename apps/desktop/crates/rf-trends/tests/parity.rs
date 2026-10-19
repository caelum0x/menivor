//! 3-way golden-fixture parity: the Rust port must reproduce, bit/byte-exact,
//! every case in `@reelforge/trends-schema`'s golden fixture — the SAME fixture
//! the TS and Python ports are golden-tested against. The fixture is loaded at
//! runtime from the package (never copied), so any drift between the ports and
//! the shared source of truth fails this test.

use std::collections::BTreeMap;

use rf_trends::{ad_safe, score, SoundFlags};
use serde::Deserialize;

/// Top-level shape of `packages/trends-schema/test/fixtures/golden/scores.json`.
#[derive(Debug, Deserialize)]
struct Golden {
    ad_safe: BTreeMap<String, AdSafeCase>,
    scores: BTreeMap<String, ScoreCase>,
}

#[derive(Debug, Deserialize)]
struct AdSafeCase {
    ad_safe: bool,
    sound: SoundFlags,
}

#[derive(Debug, Deserialize)]
struct ScoreCase {
    score: ExpectedScore,
    series: Vec<f64>,
}

/// Expected score object; the golden values are already `round6`-quantized, so
/// the parsed f64 is the exact nearest double to the emitted 6-dp decimal — the
/// Rust `round6` output must equal it bit-for-bit (same as TS/Python `===`).
#[derive(Debug, Deserialize)]
struct ExpectedScore {
    saturation: f64,
    velocity: f64,
    decay: f64,
    opportunity: f64,
}

fn load_golden() -> Golden {
    // CARGO_MANIFEST_DIR = crate dir; `../../../..` reaches the repo root, so
    // `packages/trends-schema/...` resolves to the shared fixture.
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../../packages/trends-schema/test/fixtures/golden/scores.json"
    );
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("failed to read golden fixture at {path}: {e}"));
    serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("failed to parse golden fixture at {path}: {e}"))
}

#[test]
fn golden_scores_are_bit_exact() {
    let golden = load_golden();
    assert!(
        !golden.scores.is_empty(),
        "no score cases in golden fixture"
    );

    for (name, case) in &golden.scores {
        let got = score(&case.series);
        // Exact equality — round6 is deterministic and the fixture is quantized.
        assert_eq!(
            got.saturation, case.score.saturation,
            "saturation mismatch for scores.{name} (series {:?})",
            case.series
        );
        assert_eq!(
            got.velocity, case.score.velocity,
            "velocity mismatch for scores.{name} (series {:?})",
            case.series
        );
        assert_eq!(
            got.decay, case.score.decay,
            "decay mismatch for scores.{name} (series {:?})",
            case.series
        );
        assert_eq!(
            got.opportunity, case.score.opportunity,
            "opportunity mismatch for scores.{name} (series {:?})",
            case.series
        );
    }
}

#[test]
fn golden_ad_safe_matches() {
    let golden = load_golden();
    assert!(
        !golden.ad_safe.is_empty(),
        "no ad_safe cases in golden fixture"
    );

    for (name, case) in &golden.ad_safe {
        assert_eq!(
            ad_safe(&case.sound),
            case.ad_safe,
            "ad_safe mismatch for ad_safe.{name} (sound {:?})",
            case.sound
        );
    }
}
