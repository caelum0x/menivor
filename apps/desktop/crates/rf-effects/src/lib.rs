//! `rf-effects` — Rust port of `@reelforge/effects-core` (golden-parity).
//!
//! Camera + VFX preset kernels plus the kernel registry, ported one-for-one
//! from `packages/effects-core/src/` (the TypeScript is the source of truth,
//! itself kept bit-identical with the Python `reelforge_effects_core` port).
//!
//! Everything here is pure polynomial / 32-bit-integer math (no `sin`/`pow`
//! transcendentals) so the preview UI and the render executor apply the exact
//! same numbers. Float outputs are rounded to 9 decimal places with the same
//! `Math.round(v * 1e9) / 1e9` (half toward +infinity) rule the TS/Python
//! ports use, so kernel output is byte-identical across all three languages.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

pub mod ffexpr;

/// Named kernel parameters (mirrors the TS `Record<string, number>`).
pub type Params = HashMap<String, f64>;

/// A kernel's output at a normalized time `t`: transform / filter params.
///
/// Insertion order mirrors the TS object-key order so serialized output is
/// stable and comparable across the ports.
pub type KernelOutput = Vec<(String, f64)>;

/// Signature of a pure kernel: `(t, params) -> output`.
pub type Kernel = fn(f64, &Params) -> KernelOutput;

/// The category a kernel belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum KernelCategory {
    Camera,
    Vfx,
}

// --- primitives (mirror of `keyframe.ts`) --------------------------------- //

/// Clamp to the `[0, 1]` range (matches the TS/Python `t<0?0:t>1?1:t`).
pub fn clamp01(t: f64) -> f64 {
    t.clamp(0.0, 1.0)
}

/// Linear ramp — just `clamp01`.
pub fn linear(t: f64) -> f64 {
    clamp01(t)
}

/// Quadratic ease-in-out on `[0, 1]`.
pub fn ease_in_out(t: f64) -> f64 {
    let t = clamp01(t);
    if t < 0.5 {
        2.0 * t * t
    } else {
        let u = 1.0 - t;
        1.0 - 2.0 * u * u
    }
}

/// Parabola peaking at `1.0` at `t = 0.5`, `0.0` at the ends.
pub fn peak(t: f64) -> f64 {
    let t = clamp01(t);
    4.0 * t * (1.0 - t)
}

const HASH: i64 = 2_654_435_761; // Knuth multiplicative hash constant
const MOD: i64 = 4_294_967_296; // 2**32

/// Deterministic pseudo-noise in `[-1, 1]` from an integer step + seed.
///
/// Pure 32-bit integer arithmetic (values stay `< 2**53`) so it is identical
/// in JS and Python. `n | 0` / `seed | 0` are reproduced by the `as i32` wrap.
pub fn noise1(n: i64, seed: i64) -> f64 {
    let h = (((n as i32 as i64) + (seed as i32 as i64)) * HASH) % MOD;
    (h as f64 / MOD as f64) * 2.0 - 1.0
}

/// Round to 9 dp, matching JS `Math.round(v * 1e9) / 1e9` (half toward +inf).
pub fn round9(v: f64) -> f64 {
    (v * 1e9 + 0.5).floor() / 1e9
}

fn param(params: &Params, key: &str, default: f64) -> f64 {
    params.get(key).copied().unwrap_or(default)
}

fn rounded(pairs: Vec<(&str, f64)>) -> KernelOutput {
    pairs
        .into_iter()
        .map(|(k, v)| (k.to_string(), round9(v)))
        .collect()
}

// --- Camera --------------------------------------------------------------- //

/// Slow push-in zoom: `1.0 -> 1.0 + intensity`, eased.
pub fn push_in(t: f64, params: &Params) -> KernelOutput {
    let intensity = param(params, "intensity", 0.3);
    rounded(vec![("zoom", 1.0 + intensity * ease_in_out(t))])
}

/// Linear pan + zoom over a still.
pub fn ken_burns(t: f64, params: &Params) -> KernelOutput {
    let zoom = param(params, "zoom", 0.2);
    let pan_x = param(params, "pan_x", 0.1);
    let pan_y = param(params, "pan_y", 0.05);
    rounded(vec![
        ("zoom", 1.0 + zoom * linear(t)),
        ("x", pan_x * linear(t)),
        ("y", pan_y * linear(t)),
    ])
}

/// Noise-driven micro-shake (`dx`, `dy`, `rot`).
pub fn handheld(t: f64, params: &Params) -> KernelOutput {
    let intensity = param(params, "intensity", 0.02);
    let seed = param(params, "seed", 1.0) as i64;
    let n = (t * 1000.0 + 0.5).floor() as i64; // Math.round(t * 1000)
    rounded(vec![
        ("dx", intensity * noise1(n, seed)),
        ("dy", intensity * noise1(n, seed + 7)),
        ("rot", intensity * 0.5 * noise1(n, seed + 13)),
    ])
}

