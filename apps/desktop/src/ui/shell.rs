use std::sync::{Arc, Mutex};
use std::time::Duration;

use gpui::{div, prelude::*, px, AsyncApp, Context, Entity, SharedString, WeakEntity, Window};

use crate::config::Preferences;
use crate::ui::components::TextField;
use crate::ui::editor::{EditorOverlayFields, EditorSegmentFields, PendingTimelineExport};
use crate::ui::growth::{library_trend_series, SignalFields, TREND_DAYS};
use crate::ui::theme::ActiveTheme;
use crate::updater::ReleaseChannel;
use crate::workspace::{
    start_worker, BrollMode, ConnectionState, DesktopState, JobKind, JobState, UploadTarget,
    WorkerCommand, WorkspaceCache,
};

/// Deterministic `t` sampling positions for the Effects kernel inspector. Shared
/// so the expanded keyframe table matches the labels the section advertises.
pub(super) const EFFECT_SAMPLE_POINTS: [f64; 5] = [0.0, 0.25, 0.5, 0.75, 1.0];

/// The native Menivor workspace. Network work reduces into `DesktopState`
/// on this view's thread; rendering reads only the resulting snapshots.
pub(crate) struct Shell {
    pub(super) section: WorkspaceSection,
    pub(super) state: DesktopState,
    pub(super) preferences: Preferences,
    pub(super) worker: std::sync::mpsc::Sender<WorkerCommand>,
    pub(super) api_base_field: Entity<TextField>,
    pub(super) api_key_field: Entity<TextField>,
    /// Optional WolfCut location override (Settings).
    pub(super) editor_path_field: Entity<TextField>,
    pub(super) reel_subject_field: Entity<TextField>,
    pub(super) reel_script_field: Entity<TextField>,
    pub(super) reel_avatar_field: Entity<TextField>,
    pub(super) reel_voice_field: Entity<TextField>,
    pub(super) broll_prompt_field: Entity<TextField>,
    pub(super) media_model_field: Entity<TextField>,
    pub(super) media_prompt_field: Entity<TextField>,
    pub(super) media_source_image_field: Entity<TextField>,
    pub(super) media_identity_passport_field: Entity<TextField>,
    pub(super) media_identity_version_field: Entity<TextField>,
    pub(super) media_generation_id_field: Entity<TextField>,
    pub(super) media_provenance_path_field: Entity<TextField>,
    pub(super) wallet_recipient_field: Entity<TextField>,
    pub(super) wallet_transfer_amount_field: Entity<TextField>,
    pub(super) wallet_transfer_id_field: Entity<TextField>,
    pub(super) editor_segments: Vec<EditorSegmentFields>,
    pub(super) editor_overlays: Vec<EditorOverlayFields>,
    /// Signals section inputs: measured hook signals and A/B variant results.
    pub(super) signal_fields: SignalFields,
    /// Effects section: the kernel whose deterministic keyframe samples are
    /// currently expanded (`None` = collapsed catalog).
    pub(super) selected_effect_kernel: Option<String>,
    pub(super) pending_reel_create: Option<(crate::domain::ReelDraft, String)>,
    pub(super) pending_broll_create: Option<(crate::domain::BrollDraft, String)>,
    pub(super) pending_timeline_export: Option<PendingTimelineExport>,
    /// The `.menivor` project file the editor timeline was opened from / saved to.
    pub(super) editor_project_path: Option<std::path::PathBuf>,
    /// Last editor-session JSON written to the autosave file (change detection).
    pub(super) editor_session_saved: String,
    /// Local freegen sidecar child process.  `None` when the local engine is
    /// disabled; present once the user enables it.
    pub(super) sidecar: crate::domain::LocalSidecar,
    /// Current sidecar status shown in the Settings status row.
    pub(super) sidecar_status: crate::domain::SidecarStatus,
}

/// Update-loop ticks (100 ms each) between editor-session autosave checks.
const EDITOR_AUTOSAVE_TICKS: u32 = 20;

#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum WorkspaceSection {
    Create,
    Library,
    Editor,
    MediaGateway,
    Governance,
    Trends,
    Signals,
    Captions,
    Blueprints,
    Effects,
    Workflows,
    Settings,
}

impl Shell {
    pub(crate) fn new(cx: &mut Context<Self>) -> Self {
        let channels = start_worker();
        let _ = channels.commands.send(WorkerCommand::LoadConfiguration);
        let _ = channels.commands.send(WorkerCommand::LoadWorkspace);
        let updates = Arc::new(Mutex::new(channels.updates));
        let updates_for_task = Arc::clone(&updates);
        cx.spawn(async move |this: WeakEntity<Self>, cx: &mut AsyncApp| {
            let mut ticks: u32 = 0;
            loop {
                cx.background_executor()
                    .timer(Duration::from_millis(100))
                    .await;
                ticks = ticks.wrapping_add(1);
                let autosave_due = ticks % EDITOR_AUTOSAVE_TICKS == 0;
                let app_requests = crate::app_requests::drain();
                let mut batch = Vec::new();
                if let Ok(receiver) = updates_for_task.lock() {
                    while let Ok(update) = receiver.try_recv() {
                        batch.push(update);
                    }
                }
                if batch.is_empty() && app_requests.is_empty() && !autosave_due {
                    continue;
                }
                if this
                    .update(cx, |shell, cx: &mut Context<Shell>| {
                        for request in app_requests {
                            shell.handle_app_request(request, cx);
                        }
                        if autosave_due {
                            shell.autosave_editor_session(cx);
                        }
                        if batch.is_empty() {
                            return;
                        }
                        for update in batch {
                            let restored = matches!(
                                &update,
                                crate::workspace::WorkerUpdate::WorkspaceRestored(_)
                            );
                            if let crate::workspace::WorkerUpdate::ConfigurationLoaded {
                                api_base,
                                editor_path,
                                use_local_engine,
                            } = &update
                            {
                                shell.preferences = Preferences {
                                    api_base_url: api_base.clone(),
                                    editor_path: editor_path.clone(),
                                    use_local_engine: *use_local_engine,
                                };
                                shell
                                    .api_base_field
                                    .update(cx, |field, cx| field.set_text(api_base.clone(), cx));
                                shell.editor_path_field.update(cx, |field, cx| {
                                    field.set_text(editor_path.clone(), cx)
                                });
                                if *use_local_engine
                                    && shell.sidecar_status
                                        == crate::domain::SidecarStatus::Disabled
                                {
                                    shell.start_local_sidecar(cx);
                                }
                            }
                            if matches!(
                                &update,
                                crate::workspace::WorkerUpdate::Queued {
                                    kind: JobKind::Reel,
                                    ..
                                }
                            ) {
                                shell.pending_reel_create = None;
                            }
                            if matches!(
                                &update,
                                crate::workspace::WorkerUpdate::Queued {
                                    kind: JobKind::Broll,
                                    ..
                                }
                            ) {
                                shell.pending_broll_create = None;
                            }
                            if matches!(
                                &update,
                                crate::workspace::WorkerUpdate::TimelineExportQueued { .. }
                            ) {
                                shell.pending_timeline_export = None;
                            }
                            if let crate::workspace::WorkerUpdate::MediaImageComplete {
                                url, ..
                            } = &update
                            {
                                shell
                                    .media_source_image_field
                                    .update(cx, |field, cx| field.set_text(url.clone(), cx));
                            }
                            if let crate::workspace::WorkerUpdate::MediaModels(models) = &update {
                                let has_source = !shell
                                    .media_source_image_field
                                    .read(cx)
                                    .text()
                                    .trim()
                                    .is_empty();
                                if has_source {
                                    if let Some(model) = models
                                        .iter()
                                        .find(|model| model.id.to_ascii_lowercase().contains("i2v"))
                                    {
                                        shell.media_model_field.update(cx, |field, cx| {
                                            field.set_text(model.id.clone(), cx)
                                        });
                                    }
                                }
                            }
                            if let crate::workspace::WorkerUpdate::WalletTransferComplete(
                                transfer,
                            ) = &update
                            {
                                shell.wallet_transfer_id_field.update(cx, |field, cx| {
                                    field.set_text(transfer.transfer_id.clone(), cx)
                                });
                            }
                            let wallet_sources_updated =
                                matches!(&update, crate::workspace::WorkerUpdate::WalletSources(_));
                            shell.state.apply(update);
                            if wallet_sources_updated
                                && !shell.state.selected_wallet_source_id.is_empty()
                            {
                                let source_account_id =
                                    shell.state.selected_wallet_source_id.clone();
                                let _ =
                                    shell
                                        .worker
                                        .send(WorkerCommand::RefreshWalletSourceBalance {
                                            source_account_id: source_account_id.clone(),
                                        });
                                let _ = shell.worker.send(WorkerCommand::RefreshSavedRecipients {
                                    source_account_id,
                                });
                                let _ =
                                    shell
                                        .worker
                                        .send(WorkerCommand::RefreshWalletReceiveAddress {
                                            source_account_id: shell
                                                .state
                                                .selected_wallet_source_id
                                                .clone(),
                                        });
                            }
                            if restored {
                                shell.sync_form_fields(cx);
                            }
                        }
                        let _ = shell.worker.send(WorkerCommand::PersistWorkspace(
                            WorkspaceCache::snapshot(&shell.state),
                        ));
                        cx.notify();
                    })
                    .is_err()
                {
                    break;
                }
            }
        })
        .detach();

        let preferences = Preferences::default();
        let api_base_field = cx.new(|cx| {
            TextField::new(
                cx,
                preferences.normalized_api_base(),
                "https://api.menivor.com/api/v1",
                false,
            )
        });
        let api_key_field =
            cx.new(|cx| TextField::new(cx, "", "Paste API key (kept in OS keychain)", true));
        let editor_path_field = cx.new(|cx| {
            TextField::new(
                cx,
                "",
                "Editor location (optional, found automatically when installed)",
                false,
            )
        });
        let reel_subject_field =
            cx.new(|cx| TextField::new(cx, "", "What is this reel about?", false));
        let reel_script_field = cx.new(|cx| TextField::new(cx, "", "Optional script", false));
        let reel_avatar_field = cx.new(|cx| TextField::new(cx, "", "HeyGen avatar ID", false));
        let reel_voice_field =
            cx.new(|cx| TextField::new(cx, "", "Voice selector (elevenlabs:voice_id)", false));
        let broll_prompt_field =
            cx.new(|cx| TextField::new(cx, "", "Describe the shot and motion", false));
        let media_model_field =
            cx.new(|cx| TextField::new(cx, "black-forest-labs/flux-schnell", "Model id", false));
        let media_prompt_field = cx.new(|cx| TextField::new(cx, "", "Describe the image", false));
        let media_source_image_field = cx.new(|cx| {
            TextField::new(
                cx,
                "",
                "Source image URL (optional for text-to-video)",
                false,
            )
        });
        let media_generation_id_field =
            cx.new(|cx| TextField::new(cx, "", "Generation id to inspect", false));
        let media_identity_passport_field =
            cx.new(|cx| TextField::new(cx, "", "Locked passport id (optional)", false));
        let media_identity_version_field =
            cx.new(|cx| TextField::new(cx, "", "Exact passport version", false));
        let media_provenance_path_field =
            cx.new(|cx| TextField::new(cx, "", "/path/to/new-menivor-provenance.json", false));
        let wallet_recipient_field =
            cx.new(|cx| TextField::new(cx, "", "Handle or ait1 receive address", false));
        let wallet_transfer_amount_field =
            cx.new(|cx| TextField::new(cx, "5.00", "Amount in USD", false));
        let wallet_transfer_id_field =
            cx.new(|cx| TextField::new(cx, "", "Existing transfer ID to recover", false));
        let editor_segments = vec![EditorSegmentFields::new(cx, 0)];
        let editor_overlays = vec![EditorOverlayFields::new(cx)];
        let signal_fields = SignalFields::new(cx);
        let state = DesktopState::default();

        let mut shell = Self {
            section: WorkspaceSection::Create,
            state,
            preferences,
            worker: channels.commands,
            api_base_field,
            api_key_field,
            editor_path_field,
            reel_subject_field,
            reel_script_field,
            reel_avatar_field,
            reel_voice_field,
            broll_prompt_field,
            media_model_field,
            media_prompt_field,
            media_source_image_field,
            media_identity_passport_field,
            media_identity_version_field,
            media_generation_id_field,
            media_provenance_path_field,
            wallet_recipient_field,
            wallet_transfer_amount_field,
            wallet_transfer_id_field,
            editor_segments,
            editor_overlays,
            signal_fields,
            selected_effect_kernel: None,
            pending_reel_create: None,
            pending_broll_create: None,
            pending_timeline_export: None,
            editor_project_path: None,
            editor_session_saved: String::new(),
            sidecar: crate::domain::LocalSidecar::default(),
            sidecar_status: crate::domain::SidecarStatus::Disabled,
        };
        // Bring back the last editor timeline (autosaved), so quitting mid-edit
        // never loses work.
        shell.restore_editor_session(cx);
        shell
    }
}

