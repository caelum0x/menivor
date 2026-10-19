//! PYTHON-BEHAVIORAL-PARITY tests.
//!
//! Pins the `rf-clipfarm` crate's behavior to the Python module it mirrors:
//! `apps/api/app/domains/series/fanout.py`. These are black-box integration
//! tests exercising only the crate's PUBLIC API.
//!
//! Parity is by *decisions / ordering*, NOT hash values: the Python
//! `spec_hash` is SHA-256-truncated while the Rust one is FNV-1a, so the raw
//! digests differ by design. What must match is:
//!   * the `itertools.product(bodies, hooks, templates, aspects, accounts)`
//!     enumeration order (bodies outermost, accounts innermost),
//!   * the within-run + against-`seen` dedupe decisions those hashes drive,
//!   * the `total_combinations` / `skipped_duplicates` accounting,
//!   * `pace_by_account`'s per-account cap (order-preserving, overflow dropped,
//!     `0` = no cap).

use std::collections::HashSet;

use rf_clipfarm::{pace_by_account, plan_fanout, spec_hash, ClipSpec, FanoutMatrix};

fn s(v: &[&str]) -> Vec<String> {
    v.iter().map(|x| x.to_string()).collect()
}

fn matrix(
    bodies: &[&str],
    hooks: &[&str],
    templates: &[&str],
    aspects: &[&str],
    accounts: &[&str],
) -> FanoutMatrix {
    FanoutMatrix {
        bodies: s(bodies),
        hooks: s(hooks),
        templates: s(templates),
        aspects: s(aspects),
        accounts: s(accounts),
    }
}

