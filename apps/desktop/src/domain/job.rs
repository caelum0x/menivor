//! Shared reel and B-roll lifecycle semantics.

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) enum JobKind {
    Reel,
    Broll,
}

impl JobKind {
    pub(crate) fn label(self) -> &'static str {
        match self {
            Self::Reel => "REEL",
            Self::Broll => "AI B-ROLL",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) enum JobState {
    Queued,
    Running,
    Complete,
    Failed,
}

impl JobState {
    pub(crate) fn label(self) -> &'static str {
        match self {
            Self::Queued => "Queued",
            Self::Running => "Generating",
            Self::Complete => "Ready",
            Self::Failed => "Needs attention",
        }
    }
}
