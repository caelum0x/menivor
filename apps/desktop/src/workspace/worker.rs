//! Background HTTP/upload/polling worker for the native GPUI client.
//!
//! The worker owns the authenticated transport and is the only place that may
//! block on network or file I/O. GPUI sends immutable commands and receives
//! small snapshots over standard channels.

use std::collections::HashMap;
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::thread;
use std::time::{Duration, Instant};

use crate::api::{ApiClient, ApiFailure, BrollGenerationDto, JobDto, POLL_INTERVAL};
use crate::config::Preferences;
use crate::media::playback::{open_signed_preview, open_verified_local_media};
use crate::media::toolchain::inspect_release_toolchain;
use crate::security::system_credential_store;
use crate::updater::{self, AvailableUpdate, StagedUpdate};
use crate::workspace::local_executor::{DesktopLocalExecutor, LocalExecutorEvent};
use crate::workspace::editor_handoff;
use crate::workspace::local_runtime;
use crate::workspace::persistence;
use crate::workspace::source_analysis::analyze_editor_source;
use crate::workspace::{JobKind, JobSnapshot, JobState, WorkerCommand, WorkerUpdate};

const COMMAND_WAIT: Duration = Duration::from_millis(250);

pub(crate) struct WorkerChannels {
    pub commands: Sender<WorkerCommand>,
    pub updates: Receiver<WorkerUpdate>,
}

#[derive(Clone, Debug)]
struct PollTarget {
    kind: JobKind,
    next_poll: Instant,
}

#[derive(Clone, Debug)]
struct MediaPollTarget {
    next_poll: Instant,
    /// `true` for `/media/audio` jobs, `false` for `/media/videos` jobs.
    audio: bool,
}

pub(crate) fn start_worker() -> WorkerChannels {
    let (command_sender, command_receiver) = mpsc::channel();
    let (update_sender, update_receiver) = mpsc::channel();
    thread::Builder::new()
        .name("reelforge-api-worker".into())
        .spawn(move || worker_loop(command_receiver, update_sender))
        .expect("failed to start ReelForge API worker");
    WorkerChannels {
        commands: command_sender,
        updates: update_receiver,
    }
}

fn worker_loop(commands: Receiver<WorkerCommand>, updates: Sender<WorkerUpdate>) {
    match inspect_release_toolchain() {
        Ok(message) => send(
            &updates,
            WorkerUpdate::MediaToolchainInspected {
                ready: true,
                message,
            },
        ),
        Err(message) => send(
            &updates,
            WorkerUpdate::MediaToolchainInspected {
                ready: false,
                message,
            },
        ),
    }
    // Open durable local execution synchronously before receiving any command.
    // A corrupt/unavailable snapshot fails only the local executor; cloud/API
    // workflows remain available and the UI receives the exact recovery error.
    let mut local_runtime = match local_runtime::open_default() {
        Ok(mut runtime) => {
            send(
                &updates,
                WorkerUpdate::LocalRuntimeRestored {
                    generations: runtime.generations(),
                },
            );
            runtime.resume(&mut |event| send_local_event(&updates, event));
            Some(runtime)
        }
        Err(message) => {
            send(&updates, WorkerUpdate::LocalRuntimeFailed { message });
            None
        }
    };
    let mut client: Option<ApiClient> = None;
    let mut polling: HashMap<String, PollTarget> = HashMap::new();
    let mut media_polling: HashMap<String, MediaPollTarget> = HashMap::new();
    let mut available_update: Option<AvailableUpdate> = None;
    let mut staged_update: Option<StagedUpdate> = match updater::load_staged_update() {
        Ok(staged) => staged,
        Err(message) => {
            send(
                &updates,
                WorkerUpdate::UpdateFailed {
                    operation: "restore staged update".into(),
                    message,
                },
            );
            None
        }
    };
    if let Some(staged) = staged_update.as_ref() {
        send(
            &updates,
            WorkerUpdate::UpdateStaged {
                version: staged.version.clone(),
                artifact: updater::staged_path_label(staged),
            },
        );
    }

    loop {
        match commands.recv_timeout(COMMAND_WAIT) {
            Ok(WorkerCommand::Shutdown) | Err(RecvTimeoutError::Disconnected) => return,
            Ok(command) => handle_command(
                command,
                &mut client,
                &mut polling,
                &mut media_polling,
                &mut local_runtime,
                &mut available_update,
                &mut staged_update,
                &updates,
            ),
            Err(RecvTimeoutError::Timeout) => {}
        }
        poll_due_jobs(client.as_ref(), &mut polling, &updates);
        poll_due_media_videos(client.as_ref(), &mut media_polling, &updates);
    }
}

