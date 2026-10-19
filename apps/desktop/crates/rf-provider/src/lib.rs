//! `rf-provider` — Rust port of `@reelforge/provider-adapter-kit`.
//!
//! The shared adapter contract + metadata: license classes, the
//! deprecation/sunset registry, and the async job envelope grammar. This is a
//! golden-parity port of the TypeScript package (`src/license.ts`,
//! `src/deprecation.ts`, `src/envelope.ts`) which is itself byte-identical to
//! the Python port (`reelforge_provider_adapter`) so the routing engine, SDKs,
//! and burn-preview UIs all agree.
//!
//! Parity notes:
//! - This package is pure registry/metadata logic — there is no FNV hashing,
//!   `round6` truncation, or ASS/filtergraph assembly to mirror here.
//! - ISO dates compare lexicographically = chronologically, so `today` is a
//!   plain `&str` compared with `>=`, exactly like the TS/Python source.
//! - Success-only billing truncates `cost_micros` toward zero (`Math.trunc`)
//!   and zeroes it on failure.

use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// license.ts — license-class registry + paid exclusion rule
// ---------------------------------------------------------------------------

/// License class for a model. Defaults to `Territorial` = gate-before-use.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum LicenseClass {
    CommercialSafe,
    NonCommercial,
    Territorial,
}

/// All known license classes, in declaration order (mirrors `LICENSE_CLASSES`).
pub const LICENSE_CLASSES: [LicenseClass; 3] = [
    LicenseClass::CommercialSafe,
    LicenseClass::NonCommercial,
    LicenseClass::Territorial,
];

/// Model-id → license-class registry (mirrors `LICENSE_REGISTRY`).
pub const LICENSE_REGISTRY: &[(&str, LicenseClass)] = &[
    ("wan/wan-2.2", LicenseClass::CommercialSafe),
    ("lightricks/ltx-video", LicenseClass::CommercialSafe),
    (
        "black-forest-labs/flux-schnell",
        LicenseClass::CommercialSafe,
    ),
    ("genmo/mochi-1", LicenseClass::CommercialSafe),
    ("kwaivgi/kling-v1.6", LicenseClass::CommercialSafe),
    ("black-forest-labs/flux-dev", LicenseClass::NonCommercial),
    ("coqui/xtts-v2", LicenseClass::NonCommercial),
    ("SWivid/f5-tts", LicenseClass::NonCommercial),
    (
        "stabilityai/stable-video-diffusion",
        LicenseClass::NonCommercial,
    ),
    ("tencent/hunyuan-video", LicenseClass::Territorial),
    ("THUDM/cogvideox-5b", LicenseClass::Territorial),
];

/// License class for a model (defaults to `Territorial` = gate-before-use).
pub fn license_class(model_id: &str) -> LicenseClass {
    LICENSE_REGISTRY
        .iter()
        .find(|(id, _)| *id == model_id)
        .map(|(_, cls)| *cls)
        .unwrap_or(LicenseClass::Territorial)
}

/// Only `commercial-safe` models may be used for paid renders.
pub fn can_use_for_paid(model_id: &str) -> bool {
    license_class(model_id) == LicenseClass::CommercialSafe
}

// ---------------------------------------------------------------------------
// deprecation.ts — model lifecycle + sunset registry + migration hints
// ---------------------------------------------------------------------------

/// A sunset entry: the ISO sunset date and the recommended replacement.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct DeprecationEntry {
    pub sunset: &'static str,
    pub replacement: &'static str,
}

/// Model-id → deprecation entry (mirrors `DEPRECATION_REGISTRY`).
pub const DEPRECATION_REGISTRY: &[(&str, DeprecationEntry)] = &[
    (
        "openai/sora-2",
        DeprecationEntry {
            sunset: "2026-09-24",
            replacement: "google/veo-3.1",
        },
    ),
    (
        "runwayml/gen-3a",
        DeprecationEntry {
            sunset: "2026-07-30",
            replacement: "runwayml/gen-4",
        },
    ),
    (
        "kwaivgi/kling-v1.6",
        DeprecationEntry {
            sunset: "2027-01-01",
            replacement: "kwaivgi/kling-v2-master",
        },
    ),
];