impl Drop for Shell {
    fn drop(&mut self) {
        self.sidecar.stop();
        let _ = self.worker.send(WorkerCommand::Shutdown);
    }
}

impl Render for Shell {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let colors = window.theme().colors;
        let section = self.section;
        let selected = self.state.selected_job().cloned();
        let publish_status = self.state.publish_status.clone();
        let publishing_allowed = self.state.connection == ConnectionState::Connected;
        let trend_series = library_trend_series(&self.state.jobs);
        let hook_signals = self.signal_fields.hook_signals(cx);
        let ab_variants = self.signal_fields.variants(cx);
        let editor_source_label = selected
            .as_ref()
            .map(|job| {
                if job.kind == JobKind::Reel && job.state == JobState::Complete {
                    format!("Editing completed reel {}", job.id)
                } else {
                    format!("{} is not a completed reel", job.id)
                }
            })
            .unwrap_or_else(|| "Select a completed reel in the library above".to_string());
        let editor_local_source_summary = self
            .state
            .editor_source_analysis
            .as_ref()
            .map(|analysis| {
                format!(
                    "{} · {:.3}s · {}",
                    analysis.display_name,
                    analysis.duration_ms as f64 / 1000.0,
                    &analysis.source_sha256[..15]
                )
            })
            .unwrap_or_else(|| "No analyzed local source".into());
        let editor_waveform = self
            .state
            .editor_source_analysis
            .as_ref()
            .map(|analysis| analysis.waveform.clone())
            .unwrap_or_default();
        let editor_source_activity = self.state.editor_source_activity.clone();
        let media_toolchain_status = self.state.media_toolchain_status.clone();
        let media_toolchain_ready = self.state.media_toolchain_ready;
        let update_status = self.state.update_status.clone();
        let update_available = self.state.update_available;
        let update_staged = self.state.update_staged;
        let editor_segment_rows = self
            .editor_segments
            .iter()
            .enumerate()
            .map(|(index, fields)| {
                (
                    index,
                    fields.source_in.clone(),
                    fields.source_out.clone(),
                    fields.speed.clone(),
                    fields.caption.clone(),
                    fields.effect.clone(),
                )
            })
            .collect::<Vec<_>>();
        let editor_overlay_rows = self
            .editor_overlays
            .iter()
            .enumerate()
            .map(|(index, fields)| {
                (
                    index,
                    fields.text.clone(),
                    fields.start.clone(),
                    fields.end.clone(),
                    fields.position.clone(),
                )
            })
            .collect::<Vec<_>>();
        let selected_effect_kernel = self.selected_effect_kernel.clone();
        let editor_segment_count = self.editor_segments.len();
        let attached_broll_key = self.state.reel_draft.attached_broll_key.clone();
        let connection_label = self.state.connection.label();
        let connection_error = self.state.connection_error.clone();
        let operation_error = self.state.operation_error.clone();
        let activity = self.state.activity.clone();
        let media_balance = self
            .state
            .media_credits
            .as_ref()
            .map(|c| rf_gateway::format_usd_micros(c.available_micros));
        let wallet_source_balance = self
            .state
            .wallet_source_balance
            .as_ref()
            .filter(|_| self.state.wallet_source_balance_id == self.state.selected_wallet_source_id)
            .map(|balance| rf_gateway::format_usd_micros(balance.available_micros));
        let wallet_receive_address = (self.state.wallet_receive_address_source_id
            == self.state.selected_wallet_source_id)
            .then(|| self.state.wallet_receive_address.clone())
            .filter(|address| !address.is_empty());
        let wallet_challenge = self.state.wallet_transfer_challenge.clone();
        let wallet_sources = self.state.wallet_sources.clone();
        let selected_wallet_source_id = self.state.selected_wallet_source_id.clone();
        let wallet_saved_recipients = self.state.wallet_saved_recipients.clone();
        let pending_wallet_transfer = self.state.pending_wallet_transfer.clone();
        let wallet_transfer_summary = self.state.wallet_transfer.as_ref().map(|transfer| {
            let mut summary = format!(
                "Transfer {} · sent {} from {} to {} · receipt sequence {}",
                transfer.transfer_id,
                rf_gateway::format_usd_micros(transfer.amount_micros),
                transfer.source.label,
                rf_gateway::format_wallet_destination(&transfer.recipient.handle),
                transfer
                    .mint_first_seq
                    .map(|sequence| sequence.to_string())
                    .unwrap_or_else(|| "pending".into())
            );
            if let Some(proof) = &transfer.receipt_proof {
                summary.push_str(&format!(
                    "\nSigned Mint receipt: {}\nOperation hash: {}",
                    proof.receipt_hash, proof.operation_hash
                ));
            }
            (
                summary,
                transfer.recipient.kind == "personal"
                    && !transfer.recipient.handle.starts_with("ait1"),
            )
        });
        let media_usage_rows: Vec<(String, String)> = self
            .state
            .media_usage
            .iter()
            .map(|r| {
                (
                    r.model.clone(),
                    rf_gateway::format_usd_micros(r.spend_micros),
                )
            })
            .collect();
        let media_image_result: Option<(String, String)> = (!self.state.media_image_url.is_empty())
            .then(|| {
                (
                    self.state.media_image_url.clone(),
                    self.state
                        .media_image_cost
                        .map(rf_gateway::format_usd_micros)
                        .unwrap_or_default(),
                )
            });
        let has_media_image = media_image_result.is_some();
        let media_video_summary = (!self.state.media_video_id.is_empty()).then(|| {
            let output = if self.state.media_video_url.is_empty() {
                "waiting for output".to_string()
            } else {
                self.state.media_video_url.clone()
            };
            let cost = self
                .state
                .media_video_cost
                .map(rf_gateway::format_usd_micros)
                .unwrap_or_default();
            format!(
                "{} · {} · {} · {}",
                self.state.media_video_id, self.state.media_video_status, cost, output
            )
        });
        let media_audio_summary = (!self.state.media_audio_id.is_empty()).then(|| {
            let output = if self.state.media_audio_url.is_empty() {
                "waiting for output".to_string()
            } else {
                self.state.media_audio_url.clone()
            };
            let cost = self
                .state
                .media_audio_cost
                .map(rf_gateway::format_usd_micros)
                .unwrap_or_default();
            format!(
                "{} · {} · {} · {}",
                self.state.media_audio_id, self.state.media_audio_status, cost, output
            )
        });
        let media_generation_summary: Option<String> =
            self.state.media_generation.as_ref().map(|g| {
                let proof = g.settlement_proof_view();
                let mut summary = format!(
                    "{} · {} · {}\nRequest: {}\nSettlement proof: {}\nCharge: {}\nReported settlement state: {}\nExecutor: {}\nProvider request: {}\nError: {}",
                    g.id,
                    g.status,
                    if g.output_url.is_empty() {
                        "(no output yet)"
                    } else {
                        g.output_url.as_str()
                    },
                    g.correlation_id,
                    proof.outcome_label,
                    proof.charge_label,
                    g.settlement_status,
                    g.execution.kind,
                    if g.provider_request_id.is_empty() { "pending" } else { g.provider_request_id.as_str() },
                    if g.error.is_empty() { "none" } else { g.error.as_str() },
                );
                summary.push_str(&format!("\nProof status: {}", proof.proof_label));
                if let Some(operation) = proof.operation {
                    summary.push_str(&format!("\nReceipt operation: {operation}"));
                }
                if let Some(receipt_hash) = proof.receipt_hash {
                    summary.push_str(&format!("\nReceipt hash: {receipt_hash}"));
                }
                if let Some(signature) = proof.signature {
                    summary.push_str(&format!("\nReceipt signature: {signature}"));
                }
                if let Some(identity) = &g.identity {
                    let receipt = identity.receipt.as_ref();
                    summary.push_str(&format!(
                        "\nIdentity Lock: {} v{} · {}\nDigest: {}\nPayer: {}\nRequest: {}\nProvenance: {}\nReceipt hash: {}\nSignature: {}",
                        identity.passport_id,
                        identity.version,
                        identity.status,
                        identity.content_digest,
                        identity.payer_account,
                        identity.request_id,
                        identity.provenance_id,
                        receipt.map(|proof| proof.receipt_hash.as_str()).unwrap_or("pending"),
                        receipt.map(|proof| proof.signature.as_str()).unwrap_or("pending"),
                    ));
                }
                summary
            });
        let media_generation_rows: Vec<String> = self
            .state
            .media_generations
            .iter()
            .map(|generation| {
                let proof = generation.settlement_proof_view();
                format!(
                    "{} · {} · {} · {}",
                    generation.modality, generation.status, proof.charge_label, generation.id,
                )
            })
            .collect();
        let local_runtime_status = if self.state.local_runtime_ready {
            format!(
                "Local executor ready · {} recovered job{}",
                self.state.local_generations.len(),
                if self.state.local_generations.len() == 1 {
                    ""
                } else {
                    "s"
                }
            )
        } else if self.state.local_runtime_error.is_empty() {
            "Opening durable local executor…".to_string()
        } else {
            format!(
                "Local executor unavailable: {}",
                self.state.local_runtime_error
            )
        };
        let local_execution_activity = self.state.local_execution_activity.clone();
        let local_execution_failed = self.state.local_execution_failed;
        let local_generation_rows: Vec<(String, String, bool, bool)> = self
            .state
            .local_generations
            .iter()
            .map(|generation| {
                let local = generation.execution.local.as_ref();
                let latest = local.and_then(|history| history.attempts.last());
                let verified_reference = latest
                    .and_then(|attempt| attempt.artifact_verification.as_ref())
                    .filter(|verification| {
                        verification.verified && verification.has_safe_relative_reference()
                    })
                    .and_then(|verification| verification.relative_reference.as_deref());
                let failed = generation.status == "failed";
                let rail = match generation.status.as_str() {
                    "queued" => "Persisted → waiting for local lease",
                    "in_progress" => "Persisted → leased → ffmpeg running",
                    "completed" => "Persisted → leased → rendered → SHA-256 verified",
                    "failed" => "Persisted → leased → failed (no verified artifact)",
                    _ => "Persisted local lifecycle",
                };
                let executor = local
                    .map(|history| history.executor.as_str())
                    .unwrap_or("ffmpeg-local-v1");
                let artifact = verified_reference.unwrap_or("no verified artifact yet");
                (
                    generation.id.clone(),
                    format!(
                        "{} · {}\n{}\nUnsigned local execution · $0.00 charged · no settlement receipt\n{} · {}",
                        generation.id, generation.status, rail, executor, artifact,
                    ),
                    failed,
                    verified_reference.is_some(),
                )
            })
            .collect();
        let media_model_rows: Vec<(String, String)> = self
            .state
            .media_models
            .iter()
            .map(|m| {
                (
                    m.id.clone(),
                    format!(
                        "{} / {}",
                        rf_gateway::format_usd_micros(m.price_micros),
                        m.unit
                    ),
                )
            })
            .collect();
        let media_identity_rows: Vec<(String, u32, String)> = self
            .state
            .media_identities
            .iter()
            .map(|identity| {
                (
                    identity.passport_id.clone(),
                    identity.version,
                    format!("{} · {}", identity.kind, identity.content_digest),
                )
            })
            .collect();
        let provenance_export_path = self.state.provenance_export_path.clone();
        let api_base = self.preferences.normalized_api_base();
        let reel_recording_ready = !self.state.reel_draft.screen_recording_key.is_empty();
        let broll_image_ready = !self.state.broll_draft.image_key.is_empty();
        let broll_mode = self.state.broll_draft.mode;
        let reel_generation_allowed = self.state.capabilities.reels;
        let broll_generation_allowed = self.state.capabilities.broll;