fn handle_command(
    command: WorkerCommand,
    client: &mut Option<ApiClient>,
    polling: &mut HashMap<String, PollTarget>,
    media_polling: &mut HashMap<String, MediaPollTarget>,
    local_runtime: &mut Option<DesktopLocalExecutor>,
    available_update: &mut Option<AvailableUpdate>,
    staged_update: &mut Option<StagedUpdate>,
    updates: &Sender<WorkerUpdate>,
) {
    match command {
        WorkerCommand::LoadConfiguration => {
            let preferences = match Preferences::load() {
                Ok(preferences) => preferences,
                Err(error) => {
                    connection_failed(updates, format!("Could not load API settings: {error}"));
                    return;
                }
            };
            let api_base = preferences.normalized_api_base();
            send(
                updates,
                WorkerUpdate::ConfigurationLoaded {
                    api_base: api_base.clone(),
                    editor_path: preferences.editor_path.clone(),
                    use_local_engine: preferences.use_local_engine,
                },
            );
            if preferences.use_local_engine {
                // Local engine: no API key required — use a placeholder so
                // ApiClient::new passes its non-empty check. The sidecar
                // ignores the header.
                media_polling.clear();
                configure_client(api_base, "local".to_owned(), client, polling, updates);
                return;
            }
            match system_credential_store().load_api_key() {
                Ok(Some(api_key)) => {
                    media_polling.clear();
                    configure_client(api_base, api_key, client, polling, updates)
                }
                Ok(None) => send(updates, WorkerUpdate::Disconnected),
                Err(error) => connection_failed(updates, error),
            }
        }
        WorkerCommand::LoadWorkspace => match persistence::load() {
            Ok(Some(cache)) => send(updates, WorkerUpdate::WorkspaceRestored(cache)),
            Ok(None) => {}
            Err(error) => operation_failed(
                updates,
                "restore workspace",
                ApiFailure {
                    kind: crate::api::ApiFailureKind::Request,
                    status: None,
                    message: error.to_string(),
                },
            ),
        },
        WorkerCommand::PersistWorkspace(cache) => {
            if let Err(error) = persistence::save(&cache) {
                operation_failed(
                    updates,
                    "save workspace",
                    ApiFailure {
                        kind: crate::api::ApiFailureKind::Request,
                        status: None,
                        message: error.to_string(),
                    },
                );
            }
        }
        WorkerCommand::SaveConfiguration {
            base_url,
            api_key,
            editor_path,
            use_local_engine,
        } => {
            let preferences = Preferences {
                api_base_url: base_url,
                editor_path: editor_path.trim().to_owned(),
                use_local_engine,
            };
            if let Err(error) = preferences.save() {
                connection_failed(updates, format!("Could not save API settings: {error}"));
                return;
            }
            let api_base = preferences.normalized_api_base();
            send(
                updates,
                WorkerUpdate::ConfigurationLoaded {
                    api_base: api_base.clone(),
                    editor_path: preferences.editor_path.clone(),
                    use_local_engine,
                },
            );
            media_polling.clear();
            if use_local_engine {
                // Local engine: no API key required.
                configure_client(api_base, "local".to_owned(), client, polling, updates);
                return;
            }
            let credentials = system_credential_store();
            let resolved_api_key = match api_key {
                Some(api_key) if !api_key.trim().is_empty() => {
                    let api_key = api_key.trim().to_owned();
                    if let Err(error) = credentials.save_api_key(&api_key) {
                        connection_failed(updates, error);
                        return;
                    }
                    Some(api_key)
                }
                _ => match credentials.load_api_key() {
                    Ok(api_key) => api_key,
                    Err(error) => {
                        connection_failed(updates, error);
                        return;
                    }
                },
            };
            let Some(api_key) = resolved_api_key else {
                connection_failed(updates, "Enter an API key before connecting.");
                return;
            };
            configure_client(api_base, api_key, client, polling, updates);
        }
        WorkerCommand::ClearCredentials => {
            if let Err(error) = system_credential_store().clear_api_key() {
                connection_failed(updates, error);
                return;
            }
            polling.clear();
            media_polling.clear();
            *client = None;
            send(updates, WorkerUpdate::Disconnected);
        }
        WorkerCommand::CheckConnection => check_connection(client.as_ref(), updates),
        WorkerCommand::CheckForUpdates { channel } => {
            *available_update = None;
            send(updates, WorkerUpdate::UpdateChecking { channel });
            match updater::check_for_update(channel) {
                Ok(Some(update)) => {
                    send(
                        updates,
                        WorkerUpdate::UpdateAvailable {
                            channel,
                            version: update.release.version.clone(),
                            notes_url: update.release.notes_url.clone(),
                            size_bytes: update.artifact.size_bytes,
                        },
                    );
                    *available_update = Some(update);
                }
                Ok(None) => {
                    *available_update = None;
                    send(
                        updates,
                        WorkerUpdate::UpdateCurrent {
                            channel,
                            version: env!("CARGO_PKG_VERSION").into(),
                        },
                    );
                }
                Err(message) => send(
                    updates,
                    WorkerUpdate::UpdateFailed {
                        operation: "check for updates".into(),
                        message,
                    },
                ),
            }
        }
        WorkerCommand::DownloadAvailableUpdate => {
            let Some(update) = available_update.as_ref() else {
                send(
                    updates,
                    WorkerUpdate::UpdateFailed {
                        operation: "download update".into(),
                        message: "Check for an available update first.".into(),
                    },
                );
                return;
            };
            send(
                updates,
                WorkerUpdate::UpdateDownloadStarted {
                    version: update.release.version.clone(),
                },
            );
            match updater::download_update(update) {
                Ok(staged) => {
                    send(
                        updates,
                        WorkerUpdate::UpdateStaged {
                            version: staged.version.clone(),
                            artifact: updater::staged_path_label(&staged),
                        },
                    );
                    *staged_update = Some(staged);
                    *available_update = None;
                }
                Err(message) => send(
                    updates,
                    WorkerUpdate::UpdateFailed {
                        operation: "download and verify update".into(),
                        message,
                    },
                ),
            }
        }
        WorkerCommand::InstallStagedUpdate => {
            let Some(staged) = staged_update.as_ref() else {
                send(
                    updates,
                    WorkerUpdate::UpdateFailed {
                        operation: "install update".into(),
                        message: "Download and verify an update first.".into(),
                    },
                );
                return;
            };
            match updater::install_update(staged) {
                Ok(()) => send(
                    updates,
                    WorkerUpdate::UpdateInstallerLaunched {
                        version: staged.version.clone(),
                    },
                ),
                Err(message) => send(
                    updates,
                    WorkerUpdate::UpdateFailed {
                        operation: "launch verified installer".into(),
                        message,
                    },
                ),
            }
        }
        WorkerCommand::RefreshLibrary => refresh_library(client.as_ref(), updates),
        WorkerCommand::AnalyzeEditorSource { request_id, path } => {
            match analyze_editor_source(request_id.clone(), path) {
                Ok(analysis) => send(updates, WorkerUpdate::EditorSourceAnalyzed(analysis)),
                Err(message) => send(
                    updates,
                    WorkerUpdate::EditorSourceAnalysisFailed {
                        request_id,
                        message,
                    },
                ),
            }
        }
        WorkerCommand::SubmitLocalRender(request) => {
            let Some(runtime) = local_runtime.as_mut() else {
                operation_failed(
                    updates,
                    "render locally",
                    ApiFailure {
                        kind: crate::api::ApiFailureKind::Request,
                        status: None,
                        message: "The durable local executor is unavailable.".into(),
                    },
                );
                return;
            };
            runtime.submit(request, &mut |event| send_local_event(updates, event));
        }
        WorkerCommand::OpenLocalArtifact { task_id } => {
            let Some(runtime) = local_runtime.as_ref() else {
                operation_failed(
                    updates,
                    "open local render",
                    ApiFailure {
                        kind: crate::api::ApiFailureKind::Request,
                        status: None,
                        message: "The durable local executor is unavailable.".into(),
                    },
                );
                return;
            };
            match runtime.resolve_verified_artifact_path(&task_id) {
                Ok(Some(path)) => {
                    if let Err(failure) = open_verified_local_media(&path) {
                        operation_failed(updates, "open local render", failure);
                    }
                }
                Ok(None) => operation_failed(
                    updates,
                    "open local render",
                    ApiFailure {
                        kind: crate::api::ApiFailureKind::InvalidResponse,
                        status: None,
                        message: "This local job has no verified artifact.".into(),
                    },
                ),
                Err(message) => operation_failed(
                    updates,
                    "open local render",
                    ApiFailure {
                        kind: crate::api::ApiFailureKind::InvalidResponse,
                        status: None,
                        message,
                    },
                ),
            }
        }
        WorkerCommand::RefreshMediaWallet => refresh_media_wallet(client.as_ref(), updates),
        WorkerCommand::RefreshWalletSources => refresh_wallet_sources(client.as_ref(), updates),
        WorkerCommand::RefreshWalletSourceBalance { source_account_id } => {
            refresh_wallet_source_balance(client.as_ref(), &source_account_id, updates)
        }
        WorkerCommand::RefreshWalletReceiveAddress { source_account_id } => {
            refresh_wallet_receive_address(client.as_ref(), &source_account_id, updates)
        }
        WorkerCommand::ResolveWalletRecipient { handle } => {
            resolve_wallet_recipient(client.as_ref(), &handle, updates)
        }
        WorkerCommand::ReviewWalletTransfer {
            source_account_id,
            recipient_handle,
            saved_recipient_id,
            amount_micros,
            idempotency_key,
            submitted,
        } => review_wallet_transfer(
            client.as_ref(),
            &source_account_id,
            &recipient_handle,
            saved_recipient_id.as_deref(),
            amount_micros,
            &idempotency_key,
            submitted,
            updates,
        ),
        WorkerCommand::SendWalletTransfer {
            source_account_id,
            challenge_id,
            recipient_handle,
            amount_micros,
            idempotency_key,
            workspace,
        } => {
            if let Err(error) = persistence::save(&workspace) {
                operation_failed(
                    updates,
                    "preserve transfer retry key",
                    ApiFailure {
                        kind: crate::api::ApiFailureKind::Request,
                        status: None,
                        message: error.to_string(),
                    },
                );
                return;
            }
            send_wallet_transfer(
                client.as_ref(),
                &source_account_id,
                &challenge_id,
                &recipient_handle,
                amount_micros,
                &idempotency_key,
                updates,
            )
        }
        WorkerCommand::RecoverWalletTransfer { transfer_id } => {
            recover_wallet_transfer(client.as_ref(), &transfer_id, updates)
        }
        WorkerCommand::RefreshSavedRecipients { source_account_id } => {
            refresh_saved_recipients(client.as_ref(), &source_account_id, updates)
        }
        WorkerCommand::SaveWalletRecipient {
            source_account_id,
            recipient_handle,
        } => save_wallet_recipient(
            client.as_ref(),
            &source_account_id,
            &recipient_handle,
            updates,
        ),
        WorkerCommand::DeleteWalletRecipient {
            source_account_id,
            saved_recipient_id,
        } => delete_wallet_recipient(
            client.as_ref(),
            &source_account_id,
            &saved_recipient_id,
            updates,
        ),
        WorkerCommand::RefreshMediaModels { modality } => {
            refresh_media_models(client.as_ref(), modality.as_deref(), updates)
        }
        WorkerCommand::GenerateMediaImage { model, prompt } => {
            generate_media_image(client.as_ref(), &model, &prompt, updates)
        }
        WorkerCommand::LoadMoreMediaGenerations { offset } => {
            let Some(client) = require_client(client.as_ref(), "load older generations", updates)
            else {
                return;
            };
            match client.list_media_generations_page(offset) {
                Ok(page) => send(
                    updates,
                    WorkerUpdate::MediaGenerationsPage {
                        offset,
                        generations: page.generations,
                        has_more: page.has_more,
                    },
                ),
                Err(failure) => operation_failed(updates, "load older generations", failure),
            }
        }
        WorkerCommand::GenerateMediaAudio {
            model,
            prompt,
            instrumental,
        } => generate_media_audio(
            client.as_ref(),
            &model,
            &prompt,
            instrumental,
            media_polling,
            updates,
        ),
        WorkerCommand::GenerateMediaVideo {
            model,
            prompt,
            image_url,
            duration,
            identity_passport_id,
            identity_version,
        } => generate_media_video(
            client.as_ref(),
            &model,
            &prompt,
            &image_url,
            duration,
            &identity_passport_id,
            identity_version,
            media_polling,
            updates,
        ),
        WorkerCommand::LookupGeneration { id } => lookup_generation(client.as_ref(), &id, updates),
        WorkerCommand::ExportGenerationProvenance { id, path } => {
            export_generation_provenance(client.as_ref(), &id, &path, updates)
        }
        WorkerCommand::Upload {
            target,
            path,
            content_type,
        } => {
            send(updates, WorkerUpdate::UploadStarted(target));
            let Some(client) = require_client(client.as_ref(), "upload", updates) else {
                return;
            };
            match client.upload_file(&path, &content_type) {
                Ok(uploaded) => send(
                    updates,
                    WorkerUpdate::UploadComplete {
                        target,
                        key: uploaded.key,
                    },
                ),
                Err(failure) => operation_failed(updates, "upload", failure),
            }
        }
        WorkerCommand::SubmitReel {
            draft,
            idempotency_key,
        } => {
            let Some(client) = require_client(client.as_ref(), "create reel", updates) else {
                return;
            };
            match client.create_reel(&draft, &idempotency_key) {
                Ok(job) => {
                    let id = job.job_id;
                    let correlation_id = job.correlation_id;
                    send(
                        updates,
                        WorkerUpdate::Queued {
                            id: id.clone(),
                            kind: JobKind::Reel,
                            correlation_id,
                        },
                    );
                    polling.insert(
                        id,
                        PollTarget {
                            kind: JobKind::Reel,
                            next_poll: Instant::now(),
                        },
                    );
                }
                Err(failure) => operation_failed(updates, "create reel", failure),
            }
        }
        WorkerCommand::SubmitBroll {
            draft,
            idempotency_key,
        } => {
            let Some(client) = require_client(client.as_ref(), "generate B-roll", updates) else {
                return;
            };
            match client.create_broll(&draft, &idempotency_key) {
                Ok(job) => {
                    let id = job.generation_id;
                    let correlation_id = job.correlation_id;
                    send(
                        updates,
                        WorkerUpdate::Queued {
                            id: id.clone(),
                            kind: JobKind::Broll,
                            correlation_id,
                        },
                    );
                    polling.insert(
                        id,
                        PollTarget {
                            kind: JobKind::Broll,
                            next_poll: Instant::now(),
                        },
                    );
                }
                Err(failure) => operation_failed(updates, "generate B-roll", failure),
            }
        }
        WorkerCommand::SubmitTimelineExport {
            source_job_id,
            timeline,
            idempotency_key,
        } => {
            let Some(client) = require_client(client.as_ref(), "export timeline", updates) else {
                return;
            };
            match client.create_timeline_export(&source_job_id, &timeline, &idempotency_key) {
                Ok(job) => {
                    let id = job.job_id;
                    send(
                        updates,
                        WorkerUpdate::TimelineExportQueued {
                            id: id.clone(),
                            source_job_id,
                            output_duration_ms: (job.output_duration_s * 1000.0).round() as u64,
                            segments: job.segments,
                            overlays: job.overlays,
                            correlation_id: job.correlation_id,
                        },
                    );
                    polling.insert(
                        id,
                        PollTarget {
                            kind: JobKind::Reel,
                            next_poll: Instant::now(),
                        },
                    );
                }
                Err(failure) => operation_failed(updates, "export timeline", failure),
            }
        }
        WorkerCommand::DeleteReel { job_id } => {
            let Some(client) = require_client(client.as_ref(), "delete reel", updates) else {
                return;
            };
            match client.delete_reel(&job_id) {
                Ok(()) => {
                    polling.remove(&job_id);
                    send(updates, WorkerUpdate::ReelDeleted { job_id });
                }
                Err(failure) => operation_failed(updates, "delete reel", failure),
            }
        }
        WorkerCommand::PublishReel {
            job_id,
            idempotency_key,
        } => {
            let Some(client) = require_client(client.as_ref(), "publish reel", updates) else {
                return;
            };
            match client.publish_reel(&job_id, &idempotency_key) {
                Ok(result) => send(
                    updates,
                    WorkerUpdate::ReelPublished {
                        job_id,
                        summary: result.summary(),
                    },
                ),
                Err(failure) => operation_failed(updates, "publish reel", failure),
            }
        }
        WorkerCommand::RefreshReelCatalog => refresh_reel_catalog(client.as_ref(), updates),
        WorkerCommand::PollJob { id, kind } => {
            polling.insert(
                id,
                PollTarget {
                    kind,
                    next_poll: Instant::now(),
                },
            );
        }
        WorkerCommand::OpenPreview { url } => {
            if let Err(failure) = open_signed_preview(&url) {
                operation_failed(updates, "open preview", failure);
            }
        }
        WorkerCommand::OpenJobInEditor {
            job_id,
            kind,
            result_url,
        } => open_job_in_editor(client.as_ref(), &job_id, kind, &result_url, updates),
        WorkerCommand::LaunchEditor => match editor_handoff::launch_editor() {
            Ok(()) => send(
                updates,
                WorkerUpdate::EditorOpened {
                    message: "Opening the Menivor editor…".into(),
                },
            ),
            Err(message) => send(updates, WorkerUpdate::EditorOpenFailed { message }),
        },
        WorkerCommand::SaveResultToDisk { url, dest } => {
            let Some(client) = require_client(client.as_ref(), "save result", updates) else {
                return;
            };
            match client.download_to_path(&url, &dest) {
                Ok(()) => send(
                    updates,
                    WorkerUpdate::ResultSaved {
                        path: dest.display().to_string(),
                    },
                ),
                Err(failure) => send(
                    updates,
                    WorkerUpdate::ResultSaveFailed {
                        message: failure.message,
                    },
                ),
            }
        }
        WorkerCommand::Shutdown => unreachable!(),
    }
}

