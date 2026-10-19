//! Composite creator insights (`rf-insights`). Combines the pure golden-parity
//! analytics crates into product-level decisions the desktop can act on:
//!
//! * [`reel_insight`] fuses the first-3s **hook gate** + **retention/reach**
//!   (`rf-growth`) into a post / improve / rework verdict for a finished reel;
//! * [`sound_insight`] fuses **trend momentum** + the **ad-safe** rule
//!   (`rf-trends`) into a use-now / caution / skip recommendation for a sound.
//!
//! Pure + deterministic — every number comes from the underlying golden-parity
//! crates (so it matches the cloud), and only the *thresholds* that turn those
//! numbers into a verdict live here.

use rf_growth::{dropoff, hook_score, normalize_curve, reach_tier, round6, HookSignals, Tier};
use rf_trends::{ad_safe, score as trend_score, SoundFlags};

/// What to do with a finished reel.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    /// Strong hook + boosted/viral reach — ship it.
    Post,
    /// One of hook or retention is good; tighten the other before posting.
    Improve,
    /// Weak on both — rework the concept.
    Rework,
}

/// The fused reel analysis.
#[derive(Debug, Clone, PartialEq)]
pub struct ReelInsight {
    pub hook_score: f64,
    pub hook_passes: bool,
    pub reach_tier: Tier,
    pub reach_multiplier: f64,
    pub avg_retention: f64,
    pub biggest_drop: f64,
    pub biggest_drop_at: usize,
    pub verdict: Verdict,
}

/// Fuse the hook gate and the retention/reach tier into a single verdict.
/// `retention_samples` are raw per-second viewer counts (normalized internally).
pub fn reel_insight(signals: &HookSignals, retention_samples: &[f64]) -> ReelInsight {
    let hook = hook_score(signals);
    let curve = normalize_curve(retention_samples);
    let avg = if curve.is_empty() {
        0.0
    } else {
        round6(curve.iter().sum::<f64>() / curve.len() as f64)
    };
    let tier = reach_tier(avg);
    let drop = dropoff(&curve);

    let boosted = matches!(tier.tier, Tier::Viral | Tier::Boosted);
    let verdict = if hook.passes && boosted {
        Verdict::Post
    } else if hook.passes || avg >= 0.5 {
        Verdict::Improve
    } else {
        Verdict::Rework
    };

    ReelInsight {
        hook_score: hook.score,
        hook_passes: hook.passes,
        reach_tier: tier.tier,
        reach_multiplier: tier.multiplier,
        avg_retention: avg,
        biggest_drop: drop.max_drop,
        biggest_drop_at: drop.max_drop_at,
        verdict,
    }
}

/// What to do with a candidate sound.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SoundReco {
    /// Rising, not saturated, and ad-safe — build to it now.
    UseNow,
    /// Ad-safe but late/plateauing — usable but the window is closing.
    UseWithCaution,
    /// Not cross-platform ad-safe (unlicensed or explicit) — skip.
    Skip,
}

/// The fused sound analysis.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SoundInsight {
    pub opportunity: f64,
    pub saturation: f64,
    pub velocity: f64,
    pub ad_safe: bool,
    pub recommendation: SoundReco,
}

/// Fuse trend momentum with the ad-safe rule into a recommendation.
/// `usage_series` is the sound's daily-usage counts.
pub fn sound_insight(usage_series: &[f64], flags: &SoundFlags) -> SoundInsight {
    let s = trend_score(usage_series);
    let safe = ad_safe(flags);
    // `opportunity` is already the composite momentum-vs-headroom score from
    // rf-trends (0.5·rising + 0.4·(1−saturation) + 0.1·(1−decay)); gate on it
    // directly rather than re-deriving a saturation sub-rule.
    let recommendation = if !safe {
        SoundReco::Skip
    } else if s.opportunity >= 0.55 {
        SoundReco::UseNow
    } else {
        SoundReco::UseWithCaution
    };
    SoundInsight {
        opportunity: s.opportunity,
        saturation: s.saturation,
        velocity: s.velocity,
        ad_safe: safe,
        recommendation,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn signals(m: f64, c: f64, t: f64, a: f64) -> HookSignals {
        HookSignals {
            motion: Some(m),
            contrast: Some(c),
            text: Some(t),
            audio_onset: Some(a),
        }
    }

    #[test]
    fn strong_hook_and_high_retention_says_post() {
        // Clears the 0.7 hook gate and holds ~viral retention.
        let insight = reel_insight(
            &signals(0.95, 0.9, 0.85, 0.9),
            &[1000.0, 980.0, 965.0, 955.0, 950.0, 948.0, 946.0],
        );
        assert!(insight.hook_passes);
        assert!(matches!(insight.reach_tier, Tier::Viral | Tier::Boosted));
        assert_eq!(insight.verdict, Verdict::Post);
    }

    #[test]
    fn weak_hook_and_steep_dropoff_says_rework() {
        let insight = reel_insight(
            &signals(0.1, 0.1, 0.0, 0.1),
            &[1000.0, 300.0, 120.0, 90.0, 80.0, 75.0, 70.0],
        );
        assert!(!insight.hook_passes);
        assert!(insight.avg_retention < 0.5);
        assert_eq!(insight.verdict, Verdict::Rework);
        // The biggest single-second cliff is right after the hook.
        assert_eq!(insight.biggest_drop_at, 1);
    }

    #[test]
    fn good_hook_but_mediocre_retention_says_improve() {
        let insight = reel_insight(
            &signals(0.95, 0.9, 0.85, 0.9),
            &[1000.0, 700.0, 520.0, 430.0, 400.0, 395.0, 390.0],
        );
        assert!(insight.hook_passes);
        assert_eq!(insight.verdict, Verdict::Improve);
    }

    #[test]
    fn empty_retention_is_safe() {
        let insight = reel_insight(&signals(0.9, 0.9, 0.9, 0.9), &[]);
        assert_eq!(insight.avg_retention, 0.0);
        assert_eq!(insight.reach_tier, Tier::Minimal);
    }

    #[test]
    fn rising_licensed_clean_sound_says_use_now() {
        let flags = SoundFlags {
            licensed: Some(true),
            explicit: Some(false),
        };
        let insight = sound_insight(&[10.0, 18.0, 30.0, 55.0, 95.0, 160.0, 250.0], &flags);
        assert!(insight.ad_safe);
        assert_eq!(insight.recommendation, SoundReco::UseNow);
    }

    #[test]
    fn explicit_sound_is_skipped_regardless_of_momentum() {
        let flags = SoundFlags {
            licensed: Some(true),
            explicit: Some(true),
        };
        let insight = sound_insight(&[10.0, 18.0, 30.0, 55.0, 95.0, 160.0, 250.0], &flags);
        assert!(!insight.ad_safe);
        assert_eq!(insight.recommendation, SoundReco::Skip);
    }

    #[test]
    fn saturated_sound_gets_caution() {
        let flags = SoundFlags {
            licensed: Some(true),
            explicit: Some(false),
        };
        // Flat-at-peak series: low opportunity / high saturation.
        let insight = sound_insight(&[900.0, 905.0, 903.0, 906.0, 905.0, 904.0, 905.0], &flags);
        assert!(insight.ad_safe);
        assert_eq!(insight.recommendation, SoundReco::UseWithCaution);
    }
}
