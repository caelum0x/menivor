//! UI-owned snapshots for the generation workspace.

//! This module has no I/O: worker messages are reduced on the GPUI thread and
//! cause one inexpensive render notification.

use crate::api::{
    CatalogEntry, Credits, GenerationDetail, MediaIdentityOption, MediaModel, UsageRow,
    WalletRecipient, WalletTransferResult,
};
use crate::config::{ConnectionState, GenerationCapabilities};
use crate::domain::{BrollDraft, JobKind, JobSnapshot, JobState, ReelDraft};
use crate::workspace::{EditorSourceAnalysis, WorkerUpdate};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct PendingWalletTransfer {
    #[serde(default = "legacy_pending_version")]
    pub version: u8,
    #[serde(default)]
    pub source_account_id: String,
    #[serde(default)]
    pub source_kind: String,
    #[serde(default)]
    pub source_label: String,
    #[serde(default)]
    pub challenge_id: String,
    #[serde(default)]
    pub challenge_expires_at: String,
    pub recipient_handle: String,
    pub amount_micros: u64,
    pub idempotency_key: String,
    #[serde(default = "legacy_pending_submitted")]
    pub submitted: bool,
}

fn legacy_pending_version() -> u8 {
    1
}
fn legacy_pending_submitted() -> bool {
    true
}

#[derive(Default)]
pub(crate) struct DesktopState {
    pub jobs: Vec<JobSnapshot>,
    pub selected_job_id: Option<String>,
    pub reel_draft: ReelDraft,
    pub broll_draft: BrollDraft,
    pub connection: ConnectionState,
    pub connection_error: String,
    pub operation_error: String,
    pub activity: String,
    pub capabilities: GenerationCapabilities,
    /// Reviewed reel pickers fetched from the API on connect (empty until then).
    pub reel_avatars: Vec<CatalogEntry>,
    pub reel_voices: Vec<CatalogEntry>,
    pub reel_caption_styles: Vec<CatalogEntry>,
    /// Human summary of the most recent studio publish (empty until published).
    pub publish_status: String,
    /// Media-gateway wallet balance (`None` until first fetched).
    pub media_credits: Option<Credits>,
    /// Media-gateway spend-by-model usage rows.
    pub media_usage: Vec<UsageRow>,
    /// Durable owner-scoped media history, newest first.
    pub media_generations: Vec<GenerationDetail>,
    /// Older generations exist beyond the rows loaded so far.
    pub media_generations_has_more: bool,
    /// Jobs recovered from the desktop-local atomic runtime snapshot.
    pub local_generations: Vec<GenerationDetail>,
    pub local_runtime_ready: bool,
    pub local_runtime_error: String,
    pub local_execution_activity: String,
    pub local_execution_failed: bool,
    pub media_toolchain_ready: bool,
    pub media_toolchain_status: String,
    pub wallet_recipient: Option<WalletRecipient>,
    pub wallet_sources: Vec<crate::api::WalletSource>,
    pub selected_wallet_source_id: String,
    /// Mint-authoritative balance for `selected_wallet_source_id` only.
    pub wallet_source_balance: Option<Credits>,
    pub wallet_source_balance_id: String,
    pub wallet_receive_address: String,
    pub wallet_receive_address_source_id: String,
    pub wallet_transfer_challenge: Option<crate::api::WalletTransferChallenge>,
    pub wallet_saved_recipients: Vec<crate::api::WalletSavedRecipient>,
    pub selected_wallet_saved_recipient_id: String,
    pub wallet_transfer: Option<WalletTransferResult>,
    /// Durable logical send retained across unknown outcomes and app restarts.
    pub pending_wallet_transfer: Option<PendingWalletTransfer>,
    /// Signed URL of the most recent media-gateway image (empty until generated).
    pub media_image_url: String,
    /// Charged cost (integer micros) of the most recent image.
    pub media_image_cost: Option<u64>,
    /// The latest async media-video job and output.
    pub media_video_id: String,
    pub media_video_status: String,
    pub media_video_url: String,
    pub media_video_cost: Option<u64>,
    /// The latest async music/audio job and output.
    pub media_audio_id: String,
    pub media_audio_status: String,
    pub media_audio_url: String,
    pub media_audio_cost: Option<u64>,
    /// The unified media-gateway model catalog (empty until first fetched).
    pub media_models: Vec<MediaModel>,
    pub media_identities: Vec<MediaIdentityOption>,
    /// The most recent looked-up per-generation detail.
    pub media_generation: Option<GenerationDetail>,
    pub provenance_export_path: String,
    /// Most recently accepted server-side non-destructive edit job.
    pub editor_export_job_id: String,
    pub editor_source_job_id: String,
    pub editor_output_duration_ms: u64,
    pub editor_source_request_id: String,
    pub editor_source_analysis: Option<EditorSourceAnalysis>,
    pub editor_source_activity: String,
    pub update_status: String,
    pub update_available: bool,
    pub update_staged: bool,
}