fn send_local_event(updates: &Sender<WorkerUpdate>, event: LocalExecutorEvent) {
    send(
        updates,
        WorkerUpdate::LocalRuntimeUpdated {
            generations: event.generations,
            message: event.message,
            failed: event.failed,
        },
    );
}

fn configure_client(
    base_url: String,
    api_key: String,
    client: &mut Option<ApiClient>,
    polling: &mut HashMap<String, PollTarget>,
    updates: &Sender<WorkerUpdate>,
) {
    polling.clear();
    match ApiClient::new(&base_url, &api_key) {
        Ok(configured) => {
            *client = Some(configured);
            check_connection(client.as_ref(), updates);
        }
        Err(failure) => {
            *client = None;
            send(updates, WorkerUpdate::ConnectionFailed(failure));
        }
    }
}

fn connection_failed(updates: &Sender<WorkerUpdate>, message: impl Into<String>) {
    send(
        updates,
        WorkerUpdate::ConnectionFailed(ApiFailure {
            kind: crate::api::ApiFailureKind::Request,
            status: None,
            message: message.into(),
        }),
    );
}

fn check_connection(client: Option<&ApiClient>, updates: &Sender<WorkerUpdate>) {
    send(updates, WorkerUpdate::ConnectionChecking);
    let Some(client) = require_client(client, "connect", updates) else {
        return;
    };
    match client.check_connection() {
        Ok(()) => match client.get_generation_capabilities() {
            Ok((mode, reels, broll)) => {
                send(updates, WorkerUpdate::Connected);
                send(updates, WorkerUpdate::Capabilities { mode, reels, broll });
                refresh_reel_catalog(Some(client), updates);
                refresh_library(Some(client), updates);
            }
            Err(failure) => send(updates, WorkerUpdate::ConnectionFailed(failure)),
        },
        Err(failure) => send(updates, WorkerUpdate::ConnectionFailed(failure)),
    }
}

