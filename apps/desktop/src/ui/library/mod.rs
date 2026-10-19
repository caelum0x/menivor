//! Result-library interactions.

use gpui::Context;

use crate::ui::Shell;
use crate::workspace::{JobKind, WorkerCommand};

impl Shell {
    pub(super) fn refresh_library(&mut self, cx: &mut Context<Self>) {
        if self.worker.send(WorkerCommand::RefreshLibrary).is_err() {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.activity = "Refreshing library…".into();
        }
        cx.notify();
    }

    /// Delete a finished reel (and its stored media) from the library.
    pub(super) fn delete_reel(&mut self, job_id: String, cx: &mut Context<Self>) {
        if self
            .worker
            .send(WorkerCommand::DeleteReel { job_id })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.operation_error.clear();
            self.state.activity = "Deleting reel…".into();
        }
        cx.notify();
    }

    /// Publish a finished reel through the studio API. The idempotency key is
    /// derived from the job id so a retried publish after an ambiguous response
    /// replays the same server-side outcome instead of double-posting.
    pub(super) fn publish_reel(&mut self, job_id: String, cx: &mut Context<Self>) {
        let idempotency_key = format!("desktop-publish-{job_id}");
        if self
            .worker
            .send(WorkerCommand::PublishReel {
                job_id,
                idempotency_key,
            })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.operation_error.clear();
            self.state.activity = "Publishing reel…".into();
        }
        cx.notify();
    }

    /// Hand a finished job to WolfCut, the Menivor editor. The worker re-reads
    /// the job for its `generated_clip` descriptor and a fresh signed URL.
    pub(super) fn open_job_in_editor(
        &mut self,
        job_id: String,
        kind: JobKind,
        result_url: String,
        cx: &mut Context<Self>,
    ) {
        if self
            .worker
            .send(WorkerCommand::OpenJobInEditor {
                job_id,
                kind,
                result_url,
            })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.operation_error.clear();
            self.state.activity = "Preparing the editor handoff…".into();
        }
        cx.notify();
    }

    /// Launch WolfCut on its start screen.
    pub(super) fn launch_editor(&mut self, cx: &mut Context<Self>) {
        if self.worker.send(WorkerCommand::LaunchEditor).is_err() {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.operation_error.clear();
        }
        cx.notify();
    }
}