// --- VFX ------------------------------------------------------------------ //

/// Chromatic-aberration shift in pixels, peaking mid-clip.
pub fn rgb_split(t: f64, params: &Params) -> KernelOutput {
    let intensity = param(params, "intensity", 4.0);
    rounded(vec![("shift_px", intensity * peak(t))])
}

/// Constant grain + vignette strength.
pub fn film_grain(_t: f64, params: &Params) -> KernelOutput {
    let intensity = param(params, "intensity", 0.15);
    let vignette = param(params, "vignette", 0.3);
    rounded(vec![("grain", intensity), ("vignette", vignette)])
}

/// Impact shake amplitude decaying over the clip (`(1 - t)^decay`).
pub fn shake(t: f64, params: &Params) -> KernelOutput {
    let intensity = param(params, "intensity", 8.0);
    let decay = param(params, "decay", 3.0) as i64;
    let u = 1.0 - clamp01(t);
    let mut amp = intensity;
    for _ in 0..decay {
        amp *= u;
    }
    rounded(vec![("amplitude", amp)])
}

// --- Registry (mirror of `registry.ts`) ----------------------------------- //

struct Entry {
    id: &'static str,
    category: KernelCategory,
    apply: Kernel,
}

const ENTRIES: &[Entry] = &[
    Entry {
        id: "push-in",
        category: KernelCategory::Camera,
        apply: push_in,
    },
    Entry {
        id: "ken-burns",
        category: KernelCategory::Camera,
        apply: ken_burns,
    },
    Entry {
        id: "handheld",
        category: KernelCategory::Camera,
        apply: handheld,
    },
    Entry {
        id: "rgb-split",
        category: KernelCategory::Vfx,
        apply: rgb_split,
    },
    Entry {
        id: "film-grain",
        category: KernelCategory::Vfx,
        apply: film_grain,
    },
    Entry {
        id: "shake",
        category: KernelCategory::Vfx,
        apply: shake,
    },
];

fn find(id: &str) -> Option<&'static Entry> {
    ENTRIES.iter().find(|e| e.id == id)
}

/// Resolve a kernel function by id.
pub fn get_kernel(id: &str) -> Option<Kernel> {
    find(id).map(|e| e.apply)
}

/// The category a kernel id belongs to, if known.
pub fn category_of(id: &str) -> Option<KernelCategory> {
    find(id).map(|e| e.category)
}

/// All kernel ids (optionally filtered by category), sorted ascending.
pub fn list_kernels(category: Option<KernelCategory>) -> Vec<String> {
    let mut ids: Vec<String> = ENTRIES
        .iter()
        .filter(|e| category.is_none_or(|c| e.category == c))
        .map(|e| e.id.to_string())
        .collect();
    ids.sort();
    ids
}