fn refresh_library(client: Option<&ApiClient>, updates: &Sender<WorkerUpdate>) {
    let Some(client) = require_client(client, "refresh library", updates) else {
        return;
    };
    let reels = match client.list_reels() {
        Ok(rows) => rows,
        Err(failure) => {
            operation_failed(updates, "refresh reel library", failure);
            return;
        }
    };
    let broll = match client.list_broll() {
        Ok(rows) => rows,
        Err(failure) => {
            operation_failed(updates, "refresh B-roll library", failure);
            return;
        }
    };
    let broll_ids = broll
        .iter()
        .map(|row| row.generation_id.as_str())
        .collect::<std::collections::HashSet<_>>();
    let mut jobs = reels
        .into_iter()
        .filter(|row| row.kind != "broll_gen" && !broll_ids.contains(row.job_id.as_str()))
        .map(reel_snapshot)
        .collect::<Vec<_>>();
    jobs.extend(broll.into_iter().map(broll_snapshot));
    send(updates, WorkerUpdate::Library(jobs));
}

/// Load the reel pickers after connecting. Catalog reads are best-effort: an
/// individual list that a server does not expose degrades to an empty picker
/// (the create form keeps its free-text fallback) rather than failing connect.
fn refresh_reel_catalog(client: Option<&ApiClient>, updates: &Sender<WorkerUpdate>) {
    let Some(client) = client else { return };
    let avatars = client.list_avatars().unwrap_or_default();
    let voices = client.list_voices().unwrap_or_default();
    let caption_styles = client.list_caption_styles().unwrap_or_default();
    if avatars.is_empty() && voices.is_empty() && caption_styles.is_empty() {
        return;
    }
    send(
        updates,
        WorkerUpdate::ReelCatalog {
            avatars,
            voices,
            caption_styles,
        },
    );
}

