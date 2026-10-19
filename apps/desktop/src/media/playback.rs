//! Operating-system preview adapter for short-lived signed media URLs.

use std::path::Path;
use std::process::Command;

use crate::api::{ApiFailure, ApiFailureKind};

pub(crate) fn open_signed_preview(url: &str) -> Result<(), ApiFailure> {
    if !(url.starts_with("https://") || url.starts_with("http://")) {
        return Err(ApiFailure {
            kind: ApiFailureKind::InvalidResponse,
            status: None,
            message: "The API returned an invalid preview URL.".into(),
        });
    }

    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("open");
        command.arg(url);
        command
    };
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = Command::new("rundll32.exe");
        command.args(["url.dll,FileProtocolHandler", url]);
        command
    };
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        let mut command = Command::new("xdg-open");
        command.arg(url);
        command
    };

    command.spawn().map(|_| ()).map_err(|error| ApiFailure {
        kind: ApiFailureKind::Connection,
        status: None,
        message: format!("Could not launch the operating-system media viewer: {error}"),
    })
}

/// Open a path already confined and re-verified by `rf-runtime`. This stays a
/// separate boundary from remote URL previews so an `artifact://` reference or
/// untrusted relative string can never reach the operating system launcher.
pub(crate) fn open_verified_local_media(path: &Path) -> Result<(), ApiFailure> {
    if !path.is_absolute() || !path.is_file() {
        return Err(ApiFailure {
            kind: ApiFailureKind::InvalidResponse,
            status: None,
            message: "The verified local artifact is no longer available.".into(),
        });
    }

    #[cfg(target_os = "macos")]
    let mut command = Command::new("open");
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = Command::new("rundll32.exe");
        command.arg("url.dll,FileProtocolHandler");
        command
    };
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = Command::new("xdg-open");
    command.arg(path);

    command.spawn().map(|_| ()).map_err(|error| ApiFailure {
        kind: ApiFailureKind::Connection,
        status: None,
        message: format!("Could not launch the local media viewer: {error}"),
    })
}
