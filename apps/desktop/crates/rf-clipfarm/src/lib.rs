//! Local clipfarm fan-out — the Rust mirror of `app/domains/series/fanout.py`, so
//! the desktop bulk-operator console expands the same body×hooks×templates×
//! aspects×accounts matrix, dedupes by a stable content hash, and paces per
//! account. Pure + deterministic.
//!
//! Parity note: this crate's [`spec_hash`] is its OWN FNV-1a (dependency-free),
//! NOT the same *value* as the Python side's SHA-256-truncated hash. Parity with
//! the cloud is by dedupe *behavior* — the matrix is enumerated in the identical
//! product order (bodies outermost, accounts innermost) and the same
//! within-run / against-`seen` dedupe decisions are made, so a given matrix
//! yields the same set + order of specs on both surfaces. The hashes are
//! therefore interchangeable only *within* a surface (a desktop `seen` set is
//! local); do not seed one surface's `seen` set with the other's hashes.

use std::collections::HashSet;

#[derive(Debug, Clone)]
pub struct FanoutMatrix {
    pub bodies: Vec<String>,
    pub hooks: Vec<String>,
    pub templates: Vec<String>,
    pub aspects: Vec<String>,
    pub accounts: Vec<String>,
}

impl FanoutMatrix {
    pub fn new(bodies: Vec<String>) -> Self {
        FanoutMatrix {
            bodies,
            hooks: vec![String::new()],
            templates: vec![String::new()],
            aspects: vec!["9:16".to_string()],
            accounts: vec![String::new()],
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClipSpec {
    pub spec_hash: String,
    pub body: String,
    pub hook: String,
    pub template: String,
    pub aspect: String,
    pub account: String,
}

#[derive(Debug, Default)]
pub struct FanoutPlan {
    pub specs: Vec<ClipSpec>,
    pub skipped_duplicates: usize,
    pub total_combinations: usize,
}

/// FNV-1a (64-bit) over the canonical `body|hook|template|aspect|account` string,
/// hex-truncated to 16 chars — account-scoped so the same creative can post to
/// different accounts.
pub fn spec_hash(body: &str, hook: &str, template: &str, aspect: &str, account: &str) -> String {
    let canonical = format!("{body}\u{1f}{hook}\u{1f}{template}\u{1f}{aspect}\u{1f}{account}");
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in canonical.bytes() {
        hash ^= byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{hash:016x}")
}

/// Expand the matrix into fresh specs, skipping any hash already in `seen`
/// (prior runs) or duplicated within this expansion.
pub fn plan_fanout(matrix: &FanoutMatrix, seen: &HashSet<String>) -> FanoutPlan {
    let mut plan = FanoutPlan::default();
    let mut local: HashSet<String> = seen.clone();
    for body in &matrix.bodies {
        for hook in &matrix.hooks {
            for template in &matrix.templates {
                for aspect in &matrix.aspects {
                    for account in &matrix.accounts {
                        plan.total_combinations += 1;
                        let h = spec_hash(body, hook, template, aspect, account);
                        if local.contains(&h) {
                            plan.skipped_duplicates += 1;
                            continue;
                        }
                        local.insert(h.clone());
                        plan.specs.push(ClipSpec {
                            spec_hash: h,
                            body: body.clone(),
                            hook: hook.clone(),
                            template: template.clone(),
                            aspect: aspect.clone(),
                            account: account.clone(),
                        });
                    }
                }
            }
        }
    }
    plan
}

/// Cap how many specs post to each account this run (cannibalization pacing).
pub fn pace_by_account(specs: &[ClipSpec], max_per_account: usize) -> Vec<ClipSpec> {
    if max_per_account == 0 {
        return specs.to_vec();
    }
    let mut counts: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    let mut kept = Vec::new();
    for spec in specs {
        let n = counts.entry(spec.account.clone()).or_insert(0);
        if *n >= max_per_account {
            continue;
        }
        *n += 1;
        kept.push(spec.clone());
    }
    kept
}

/// Cap the TOTAL specs run this batch, across all accounts (a faceless operator's
/// per-run budget — "render at most N clips tonight"). Order-preserving: keeps the
/// first `max_total`, leaving the overflow for the next run's window. `0` = no cap.
/// Compose with [`pace_by_account`] (per-account first, then a global ceiling).
pub fn cap_total(specs: &[ClipSpec], max_total: usize) -> Vec<ClipSpec> {
    if max_total == 0 || specs.len() <= max_total {
        return specs.to_vec();
    }
    specs[..max_total].to_vec()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn full_cartesian_product() {
        let m = FanoutMatrix {
            bodies: s(&["b1", "b2"]),
            hooks: s(&["h1", "h2"]),
            templates: s(&["t1"]),
            aspects: s(&["9:16"]),
            accounts: s(&["acc1"]),
        };
        let plan = plan_fanout(&m, &HashSet::new());
        assert_eq!(plan.total_combinations, 4);
        assert_eq!(plan.specs.len(), 4);
        assert_eq!(plan.skipped_duplicates, 0);
    }

    #[test]
    fn dedupes_against_seen() {
        let m = FanoutMatrix::new(s(&["b1"]));
        let first = plan_fanout(&m, &HashSet::new());
        let seen: HashSet<String> = first.specs.iter().map(|s| s.spec_hash.clone()).collect();
        let again = plan_fanout(&m, &seen);
        assert_eq!(again.specs.len(), 0);
        assert_eq!(again.skipped_duplicates, 1);
    }

    #[test]
    fn hash_is_stable_and_account_scoped() {
        let a = spec_hash("b", "h", "t", "9:16", "acc1");
        let b = spec_hash("b", "h", "t", "9:16", "acc1");
        let c = spec_hash("b", "h", "t", "9:16", "acc2");
        assert_eq!(a, b);
        assert_ne!(a, c);
    }

    #[test]
    fn pacing_caps_per_account() {
        let m = FanoutMatrix::new(s(&["b1", "b2", "b3"]));
        let specs = plan_fanout(&m, &HashSet::new()).specs;
        assert_eq!(pace_by_account(&specs, 2).len(), 2);
        assert_eq!(pace_by_account(&specs, 0).len(), 3);
    }

    #[test]
    fn cap_total_limits_batch_order_preserving() {
        let m = FanoutMatrix::new(s(&["b1", "b2", "b3", "b4", "b5"]));
        let specs = plan_fanout(&m, &HashSet::new()).specs;
        let capped = cap_total(&specs, 3);
        assert_eq!(capped.len(), 3);
        // Keeps the FIRST three in order (the overflow waits for next run).
        assert_eq!(capped[0].body, "b1");
        assert_eq!(capped[2].body, "b3");
        // 0 = no cap; a cap >= len is a no-op.
        assert_eq!(cap_total(&specs, 0).len(), 5);
        assert_eq!(cap_total(&specs, 99).len(), 5);
    }

    #[test]
    fn pace_then_cap_composes() {
        let m = FanoutMatrix {
            bodies: s(&["b1", "b2", "b3"]),
            hooks: s(&["h1", "h2"]),
            templates: s(&["t1"]),
            aspects: s(&["9:16"]),
            accounts: s(&["a1", "a2"]),
        };
        let specs = plan_fanout(&m, &HashSet::new()).specs;
        // Per-account cap of 3, then a global ceiling of 4.
        let paced = pace_by_account(&specs, 3);
        let final_batch = cap_total(&paced, 4);
        assert_eq!(final_batch.len(), 4);
    }

    #[test]
    fn enumeration_matches_python_product_order() {
        // Mirrors `itertools.product(bodies, hooks, templates, aspects, accounts)`:
        // bodies vary slowest (outer), accounts fastest (inner).
        let m = FanoutMatrix {
            bodies: s(&["b1", "b2"]),
            hooks: s(&["h1"]),
            templates: s(&["t1"]),
            aspects: s(&["9:16"]),
            accounts: s(&["a1", "a2"]),
        };
        let specs = plan_fanout(&m, &HashSet::new()).specs;
        let order: Vec<(&str, &str)> = specs
            .iter()
            .map(|c| (c.body.as_str(), c.account.as_str()))
            .collect();
        assert_eq!(
            order,
            vec![("b1", "a1"), ("b1", "a2"), ("b2", "a1"), ("b2", "a2")]
        );
    }
}
