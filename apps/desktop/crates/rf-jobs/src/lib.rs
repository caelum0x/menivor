//! Local render-job envelope — the Rust mirror of the API's
//! `app/services/render/envelope.py` state machine, so the desktop local render
//! farm (`rf-render`) speaks the exact same `IN_QUEUE → IN_PROGRESS → COMPLETED /
//! FAILED / CANCELLED` grammar as the cloud. Pure + deterministic; unit-tested
//! with `cargo test` (no I/O here).

use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum State {
    InQueue,
    InProgress,
    Completed,
    Failed,
    Cancelled,
}

impl State {
    pub fn is_terminal(self) -> bool {
        matches!(self, State::Completed | State::Failed | State::Cancelled)
    }

    /// Legal forward edges — terminal states have no outgoing transitions.
    fn can_go(self, to: State) -> bool {
        use State::*;
        match self {
            InQueue => matches!(to, InQueue | InProgress | Completed | Failed | Cancelled),
            InProgress => matches!(to, InProgress | Completed | Failed | Cancelled),
            Completed => to == Completed,
            Failed => to == Failed,
            Cancelled => to == Cancelled,
        }
    }

    /// Normalize a backend's raw status string to a canonical state.
    ///
    /// The vocabularies mirror `envelope._DEFAULT_ALIASES` in the Python API so
    /// both sides collapse provider statuses identically.
    pub fn normalize(raw: &str) -> State {
        match raw.trim().to_ascii_uppercase().as_str() {
            "IN_QUEUE" | "QUEUED" | "STARTING" | "PENDING" | "CREATED" | "NOT_STARTED" => {
                State::InQueue
            }
            "IN_PROGRESS" | "RUNNING" | "PROCESSING" | "EXECUTING" | "UPLOADING" => {
                State::InProgress
            }
            "COMPLETED" | "COMPLETE" | "SUCCEEDED" | "SUCCESS" | "FINISHED" | "DONE" => {
                State::Completed
            }
            "FAILED" | "FAILURE" | "ERROR" | "TIMED_OUT" | "TIMEOUT" | "CRASHED" => State::Failed,
            "CANCELLED" | "CANCELED" | "ABORTED" => State::Cancelled,
            // Unknown but live -> treat as running (safer than done/failed).
            _ => State::InProgress,
        }
    }
}

impl fmt::Display for State {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let s = match self {
            State::InQueue => "IN_QUEUE",
            State::InProgress => "IN_PROGRESS",
            State::Completed => "COMPLETED",
            State::Failed => "FAILED",
            State::Cancelled => "CANCELLED",
        };
        f.write_str(s)
    }
}

#[derive(Debug, Clone)]
pub struct RenderJob {
    pub id: String,
    pub state: State,
    pub progress: f32,
    pub output_refs: Vec<String>,
    pub error: String,
}

#[derive(Debug, PartialEq, Eq)]
pub struct TransitionError(pub String);

impl RenderJob {
    pub fn new(id: impl Into<String>) -> Self {
        RenderJob {
            id: id.into(),
            state: State::InQueue,
            progress: 0.0,
            output_refs: Vec::new(),
            error: String::new(),
        }
    }

    /// Advance to `target`, enforcing the legal edges. A no-op re-entry into the
    /// same terminal state is allowed (idempotent poll/webhook).
    pub fn transition(
        &mut self,
        target: State,
        progress: Option<f32>,
    ) -> Result<(), TransitionError> {
        if self.state == target && target.is_terminal() {
            return Ok(());
        }
        if !self.state.can_go(target) {
            return Err(TransitionError(format!(
                "illegal transition {} -> {} (job {})",
                self.state, target, self.id
            )));
        }
        // Mirror `envelope.transition`: an explicit progress is clamped and wins;
        // otherwise COMPLETED implies 1.0 and every other target keeps current.
        let mut next = self.progress;
        if let Some(p) = progress {
            next = p.clamp(0.0, 1.0);
        } else if target == State::Completed {
            next = 1.0;
        }
        if !target.is_terminal() {
            // Monotonic while running — never regress a live poll.
            next = next.max(self.progress);
        }
        self.state = target;
        self.progress = next;
        Ok(())
    }

