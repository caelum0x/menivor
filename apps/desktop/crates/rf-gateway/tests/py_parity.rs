//! PYTHON-BEHAVIORAL-PARITY tests for `rf-gateway`.
//!
//! These integration tests pin the Rust crate's public API to the documented
//! behavior of the Python module it mirrors:
//! `apps/api/app/domains/gateway/media_gateway.py` (+ `media_catalog.py`), as
//! exercised by `tests/reelforge/test_media_gateway.py`.
//!
//! Focus (per the parity brief):
//!   * integer-micro cost charge — image/audio **flat per-generation**, video
//!     **per-second × duration clamped to `[1, max_seconds]`**;
//!   * wallet reserve/settle coverage via `wallet_preflight` (Ok / Insufficient).
//!
//! Python spec pinned:
//!   * `create_video`: `seconds = max(1, min(int(duration), m.max_seconds or
//!     int(duration)))` then `cost = seconds * m.price_micros`.
//!   * `create_image`: `cost = m.price_micros` (flat, duration-independent).
//!   * `create_audio`: `cost = m.price_micros` (flat per-generation).
//!   * `WalletService.reserve`: holds `amount`; raises `WalletError(402, ...)`
//!     only when `available < amount` — i.e. `available >= amount` succeeds
//!     (equal is Ok). `wallet_preflight` mirrors that Ok/Insufficient decision
//!     plus the residual/shortfall math.
//!   * `_settle`: charges `min(actual, held)`; for media jobs the gateway sets
//!     `actual_cost_micros == held_cost_micros`, so the settled amount equals
//!     the reserved estimate (identity pinned below).
//!
//! Uses ONLY the crate's public API. Real catalog prices/caps are used as inputs
//! so the asserted micro amounts match what the Python gateway reserves/settles
//! (e.g. the 420_000 reservation asserted in `test_media_gateway.py`).

use rf_gateway::{clamp_seconds, wallet_preflight, MediaModel, Modality, Preflight};

/// `kwaivgi/kling-v1.6` — VIDEO, 84_000 micros/sec, max 10s (real catalog row).
fn kling_v16() -> MediaModel {
    MediaModel {
        id: "kwaivgi/kling-v1.6".into(),
        modality: Modality::Video,
        provider: "kling-fal".into(),
        price_micros: 84_000,
        unit: "second".into(),
        max_seconds: 10,
        description: String::new(),
    }
}

/// `minimax/hailuo-02-fal` — VIDEO, 260_000 micros/sec, max 6s (real catalog row).
fn hailuo_02_fal() -> MediaModel {
    MediaModel {
        id: "minimax/hailuo-02-fal".into(),
        modality: Modality::Video,
        provider: "kling-fal".into(),
        price_micros: 260_000,
        unit: "second".into(),
        max_seconds: 6,
        description: String::new(),
    }
}

/// `openai/gpt-image-1` — IMAGE, flat 40_000 micros (real catalog row).
fn gpt_image_1() -> MediaModel {
    MediaModel {
        id: "openai/gpt-image-1".into(),
        modality: Modality::Image,
        provider: "openai-image".into(),
        price_micros: 40_000,
        unit: "image".into(),
        max_seconds: 0,
        description: String::new(),
    }
}

/// `suno/v4` — AUDIO, flat 80_000 micros/clip (real catalog row).
fn suno_v4() -> MediaModel {
    MediaModel {
        id: "suno/v4".into(),
        modality: Modality::Audio,
        provider: "suno".into(),
        price_micros: 80_000,
        unit: "clip".into(),
        max_seconds: 0,
        description: String::new(),
    }
}

// ---- Python reference re-implementations (the spec we pin against) ---------- //

/// Mirror of `create_video`'s `seconds = max(1, min(int(duration), m.max_seconds or int(duration)))`.
/// `max_seconds == 0` is falsy in Python, so the cap collapses to `duration`
/// (uncapped, floor 1) — exactly what `clamp_seconds` does with `max_seconds == 0`.
fn py_video_seconds(duration: u32, max_seconds: u32) -> u32 {
    let cap = if max_seconds != 0 {
        max_seconds
    } else {
        duration
    };
    1u32.max(duration.min(cap))
}

/// Mirror of the gateway charge: video = seconds*price, image/audio = flat price.
fn py_cost_micros(m: &MediaModel, duration: u32) -> u64 {
    match m.modality {
        Modality::Video => py_video_seconds(duration, m.max_seconds) as u64 * m.price_micros,
        Modality::Image | Modality::Audio => m.price_micros,
    }
}

// --------------------------------------------------------------------------- //
// Video — per-second × duration clamped to [1, max_seconds]
// --------------------------------------------------------------------------- //

#[test]
fn video_cost_matches_python_nominal() {
    let m = kling_v16();
    // test_media_gateway.py reserves 5s * $0.084 = 420_000 micros for kling-v1.6.
    assert_eq!(m.estimate_cost_micros(5), 420_000);
    assert_eq!(m.estimate_cost_micros(5), py_cost_micros(&m, 5));
}

#[test]
fn video_cost_clamps_to_max_seconds() {
    let m = kling_v16(); // max 10s
    for duration in [10u32, 11, 20, 999] {
        // Python: min(duration, max_seconds) once past the cap => 10 * price.
        assert_eq!(m.estimate_cost_micros(duration), 10 * 84_000);
        assert_eq!(
            m.estimate_cost_micros(duration),
            py_cost_micros(&m, duration)
        );
    }
    // A different cap (hailuo max 6s) clamps independently.
    let h = hailuo_02_fal();
    assert_eq!(h.estimate_cost_micros(10), 6 * 260_000);
    assert_eq!(h.estimate_cost_micros(10), py_cost_micros(&h, 10));
}

