//! Media-gateway interactions.

use gpui::Context;

use crate::ui::Shell;
use crate::workspace::{WorkerCommand, WorkspaceCache};

impl Shell {
    pub(super) fn review_wallet_transfer(&mut self, cx: &mut Context<Self>) {
        let handle = self.wallet_recipient_field.read(cx).text();
        let amount = self.wallet_transfer_amount_field.read(cx).text();
        let Some(amount_micros) = rf_gateway::parse_usd_micros(&amount) else {
            self.state.operation_error =
                "Enter a positive USD amount with no more than 6 decimal places.".into();
            cx.notify();
            return;
        };
        if amount_micros > 1_000_000_000 {
            self.state.operation_error = "One transfer cannot exceed $1,000.".into();
            cx.notify();
            return;
        }
        let normalized_handle = handle.trim().trim_start_matches('@');
        let Some(source) = self
            .state
            .wallet_sources
            .iter()
            .find(|source| source.source_account_id == self.state.selected_wallet_source_id)
            .cloned()
        else {
            self.state.operation_error = "Choose an authorized transfer source.".into();
            cx.notify();
            return;
        };
        if let Some(pending) = &self.state.pending_wallet_transfer {
            if !rf_gateway::wallet_destinations_equal(&pending.recipient_handle, normalized_handle)
                || pending.amount_micros != amount_micros
                || if pending.version == 2 {
                    pending.source_account_id != source.source_account_id
                } else {
                    source.kind != "personal"
                }
            {
                self.state.operation_error = format!(
                    "Resolve the pending {} transfer to {} before starting another send.",
                    rf_gateway::format_usd_micros(pending.amount_micros),
                    rf_gateway::format_wallet_destination(&pending.recipient_handle),
                );
                cx.notify();
                return;
            }
        }
        if !self
            .state
            .pending_wallet_transfer
            .as_ref()
            .is_some_and(|pending| pending.submitted)
        {
            if !source.can_send {
                self.state.operation_error = "Your role cannot send from this source.".into();
                cx.notify();
                return;
            }
            if source.limits.per_transfer_micros > 0
                && amount_micros > source.limits.per_transfer_micros
            {
                self.state.operation_error = format!(
                    "This source allows at most {} per transfer.",
                    rf_gateway::format_usd_micros(source.limits.per_transfer_micros)
                );
                cx.notify();
                return;
            }
            if source
                .limits
                .daily_remaining_micros
                .is_some_and(|remaining| amount_micros > remaining)
            {
                self.state.operation_error =
                    "This amount exceeds the source's remaining daily limit.".into();
                cx.notify();
                return;
            }
            if let Some(available) = self
                .state
                .wallet_source_balance
                .as_ref()
                .filter(|_| self.state.wallet_source_balance_id == source.source_account_id)
                .map(|credits| credits.available_micros)
            {
                if amount_micros > available {
                    self.state.operation_error = format!(
                        "Insufficient balance — want to send {}, have {}.",
                        rf_gateway::format_usd_micros(amount_micros),
                        rf_gateway::format_usd_micros(available),
                    );
                    cx.notify();
                    return;
                }
            }
        }
        self.state.wallet_recipient = None;
        self.state.wallet_transfer = None;
        let (idempotency_key, submitted) = self
            .state
            .pending_wallet_transfer
            .as_ref()
            .map(|pending| (pending.idempotency_key.clone(), pending.submitted))
            .unwrap_or_else(|| {
                let nanos = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|value| value.as_nanos())
                    .unwrap_or_default();
                (format!("desktop-transfer-{nanos}"), false)
            });
        if self
            .worker
            .send(WorkerCommand::ReviewWalletTransfer {
                source_account_id: source.source_account_id,
                recipient_handle: handle,
                saved_recipient_id: (!self.state.selected_wallet_saved_recipient_id.is_empty())
                    .then(|| self.state.selected_wallet_saved_recipient_id.clone()),
                amount_micros,
                idempotency_key,
                submitted,
            })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Sealing transfer review…".into();
            self.state.operation_error.clear();
        }
        cx.notify();
    }

    pub(super) fn select_wallet_source(
        &mut self,
        source_account_id: String,
        cx: &mut Context<Self>,
    ) {
        if self
            .state
            .pending_wallet_transfer
            .as_ref()
            .is_some_and(|pending| pending.submitted)
        {
            self.state.operation_error =
                "Resolve the submitted transfer before changing source.".into();
            cx.notify();
            return;
        }
        self.state.selected_wallet_source_id = source_account_id.clone();
        self.state.wallet_source_balance = None;
        self.state.wallet_source_balance_id.clear();
        self.state.wallet_receive_address.clear();
        self.state.wallet_receive_address_source_id.clear();
        self.state.selected_wallet_saved_recipient_id.clear();
        self.state.wallet_transfer_challenge = None;
        self.state.pending_wallet_transfer = None;
        let _ = self.worker.send(WorkerCommand::RefreshSavedRecipients {
            source_account_id: source_account_id.clone(),
        });
        let _ = self
            .worker
            .send(WorkerCommand::RefreshWalletSourceBalance { source_account_id });
        let _ = self
            .worker
            .send(WorkerCommand::RefreshWalletReceiveAddress {
                source_account_id: self.state.selected_wallet_source_id.clone(),
            });
        cx.notify();
    }

    pub(super) fn select_saved_wallet_recipient(
        &mut self,
        saved_id: String,
        handle: String,
        cx: &mut Context<Self>,
    ) {
        self.state.selected_wallet_saved_recipient_id = saved_id;
        self.wallet_recipient_field
            .update(cx, |field, cx| field.set_text(handle, cx));
        self.state.wallet_transfer_challenge = None;
        if !self
            .state
            .pending_wallet_transfer
            .as_ref()
            .is_some_and(|pending| pending.submitted)
        {
            self.state.pending_wallet_transfer = None;
        }
        cx.notify();
    }

    pub(super) fn delete_saved_wallet_recipient(
        &mut self,
        source: String,
        saved: String,
        cx: &mut Context<Self>,
    ) {
        let _ = self.worker.send(WorkerCommand::DeleteWalletRecipient {
            source_account_id: source,
            saved_recipient_id: saved,
        });
        cx.notify();
    }

    pub(super) fn save_last_wallet_recipient(&mut self, cx: &mut Context<Self>) {
        if let Some(transfer) = self.state.wallet_transfer.as_ref() {
            if transfer.recipient.kind != "personal"
                || transfer.recipient.handle.starts_with("ait1")
            {
                self.state.operation_error =
                    "Public addresses cannot be saved as person shortcuts yet.".into();
                cx.notify();
                return;
            }
            let _ = self.worker.send(WorkerCommand::SaveWalletRecipient {
                source_account_id: transfer.source.source_account_id.clone(),
                recipient_handle: transfer.recipient.handle.clone(),
            });
        }
        cx.notify();
    }

    pub(super) fn confirm_wallet_transfer(&mut self, cx: &mut Context<Self>) {
        let Some(mut pending) = self.state.pending_wallet_transfer.clone() else {
            self.state.operation_error =
                "Review the source, recipient and amount before sending.".into();
            cx.notify();
            return;
        };
        if pending.version != 2 || pending.challenge_id.is_empty() {
            self.state.operation_error = "The server review is missing. Review again.".into();
            cx.notify();
            return;
        }
        if !pending.submitted {
            let current_handle = self.wallet_recipient_field.read(cx).text();
            let current_amount =
                rf_gateway::parse_usd_micros(&self.wallet_transfer_amount_field.read(cx).text());
            if !rf_gateway::wallet_destinations_equal(
                &pending.recipient_handle,
                current_handle.trim().trim_start_matches('@'),
            ) || current_amount != Some(pending.amount_micros)
                || self.state.selected_wallet_source_id != pending.source_account_id
            {
                self.state.pending_wallet_transfer = None;
                self.state.wallet_transfer_challenge = None;
                self.state.operation_error =
                    "Source, recipient or amount changed. Review the transfer again.".into();
                cx.notify();
                return;
            }
        }
        pending.submitted = true;
        self.state.pending_wallet_transfer = Some(pending.clone());
        if self
            .worker
            .send(WorkerCommand::SendWalletTransfer {
                source_account_id: pending.source_account_id,
                challenge_id: pending.challenge_id,
                recipient_handle: pending.recipient_handle,
                amount_micros: pending.amount_micros,
                idempotency_key: pending.idempotency_key,
                workspace: WorkspaceCache::snapshot(&self.state),
            })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Sending AI tokens…".into();
            self.state.operation_error.clear();
        }
        cx.notify();
    }

    pub(super) fn recover_wallet_transfer(&mut self, cx: &mut Context<Self>) {
        let transfer_id = self.wallet_transfer_id_field.read(cx).text();
        if transfer_id.trim().is_empty() {
            self.state.operation_error = "Enter a transfer ID to recover.".into();
        } else if self
            .worker
            .send(WorkerCommand::RecoverWalletTransfer { transfer_id })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Recovering transfer…".into();
            self.state.operation_error.clear();
        }
        cx.notify();
    }

    pub(super) fn refresh_media_wallet(&mut self, cx: &mut Context<Self>) {
        if self.worker.send(WorkerCommand::RefreshMediaWallet).is_err()
            || self
                .worker
                .send(WorkerCommand::RefreshWalletSources)
                .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Refreshing media wallet…".into();
        }
        cx.notify();
    }

    pub(super) fn refresh_media_models(
        &mut self,
        modality: Option<String>,
        cx: &mut Context<Self>,
    ) {
        if self
            .worker
            .send(WorkerCommand::RefreshMediaModels { modality })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Loading model catalog…".into();
        }
        cx.notify();
    }

    pub(super) fn load_more_media_generations(&mut self, cx: &mut Context<Self>) {
        let offset = self.state.media_generations.len() as u64;
        if self
            .worker
            .send(WorkerCommand::LoadMoreMediaGenerations { offset })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Loading older generations…".into();
        }
        cx.notify();
    }

    pub(super) fn lookup_generation(&mut self, cx: &mut Context<Self>) {
        let id = self.media_generation_id_field.read(cx).text();
        if id.trim().is_empty() {
            self.state.operation_error = "Enter a generation id to look up.".into();
        } else if self
            .worker
            .send(WorkerCommand::LookupGeneration { id })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Looking up generation…".into();
            self.state.operation_error.clear();
        }
        cx.notify();
    }

    pub(super) fn export_generation_provenance(&mut self, cx: &mut Context<Self>) {
        let id = self.media_generation_id_field.read(cx).text();
        let path = self.media_provenance_path_field.read(cx).text();
        if id.trim().is_empty() || path.trim().is_empty() {
            self.state.operation_error =
                "Enter both a generation id and a new JSON export path.".into();
        } else if self
            .worker
            .send(WorkerCommand::ExportGenerationProvenance {
                id,
                path: std::path::PathBuf::from(path),
            })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Exporting signed provenance…".into();
            self.state.operation_error.clear();
        }
        cx.notify();
    }

    pub(super) fn select_media_identity(
        &mut self,
        passport_id: String,
        version: u32,
        cx: &mut Context<Self>,
    ) {
        self.media_identity_passport_field
            .update(cx, |field, cx| field.set_text(passport_id, cx));
        self.media_identity_version_field
            .update(cx, |field, cx| field.set_text(version.to_string(), cx));
        cx.notify();
    }

    /// Fill the generate form's model field from a clicked catalog row.
    pub(super) fn select_media_model(&mut self, model_id: String, cx: &mut Context<Self>) {
        self.media_model_field
            .update(cx, |field, cx| field.set_text(model_id, cx));
        cx.notify();
    }

    pub(super) fn generate_media_image(&mut self, cx: &mut Context<Self>) {
        let model = self.media_model_field.read(cx).text();
        let prompt = self.media_prompt_field.read(cx).text();
        if model.trim().is_empty() || prompt.trim().is_empty() {
            self.state.operation_error = "Image needs a model id and a prompt.".into();
            cx.notify();
            return;
        }
        // Affordability pre-flight (same guard as web/mobile): when the catalog +
        // balance are loaded, block a generation the wallet can't cover, using the
        // shared rf-gateway cost estimate. Copy the u64s so no borrow of
        // `self.state` is held when we set `operation_error`.
        let preflight = self
            .state
            .media_models
            .iter()
            .find(|m| m.id == model)
            .map(|m| m.estimate_cost_micros(0))
            .zip(
                self.state
                    .media_credits
                    .as_ref()
                    .map(|c| c.available_micros),
            );
        if let Some((estimate, available)) = preflight {
            if estimate > available {
                self.state.operation_error = format!(
                    "Insufficient balance — need {}, have {}.",
                    rf_gateway::format_usd_micros(estimate),
                    rf_gateway::format_usd_micros(available),
                );
                cx.notify();
                return;
            }
        }
        if self
            .worker
            .send(WorkerCommand::GenerateMediaImage { model, prompt })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Generating image…".into();
            self.state.operation_error.clear();
        }
        cx.notify();
    }

    pub(super) fn generate_media_video(&mut self, cx: &mut Context<Self>) {
        let model = self.media_model_field.read(cx).text();
        let prompt = self.media_prompt_field.read(cx).text();
        let image_url = self.media_source_image_field.read(cx).text();
        let identity_passport_id = self.media_identity_passport_field.read(cx).text();
        let identity_version_text = self.media_identity_version_field.read(cx).text();
        if model.trim().is_empty() || prompt.trim().is_empty() {
            self.state.operation_error = "Video needs a model id and a prompt.".into();
            cx.notify();
            return;
        }
        if model.to_ascii_lowercase().contains("i2v") && image_url.trim().is_empty() {
            self.state.operation_error =
                "This image-to-video model needs a source image URL.".into();
            cx.notify();
            return;
        }
        let identity_version = if identity_passport_id.trim().is_empty() {
            None
        } else {
            match identity_version_text.trim().parse::<u32>() {
                Ok(version) if version > 0 => Some(version),
                _ => {
                    self.state.operation_error =
                        "A selected Identity Lock passport needs its exact positive version."
                            .into();
                    cx.notify();
                    return;
                }
            }
        };
        let estimate = self
            .state
            .media_models
            .iter()
            .find(|candidate| candidate.id == model)
            .map(|candidate| candidate.estimate_cost_micros(5))
            .zip(
                self.state
                    .media_credits
                    .as_ref()
                    .map(|credits| credits.available_micros),
            );
        if let Some((estimate, available)) = estimate {
            if estimate > available {
                self.state.operation_error = format!(
                    "Insufficient balance — need {}, have {}.",
                    rf_gateway::format_usd_micros(estimate),
                    rf_gateway::format_usd_micros(available),
                );
                cx.notify();
                return;
            }
        }
        if self
            .worker
            .send(WorkerCommand::GenerateMediaVideo {
                model,
                prompt,
                image_url,
                duration: 5,
                identity_passport_id,
                identity_version,
            })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Submitting video…".into();
            self.state.operation_error.clear();
        }
        cx.notify();
    }

    /// Submit a music/audio generation with the shared model + prompt fields.
    /// The model must be an audio model from the catalog (e.g. `suno/v4.5`);
    /// `instrumental` asks for music without vocals.
    pub(super) fn generate_media_audio(&mut self, instrumental: bool, cx: &mut Context<Self>) {
        let model = self.media_model_field.read(cx).text();
        let prompt = self.media_prompt_field.read(cx).text();
        if model.trim().is_empty() || prompt.trim().is_empty() {
            self.state.operation_error = "Music needs a model id and a prompt.".into();
            cx.notify();
            return;
        }
        let catalog_entry = self
            .state
            .media_models
            .iter()
            .find(|candidate| candidate.id == model)
            .map(|candidate| {
                (
                    candidate.modality == rf_gateway::Modality::Audio,
                    candidate.estimate_cost_micros(0),
                )
            });
        if let Some((is_audio, _)) = catalog_entry {
            if !is_audio {
                self.state.operation_error = format!(
                    "{model} is not a music model. Load the music models and pick one first."
                );
                cx.notify();
                return;
            }
        }
        let preflight = catalog_entry.map(|(_, estimate)| estimate).zip(
            self.state
                .media_credits
                .as_ref()
                .map(|credits| credits.available_micros),
        );
        if let Some((estimate, available)) = preflight {
            if estimate > available {
                self.state.operation_error = format!(
                    "Insufficient balance — need {}, have {}.",
                    rf_gateway::format_usd_micros(estimate),
                    rf_gateway::format_usd_micros(available),
                );
                cx.notify();
                return;
            }
        }
        if self
            .worker
            .send(WorkerCommand::GenerateMediaAudio {
                model,
                prompt,
                instrumental,
            })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Submitting music…".into();
            self.state.operation_error.clear();
        }
        cx.notify();
    }

    /// Continue from the latest generated image into the video workflow. The
    /// source URL is already copied when the image completes; this narrows the
    /// catalog so the next click can select an image-to-video model.
    pub(super) fn animate_latest_media_image(&mut self, cx: &mut Context<Self>) {
        if self.state.media_image_url.is_empty() {
            self.state.operation_error = "Generate an image before animating it.".into();
            cx.notify();
            return;
        }
        let image_url = self.state.media_image_url.clone();
        self.media_source_image_field
            .update(cx, |field, cx| field.set_text(image_url, cx));
        self.refresh_media_models(Some("video".into()), cx);
    }
}
