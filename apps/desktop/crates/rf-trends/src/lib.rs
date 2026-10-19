//! Pure trend scoring — Rust port of `@reelforge/trends-schema` (`scoring.ts`,
//! itself a mirror of `scoring.py`). Reproduces the same IEEE-754 op sequence +
//! shared [`round6`] so scores are bit-identical to the TS/Python ports against
//! the golden fixtures (saturation / velocity / decay / opportunity + adSafe).

use serde::{Deserialize, Serialize};

/// Clamp `x` into the inclusive range `[0, 1]`.
///
/// Kept as explicit branches (rather than `f64::clamp`) to mirror the TS
/// `x < 0 ? 0 : x > 1 ? 1 : x` source exactly.
#[allow(clippy::manual_clamp)]
pub fn clamp01(x: f64) -> f64 {
    if x < 0.0 {
        0.0
    } else if x > 1.0 {
        1.0
    } else {
        x
    }
}

/// Deterministic 6-decimal round (half away from zero) — identical in JS/Python.
pub fn round6(x: f64) -> f64 {
    let bias = if x >= 0.0 { 0.5 } else { -0.5 };
    (x * 1_000_000.0 + bias).trunc() / 1_000_000.0
}

/// Full trend score for a popularity series.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct TrendScore {
    pub saturation: f64,
    pub velocity: f64,
    pub decay: f64,
    pub opportunity: f64,
}

/// Maximum of a series (`Math.max(...series)` semantics; caller guards empty).
fn peak_of(series: &[f64]) -> f64 {
    series.iter().copied().fold(f64::NEG_INFINITY, f64::max)
}

/// How close the latest value is to the series peak, in `[0, 1]`.
pub fn saturation(series: &[f64]) -> f64 {
    if series.is_empty() {
        return 0.0;
    }
    let peak = peak_of(series);
    if peak <= 0.0 {
        return 0.0;
    }
    round6(series[series.len() - 1] / peak)
}

/// Recent rate of change over the last `window` samples, peak-normalized.
///
/// The TS source `truncates` the `window` argument; here it is already an `i64`.
pub fn velocity_with_window(series: &[f64], window: i64) -> f64 {
    let n = series.len();
    if n < 2 {
        return 0.0;
    }
    let k = window.min(n as i64 - 1);
    let peak = peak_of(series);
    let denom = if peak > 0.0 { peak } else { 1.0 };
    let change = series[n - 1] - series[n - 1 - k as usize];
    round6(change / (k as f64 * denom))
}

/// Velocity with the default `window` of 3 (matches the TS default argument).
pub fn velocity(series: &[f64]) -> f64 {
    velocity_with_window(series, 3)
}

/// Decline from the peak once the trend is past its peak, in `[0, 1]`.
pub fn decay(series: &[f64]) -> f64 {
    if series.is_empty() {
        return 0.0;
    }
    let peak = peak_of(series);
    if peak <= 0.0 {
        return 0.0;
    }
    let last = series[series.len() - 1];
    let peak_idx = series.iter().position(|&v| v == peak).unwrap_or(0);
    if peak_idx < series.len() - 1 && last < peak {
        return round6((peak - last) / peak);
    }
    0.0
}

/// Composite "how much upside is left" score in `[0, 1]`.
pub fn opportunity(series: &[f64]) -> f64 {
    let sat = saturation(series);
    let vel = velocity(series);
    let dec = decay(series);
    let rising = clamp01(vel * 10.0);
    round6(clamp01(
        0.5 * rising + 0.4 * (1.0 - sat) + 0.1 * (1.0 - dec),
    ))
}

/// Full trend score for a popularity series.
pub fn score(series: &[f64]) -> TrendScore {
    TrendScore {
        saturation: saturation(series),
        velocity: velocity(series),
        decay: decay(series),
        opportunity: opportunity(series),
    }
}

/// Sound clearance flags used by the ad-safety rule.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct SoundFlags {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub licensed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub explicit: Option<bool>,
}

/// Cross-platform (Meta-compatible) ad-safe rule: licensed + not explicit.
pub fn ad_safe(sound: &SoundFlags) -> bool {
    sound.licensed.unwrap_or(true) && !sound.explicit.unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    // Golden fixtures ported from
    // packages/trends-schema/test/fixtures/golden/scores.json.

    fn assert_score(series: &[f64], sat: f64, vel: f64, dec: f64, opp: f64) {
        let got = score(series);
        assert_eq!(got.saturation, sat, "saturation for {series:?}");
        assert_eq!(got.velocity, vel, "velocity for {series:?}");
        assert_eq!(got.decay, dec, "decay for {series:?}");
        assert_eq!(got.opportunity, opp, "opportunity for {series:?}");
    }

    #[test]
    fn golden_empty() {
        assert_score(&[], 0.0, 0.0, 0.0, 0.5);
    }

    #[test]
    fn golden_single() {
        assert_score(&[7.0], 1.0, 0.0, 0.0, 0.1);
    }

    #[test]
    fn golden_flat() {
        assert_score(&[20.0, 20.0, 20.0, 20.0], 1.0, 0.0, 0.0, 0.1);
    }

    #[test]
    fn golden_explosive() {
        assert_score(
            &[1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0],
            1.0,
            0.291667,
            0.0,
            0.6,
        );
    }

    #[test]
    fn golden_rising() {
        assert_score(&[2.0, 5.0, 9.0, 15.0, 24.0, 40.0], 1.0, 0.258333, 0.0, 0.6);
    }

    #[test]
    fn golden_peaked() {
        assert_score(
            &[10.0, 30.0, 60.0, 58.0, 40.0, 25.0],
            0.416667,
            -0.194444,
            0.583333,
            0.275,
        );
    }

    #[test]
    fn ad_safe_clean() {
        assert!(ad_safe(&SoundFlags {
            licensed: Some(true),
            explicit: Some(false),
        }));
    }

    #[test]
    fn ad_safe_explicit() {
        assert!(!ad_safe(&SoundFlags {
            licensed: Some(true),
            explicit: Some(true),
        }));
    }

    #[test]
    fn ad_safe_unlicensed() {
        assert!(!ad_safe(&SoundFlags {
            licensed: Some(false),
            explicit: Some(false),
        }));
    }

    #[test]
    fn ad_safe_defaults() {
        // licensed defaults to true, explicit defaults to false.
        assert!(ad_safe(&SoundFlags::default()));
    }

    #[test]
    fn round6_half_away_from_zero() {
        assert_eq!(round6(0.2916666666), 0.291667);
        assert_eq!(round6(-0.1944444444), -0.194444);
    }

    #[test]
    fn clamp01_bounds() {
        assert_eq!(clamp01(-1.0), 0.0);
        assert_eq!(clamp01(2.0), 1.0);
        assert_eq!(clamp01(0.5), 0.5);
    }

    #[test]
    fn velocity_explicit_window() {
        // Default overload equals an explicit window of 3.
        let s = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0];
        assert_eq!(velocity_with_window(&s, 3), velocity(&s));
    }
}
