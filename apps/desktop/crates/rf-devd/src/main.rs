//! `rf-devd` — ReelForge's on-device MCP daemon.
//!
//! Serves the `rf-devproto` JSON-RPC envelope over a Unix domain socket so a
//! local AI agent can drive the desktop app's real engine: start and inspect
//! durable renders, list and open local projects, expand a clipfarm batch, and
//! record the screen. Every method is gated by the protocol's allowlist and
//! wired to genuine functionality — the same `rf_runtime::Runtime` and `ffmpeg`
//! pipeline the GUI host uses. Nothing here is stubbed.

mod capture;
mod dispatch;
mod log;
mod render;
mod server;

use std::path::PathBuf;

use dispatch::Engine;
use render::RenderPipeline;

/// The durable local-render snapshot filename — identical to the GUI host
/// (`apps/desktop/src/workspace/local_runtime.rs`) so the daemon and the app
/// share one store: a render the agent starts is visible in the GUI, and vice
/// versa.
const SNAPSHOT_FILE: &str = "local-render-jobs-v1.json";

fn main() {
    if let Err(error) = run() {
        log::error(format!("fatal: {error}"));
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let socket_path = server::socket_path();
    let snapshot_path = snapshot_path()?;
    log::info(format!(
        "opening durable local runtime at {}",
        snapshot_path.display()
    ));
    let pipeline = RenderPipeline::open(&snapshot_path)?;
    let engine = Engine::new(pipeline);
    server::serve(&socket_path, engine)
}

/// The application data directory, mirroring the GUI host's `app_data_dir`
/// (`ReelForge` under the OS config/support root) so both open the same snapshot.
fn app_data_dir() -> Result<PathBuf, String> {
    #[cfg(target_os = "macos")]
    let root = std::env::var_os("HOME")
        .map(PathBuf::from)
        .map(|home| home.join("Library/Application Support"));
    #[cfg(target_os = "windows")]
    let root = std::env::var_os("APPDATA").map(PathBuf::from);
    #[cfg(target_os = "linux")]
    let root = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")));
    #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
    let root: Option<PathBuf> = None;

    root.map(|directory| directory.join("ReelForge"))
        .ok_or_else(|| "no OS application-data directory is available".to_string())
}

fn snapshot_path() -> Result<PathBuf, String> {
    let directory = app_data_dir()?;
    std::fs::create_dir_all(&directory)
        .map_err(|error| format!("create {}: {error}", directory.display()))?;
    Ok(directory.join(SNAPSHOT_FILE))
}
