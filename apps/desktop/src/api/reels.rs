//! Canonical `/jobs` request operations.

use super::models::{JobListData, PublishResult, ReelCreateInput, ReelParams};
use super::{ApiClient, ApiFailure, JobDto};
use crate::domain::ReelDraft;

/// `/jobs` caps `limit` at 100.
const LIBRARY_PAGE_SIZE: usize = 100;
/// Upper bound on library pages fetched per refresh (10,000 reels).
const MAX_LIBRARY_PAGES: usize = 100;

impl ApiClient {
    pub(crate) fn create_reel(
        &self,
        draft: &ReelDraft,
        idempotency_key: &str,
    ) -> Result<JobDto, ApiFailure> {
        let params = ReelParams {
            video_subject: draft.video_subject.trim(),
            video_script: draft.video_script.trim(),
            voice_name: draft.voice_name.trim(),
            avatar_id: draft.avatar_id.trim(),
            avatar_provider: "heygen",
            caption_style: draft.caption_style.as_str(),
            layout: draft.layout.as_str(),
            aspect: "9:16",
            language: draft.language.as_str(),
            target_duration_s: draft.target_duration_s,
            platforms: &draft.platforms,
            screen_recording_key: draft.screen_recording_key.trim(),
        };
        self.post_idempotent(
            "/jobs",
            &ReelCreateInput {
                params,
                broll_intro_key: draft.attached_broll_key.as_deref(),
            },
            idempotency_key,
        )
    }

    pub(crate) fn get_reel(&self, id: &str) -> Result<JobDto, ApiFailure> {
        self.get(&format!("/jobs/{id}"))
    }

    /// The caller's whole reel library, newest first. `/jobs` pages at most 100
    /// rows, so this walks the pages until a short page (bounded so a runaway
    /// server cannot pin the worker).
    pub(crate) fn list_reels(&self) -> Result<Vec<JobDto>, ApiFailure> {
        let mut jobs = Vec::new();
        for page in 0..MAX_LIBRARY_PAGES {
            let offset = page * LIBRARY_PAGE_SIZE;
            let data: JobListData =
                self.get(&format!("/jobs?limit={LIBRARY_PAGE_SIZE}&offset={offset}"))?;
            let fetched = data.jobs.len();
            jobs.extend(data.jobs);
            if fetched < LIBRARY_PAGE_SIZE {
                break;
            }
        }
        Ok(jobs)
    }

    /// Soft-delete a finished reel and its stored media (`DELETE /jobs/{id}`).
    /// The server refuses (409) while the reel is still rendering.
    pub(crate) fn delete_reel(&self, job_id: &str) -> Result<(), ApiFailure> {
        let _deleted: serde_json::Value = self.delete(&format!("/jobs/{job_id}"))?;
        Ok(())
    }

    /// Publish a finished reel through the studio surface (`POST /jobs/{id}/publish`).
    /// The launch `publishing` gate is enforced server-side (403 when disabled),
    /// surfaced to the UI as an operation failure. Idempotent so a retried publish
    /// after an ambiguous response never double-posts.
    pub(crate) fn publish_reel(
        &self,
        job_id: &str,
        idempotency_key: &str,
    ) -> Result<PublishResult, ApiFailure> {
        self.post_idempotent(
            &format!("/jobs/{job_id}/publish"),
            &serde_json::json!({}),
            idempotency_key,
        )
    }
}
