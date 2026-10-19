//! Reviewed Rust mappings of shared OpenAPI response and request schemas.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize)]
pub(crate) struct JobDto {
    pub job_id: String,
    #[serde(default)]
    pub kind: String,
    pub state: i32,
    #[serde(default)]
    pub progress: i32,
    #[serde(default)]
    pub result_url: String,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub retry_eligible: bool,
    #[serde(default)]
    pub poster_url: String,
    #[serde(default)]
    pub preview_url: String,
    #[serde(default)]
    pub cover_url: String,
    #[serde(default)]
    pub created_at: String,
    #[serde(default)]
    pub correlation_id: String,
    /// WolfCut `GeneratedClip` descriptor, attached by the API to a completed
    /// job the caller may view (`apps/api/app/services/generated_clip.py`).
    /// Kept as raw JSON: the shell forwards it to the editor unchanged.
    #[serde(default)]
    pub generated_clip: Option<serde_json::Value>,
}

#[derive(Clone, Debug, Deserialize)]
pub(crate) struct BrollGenerationDto {
    pub generation_id: String,
    pub state: i32,
    #[serde(default)]
    pub progress: i32,
    #[serde(default)]
    pub broll_key: String,
    #[serde(default)]
    pub result_url: String,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub retry_eligible: bool,
    #[serde(default)]
    pub correlation_id: String,
}

/// Immediate response from the timeline-export command. The resulting job is
/// polled through the canonical `/jobs/{id}` endpoint after it is queued.
#[derive(Clone, Debug, Deserialize, PartialEq)]
pub(crate) struct TimelineExportJobDto {
    pub job_id: String,
    pub state: i32,
    #[serde(default)]
    pub progress: i32,
    pub output_duration_s: f64,
    pub segments: usize,
    pub overlays: usize,
    #[serde(default)]
    pub correlation_id: String,
}

#[derive(Clone, Debug, Deserialize)]
pub(super) struct PilotCapabilitiesDto {
    pub mode: String,
    pub generation: GenerationCapabilitiesDto,
    #[serde(default)]
    pub product: serde_json::Value,
}

#[derive(Clone, Copy, Debug, Deserialize)]
pub(super) struct GenerationCapabilitiesDto {
    pub reels: bool,
    pub broll: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct UploadedObject {
    pub key: String,
    pub get_url: String,
}

#[derive(Debug, Deserialize)]
pub(super) struct Envelope<T> {
    pub data: T,
}

#[derive(Debug, Deserialize)]
pub(super) struct JobListData {
    #[serde(default)]
    pub jobs: Vec<JobDto>,
}

/// Studio publish acknowledgement (`POST /jobs/{id}/publish`). The exact payload
/// varies by provider fan-out, so every field is optional; a human summary is
/// derived from whichever fields the server returned.
#[derive(Clone, Debug, Deserialize)]
pub(crate) struct PublishResult {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub published_at: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub provider: String,
}

impl PublishResult {
    /// A short, display-safe summary of the publish outcome.
    pub(crate) fn summary(&self) -> String {
        for candidate in [&self.message, &self.url, &self.status] {
            let candidate = candidate.trim();
            if !candidate.is_empty() {
                return if self.provider.trim().is_empty() {
                    candidate.to_owned()
                } else {
                    format!("{} · {candidate}", self.provider.trim())
                };
            }
        }
        if !self.published_at.trim().is_empty() {
            format!("Published at {}", self.published_at.trim())
        } else {
            "Published".to_owned()
        }
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct PresignData {
    pub upload_url: String,
    pub get_url: String,
    pub key: String,
    #[serde(default)]
    pub headers: HashMap<String, String>,
}

#[derive(Debug, Serialize)]
pub(super) struct PresignInput<'a> {
    pub filename: &'a str,
    pub content_type: &'a str,
    pub size: u64,
}

#[derive(Debug, Serialize)]
pub(super) struct RegisterUploadInput<'a> {
    pub key: &'a str,
    pub kind: &'a str,
}

#[derive(Debug, Deserialize)]
pub(super) struct RegisteredUpload {
    pub key: String,
}

#[derive(Debug, Serialize)]
pub(super) struct ReelParams<'a> {
    pub video_subject: &'a str,
    #[serde(skip_serializing_if = "str::is_empty")]
    pub video_script: &'a str,
    pub voice_name: &'a str,
    pub avatar_id: &'a str,
    pub avatar_provider: &'static str,
    pub caption_style: &'a str,
    pub layout: &'a str,
    pub aspect: &'static str,
    pub language: &'a str,
    pub target_duration_s: u32,
    pub platforms: &'a [String],
    pub screen_recording_key: &'a str,
}

#[derive(Debug, Serialize)]
pub(super) struct ReelCreateInput<'a> {
    pub params: ReelParams<'a>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub broll_intro_key: Option<&'a str>,
}

#[derive(Debug, Serialize)]
pub(super) struct BrollCreateInput<'a> {
    pub prompt: &'a str,
    pub mode: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub image_key: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub workflow_id: Option<&'a str>,
}