/// Lifecycle status of a model relative to `today`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Lifecycle {
    Active,
    Deprecating,
    Sunset,
}

fn deprecation_entry(model_id: &str) -> Option<&'static DeprecationEntry> {
    DEPRECATION_REGISTRY
        .iter()
        .find(|(id, _)| *id == model_id)
        .map(|(_, entry)| entry)
}

/// ISO dates compare lexicographically = chronologically → `today` is a param.
pub fn lifecycle(model_id: &str, today: &str) -> Lifecycle {
    match deprecation_entry(model_id) {
        None => Lifecycle::Active,
        Some(entry) => {
            if today >= entry.sunset {
                Lifecycle::Sunset
            } else {
                Lifecycle::Deprecating
            }
        }
    }
}

/// Recommended replacement model, if the model is registered for sunset.
pub fn replacement_for(model_id: &str) -> Option<&'static str> {
    deprecation_entry(model_id).map(|entry| entry.replacement)
}

/// Migration guidance for a model at a given date.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrationHint {
    pub model: String,
    pub status: Lifecycle,
    pub should_migrate: bool,
    pub replacement: Option<String>,
}

/// Build a migration hint: models past/near sunset should migrate.
pub fn migrate(model_id: &str, today: &str) -> MigrationHint {
    let status = lifecycle(model_id, today);
    MigrationHint {
        model: model_id.to_string(),
        status,
        should_migrate: status == Lifecycle::Deprecating || status == Lifecycle::Sunset,
        replacement: replacement_for(model_id).map(|s| s.to_string()),
    }
}

// ---------------------------------------------------------------------------
// envelope.ts — unified async job envelope
// ---------------------------------------------------------------------------

/// Canonical async job state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum JobState {
    InQueue,
    InProgress,
    Completed,
    Failed,
    Cancelled,
}

/// All canonical states, in declaration order (mirrors `STATES`).
pub const STATES: [JobState; 5] = [
    JobState::InQueue,
    JobState::InProgress,
    JobState::Completed,
    JobState::Failed,
    JobState::Cancelled,
];

/// Collapse a provider's raw status string to the canonical state.
pub fn normalize_state(raw: &str) -> JobState {
    let s = raw.trim().to_uppercase();
    match s.as_str() {
        "IN_QUEUE" | "QUEUED" | "PENDING" | "STARTING" | "CREATED" | "SUBMITTED" => {
            JobState::InQueue
        }
        "IN_PROGRESS" | "RUNNING" | "PROCESSING" | "EXECUTING" | "DREAMING" | "THROTTLED" => {
            JobState::InProgress
        }
        "COMPLETED" | "COMPLETE" | "SUCCEEDED" | "SUCCESS" | "FINISHED" => JobState::Completed,
        "FAILED" | "ERROR" | "TIMED_OUT" | "CRASHED" => JobState::Failed,
        "CANCELLED" | "CANCELED" | "ABORTED" => JobState::Cancelled,
        _ => JobState::InProgress, // unknown but live
    }
}

/// Whether a state is terminal (no further transitions expected).
pub fn is_terminal(state: JobState) -> bool {
    matches!(
        state,
        JobState::Completed | JobState::Failed | JobState::Cancelled
    )
}

/// Normalized usage record. Success-only billing: cost is carried only when
/// the run succeeded.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NormalizedUsage {
    pub units: f64,
    pub cost_micros: i64,
    pub success: bool,
}

/// Success-only billing: `cost_micros` is truncated toward zero on success and
/// zeroed on failure (mirrors `Math.trunc`).
pub fn normalized_usage(units: f64, cost_micros: f64, success: bool) -> NormalizedUsage {
    NormalizedUsage {
        units,
        cost_micros: if success {
            cost_micros.trunc() as i64
        } else {
            0
        },
        success,
    }
}