fn refresh_media_wallet(client: Option<&ApiClient>, updates: &Sender<WorkerUpdate>) {
    let Some(client) = require_client(client, "refresh media wallet", updates) else {
        return;
    };
    let credits = match client.get_media_credits() {
        Ok(credits) => credits,
        Err(failure) => {
            operation_failed(updates, "refresh media credits", failure);
            return;
        }
    };
    let usage = match client.get_media_usage() {
        Ok(usage) => usage,
        Err(failure) => {
            operation_failed(updates, "refresh media usage", failure);
            return;
        }
    };
    let (generations, generations_has_more) = match client.list_media_generations() {
        Ok(page) => (page.generations, page.has_more),
        Err(failure) => {
            operation_failed(updates, "refresh media generations", failure);
            return;
        }
    };
    let identities = match client.list_media_identities() {
        Ok(identities) => identities,
        Err(failure) => {
            operation_failed(updates, "refresh media identities", failure);
            return;
        }
    };
    send(updates, WorkerUpdate::MediaIdentities(identities));
    send(
        updates,
        WorkerUpdate::MediaWallet {
            credits,
            usage,
            generations,
            generations_has_more,
        },
    );
}

fn resolve_wallet_recipient(
    client: Option<&ApiClient>,
    handle: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "resolve transfer recipient", updates) else {
        return;
    };
    match client.resolve_wallet_recipient(handle) {
        Ok(recipient) => send(updates, WorkerUpdate::WalletRecipientResolved(recipient)),
        Err(failure) => operation_failed(updates, "resolve transfer recipient", failure),
    }
}

fn send_wallet_transfer(
    client: Option<&ApiClient>,
    source_account_id: &str,
    challenge_id: &str,
    recipient_handle: &str,
    amount_micros: u64,
    idempotency_key: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "send AI tokens", updates) else {
        return;
    };
    match client.send_wallet_transfer(
        source_account_id,
        challenge_id,
        recipient_handle,
        amount_micros,
        idempotency_key,
    ) {
        Ok(transfer) => send(updates, WorkerUpdate::WalletTransferComplete(transfer)),
        Err(mut failure) => {
            let definitive_rejection = failure
                .status
                .is_some_and(rf_gateway::is_definitive_transfer_failure_status);
            if definitive_rejection {
                send(updates, WorkerUpdate::WalletTransferRejected(failure));
                return;
            }
            if matches!(
                failure.kind,
                crate::api::ApiFailureKind::Connection
                    | crate::api::ApiFailureKind::Unavailable
                    | crate::api::ApiFailureKind::InvalidResponse
            ) {
                failure.message.push_str(
                    " Outcome unknown: Confirm send again to reuse the same transfer key, or recover by transfer ID.",
                );
            }
            operation_failed(updates, "send AI tokens", failure)
        }
    }
}