/// Apply a kernel by id. Returns an `Err` for an unknown id (the TS throws).
pub fn apply(id: &str, t: f64, params: &Params) -> Result<KernelOutput, String> {
    match get_kernel(id) {
        Some(fun) => Ok(fun(t, params)),
        None => Err(format!("unknown kernel {id}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn empty() -> Params {
        Params::new()
    }

    fn get(out: &KernelOutput, key: &str) -> f64 {
        out.iter().find(|(k, _)| k == key).unwrap().1
    }

    // --- primitives --------------------------------------------------------
    #[test]
    fn primitives_clamp_and_curves() {
        assert_eq!(clamp01(-1.0), 0.0);
        assert_eq!(clamp01(2.0), 1.0);
        assert_eq!(clamp01(0.4), 0.4);
        assert_eq!(linear(0.25), 0.25);
        assert_eq!(ease_in_out(0.0), 0.0);
        assert_eq!(ease_in_out(0.25), 0.125);
        assert_eq!(ease_in_out(0.5), 0.5);
        assert_eq!(ease_in_out(1.0), 1.0);
        assert_eq!(peak(0.0), 0.0);
        assert_eq!(peak(0.5), 1.0);
        assert_eq!(peak(0.25), 0.75);
    }

    // --- golden fixtures (packages/effects-core/test/fixtures/golden) -------
    // t samples: 0.0, 0.25, 0.5, 0.75, 1.0

    #[test]
    fn golden_push_in() {
        let p = empty();
        let zooms = [1.0, 1.0375, 1.15, 1.2625, 1.3];
        for (i, t) in [0.0, 0.25, 0.5, 0.75, 1.0].iter().enumerate() {
            assert_eq!(get(&apply("push-in", *t, &p).unwrap(), "zoom"), zooms[i]);
        }
    }

    #[test]
    fn golden_ken_burns() {
        let p = empty();
        let expect = [
            (0.0, 1.0, 0.0, 0.0),
            (0.25, 1.05, 0.025, 0.0125),
            (0.5, 1.1, 0.05, 0.025),
            (0.75, 1.15, 0.075, 0.0375),
            (1.0, 1.2, 0.1, 0.05),
        ];
        for (t, zoom, x, y) in expect {
            let out = apply("ken-burns", t, &p).unwrap();
            assert_eq!(get(&out, "zoom"), zoom);
            assert_eq!(get(&out, "x"), x);
            assert_eq!(get(&out, "y"), y);
        }
    }

    #[test]
    fn golden_handheld() {
        let p = empty();
        let expect = [
            (0.0, 0.004721359, 0.017770876, 0.003049516),
            (0.25, -0.014938773, -0.001889257, -0.00678055),
            (0.5, 0.005401095, 0.018450611, 0.003389384),
            (0.75, -0.014259037, -0.001209521, -0.006440682),
            (1.0, 0.00608083, 0.019130347, 0.003729252),
        ];
        for (t, dx, dy, rot) in expect {
            let out = apply("handheld", t, &p).unwrap();
            assert_eq!(get(&out, "dx"), dx);
            assert_eq!(get(&out, "dy"), dy);
            assert_eq!(get(&out, "rot"), rot);
        }
    }

    #[test]
    fn golden_rgb_split() {
        let p = empty();
        let shifts = [0.0, 3.0, 4.0, 3.0, 0.0];
        for (i, t) in [0.0, 0.25, 0.5, 0.75, 1.0].iter().enumerate() {
            assert_eq!(
                get(&apply("rgb-split", *t, &p).unwrap(), "shift_px"),
                shifts[i]
            );
        }
    }

    #[test]
    fn golden_film_grain() {
        let p = empty();
        for t in [0.0, 0.25, 0.5, 0.75, 1.0] {
            let out = apply("film-grain", t, &p).unwrap();
            assert_eq!(get(&out, "grain"), 0.15);
            assert_eq!(get(&out, "vignette"), 0.3);
        }
    }

    #[test]
    fn golden_shake() {
        let p = empty();
        let amps = [8.0, 3.375, 1.0, 0.125, 0.0];
        for (i, t) in [0.0, 0.25, 0.5, 0.75, 1.0].iter().enumerate() {
            assert_eq!(get(&apply("shake", *t, &p).unwrap(), "amplitude"), amps[i]);
        }
    }

    // --- registry ----------------------------------------------------------
    #[test]
    fn registry_categories() {
        assert_eq!(category_of("push-in"), Some(KernelCategory::Camera));
        assert_eq!(category_of("ken-burns"), Some(KernelCategory::Camera));
        assert_eq!(category_of("handheld"), Some(KernelCategory::Camera));
        assert_eq!(category_of("rgb-split"), Some(KernelCategory::Vfx));
        assert_eq!(category_of("film-grain"), Some(KernelCategory::Vfx));
        assert_eq!(category_of("shake"), Some(KernelCategory::Vfx));
        assert_eq!(category_of("nope"), None);
    }

    #[test]
    fn registry_list_kernels_sorted() {
        assert_eq!(
            list_kernels(None),
            vec![
                "film-grain",
                "handheld",
                "ken-burns",
                "push-in",
                "rgb-split",
                "shake",
            ]
        );
        assert_eq!(
            list_kernels(Some(KernelCategory::Camera)),
            vec!["handheld", "ken-burns", "push-in"]
        );
        assert_eq!(
            list_kernels(Some(KernelCategory::Vfx)),
            vec!["film-grain", "rgb-split", "shake"]
        );
    }

    #[test]
    fn apply_unknown_kernel_errors() {
        let p = empty();
        assert_eq!(
            apply("bogus", 0.5, &p),
            Err("unknown kernel bogus".to_string())
        );
    }

    #[test]
    fn params_override_defaults() {
        // push-in with intensity 1.0 at t=0.5 -> 1 + 1.0 * ease_in_out(0.5) = 1.5
        let mut p = empty();
        p.insert("intensity".to_string(), 1.0);
        assert_eq!(get(&apply("push-in", 0.5, &p).unwrap(), "zoom"), 1.5);

        // shake with decay 1 at t=0.5 -> 8 * (1-0.5) = 4.0
        let mut p2 = empty();
        p2.insert("decay".to_string(), 1.0);
        assert_eq!(get(&apply("shake", 0.5, &p2).unwrap(), "amplitude"), 4.0);
    }

    #[test]
    fn category_serde_roundtrip() {
        let json = serde_json::to_string(&KernelCategory::Camera).unwrap();
        assert_eq!(json, "\"camera\"");
        let back: KernelCategory = serde_json::from_str("\"vfx\"").unwrap();
        assert_eq!(back, KernelCategory::Vfx);
    }
}
