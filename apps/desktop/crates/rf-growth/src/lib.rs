//! `rf-growth` — Rust port of `@reelforge/growth-analytics` (golden-parity).
//!
//! Pure funnel / retention / hook / A-B utilities: takes data, returns verdicts
//! (no I/O). Bit-identical to the TypeScript source and its Python port
//! (`reelforge_growth_analytics`, golden fixtures) so web/mobile/api/desktop all
//! compute the same numbers.
//!
//! Float scores share one rounding helper: [`round6`], a truncate
//! half-away-from-zero. Weighted sums preserve the exact summation order of the
//! TypeScript so IEEE-754 doubles match to the last bit.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

// ---------------------------------------------------------------------------
// Shared numeric helpers (bit-identical to `util.ts` / `_util.py`).
// ---------------------------------------------------------------------------

/// Clamp `x` into the inclusive range `[0, 1]`.
///
/// Equivalent to the TS ternary `x < 0 ? 0 : x > 1 ? 1 : x`; `f64::clamp`
/// applies the same branch logic (and matches its NaN / -0.0 handling).
pub fn clamp01(x: f64) -> f64 {
    x.clamp(0.0, 1.0)
}

/// Round to 6 decimals via truncation half-away-from-zero.
///
/// Mirrors `Math.trunc(x * 1e6 + bias) / 1e6` where `bias = ±0.5`.
pub fn round6(x: f64) -> f64 {
    let bias = if x >= 0.0 { 0.5 } else { -0.5 };
    (x * 1_000_000.0 + bias).trunc() / 1_000_000.0
}

// ---------------------------------------------------------------------------
// Hook strength vs the 70% gate (mirror of `hook.ts`).
// ---------------------------------------------------------------------------

/// The pass threshold for [`hook_score`].
pub const GATE: f64 = 0.7;

const W_MOTION: f64 = 0.35;
const W_CONTRAST: f64 = 0.2;
const W_TEXT: f64 = 0.2;
const W_AUDIO_ONSET: f64 = 0.25;

/// Raw hook signals; each missing signal is treated as `0`.
#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct HookSignals {
    #[serde(default)]
    pub motion: Option<f64>,
    #[serde(default)]
    pub contrast: Option<f64>,
    #[serde(default)]
    pub text: Option<f64>,
    #[serde(default)]
    pub audio_onset: Option<f64>,
}

/// Result of scoring a set of [`HookSignals`].
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct HookResult {
    pub score: f64,
    pub passes: bool,
}

/// Weighted hook score; `passes` is `score >= GATE`.
///
/// Terms are summed in the TypeScript key order (motion, contrast, text,
/// audio_onset) so the accumulated double is identical.
pub fn hook_score(signals: &HookSignals) -> HookResult {
    let mut total = 0.0;
    total += W_MOTION * clamp01(signals.motion.unwrap_or(0.0));
    total += W_CONTRAST * clamp01(signals.contrast.unwrap_or(0.0));
    total += W_TEXT * clamp01(signals.text.unwrap_or(0.0));
    total += W_AUDIO_ONSET * clamp01(signals.audio_onset.unwrap_or(0.0));
    let score = round6(total);
    HookResult {
        score,
        passes: score >= GATE,
    }
}

// ---------------------------------------------------------------------------
// Retention curve + reach tier + drop-off (mirror of `retention.ts`).
// ---------------------------------------------------------------------------

/// Reach tier bucket with its distribution multiplier.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tier {
    Viral,
    Boosted,
    Minimal,
}

impl Tier {
    fn as_str(self) -> &'static str {
        match self {
            Tier::Viral => "viral",
            Tier::Boosted => "boosted",
            Tier::Minimal => "minimal",
        }
    }
}

impl Serialize for Tier {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(self.as_str())
    }
}

/// Reach tier + multiplier returned by [`reach_tier`].
#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
pub struct ReachTier {
    pub tier: Tier,
    pub multiplier: f64,
}

/// Normalize raw retention samples to `[0, 1]` against the first (or peak) sample.
pub fn normalize_curve(samples: &[f64]) -> Vec<f64> {
    if samples.is_empty() {
        return Vec::new();
    }
    let base = if samples[0] > 0.0 {
        samples[0]
    } else {
        let max = samples.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        // Mirror `Math.max(...) || 1`: a falsy (zero) max falls back to 1.
        if max != 0.0 {
            max
        } else {
            1.0
        }
    };
    samples.iter().map(|&s| round6(clamp01(s / base))).collect()
}

