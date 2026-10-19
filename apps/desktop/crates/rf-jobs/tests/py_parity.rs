//! PYTHON-BEHAVIORAL-PARITY tests.
//!
//! These pin `rf-jobs` (the Rust envelope) to the behavior documented in the
//! API's `apps/api/app/services/render/envelope.py`. Each test names the Python
//! symbol it mirrors so a future change to either side is caught here.
//!
//! Scope: the `IN_QUEUE → IN_PROGRESS → COMPLETED / FAILED / CANCELLED` state
//! machine, the legal-transition edge set (`envelope._EDGES` / `can_transition`),
//! the `normalize_state` provider vocabularies (`envelope._DEFAULT_ALIASES`), and
//! the monotonic + clamped progress rules in `envelope.transition`.
//!
//! Only the crate's PUBLIC API is used. Hash values are never asserted (the
//! Python side has no hashing here); we assert the *decisions/ordering* the
//! state machine drives instead.

use rf_jobs::{RenderJob, State};

/// The five canonical envelope states (`envelope.ALL_STATES`).
const ALL_STATES: [State; 5] = [
    State::InQueue,
    State::InProgress,
    State::Completed,
    State::Failed,
    State::Cancelled,
];

/// Build a fresh job already sitting in `state`.
///
/// Every non-queue state is reachable in one legal hop from `IN_QUEUE`
/// (`envelope._EDGES[IN_QUEUE]` == all states), so this never exercises an
/// illegal edge while constructing the fixture.
fn job_in(state: State) -> RenderJob {
    let mut j = RenderJob::new("fixture");
    if state != State::InQueue {
        j.transition(state, None)
            .expect("IN_QUEUE reaches every state in one legal hop");
    }
    j
}

/// Mirrors `envelope.can_transition`: whether `from → to` is a legal edge, read
/// through the public `transition` result (Ok == legal, Err == illegal).
fn edge_is_legal(from: State, to: State) -> bool {
    let mut j = job_in(from);
    j.transition(to, None).is_ok()
}

// ---------------------------------------------------------------------------
// State machine: TERMINAL_STATES + is_terminal
// ---------------------------------------------------------------------------

#[test]
fn is_terminal_matches_python_terminal_states() {
    // envelope.TERMINAL_STATES = {COMPLETED, FAILED, CANCELLED}
    assert!(!State::InQueue.is_terminal());
    assert!(!State::InProgress.is_terminal());
    assert!(State::Completed.is_terminal());
    assert!(State::Failed.is_terminal());
    assert!(State::Cancelled.is_terminal());
}

// ---------------------------------------------------------------------------
// Legal edge set — pins the full 5x5 matrix from envelope._EDGES.
// ---------------------------------------------------------------------------

#[test]
fn edge_matrix_matches_python_edges() {
    // The exact adjacency from envelope._EDGES:
    //   IN_QUEUE    -> every state
    //   IN_PROGRESS -> {IN_PROGRESS, COMPLETED, FAILED, CANCELLED}  (NOT IN_QUEUE)
    //   COMPLETED   -> {COMPLETED}
    //   FAILED      -> {FAILED}
    //   CANCELLED   -> {CANCELLED}
    let legal = |from: State| -> Vec<State> {
        ALL_STATES
            .iter()
            .copied()
            .filter(|&to| edge_is_legal(from, to))
            .collect()
    };

    assert_eq!(
        legal(State::InQueue),
        vec![
            State::InQueue,
            State::InProgress,
            State::Completed,
            State::Failed,
            State::Cancelled,
        ],
        "IN_QUEUE must reach every state"
    );
    assert_eq!(
        legal(State::InProgress),
        vec![
            State::InProgress,
            State::Completed,
            State::Failed,
            State::Cancelled,
        ],
        "IN_PROGRESS must NOT be able to return to IN_QUEUE"
    );
    assert_eq!(
        legal(State::Completed),
        vec![State::Completed],
        "COMPLETED is terminal — only the idempotent self-edge"
    );
    assert_eq!(legal(State::Failed), vec![State::Failed]);
    assert_eq!(legal(State::Cancelled), vec![State::Cancelled]);
}

