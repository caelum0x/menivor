//! FFmpeg-expression bridge — Rust port of `reelforge_effects_core/ffexpr.py`
//! (and `packages/effects-core/src/ffexpr.ts`).
//!
//! [`crate`]'s numeric kernels return transform/filter params at a normalized
//! time `t` (the live preview). This module renders the **same** kernels as
//! FFmpeg filter-expression **strings** (in a caller-supplied normalized-time
//! sub-expression `tn`) so the desktop encode (`rf-encode`) can splice them into
//! a `scale=...:eval=frame` / `crop` / `rotate` chain and land the exact value
//! the preview showed — frame-accurate parity with the cloud render path.
//!
//! Because the kernels are pure polynomial / exact-integer math (all
//! intermediates `< 2**53`), FFmpeg's `double` evaluation of these strings is
//! bit-identical to the numeric kernels. Only the whitelisted FFmpeg ops are
//! used (`+ - * /`, `clip`, `if`, `lt`, `floor`) so the output stays portable.

/// Knuth multiplicative hash — must match [`crate::noise1`] / `keyframe.ts`.
const HASH: i64 = 2_654_435_761;
const MOD: i64 = 4_294_967_296; // 2**32

/// Kernel defaults (mirror [`crate`]'s numeric kernels), exposed so callers that
/// render the bare kernel ids (no per-segment params) reproduce the preview.
pub const PUSH_IN_INTENSITY: f64 = 0.3;
pub const KEN_BURNS_ZOOM: f64 = 0.2;
pub const KEN_BURNS_PAN_X: f64 = 0.1;
pub const KEN_BURNS_PAN_Y: f64 = 0.05;
pub const HANDHELD_INTENSITY: f64 = 0.02;
pub const HANDHELD_SEED: i64 = 1;

/// Render a float as a compact literal with `sig` significant digits, trailing
/// zeros trimmed — mirrors Python `f"{n:.9g}"` / JS `Number(n.toPrecision(9))`
/// for the small positive magnitudes these kernels use.
pub fn fmt_g(n: f64, sig: usize) -> String {
    if n == 0.0 || !n.is_finite() {
        return "0".to_string();
    }
    let exp = n.abs().log10().floor() as i32;
    let decimals = (sig as i32 - 1 - exp).max(0) as usize;
    let rounded: f64 = format!("{n:.decimals$}").parse().unwrap_or(n);
    // Rust's default float formatting is the shortest round-trip representation,
    // so trailing zeros are already dropped (0.300000000 -> "0.3").
    format!("{rounded}")
}

fn g9(n: f64) -> String {
    fmt_g(n, 9)
}

// --- easing primitives -> FFmpeg expression strings (mirror easing) -------- //

/// Clamp a normalized-time sub-expression to `[0, 1]` (matches `clamp01`).
pub fn clamp01_expr(tn: &str) -> String {
    format!("(clip(({tn}),0,1))")
}

/// Linear ramp — clamped identity (matches `linear`).
pub fn linear_expr(tn: &str) -> String {
    clamp01_expr(tn)
}

/// Quadratic ease-in-out on `[0, 1]` (matches `ease_in_out`).
pub fn ease_in_out_expr(tn: &str) -> String {
    let t = clamp01_expr(tn);
    format!("(if(lt({t},0.5),2*{t}*{t},1-2*(1-{t})*(1-{t})))")
}

/// Parabola peaking at `t = 0.5` (matches `peak`).
pub fn peak_expr(tn: &str) -> String {
    let t = clamp01_expr(tn);
    format!("(4*{t}*(1-{t}))")
}

/// Deterministic pseudo-noise in `[-1, 1]` (matches [`crate::noise1`]). The
/// modulo is written with `floor` (not FFmpeg `mod`) so it matches the numeric
/// kernel's `%` exactly for the positive operands used here.
pub fn noise1_expr(n_expr: &str, seed: i64) -> String {
    let m = format!("((({n_expr})+({seed}))*{HASH})");
    let h = format!("({m}-floor({m}/{MOD})*{MOD})");
    format!("({h}/{MOD}*2-1)")
}

/// FFmpeg has no `round()`; `floor(x+0.5)` matches `Math.round(t*1000)`.
fn round_expr(x: &str) -> String {
    format!("floor(({x})*1000+0.5)")
}

// --- camera kernels -> FFmpeg expression strings (mirror kernels) ---------- //

/// Push-in zoom factor expression — mirrors [`crate::push_in`].
pub fn push_in_zoom_expr(tn: &str, intensity: f64) -> String {
    format!("(1+{}*{})", g9(intensity), ease_in_out_expr(tn))
}

/// Ken-Burns `(zoom, x, y)` expressions — mirrors [`crate::ken_burns`].
pub struct KenBurnsExpr {
    pub zoom: String,
    pub x: String,
    pub y: String,
}

/// Build the Ken-Burns zoom + normalized pan expressions.
pub fn ken_burns_expr(tn: &str, zoom: f64, pan_x: f64, pan_y: f64) -> KenBurnsExpr {
    let lin = linear_expr(tn);
    KenBurnsExpr {
        zoom: format!("(1+{}*{lin})", g9(zoom)),
        x: format!("({}*{lin})", g9(pan_x)),
        y: format!("({}*{lin})", g9(pan_y)),
    }
}

/// Handheld `(dx, dy, rot)` expressions — mirrors [`crate::handheld`].
pub struct HandheldExpr {
    pub dx: String,
    pub dy: String,
    pub rot: String,
}

/// Build the handheld micro-shake `(dx, dy, rot)` noise expressions.
pub fn handheld_expr(tn: &str, intensity: f64, seed: i64) -> HandheldExpr {
    let n = round_expr(&clamp01_expr(tn));
    HandheldExpr {
        dx: format!("({}*{})", g9(intensity), noise1_expr(&n, seed)),
        dy: format!("({}*{})", g9(intensity), noise1_expr(&n, seed + 7)),
        rot: format!("({}*{})", g9(intensity * 0.5), noise1_expr(&n, seed + 13)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn g_formats_like_python_9g() {
        assert_eq!(g9(0.3), "0.3");
        assert_eq!(g9(0.05), "0.05");
        assert_eq!(g9(0.02 * 0.5), "0.01");
        assert_eq!(g9(0.0), "0");
    }

    #[test]
    fn push_in_expr_embeds_ease() {
        let e = push_in_zoom_expr("(t/2)", PUSH_IN_INTENSITY);
        assert!(e.starts_with("(1+0.3*"));
        assert!(e.contains("if(lt"));
    }

    #[test]
    fn handheld_expr_uses_three_seeds() {
        let hh = handheld_expr("(t/2)", HANDHELD_INTENSITY, HANDHELD_SEED);
        assert!(hh.dx.contains("+(1)"));
        assert!(hh.dy.contains("+(8)"));
        assert!(hh.rot.contains("+(14)"));
    }
}
