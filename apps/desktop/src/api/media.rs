//! Unified **media gateway** request operations (`/media/*`) — the desktop client
//! for the OpenRouter-style one-key/one-balance surface web + mobile already use.
//! Reuses the pure `rf-gateway` crate for the DTOs, request bodies, and cost/
//! pre-flight logic, so the desktop composes against the identical catalog + money
//! model as the cloud.

use rf_gateway::{
    audio_request, image_request, video_request, video_request_with_identity, Credits,
    GenerationDetail, GenerationPage, ImageResult, MediaIdentityOption, MediaModel,
    MediaProvenanceExport, UsageRow, VideoJob,
};
use serde::Deserialize;

use super::{ApiClient, ApiFailure};

/// Rows per page of the media generation timeline.
pub(crate) const MEDIA_HISTORY_PAGE: u64 = 24;

#[derive(Debug, Deserialize)]
struct ModelsData {
    #[serde(default)]
    models: Vec<MediaModel>,
}

#[derive(Debug, Deserialize)]
struct UsageData {
    #[serde(default)]
    usage: Vec<UsageRow>,
}

#[derive(Debug, Deserialize)]
struct IdentitiesData {
    #[serde(default)]
    identities: Vec<MediaIdentityOption>,
}

impl ApiClient {
    /// The unified catalog, optionally filtered to one modality (`image`/`video`/`audio`).
    pub(crate) fn list_media_models(
        &self,
        modality: Option<&str>,
    ) -> Result<Vec<MediaModel>, ApiFailure> {
        let path = match modality {
            Some(m) => format!("/media/models?modality={m}"),
            None => "/media/models".to_string(),
        };
        let data: ModelsData = self.get(&path)?;
        Ok(data.models)
    }

    /// Synchronous image generation (`POST /media/images`).
    pub(crate) fn create_media_image(
        &self,
        model: &str,
        prompt: &str,
    ) -> Result<ImageResult, ApiFailure> {
        self.post("/media/images", &image_request(model, prompt))
    }

    /// Submit an async video job (`POST /media/videos`); poll with [`get_media_video`].
    pub(crate) fn create_media_video(
        &self,
        model: &str,
        prompt: &str,
        duration: u32,
        aspect_ratio: &str,
        image_url: &str,
    ) -> Result<VideoJob, ApiFailure> {
        self.post(
            "/media/videos",
            &video_request(model, prompt, duration, aspect_ratio, image_url),
        )
    }

    /// Submit a video bound to an immutable Railyard Identity Lock passport.
    pub(crate) fn create_identity_media_video(
        &self,
        model: &str,
        prompt: &str,
        duration: u32,
        aspect_ratio: &str,
        image_url: &str,
        passport_id: &str,
        version: Option<u32>,
    ) -> Result<VideoJob, ApiFailure> {
        self.post(
            "/media/videos",
            &video_request_with_identity(
                model,
                prompt,
                duration,
                aspect_ratio,
                image_url,
                passport_id,
                version,
            ),
        )
    }

    pub(crate) fn get_media_video(&self, id: &str) -> Result<VideoJob, ApiFailure> {
        self.get(&format!("/media/videos/{id}"))
    }

    /// Submit an async audio/music job (`POST /media/audio`); poll with [`get_media_audio`].
    pub(crate) fn create_media_audio(
        &self,
        model: &str,
        prompt: &str,
        instrumental: bool,
    ) -> Result<VideoJob, ApiFailure> {
        self.post("/media/audio", &audio_request(model, prompt, instrumental))
    }

    pub(crate) fn get_media_audio(&self, id: &str) -> Result<VideoJob, ApiFailure> {
        self.get(&format!("/media/audio/{id}"))
    }

    /// Spendable credits + reserved hold + lifetime gateway spend (`GET /media/credits`).
    pub(crate) fn get_media_credits(&self) -> Result<Credits, ApiFailure> {
        self.get("/media/credits")
    }

    /// Spend + counts by model (`GET /media/usage`).
    pub(crate) fn get_media_usage(&self) -> Result<Vec<UsageRow>, ApiFailure> {
        let data: UsageData = self.get("/media/usage")?;
        Ok(data.usage)
    }

    /// Per-generation cost/status detail (`GET /media/generation/{id}`).
    pub(crate) fn get_media_generation(&self, id: &str) -> Result<GenerationDetail, ApiFailure> {
        self.get(&format!("/media/generation/{id}"))
    }

    /// Durable owner-scoped timeline; the backend also reconciles bounded pending work.
    pub(crate) fn list_media_generations(&self) -> Result<GenerationPage, ApiFailure> {
        self.get(&format!(
            "/media/generations?limit={MEDIA_HISTORY_PAGE}&refresh_pending=true"
        ))
    }

    /// An older page of the timeline (`offset` rows in). Older rows are already
    /// settled, so this never asks the backend to reconcile pending work.
    pub(crate) fn list_media_generations_page(
        &self,
        offset: u64,
    ) -> Result<GenerationPage, ApiFailure> {
        self.get(&format!(
            "/media/generations?limit={MEDIA_HISTORY_PAGE}&offset={offset}&refresh_pending=false"
        ))
    }

    pub(crate) fn list_media_identities(&self) -> Result<Vec<MediaIdentityOption>, ApiFailure> {
        let data: IdentitiesData = self.get("/media/identities")?;
        Ok(data.identities)
    }

    pub(crate) fn get_media_provenance(
        &self,
        id: &str,
    ) -> Result<MediaProvenanceExport, ApiFailure> {
        self.get(&format!("/media/generation/{id}/provenance"))
    }
}
