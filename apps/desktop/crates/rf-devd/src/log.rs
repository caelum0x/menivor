//! Dependency-free structured stderr logging for the daemon.
//!
//! The desktop GUI ships no logging framework (it never writes to a console),
//! but a headless long-running daemon must be observable. Following the Unix
//! convention for services, `devd` writes one line per event to stderr —
//! `<epoch_seconds> devd <LEVEL> <message>` — so an operator or an init system
//! (systemd/launchd) can capture and route it. No secrets ever cross this
//! boundary; callers log ids and method names, never request payloads.

use std::io::Write;
use std::time::{SystemTime, UNIX_EPOCH};

fn epoch_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or_default()
}

fn emit(level: &str, message: &str) {
    // Best-effort: a closed/broken stderr must never take the daemon down.
    let mut stderr = std::io::stderr().lock();
    let _ = writeln!(stderr, "{} devd {level} {message}", epoch_seconds());
}

pub(crate) fn info(message: impl AsRef<str>) {
    emit("INFO", message.as_ref());
}

pub(crate) fn warn(message: impl AsRef<str>) {
    emit("WARN", message.as_ref());
}

pub(crate) fn error(message: impl AsRef<str>) {
    emit("ERROR", message.as_ref());
}
