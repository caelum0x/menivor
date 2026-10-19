//! Live screen-capture process management for the daemon.
//!
//! `rf-capture` is a pure argv builder; its module doc says "the runtime spawns
//! it." In the GUI that runtime is the host; here `devd` is the runtime. This
//! manager assembles the platform screen-grab argv with `rf_capture` and drives
//! a real `ffmpeg` process, tracking each recording by id so `capture.stop` can
//! end it gracefully (ffmpeg's `q` stdin command) and reap it.

use std::collections::HashMap;
use std::io::Write;
use std::process::{Child, Command, Stdio};

use rf_capture::{build_capture_argv, CaptureSpec, Region};

use crate::render::host_platform;

/// A recording in flight plus the output path it is writing, so a later stop can
/// report where the finished capture landed.
struct ActiveCapture {
    child: Child,
    output: String,
}

/// Tracks every live `ffmpeg` screen capture this daemon started, keyed by a
/// caller-supplied or generated capture id.
pub(crate) struct CaptureManager {
    active: HashMap<String, ActiveCapture>,
    next_id: u64,
}

impl CaptureManager {
    pub(crate) fn new() -> Self {
        CaptureManager {
            active: HashMap::new(),
            next_id: 0,
        }
    }

    /// Spawn one real screen capture and remember it under `capture_id` (a fresh
    /// id is minted when the caller supplies none). Returns the id and the OS pid.
    pub(crate) fn start(
        &mut self,
        capture_id: Option<String>,
        spec: CaptureSpec,
    ) -> Result<serde_json::Value, String> {
        let output = spec.output.clone();
        if output.trim().is_empty() {
            return Err("capture.start requires a non-empty output path".into());
        }
        let capture_id = match capture_id {
            Some(id) if !id.trim().is_empty() => id,
            _ => {
                self.next_id += 1;
                format!("capture-{}", self.next_id)
            }
        };
        if self.active.contains_key(&capture_id) {
            return Err(format!("capture {capture_id} is already recording"));
        }

        let argv = build_capture_argv(host_platform(), &spec);
        // stdin is piped so `capture.stop` can ask ffmpeg to finalize the file.
        let child = Command::new("ffmpeg")
            .args(["-hide_banner", "-loglevel", "error"])
            .args(&argv)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| format!("start ffmpeg screen capture: {error}"))?;
        let pid = child.id();
        self.active
            .insert(capture_id.clone(), ActiveCapture { child, output });

        Ok(serde_json::json!({
            "capture_id": capture_id,
            "pid": pid,
            "output": spec.output,
        }))
    }

    /// End a recording by id: ask ffmpeg to finalize (write `q` to stdin), then
    /// reap it — killing it only if it ignores the graceful request.
    pub(crate) fn stop(&mut self, capture_id: &str) -> Result<Option<serde_json::Value>, String> {
        let Some(mut capture) = self.active.remove(capture_id) else {
            return Ok(None);
        };
        // ffmpeg treats a `q` on stdin as "stop and finalize the output cleanly".
        if let Some(mut stdin) = capture.child.stdin.take() {
            let _ = stdin.write_all(b"q");
            let _ = stdin.flush();
        }
        let status = match capture.child.wait() {
            Ok(status) => status,
            Err(error) => {
                let _ = capture.child.kill();
                return Err(format!("wait for capture {capture_id} to finalize: {error}"));
            }
        };
        Ok(Some(serde_json::json!({
            "capture_id": capture_id,
            "stopped": true,
            "output": capture.output,
            "exit_ok": status.success(),
        })))
    }
}

/// Parse the JSON params of `capture.start` into a validated [`CaptureSpec`].
pub(crate) fn spec_from_params(params: &serde_json::Value) -> Result<CaptureSpec, String> {
    let output = params
        .get("output")
        .and_then(|value| value.as_str())
        .filter(|value| !value.trim().is_empty())
        .ok_or("capture.start requires a string `output` path")?
        .to_string();
    let fps = params
        .get("fps")
        .and_then(|value| value.as_u64())
        .map(|value| value as u32)
        .unwrap_or(30);
    let source = params
        .get("source")
        .and_then(|value| value.as_str())
        .unwrap_or_default()
        .to_string();
    let max_seconds = params
        .get("max_seconds")
        .and_then(|value| value.as_u64())
        .map(|value| value as u32);
    let region = match params.get("region") {
        Some(region) if !region.is_null() => Some(region_from_params(region)?),
        _ => None,
    };
    Ok(CaptureSpec {
        fps,
        source,
        output,
        region,
        max_seconds,
    })
}

fn region_from_params(region: &serde_json::Value) -> Result<Region, String> {
    let field = |name: &str| -> Result<u32, String> {
        region
            .get(name)
            .and_then(|value| value.as_u64())
            .map(|value| value as u32)
            .ok_or_else(|| format!("capture region needs a numeric `{name}`"))
    };
    Ok(Region {
        width: field("width")?,
        height: field("height")?,
        x: field("x")?,
        y: field("y")?,
    })
}