/// Full 5-axis tuple in enumeration order, for asserting product ordering.
fn tuples(specs: &[ClipSpec]) -> Vec<(&str, &str, &str, &str, &str)> {
    specs
        .iter()
        .map(|c| {
            (
                c.body.as_str(),
                c.hook.as_str(),
                c.template.as_str(),
                c.aspect.as_str(),
                c.account.as_str(),
            )
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Product ORDER — mirrors itertools.product(bodies, hooks, templates,
// aspects, accounts): bodies vary slowest (outer), accounts fastest (inner).
// ---------------------------------------------------------------------------

#[test]
fn product_order_bodies_outer_accounts_inner() {
    // Two axes varied so the nesting is observable end-to-end.
    let m = matrix(&["b1", "b2"], &["h1"], &["t1"], &["9:16"], &["a1", "a2"]);
    let specs = plan_fanout(&m, &HashSet::new()).specs;
    let order: Vec<(&str, &str)> = specs
        .iter()
        .map(|c| (c.body.as_str(), c.account.as_str()))
        .collect();
    // Python: for (b1,a1),(b1,a2),(b2,a1),(b2,a2) — account cycles inside body.
    assert_eq!(
        order,
        vec![("b1", "a1"), ("b1", "a2"), ("b2", "a1"), ("b2", "a2")]
    );
}

#[test]
fn product_order_all_five_axes_odometer() {
    // Every axis has 2 entries → 32 combinations. The rightmost axis (accounts)
    // must "tick" fastest, the leftmost (bodies) slowest — exactly
    // itertools.product's odometer semantics.
    let m = matrix(
        &["b1", "b2"],
        &["h1", "h2"],
        &["t1", "t2"],
        &["9:16", "1:1"],
        &["a1", "a2"],
    );
    let plan = plan_fanout(&m, &HashSet::new());
    assert_eq!(plan.total_combinations, 32);
    let got = tuples(&plan.specs);

    // Build the expected order the same way itertools.product does.
    let mut expected = Vec::new();
    for b in ["b1", "b2"] {
        for h in ["h1", "h2"] {
            for t in ["t1", "t2"] {
                for asp in ["9:16", "1:1"] {
                    for acc in ["a1", "a2"] {
                        expected.push((b, h, t, asp, acc));
                    }
                }
            }
        }
    }
    assert_eq!(got, expected);
}

// ---------------------------------------------------------------------------
// Default matrix axes — FanoutMatrix defaults in Python: hooks=("",),
// templates=("",), aspects=("9:16",), accounts=("",).
// ---------------------------------------------------------------------------

#[test]
fn default_axes_match_python_defaults() {
    let m = FanoutMatrix::new(s(&["b1"]));
    let plan = plan_fanout(&m, &HashSet::new());
    assert_eq!(plan.total_combinations, 1);
    assert_eq!(plan.specs.len(), 1);
    let spec = &plan.specs[0];
    assert_eq!(spec.body, "b1");
    assert_eq!(spec.hook, "");
    assert_eq!(spec.template, "");
    assert_eq!(spec.aspect, "9:16");
    assert_eq!(spec.account, "");
}

// ---------------------------------------------------------------------------
// Accounting — total_combinations counts EVERY product tuple (including
// skipped dupes); skipped_duplicates counts those not emitted.
// ---------------------------------------------------------------------------

#[test]
fn accounting_counts_all_combinations_including_skips() {
    let m = matrix(&["b1", "b2"], &["h1", "h2"], &["t1"], &["9:16"], &["a1"]);
    let plan = plan_fanout(&m, &HashSet::new());
    assert_eq!(plan.total_combinations, 4);
    assert_eq!(plan.specs.len(), 4);
    assert_eq!(plan.skipped_duplicates, 0);
    // Invariant the Python holds: specs + skipped == total.
    assert_eq!(
        plan.specs.len() + plan.skipped_duplicates,
        plan.total_combinations
    );
}

// ---------------------------------------------------------------------------
// Within-run dedupe — a combination that repeats inside the SAME matrix
// (duplicate axis value) hashes identically, so only the first is emitted;
// the rest are skipped. Python adds each fresh hash to `seen` as it goes.
// ---------------------------------------------------------------------------

#[test]
fn within_run_dedupe_collapses_duplicate_axis_values() {
    // bodies has "b1" twice → two product tuples with identical hash.
    let m = matrix(&["b1", "b1"], &["h1"], &["t1"], &["9:16"], &["a1"]);
    let plan = plan_fanout(&m, &HashSet::new());
    assert_eq!(plan.total_combinations, 2);
    assert_eq!(plan.specs.len(), 1);
    assert_eq!(plan.skipped_duplicates, 1);
    // The emitted one is the first occurrence.
    assert_eq!(plan.specs[0].body, "b1");
}

#[test]
fn within_run_dedupe_multiple_duplicates() {
    // Three identical rows collapse to one; two skipped.
    let m = matrix(&["b1", "b1", "b1"], &[""], &[""], &["9:16"], &[""]);
    let plan = plan_fanout(&m, &HashSet::new());
    assert_eq!(plan.total_combinations, 3);
    assert_eq!(plan.specs.len(), 1);
    assert_eq!(plan.skipped_duplicates, 2);
}

// ---------------------------------------------------------------------------
// Against-`seen` dedupe — a hash already rendered in a PRIOR run (seeded via
// the crate's own spec_hash) is skipped, never re-emitted. This is the whole
// point of the content-addressed hash. We seed `seen` with the *crate's own*
// hashes (never cross-surface), matching the module's guidance.
// ---------------------------------------------------------------------------

#[test]
fn against_seen_dedupe_skips_prior_run() {
    let m = FanoutMatrix::new(s(&["b1"]));
    let first = plan_fanout(&m, &HashSet::new());
    assert_eq!(first.specs.len(), 1);

    let seen: HashSet<String> = first.specs.iter().map(|c| c.spec_hash.clone()).collect();
    let again = plan_fanout(&m, &seen);
    assert_eq!(again.specs.len(), 0);
    assert_eq!(again.skipped_duplicates, 1);
    assert_eq!(again.total_combinations, 1);
}

#[test]
fn against_seen_dedupe_is_partial() {
    // Prior run rendered only (b1); this run's matrix adds b2. Only b2 is fresh.
    let seen: HashSet<String> = [spec_hash("b1", "", "", "9:16", "")].into_iter().collect();
    let m = matrix(&["b1", "b2"], &[""], &[""], &["9:16"], &[""]);
    let plan = plan_fanout(&m, &seen);
    assert_eq!(plan.total_combinations, 2);
    assert_eq!(plan.skipped_duplicates, 1);
    assert_eq!(plan.specs.len(), 1);
    assert_eq!(plan.specs[0].body, "b2");
}

// ---------------------------------------------------------------------------
// Account-scoping DECISION — the same creative for a different account is NOT
// a dupe. We assert the *decision* (both emitted), not the hash values.
// ---------------------------------------------------------------------------

#[test]
fn same_creative_different_account_is_not_a_dupe() {
    let m = matrix(&["b1"], &["h1"], &["t1"], &["9:16"], &["acc1", "acc2"]);
    let plan = plan_fanout(&m, &HashSet::new());
    // Both survive: account is part of the hash, so no dedupe collision.
    assert_eq!(plan.specs.len(), 2);
    assert_eq!(plan.skipped_duplicates, 0);
    assert_ne!(plan.specs[0].spec_hash, plan.specs[1].spec_hash);
}

#[test]
fn spec_hash_is_deterministic_and_account_scoped_decision() {
    // Stable across calls (drives reproducible dedupe).
    assert_eq!(
        spec_hash("b", "h", "t", "9:16", "acc1"),
        spec_hash("b", "h", "t", "9:16", "acc1")
    );
    // Differs by account (drives the "not a dupe across accounts" decision).
    assert_ne!(
        spec_hash("b", "h", "t", "9:16", "acc1"),
        spec_hash("b", "h", "t", "9:16", "acc2")
    );
    // Differs by any other axis too.
    assert_ne!(
        spec_hash("b", "h", "t", "9:16", "acc1"),
        spec_hash("b2", "h", "t", "9:16", "acc1")
    );
}

// ---------------------------------------------------------------------------
// pace_by_account — caps posts per account this run; keeps input order; drops
// overflow; max_per_account == 0 means no cap (Python: <= 0).
// ---------------------------------------------------------------------------

#[test]
fn pace_caps_per_account_keeping_order() {
    // Interleaved accounts (accounts innermost): a1,a2,a1,a2,a1,a2 across 3 bodies.
    let m = matrix(
        &["b1", "b2", "b3"],
        &["h1"],
        &["t1"],
        &["9:16"],
        &["a1", "a2"],
    );
    let specs = plan_fanout(&m, &HashSet::new()).specs;
    assert_eq!(specs.len(), 6);

    // Cap 1 per account: keep the FIRST spec seen for each account, in order.
    let paced = pace_by_account(&specs, 1);
    assert_eq!(paced.len(), 2);
    assert_eq!(paced[0].body, "b1");
    assert_eq!(paced[0].account, "a1");
    assert_eq!(paced[1].body, "b1");
    assert_eq!(paced[1].account, "a2");

    // Cap 2 per account: 2 from a1 + 2 from a2, still in original order.
    let paced2 = pace_by_account(&specs, 2);
    assert_eq!(paced2.len(), 4);
    let bodies: Vec<&str> = paced2.iter().map(|c| c.body.as_str()).collect();
    let accounts: Vec<&str> = paced2.iter().map(|c| c.account.as_str()).collect();
    assert_eq!(bodies, vec!["b1", "b1", "b2", "b2"]);
    assert_eq!(accounts, vec!["a1", "a2", "a1", "a2"]);
}

#[test]
fn pace_zero_means_no_cap() {
    let m = FanoutMatrix::new(s(&["b1", "b2", "b3"]));
    let specs = plan_fanout(&m, &HashSet::new()).specs;
    // All share account "" (default), so any positive cap would trim them.
    assert_eq!(pace_by_account(&specs, 0).len(), 3);
    // Sanity: a positive cap on the shared default account DOES trim.
    assert_eq!(pace_by_account(&specs, 2).len(), 2);
}

#[test]
fn pace_below_cap_is_a_noop() {
    let m = matrix(&["b1", "b2"], &["h1"], &["t1"], &["9:16"], &["a1", "a2"]);
    let specs = plan_fanout(&m, &HashSet::new()).specs; // 2 per account
                                                        // Cap of 5 > any account's count → everything kept, order preserved.
    let paced = pace_by_account(&specs, 5);
    assert_eq!(paced, specs);
}
