//! Canonical `/generation/broll/*` request operations.

use super::models::BrollCreateInput;
use super::{ApiClient, ApiFailure, BrollGenerationDto};
use crate::domain::{BrollDraft, BrollMode};

impl ApiClient {
    pub(crate) fn create_broll(
        &self,
        draft: &BrollDraft,
        idempotency_key: &str,
    ) -> Result<BrollGenerationDto, ApiFailure> {
        let mode = match draft.mode {
            BrollMode::TextToVideo => "t2v",
            BrollMode::ImageToVideo => "i2v",
        };
        self.post_idempotent(
            "/generation/broll/generate",
            &BrollCreateInput {
                prompt: draft.prompt.trim(),
                mode,
                image_key: non_empty(&draft.image_key),
                workflow_id: non_empty(&draft.workflow_id),
            },
            idempotency_key,
        )
    }

    pub(crate) fn get_broll(&self, id: &str) -> Result<BrollGenerationDto, ApiFailure> {
        self.get(&format!("/generation/broll/generations/{id}"))
    }

    pub(crate) fn list_broll(&self) -> Result<Vec<BrollGenerationDto>, ApiFailure> {
        self.get("/generation/broll/generations")
    }
}

fn non_empty(value: &str) -> Option<&str> {
    let value = value.trim();
    (!value.is_empty()).then_some(value)
}
