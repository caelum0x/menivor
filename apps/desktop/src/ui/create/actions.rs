use gpui::{Context, PathPromptOptions, Window};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::media::capture::UploadSelection;
use crate::ui::shell::WorkspaceSection;
use crate::ui::Shell;
use crate::workspace::{BrollMode, LocalRenderRequest, UploadTarget, WorkerCommand};

static CREATE_SEQUENCE: AtomicU64 = AtomicU64::new(1);

/// Clamp a raw millisecond duration into the reel form's supported second range.
fn duration_ms_to_target_seconds(total_ms: i64) -> u32 {
    let clamped = total_ms.max(0);
    // Ceil-divide without relying on a specific toolchain's `div_ceil`.
    let seconds = (clamped + 999) / 1000;
    seconds.clamp(1, 600) as u32
}

impl Shell {
    pub(in crate::ui) fn sync_form_fields(&mut self, cx: &mut Context<Self>) {
        let reel = self.state.reel_draft.clone();
        let broll = self.state.broll_draft.clone();
        self.reel_subject_field
            .update(cx, |field, cx| field.set_text(reel.video_subject, cx));
        self.reel_script_field
            .update(cx, |field, cx| field.set_text(reel.video_script, cx));
        self.reel_avatar_field
            .update(cx, |field, cx| field.set_text(reel.avatar_id, cx));
        self.reel_voice_field
            .update(cx, |field, cx| field.set_text(reel.voice_name, cx));
        self.broll_prompt_field
            .update(cx, |field, cx| field.set_text(broll.prompt, cx));
        if let Some(transfer) = &self.state.wallet_transfer {
            self.wallet_transfer_id_field.update(cx, |field, cx| {
                field.set_text(transfer.transfer_id.clone(), cx)
            });
        }
        if let Some(pending) = &self.state.pending_wallet_transfer {
            self.wallet_recipient_field.update(cx, |field, cx| {
                field.set_text(pending.recipient_handle.clone(), cx)
            });
            self.wallet_transfer_amount_field.update(cx, |field, cx| {
                field.set_text(rf_gateway::usd_micros_decimal(pending.amount_micros), cx)
            });
        }
    }