impl DesktopState {
    pub(crate) fn apply(&mut self, update: WorkerUpdate) {
        match update {
            WorkerUpdate::ConfigurationLoaded { .. } => {}
            WorkerUpdate::WorkspaceRestored(cache) => cache.restore(self),
            WorkerUpdate::Disconnected => {
                self.connection = ConnectionState::Disconnected;
                self.connection_error.clear();
                self.capabilities = GenerationCapabilities::default();
                self.jobs.clear();
                self.selected_job_id = None;
                self.reel_avatars.clear();
                self.reel_voices.clear();
                self.reel_caption_styles.clear();
                self.publish_status.clear();
            }
            WorkerUpdate::ConnectionChecking => {
                self.connection = ConnectionState::Checking;
                self.connection_error.clear();
            }
            WorkerUpdate::Connected => {
                self.connection = ConnectionState::Connected;
                self.connection_error.clear();
                self.operation_error.clear();
            }
            WorkerUpdate::UpdateChecking { channel } => {
                self.update_status = format!("Checking the {channel} update channel…");
                self.update_available = false;
            }
            WorkerUpdate::UpdateAvailable {
                channel,
                version,
                notes_url,
                size_bytes,
            } => {
                self.update_status = format!(
                    "Menivor {version} is available on {channel} · {:.1} MiB · {notes_url}",
                    size_bytes as f64 / (1024.0 * 1024.0)
                );
                self.update_available = true;
                self.update_staged = false;
            }
            WorkerUpdate::UpdateCurrent { channel, version } => {
                self.update_status =
                    format!("Menivor {version} is current on the {channel} channel.");
                self.update_available = false;
            }
            WorkerUpdate::UpdateDownloadStarted { version } => {
                self.update_status = format!("Downloading and verifying Menivor {version}…");
            }
            WorkerUpdate::UpdateStaged { version, artifact } => {
                self.update_status =
                    format!("Menivor {version} verified and staged as {artifact}.");
                self.update_available = false;
                self.update_staged = true;
            }
            WorkerUpdate::UpdateInstallerLaunched { version } => {
                self.update_status = format!("Opened the verified Menivor {version} installer.");
            }
            WorkerUpdate::UpdateFailed { operation, message } => {
                self.update_status = format!("Could not {operation}: {message}");
            }
            WorkerUpdate::Capabilities { mode, reels, broll } => {
                self.capabilities = GenerationCapabilities {
                    loaded: true,
                    mode,
                    reels,
                    broll,
                };
            }
            WorkerUpdate::ReelCatalog {
                avatars,
                voices,
                caption_styles,
            } => {
                self.reel_avatars = avatars;
                self.reel_voices = voices;
                self.reel_caption_styles = caption_styles;
            }
            WorkerUpdate::ReelDeleted { job_id } => {
                self.jobs.retain(|job| job.id != job_id);
                if self.selected_job_id.as_deref() == Some(job_id.as_str()) {
                    self.selected_job_id = None;
                }
                self.activity = format!("Deleted {job_id}");
                self.operation_error.clear();
            }
            WorkerUpdate::ReelPublished { job_id, summary } => {
                self.publish_status = format!("Published {job_id}: {summary}");
                self.activity = format!("Published {job_id}");
                self.operation_error.clear();
            }
            WorkerUpdate::ConnectionFailed(failure) => {
                self.connection = ConnectionState::Failed;
                self.connection_error = failure.message;
                self.capabilities = GenerationCapabilities::default();
            }
            WorkerUpdate::MediaWallet {
                credits,
                usage,
                generations,
                generations_has_more,
            } => {
                self.media_credits = Some(credits);
                self.media_usage = usage;
                self.media_generations = generations;
                self.media_generations_has_more = generations_has_more;
                self.operation_error.clear();
            }
            WorkerUpdate::MediaGenerationsPage {
                offset,
                generations,
                has_more,
            } => {
                // Ignore a stale page when the timeline was refreshed meanwhile.
                if offset as usize == self.media_generations.len() {
                    let known: std::collections::HashSet<String> = self
                        .media_generations
                        .iter()
                        .map(|generation| generation.id.clone())
                        .collect();
                    self.media_generations.extend(
                        generations
                            .into_iter()
                            .filter(|generation| !known.contains(&generation.id)),
                    );
                    self.media_generations_has_more = has_more;
                }
                self.activity.clear();
                self.operation_error.clear();
            }
            WorkerUpdate::MediaToolchainInspected { ready, message } => {
                self.media_toolchain_ready = ready;
                self.media_toolchain_status = message;
            }
            WorkerUpdate::LocalRuntimeRestored { generations } => {
                self.local_generations = generations;
                self.local_runtime_ready = true;
                self.local_runtime_error.clear();
                self.local_execution_activity = "Local executor ready".into();
                self.local_execution_failed = false;
            }
            WorkerUpdate::LocalRuntimeFailed { message } => {
                self.local_generations.clear();
                self.local_runtime_ready = false;
                self.local_runtime_error = message;
                self.local_execution_activity.clear();
                self.local_execution_failed = true;
            }
            WorkerUpdate::LocalRuntimeUpdated {
                generations,
                message,
                failed,
            } => {
                self.local_generations = generations;
                self.local_runtime_ready = true;
                self.local_runtime_error.clear();
                self.local_execution_activity = message;
                self.local_execution_failed = failed;
            }
            WorkerUpdate::EditorSourceAnalyzed(analysis) => {
                if analysis.request_id == self.editor_source_request_id {
                    self.editor_source_activity = format!(
                        "Analyzed {} · {:.3}s",
                        analysis.display_name,
                        analysis.duration_ms as f64 / 1000.0
                    );
                    self.editor_source_analysis = Some(analysis);
                    self.operation_error.clear();
                }
            }
            WorkerUpdate::EditorSourceAnalysisFailed {
                request_id,
                message,
            } => {
                if request_id == self.editor_source_request_id {
                    self.editor_source_analysis = None;
                    self.editor_source_activity.clear();
                    self.operation_error = format!("Could not analyze editor source: {message}");
                }
            }
            WorkerUpdate::WalletRecipientResolved(recipient) => {
                self.wallet_recipient = Some(recipient);
                self.wallet_transfer = None;
                self.activity.clear();
                self.operation_error.clear();
            }
            WorkerUpdate::WalletSources(sources) => {
                if self.selected_wallet_source_id.is_empty() {
                    let restored = self.pending_wallet_transfer.as_ref().and_then(|pending| {
                        if pending.version == 2 {
                            sources.iter().find(|source| {
                                source.source_account_id == pending.source_account_id
                            })
                        } else {
                            sources.iter().find(|source| source.kind == "personal")
                        }
                    });
                    self.selected_wallet_source_id = restored
                        .or_else(|| sources.iter().find(|source| source.can_send))
                        .map(|source| source.source_account_id.clone())
                        .unwrap_or_default();
                }
                self.wallet_sources = sources;
            }
            WorkerUpdate::WalletSourceBalance {
                source_account_id,
                balance,
            } => {
                // A slow response from a previously selected source must never
                // overwrite the balance bound to the current transfer form.
                if source_account_id == self.selected_wallet_source_id {
                    self.wallet_source_balance_id = source_account_id;
                    self.wallet_source_balance = Some(balance);
                    self.operation_error.clear();
                }
            }
            WorkerUpdate::WalletReceiveAddress(receive) => {
                if receive.source.source_account_id == self.selected_wallet_source_id {
                    self.wallet_receive_address_source_id = receive.source.source_account_id;
                    self.wallet_receive_address = receive.address;
                    self.operation_error.clear();
                }
            }
            WorkerUpdate::WalletTransferReviewed {
                challenge,
                idempotency_key,
                submitted,
            } => {
                self.selected_wallet_source_id = challenge.source.source_account_id.clone();
                self.pending_wallet_transfer = Some(PendingWalletTransfer {
                    version: 2,
                    source_account_id: challenge.source.source_account_id.clone(),
                    source_kind: challenge.source.kind.clone(),
                    source_label: challenge.source.label.clone(),
                    challenge_id: challenge.challenge_id.clone(),
                    challenge_expires_at: challenge.expires_at.clone(),
                    recipient_handle: challenge.recipient.handle.clone(),
                    amount_micros: challenge.amount_micros,
                    idempotency_key,
                    submitted,
                });
                self.wallet_transfer_challenge = Some(challenge);
                self.operation_error.clear();
            }
            WorkerUpdate::WalletSavedRecipients(recipients) => {
                self.wallet_saved_recipients = recipients
            }
            WorkerUpdate::WalletRecipientSaved(recipient) => {
                self.wallet_saved_recipients.push(recipient)
            }
            WorkerUpdate::WalletRecipientDeleted(id) => self
                .wallet_saved_recipients
                .retain(|value| value.saved_recipient_id != id),
            WorkerUpdate::WalletTransferComplete(transfer) => {
                if let Some(balance) = transfer.sender_balance.as_ref() {
                    if transfer.source.kind == "personal" {
                        if let Some(credits) = self.media_credits.as_mut() {
                            credits.available_micros = balance.available_micros;
                            credits.reserved_micros = balance.held_micros;
                        }
                    }
                    if transfer.source.source_account_id == self.selected_wallet_source_id {
                        if let Some(credits) = self.wallet_source_balance.as_mut() {
                            credits.available_micros = balance.available_micros;
                            credits.reserved_micros = balance.held_micros;
                        }
                    }
                }
                let resolves_pending =
                    self.pending_wallet_transfer
                        .as_ref()
                        .is_some_and(|pending| {
                            rf_gateway::wallet_destinations_equal(
                                &pending.recipient_handle,
                                &transfer.recipient.handle,
                            ) && pending.amount_micros == transfer.amount_micros
                                && if pending.version == 2 {
                                    pending.source_account_id == transfer.source.source_account_id
                                } else {
                                    transfer.source.kind == "personal"
                                }
                        });
                self.wallet_transfer = Some(transfer);
                if resolves_pending {
                    self.pending_wallet_transfer = None;
                }
                self.wallet_recipient = None;
                self.wallet_transfer_challenge = None;
                self.activity.clear();
                self.operation_error.clear();
            }
            WorkerUpdate::WalletTransferRejected(failure) => {
                self.pending_wallet_transfer = None;
                self.activity.clear();
                self.operation_error = format!("send AI tokens: {}", failure.message);
            }
            WorkerUpdate::MediaImageComplete { url, cost_micros } => {
                self.media_image_url = url;
                self.media_image_cost = Some(cost_micros);
                self.activity.clear();
                self.operation_error.clear();
            }
            WorkerUpdate::MediaVideoQueued { id, cost_micros } => {
                self.media_video_id = id;
                self.media_video_status = "queued".into();
                self.media_video_url.clear();
                self.media_video_cost = Some(cost_micros);
                self.activity = "Video queued".into();
                self.operation_error.clear();
            }
            WorkerUpdate::MediaVideoProgress { id, status } => {
                self.media_video_id = id;
                self.media_video_status = status;
                self.activity = "Generating video…".into();
                self.operation_error.clear();
            }
            WorkerUpdate::MediaVideoComplete {
                id,
                url,
                cost_micros,
            } => {
                self.media_video_id = id;
                self.media_video_status = "completed".into();
                self.media_video_url = url;
                self.media_video_cost = Some(cost_micros);
                self.activity.clear();
                self.operation_error.clear();
            }
            WorkerUpdate::MediaAudioQueued { id, cost_micros } => {
                self.media_audio_id = id;
                self.media_audio_status = "queued".into();
                self.media_audio_url.clear();
                self.media_audio_cost = Some(cost_micros);
                self.activity = "Music queued".into();
                self.operation_error.clear();
            }
            WorkerUpdate::MediaAudioProgress { id, status } => {
                self.media_audio_id = id;
                self.media_audio_status = status;
                self.activity = "Generating music…".into();
                self.operation_error.clear();
            }
            WorkerUpdate::MediaAudioComplete {
                id,
                url,
                cost_micros,
            } => {
                self.media_audio_id = id;
                self.media_audio_status = "completed".into();
                self.media_audio_url = url;
                self.media_audio_cost = Some(cost_micros);
                self.activity.clear();
                self.operation_error.clear();
            }
            WorkerUpdate::MediaModels(models) => {
                self.media_models = models;
                self.operation_error.clear();
            }
            WorkerUpdate::MediaIdentities(identities) => {
                self.media_identities = identities;
                self.operation_error.clear();
            }
            WorkerUpdate::GenerationDetailLoaded(detail) => {
                self.media_generation = Some(detail);
                self.activity.clear();
                self.operation_error.clear();
            }
            WorkerUpdate::ProvenanceExported {
                generation_id,
                path,
            } => {
                self.provenance_export_path = path.display().to_string();
                self.activity = format!("Exported provenance for {generation_id}");
                self.operation_error.clear();
            }
            WorkerUpdate::Library(jobs) => {
                self.jobs = jobs;
                if self
                    .selected_job_id
                    .as_ref()
                    .is_some_and(|id| !self.jobs.iter().any(|job| &job.id == id))
                {
                    self.selected_job_id = None;
                }
                self.activity.clear();
            }
            WorkerUpdate::UploadStarted(target) => {
                self.activity = match target {
                    crate::workspace::UploadTarget::ReelRecording => {
                        "Uploading screen recording…".into()
                    }
                    crate::workspace::UploadTarget::BrollReference => {
                        "Uploading B-roll reference image…".into()
                    }
                };
                self.operation_error.clear();
            }
            WorkerUpdate::UploadComplete { target, key } => {
                match target {
                    crate::workspace::UploadTarget::ReelRecording => {
                        self.reel_draft.screen_recording_key = key;
                    }
                    crate::workspace::UploadTarget::BrollReference => {
                        self.broll_draft.image_key = key;
                    }
                }
                self.activity = "Upload ready".into();
            }
            WorkerUpdate::ResultSaved { path } => {
                self.activity = format!("Saved to {path}");
                self.operation_error.clear();
            }
            WorkerUpdate::ResultSaveFailed { message } => {
                self.activity.clear();
                self.operation_error = format!("save to disk: {message}");
            }
            WorkerUpdate::EditorOpened { message } => {
                self.activity = message;
                self.operation_error.clear();
            }
            WorkerUpdate::EditorOpenFailed { message } => {
                self.activity.clear();
                self.operation_error = format!("open in editor: {message}");
            }
            WorkerUpdate::OperationFailed { operation, failure } => {
                self.activity.clear();
                self.operation_error = format!("{operation}: {}", failure.message);
            }
            WorkerUpdate::Queued {
                id,
                kind,
                correlation_id,
            } => {
                self.activity = format!("{} queued", kind.label());
                self.upsert(
                    id,
                    kind,
                    JobState::Queued,
                    0,
                    "",
                    "",
                    "",
                    false,
                    "",
                    &correlation_id,
                )
            }
            WorkerUpdate::TimelineExportQueued {
                id,
                source_job_id,
                output_duration_ms,
                segments,
                overlays,
                correlation_id,
            } => {
                self.editor_export_job_id = id.clone();
                self.editor_source_job_id = source_job_id;
                self.editor_output_duration_ms = output_duration_ms;
                self.activity = format!(
                    "Timeline export queued · {segments} segment(s) · {overlays} overlay(s)"
                );
                self.operation_error.clear();
                self.upsert(
                    id,
                    JobKind::Reel,
                    JobState::Queued,
                    0,
                    "",
                    "",
                    "",
                    false,
                    "",
                    &correlation_id,
                );
            }
            WorkerUpdate::Progress {
                id,
                kind,
                progress,
                correlation_id,
            } => self.upsert(
                id,
                kind,
                JobState::Running,
                progress.clamp(0, 100),
                "",
                "",
                "",
                false,
                "",
                &correlation_id,
            ),
            WorkerUpdate::Complete {
                id,
                kind,
                result_url,
                result_key,
                correlation_id,
            } => self.upsert(
                id,
                kind,
                JobState::Complete,
                100,
                &result_url,
                &result_key,
                "",
                false,
                "",
                &correlation_id,
            ),
            WorkerUpdate::Failed {
                id,
                kind,
                message,
                retry_eligible,
                correlation_id,
            } => self.upsert(
                id,
                kind,
                JobState::Failed,
                0,
                "",
                "",
                &message,
                retry_eligible,
                "",
                &correlation_id,
            ),
        }
    }

