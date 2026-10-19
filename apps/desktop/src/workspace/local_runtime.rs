//! Bootstrap boundary for durable desktop-local execution.

use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use rf_runtime::Runtime;

use crate::config::app_data_dir;
use crate::workspace::local_executor::DesktopLocalExecutor;

const SNAPSHOT_FILE: &str = "local-render-jobs-v1.json";
const LOCAL_NODE_ID: &str = "desktop-local";
const LOCAL_NODE_CAPACITY: u32 = 1;
const LEASE_TTL_SECONDS: u64 = 60;
const DEFAULT_VRAM_BUDGET_MB: u32 = 24_000;

pub(super) fn open_default() -> Result<DesktopLocalExecutor, String> {
    let path = app_data_dir()
        .map_err(|error| format!("resolve local runtime directory: {error}"))?
        .join(SNAPSHOT_FILE);
    let runtime = open_at(&path, unix_seconds()?)?;
    let artifact_root = runtime
        .artifact_root()
        .ok_or_else(|| "durable local runtime has no confined artifact root".to_string())?
        .to_path_buf();
    Ok(DesktopLocalExecutor::new(runtime, artifact_root))
}

fn unix_seconds() -> Result<u64, String> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|error| format!("system clock is before the Unix epoch: {error}"))
}

fn open_at(path: &Path, now_s: u64) -> Result<Runtime, String> {
    let mut runtime = Runtime::open_local(
        PathBuf::from(path),
        LEASE_TTL_SECONDS,
        DEFAULT_VRAM_BUDGET_MB,
        now_s,
    )
    .map_err(|error| format!("open durable local jobs: {error}"))?;
    runtime
        .try_add_node(LOCAL_NODE_ID, LOCAL_NODE_CAPACITY)
        .map_err(|error| format!("restore local render lease: {error}"))?;
    Ok(runtime)
}