    /// A node reported the render finished: move to `Completed` (progress → 1.0)
    /// and attach the output references. Idempotent if already completed.
    pub fn complete(&mut self, output_refs: Vec<String>) -> Result<(), TransitionError> {
        self.transition(State::Completed, None)?;
        self.output_refs = output_refs;
        Ok(())
    }

    /// A node crashed / the render errored: move to `Failed` and record the
    /// reason. Per the shared state machine an in-progress job cannot return to
    /// the queue — the caller creates a fresh retry job instead.
    pub fn fail(&mut self, error: impl Into<String>) -> Result<(), TransitionError> {
        self.transition(State::Failed, None)?;
        self.error = error.into();
        Ok(())
    }

    /// The user aborted the job before it finished. No-op if already cancelled.
    pub fn cancel(&mut self) -> Result<(), TransitionError> {
        self.transition(State::Cancelled, None)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legal_flow_to_completed() {
        let mut j = RenderJob::new("j1");
        assert_eq!(j.state, State::InQueue);
        j.transition(State::InProgress, Some(0.3)).unwrap();
        assert_eq!(j.state, State::InProgress);
        j.transition(State::Completed, None).unwrap();
        assert!(j.state.is_terminal() && j.progress == 1.0);
    }

    #[test]
    fn no_move_out_of_terminal() {
        let mut j = RenderJob::new("j");
        j.transition(State::Completed, None).unwrap();
        assert!(j.transition(State::InProgress, None).is_err());
        // idempotent terminal re-entry is fine
        assert!(j.transition(State::Completed, None).is_ok());
    }

    #[test]
    fn progress_is_monotonic() {
        let mut j = RenderJob::new("j");
        j.transition(State::InProgress, Some(0.6)).unwrap();
        j.transition(State::InProgress, Some(0.2)).unwrap();
        assert_eq!(j.progress, 0.6);
    }

    #[test]
    fn normalize_vocabularies() {
        assert_eq!(State::normalize("queued"), State::InQueue);
        assert_eq!(State::normalize("Processing"), State::InProgress);
        assert_eq!(State::normalize("SUCCEEDED"), State::Completed);
        assert_eq!(State::normalize("error"), State::Failed);
        assert_eq!(State::normalize("weird"), State::InProgress);
    }

    #[test]
    fn complete_sets_progress_and_output() {
        let mut j = RenderJob::new("j");
        j.transition(State::InProgress, Some(0.4)).unwrap();
        j.complete(vec!["r2://out.mp4".into()]).unwrap();
        assert_eq!(j.state, State::Completed);
        assert_eq!(j.progress, 1.0);
        assert_eq!(j.output_refs, vec!["r2://out.mp4".to_string()]);
    }

    #[test]
    fn fail_records_the_reason() {
        let mut j = RenderJob::new("j");
        j.transition(State::InProgress, Some(0.5)).unwrap();
        j.fail("node gpu-a crashed").unwrap();
        assert_eq!(j.state, State::Failed);
        assert_eq!(j.error, "node gpu-a crashed");
    }

    #[test]
    fn cannot_fail_a_completed_job() {
        let mut j = RenderJob::new("j");
        j.complete(vec![]).unwrap();
        // Completed is terminal — failing it is an illegal transition.
        assert!(j.fail("late error").is_err());
        assert_eq!(j.state, State::Completed);
    }

    #[test]
    fn cancel_from_queue_or_progress() {
        let mut queued = RenderJob::new("q");
        queued.cancel().unwrap();
        assert_eq!(queued.state, State::Cancelled);

        let mut running = RenderJob::new("r");
        running.transition(State::InProgress, Some(0.2)).unwrap();
        running.cancel().unwrap();
        assert_eq!(running.state, State::Cancelled);
    }
}