    pub(crate) fn select_job(&mut self, id: impl Into<String>) {
        self.selected_job_id = Some(id.into());
    }

    pub(crate) fn selected_job(&self) -> Option<&JobSnapshot> {
        self.selected_job_id
            .as_ref()
            .and_then(|id| self.jobs.iter().find(|job| &job.id == id))
    }

    /// Attaching is deliberately restricted to completed B-roll. A reel request
    /// can therefore never reference a job still being generated or one owned
    /// by a failed provider run.
    pub(crate) fn attach_selected_broll(&mut self) -> bool {
        let Some(job) = self.selected_job() else {
            return false;
        };
        if job.kind != JobKind::Broll || job.state != JobState::Complete {
            return false;
        }
        if job.result_key.is_empty() {
            return false;
        }
        self.reel_draft.attached_broll_key = Some(job.result_key.clone());
        true
    }

    fn upsert(
        &mut self,
        id: String,
        kind: JobKind,
        state: JobState,
        progress: i32,
        result_url: &str,
        result_key: &str,
        error: &str,
        retry_eligible: bool,
        created_at: &str,
        correlation_id: &str,
    ) {
        if let Some(job) = self.jobs.iter_mut().find(|job| job.id == id) {
            job.kind = kind;
            job.state = state;
            job.progress = progress;
            if !result_url.is_empty() {
                job.result_url = result_url.into();
            }
            if !result_key.is_empty() {
                job.result_key = result_key.into();
            }
            if !error.is_empty() {
                job.error = error.into();
            }
            job.retry_eligible = retry_eligible;
            if !created_at.is_empty() {
                job.created_at = created_at.into();
            }
            if !correlation_id.is_empty() {
                job.correlation_id = correlation_id.into();
            }
            return;
        }
        self.jobs.insert(
            0,
            JobSnapshot {
                id,
                kind,
                progress,
                state,
                result_url: result_url.into(),
                result_key: result_key.into(),
                error: error.into(),
                retry_eligible,
                created_at: created_at.into(),
                correlation_id: correlation_id.into(),
            },
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn worker_updates_drive_terminal_job_state() {
        let mut state = DesktopState::default();
        state.apply(WorkerUpdate::Queued {
            id: "job-1".into(),
            kind: JobKind::Broll,
            correlation_id: "request-1".into(),
        });
        state.apply(WorkerUpdate::Progress {
            id: "job-1".into(),
            kind: JobKind::Broll,
            progress: 52,
            correlation_id: "request-1".into(),
        });
        state.apply(WorkerUpdate::Complete {
            id: "job-1".into(),
            kind: JobKind::Broll,
            result_url: "https://result".into(),
            result_key: "broll/job-1.mp4".into(),
            correlation_id: "request-1".into(),
        });
        assert_eq!(state.jobs[0].state, JobState::Complete);
        assert_eq!(state.jobs[0].progress, 100);
        assert_eq!(state.jobs[0].result_url, "https://result");
        assert_eq!(state.jobs[0].kind, JobKind::Broll);
    }

    #[test]
    fn timeline_acceptance_tracks_export_and_inserts_pollable_job() {
        let mut state = DesktopState::default();
        state.apply(WorkerUpdate::TimelineExportQueued {
            id: "edit-1".into(),
            source_job_id: "reel-1".into(),
            output_duration_ms: 7_500,
            segments: 1,
            overlays: 1,
            correlation_id: "request-edit-1".into(),
        });

        assert_eq!(state.editor_export_job_id, "edit-1");
        assert_eq!(state.editor_source_job_id, "reel-1");
        assert_eq!(state.editor_output_duration_ms, 7_500);
        assert_eq!(state.jobs[0].id, "edit-1");
        assert_eq!(state.jobs[0].state, JobState::Queued);
        assert!(state.activity.contains("1 segment"));
    }

    #[test]
    fn late_editor_source_analysis_cannot_replace_the_current_selection() {
        let analysis = |request_id: &str, name: &str| EditorSourceAnalysis {
            request_id: request_id.into(),
            path: std::path::PathBuf::from(format!("/{name}.mp4")),
            display_name: format!("{name}.mp4"),
            duration_ms: 2_000,
            waveform: vec![0, 500, 1000],
            source_sha256: format!("sha256:{name}"),
        };
        let mut state = DesktopState {
            editor_source_request_id: "new".into(),
            editor_source_activity: "Analyzing local source…".into(),
            ..DesktopState::default()
        };

        state.apply(WorkerUpdate::EditorSourceAnalyzed(analysis("old", "stale")));
        assert!(state.editor_source_analysis.is_none());
        assert_eq!(state.editor_source_activity, "Analyzing local source…");

        state.apply(WorkerUpdate::EditorSourceAnalyzed(analysis(
            "new", "current",
        )));
        assert_eq!(
            state.editor_source_analysis.as_ref().unwrap().display_name,
            "current.mp4"
        );
        assert!(state.editor_source_activity.contains("2.000s"));

        state.apply(WorkerUpdate::EditorSourceAnalysisFailed {
            request_id: "old".into(),
            message: "late failure".into(),
        });
        assert_eq!(
            state.editor_source_analysis.as_ref().unwrap().display_name,
            "current.mp4"
        );
    }

    #[test]
    fn local_runtime_updates_replace_history_and_surface_failure_truthfully() {
        let mut state = DesktopState::default();
        state.apply(WorkerUpdate::LocalRuntimeUpdated {
            generations: Vec::new(),
            message: "ffmpeg-local-v1 failed: ffmpeg exited with status 1".into(),
            failed: true,
        });
        assert!(state.local_runtime_ready);
        assert!(state.local_execution_failed);
        assert!(state.local_execution_activity.contains("ffmpeg exited"));
        assert!(state.local_runtime_error.is_empty());
    }

    #[test]
    fn update_state_requires_verified_staging_before_install_surface() {
        let mut state = DesktopState::default();
        state.apply(WorkerUpdate::UpdateChecking {
            channel: crate::updater::ReleaseChannel::Stable,
        });
        assert!(!state.update_available);
        assert!(!state.update_staged);

        state.apply(WorkerUpdate::UpdateAvailable {
            channel: crate::updater::ReleaseChannel::Stable,
            version: "1.2.3".into(),
            notes_url: "https://updates.example/1.2.3".into(),
            size_bytes: 4 * 1024 * 1024,
        });
        assert!(state.update_available);
        assert!(!state.update_staged);
        assert!(state.update_status.contains("1.2.3"));

        state.apply(WorkerUpdate::UpdateDownloadStarted {
            version: "1.2.3".into(),
        });
        assert!(state.update_status.contains("verifying"));
        state.apply(WorkerUpdate::UpdateStaged {
            version: "1.2.3".into(),
            artifact: "menivor-linux-x86_64.appimage".into(),
        });
        assert!(!state.update_available);
        assert!(state.update_staged);
        assert!(state.update_status.contains("verified and staged"));
    }

    #[test]
    fn only_completed_broll_can_be_attached_to_a_reel() {
        let mut state = DesktopState::default();
        state.apply(WorkerUpdate::Complete {
            id: "broll-1".into(),
            kind: JobKind::Broll,
            result_url: "https://result".into(),
            result_key: "broll/broll-1.mp4".into(),
            correlation_id: "request-2".into(),
        });
        state.select_job("broll-1");
        assert!(state.attach_selected_broll());
        assert_eq!(
            state.reel_draft.attached_broll_key.as_deref(),
            Some("broll/broll-1.mp4")
        );
    }

    #[test]
    fn definitive_transfer_clears_only_the_persisted_logical_send() {
        let mut state = DesktopState {
            pending_wallet_transfer: Some(PendingWalletTransfer {
                version: 1,
                source_account_id: String::new(),
                source_kind: String::new(),
                source_label: String::new(),
                challenge_id: String::new(),
                challenge_expires_at: String::new(),
                recipient_handle: "bob".into(),
                amount_micros: 2_000_000,
                idempotency_key: "desktop-transfer-one".into(),
                submitted: true,
            }),
            ..DesktopState::default()
        };
        let transfer: WalletTransferResult = serde_json::from_value(serde_json::json!({
            "transfer_id": "tr_1",
            "source": {"source_account_id": "personal_1", "kind": "personal", "label": "Personal"},
            "recipient": {"handle": "bob"},
            "amount_micros": 2_000_000,
            "amount_usd": "2.00",
            "status": "completed",
            "mint_first_seq": 7,
            "idempotent_replay": false,
            "created_at": null,
            "completed_at": null,
            "receipt_proof": null
        }))
        .unwrap();

        state.apply(WorkerUpdate::WalletTransferComplete(transfer));

        assert!(state.pending_wallet_transfer.is_none());
        assert_eq!(state.wallet_transfer.as_ref().unwrap().transfer_id, "tr_1");
    }

    #[test]
    fn unrelated_recovery_cannot_clear_an_unresolved_send() {
        let mut state = DesktopState {
            pending_wallet_transfer: Some(PendingWalletTransfer {
                version: 1,
                source_account_id: String::new(),
                source_kind: String::new(),
                source_label: String::new(),
                challenge_id: String::new(),
                challenge_expires_at: String::new(),
                recipient_handle: "bob".into(),
                amount_micros: 2_000_000,
                idempotency_key: "desktop-transfer-one".into(),
                submitted: true,
            }),
            ..DesktopState::default()
        };
        let recovered: WalletTransferResult = serde_json::from_value(serde_json::json!({
            "transfer_id": "tr_other",
            "recipient": {"handle": "alice"},
            "amount_micros": 3_000_000,
            "amount_usd": "3.00",
            "status": "completed",
            "mint_first_seq": 9,
            "receipt_proof": null
        }))
        .unwrap();

        state.apply(WorkerUpdate::WalletTransferComplete(recovered));

        assert_eq!(
            state
                .pending_wallet_transfer
                .as_ref()
                .map(|pending| pending.idempotency_key.as_str()),
            Some("desktop-transfer-one")
        );
    }

    #[test]
    fn definitive_client_rejection_unblocks_a_new_review() {
        let mut state = DesktopState {
            pending_wallet_transfer: Some(PendingWalletTransfer {
                version: 1,
                source_account_id: String::new(),
                source_kind: String::new(),
                source_label: String::new(),
                challenge_id: String::new(),
                challenge_expires_at: String::new(),
                recipient_handle: "bob".into(),
                amount_micros: 2_000_000,
                idempotency_key: "desktop-transfer-one".into(),
                submitted: true,
            }),
            ..DesktopState::default()
        };

        state.apply(WorkerUpdate::WalletTransferRejected(
            crate::api::ApiFailure {
                kind: crate::api::ApiFailureKind::Request,
                status: Some(422),
                message: "invalid transfer".into(),
            },
        ));

        assert!(state.pending_wallet_transfer.is_none());
        assert!(state.operation_error.contains("invalid transfer"));
    }

    #[test]
    fn reviewed_workspace_transfer_persists_full_v2_command() {
        let mut state = DesktopState::default();
        let challenge: crate::api::WalletTransferChallenge = serde_json::from_value(serde_json::json!({
            "challenge_id": "challenge_1",
            "source": {
                "source_account_id": "workspace_1", "kind": "workspace", "label": "Studio",
                "role": "owner", "can_send": true,
                "limits": {"per_transfer_micros": 10000000, "daily_micros": 20000000, "daily_used_micros": 0, "daily_remaining_micros": 20000000}
            },
            "recipient": {"handle": "bob", "display_name": "Bob"},
            "amount_micros": 2000000,
            "binding_sha256": "binding",
            "expires_at": "2026-08-28T23:59:00Z"
        })).unwrap();
        state.apply(WorkerUpdate::WalletTransferReviewed {
            challenge,
            idempotency_key: "stable-key".into(),
            submitted: true,
        });
        let pending = state.pending_wallet_transfer.unwrap();
        assert_eq!(pending.version, 2);
        assert_eq!(pending.source_account_id, "workspace_1");
        assert_eq!(pending.challenge_id, "challenge_1");
        assert_eq!(pending.idempotency_key, "stable-key");
        assert!(pending.submitted);
    }

    #[test]
    fn late_balance_from_an_old_source_cannot_replace_the_selected_balance() {
        let mut state = DesktopState {
            selected_wallet_source_id: "workspace_2".into(),
            ..DesktopState::default()
        };
        let balance = Credits {
            available_micros: 7_000_000,
            reserved_micros: 1_000_000,
            total_gateway_spend_micros: 0,
            currency: "usd".into(),
        };

        state.apply(WorkerUpdate::WalletSourceBalance {
            source_account_id: "workspace_1".into(),
            balance: balance.clone(),
        });
        assert!(state.wallet_source_balance.is_none());

        state.apply(WorkerUpdate::WalletSourceBalance {
            source_account_id: "workspace_2".into(),
            balance,
        });
        assert_eq!(state.wallet_source_balance_id, "workspace_2");
        assert_eq!(
            state
                .wallet_source_balance
                .as_ref()
                .map(|value| value.available_micros),
            Some(7_000_000)
        );
    }

    #[test]
    fn receive_address_is_bound_to_the_current_source() {
        let mut state = DesktopState {
            selected_wallet_source_id: "workspace_2".into(),
            ..DesktopState::default()
        };
        let receive = |source_account_id: &str, address: &str| {
            WorkerUpdate::WalletReceiveAddress(crate::api::WalletReceiveAddress {
                address: address.into(),
                source: crate::api::WalletSource {
                    source_account_id: source_account_id.into(),
                    kind: "workspace".into(),
                    label: "Studio".into(),
                    ..crate::api::WalletSource::default()
                },
            })
        };

        state.apply(receive("workspace_1", "ait1qold"));
        assert!(state.wallet_receive_address.is_empty());

        state.apply(receive("workspace_2", "ait1qcurrent"));
        assert_eq!(state.wallet_receive_address, "ait1qcurrent");
        assert_eq!(state.wallet_receive_address_source_id, "workspace_2");
    }

    #[test]
    fn workspace_transfer_updates_only_its_source_balance() {
        let mut state = DesktopState {
            selected_wallet_source_id: "workspace_1".into(),
            wallet_source_balance_id: "workspace_1".into(),
            wallet_source_balance: Some(Credits {
                available_micros: 20_000_000,
                reserved_micros: 0,
                total_gateway_spend_micros: 0,
                currency: "usd".into(),
            }),
            media_credits: Some(Credits {
                available_micros: 3_000_000,
                reserved_micros: 0,
                total_gateway_spend_micros: 0,
                currency: "usd".into(),
            }),
            ..DesktopState::default()
        };
        let transfer: WalletTransferResult = serde_json::from_value(serde_json::json!({
            "transfer_id": "tr_workspace",
            "source": {"source_account_id": "workspace_1", "kind": "workspace", "label": "Studio"},
            "recipient": {"handle": "bob"},
            "amount_micros": 2_000_000,
            "amount_usd": "2.00",
            "status": "completed",
            "mint_first_seq": 7,
            "sender_balance": {"available_micros": 18_000_000, "held_micros": 0},
            "receipt_proof": null
        }))
        .unwrap();

        state.apply(WorkerUpdate::WalletTransferComplete(transfer));

        assert_eq!(
            state.media_credits.as_ref().unwrap().available_micros,
            3_000_000
        );
        assert_eq!(
            state
                .wallet_source_balance
                .as_ref()
                .unwrap()
                .available_micros,
            18_000_000
        );
    }

    #[test]
    fn local_runtime_bootstrap_status_is_independent_from_cloud_connection() {
        let mut state = DesktopState::default();
        state.apply(WorkerUpdate::LocalRuntimeFailed {
            message: "snapshot is corrupt".into(),
        });
        assert!(!state.local_runtime_ready);
        assert_eq!(state.local_runtime_error, "snapshot is corrupt");

        state.apply(WorkerUpdate::LocalRuntimeRestored {
            generations: Vec::new(),
        });
        assert!(state.local_runtime_ready);
        assert!(state.local_runtime_error.is_empty());
    }
}
