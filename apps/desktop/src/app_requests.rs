//! App-level requests (menu commands, "Open With" files, launch arguments)
//! handed from GPUI's global handlers to the workspace view.
//!
//! Global action handlers and the OS open-URL callback run outside the Shell
//! view, so they enqueue here and the Shell drains the queue on its update tick.

use std::path::PathBuf;
use std::sync::Mutex;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum AppRequest {
    /// Open a file: an editor project or a local source video.
    OpenPath(PathBuf),
    /// Show the open dialog for an editor project.
    PromptOpenProject,
    /// Show the save dialog for the current editor project.
    PromptSaveProject,
}

static PENDING: Mutex<Vec<AppRequest>> = Mutex::new(Vec::new());

pub(crate) fn push(request: AppRequest) {
    if let Ok(mut pending) = PENDING.lock() {
        pending.push(request);
    }
}

pub(crate) fn drain() -> Vec<AppRequest> {
    PENDING
        .lock()
        .map(|mut pending| std::mem::take(&mut *pending))
        .unwrap_or_default()
}

/// Queue every file named on the command line (the Linux `.desktop` entry passes
/// `%U`, which may be plain paths or `file://` URIs). Flags are ignored.
pub(crate) fn queue_launch_arguments() {
    for argument in std::env::args().skip(1) {
        if argument.starts_with('-') {
            continue;
        }
        if let Some(path) = path_from_argument(&argument) {
            push(AppRequest::OpenPath(path));
        }
    }
}

/// Queue files the OS asked us to open (macOS "Open With", Dock drops).
pub(crate) fn queue_open_urls(urls: Vec<String>) {
    for url in urls {
        if let Some(path) = path_from_argument(&url) {
            push(AppRequest::OpenPath(path));
        }
    }
}

/// Resolve a plain path or a `file://` URI to an existing local file.
fn path_from_argument(argument: &str) -> Option<PathBuf> {
    let path = match argument.strip_prefix("file://") {
        Some(rest) => {
            // `file://localhost/path` and `file:///path` are both local.
            let rest = rest.strip_prefix("localhost").unwrap_or(rest);
            PathBuf::from(percent_decode(rest)?)
        }
        None if argument.contains("://") => return None,
        None => PathBuf::from(argument),
    };
    path.is_file().then_some(path)
}

fn percent_decode(value: &str) -> Option<String> {
    let bytes = value.as_bytes();
    let mut decoded = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            let hex = value.get(index + 1..index + 3)?;
            decoded.push(u8::from_str_radix(hex, 16).ok()?);
            index += 3;
        } else {
            decoded.push(bytes[index]);
            index += 1;
        }
    }
    String::from_utf8(decoded).ok()
}
