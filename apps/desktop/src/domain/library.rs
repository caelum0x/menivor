//! Library rows returned by the product API.

use super::{JobKind, JobState};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct JobSnapshot {
    pub id: String,
    pub kind: JobKind,
    pub progress: i32,
    pub state: JobState,
    pub result_url: String,
    /// Durable R2 key for an attachable B-roll clip. Signed URLs are transient.
    pub result_key: String,
    pub error: String,
    pub retry_eligible: bool,
    pub created_at: String,
    /// Cross-service trace identifier. It is safe to display and log.
    pub correlation_id: String,
}
