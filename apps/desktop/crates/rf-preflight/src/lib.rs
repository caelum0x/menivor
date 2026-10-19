//! Pre-render clearance (`rf-preflight`). Composes the two gates the desktop
//! must clear before spending on a generation into one decision:
//!
//! * the **license + lifecycle** gate (`rf-provider`) — is the model
//!   commercial-safe for a paid render, and is it still active (not sunset)?
//! * the **cost + wallet** gate (`rf-gateway`) — does the balance cover the
//!   estimate?
//!
//! Pure + deterministic (`today` and the balance are injected). Only the
//! *combining* rule lives here; every underlying number/classification comes
//! from the golden-parity crates, so a desktop clearance matches the cloud's.

use rf_gateway::{wallet_preflight, MediaModel, Preflight};
use rf_provider::{can_use_for_paid, license_class, migrate, LicenseClass, Lifecycle};

/// The combined go/no-go for one generation.
#[derive(Debug, Clone)]
pub struct Clearance {
    pub model: String,
    pub license: LicenseClass,
    /// The license is commercial-safe (may back paid output).
    pub paid_ok: bool,
    pub lifecycle: Lifecycle,
    /// Recommended replacement when the model is deprecating/sunset.
    pub replacement: Option<String>,
    pub estimate_micros: u64,
    pub available_micros: u64,
    pub affordable: bool,
    /// How much more is needed when not affordable (0 otherwise).
    pub shortfall_micros: u64,
    /// Cleared to run: commercial-safe **and** affordable **and** not sunset.
    pub cleared: bool,
    /// Human-readable reasons the generation is blocked (empty when cleared).
    pub blockers: Vec<String>,
}

/// Clear (or block) a paid generation of `model` for `seconds` of output against
/// the wallet `available_micros`, as of ISO date `today`.
pub fn clear_generation(
    model: &MediaModel,
    seconds: u32,
    available_micros: u64,
    today: &str,
) -> Clearance {
    let estimate_micros = model.estimate_cost_micros(seconds);
    let license = license_class(&model.id);
    let paid_ok = can_use_for_paid(&model.id);
    let hint = migrate(&model.id, today);

    let (affordable, shortfall_micros) = match wallet_preflight(estimate_micros, available_micros) {
        Preflight::Ok { .. } => (true, 0),
        Preflight::Insufficient { shortfall_micros } => (false, shortfall_micros),
    };

    let sunset = matches!(hint.status, Lifecycle::Sunset);
    let cleared = paid_ok && affordable && !sunset;

    let mut blockers = Vec::new();
    if !paid_ok {
        blockers.push(format!(
            "{} is not commercial-safe (license {:?})",
            model.id, license
        ));
    }
    if sunset {
        let repl = hint
            .replacement
            .as_deref()
            .map(|r| format!("; migrate to {r}"))
            .unwrap_or_default();
        blockers.push(format!("{} is sunset{repl}", model.id));
    }
    if !affordable {
        blockers.push(format!(
            "insufficient balance — short {shortfall_micros} micros"
        ));
    }

    Clearance {
        model: model.id.clone(),
        license,
        paid_ok,
        lifecycle: hint.status,
        replacement: hint.replacement,
        estimate_micros,
        available_micros,
        affordable,
        shortfall_micros,
        cleared,
        blockers,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rf_gateway::Modality;

    fn model(id: &str, price_micros: u64) -> MediaModel {
        MediaModel {
            id: id.to_string(),
            modality: Modality::Image,
            provider: "test".to_string(),
            price_micros,
            unit: "image".to_string(),
            max_seconds: 0,
            description: String::new(),
        }
    }

    #[test]
    fn commercial_safe_and_affordable_clears() {
        let c = clear_generation(&model("wan/wan-2.2", 40_000), 0, 1_000_000, "2026-08-19");
        assert!(c.paid_ok && c.affordable && c.cleared);
        assert!(c.blockers.is_empty());
        assert_eq!(c.estimate_micros, 40_000);
    }

    #[test]
    fn non_commercial_license_blocks() {
        let c = clear_generation(
            &model("black-forest-labs/flux-dev", 40_000),
            0,
            1_000_000,
            "2026-08-19",
        );
        assert!(!c.paid_ok);
        assert!(!c.cleared);
        assert!(c.blockers.iter().any(|b| b.contains("not commercial-safe")));
    }

    #[test]
    fn insufficient_balance_blocks_with_shortfall() {
        let c = clear_generation(&model("wan/wan-2.2", 500_000), 0, 100_000, "2026-08-19");
        assert!(c.paid_ok);
        assert!(!c.affordable);
        assert_eq!(c.shortfall_micros, 400_000);
        assert!(!c.cleared);
    }

    #[test]
    fn deprecating_model_still_clears_before_sunset() {
        // kling-v1.6 is commercial-safe and sunsets 2027-01-01 — before that it's
        // only "deprecating", which does not block.
        let c = clear_generation(
            &model("kwaivgi/kling-v1.6", 40_000),
            0,
            1_000_000,
            "2026-08-19",
        );
        assert!(matches!(c.lifecycle, Lifecycle::Deprecating));
        assert!(c.cleared);
        assert_eq!(c.replacement.as_deref(), Some("kwaivgi/kling-v2-master"));
    }

    #[test]
    fn sunset_model_blocks_even_when_affordable_and_licensed() {
        // Same model, but past its sunset date.
        let c = clear_generation(
            &model("kwaivgi/kling-v1.6", 40_000),
            0,
            1_000_000,
            "2027-06-01",
        );
        assert!(c.paid_ok && c.affordable);
        assert!(matches!(c.lifecycle, Lifecycle::Sunset));
        assert!(!c.cleared);
        assert!(c.blockers.iter().any(|b| b.contains("sunset")));
    }
}
