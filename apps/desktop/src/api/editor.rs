//! Authenticated non-destructive timeline export operations.

use rf_project::TimelineExport;

use super::{ApiClient, ApiFailure, ApiFailureKind, TimelineExportJobDto};

impl ApiClient {
    pub(crate) fn create_timeline_export(
        &self,
        source_job_id: &str,
        timeline: &TimelineExport,
        idempotency_key: &str,
    ) -> Result<TimelineExportJobDto, ApiFailure> {
        timeline.validate().map_err(|error| ApiFailure {
            kind: ApiFailureKind::Request,
            status: None,
            message: format!("Timeline is not exportable: {error}"),
        })?;
        let body: serde_json::Value =
            serde_json::from_str(&timeline.to_request_json().map_err(|error| ApiFailure {
                kind: ApiFailureKind::InvalidResponse,
                status: None,
                message: format!("Could not serialize the timeline: {error}"),
            })?)
            .map_err(|error| ApiFailure {
                kind: ApiFailureKind::InvalidResponse,
                status: None,
                message: format!("Could not assemble the timeline request: {error}"),
            })?;

        self.post_idempotent(
            &format!("/jobs/{source_job_id}/timeline-exports"),
            &body,
            idempotency_key,
        )
    }
}