#[test]
fn video_cost_floors_to_one_second() {
    let m = kling_v16();
    // Python max(1, ...) => a 0-second request still costs a single second.
    assert_eq!(m.estimate_cost_micros(0), 84_000);
    assert_eq!(m.estimate_cost_micros(0), py_cost_micros(&m, 0));
    assert_eq!(m.estimate_cost_micros(1), 84_000);
}

#[test]
fn video_seconds_uncapped_when_max_is_zero() {
    // Python `m.max_seconds or int(duration)`: max_seconds == 0 (falsy) => cap
    // becomes the duration itself, so only the floor-of-1 applies. clamp_seconds
    // must reproduce that exact branch.
    for duration in [0u32, 1, 7, 42, 1000] {
        assert_eq!(
            clamp_seconds(duration, 0),
            py_video_seconds(duration, 0),
            "clamp_seconds diverged from Python for uncapped duration {duration}"
        );
    }
}

#[test]
fn clamp_seconds_matches_python_across_grid() {
    // Exhaustively pin clamp_seconds to the Python seconds formula.
    for max_seconds in [0u32, 1, 6, 8, 10] {
        for duration in 0u32..=25 {
            assert_eq!(
                clamp_seconds(duration, max_seconds),
                py_video_seconds(duration, max_seconds),
                "divergence at duration={duration}, max_seconds={max_seconds}"
            );
        }
    }
}

#[test]
fn video_cost_matches_python_across_grid() {
    for m in [kling_v16(), hailuo_02_fal()] {
        for duration in 0u32..=25 {
            assert_eq!(
                m.estimate_cost_micros(duration),
                py_cost_micros(&m, duration),
                "cost divergence for {} at duration={duration}",
                m.id
            );
        }
    }
}

// --------------------------------------------------------------------------- //
// Image + audio — flat per-generation (duration-independent)
// --------------------------------------------------------------------------- //

#[test]
fn image_cost_is_flat_per_generation() {
    let m = gpt_image_1();
    // Python create_image: cost = m.price_micros, independent of any duration.
    for duration in [0u32, 1, 5, 999] {
        assert_eq!(m.estimate_cost_micros(duration), 40_000);
        assert_eq!(
            m.estimate_cost_micros(duration),
            py_cost_micros(&m, duration)
        );
    }
}

#[test]
fn audio_cost_is_flat_per_generation() {
    let m = suno_v4();
    // test_media_gateway.py reserves the flat clip price (80_000) for suno/v4,
    // regardless of any duration hint.
    for duration in [0u32, 6, 240, 100_000] {
        assert_eq!(m.estimate_cost_micros(duration), 80_000);
        assert_eq!(
            m.estimate_cost_micros(duration),
            py_cost_micros(&m, duration)
        );
    }
}

// --------------------------------------------------------------------------- //
// Wallet reserve/settle — wallet_preflight Ok / Insufficient
// --------------------------------------------------------------------------- //

#[test]
fn preflight_ok_covers_reservation_and_reports_residual() {
    // test_media_gateway.py: 100_000_000 balance, reserve 420_000 for a kling
    // video => available_micros afterward is 100_000_000 - 420_000 = 99_580_000.
    let estimate = kling_v16().estimate_cost_micros(5); // 420_000
    assert_eq!(
        wallet_preflight(estimate, 100_000_000),
        Preflight::Ok {
            remaining_micros: 99_580_000
        }
    );
}

#[test]
fn preflight_boundary_equal_is_ok() {
    // Python WalletService.reserve only raises InsufficientFundsError when
    // available < amount, so available == amount reserves successfully (Ok, 0 left).
    let estimate = suno_v4().estimate_cost_micros(0); // 80_000
    assert_eq!(
        wallet_preflight(estimate, estimate),
        Preflight::Ok {
            remaining_micros: 0
        }
    );
}

#[test]
fn preflight_insufficient_reports_shortfall() {
    // A 420_000 video estimate against a 100_000-micro balance is short by 320_000
    // => Python reserve raises WalletError(402, "insufficient wallet balance...").
    let estimate = kling_v16().estimate_cost_micros(5); // 420_000
    assert_eq!(
        wallet_preflight(estimate, 100_000),
        Preflight::Insufficient {
            shortfall_micros: 320_000
        }
    );
}

#[test]
fn preflight_one_micro_short_is_insufficient() {
    // Strict inequality: one micro under the estimate is still Insufficient(1).
    let estimate = 40_000u64; // gpt-image-1 flat price
    assert_eq!(
        wallet_preflight(estimate, estimate - 1),
        Preflight::Insufficient {
            shortfall_micros: 1
        }
    );
}

#[test]
fn settled_amount_equals_reserved_estimate_for_media_jobs() {
    // Python: `_settle` charges min(actual, held); the gateway sets
    // `actual_cost_micros = held_cost_micros`, so a completed media job settles
    // exactly the reserved estimate (identity the success-only billing relies on).
    // We pin the identity through the residual reported by the Ok preflight.
    let held = kling_v16().estimate_cost_micros(5); // reserved == 420_000
    let actual = held; // gateway sets actual == held
    let settled = actual.min(held);
    assert_eq!(settled, held);
    // Post-settle balance == pre-reserve balance minus the settled charge.
    let pre = 100_000_000u64;
    assert_eq!(pre - settled, 99_580_000);
    // And the preflight's Ok residual equals that post-settle available balance.
    assert_eq!(
        wallet_preflight(held, pre),
        Preflight::Ok {
            remaining_micros: pre - settled
        }
    );
}