/// Map an average retention into a [`ReachTier`].
pub fn reach_tier(avg_retention: f64) -> ReachTier {
    let r = clamp01(avg_retention);
    if r >= 0.85 {
        ReachTier {
            tier: Tier::Viral,
            multiplier: 3.0,
        }
    } else if r >= 0.7 {
        ReachTier {
            tier: Tier::Boosted,
            multiplier: 2.2,
        }
    } else {
        ReachTier {
            tier: Tier::Minimal,
            multiplier: 1.0,
        }
    }
}

/// Drop-off summary for a normalized retention curve.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct Dropoff {
    pub max_drop: f64,
    pub max_drop_at: usize,
    pub first_3s: f64,
}

/// Largest single-step drop, where it occurs, and the first-3-samples average.
pub fn dropoff(curve: &[f64]) -> Dropoff {
    let mut max_drop = 0.0;
    let mut at = 0;
    for i in 1..curve.len() {
        let drop = curve[i - 1] - curve[i];
        if drop > max_drop {
            max_drop = drop;
            at = i;
        }
    }
    let head_len = curve.len().min(3);
    let first_3s = if head_len > 0 {
        let sum: f64 = curve[..head_len].iter().sum();
        round6(sum / head_len as f64)
    } else {
        0.0
    };
    Dropoff {
        max_drop: round6(max_drop),
        max_drop_at: at,
        first_3s,
    }
}

// ---------------------------------------------------------------------------
// Retention-weighted A/B winner selection (mirror of `ab.ts`).
// ---------------------------------------------------------------------------

/// One A/B variant; missing metrics are treated as `0`.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Variant {
    pub id: String,
    #[serde(default)]
    pub completion: Option<f64>,
    #[serde(default)]
    pub avg_watch: Option<f64>,
}

/// Winner id (if any) plus each variant's score, keyed by id.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct WinnerResult {
    pub winner: Option<String>,
    pub scores: BTreeMap<String, f64>,
}

/// Pick the winner as `0.6 * completion + 0.4 * watch_norm`, first-max-wins.
pub fn select_winner(variants: &[Variant]) -> WinnerResult {
    if variants.is_empty() {
        return WinnerResult {
            winner: None,
            scores: BTreeMap::new(),
        };
    }
    let max_watch = variants
        .iter()
        .map(|v| v.avg_watch.unwrap_or(0.0))
        .fold(0.0, f64::max);
    let denom = if max_watch > 0.0 { max_watch } else { 1.0 };
    let mut scores = BTreeMap::new();
    let mut best_id: Option<String> = None;
    let mut best_score = -1.0;
    for v in variants {
        let completion = clamp01(v.completion.unwrap_or(0.0));
        let watch_norm = clamp01(v.avg_watch.unwrap_or(0.0) / denom);
        let s = round6(0.6 * completion + 0.4 * watch_norm);
        scores.insert(v.id.clone(), s);
        if s > best_score {
            best_score = s;
            best_id = Some(v.id.clone());
        }
    }
    WinnerResult {
        winner: best_id,
        scores,
    }
}

