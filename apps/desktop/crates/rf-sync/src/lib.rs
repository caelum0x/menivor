//! Cloud reconcile (`rf-sync`). Before a local project renders in the cloud (or
//! after offline work), the desktop app computes the delta between local and
//! remote state — which content-addressed assets must be uploaded, which are
//! already present — and runs a **wallet pre-flight**: is the reserved estimate
//! covered by the available balance? Pure diff/decision logic; the transport +
//! wallet call are the runtime's job.

use std::collections::HashSet;

/// The set of asset CAS keys present locally vs. already in the cloud.
#[derive(Debug)]
pub struct ReconcilePlan {
    pub to_upload: Vec<String>,
    pub already_present: Vec<String>,
}

/// Diff local asset keys against the cloud's known set. Result is deterministic
/// (sorted) so the UI + tests are stable.
pub fn plan_asset_sync(local_keys: &[String], remote_keys: &HashSet<String>) -> ReconcilePlan {
    let mut to_upload: Vec<String> = local_keys
        .iter()
        .filter(|k| !remote_keys.contains(*k))
        .cloned()
        .collect();
    let mut already: Vec<String> = local_keys
        .iter()
        .filter(|k| remote_keys.contains(*k))
        .cloned()
        .collect();
    to_upload.sort();
    to_upload.dedup();
    already.sort();
    already.dedup();
    ReconcilePlan {
        to_upload,
        already_present: already,
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum PreflightResult {
    /// Covered; `remaining_micros` is the balance after reserving the estimate.
    Ok { remaining_micros: u64 },
    /// Short by `shortfall_micros`; the user must top up before rendering.
    Insufficient { shortfall_micros: u64 },
}

/// Wallet pre-flight: can `estimate_micros` be reserved from `available_micros`?
pub fn wallet_preflight(estimate_micros: u64, available_micros: u64) -> PreflightResult {
    if available_micros >= estimate_micros {
        PreflightResult::Ok {
            remaining_micros: available_micros - estimate_micros,
        }
    } else {
        PreflightResult::Insufficient {
            shortfall_micros: estimate_micros - available_micros,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn set(v: &[&str]) -> HashSet<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn splits_upload_vs_present() {
        let local = vec!["a".into(), "b".into(), "c".into()];
        let remote = set(&["b"]);
        let plan = plan_asset_sync(&local, &remote);
        assert_eq!(plan.to_upload, vec!["a".to_string(), "c".to_string()]);
        assert_eq!(plan.already_present, vec!["b".to_string()]);
    }

    #[test]
    fn dedupes_local_keys() {
        let local = vec!["a".into(), "a".into(), "b".into()];
        let plan = plan_asset_sync(&local, &HashSet::new());
        assert_eq!(plan.to_upload, vec!["a".to_string(), "b".to_string()]);
    }

    #[test]
    fn preflight_ok_when_covered() {
        assert_eq!(
            wallet_preflight(100_000, 250_000),
            PreflightResult::Ok {
                remaining_micros: 150_000
            }
        );
    }

    #[test]
    fn preflight_reports_shortfall() {
        assert_eq!(
            wallet_preflight(300_000, 100_000),
            PreflightResult::Insufficient {
                shortfall_micros: 200_000
            }
        );
    }
}
