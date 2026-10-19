//! Local freegen sidecar process management.
//!
//! The freegen sidecar (`tools/freegen/server.py`) runs on
//! `http://127.0.0.1:8765/api/v1` and speaks the same wire protocol as
//! `api.menivor.com/api/v1`.  When the user enables the local free engine in
//! Settings, the desktop app starts this sidecar automatically and kills it on
//! quit.

use std::path::{Path, PathBuf};
use std::process::Child;
use std::time::{Duration, Instant};

/// The port the freegen sidecar listens on.
pub(crate) const SIDECAR_PORT: u16 = 8765;

/// Status of the local freegen sidecar.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum SidecarStatus {
    /// The user has not enabled the local engine.
    Disabled,
    /// The sidecar process has been spawned and we are waiting for it to
    /// respond on `/health` (typically < 5 s with the model cached).
    Starting,
    /// The sidecar responded on `/health` and is ready to serve jobs.
    Running,
    /// The sidecar exited or failed to start.
    NotInstalled(String),
}

impl SidecarStatus {
    /// Human-readable label shown in the Settings status row.
    pub(crate) fn label(&self) -> &str {
        match self {
            Self::Disabled => "",
            Self::Starting => "Local engine: starting",
            Self::Running => "Local engine: running",
            Self::NotInstalled(msg) if msg.is_empty() => "Local engine: not installed",
            Self::NotInstalled(msg) => msg.as_str(),
        }
    }
}

/// Manages the lifecycle of the freegen sidecar child process.
pub(crate) struct LocalSidecar {
    child: Option<Child>,
}

impl Default for LocalSidecar {
    fn default() -> Self {
        Self { child: None }
    }
}

impl LocalSidecar {
    /// Resolve the default freegen directory relative to the running binary.
    ///
    /// Layout on disk: `<app_bundle>/Contents/MacOS/reelforge-desktop`
    /// freegen lives at `<repo_root>/tools/freegen/server.py` when running
    /// from a development checkout.  For a shipped app bundle the sidecar
    /// would be bundled alongside; here we walk up from the binary.
    pub(crate) fn default_freegen_dir() -> Option<PathBuf> {
        // Development: binary is in `target/{profile}/reelforge-desktop`;
        // walk up to the workspace root and descend into tools/freegen.
        let exe = std::env::current_exe().ok()?;
        let mut dir = exe.parent()?;
        for _ in 0..6 {
            let candidate = dir.join("tools/freegen");
            if candidate.join("server.py").exists() {
                return Some(candidate);
            }
            dir = dir.parent()?;
        }
        None
    }

    /// Start the freegen sidecar.  Returns an error message if the venv or
    /// `server.py` is not found.
    pub(crate) fn start(freegen_dir: &Path) -> Result<Self, String> {
        let python = freegen_dir.join(".venv/bin/python");
        let server = freegen_dir.join("server.py");
        if !python.exists() {
            return Err(format!(
                "Local engine: venv not found at {}.  Run the freegen setup first.",
                python.display()
            ));
        }
        if !server.exists() {
            return Err(format!(
                "Local engine: server.py not found at {}.",
                server.display()
            ));
        }
        let child = std::process::Command::new(&python)
            .arg(&server)
            .spawn()
            .map_err(|e| format!("Local engine: failed to start: {e}"))?;
        Ok(Self { child: Some(child) })
    }

    /// Returns `true` if the sidecar process is alive (best-effort: does not
    /// wait for a `/health` response — call `wait_for_health` for that).
    pub(crate) fn process_alive(&mut self) -> bool {
        let Some(child) = self.child.as_mut() else {
            return false;
        };
        matches!(child.try_wait(), Ok(None))
    }

    /// Poll `GET /health` up to `timeout` seconds.  Returns `true` when the
    /// sidecar responds with HTTP 200.
    pub(crate) fn wait_for_health(timeout: Duration) -> bool {
        let url = format!("http://127.0.0.1:{SIDECAR_PORT}/health");
        let deadline = Instant::now() + timeout;
        loop {
            if let Ok(resp) = ureq::get(&url).call() {
                if resp.status() == 200 {
                    return true;
                }
            }
            if Instant::now() >= deadline {
                return false;
            }
            std::thread::sleep(Duration::from_millis(300));
        }
    }

    /// Check health without blocking (single attempt).
    pub(crate) fn is_healthy() -> bool {
        let url = format!("http://127.0.0.1:{SIDECAR_PORT}/health");
        ureq::get(&url)
            .call()
            .map(|r| r.status() == 200)
            .unwrap_or(false)
    }

    /// Kill the child process.  Called on app quit.
    pub(crate) fn stop(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
        }
    }
}

impl Drop for LocalSidecar {
    fn drop(&mut self) {
        self.stop();
    }
}
