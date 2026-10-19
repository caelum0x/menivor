//! The Unix-socket server loop: bind, accept, frame, dispatch, shut down.
//!
//! Framing is newline-delimited JSON — one `rf-devproto` `Request` object per
//! line in, one `Response` object per line out. Each accepted connection is
//! served on its own thread, so a slow or misbehaving client can neither block
//! nor crash the others; a panic is confined to that connection's thread. A
//! `SIGINT`/`SIGTERM` flips an atomic flag that unwinds the accept loop and
//! removes the socket file so the next start is clean.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use rf_devproto::{check_version, parse_request, Response};

use crate::dispatch::{dispatch, Engine};
use crate::log;

/// Set by the signal handler to request a graceful shutdown.
static SHUTDOWN: AtomicBool = AtomicBool::new(false);

/// How long the accept loop parks between shutdown-flag checks while no client
/// is knocking. Keeps a stopped daemon from spinning a core.
const ACCEPT_POLL: Duration = Duration::from_millis(100);

/// Async-signal-safe handler: the only thing it does is store into an atomic,
/// which is permitted from a signal context.
extern "C" fn on_signal(_signal: libc::c_int) {
    SHUTDOWN.store(true, Ordering::SeqCst);
}

/// Install `SIGINT`/`SIGTERM` handlers that request a clean shutdown.
fn install_signal_handlers() {
    // SAFETY: `on_signal` only performs an atomic store, which is
    // async-signal-safe, and we register it before any connection thread exists.
    unsafe {
        libc::signal(libc::SIGINT, on_signal as *const () as libc::sighandler_t);
        libc::signal(libc::SIGTERM, on_signal as *const () as libc::sighandler_t);
    }
}

/// Bind the socket at `socket_path`, serving `engine` until a shutdown signal.
/// Any pre-existing socket file is removed first so a stale path from a previous
/// run never blocks the bind.
pub(crate) fn serve(socket_path: &Path, engine: Engine) -> Result<(), String> {
    remove_stale_socket(socket_path)?;
    let listener = UnixListener::bind(socket_path)
        .map_err(|error| format!("bind {}: {error}", socket_path.display()))?;
    listener
        .set_nonblocking(true)
        .map_err(|error| format!("configure the listener: {error}"))?;
    install_signal_handlers();
    log::info(format!("listening on {}", socket_path.display()));

    let engine = Arc::new(engine);
    while !SHUTDOWN.load(Ordering::SeqCst) {
        match listener.accept() {
            Ok((stream, _address)) => {
                let engine = Arc::clone(&engine);
                // One thread per connection isolates faults: a panic or a stuck
                // read touches only this client.
                if let Err(error) = thread::Builder::new()
                    .name("rf-devd-conn".into())
                    .spawn(move || serve_connection(stream, &engine))
                {
                    log::error(format!("spawn connection handler: {error}"));
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(ACCEPT_POLL);
            }
            // Isolate accept-time errors: log and keep serving, never exit.
            Err(error) => log::warn(format!("accept failed: {error}")),
        }
    }

    log::info("shutdown requested; removing socket");
    let _ = std::fs::remove_file(socket_path);
    Ok(())
}

/// Serve one client: read framed requests line by line, dispatch each, and write
/// the framed response back. Errors are contained to this connection.
fn serve_connection(stream: UnixStream, engine: &Engine) {
    // Accepted streams inherit the listener's non-blocking mode on some
    // platforms; force blocking so line reads don't busy-error.
    if let Err(error) = stream.set_nonblocking(false) {
        log::warn(format!("connection setup failed: {error}"));
        return;
    }
    let reader = match stream.try_clone() {
        Ok(clone) => BufReader::new(clone),
        Err(error) => {
            log::warn(format!("clone connection stream: {error}"));
            return;
        }
    };
    let mut writer = stream;
    for line in reader.lines() {
        let line = match line {
            Ok(line) => line,
            Err(error) => {
                log::warn(format!("read frame: {error}"));
                break;
            }
        };
        if line.trim().is_empty() {
            continue;
        }
        let response = handle_frame(engine, &line);
        if let Err(error) = write_frame(&mut writer, &response) {
            log::warn(format!("write response: {error}"));
            break;
        }
    }
}

/// Turn one raw JSON line into a `Response`: enforce the optional version
/// handshake, parse the envelope, then dispatch against the allowlist.
fn handle_frame(engine: &Engine, raw: &str) -> Response {
    if let Some(rejection) = version_gate(raw) {
        return rejection;
    }
    match parse_request(raw) {
        Ok(request) => dispatch(engine, &request),
        Err(rejection) => rejection,
    }
}

/// When a frame advertises a `protocol` field, enforce the daemon's protocol
/// version before dispatch. Absent field = a lenient client; the envelope itself
/// still carries no version, so this stays optional.
fn version_gate(raw: &str) -> Option<Response> {
    let value: serde_json::Value = serde_json::from_str(raw).ok()?;
    let client = value.get("protocol").and_then(|value| value.as_str())?;
    let id = value.get("id").and_then(|value| value.as_u64()).unwrap_or(0);
    check_version(client, id).err()
}

fn write_frame(writer: &mut UnixStream, response: &Response) -> std::io::Result<()> {
    let mut encoded = serde_json::to_string(response)
        .unwrap_or_else(|_| r#"{"id":0,"error":{"code":-32603,"message":"encode failed"}}"#.into());
    encoded.push('\n');
    writer.write_all(encoded.as_bytes())?;
    writer.flush()
}

fn remove_stale_socket(socket_path: &Path) -> Result<(), String> {
    match std::fs::symlink_metadata(socket_path) {
        Ok(_) => std::fs::remove_file(socket_path)
            .map_err(|error| format!("remove stale socket {}: {error}", socket_path.display())),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!(
            "inspect socket path {}: {error}",
            socket_path.display()
        )),
    }
}

/// Resolve the daemon's socket path: `$XDG_RUNTIME_DIR/reelforge-devd.sock`,
/// falling back to `/tmp/reelforge-devd.sock` when the runtime dir is unset.
pub(crate) fn socket_path() -> PathBuf {
    match std::env::var_os("XDG_RUNTIME_DIR") {
        Some(dir) if !dir.is_empty() => PathBuf::from(dir).join("reelforge-devd.sock"),
        _ => PathBuf::from("/tmp/reelforge-devd.sock"),
    }
}