fn refresh_wallet_sources(client: Option<&ApiClient>, updates: &Sender<WorkerUpdate>) {
    let Some(client) = require_client(client, "load transfer sources", updates) else {
        return;
    };
    match client.list_wallet_sources() {
        Ok(sources) => send(updates, WorkerUpdate::WalletSources(sources)),
        Err(failure) => operation_failed(updates, "load transfer sources", failure),
    }
}

fn refresh_wallet_source_balance(
    client: Option<&ApiClient>,
    source_account_id: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "load transfer source balance", updates) else {
        return;
    };
    match client.get_wallet_source_balance(source_account_id) {
        Ok(balance) => send(
            updates,
            WorkerUpdate::WalletSourceBalance {
                source_account_id: source_account_id.into(),
                balance,
            },
        ),
        Err(failure) => operation_failed(updates, "load transfer source balance", failure),
    }
}

fn refresh_wallet_receive_address(
    client: Option<&ApiClient>,
    source_account_id: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "load wallet receive address", updates) else {
        return;
    };
    match client.get_wallet_receive_address(source_account_id) {
        Ok(receive) => send(updates, WorkerUpdate::WalletReceiveAddress(receive)),
        Err(failure) => operation_failed(updates, "load wallet receive address", failure),
    }
}

#[allow(clippy::too_many_arguments)]
fn review_wallet_transfer(
    client: Option<&ApiClient>,
    source: &str,
    recipient: &str,
    saved: Option<&str>,
    amount: u64,
    key: &str,
    submitted: bool,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "review transfer", updates) else {
        return;
    };
    match client.create_wallet_transfer_challenge(source, recipient, saved, amount, key) {
        Ok(challenge) => send(
            updates,
            WorkerUpdate::WalletTransferReviewed {
                challenge,
                idempotency_key: key.into(),
                submitted,
            },
        ),
        Err(failure) => operation_failed(updates, "review transfer", failure),
    }
}

fn refresh_saved_recipients(
    client: Option<&ApiClient>,
    source: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "load saved recipients", updates) else {
        return;
    };
    match client.list_saved_recipients(source) {
        Ok(values) => send(updates, WorkerUpdate::WalletSavedRecipients(values)),
        Err(failure) => operation_failed(updates, "load saved recipients", failure),
    }
}

fn save_wallet_recipient(
    client: Option<&ApiClient>,
    source: &str,
    recipient: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "save recipient", updates) else {
        return;
    };
    match client.save_wallet_recipient(source, recipient, "") {
        Ok(value) => send(updates, WorkerUpdate::WalletRecipientSaved(value)),
        Err(failure) => operation_failed(updates, "save recipient", failure),
    }
}

fn delete_wallet_recipient(
    client: Option<&ApiClient>,
    source: &str,
    saved: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "delete saved recipient", updates) else {
        return;
    };
    match client.delete_wallet_recipient(source, saved) {
        Ok(_) => send(updates, WorkerUpdate::WalletRecipientDeleted(saved.into())),
        Err(failure) => operation_failed(updates, "delete saved recipient", failure),
    }
}

fn recover_wallet_transfer(
    client: Option<&ApiClient>,
    transfer_id: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "recover transfer", updates) else {
        return;
    };
    match client.get_wallet_transfer(transfer_id) {
        Ok(transfer) => send(updates, WorkerUpdate::WalletTransferComplete(transfer)),
        Err(failure) => operation_failed(updates, "recover transfer", failure),
    }
}

fn refresh_media_models(
    client: Option<&ApiClient>,
    modality: Option<&str>,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "refresh media models", updates) else {
        return;
    };
    match client.list_media_models(modality) {
        Ok(models) => send(updates, WorkerUpdate::MediaModels(models)),
        Err(failure) => operation_failed(updates, "refresh media models", failure),
    }
}

fn lookup_generation(client: Option<&ApiClient>, id: &str, updates: &Sender<WorkerUpdate>) {
    let Some(client) = require_client(client, "look up generation", updates) else {
        return;
    };
    match client.get_media_generation(id) {
        Ok(detail) => send(updates, WorkerUpdate::GenerationDetailLoaded(detail)),
        Err(failure) => operation_failed(updates, "look up generation", failure),
    }
}

fn export_generation_provenance(
    client: Option<&ApiClient>,
    id: &str,
    path: &std::path::Path,
    updates: &Sender<WorkerUpdate>,
) {
    use std::io::Write;

    let Some(client) = require_client(client, "export provenance", updates) else {
        return;
    };
    let proof = match client.get_media_provenance(id) {
        Ok(proof) => proof,
        Err(failure) => {
            operation_failed(updates, "export provenance", failure);
            return;
        }
    };
    let encoded = match serde_json::to_vec_pretty(&proof) {
        Ok(mut encoded) => {
            encoded.push(b'\n');
            encoded
        }
        Err(error) => {
            operation_failed(
                updates,
                "export provenance",
                ApiFailure {
                    kind: crate::api::ApiFailureKind::Request,
                    status: None,
                    message: format!("cannot encode provenance: {error}"),
                },
            );
            return;
        }
    };
    let result = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .and_then(|mut file| {
            file.write_all(&encoded)?;
            file.sync_all()
        });
    match result {
        Ok(()) => send(
            updates,
            WorkerUpdate::ProvenanceExported {
                generation_id: id.to_string(),
                path: path.to_path_buf(),
            },
        ),
        Err(error) => operation_failed(
            updates,
            "export provenance",
            ApiFailure {
                kind: crate::api::ApiFailureKind::Request,
                status: None,
                message: format!("cannot create {}: {error}", path.display()),
            },
        ),
    }
}