    pub(in crate::ui) fn choose_upload(
        &mut self,
        target: UploadTarget,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let selected = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: false,
            prompt: Some(
                match target {
                    UploadTarget::ReelRecording => "Choose screen recording",
                    UploadTarget::BrollReference => "Choose reference image",
                }
                .into(),
            ),
        });
        let commands = self.worker.clone();
        cx.spawn(async move |this, cx| {
            let Ok(Ok(Some(paths))) = selected.await else {
                return;
            };
            let Some(path) = paths.into_iter().next() else {
                return;
            };
            let selection = match UploadSelection::from_path(path, target) {
                Ok(selection) => selection,
                Err(message) => {
                    let _ = this.update(cx, |shell, cx| {
                        shell.state.operation_error = message;
                        cx.notify();
                    });
                    return;
                }
            };
            if commands
                .send(WorkerCommand::Upload {
                    target: selection.target,
                    path: selection.path,
                    content_type: selection.content_type,
                })
                .is_err()
            {
                let _ = this.update(cx, |shell, cx| {
                    shell.state.operation_error = "The background worker is unavailable.".into();
                    cx.notify();
                });
            }
        })
        .detach();
    }

    pub(in crate::ui) fn choose_local_render(
        &mut self,
        _window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if !self.state.local_runtime_ready {
            self.state.operation_error = "The durable local executor is unavailable.".into();
            cx.notify();
            return;
        }
        let selected = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: false,
            prompt: Some("Choose a video to render as a local portrait draft".into()),
        });
        let commands = self.worker.clone();
        cx.spawn(async move |this, cx| {
            let Ok(Ok(Some(paths))) = selected.await else {
                return;
            };
            let Some(input_path) = paths.into_iter().next() else {
                return;
            };
            let request = LocalRenderRequest {
                task_id: create_local_task_id(),
                input_path,
                expected_source_sha256: None,
                timeline: None,
            };
            if commands
                .send(WorkerCommand::SubmitLocalRender(request))
                .is_err()
            {
                let _ = this.update(cx, |shell, cx| {
                    shell.state.operation_error = "The background worker is unavailable.".into();
                    cx.notify();
                });
                return;
            }
            let _ = this.update(cx, |shell, cx| {
                shell.state.local_execution_activity =
                    "Staging selected bytes before durable scheduling…".into();
                shell.state.local_execution_failed = false;
                shell.state.operation_error.clear();
                cx.notify();
            });
        })
        .detach();
    }

    pub(in crate::ui) fn open_local_artifact(&mut self, task_id: String, cx: &mut Context<Self>) {
        if self
            .worker
            .send(WorkerCommand::OpenLocalArtifact { task_id })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
            cx.notify();
        }
    }

    pub(in crate::ui) fn submit_reel(&mut self, cx: &mut Context<Self>) {
        if !self.state.capabilities.reels {
            self.state.operation_error =
                "Reel generation is not available for this pilot account.".into();
            cx.notify();
            return;
        }
        self.state.reel_draft.video_subject = self.reel_subject_field.read(cx).text();
        self.state.reel_draft.video_script = self.reel_script_field.read(cx).text();
        self.state.reel_draft.avatar_id = self.reel_avatar_field.read(cx).text();
        self.state.reel_draft.voice_name = self.reel_voice_field.read(cx).text();
        let draft = self.state.reel_draft.clone();
        let missing = [
            (draft.video_subject.trim().is_empty(), "subject"),
            (
                draft.screen_recording_key.trim().is_empty(),
                "screen recording",
            ),
            (draft.avatar_id.trim().is_empty(), "avatar"),
            (draft.voice_name.trim().is_empty(), "voice"),
        ]
        .into_iter()
        .filter_map(|(missing, label)| missing.then_some(label))
        .collect::<Vec<_>>();
        if !missing.is_empty() {
            self.state.operation_error = format!("Reel needs: {}.", missing.join(", "));
        } else {
            let idempotency_key = match self.pending_reel_create.as_ref() {
                Some((pending_draft, key)) if pending_draft == &draft => key.clone(),
                _ => {
                    let key = create_idempotency_key();
                    self.pending_reel_create = Some((draft.clone(), key.clone()));
                    key
                }
            };
            if self
                .worker
                .send(WorkerCommand::SubmitReel {
                    draft,
                    idempotency_key,
                })
                .is_err()
            {
                self.state.operation_error = "The background worker is unavailable.".into();
            } else {
                self.state.activity = "Submitting reel…".into();
                self.state.operation_error.clear();
            }
        }
        cx.notify();
    }

    pub(in crate::ui) fn submit_broll(&mut self, cx: &mut Context<Self>) {
        if !self.state.capabilities.broll {
            self.state.operation_error =
                "AI B-roll is not available for this pilot account.".into();
            cx.notify();
            return;
        }
        self.state.broll_draft.prompt = self.broll_prompt_field.read(cx).text();
        let draft = self.state.broll_draft.clone();
        if draft.prompt.trim().is_empty() {
            self.state.operation_error = "B-roll needs a shot description.".into();
        } else if draft.mode == BrollMode::ImageToVideo && draft.image_key.trim().is_empty() {
            self.state.operation_error = "Image-to-video needs a reference image.".into();
        } else {
            let idempotency_key = match self.pending_broll_create.as_ref() {
                Some((pending_draft, key)) if pending_draft == &draft => key.clone(),
                _ => {
                    let key = create_idempotency_key();
                    self.pending_broll_create = Some((draft.clone(), key.clone()));
                    key
                }
            };
            if self
                .worker
                .send(WorkerCommand::SubmitBroll {
                    draft,
                    idempotency_key,
                })
                .is_err()
            {
                self.state.operation_error = "The background worker is unavailable.".into();
            } else {
                self.state.activity = "Submitting B-roll…".into();
                self.state.operation_error.clear();
            }
        }
        cx.notify();
    }

    pub(in crate::ui) fn set_broll_mode(&mut self, mode: BrollMode, cx: &mut Context<Self>) {
        self.state.broll_draft.mode = mode;
        cx.notify();
    }

    /// Apply a catalog-selected avatar to both the draft and its text field.
    pub(in crate::ui) fn apply_reel_avatar(&mut self, avatar_id: String, cx: &mut Context<Self>) {
        self.state.reel_draft.avatar_id = avatar_id.clone();
        self.reel_avatar_field
            .update(cx, |field, cx| field.set_text(avatar_id, cx));
        cx.notify();
    }

    /// Apply a catalog-selected voice to both the draft and its text field.
    pub(in crate::ui) fn apply_reel_voice(&mut self, voice_name: String, cx: &mut Context<Self>) {
        self.state.reel_draft.voice_name = voice_name.clone();
        self.reel_voice_field
            .update(cx, |field, cx| field.set_text(voice_name, cx));
        cx.notify();
    }

    /// Apply a catalog-selected caption style to the draft.
    pub(in crate::ui) fn apply_reel_caption_style(
        &mut self,
        caption_style: String,
        cx: &mut Context<Self>,
    ) {
        self.state.reel_draft.caption_style = caption_style;
        cx.notify();
    }

    /// Captions section: adopt a first-party caption preset into the reel draft
    /// and focus the Create form. Reuses `apply_reel_caption_style` so the value
    /// flows through the same `SubmitReel` path a catalog pick uses.
    pub(in crate::ui) fn use_caption_preset(&mut self, name: String, cx: &mut Context<Self>) {
        if let Err(message) = rf_captions::get_preset(&name) {
            self.state.operation_error = format!("Caption preset {name} is unavailable: {message}");
            cx.notify();
            return;
        }
        self.apply_reel_caption_style(name.clone(), cx);
        self.section = WorkspaceSection::Create;
        self.state.operation_error.clear();
        self.state.activity = format!("Caption style set to {name} for the next reel.");
        cx.notify();
    }

    /// Blueprints section: seed the Create form from a shot-template blueprint —
    /// a shot-by-shot script scaffold, the template's aspect layout, its first
    /// captioned slot's preset, and a target duration derived from its slots.
    pub(in crate::ui) fn apply_shot_blueprint(&mut self, slug: String, cx: &mut Context<Self>) {
        let template = match rf_shots::get_preset(&slug) {
            Ok(template) => template,
            Err(message) => {
                self.state.operation_error =
                    format!("Blueprint {slug} is unavailable: {message}");
                cx.notify();
                return;
            }
        };
        let target_duration_s =
            duration_ms_to_target_seconds(rf_shots::total_duration_ms(&template));
        let script = template
            .slots
            .iter()
            .enumerate()
            .map(|(index, slot)| {
                let seconds = (slot.t_end_ms - slot.t_start_ms).max(0) as f64 / 1000.0;
                format!("{}. [{} · {seconds:.1}s]", index + 1, slot.role)
            })
            .collect::<Vec<_>>()
            .join("\n");
        let caption_preset = template
            .slots
            .iter()
            .map(|slot| slot.caption_preset.trim())
            .find(|preset| !preset.is_empty())
            .map(str::to_owned);

        let subject = if self.state.reel_draft.video_subject.trim().is_empty() {
            format!("{} reel", template.genre)
        } else {
            self.state.reel_draft.video_subject.clone()
        };
        self.state.reel_draft.video_subject = subject;
        self.state.reel_draft.video_script = script;
        self.state.reel_draft.layout = template.aspect.clone();
        self.state.reel_draft.target_duration_s = target_duration_s;
        if let Some(caption_preset) = caption_preset {
            self.state.reel_draft.caption_style = caption_preset;
        }
        self.section = WorkspaceSection::Create;
        self.state.operation_error.clear();
        self.state.activity = format!(
            "Loaded blueprint {} · {} shot(s) · {}s into the reel form.",
            template.slug,
            template.slots.len(),
            target_duration_s
        );
        self.sync_form_fields(cx);
        cx.notify();
    }

    /// Trends section: seed an ad-safe short-form reel draft sized to the current
    /// trend window, recording the computed opportunity in the subject scaffold.
    pub(in crate::ui) fn draft_reel_for_trend(&mut self, cx: &mut Context<Self>) {
        let Some(series) = crate::ui::growth::library_trend_series(&self.state.jobs) else {
            self.state.operation_error =
                "No jobs from the last week yet - there is no trend window to draft for.".into();
            cx.notify();
            return;
        };
        let trend = rf_trends::score(&series);
        // Higher opportunity → lean into the full 30s hook window; a cooling
        // trend gets a tighter 20s cut. Both are valid reel form durations.
        let target_duration_s = if trend.opportunity >= 0.5 { 30 } else { 20 };
        if self.state.reel_draft.video_subject.trim().is_empty() {
            self.state.reel_draft.video_subject =
                format!("Trending format (opportunity {:.2})", trend.opportunity);
        }
        self.state.reel_draft.target_duration_s = target_duration_s;
        self.section = WorkspaceSection::Create;
        self.state.operation_error.clear();
        self.state.activity = format!(
            "Drafted a {target_duration_s}s reel for this trend · velocity {:.2} · opportunity {:.2}.",
            trend.velocity, trend.opportunity
        );
        self.sync_form_fields(cx);
        cx.notify();
    }

    /// Signals section: adopt the A/B winner's measured average watch time (as
    /// entered from the creator's analytics) as the
    /// reel draft's production target duration and focus the Create form.
    pub(in crate::ui) fn adopt_ab_winner(&mut self, cx: &mut Context<Self>) {
        let variants = match self.signal_fields.variants(cx) {
            Ok(variants) => variants,
            Err(message) => {
                self.state.operation_error = message;
                cx.notify();
                return;
            }
        };
        let result = rf_growth::select_winner(&variants);
        let Some(winner_id) = result.winner else {
            self.state.operation_error = "No A/B winner is available to adopt yet.".into();
            cx.notify();
            return;
        };
        let avg_watch = variants
            .iter()
            .find(|variant| variant.id == winner_id)
            .and_then(|variant| variant.avg_watch)
            .unwrap_or(0.0);
        let target_duration_s = duration_ms_to_target_seconds((avg_watch * 1000.0).round() as i64);
        self.state.reel_draft.target_duration_s = target_duration_s;
        self.section = WorkspaceSection::Create;
        self.state.operation_error.clear();
        self.state.activity = format!(
            "Adopted A/B winner {winner_id} · target duration set to {target_duration_s}s.",
        );
        self.sync_form_fields(cx);
        cx.notify();
    }

    /// Governance section: adopt a governed model into the media-gateway generate
    /// form when it is commercial-safe, or refuse with a licence-class reason when
    /// it cannot bill a paid render.
    pub(in crate::ui) fn use_governed_model(&mut self, model_id: String, cx: &mut Context<Self>) {
        if !rf_provider::can_use_for_paid(&model_id) {
            let class = rf_provider::license_class(&model_id);
            self.state.operation_error = format!(
                "{model_id} is {class:?}, not commercial-safe — paid renders are blocked for it."
            );
            cx.notify();
            return;
        }
        self.media_model_field
            .update(cx, |field, cx| field.set_text(model_id.clone(), cx));
        self.section = WorkspaceSection::MediaGateway;
        self.state.operation_error.clear();
        self.state.activity =
            format!("Loaded commercial-safe model {model_id} into the generate form.");
        cx.notify();
    }

    /// Workflows section: run a pinned ComfyUI workflow on the hosted media
    /// gateway. Each runnable workflow maps to the catalog model that serves the
    /// same weights (see [`hosted_model_for_workflow`]); the generate form is
    /// seeded with that model and a starting prompt, then the Media Gateway is
    /// focused. Workflows with no hosted equivalent are refused with a clear
    /// reason instead of staging a model id the gateway cannot route.
    pub(in crate::ui) fn instantiate_workflow(&mut self, slug: String, cx: &mut Context<Self>) {
        let workflow = match rf_workflows::get_workflow(&slug) {
            Ok(workflow) => workflow,
            Err(message) => {
                self.state.operation_error =
                    format!("Workflow {slug} is unavailable: {message}");
                cx.notify();
                return;
            }
        };
        let graph_hash = rf_workflows::graph_hash(&workflow);
        let Some(model_id) = hosted_model_for_workflow(&workflow.slug) else {
            self.state.operation_error = format!(
                "Workflow {} ({}) has no hosted runner on the media gateway yet. Run it in a local ComfyUI with the pinned node commits and weights shown here.",
                workflow.slug, workflow.category
            );
            cx.notify();
            return;
        };
        let seed_prompt = workflow
            .inputs
            .iter()
            .find_map(|slot| match (&slot.slot_type, &slot.default) {
                (rf_workflows::SlotType::String, Some(rf_workflows::DefaultValue::Str(value)))
                    if !value.trim().is_empty() =>
                {
                    Some(value.clone())
                }
                _ => None,
            })
            .unwrap_or_else(|| workflow.description.clone());
        let needs_image = workflow
            .inputs
            .iter()
            .any(|slot| slot.required && matches!(slot.slot_type, rf_workflows::SlotType::Image));

        self.media_model_field
            .update(cx, |field, cx| field.set_text(model_id.to_string(), cx));
        self.media_prompt_field
            .update(cx, |field, cx| field.set_text(seed_prompt, cx));
        self.section = WorkspaceSection::MediaGateway;
        self.state.operation_error.clear();
        self.state.activity = if needs_image {
            format!(
                "Staged workflow {} (graph_hash {graph_hash}) on {model_id}. Add a source image, then Generate.",
                workflow.slug
            )
        } else {
            format!(
                "Staged workflow {} (graph_hash {graph_hash}) on {model_id}. Review the prompt, then Generate.",
                workflow.slug
            )
        };
        cx.notify();
    }

    /// Effects section: toggle a kernel's inspector open/closed. The render surface
    /// samples the selected kernel deterministically at `EFFECT_SAMPLE_POINTS`.
    pub(in crate::ui) fn toggle_effect_kernel(&mut self, kernel_id: String, cx: &mut Context<Self>) {
        if self.selected_effect_kernel.as_deref() == Some(kernel_id.as_str()) {
            self.selected_effect_kernel = None;
        } else {
            self.selected_effect_kernel = Some(kernel_id);
        }
        cx.notify();
    }
}

fn create_idempotency_key() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = CREATE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("desktop-{}-{nanos}-{sequence}", std::process::id())
}

fn create_local_task_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = CREATE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("local-{nanos}-{sequence}")
}

/// The media-gateway catalog model that serves the same weights as a pinned
/// ComfyUI workflow, or `None` when the workflow has no hosted runner.
///
/// * `wan-i2v` pins Wan 2.2 A14B image-to-video, hosted as `wan/wan-2.2-i2v`.
/// * `flux-first-frame` pins FLUX.1 schnell, hosted as
///   `black-forest-labs/flux-schnell`.
/// * `lipsync-musetalk` needs a video plus an audio input; the gateway has no
///   lipsync route, so it stays a local-ComfyUI workflow.
pub(in crate::ui) fn hosted_model_for_workflow(slug: &str) -> Option<&'static str> {
    match slug {
        "wan-i2v" => Some("wan/wan-2.2-i2v"),
        "flux-first-frame" => Some("black-forest-labs/flux-schnell"),
        _ => None,
    }
}