        let nav_item = |label: &'static str, target: WorkspaceSection| {
            let active = section == target;
            div()
                .id(label)
                .px_2()
                .py_1()
                .rounded(window.theme().radius)
                .text_xs()
                .cursor_pointer()
                .bg(if active {
                    colors.accent
                } else {
                    colors.background
                })
                .on_click(cx.listener(move |this, _, _, cx| {
                    this.section = target;
                    cx.notify();
                }))
                .child(label)
        };

        let media_models_button = |label: &'static str, modality: Option<&'static str>| {
            div()
                .id(label)
                .rounded(window.theme().radius)
                .border_1()
                .border_color(colors.border)
                .px_3()
                .py_1()
                .cursor_pointer()
                .text_xs()
                .on_click(cx.listener(move |this, _, _, cx| {
                    this.refresh_media_models(modality.map(String::from), cx)
                }))
                .child(label)
        };

        let library_items = self.state.jobs.iter().map(|job| {
            let id = job.id.clone();
            let is_selected = self.state.selected_job_id.as_deref() == Some(job.id.as_str());
            let summary = match job.state {
                JobState::Running => format!("{}% · {}", job.progress, job.state.label()),
                _ => job.state.label().into(),
            };
            div()
                .id(SharedString::from(format!("generation-job-{id}")))
                .flex()
                .flex_col()
                .gap_1()
                .rounded(window.theme().radius)
                .p_2()
                .cursor_pointer()
                .bg(if is_selected {
                    colors.sidebar_accent
                } else {
                    colors.sidebar
                })
                .hover(|style| style.bg(colors.sidebar_accent))
                .on_click(cx.listener(move |this, _, _, cx| {
                    this.state.select_job(id.clone());
                    cx.notify();
                }))
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::MEDIUM)
                        .child(job.kind.label()),
                )
                .child(div().text_xs().child(summary))
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(job.id.clone()),
                )
        });

        let preview = match selected {
            Some(job) if job.state == JobState::Complete => {
                let can_attach = job.kind == JobKind::Broll && !job.result_key.is_empty();
                let preview_url = (!job.result_url.is_empty()).then_some(job.result_url.clone());
                div()
                    .flex()
                    .flex_col()
                    .items_center()
                    .justify_center()
                    .gap_3()
                    .h_full()
                    .child(
                        div()
                            .text_lg()
                            .font_weight(gpui::FontWeight::BOLD)
                            .child("Preview ready"),
                    )
                    .child(div().text_sm().text_color(colors.muted_foreground).child(
                        if job.result_url.is_empty() {
                            "The signed preview link is being prepared."
                        } else {
                            "Signed preview URL available to the native player."
                        },
                    ))
                    .when_some(preview_url, |this, url| {
                        this.child(
                            div()
                                .id(SharedString::from(format!("open-preview-{}", job.id)))
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .border_1()
                                .border_color(colors.border)
                                .text_xs()
                                .font_weight(gpui::FontWeight::MEDIUM)
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.open_preview(url.clone(), cx)
                                }))
                                .child("Open preview"),
                        )
                    })
                    .when(!job.result_url.is_empty(), |this| {
                        let save_url = job.result_url.clone();
                        let suggested_name = format!(
                            "{}-{}.mp4",
                            match job.kind {
                                JobKind::Reel => "reel",
                                JobKind::Broll => "broll",
                            },
                            job.id
                        );
                        this.child(
                            div()
                                .id(SharedString::from(format!("save-result-{}", job.id)))
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .border_1()
                                .border_color(colors.border)
                                .text_xs()
                                .font_weight(gpui::FontWeight::MEDIUM)
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.save_result(
                                        save_url.clone(),
                                        suggested_name.clone(),
                                        cx,
                                    )
                                }))
                                .child("Save to disk"),
                        )
                    })
                    .when(!job.result_url.is_empty(), |this| {
                        let edit_id = job.id.clone();
                        let edit_kind = job.kind;
                        let edit_url = job.result_url.clone();
                        this.child(
                            div()
                                .id(SharedString::from(format!("open-in-editor-{}", job.id)))
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .border_1()
                                .border_color(colors.border)
                                .text_xs()
                                .font_weight(gpui::FontWeight::MEDIUM)
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.open_job_in_editor(
                                        edit_id.clone(),
                                        edit_kind,
                                        edit_url.clone(),
                                        cx,
                                    )
                                }))
                                .child("Open in editor"),
                        )
                    })
                    .when(job.kind == JobKind::Reel && publishing_allowed, |this| {
                        let publish_id = job.id.clone();
                        this.child(
                            div()
                                .id(SharedString::from(format!("publish-reel-{}", job.id)))
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .bg(colors.primary)
                                .text_color(colors.primary_foreground)
                                .text_xs()
                                .font_weight(gpui::FontWeight::MEDIUM)
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.publish_reel(publish_id.clone(), cx)
                                }))
                                .child("Publish"),
                        )
                    })
                    .when(job.kind == JobKind::Reel, |this| {
                        let delete_id = job.id.clone();
                        this.child(
                            div()
                                .id(SharedString::from(format!("delete-reel-{}", job.id)))
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .border_1()
                                .border_color(colors.destructive)
                                .text_color(colors.destructive)
                                .text_xs()
                                .font_weight(gpui::FontWeight::MEDIUM)
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.delete_reel(delete_id.clone(), cx)
                                }))
                                .child("Delete"),
                        )
                    })
                    .when(!publish_status.is_empty(), |this| {
                        this.child(
                            div()
                                .text_xs()
                                .text_color(colors.muted_foreground)
                                .child(publish_status.clone()),
                        )
                    })
                    .when(can_attach, |this| {
                        this.child(
                            div()
                                .id(SharedString::from(format!("attach-broll-{}", job.id)))
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .bg(colors.primary)
                                .text_color(colors.primary_foreground)
                                .text_xs()
                                .font_weight(gpui::FontWeight::MEDIUM)
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.state.attach_selected_broll();
                                    this.section = WorkspaceSection::Create;
                                    cx.notify();
                                }))
                                .child("Attach to reel"),
                        )
                    })
            }
            Some(job) if job.state == JobState::Failed => div()
                .flex()
                .flex_col()
                .items_center()
                .justify_center()
                .gap_2()
                .h_full()
                .child(
                    div()
                        .text_lg()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Generation failed"),
                )
                .child(
                    div()
                        .text_sm()
                        .text_color(colors.destructive)
                        .child(job.error),
                ),
            Some(job) => div()
                .flex()
                .flex_col()
                .items_center()
                .justify_center()
                .gap_2()
                .h_full()
                .child(
                    div()
                        .text_lg()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child(job.state.label()),
                )
                .child(
                    div()
                        .text_sm()
                        .text_color(colors.muted_foreground)
                        .child(format!("{}% complete", job.progress)),
                ),
            None => div()
                .flex()
                .flex_col()
                .items_center()
                .justify_center()
                .gap_2()
                .h_full()
                .child(
                    div()
                        .text_lg()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Generation preview"),
                )
                .child(
                    div()
                        .text_sm()
                        .text_color(colors.muted_foreground)
                        .child("Select a completed reel or B-roll clip from the library."),
                ),
        };

        let field_label = |label: &'static str| {
            div()
                .text_xs()
                .text_color(colors.muted_foreground)
                .child(label)
        };
        let workspace_bottom = match section {
            WorkspaceSection::MediaGateway => div()
                .id("media-gateway-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Media gateway"),
                )
                .child(div().text_xs().text_color(colors.muted_foreground).child(
                    match &media_balance {
                        Some(balance) => format!("Wallet balance: {balance}"),
                        None => "Wallet balance: — (refresh to load)".to_string(),
                    },
                ))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_1()
                        .children(media_usage_rows.into_iter().map(|(model, spend)| {
                            div()
                                .flex()
                                .justify_between()
                                .text_xs()
                                .child(div().child(model))
                                .child(div().text_color(colors.muted_foreground).child(spend))
                        })),
                )
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child(format!(
                            "Model catalog ({}) — click a row to use it",
                            media_model_rows.len()
                        )),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(format!(
                            "Receive address: {}",
                            wallet_receive_address.unwrap_or_else(|| "loading…".into())
                        )),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_1()
                        .children(media_model_rows.into_iter().map(|(id, price)| {
                            let model_id = id.clone();
                            div()
                                .id(SharedString::from(format!("media-model-{id}")))
                                .flex()
                                .justify_between()
                                .text_xs()
                                .cursor_pointer()
                                .hover(|style| style.bg(colors.sidebar_accent))
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.select_media_model(model_id.clone(), cx)
                                }))
                                .child(div().child(id))
                                .child(div().text_color(colors.muted_foreground).child(price))
                        })),
                )
                .child(
                    div()
                        .flex()
                        .gap_2()
                        .child(media_models_button("All", None))
                        .child(media_models_button("Image", Some("image")))
                        .child(media_models_button("Video", Some("video")))
                        .child(media_models_button("Audio", Some("audio"))),
                )
                .child(
                    div()
                        .id("refresh-media-wallet")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| this.refresh_media_wallet(cx)))
                        .child("Refresh balance"),
                )
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Send AI tokens"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Review an exact public handle, then confirm the irreversible Mint transfer."),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(format!(
                            "Selected source available: {}",
                            wallet_source_balance.unwrap_or_else(|| "loading…".into())
                        )),
                )
                .child(div().flex().gap_2().children(wallet_sources.into_iter().enumerate().map(|(index, source)| {
                    let source_id = source.source_account_id.clone();
                    let selected = source_id == selected_wallet_source_id;
                    div()
                        .id(("wallet-source", index))
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(if selected { colors.primary } else { colors.border })
                        .px_3().py_1().text_xs().cursor_pointer()
                        .on_click(cx.listener(move |this, _, _, cx| this.select_wallet_source(source_id.clone(), cx)))
                        .child(format!("{} · {}{}", source.label, source.kind, if source.can_send { "" } else { " · view only" }))
                })))
                .child(div().flex().gap_2().children(wallet_saved_recipients.into_iter().enumerate().map(|(index, saved)| {
                    let select_id = saved.saved_recipient_id.clone();
                    let handle = saved.handle.clone();
                    let delete_id = saved.saved_recipient_id.clone();
                    let source_id = selected_wallet_source_id.clone();
                    div().flex().gap_1().rounded(window.theme().radius).border_1().border_color(colors.border).px_2().py_1().text_xs()
                        .child(div().id(("select-wallet-recipient", index)).cursor_pointer().on_click(cx.listener(move |this, _, _, cx| this.select_saved_wallet_recipient(select_id.clone(), handle.clone(), cx))).child(format!("{} · @{}", saved.display_name, saved.handle)))
                        .child(div().id(("delete-wallet-recipient", index)).cursor_pointer().on_click(cx.listener(move |this, _, _, cx| this.delete_saved_wallet_recipient(source_id.clone(), delete_id.clone(), cx))).child("×"))
                })))
                .children(pending_wallet_transfer.map(|pending| {
                    div()
                        .flex().justify_between().items_center().gap_2()
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.primary)
                        .px_3()
                        .py_2()
                        .text_xs()
                        .child(format!(
                            "Pending logical transfer: {} from {} to {}. Exact retry reuses its source, challenge and key.",
                            rf_gateway::format_usd_micros(pending.amount_micros),
                            if pending.source_label.is_empty() { "Personal wallet" } else { &pending.source_label },
                            rf_gateway::format_wallet_destination(&pending.recipient_handle),
                        ))
                        .children(pending.submitted.then(|| {
                            div().id("retry-wallet-transfer").rounded(window.theme().radius).bg(colors.primary).text_color(colors.primary_foreground).px_3().py_1().cursor_pointer().on_click(cx.listener(|this, _, _, cx| this.confirm_wallet_transfer(cx))).child("Retry exact send")
                        }))
                }))
                .child(self.wallet_recipient_field.clone())
                .child(self.wallet_transfer_amount_field.clone())
                .child(
                    div()
                        .id("review-wallet-transfer")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| this.review_wallet_transfer(cx)))
                        .child("Review recipient"),
                )
                .children(wallet_challenge.map(|challenge| {
                    let label = format!(
                        "Send {} from {} to {} ({})? Expires {}",
                        rf_gateway::format_usd_micros(challenge.amount_micros),
                        challenge.source.label,
                        rf_gateway::format_wallet_destination(&challenge.recipient.handle),
                        challenge.recipient.display_name,
                        challenge.expires_at,
                    );
                    div()
                        .flex()
                        .justify_between()
                        .items_center()
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.primary)
                        .px_3()
                        .py_2()
                        .child(div().text_xs().child(label))
                        .child(
                            div()
                                .id("confirm-wallet-transfer")
                                .rounded(window.theme().radius)
                                .bg(colors.primary)
                                .text_color(colors.primary_foreground)
                                .px_3()
                                .py_1()
                                .cursor_pointer()
                                .text_xs()
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.confirm_wallet_transfer(cx)
                                }))
                                .child("Confirm send"),
                        )
                }))
                .children(wallet_transfer_summary.map(|(summary, can_save)| {
                    div().flex().gap_2()
                        .child(div().text_xs().text_color(colors.primary).child(summary))
                        .children(can_save.then(|| div().id("save-wallet-recipient").cursor_pointer().text_xs().on_click(cx.listener(|this, _, _, cx| this.save_last_wallet_recipient(cx))).child("Save recipient")))
                }))
                .child(self.wallet_transfer_id_field.clone())
                .child(
                    div()
                        .id("recover-wallet-transfer")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| {
                            this.recover_wallet_transfer(cx)
                        }))
                        .child("Recover transfer"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Recovery reads an existing sender-owned transfer and never sends tokens again."),
                )
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Generate image"),
                )
                .child(self.media_model_field.clone())
                .child(self.media_prompt_field.clone())
                .child(
                    div()
                        .id("generate-media-image")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| this.generate_media_image(cx)))
                        .child("Generate"),
                )
                .children(media_image_result.map(|(url, cost)| {
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(format!("Image ready ({cost}): {url}"))
                }))
                .children(has_media_image.then(|| {
                    div()
                        .id("animate-media-image")
                        .rounded(window.theme().radius)
                        .bg(colors.primary)
                        .text_color(colors.primary_foreground)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| {
                            this.animate_latest_media_image(cx)
                        }))
                        .child("Animate image")
                }))
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Generate video"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Use the same model and prompt fields above. Add a source image for image-to-video models; duration is 5 seconds."),
                )
                .child(self.media_source_image_field.clone())
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Identity Lock (optional, video reference conditioning)"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Select a locked owner passport below or enter the exact passport id and version."),
                )
                .child(self.media_identity_passport_field.clone())
                .child(self.media_identity_version_field.clone())
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_1()
                        .children(media_identity_rows.into_iter().map(|(passport_id, version, detail)| {
                            let selected_id = passport_id.clone();
                            div()
                                .id(SharedString::from(format!("media-identity-{passport_id}-{version}")))
                                .flex()
                                .justify_between()
                                .text_xs()
                                .cursor_pointer()
                                .hover(|style| style.bg(colors.sidebar_accent))
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.select_media_identity(selected_id.clone(), version, cx)
                                }))
                                .child(div().child(format!("{passport_id} · v{version}")))
                                .child(div().text_color(colors.muted_foreground).child(detail))
                        })),
                )
                .child(
                    div()
                        .id("generate-media-video")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| this.generate_media_video(cx)))
                        .child("Generate video"),
                )
                .children(media_video_summary.map(|summary| {
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(summary)
                }))
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Generate music"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Load the music models, pick one, then describe the track in the prompt field above."),
                )
                .child(
                    div()
                        .flex()
                        .gap_2()
                        .child(
                            div()
                                .id("load-music-models")
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .text_xs()
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.refresh_media_models(Some("audio".into()), cx)
                                }))
                                .child("Load music models"),
                        )
                        .child(
                            div()
                                .id("generate-media-song")
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .text_xs()
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.generate_media_audio(false, cx)
                                }))
                                .child("Generate song"),
                        )
                        .child(
                            div()
                                .id("generate-media-instrumental")
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .text_xs()
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.generate_media_audio(true, cx)
                                }))
                                .child("Generate instrumental"),
                        ),
                )
                .children(media_audio_summary.map(|summary| {
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(summary)
                }))
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Inspect generation"),
                )
                .child(self.media_generation_id_field.clone())
                .child(
                    div()
                        .id("lookup-generation")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| this.lookup_generation(cx)))
                        .child("Look up"),
                )
                .children(media_generation_summary.map(|summary| {
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(summary)
                }))
                .child(self.media_provenance_path_field.clone())
                .child(
                    div()
                        .id("export-generation-provenance")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| {
                            this.export_generation_provenance(cx)
                        }))
                        .child("Export signed provenance JSON"),
                )
                .children((!provenance_export_path.is_empty()).then(|| {
                    div()
                        .text_xs()
                        .text_color(colors.primary)
                        .child(format!("Exported: {provenance_export_path}"))
                }))
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Desktop-local recovery"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(if self.state.local_runtime_ready {
                            colors.primary
                        } else {
                            colors.muted_foreground
                        })
                        .child(local_runtime_status),
                )
                .child(
                    div()
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .p_3()
                        .flex()
                        .flex_col()
                        .gap_2()
                        .child(
                            div()
                                .text_xs()
                                .font_weight(gpui::FontWeight::BOLD)
                                .child("Local execution rail"),
                        )
                        .child(
                            div()
                                .text_xs()
                                .text_color(colors.muted_foreground)
                                .child("Choose a local video. Menivor stages its bytes, persists the project and lease, then creates a real 1080×1920 MP4 with ffmpeg. Completion requires a matching SHA-256. This is a local transcode—not AI generation."),
                        )
                        .child(
                            div()
                                .id("submit-local-render")
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .bg(if self.state.local_runtime_ready {
                                    colors.primary
                                } else {
                                    colors.muted
                                })
                                .text_color(if self.state.local_runtime_ready {
                                    colors.primary_foreground
                                } else {
                                    colors.muted_foreground
                                })
                                .text_xs()
                                .when(self.state.local_runtime_ready, |button| {
                                    button.on_click(cx.listener(|this, _, window, cx| {
                                        this.choose_local_render(window, cx)
                                    }))
                                })
                                .child(if self.state.local_runtime_ready {
                                    "Choose video and render local draft"
                                } else {
                                    "Local executor unavailable"
                                }),
                        )
                        .when(!local_execution_activity.is_empty(), |panel| {
                            panel.child(
                                div()
                                    .text_xs()
                                    .text_color(if local_execution_failed {
                                        colors.destructive
                                    } else {
                                        colors.primary
                                    })
                                    .child(local_execution_activity),
                            )
                        }),
                )
                .children(local_generation_rows.into_iter().enumerate().map(|(index, (task_id, summary, failed, can_open))| {
                    div()
                        .flex()
                        .justify_between()
                        .items_center()
                        .gap_2()
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(if failed { colors.destructive } else { colors.border })
                        .px_3()
                        .py_2()
                        .text_xs()
                        .text_color(if failed {
                            colors.destructive
                        } else {
                            colors.muted_foreground
                        })
                        .child(summary)
                        .when(can_open, |row| {
                            row.child(
                                div()
                                    .id(("open-local-artifact", index))
                                    .rounded(window.theme().radius)
                                    .border_1()
                                    .border_color(colors.primary)
                                    .px_3()
                                    .py_1()
                                    .cursor_pointer()
                                    .text_color(colors.primary)
                                    .on_click(cx.listener(move |this, _, _, cx| {
                                        this.open_local_artifact(task_id.clone(), cx)
                                    }))
                                    .child("Open verified MP4"),
                            )
                        })
                }))
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Recoverable generation timeline"),
                )
                .children(media_generation_rows.into_iter().map(|summary| {
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(summary)
                }))
                .children(self.state.media_generations_has_more.then(|| {
                    div()
                        .id("load-older-generations")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| {
                            this.load_more_media_generations(cx)
                        }))
                        .child("Load older generations")
                }))
                .into_any_element(),
            WorkspaceSection::Governance => div()
                .id("governance-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Model governance"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("License classes gate paid renders; only commercial-safe models may bill. Sunset dates and replacements come from the provider deprecation registry. Select a model to load a commercial-safe pick into the generate form."),
                )
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child(format!(
                            "License registry ({} models)",
                            rf_provider::LICENSE_REGISTRY.len()
                        )),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_1()
                        .children(rf_provider::LICENSE_REGISTRY.iter().map(|(model, class)| {
                            let model_id = model.to_string();
                            div()
                                .id(SharedString::from(format!("governance-model-{model}")))
                                .flex()
                                .justify_between()
                                .text_xs()
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.use_governed_model(model_id.clone(), cx)
                                }))
                                .child(div().child(model.to_string()))
                                .child(
                                    div()
                                        .text_color(colors.muted_foreground)
                                        .child(format!(
                                            "{:?} · paid: {}",
                                            class,
                                            if rf_provider::can_use_for_paid(model) {
                                                "yes"
                                            } else {
                                                "no"
                                            }
                                        )),
                                )
                        })),
                )
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child(format!(
                            "Deprecation registry ({} models)",
                            rf_provider::DEPRECATION_REGISTRY.len()
                        )),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_1()
                        .children(rf_provider::DEPRECATION_REGISTRY.iter().map(|(model, entry)| {
                            div()
                                .flex()
                                .justify_between()
                                .text_xs()
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .child(div().child(model.to_string()))
                                .child(
                                    div()
                                        .text_color(colors.muted_foreground)
                                        .child(format!(
                                            "sunset {} → {}",
                                            entry.sunset, entry.replacement
                                        )),
                                )
                        })),
                )
                .into_any_element(),
            WorkspaceSection::Trends => div()
                .id("trends-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Trend scoring"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(match &trend_series {
                            Some(series) => format!(
                                "Your jobs per day, last {TREND_DAYS} days (oldest first): {}",
                                series
                                    .iter()
                                    .map(|count| format!("{count:.0}"))
                                    .collect::<Vec<_>>()
                                    .join(", ")
                            ),
                            None => format!(
                                "No jobs in your library from the last {TREND_DAYS} days yet. Create a reel and your trend window fills in here."
                            ),
                        }),
                )
                .when_some(trend_series, |this, series| {
                    let trend = rf_trends::score(&series);
                    this.child(
                        div()
                            .id("draft-reel-for-trend")
                            .rounded(window.theme().radius)
                            .border_1()
                            .border_color(colors.border)
                            .px_3()
                            .py_2()
                            .cursor_pointer()
                            .text_xs()
                            .on_click(cx.listener(|this, _, _, cx| this.draft_reel_for_trend(cx)))
                            .child("Draft an ad-safe reel for this trend window"),
                    )
                    .child(
                        div().flex().flex_col().gap_1().children(
                            [
                                ("Saturation", trend.saturation),
                                ("Velocity", trend.velocity),
                                ("Decay", trend.decay),
                                ("Opportunity", trend.opportunity),
                            ]
                            .into_iter()
                            .map(|(label, value)| {
                                div()
                                    .flex()
                                    .justify_between()
                                    .text_xs()
                                    .rounded(window.theme().radius)
                                    .border_1()
                                    .border_color(colors.border)
                                    .px_3()
                                    .py_2()
                                    .child(div().child(label))
                                    .child(
                                        div()
                                            .text_color(colors.muted_foreground)
                                            .child(format!("{value:.6}")),
                                    )
                            }),
                        ),
                    )
                })
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Ad-safe sound policy (licensed and not explicit)"),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_1()
                        .children(
                            [
                                (
                                    "Licensed, clean",
                                    rf_trends::SoundFlags {
                                        licensed: Some(true),
                                        explicit: Some(false),
                                    },
                                ),
                                (
                                    "Licensed, explicit",
                                    rf_trends::SoundFlags {
                                        licensed: Some(true),
                                        explicit: Some(true),
                                    },
                                ),
                                (
                                    "Unlicensed",
                                    rf_trends::SoundFlags {
                                        licensed: Some(false),
                                        explicit: Some(false),
                                    },
                                ),
                                (
                                    "Defaults (licensed, clean)",
                                    rf_trends::SoundFlags {
                                        licensed: None,
                                        explicit: None,
                                    },
                                ),
                            ]
                            .into_iter()
                            .map(|(label, flags)| {
                                div()
                                    .flex()
                                    .justify_between()
                                    .text_xs()
                                    .rounded(window.theme().radius)
                                    .border_1()
                                    .border_color(colors.border)
                                    .px_3()
                                    .py_2()
                                    .child(div().child(label))
                                    .child(
                                        div()
                                            .text_color(colors.muted_foreground)
                                            .child(if rf_trends::ad_safe(&flags) {
                                                "ad-safe".to_string()
                                            } else {
                                                "blocked".to_string()
                                            }),
                                    )
                            }),
                        ),
                )
                .into_any_element(),
            WorkspaceSection::Signals => div()
                .id("signals-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Growth signals"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(format!(
                            "Score a reel from what your platform analytics measured. Hook gate: score >= {}",
                            rf_growth::GATE
                        )),
                )
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Hook signals"),
                )
                .child(self.signal_fields.motion.clone())
                .child(self.signal_fields.contrast.clone())
                .child(self.signal_fields.text.clone())
                .child(self.signal_fields.audio_onset.clone())
                .child(match &hook_signals {
                    Ok(Some(signals)) => {
                        let result = rf_growth::hook_score(signals);
                        div()
                            .flex()
                            .justify_between()
                            .rounded(window.theme().radius)
                            .border_1()
                            .border_color(colors.border)
                            .px_3()
                            .py_2()
                            .text_xs()
                            .child(div().child(format!("Hook score {}", result.score)))
                            .child(div().font_weight(gpui::FontWeight::BOLD).child(
                                if result.passes { "PASS" } else { "GATE" },
                            ))
                    }
                    Ok(None) => div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Enter at least one hook signal to score the opening."),
                    Err(message) => div()
                        .text_xs()
                        .text_color(colors.destructive)
                        .child(message.clone()),
                })
                .child(
                    div()
                        .text_xs()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("A/B variants"),
                )
                .children(self.signal_fields.variants.iter().map(|row| {
                    div()
                        .flex()
                        .gap_2()
                        .child(div().flex_1().child(row.completion.clone()))
                        .child(div().flex_1().child(row.avg_watch.clone()))
                }))
                .child(match &ab_variants {
                    Ok(variants) if !variants.is_empty() => {
                        let completions: Vec<f64> =
                            variants.iter().filter_map(|variant| variant.completion).collect();
                        let reach = (!completions.is_empty()).then(|| {
                            let average = completions.iter().sum::<f64>() / completions.len() as f64;
                            (average, rf_growth::reach_tier(average))
                        });
                        let result = rf_growth::select_winner(variants);
                        div()
                            .flex()
                            .flex_col()
                            .gap_1()
                            .child(
                                div()
                                    .text_xs()
                                    .text_color(colors.muted_foreground)
                                    .child(format!(
                                        "Winner: {}",
                                        result.winner.clone().unwrap_or_else(|| "none yet".into())
                                    )),
                            )
                            .children(result.scores.into_iter().map(|(id, score)| {
                                div()
                                    .flex()
                                    .justify_between()
                                    .text_xs()
                                    .child(div().child(id))
                                    .child(
                                        div()
                                            .text_color(colors.muted_foreground)
                                            .child(format!("{score}")),
                                    )
                            }))
                            .when_some(reach, |this, (average, tier)| {
                                this.child(
                                    div()
                                        .text_xs()
                                        .text_color(colors.muted_foreground)
                                        .child(format!(
                                            "Reach tier at {:.0}% average completion: {:?}, {}x distribution",
                                            average * 100.0,
                                            tier.tier,
                                            tier.multiplier
                                        )),
                                )
                            })
                    }
                    Ok(_) => div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Enter completion and average watch time for two or more variants to pick a winner."),
                    Err(message) => div()
                        .text_xs()
                        .text_color(colors.destructive)
                        .child(message.clone()),
                })
                .child(
                    div()
                        .id("adopt-ab-winner")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| this.adopt_ab_winner(cx)))
                        .child("Adopt the A/B winner's watch time as the reel target"),
                )
                .into_any_element(),
            WorkspaceSection::Captions => div()
                .id("captions-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Caption style presets"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(format!(
                            "{} presets — canvas {}x{}",
                            rf_captions::list_presets().len(),
                            rf_captions::PLAY_RES_X,
                            rf_captions::PLAY_RES_Y
                        )),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_2()
                        .children(rf_captions::list_presets().into_iter().filter_map(|name| {
                            rf_captions::get_preset(&name).ok().map(|style| {
                                let name_for_click = name.clone();
                                div()
                                    .id(SharedString::from(format!("caption-preset-{name}")))
                                    .flex()
                                    .flex_col()
                                    .gap_1()
                                    .rounded(window.theme().radius)
                                    .border_1()
                                    .border_color(colors.border)
                                    .px_3()
                                    .py_2()
                                    .cursor_pointer()
                                    .on_click(cx.listener(move |this, _, _, cx| {
                                        this.use_caption_preset(name_for_click.clone(), cx)
                                    }))
                                    .child(
                                        div()
                                            .flex()
                                            .justify_between()
                                            .text_sm()
                                            .child(
                                                div()
                                                    .font_weight(gpui::FontWeight::BOLD)
                                                    .child(name.clone()),
                                            )
                                            .child(
                                                div()
                                                    .text_color(colors.muted_foreground)
                                                    .child(format!("{} @ {}px", style.font, style.size)),
                                            ),
                                    )
                                    .child(
                                        div()
                                            .flex()
                                            .justify_between()
                                            .text_xs()
                                            .text_color(colors.muted_foreground)
                                            .child(div().child(format!(
                                                "primary {}  highlight {}  outline {}",
                                                style.primary_hex, style.highlight_hex, style.outline_hex
                                            )))
                                            .child(div().child(format!("align {}", style.alignment))),
                                    )
                                    .child(
                                        div()
                                            .text_xs()
                                            .text_color(colors.muted_foreground)
                                            .child(format!(
                                                "outline {}  shadow {}  margin_v {}  bold {}  uppercase {}  words/group {}",
                                                style.outline,
                                                style.shadow,
                                                style.margin_v,
                                                style.bold,
                                                style.uppercase,
                                                style.words_per_group
                                            )),
                                    )
                            })
                        })),
                )
                .into_any_element(),
            WorkspaceSection::Blueprints => div()
                .id("blueprints-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Shot-template blueprints"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(format!(
                            "{} genre presets — slots, content hash, and total duration",
                            rf_shots::list_presets(None).len()
                        )),
                )
                .children(
                    rf_shots::list_presets(None)
                        .into_iter()
                        .filter_map(|slug| rf_shots::get_preset(&slug).ok())
                        .map(|template| {
                            let slug_for_click = template.slug.clone();
                            div()
                                .id(SharedString::from(format!(
                                    "blueprint-{}",
                                    template.slug
                                )))
                                .flex()
                                .flex_col()
                                .gap_1()
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.apply_shot_blueprint(slug_for_click.clone(), cx)
                                }))
                                .child(
                                    div()
                                        .flex()
                                        .justify_between()
                                        .text_sm()
                                        .font_weight(gpui::FontWeight::BOLD)
                                        .child(div().child(template.slug.clone()))
                                        .child(
                                            div()
                                                .text_xs()
                                                .text_color(colors.muted_foreground)
                                                .child(format!(
                                                    "{} / {}",
                                                    template.genre, template.aspect
                                                )),
                                        ),
                                )
                                .child(
                                    div()
                                        .flex()
                                        .justify_between()
                                        .text_xs()
                                        .text_color(colors.muted_foreground)
                                        .child(div().child(format!(
                                            "hash {}",
                                            rf_shots::content_hash(&template)
                                        )))
                                        .child(div().child(format!(
                                            "total {} ms",
                                            rf_shots::total_duration_ms(&template)
                                        ))),
                                )
                                .child(
                                    div()
                                        .flex()
                                        .flex_col()
                                        .gap_1()
                                        .children(template.slots.iter().map(|slot| {
                                            div()
                                                .flex()
                                                .justify_between()
                                                .text_xs()
                                                .child(div().child(slot.role.clone()))
                                                .child(
                                                    div()
                                                        .text_color(colors.muted_foreground)
                                                        .child(format!(
                                                            "{} - {} ms",
                                                            slot.t_start_ms, slot.t_end_ms
                                                        )),
                                                )
                                        })),
                                )
                        }),
                )
                .into_any_element(),
            WorkspaceSection::Effects => div()
                .id("effects-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Animation effect kernels"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(format!(
                            "{} kernels — each shown with its category and apply(id, 0.5) output",
                            rf_effects::list_kernels(None).len()
                        )),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Select a kernel to expand its deterministic keyframe curve."),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_1()
                        .children(rf_effects::list_kernels(None).into_iter().map(|id| {
                            let category = match rf_effects::category_of(&id) {
                                Some(rf_effects::KernelCategory::Camera) => "camera",
                                Some(rf_effects::KernelCategory::Vfx) => "vfx",
                                None => "unknown",
                            };
                            let sample_at = |t: f64| {
                                rf_effects::apply(&id, t, &rf_effects::Params::new())
                                    .map(|pairs| {
                                        pairs
                                            .into_iter()
                                            .map(|(k, v)| format!("{k}={v}"))
                                            .collect::<Vec<_>>()
                                            .join(", ")
                                    })
                                    .unwrap_or_else(|err| err)
                            };
                            let output = sample_at(0.5);
                            let is_selected =
                                selected_effect_kernel.as_deref() == Some(id.as_str());
                            let keyframe_rows: Vec<(String, String)> = if is_selected {
                                EFFECT_SAMPLE_POINTS
                                    .iter()
                                    .map(|t| (format!("t={t:.2}"), sample_at(*t)))
                                    .collect()
                            } else {
                                Vec::new()
                            };
                            let id_for_click = id.clone();
                            div()
                                .id(SharedString::from(format!("effect-kernel-{id}")))
                                .flex()
                                .flex_col()
                                .gap_1()
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .bg(if is_selected {
                                    colors.accent
                                } else {
                                    colors.card
                                })
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.toggle_effect_kernel(id_for_click.clone(), cx)
                                }))
                                .child(
                                    div()
                                        .flex()
                                        .justify_between()
                                        .text_xs()
                                        .child(
                                            div()
                                                .font_weight(gpui::FontWeight::BOLD)
                                                .child(id.clone()),
                                        )
                                        .child(
                                            div()
                                                .text_color(colors.muted_foreground)
                                                .child(category.to_string()),
                                        ),
                                )
                                .child(
                                    div()
                                        .text_xs()
                                        .text_color(colors.muted_foreground)
                                        .child(format!("apply(0.5): {output}")),
                                )
                                .when(is_selected, |row| {
                                    row.child(
                                        div()
                                            .flex()
                                            .flex_col()
                                            .gap_1()
                                            .children(keyframe_rows.into_iter().map(
                                                |(label, values)| {
                                                    div()
                                                        .flex()
                                                        .justify_between()
                                                        .gap_2()
                                                        .text_xs()
                                                        .child(
                                                            div()
                                                                .font_weight(
                                                                    gpui::FontWeight::BOLD,
                                                                )
                                                                .child(label),
                                                        )
                                                        .child(
                                                            div()
                                                                .text_color(
                                                                    colors.muted_foreground,
                                                                )
                                                                .child(values),
                                                        )
                                                },
                                            )),
                                    )
                                })
                                .when(is_selected, |row| {
                                    let apply_kernel = id.clone();
                                    row.child(
                                        div()
                                            .flex()
                                            .flex_col()
                                            .gap_1()
                                            .child(
                                                div()
                                                    .text_xs()
                                                    .text_color(colors.muted_foreground)
                                                    .child(
                                                        "Apply to a timeline segment (persists through export):",
                                                    ),
                                            )
                                            .child(
                                                div()
                                                    .flex()
                                                    .flex_wrap()
                                                    .gap_1()
                                                    .children((0..editor_segment_count).map(
                                                        |segment_index| {
                                                            let kernel_for_click =
                                                                apply_kernel.clone();
                                                            div()
                                                                .id(SharedString::from(format!(
                                                                    "apply-effect-{apply_kernel}-seg-{segment_index}"
                                                                )))
                                                                .rounded(window.theme().radius)
                                                                .border_1()
                                                                .border_color(colors.border)
                                                                .px_2()
                                                                .py_1()
                                                                .text_xs()
                                                                .cursor_pointer()
                                                                .on_click(cx.listener(
                                                                    move |this, _, _, cx| {
                                                                        this.apply_effect_to_segment(
                                                                            segment_index,
                                                                            kernel_for_click.clone(),
                                                                            cx,
                                                                        )
                                                                    },
                                                                ))
                                                                .child(format!(
                                                                    "→ Segment {}",
                                                                    segment_index + 1
                                                                ))
                                                        },
                                                    )),
                                            ),
                                    )
                                })
                        })),
                )
                .into_any_element(),
            WorkspaceSection::Workflows => div()
                .id("workflows-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Workflow registry"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child(format!(
                            "{} pinned ComfyUI workflow descriptors (graph_hash-pinned identity). Select a hosted one to run it on the media gateway.",
                            rf_workflows::list_workflows(None).len()
                        )),
                )
                .children(
                    rf_workflows::list_workflows(None)
                        .into_iter()
                        .filter_map(|slug| rf_workflows::get_workflow(&slug).ok())
                        .map(|w| {
                            let hash = rf_workflows::graph_hash(&w);
                            let slug_for_click = w.slug.clone();
                            div()
                                .id(SharedString::from(format!("workflow-{}", w.slug)))
                                .flex()
                                .flex_col()
                                .gap_1()
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.instantiate_workflow(slug_for_click.clone(), cx)
                                }))
                                .child(
                                    div()
                                        .flex()
                                        .justify_between()
                                        .text_sm()
                                        .child(
                                            div()
                                                .font_weight(gpui::FontWeight::BOLD)
                                                .child(w.slug.clone()),
                                        )
                                        .child(
                                            div()
                                                .text_color(colors.muted_foreground)
                                                .child(format!("graph_hash {hash}")),
                                        ),
                                )
                                .child(
                                    div()
                                        .text_xs()
                                        .text_color(colors.muted_foreground)
                                        .child(format!("{} — {}", w.category, w.description)),
                                )
                                .child(
                                    div()
                                        .text_xs()
                                        .font_weight(gpui::FontWeight::BOLD)
                                        .child(
                                            match crate::ui::create::hosted_model_for_workflow(
                                                &w.slug,
                                            ) {
                                                Some(model) => format!("Runs on {model}"),
                                                None => "Local ComfyUI only (no hosted runner)"
                                                    .to_string(),
                                            },
                                        ),
                                )
                                .child(
                                    div()
                                        .text_xs()
                                        .font_weight(gpui::FontWeight::BOLD)
                                        .child(format!("Node commits ({})", w.node_commits.len())),
                                )
                                .child(
                                    div()
                                        .flex()
                                        .flex_col()
                                        .gap_1()
                                        .children(w.node_commits.iter().map(|(node, commit)| {
                                            div()
                                                .flex()
                                                .justify_between()
                                                .text_xs()
                                                .child(div().child(node.to_string()))
                                                .child(
                                                    div()
                                                        .text_color(colors.muted_foreground)
                                                        .child(commit.to_string()),
                                                )
                                        })),
                                )
                                .child(
                                    div()
                                        .text_xs()
                                        .font_weight(gpui::FontWeight::BOLD)
                                        .child(format!("Weight refs ({})", w.weight_refs.len())),
                                )
                                .child(
                                    div()
                                        .flex()
                                        .flex_col()
                                        .gap_1()
                                        .children(w.weight_refs.iter().map(|weight_ref| {
                                            div()
                                                .text_xs()
                                                .text_color(colors.muted_foreground)
                                                .child(weight_ref.to_string())
                                        })),
                                )
                                .child(
                                    div()
                                        .text_xs()
                                        .font_weight(gpui::FontWeight::BOLD)
                                        .child(format!("Input contract ({})", w.inputs.len())),
                                )
                                .child(
                                    div()
                                        .flex()
                                        .flex_col()
                                        .gap_1()
                                        .children(w.inputs.iter().map(|slot| {
                                            let ty = match slot.slot_type {
                                                rf_workflows::SlotType::Int => "int",
                                                rf_workflows::SlotType::String => "string",
                                                rf_workflows::SlotType::Image => "image",
                                                rf_workflows::SlotType::Video => "video",
                                                rf_workflows::SlotType::Audio => "audio",
                                            };
                                            let default = match &slot.default {
                                                Some(rf_workflows::DefaultValue::Int(n)) => {
                                                    n.to_string()
                                                }
                                                Some(rf_workflows::DefaultValue::Str(s)) => {
                                                    s.clone()
                                                }
                                                None => "—".to_string(),
                                            };
                                            let range = match (slot.min, slot.max) {
                                                (Some(lo), Some(hi)) => format!(" [{lo}..{hi}]"),
                                                (Some(lo), None) => format!(" [>={lo}]"),
                                                (None, Some(hi)) => format!(" [<={hi}]"),
                                                (None, None) => String::new(),
                                            };
                                            let req = if slot.required {
                                                "required"
                                            } else {
                                                "optional"
                                            };
                                            div()
                                                .flex()
                                                .justify_between()
                                                .text_xs()
                                                .child(div().child(format!(
                                                    "{}: {}{}",
                                                    slot.name, ty, range
                                                )))
                                                .child(
                                                    div()
                                                        .text_color(colors.muted_foreground)
                                                        .child(format!(
                                                            "{req} · default {default}"
                                                        )),
                                                )
                                        })),
                                )
                        }),
                )
                .into_any_element(),
            WorkspaceSection::Editor => div()
                .id("editor-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .flex()
                        .justify_between()
                        .items_center()
                        .child(
                            div()
                                .text_sm()
                                .font_weight(gpui::FontWeight::BOLD)
                                .child("Timeline export"),
                        )
                        .child(
                            div()
                                .text_xs()
                                .text_color(colors.muted_foreground)
                                .child(editor_source_label),
                        ),
                )
                .child(
                    div()
                        .flex()
                        .justify_between()
                        .items_center()
                        .gap_3()
                        .p_3()
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .child(
                            div()
                                .text_xs()
                                .text_color(colors.muted_foreground)
                                .child("For hands-on editing with a live preview, timeline, captions and effects, use the Menivor editor (WolfCut). Finished jobs open there from the Library with Open in editor."),
                        )
                        .child(
                            div()
                                .id("launch-wolfcut")
                                .flex_none()
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .bg(colors.primary)
                                .text_color(colors.primary_foreground)
                                .text_xs()
                                .font_weight(gpui::FontWeight::MEDIUM)
                                .on_click(cx.listener(|this, _, _, cx| this.launch_editor(cx)))
                                .child("Open editor"),
                        ),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Quick timeline export: trim source spans, change per-segment speed, burn captions, and add an optional timed overlay, then render on Menivor or locally."),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_2()
                        .p_3()
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .child(
                            div()
                                .flex()
                                .items_center()
                                .justify_between()
                                .child(
                                    div()
                                        .flex()
                                        .flex_col()
                                        .gap_1()
                                        .child(
                                            div()
                                                .text_xs()
                                                .font_weight(gpui::FontWeight::BOLD)
                                                .child("Local source waveform"),
                                        )
                                        .child(
                                            div()
                                                .text_xs()
                                                .text_color(colors.muted_foreground)
                                                .child(editor_local_source_summary),
                                        ),
                                )
                                .child(
                                    div()
                                        .id("analyze-editor-source")
                                        .rounded(window.theme().radius)
                                        .border_1()
                                        .border_color(colors.border)
                                        .px_3()
                                        .py_2()
                                        .cursor_pointer()
                                        .text_xs()
                                        .on_click(cx.listener(|this, _, window, cx| {
                                            this.choose_editor_source(window, cx)
                                        }))
                                        .child("Choose + analyze"),
                                )
                                .child(
                                    div()
                                        .id("open-editor-project")
                                        .rounded(window.theme().radius)
                                        .border_1()
                                        .border_color(colors.border)
                                        .px_3()
                                        .py_2()
                                        .cursor_pointer()
                                        .text_xs()
                                        .on_click(cx.listener(|this, _, _, cx| {
                                            this.prompt_open_project(cx)
                                        }))
                                        .child("Open project"),
                                )
                                .child(
                                    div()
                                        .id("save-editor-project")
                                        .rounded(window.theme().radius)
                                        .border_1()
                                        .border_color(colors.border)
                                        .px_3()
                                        .py_2()
                                        .cursor_pointer()
                                        .text_xs()
                                        .on_click(cx.listener(|this, _, _, cx| {
                                            this.prompt_save_project(cx)
                                        }))
                                        .child("Save project"),
                                ),
                        )
                        .when(!editor_source_activity.is_empty(), |this| {
                            this.child(
                                div()
                                    .text_xs()
                                    .text_color(colors.muted_foreground)
                                    .child(editor_source_activity),
                            )
                        })
                        .when(!media_toolchain_status.is_empty(), |this| {
                            this.child(
                                div()
                                    .text_xs()
                                    .text_color(if media_toolchain_ready {
                                        colors.muted_foreground
                                    } else {
                                        colors.destructive
                                    })
                                    .child(media_toolchain_status),
                            )
                        })
                        .when(!editor_waveform.is_empty(), |this| {
                            this.child(
                                div()
                                    .flex()
                                    .items_end()
                                    .w_full()
                                    .h(px(56.0))
                                    .overflow_hidden()
                                    .children(editor_waveform.into_iter().map(|peak| {
                                        div()
                                            .flex_1()
                                            .h(px(2.0 + f32::from(peak) * 0.052))
                                            .bg(colors.primary)
                                    })),
                            )
                        }),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_2()
                        .children(editor_segment_rows.into_iter().map(|(index, source_in, source_out, speed, caption, effect)| {
                            div()
                                .flex()
                                .flex_col()
                                .gap_1()
                                .pb_2()
                                .border_b_1()
                                .border_color(colors.border)
                                .child(
                                    div()
                                        .flex()
                                        .items_center()
                                        .justify_between()
                                        .text_xs()
                                        .font_weight(gpui::FontWeight::BOLD)
                                        .child(format!("Segment {}", index + 1))
                                        .child(
                                            div()
                                                .flex()
                                                .gap_1()
                                                .child(div().id(SharedString::from(format!("move-editor-segment-up-{index}"))).rounded(window.theme().radius).border_1().border_color(colors.border).px_2().py_1().cursor_pointer().on_click(cx.listener(move |this, _, _, cx| this.move_editor_segment(index, -1, cx))).child("Up"))
                                                .child(div().id(SharedString::from(format!("move-editor-segment-down-{index}"))).rounded(window.theme().radius).border_1().border_color(colors.border).px_2().py_1().cursor_pointer().on_click(cx.listener(move |this, _, _, cx| this.move_editor_segment(index, 1, cx))).child("Down"))
                                                .child(div().id(SharedString::from(format!("duplicate-editor-segment-{index}"))).rounded(window.theme().radius).border_1().border_color(colors.border).px_2().py_1().cursor_pointer().on_click(cx.listener(move |this, _, _, cx| this.duplicate_editor_segment(index, cx))).child("Duplicate"))
                                                .child(div().id(SharedString::from(format!("delete-editor-segment-{index}"))).rounded(window.theme().radius).border_1().border_color(colors.destructive).text_color(colors.destructive).px_2().py_1().cursor_pointer().on_click(cx.listener(move |this, _, _, cx| this.remove_editor_segment_at(index, cx))).child("Delete")),
                                        ),
                                )
                                .child(
                                    div()
                                        .flex()
                                        .gap_2()
                                        .child(div().flex().flex_col().w_1_3().gap_1().child(field_label("Source in · seconds")).child(source_in))
                                        .child(div().flex().flex_col().w_1_3().gap_1().child(field_label("Source out · seconds")).child(source_out))
                                        .child(div().flex().flex_col().w_1_3().gap_1().child(field_label("Playback speed · 0.25–4×")).child(speed)),
                                )
                                .child(field_label("Burned caption · optional"))
                                .child(caption)
                                .child(field_label("Animation effect · kernel id · optional"))
                                .child(effect)
                        })),
                )
                .child(
                    div()
                        .flex()
                        .gap_2()
                        .child(
                            div()
                                .id("add-editor-segment")
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .text_xs()
                                .on_click(cx.listener(|this, _, _, cx| this.add_editor_segment(cx)))
                                .child("Add segment"),
                        )
                        .child(div().text_xs().text_color(colors.muted_foreground).child("Rows render in this exact top-to-bottom order.")),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap_2()
                        .children(editor_overlay_rows.into_iter().map(|(index, text, start, end, position)| {
                            div()
                                .flex()
                                .flex_col()
                                .gap_1()
                                .child(
                                    div()
                                        .flex()
                                        .justify_between()
                                        .items_center()
                                        .child(div().text_xs().font_weight(gpui::FontWeight::BOLD).child(format!("Overlay {}", index + 1)))
                                        .child(div().id(SharedString::from(format!("delete-editor-overlay-{index}"))).rounded(window.theme().radius).border_1().border_color(colors.destructive).text_color(colors.destructive).px_2().py_1().cursor_pointer().text_xs().on_click(cx.listener(move |this, _, _, cx| this.remove_editor_overlay(index, cx))).child("Delete")),
                                )
                                .child(
                                    div()
                                        .flex()
                                        .gap_2()
                                        .child(div().flex().flex_col().w_1_3().gap_1().child(field_label("Text · blank disables row")).child(text))
                                        .child(div().flex().flex_col().w_1_3().gap_1().child(field_label("Start · seconds")).child(start))
                                        .child(div().flex().flex_col().w_1_3().gap_1().child(field_label("End · seconds")).child(end))
                                        .child(div().flex().flex_col().w_1_3().gap_1().child(field_label("Position")).child(position)),
                                )
                        }))
                        .child(
                            div()
                                .id("add-editor-overlay")
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .text_xs()
                                .on_click(cx.listener(|this, _, _, cx| this.add_editor_overlay(cx)))
                                .child("Add overlay"),
                        ),
                )
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap_3()
                        .child(
                            div()
                                .id("submit-timeline-export")
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .bg(colors.primary)
                                .text_color(colors.primary_foreground)
                                .text_xs()
                                .font_weight(gpui::FontWeight::MEDIUM)
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.submit_timeline_export(cx)
                                }))
                                .child("Export timeline"),
                        )
                        .child(
                            div()
                                .id("render-timeline-locally")
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .border_1()
                                .border_color(colors.border)
                                .text_xs()
                                .font_weight(gpui::FontWeight::MEDIUM)
                                .on_click(cx.listener(|this, _, window, cx| {
                                    this.choose_local_timeline_render(window, cx)
                                }))
                                .child("Render local source"),
                        )
                        .when(!self.state.editor_export_job_id.is_empty(), |this| {
                            this.child(
                                div()
                                    .text_xs()
                                    .text_color(colors.muted_foreground)
                                    .child(format!(
                                        "Latest export {} · {:.3}s",
                                        self.state.editor_export_job_id,
                                        self.state.editor_output_duration_ms as f64 / 1000.0
                                    )),
                            )
                        }),
                )
                .into_any_element(),
            WorkspaceSection::Settings => div()
                .id("settings-workspace")
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Connection settings"),
                )
                .child({
                    let use_local = self.preferences.use_local_engine;
                    let status_label = self.sidecar_status.label().to_owned();
                    let toggle_label = if use_local {
                        "Local (free) engine: on"
                    } else {
                        "Local (free) engine: off"
                    };
                    div()
                        .flex()
                        .flex_col()
                        .gap_1()
                        .child(
                            div()
                                .flex()
                                .items_center()
                                .gap_2()
                                .child(
                                    div()
                                        .id("toggle-local-engine")
                                        .rounded(window.theme().radius)
                                        .border_1()
                                        .border_color(if use_local {
                                            colors.primary
                                        } else {
                                            colors.border
                                        })
                                        .px_3()
                                        .py_1()
                                        .cursor_pointer()
                                        .text_xs()
                                        .text_color(if use_local {
                                            colors.primary
                                        } else {
                                            colors.muted_foreground
                                        })
                                        .on_click(cx.listener(|this, _, _, cx| {
                                            this.toggle_local_engine(cx)
                                        }))
                                        .child(toggle_label),
                                )
                                .child(
                                    div()
                                        .text_xs()
                                        .text_color(colors.muted_foreground)
                                        .child(
                                            "Make AI videos on this Mac. No API key. No cloud bill. \
                                             Generation is always free.",
                                        ),
                                ),
                        )
                        .when(!status_label.is_empty(), |this| {
                            this.child(
                                div()
                                    .text_xs()
                                    .text_color(if self.sidecar_status
                                        == crate::domain::SidecarStatus::Running
                                    {
                                        colors.primary
                                    } else {
                                        colors.muted_foreground
                                    })
                                    .child(status_label),
                            )
                        })
                })
                .child(field_label("API base URL"))
                .child(self.api_base_field.clone())
                .child(field_label("API key"))
                .child(self.api_key_field.clone())
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap_2()
                        .child(
                            div()
                                .text_xs()
                                .text_color(colors.muted_foreground)
                                .child("No key yet? Sign in on the web, create a personal API key, then paste it here."),
                        )
                        .child(
                            div()
                                .id("open-api-keys-page")
                                .rounded(window.theme().radius)
                                .border_1()
                                .border_color(colors.border)
                                .px_3()
                                .py_1()
                                .cursor_pointer()
                                .text_xs()
                                .on_click(cx.listener(|this, _, _, cx| this.open_api_keys_page(cx)))
                                .child("Get an API key"),
                        ),
                )
                .child(field_label("Menivor editor (WolfCut) location"))
                .child(self.editor_path_field.clone())
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Leave the key blank to keep the credential already stored in the operating-system keychain."),
                )
                .child(
                    div()
                        .flex()
                        .gap_2()
                        .child(
                            div()
                                .id("save-settings")
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .bg(colors.primary)
                                .text_color(colors.primary_foreground)
                                .text_xs()
                                .on_click(cx.listener(|this, _, _, cx| this.save_settings(cx)))
                                .child("Save and connect"),
                        )
                        .child(
                            div()
                                .id("clear-credentials")
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .border_1()
                                .border_color(colors.destructive)
                                .text_color(colors.destructive)
                                .text_xs()
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.clear_credentials(cx)
                                }))
                                .child("Remove saved key"),
                        ),
                )
                .child(
                    div()
                        .mt_3()
                        .pt_3()
                        .border_t_1()
                        .border_color(colors.border)
                        .flex()
                        .flex_col()
                        .gap_2()
                        .child(
                            div()
                                .text_sm()
                                .font_weight(gpui::FontWeight::BOLD)
                                .child(format!(
                                    "Menivor updates · installed {}",
                                    env!("CARGO_PKG_VERSION")
                                )),
                        )
                        .child(
                            div()
                                .text_xs()
                                .text_color(colors.muted_foreground)
                                .child(if update_status.is_empty() {
                                    "Choose a signed release channel to check for updates."
                                        .to_string()
                                } else {
                                    update_status
                                }),
                        )
                        .child(
                            div()
                                .flex()
                                .gap_2()
                                .child(
                                    div()
                                        .id("check-stable-update")
                                        .rounded(window.theme().radius)
                                        .border_1()
                                        .border_color(colors.border)
                                        .px_3()
                                        .py_2()
                                        .cursor_pointer()
                                        .text_xs()
                                        .on_click(cx.listener(|this, _, _, cx| {
                                            let _ = this.worker.send(
                                                WorkerCommand::CheckForUpdates {
                                                    channel: ReleaseChannel::Stable,
                                                },
                                            );
                                            this.state.update_status =
                                                "Requesting the stable signed manifest…".into();
                                            cx.notify();
                                        }))
                                        .child("Check stable"),
                                )
                                .child(
                                    div()
                                        .id("check-beta-update")
                                        .rounded(window.theme().radius)
                                        .border_1()
                                        .border_color(colors.border)
                                        .px_3()
                                        .py_2()
                                        .cursor_pointer()
                                        .text_xs()
                                        .on_click(cx.listener(|this, _, _, cx| {
                                            let _ = this.worker.send(
                                                WorkerCommand::CheckForUpdates {
                                                    channel: ReleaseChannel::Beta,
                                                },
                                            );
                                            this.state.update_status =
                                                "Requesting the beta signed manifest…".into();
                                            cx.notify();
                                        }))
                                        .child("Check beta"),
                                )
                                .when(update_available, |this| {
                                    this.child(
                                        div()
                                            .id("download-verified-update")
                                            .rounded(window.theme().radius)
                                            .bg(colors.primary)
                                            .text_color(colors.primary_foreground)
                                            .px_3()
                                            .py_2()
                                            .cursor_pointer()
                                            .text_xs()
                                            .on_click(cx.listener(|this, _, _, cx| {
                                                let _ = this.worker.send(
                                                    WorkerCommand::DownloadAvailableUpdate,
                                                );
                                                this.state.update_status =
                                                    "Starting verified update download…".into();
                                                cx.notify();
                                            }))
                                            .child("Download + verify"),
                                    )
                                })
                                .when(update_staged, |this| {
                                    this.child(
                                        div()
                                            .id("install-verified-update")
                                            .rounded(window.theme().radius)
                                            .bg(colors.primary)
                                            .text_color(colors.primary_foreground)
                                            .px_3()
                                            .py_2()
                                            .cursor_pointer()
                                            .text_xs()
                                            .on_click(cx.listener(|this, _, _, cx| {
                                                let _ = this
                                                    .worker
                                                    .send(WorkerCommand::InstallStagedUpdate);
                                                this.state.update_status =
                                                    "Opening the verified platform installer…"
                                                        .into();
                                                cx.notify();
                                            }))
                                            .child("Install verified update"),
                                    )
                                }),
                        ),
                )
                .into_any_element(),
            WorkspaceSection::Library => div()
                .flex()
                .flex_col()
                .h_1_3()
                .p_4()
                .gap_2()
                .bg(colors.card)
                .child(
                    div()
                        .text_sm()
                        .font_weight(gpui::FontWeight::BOLD)
                        .child("Result library"),
                )
                .child(
                    div()
                        .text_xs()
                        .text_color(colors.muted_foreground)
                        .child("Select a job above to inspect progress, open its signed result, or attach completed B-roll to a reel."),
                )
                .child(
                    div()
                        .id("refresh-library-bottom")
                        .rounded(window.theme().radius)
                        .border_1()
                        .border_color(colors.border)
                        .px_3()
                        .py_2()
                        .cursor_pointer()
                        .text_xs()
                        .on_click(cx.listener(|this, _, _, cx| this.refresh_library(cx)))
                        .child("Refresh now"),
                )
                .into_any_element(),
            WorkspaceSection::Create => div()
                .id("create-workspace")
                .flex()
                .h_1_3()
                .overflow_y_scroll()
                .bg(colors.card)
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .w_1_2()
                        .p_4()
                        .gap_2()
                        .border_r_1()
                        .border_color(colors.border)
                        .child(
                            div()
                                .text_sm()
                                .font_weight(gpui::FontWeight::BOLD)
                                .child("Create reel"),
                        )
                        .child(self.reel_subject_field.clone())
                        .child(self.reel_script_field.clone())
                        .child(
                            div()
                                .flex()
                                .gap_2()
                                .child(self.reel_avatar_field.clone())
                                .child(self.reel_voice_field.clone()),
                        )
                        .when(!self.state.reel_avatars.is_empty(), |this| {
                            this.child(
                                div()
                                    .flex()
                                    .flex_col()
                                    .gap_1()
                                    .child(
                                        div()
                                            .text_xs()
                                            .text_color(colors.muted_foreground)
                                            .child("Avatars"),
                                    )
                                    .child(div().flex().flex_wrap().gap_1().children(
                                        self.state.reel_avatars.iter().map(|entry| {
                                            let value = entry.id.clone();
                                            let selected = self.state.reel_draft.avatar_id
                                                == entry.id;
                                            div()
                                                .id(SharedString::from(format!(
                                                    "avatar-{}",
                                                    entry.id
                                                )))
                                                .rounded(window.theme().radius)
                                                .border_1()
                                                .border_color(colors.border)
                                                .px_2()
                                                .py_1()
                                                .cursor_pointer()
                                                .text_xs()
                                                .bg(if selected {
                                                    colors.accent
                                                } else {
                                                    colors.background
                                                })
                                                .on_click(cx.listener(move |this, _, _, cx| {
                                                    this.apply_reel_avatar(value.clone(), cx)
                                                }))
                                                .child(entry.display.clone())
                                        }),
                                    )),
                            )
                        })
                        .when(!self.state.reel_voices.is_empty(), |this| {
                            this.child(
                                div()
                                    .flex()
                                    .flex_col()
                                    .gap_1()
                                    .child(
                                        div()
                                            .text_xs()
                                            .text_color(colors.muted_foreground)
                                            .child("Voices"),
                                    )
                                    .child(div().flex().flex_wrap().gap_1().children(
                                        self.state.reel_voices.iter().map(|entry| {
                                            let value = entry.id.clone();
                                            let selected = self.state.reel_draft.voice_name
                                                == entry.id;
                                            div()
                                                .id(SharedString::from(format!(
                                                    "voice-{}",
                                                    entry.id
                                                )))
                                                .rounded(window.theme().radius)
                                                .border_1()
                                                .border_color(colors.border)
                                                .px_2()
                                                .py_1()
                                                .cursor_pointer()
                                                .text_xs()
                                                .bg(if selected {
                                                    colors.accent
                                                } else {
                                                    colors.background
                                                })
                                                .on_click(cx.listener(move |this, _, _, cx| {
                                                    this.apply_reel_voice(value.clone(), cx)
                                                }))
                                                .child(entry.display.clone())
                                        }),
                                    )),
                            )
                        })
                        .when(!self.state.reel_caption_styles.is_empty(), |this| {
                            this.child(
                                div()
                                    .flex()
                                    .flex_col()
                                    .gap_1()
                                    .child(
                                        div()
                                            .text_xs()
                                            .text_color(colors.muted_foreground)
                                            .child("Caption styles"),
                                    )
                                    .child(div().flex().flex_wrap().gap_1().children(
                                        self.state.reel_caption_styles.iter().map(|entry| {
                                            let value = entry.id.clone();
                                            let selected = self.state.reel_draft.caption_style
                                                == entry.id;
                                            div()
                                                .id(SharedString::from(format!(
                                                    "caption-style-{}",
                                                    entry.id
                                                )))
                                                .rounded(window.theme().radius)
                                                .border_1()
                                                .border_color(colors.border)
                                                .px_2()
                                                .py_1()
                                                .cursor_pointer()
                                                .text_xs()
                                                .bg(if selected {
                                                    colors.accent
                                                } else {
                                                    colors.background
                                                })
                                                .on_click(cx.listener(move |this, _, _, cx| {
                                                    this.apply_reel_caption_style(
                                                        value.clone(),
                                                        cx,
                                                    )
                                                }))
                                                .child(entry.display.clone())
                                        }),
                                    )),
                            )
                        })
                        .child(
                            div()
                                .flex()
                                .items_center()
                                .gap_2()
                                .child(
                                    div()
                                        .id("upload-reel-recording")
                                        .rounded(window.theme().radius)
                                        .border_1()
                                        .border_color(colors.border)
                                        .px_3()
                                        .py_2()
                                        .cursor_pointer()
                                        .text_xs()
                                        .on_click(cx.listener(|this, _, window, cx| {
                                            this.choose_upload(
                                                UploadTarget::ReelRecording,
                                                window,
                                                cx,
                                            )
                                        }))
                                        .child(if reel_recording_ready {
                                            "Change recording"
                                        } else {
                                            "Choose recording"
                                        }),
                                )
                                .when(reel_recording_ready, |this| {
                                    this.child(
                                        div()
                                            .text_xs()
                                            .text_color(colors.primary)
                                            .child("Upload ready ✓"),
                                    )
                                })
                                .when_some(attached_broll_key.clone(), |this, _| {
                                    this.child(
                                        div()
                                            .text_xs()
                                            .text_color(colors.primary)
                                            .child("B-roll attached ✓"),
                                    )
                                }),
                        )
                        .child(
                            div()
                                .id("submit-reel")
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .bg(if reel_generation_allowed {
                                    colors.primary
                                } else {
                                    colors.muted
                                })
                                .text_color(if reel_generation_allowed {
                                    colors.primary_foreground
                                } else {
                                    colors.muted_foreground
                                })
                                .text_xs()
                                .when(reel_generation_allowed, |button| {
                                    button.on_click(
                                        cx.listener(|this, _, _, cx| this.submit_reel(cx)),
                                    )
                                })
                                .child(if reel_generation_allowed {
                                    "Generate reel"
                                } else {
                                    "Pilot access required"
                                }),
                        ),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .w_1_2()
                        .p_4()
                        .gap_2()
                        .child(
                            div()
                                .text_sm()
                                .font_weight(gpui::FontWeight::BOLD)
                                .child("Generate AI B-roll"),
                        )
                        .child(self.broll_prompt_field.clone())
                        .child(
                            div()
                                .flex()
                                .gap_2()
                                .child(
                                    div()
                                        .id("broll-mode-t2v")
                                        .rounded(window.theme().radius)
                                        .px_3()
                                        .py_2()
                                        .cursor_pointer()
                                        .border_1()
                                        .border_color(colors.border)
                                        .bg(if broll_mode == BrollMode::TextToVideo {
                                            colors.accent
                                        } else {
                                            colors.card
                                        })
                                        .text_xs()
                                        .on_click(cx.listener(|this, _, _, cx| {
                                            this.set_broll_mode(
                                                BrollMode::TextToVideo,
                                                cx,
                                            )
                                        }))
                                        .child("Text to video"),
                                )
                                .child(
                                    div()
                                        .id("broll-mode-i2v")
                                        .rounded(window.theme().radius)
                                        .px_3()
                                        .py_2()
                                        .cursor_pointer()
                                        .border_1()
                                        .border_color(colors.border)
                                        .bg(if broll_mode == BrollMode::ImageToVideo {
                                            colors.accent
                                        } else {
                                            colors.card
                                        })
                                        .text_xs()
                                        .on_click(cx.listener(|this, _, _, cx| {
                                            this.set_broll_mode(
                                                BrollMode::ImageToVideo,
                                                cx,
                                            )
                                        }))
                                        .child("Image to video"),
                                ),
                        )
                        .when(
                            broll_mode == BrollMode::ImageToVideo,
                            |this| {
                                this.child(
                                    div()
                                        .id("upload-broll-reference")
                                        .rounded(window.theme().radius)
                                        .border_1()
                                        .border_color(colors.border)
                                        .px_3()
                                        .py_2()
                                        .cursor_pointer()
                                        .text_xs()
                                        .on_click(cx.listener(|this, _, window, cx| {
                                            this.choose_upload(
                                                UploadTarget::BrollReference,
                                                window,
                                                cx,
                                            )
                                        }))
                                        .child(if broll_image_ready {
                                            "Reference image ready ✓"
                                        } else {
                                            "Choose reference image"
                                        }),
                                )
                            },
                        )
                        .child(
                            div()
                                .id("submit-broll")
                                .rounded(window.theme().radius)
                                .px_3()
                                .py_2()
                                .cursor_pointer()
                                .bg(if broll_generation_allowed {
                                    colors.primary
                                } else {
                                    colors.muted
                                })
                                .text_color(if broll_generation_allowed {
                                    colors.primary_foreground
                                } else {
                                    colors.muted_foreground
                                })
                                .text_xs()
                                .when(broll_generation_allowed, |button| {
                                    button.on_click(
                                        cx.listener(|this, _, _, cx| this.submit_broll(cx)),
                                    )
                                })
                                .child(if broll_generation_allowed {
                                    "Generate B-roll"
                                } else {
                                    "Pilot access required"
                                }),
                        )
                        .when(!activity.is_empty(), |this| {
                            this.child(
                                div()
                                    .text_xs()
                                    .text_color(colors.muted_foreground)
                                    .child(activity.clone()),
                            )
                        })
                        .when(!operation_error.is_empty(), |this| {
                            this.child(
                                div()
                                    .text_xs()
                                    .text_color(colors.destructive)
                                    .child(operation_error.clone()),
                            )
                        }),
                )
                .into_any_element(),
        };

        div()
            .flex()
            .flex_col()
            .size_full()
            .bg(colors.background)
            .text_color(colors.foreground)
            .child(
                div()
                    .flex()
                    .items_center()
                    .justify_between()
                    .h_10()
                    .px_4()
                    .border_b_1()
                    .border_color(colors.border)
                    .child(
                        div()
                            .text_sm()
                            .font_weight(gpui::FontWeight::BOLD)
                            .child(crate::app::PRODUCT_NAME),
                    )
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap_2()
                            .child(
                                div()
                                    .text_xs()
                                    .text_color(
                                        if self.state.connection == ConnectionState::Connected {
                                            colors.primary
                                        } else {
                                            colors.muted_foreground
                                        },
                                    )
                                    .child(connection_label),
                            )
                            .child(nav_item("Create", WorkspaceSection::Create))
                            .child(nav_item("Library", WorkspaceSection::Library))
                            .child(nav_item("Editor", WorkspaceSection::Editor))
                            .child(nav_item("Media", WorkspaceSection::MediaGateway))
                            .child(nav_item("Governance", WorkspaceSection::Governance))
                            .child(nav_item("Trends", WorkspaceSection::Trends))
                            .child(nav_item("Signals", WorkspaceSection::Signals))
                            .child(nav_item("Captions", WorkspaceSection::Captions))
                            .child(nav_item("Blueprints", WorkspaceSection::Blueprints))
                            .child(nav_item("Effects", WorkspaceSection::Effects))
                            .child(nav_item("Workflows", WorkspaceSection::Workflows))
                            .child(nav_item("Settings", WorkspaceSection::Settings)),
                    ),
            )
            .child(
                div()
                    .flex()
                    .h_2_3()
                    .border_b_1()
                    .border_color(colors.border)
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .w_1_4()
                            .h_full()
                            .p_4()
                            .gap_3()
                            .border_r_1()
                            .border_color(colors.sidebar_border)
                            .bg(colors.sidebar)
                            .child(
                                div()
                                    .text_sm()
                                    .font_weight(gpui::FontWeight::BOLD)
                                    .child("Library"),
                            )
                            .child(
                                div()
                                    .text_xs()
                                    .text_color(colors.muted_foreground)
                                    .child("Reels and AI B-roll generated by this account."),
                            )
                            .children(library_items),
                    )
                    .child(div().w_1_2().h_full().bg(colors.background).child(preview))
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .w_1_4()
                            .h_full()
                            .p_4()
                            .gap_3()
                            .border_l_1()
                            .border_color(colors.border)
                            .bg(colors.card)
                            .child(
                                div()
                                    .text_sm()
                                    .font_weight(gpui::FontWeight::BOLD)
                                    .child("Connection"),
                            )
                            .child(
                                div()
                                    .text_xs()
                                    .text_color(colors.muted_foreground)
                                    .child(api_base),
                            )
                            .child(div().text_xs().text_color(colors.muted_foreground).child(
                                "API credentials stay in the operating-system credential store.",
                            ))
                            .when(!connection_error.is_empty(), |this| {
                                this.child(
                                    div()
                                        .text_xs()
                                        .text_color(colors.destructive)
                                        .child(connection_error),
                                )
                            })
                            .child(
                                div()
                                    .id("refresh-library")
                                    .rounded(window.theme().radius)
                                    .border_1()
                                    .border_color(colors.border)
                                    .px_3()
                                    .py_2()
                                    .cursor_pointer()
                                    .text_xs()
                                    .on_click(
                                        cx.listener(|this, _, _, cx| this.refresh_library(cx)),
                                    )
                                    .child("Refresh library"),
                            )
                            .child(
                                div()
                                    .text_sm()
                                    .font_weight(gpui::FontWeight::BOLD)
                                    .child("Reel attachment"),
                            )
                            .child(div().text_xs().text_color(colors.muted_foreground).child(
                                match attached_broll_key {
                                    Some(key) => format!("B-roll attached: {key}"),
                                    None => {
                                        "Select a completed AI B-roll clip to attach it.".into()
                                    }
                                },
                            )),
                    ),
            )
            .child(workspace_bottom)
    }
}