fn generate_media_image(
    client: Option<&ApiClient>,
    model: &str,
    prompt: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "generate image", updates) else {
        return;
    };
    match client.create_media_image(model, prompt) {
        Ok(result) => send(
            updates,
            WorkerUpdate::MediaImageComplete {
                url: result.url,
                cost_micros: result.cost_micros,
            },
        ),
        Err(failure) => operation_failed(updates, "generate media image", failure),
    }
}

fn generate_media_video(
    client: Option<&ApiClient>,
    model: &str,
    prompt: &str,
    image_url: &str,
    duration: u32,
    identity_passport_id: &str,
    identity_version: Option<u32>,
    media_polling: &mut HashMap<String, MediaPollTarget>,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "generate video", updates) else {
        return;
    };
    let result = if identity_passport_id.trim().is_empty() {
        client.create_media_video(model, prompt, duration, "9:16", image_url)
    } else {
        client.create_identity_media_video(
            model,
            prompt,
            duration,
            "9:16",
            image_url,
            identity_passport_id,
            identity_version,
        )
    };
    match result {
        Ok(job) => {
            let id = job.id;
            send(
                updates,
                WorkerUpdate::MediaVideoQueued {
                    id: id.clone(),
                    cost_micros: job.cost_micros,
                },
            );
            media_polling.insert(
                id,
                MediaPollTarget {
                    next_poll: Instant::now() + POLL_INTERVAL,
                    audio: false,
                },
            );
        }
        Err(failure) => operation_failed(updates, "generate media video", failure),
    }
}

fn generate_media_audio(
    client: Option<&ApiClient>,
    model: &str,
    prompt: &str,
    instrumental: bool,
    media_polling: &mut HashMap<String, MediaPollTarget>,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = require_client(client, "generate music", updates) else {
        return;
    };
    match client.create_media_audio(model, prompt, instrumental) {
        Ok(job) => {
            let id = job.id;
            send(
                updates,
                WorkerUpdate::MediaAudioQueued {
                    id: id.clone(),
                    cost_micros: job.cost_micros,
                },
            );
            media_polling.insert(
                id,
                MediaPollTarget {
                    next_poll: Instant::now() + POLL_INTERVAL,
                    audio: true,
                },
            );
        }
        Err(failure) => operation_failed(updates, "generate music", failure),
    }
}

fn poll_due_media_videos(
    client: Option<&ApiClient>,
    polling: &mut HashMap<String, MediaPollTarget>,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = client else { return };
    let now = Instant::now();
    let due = polling
        .iter()
        .filter(|(_, target)| target.next_poll <= now)
        .map(|(id, target)| (id.clone(), target.audio))
        .collect::<Vec<_>>();

    for (id, audio) in due {
        let polled = if audio {
            client.get_media_audio(&id)
        } else {
            client.get_media_video(&id)
        };
        match polled {
            Ok(job) if job.is_terminal() => {
                polling.remove(&id);
                if job.gen_status() == rf_gateway::GenStatus::Completed {
                    let update = if audio {
                        WorkerUpdate::MediaAudioComplete {
                            id,
                            url: job.url,
                            cost_micros: job.cost_micros,
                        }
                    } else {
                        WorkerUpdate::MediaVideoComplete {
                            id,
                            url: job.url,
                            cost_micros: job.cost_micros,
                        }
                    };
                    send(updates, update);
                } else {
                    operation_failed(
                        updates,
                        if audio {
                            "generate music"
                        } else {
                            "generate media video"
                        },
                        ApiFailure {
                            kind: crate::api::ApiFailureKind::Request,
                            status: None,
                            message: if !job.error.is_empty() {
                                job.error
                            } else if audio {
                                "Music generation failed.".into()
                            } else {
                                "Video generation failed.".into()
                            },
                        },
                    );
                }
            }
            Ok(job) => {
                let update = if audio {
                    WorkerUpdate::MediaAudioProgress {
                        id: id.clone(),
                        status: job.status,
                    }
                } else {
                    WorkerUpdate::MediaVideoProgress {
                        id: id.clone(),
                        status: job.status,
                    }
                };
                send(updates, update);
                if let Some(target) = polling.get_mut(&id) {
                    target.next_poll = Instant::now() + POLL_INTERVAL;
                }
            }
            Err(failure) => {
                operation_failed(
                    updates,
                    if audio {
                        "poll music"
                    } else {
                        "poll media video"
                    },
                    failure,
                );
                if let Some(target) = polling.get_mut(&id) {
                    target.next_poll = Instant::now() + POLL_INTERVAL;
                }
            }
        }
    }
}

fn poll_due_jobs(
    client: Option<&ApiClient>,
    polling: &mut HashMap<String, PollTarget>,
    updates: &Sender<WorkerUpdate>,
) {
    let Some(client) = client else { return };
    let now = Instant::now();
    let due = polling
        .iter()
        .filter(|(_, target)| target.next_poll <= now)
        .map(|(id, target)| (id.clone(), target.kind))
        .collect::<Vec<_>>();

    for (id, kind) in due {
        let result = match kind {
            JobKind::Reel => client.get_reel(&id).map(PollResult::Reel),
            JobKind::Broll => client.get_broll(&id).map(PollResult::Broll),
        };
        match result {
            Ok(PollResult::Reel(job)) => apply_reel_poll(job, polling, updates),
            Ok(PollResult::Broll(job)) => apply_broll_poll(job, polling, updates),
            Err(failure) => {
                operation_failed(updates, "poll generation", failure);
                if let Some(target) = polling.get_mut(&id) {
                    target.next_poll = Instant::now() + POLL_INTERVAL;
                }
            }
        }
    }
}

enum PollResult {
    Reel(JobDto),
    Broll(BrollGenerationDto),
}

