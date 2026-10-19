//! Signed-preview interactions.

use std::path::PathBuf;

use gpui::Context;

use crate::ui::Shell;
use crate::workspace::WorkerCommand;

impl Shell {
    pub(super) fn open_preview(&mut self, url: String, cx: &mut Context<Self>) {
        if self
            .worker
            .send(WorkerCommand::OpenPreview { url })
            .is_err()
        {
            self.state.operation_error = "The background worker is unavailable.".into();
        } else {
            self.state.operation_error.clear();
            self.state.activity = "Opening signed preview…".into();
        }
        cx.notify();
    }

    /// Prompt for a save location, then stream the finished result to disk. The
    /// preview URL is short-lived, so this is how a creator keeps a durable copy
    /// they own. Mirrors the async file-dialog pattern in
    /// `ui::create::actions::choose_upload`, using the OS save dialog
    /// (`prompt_for_new_path`) instead of an open dialog.
    pub(super) fn save_result(
        &mut self,
        url: String,
        suggested_name: String,
        cx: &mut Context<Self>,
    ) {
        let selected =
            cx.prompt_for_new_path(&default_save_directory(), Some(suggested_name.as_str()));
        let commands = self.worker.clone();
        cx.spawn(async move |this, cx| {
            let Ok(Ok(Some(dest))) = selected.await else {
                return;
            };
            if commands
                .send(WorkerCommand::SaveResultToDisk { url, dest })
                .is_err()
            {
                let _ = this.update(cx, |shell, cx| {
                    shell.state.operation_error = "The background worker is unavailable.".into();
                    cx.notify();
                });
                return;
            }
            let _ = this.update(cx, |shell, cx| {
                shell.state.operation_error.clear();
                shell.state.activity = "Saving to disk…".into();
                cx.notify();
            });
        })
        .detach();
    }
}

/// Starting directory for the save dialog: the user's home directory when the
/// platform exposes one, otherwise the current working directory. The user can
/// navigate anywhere from here; this only seeds the dialog's initial location.
pub(in crate::ui) fn default_save_directory() -> PathBuf {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}