// ---------------------------------------------------------------------------
// tests — ported from packages/provider-adapter-kit golden fixtures
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn license_registry_parity() {
        let cases: &[(&str, LicenseClass)] = &[
            ("SWivid/f5-tts", LicenseClass::NonCommercial),
            ("THUDM/cogvideox-5b", LicenseClass::Territorial),
            ("black-forest-labs/flux-dev", LicenseClass::NonCommercial),
            (
                "black-forest-labs/flux-schnell",
                LicenseClass::CommercialSafe,
            ),
            ("coqui/xtts-v2", LicenseClass::NonCommercial),
            ("genmo/mochi-1", LicenseClass::CommercialSafe),
            ("kwaivgi/kling-v1.6", LicenseClass::CommercialSafe),
            ("lightricks/ltx-video", LicenseClass::CommercialSafe),
            (
                "stabilityai/stable-video-diffusion",
                LicenseClass::NonCommercial,
            ),
            ("tencent/hunyuan-video", LicenseClass::Territorial),
            ("unknown/model", LicenseClass::Territorial),
            ("wan/wan-2.2", LicenseClass::CommercialSafe),
        ];
        for (model, want) in cases {
            assert_eq!(license_class(model), *want, "license.{model}");
        }
    }

    #[test]
    fn paid_parity() {
        let cases: &[(&str, bool)] = &[
            ("SWivid/f5-tts", false),
            ("THUDM/cogvideox-5b", false),
            ("black-forest-labs/flux-dev", false),
            ("black-forest-labs/flux-schnell", true),
            ("coqui/xtts-v2", false),
            ("genmo/mochi-1", true),
            ("kwaivgi/kling-v1.6", true),
            ("lightricks/ltx-video", true),
            ("stabilityai/stable-video-diffusion", false),
            ("tencent/hunyuan-video", false),
            ("unknown/model", false),
            ("wan/wan-2.2", true),
        ];
        for (model, want) in cases {
            assert_eq!(can_use_for_paid(model), *want, "paid.{model}");
        }
    }

    fn hint(model: &str, status: Lifecycle, replacement: &str) -> MigrationHint {
        MigrationHint {
            model: model.to_string(),
            status,
            should_migrate: true,
            replacement: Some(replacement.to_string()),
        }
    }

    #[test]
    fn deprecation_migrate_parity() {
        // kwaivgi/kling-v1.6 — sunset 2027-01-01, always deprecating in-window.
        for date in ["2026-06-01", "2026-08-01", "2026-10-01"] {
            assert_eq!(
                migrate("kwaivgi/kling-v1.6", date),
                hint(
                    "kwaivgi/kling-v1.6",
                    Lifecycle::Deprecating,
                    "kwaivgi/kling-v2-master"
                ),
                "migrate.kwaivgi/kling-v1.6.{date}"
            );
        }
        // openai/sora-2 — sunset 2026-09-24.
        assert_eq!(
            migrate("openai/sora-2", "2026-06-01").status,
            Lifecycle::Deprecating
        );
        assert_eq!(
            migrate("openai/sora-2", "2026-08-01").status,
            Lifecycle::Deprecating
        );
        assert_eq!(
            migrate("openai/sora-2", "2026-10-01"),
            hint("openai/sora-2", Lifecycle::Sunset, "google/veo-3.1")
        );
        // runwayml/gen-3a — sunset 2026-07-30.
        assert_eq!(
            migrate("runwayml/gen-3a", "2026-06-01").status,
            Lifecycle::Deprecating
        );
        assert_eq!(
            migrate("runwayml/gen-3a", "2026-08-01"),
            hint("runwayml/gen-3a", Lifecycle::Sunset, "runwayml/gen-4")
        );
        assert_eq!(
            migrate("runwayml/gen-3a", "2026-10-01").status,
            Lifecycle::Sunset
        );
    }

    #[test]
    fn migrate_active_unknown_model() {
        let got = migrate("unknown/model", "2026-08-01");
        assert_eq!(
            got,
            MigrationHint {
                model: "unknown/model".to_string(),
                status: Lifecycle::Active,
                should_migrate: false,
                replacement: None,
            }
        );
    }

    #[test]
    fn sunset_boundary_is_inclusive() {
        // today >= sunset → sunset (boundary date counts as sunset).
        assert_eq!(lifecycle("openai/sora-2", "2026-09-24"), Lifecycle::Sunset);
        assert_eq!(
            lifecycle("openai/sora-2", "2026-09-23"),
            Lifecycle::Deprecating
        );
    }

    #[test]
    fn envelope_state_parity() {
        let cases: &[(&str, JobState, bool)] = &[
            ("", JobState::InProgress, false),
            ("DREAMING", JobState::InProgress, false),
            ("Fail", JobState::InProgress, false),
            ("RUNNING", JobState::InProgress, false),
            ("canceled", JobState::Cancelled, true),
            ("queued", JobState::InQueue, false),
            ("succeeded", JobState::Completed, true),
            ("weird", JobState::InProgress, false),
        ];
        for (raw, state, terminal) in cases {
            let got = normalize_state(raw);
            assert_eq!(got, *state, "state.{raw:?}");
            assert_eq!(is_terminal(got), *terminal, "terminal.{raw:?}");
        }
    }

    #[test]
    fn normalize_state_trims_and_uppercases() {
        assert_eq!(normalize_state("  running  "), JobState::InProgress);
        assert_eq!(normalize_state("Succeeded"), JobState::Completed);
    }

    #[test]
    fn usage_success_carries_truncated_cost() {
        let ok = normalized_usage(5.0, 420000.0, true);
        assert_eq!(
            ok,
            NormalizedUsage {
                units: 5.0,
                cost_micros: 420000,
                success: true,
            }
        );
    }

    #[test]
    fn usage_failure_zeroes_cost() {
        let fail = normalized_usage(5.0, 420000.0, false);
        assert_eq!(
            fail,
            NormalizedUsage {
                units: 5.0,
                cost_micros: 0,
                success: false,
            }
        );
    }

    #[test]
    fn usage_truncates_toward_zero() {
        assert_eq!(normalized_usage(1.0, 999.9, true).cost_micros, 999);
    }

    #[test]
    fn serialization_shapes_match_golden() {
        // Lowercase lifecycle, kebab-case license, SCREAMING_SNAKE state.
        assert_eq!(
            serde_json::to_string(&Lifecycle::Deprecating).unwrap(),
            "\"deprecating\""
        );
        assert_eq!(
            serde_json::to_string(&LicenseClass::CommercialSafe).unwrap(),
            "\"commercial-safe\""
        );
        assert_eq!(
            serde_json::to_string(&LicenseClass::NonCommercial).unwrap(),
            "\"non-commercial\""
        );
        assert_eq!(
            serde_json::to_string(&JobState::InQueue).unwrap(),
            "\"IN_QUEUE\""
        );
        let hint = migrate("openai/sora-2", "2026-10-01");
        let v = serde_json::to_value(&hint).unwrap();
        assert_eq!(v["model"], "openai/sora-2");
        assert_eq!(v["status"], "sunset");
        assert_eq!(v["should_migrate"], true);
        assert_eq!(v["replacement"], "google/veo-3.1");
    }

    #[test]
    fn registry_constants_are_complete() {
        assert_eq!(LICENSE_CLASSES.len(), 3);
        assert_eq!(STATES.len(), 5);
        assert_eq!(LICENSE_REGISTRY.len(), 11);
        assert_eq!(DEPRECATION_REGISTRY.len(), 3);
    }
}