fn apply_reel_poll(
    job: JobDto,
    polling: &mut HashMap<String, PollTarget>,
    updates: &Sender<WorkerUpdate>,
) {
    let id = job.job_id.clone();
    if job.state == 1 {
        polling.remove(&id);
        send(
            updates,
            WorkerUpdate::Complete {
                id,
                kind: JobKind::Reel,
                result_url: job.result_url,
                result_key: String::new(),
                correlation_id: job.correlation_id,
            },
        );
    } else if job.state == -1 {
        polling.remove(&id);
        send(
            updates,
            WorkerUpdate::Failed {
                id,
                kind: JobKind::Reel,
                message: job.error,
                retry_eligible: job.retry_eligible,
                correlation_id: job.correlation_id,
            },
        );
    } else {
        schedule_next(&id, polling);
        send(
            updates,
            WorkerUpdate::Progress {
                id,
                kind: JobKind::Reel,
                progress: job.progress,
                correlation_id: job.correlation_id,
            },
        );
    }
}

fn apply_broll_poll(
    job: BrollGenerationDto,
    polling: &mut HashMap<String, PollTarget>,
    updates: &Sender<WorkerUpdate>,
) {
    let id = job.generation_id.clone();
    if job.state == 1 {
        polling.remove(&id);
        send(
            updates,
            WorkerUpdate::Complete {
                id,
                kind: JobKind::Broll,
                result_url: job.result_url,
                result_key: job.broll_key,
                correlation_id: job.correlation_id,
            },
        );
    } else if job.state == -1 {
        polling.remove(&id);
        send(
            updates,
            WorkerUpdate::Failed {
                id,
                kind: JobKind::Broll,
                message: job.error,
                retry_eligible: job.retry_eligible,
                correlation_id: job.correlation_id,
            },
        );
    } else {
        schedule_next(&id, polling);
        send(
            updates,
            WorkerUpdate::Progress {
                id,
                kind: JobKind::Broll,
                progress: job.progress,
                correlation_id: job.correlation_id,
            },
        );
    }
}

fn schedule_next(id: &str, polling: &mut HashMap<String, PollTarget>) {
    if let Some(target) = polling.get_mut(id) {
        target.next_poll = Instant::now() + POLL_INTERVAL;
    }
}

fn reel_snapshot(job: JobDto) -> JobSnapshot {
    let media_url = if !job.result_url.is_empty() {
        job.result_url
    } else if !job.preview_url.is_empty() {
        job.preview_url
    } else if !job.cover_url.is_empty() {
        job.cover_url
    } else {
        job.poster_url
    };
    JobSnapshot {
        id: job.job_id,
        kind: JobKind::Reel,
        progress: job.progress.clamp(0, 100),
        state: state_from_api(job.state),
        result_url: media_url,
        result_key: String::new(),
        error: job.error,
        retry_eligible: job.retry_eligible,
        created_at: job.created_at,
        correlation_id: job.correlation_id,
    }
}

fn broll_snapshot(job: BrollGenerationDto) -> JobSnapshot {
    JobSnapshot {
        id: job.generation_id,
        kind: JobKind::Broll,
        progress: job.progress.clamp(0, 100),
        state: state_from_api(job.state),
        result_url: job.result_url,
        result_key: job.broll_key,
        error: job.error,
        retry_eligible: job.retry_eligible,
        created_at: String::new(),
        correlation_id: job.correlation_id,
    }
}

fn state_from_api(state: i32) -> JobState {
    match state {
        1 => JobState::Complete,
        -1 => JobState::Failed,
        _ => JobState::Running,
    }
}

fn require_client<'a>(
    client: Option<&'a ApiClient>,
    operation: &str,
    updates: &Sender<WorkerUpdate>,
) -> Option<&'a ApiClient> {
    if client.is_none() {
        operation_failed(
            updates,
            operation,
            ApiFailure {
                kind: crate::api::ApiFailureKind::InvalidCredentials,
                status: None,
                message: "Save an API base URL and API key in Settings first.".into(),
            },
        );
    }
    client
}

/// Hands a finished job to WolfCut. A reel is re-read so the handoff uses the
/// API's `generated_clip` (exact size, rate and job-side caption timing) and a
/// freshly-signed URL; B-roll has no descriptor and is probed by the editor.
fn open_job_in_editor(
    client: Option<&ApiClient>,
    job_id: &str,
    kind: JobKind,
    result_url: &str,
    updates: &Sender<WorkerUpdate>,
) {
    let (label, api_clip, url) = match kind {
        JobKind::Reel => {
            let Some(client) = require_client(client, "open in editor", updates) else {
                return;
            };
            match client.get_reel(job_id) {
                Ok(job) => {
                    let url = if job.result_url.is_empty() {
                        result_url.to_owned()
                    } else {
                        job.result_url
                    };
                    ("Menivor reel", job.generated_clip, url)
                }
                Err(failure) => {
                    operation_failed(updates, "open in editor", failure);
                    return;
                }
            }
        }
        JobKind::Broll => ("Menivor B-roll", None, result_url.to_owned()),
    };
    let result = editor_handoff::descriptor_for_job(job_id, label, api_clip, &url)
        .and_then(|descriptor| editor_handoff::open_in_editor(job_id, &descriptor));
    match result {
        Ok(()) => send(
            updates,
            WorkerUpdate::EditorOpened {
                message: "Opening in the Menivor editor…".into(),
            },
        ),
        Err(message) => send(updates, WorkerUpdate::EditorOpenFailed { message }),
    }
}

fn operation_failed(updates: &Sender<WorkerUpdate>, operation: &str, failure: ApiFailure) {
    send(
        updates,
        WorkerUpdate::OperationFailed {
            operation: operation.into(),
            failure,
        },
    );
}

fn send(updates: &Sender<WorkerUpdate>, update: WorkerUpdate) {
    let _ = updates.send(update);
}