// ---------------------------------------------------------------------------
// Tests — ported from `test/fixtures/golden/analytics.json`.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn sig(m: f64, c: f64, t: f64, a: f64) -> HookSignals {
        HookSignals {
            motion: Some(m),
            contrast: Some(c),
            text: Some(t),
            audio_onset: Some(a),
        }
    }

    #[test]
    fn round6_half_away_from_zero() {
        assert_eq!(round6(0.5666666666666667), 0.566667);
        assert_eq!(round6(-0.5666666666666667), -0.566667);
        assert_eq!(round6(0.815), 0.815);
    }

    #[test]
    fn clamp01_bounds() {
        assert_eq!(clamp01(-0.5), 0.0);
        assert_eq!(clamp01(1.5), 1.0);
        assert_eq!(clamp01(0.42), 0.42);
    }

    #[test]
    fn hook_strong() {
        let r = hook_score(&sig(0.9, 0.8, 0.7, 0.8));
        assert_eq!(r.score, 0.815);
        assert!(r.passes);
    }

    #[test]
    fn hook_borderline() {
        let r = hook_score(&sig(0.7, 0.7, 0.7, 0.7));
        assert_eq!(r.score, 0.7);
        assert!(r.passes);
    }

    #[test]
    fn hook_weak() {
        let r = hook_score(&sig(0.3, 0.2, 0.1, 0.2));
        assert_eq!(r.score, 0.215);
        assert!(!r.passes);
    }

    #[test]
    fn hook_missing_signals_default_zero() {
        let r = hook_score(&HookSignals::default());
        assert_eq!(r.score, 0.0);
        assert!(!r.passes);
    }

    #[test]
    fn retention_flat() {
        assert_eq!(
            normalize_curve(&[200.0, 200.0, 200.0, 200.0]),
            vec![1.0, 1.0, 1.0, 1.0]
        );
    }

    #[test]
    fn retention_decaying() {
        assert_eq!(
            normalize_curve(&[1000.0, 820.0, 610.0, 540.0, 410.0, 300.0]),
            vec![1.0, 0.82, 0.61, 0.54, 0.41, 0.3]
        );
    }

    #[test]
    fn retention_cliff() {
        assert_eq!(
            normalize_curve(&[500.0, 480.0, 120.0, 90.0, 70.0]),
            vec![1.0, 0.96, 0.24, 0.18, 0.14]
        );
    }

    #[test]
    fn retention_empty() {
        assert_eq!(normalize_curve(&[]), Vec::<f64>::new());
    }

    #[test]
    fn reach_tiers() {
        assert_eq!(reach_tier(0.9).tier, Tier::Viral);
        assert_eq!(reach_tier(0.85).tier, Tier::Viral);
        assert_eq!(reach_tier(0.85).multiplier, 3.0);
        assert_eq!(reach_tier(0.78).tier, Tier::Boosted);
        assert_eq!(reach_tier(0.7).tier, Tier::Boosted);
        assert_eq!(reach_tier(0.7).multiplier, 2.2);
        assert_eq!(reach_tier(0.5).tier, Tier::Minimal);
        assert_eq!(reach_tier(0.5).multiplier, 1.0);
    }

    #[test]
    fn dropoff_cliff() {
        let d = dropoff(&[1.0, 0.96, 0.24, 0.18, 0.14]);
        assert_eq!(d.max_drop, 0.72);
        assert_eq!(d.max_drop_at, 2);
        assert_eq!(d.first_3s, 0.733333);
    }

    #[test]
    fn dropoff_decaying() {
        let d = dropoff(&[1.0, 0.82, 0.61, 0.54, 0.41, 0.3]);
        assert_eq!(d.max_drop, 0.21);
        assert_eq!(d.max_drop_at, 2);
        assert_eq!(d.first_3s, 0.81);
    }

    #[test]
    fn dropoff_flat() {
        let d = dropoff(&[1.0, 1.0, 1.0, 1.0]);
        assert_eq!(d.max_drop, 0.0);
        assert_eq!(d.max_drop_at, 0);
        assert_eq!(d.first_3s, 1.0);
    }

    #[test]
    fn ab_three_way() {
        let variants = vec![
            Variant {
                id: "A".into(),
                completion: Some(0.5),
                avg_watch: Some(12.0),
            },
            Variant {
                id: "B".into(),
                completion: Some(0.42),
                avg_watch: Some(18.0),
            },
            Variant {
                id: "C".into(),
                completion: Some(0.6),
                avg_watch: Some(9.0),
            },
        ];
        let r = select_winner(&variants);
        assert_eq!(r.winner.as_deref(), Some("B"));
        assert_eq!(r.scores["A"], 0.566667);
        assert_eq!(r.scores["B"], 0.652);
        assert_eq!(r.scores["C"], 0.56);
    }

    #[test]
    fn ab_empty() {
        let r = select_winner(&[]);
        assert_eq!(r.winner, None);
        assert!(r.scores.is_empty());
    }

    #[test]
    fn winner_result_serializes() {
        let r = select_winner(&[Variant {
            id: "A".into(),
            completion: Some(1.0),
            avg_watch: Some(10.0),
        }]);
        let json = serde_json::to_string(&r).unwrap();
        assert_eq!(json, r#"{"winner":"A","scores":{"A":1.0}}"#);
    }
}