#[test]
fn in_progress_cannot_regress_to_queue() {
    // envelope.transition raises EnvelopeError for IN_PROGRESS → IN_QUEUE.
    let mut j = job_in(State::InProgress);
    assert!(j.transition(State::InQueue, None).is_err());
    // State is left untouched on an illegal transition.
    assert_eq!(j.state, State::InProgress);
}

#[test]
fn terminal_states_have_no_outgoing_edges() {
    // A late/duplicate poll can never move a terminal job (module docstring).
    for terminal in [State::Completed, State::Failed, State::Cancelled] {
        for &target in &ALL_STATES {
            let mut j = job_in(terminal);
            let res = j.transition(target, None);
            if target == terminal {
                assert!(res.is_ok(), "idempotent self re-entry must be allowed");
            } else {
                assert!(
                    res.is_err(),
                    "{terminal} → {target} must be illegal (terminal is a sink)"
                );
                assert_eq!(j.state, terminal, "illegal move must not mutate state");
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Idempotent terminal re-entry (duplicate webhook/poll).
// ---------------------------------------------------------------------------

#[test]
fn idempotent_terminal_reentry_is_noop() {
    // envelope.transition: `if job.state == target and target in TERMINAL_STATES:
    // return job` — the job is returned UNCHANGED, ignoring any supplied progress.
    let mut j = RenderJob::new("dup");
    j.complete(vec!["r2://out.mp4".into()]).unwrap();
    assert_eq!(j.progress, 1.0);

    // A duplicate COMPLETED poll carrying a bogus lower progress must not regress.
    j.transition(State::Completed, Some(0.1)).unwrap();
    assert_eq!(j.state, State::Completed);
    assert_eq!(
        j.progress, 1.0,
        "terminal re-entry must ignore supplied progress"
    );
    assert_eq!(j.output_refs, vec!["r2://out.mp4".to_string()]);
}

// ---------------------------------------------------------------------------
// Progress: monotonic while non-terminal, clamped to [0,1],
// COMPLETED-with-None => 1.0, COMPLETED-with-explicit => the explicit value.
// ---------------------------------------------------------------------------

#[test]
fn progress_is_monotonic_while_running() {
    // envelope.transition: `if target not in TERMINAL_STATES:
    // new_progress = max(job.progress, new_progress)`.
    let mut j = RenderJob::new("mono");
    j.transition(State::InProgress, Some(0.6)).unwrap();
    j.transition(State::InProgress, Some(0.2)).unwrap();
    assert_eq!(
        j.progress, 0.6,
        "a lower running poll must not regress progress"
    );
}

#[test]
fn progress_is_clamped_to_unit_interval() {
    // envelope.transition: `new_progress = max(0.0, min(1.0, float(progress)))`.
    let mut hi = RenderJob::new("hi");
    hi.transition(State::InProgress, Some(1.5)).unwrap();
    assert_eq!(hi.progress, 1.0);

    let mut lo = RenderJob::new("lo");
    lo.transition(State::InProgress, Some(-0.3)).unwrap();
    assert_eq!(lo.progress, 0.0);
}

#[test]
fn completed_without_progress_defaults_to_one() {
    // envelope.transition: `elif target == COMPLETED: new_progress = 1.0`.
    let mut j = RenderJob::new("done");
    j.transition(State::InProgress, Some(0.3)).unwrap();
    j.transition(State::Completed, None).unwrap();
    assert_eq!(j.progress, 1.0);
}

#[test]
fn completed_with_explicit_progress_uses_that_value() {
    // envelope.transition evaluates the explicit `progress` FIRST, so a supplied
    // value wins even for COMPLETED (the `elif target == COMPLETED` never runs).
    // This is the divergence that was fixed in the Rust port.
    let mut j = RenderJob::new("partial-done");
    j.transition(State::InProgress, Some(0.3)).unwrap();
    j.transition(State::Completed, Some(0.42)).unwrap();
    assert_eq!(j.state, State::Completed);
    assert_eq!(
        j.progress, 0.42,
        "explicit progress must win over the COMPLETED=>1.0 default"
    );
}

#[test]
fn terminal_failure_preserves_current_progress() {
    // envelope.transition: for a terminal target with progress=None, new_progress
    // stays job.progress and the monotonic max is skipped.
    let mut j = RenderJob::new("boom");
    j.transition(State::InProgress, Some(0.5)).unwrap();
    j.fail("gpu crashed").unwrap();
    assert_eq!(j.state, State::Failed);
    assert_eq!(
        j.progress, 0.5,
        "FAILED must keep the last observed progress"
    );
    assert_eq!(j.error, "gpu crashed");
}

// ---------------------------------------------------------------------------
// normalize_state — pins the full envelope._DEFAULT_ALIASES vocabulary,
// case-insensitivity, whitespace trimming, and the IN_PROGRESS default.
// ---------------------------------------------------------------------------

#[test]
fn normalize_queue_vocabulary() {
    // _DEFAULT_ALIASES queue bucket.
    for raw in [
        "IN_QUEUE",
        "QUEUED",
        "STARTING",
        "PENDING",
        "CREATED",
        "NOT_STARTED",
    ] {
        assert_eq!(
            State::normalize(raw),
            State::InQueue,
            "{raw} should be IN_QUEUE"
        );
    }
}

#[test]
fn normalize_running_vocabulary() {
    // _DEFAULT_ALIASES running bucket.
    for raw in [
        "IN_PROGRESS",
        "RUNNING",
        "PROCESSING",
        "EXECUTING",
        "UPLOADING",
    ] {
        assert_eq!(
            State::normalize(raw),
            State::InProgress,
            "{raw} should be IN_PROGRESS"
        );
    }
}

#[test]
fn normalize_done_vocabulary() {
    // _DEFAULT_ALIASES done bucket.
    for raw in [
        "COMPLETED",
        "COMPLETE",
        "SUCCEEDED",
        "SUCCESS",
        "FINISHED",
        "DONE",
    ] {
        assert_eq!(
            State::normalize(raw),
            State::Completed,
            "{raw} should be COMPLETED"
        );
    }
}

#[test]
fn normalize_failed_vocabulary() {
    // _DEFAULT_ALIASES failed bucket.
    for raw in [
        "FAILED",
        "FAILURE",
        "ERROR",
        "TIMED_OUT",
        "TIMEOUT",
        "CRASHED",
    ] {
        assert_eq!(
            State::normalize(raw),
            State::Failed,
            "{raw} should be FAILED"
        );
    }
}

#[test]
fn normalize_cancelled_vocabulary() {
    // _DEFAULT_ALIASES cancelled bucket.
    for raw in ["CANCELLED", "CANCELED", "ABORTED"] {
        assert_eq!(
            State::normalize(raw),
            State::Cancelled,
            "{raw} should be CANCELLED"
        );
    }
}

#[test]
fn normalize_is_case_insensitive_and_trims() {
    // envelope.normalize_state: `str(raw or "").strip().upper()`.
    assert_eq!(State::normalize("queued"), State::InQueue);
    assert_eq!(State::normalize("  Processing  "), State::InProgress);
    assert_eq!(State::normalize("Succeeded"), State::Completed);
    assert_eq!(State::normalize("\tcanceled\n"), State::Cancelled);
}

#[test]
fn normalize_unknown_and_empty_default_to_in_progress() {
    // "a live job we don't yet understand is safer treated as running".
    assert_eq!(State::normalize("wat"), State::InProgress);
    assert_eq!(State::normalize(""), State::InProgress);
    assert_eq!(State::normalize("   "), State::InProgress);
}

// ---------------------------------------------------------------------------
// End-to-end happy path mirrors the module docstring's canonical flow.
// ---------------------------------------------------------------------------

#[test]
fn canonical_lifecycle_queue_to_completed() {
    let mut j = RenderJob::new("job-1");
    assert_eq!(j.state, State::InQueue);
    assert_eq!(j.progress, 0.0);

    // Provider reports "running" then a couple of progress polls.
    j.transition(State::normalize("running"), Some(0.25))
        .unwrap();
    assert_eq!(j.state, State::InProgress);
    j.transition(State::InProgress, Some(0.75)).unwrap();

    // Provider reports "succeeded" -> COMPLETED with progress pinned to 1.0.
    j.complete(vec!["r2://final.mp4".into()]).unwrap();
    assert_eq!(j.state, State::Completed);
    assert_eq!(j.progress, 1.0);
    assert_eq!(j.output_refs, vec!["r2://final.mp4".to_string()]);
}
