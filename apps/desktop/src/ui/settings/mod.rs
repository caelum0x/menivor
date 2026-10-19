//! Secure connection settings interactions.

use gpui::Context;

use crate::ui::Shell;
use crate::workspace::{ConnectionState, WorkerCommand};

impl Shell {
    /// Open the web page where a signed-in user mints a personal API key for
    /// this desktop app. The web origin pairs with the configured API base
    /// (`api.menivor.com` -> `menivor.com`).
    pub(super) fn open_api_keys_page(&mut self, cx: &mut Context<Self>) {
        let api_base = self.api_base_field.read(cx).text();
        let url = format!(
            "{}/account/api-keys",
            crate::config::web_origin_for_api_base(&api_base)
        );
        cx.open_url(&url);
        self.state.operation_error.clear();
        self.state.activity = format!("Opened {url} in your browser.");
        cx.notify();
    }

    pub(super) fn save_settings(&mut self, cx: &mut Context<Self>) {
        let api_base = self.api_base_field.read(cx).text();
        let new_api_key = self.api_key_field.read(cx).text();
        let editor_path = self.editor_path_field.read(cx).text();
        let use_local_engine = self.preferences.use_local_engine;
        self.api_key_field
            .update(cx, |field, cx| field.set_text("", cx));
        self.state.connection_error.clear();
        self.state.connection = ConnectionState::Checking;
        if self
            .worker
            .send(WorkerCommand::SaveConfiguration {
                base_url: api_base,
                api_key: (!new_api_key.trim().is_empty()).then(|| new_api_key.trim().to_owned()),
                editor_path,
                use_local_engine,
            })
            .is_err()
        {
            self.state.connection = ConnectionState::Failed;
            self.state.connection_error = "The background worker is unavailable.".into();
        }
        if use_local_engine
            && self.sidecar_status == crate::domain::SidecarStatus::Disabled
        {
            self.start_local_sidecar(cx);
        } else if !use_local_engine {
            self.sidecar.stop();
            self.sidecar_status = crate::domain::SidecarStatus::Disabled;
        }
        cx.notify();
    }

    /// Toggle the local engine preference and trigger a sidecar start/stop.
    pub(super) fn toggle_local_engine(&mut self, cx: &mut Context<Self>) {
        self.preferences.use_local_engine = !self.preferences.use_local_engine;
        self.save_settings(cx);
    }

    /// Attempt to start the freegen sidecar; update `sidecar_status` with the
    /// result so the Settings status row reflects it.
    pub(super) fn start_local_sidecar(&mut self, cx: &mut Context<Self>) {
        use crate::domain::{LocalSidecar, SidecarStatus};
        use std::time::Duration;

        let freegen_dir = match LocalSidecar::default_freegen_dir() {
            Some(dir) => dir,
            None => {
                self.sidecar_status = SidecarStatus::NotInstalled(
                    "Local engine: freegen directory not found. \
                     Make sure the repo is on disk next to this binary."
                        .to_owned(),
                );
                return;
            }
        };
        self.sidecar_status = SidecarStatus::Starting;
        match LocalSidecar::start(&freegen_dir) {
            Ok(sidecar) => {
                self.sidecar = sidecar;
                cx.notify();
                // Poll health for up to 15 s off the UI thread, then report back.
                let health = cx
                    .background_executor()
                    .spawn(async { LocalSidecar::wait_for_health(Duration::from_secs(15)) });
                cx.spawn(async move |this, cx| {
                    let healthy = health.await;
                    let _ = this.update(cx, |shell, cx| {
                        shell.sidecar_status = if healthy {
                            SidecarStatus::Running
                        } else {
                            SidecarStatus::NotInstalled(
                                "Local engine: started but did not respond on /health. \
                                 Check that the venv and models are installed."
                                    .to_owned(),
                            )
                        };
                        cx.notify();
                    });
                })
                .detach();
            }
            Err(msg) => {
                self.sidecar_status = SidecarStatus::NotInstalled(msg);
            }
        }
    }

    pub(super) fn clear_credentials(&mut self, cx: &mut Context<Self>) {
        self.state.connection = ConnectionState::Checking;
        self.state.connection_error.clear();
        if self.worker.send(WorkerCommand::ClearCredentials).is_err() {
            self.state.connection = ConnectionState::Failed;
            self.state.connection_error = "The background worker is unavailable.".into();
        }
        cx.notify();
    }
}
