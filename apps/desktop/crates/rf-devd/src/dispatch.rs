//! Method dispatch — the daemon's allowlisted bridge from a `rf-devproto`
//! `Request` to the real desktop engine surface.
//!
//! Every method here is wired to genuine behavior: renders run through the same
//! durable `rf_runtime::Runtime` the GUI drives, project queries read that same
//! store, clipfarm expansion goes through the runtime's real dedupe, and screen
//! capture drives a real `ffmpeg`. Nothing is stubbed. The `rf-devproto`
//! allowlist gate ([`validate`]) rejects anything off the list before we ever
//! look at params.

use std::path::Path;
use std::sync::Mutex;

use rf_clipfarm::FanoutMatrix;
use rf_devproto::{validate, Request, Response, ERR_INVALID_REQUEST};
use rf_project::TimelineExport;

use crate::capture::{spec_from_params, CaptureManager};
use crate::render::RenderPipeline;

// App-specific error codes in the JSON-RPC server-error range (-32000..-32099),
// the same convention `rf-devproto` uses for `ERR_UNSUPPORTED_VERSION`.
const ERR_NOT_FOUND: i32 = -32002;
const ERR_ENGINE: i32 = -32003;

/// The shared, thread-safe engine the daemon serves. Each surface is behind its
/// own mutex so an in-flight render never blocks a capture query. Locks recover
/// from poisoning so one panicking connection can never wedge the daemon.
pub(crate) struct Engine {
    pipeline: Mutex<RenderPipeline>,
    captures: Mutex<CaptureManager>,
}

impl Engine {
    pub(crate) fn new(pipeline: RenderPipeline) -> Self {
        Engine {
            pipeline: Mutex::new(pipeline),
            captures: Mutex::new(CaptureManager::new()),
        }
    }
}

/// A handler outcome: either a result payload or an `(error code, message)` pair.
type Handled = Result<serde_json::Value, (i32, String)>;

/// Validate against the allowlist, then run the method against the real engine,
/// mapping the outcome back into a serializable `Response`.
pub(crate) fn dispatch(engine: &Engine, request: &Request) -> Response {
    // The protocol's allowlist gate: unknown/not-allowed methods are rejected
    // here with `ERR_UNKNOWN_METHOD` before any handler sees them.
    if let Err(rejection) = validate(request) {
        return rejection;
    }
    let handled = match request.method.as_str() {
        "render.start" => render_start(engine, &request.params),
        "render.status" => render_status(engine, &request.params),
        "project.list" => project_list(engine),
        "project.open" => project_open(engine, &request.params),
        "clipfarm.run" => clipfarm_run(engine, &request.params),
        "capture.start" => capture_start(engine, &request.params),
        "capture.stop" => capture_stop(engine, &request.params),
        // Unreachable: `validate` already gated the method against the allowlist.
        other => Err((ERR_ENGINE, format!("no handler for allowed method {other}"))),
    };
    match handled {
        Ok(result) => Response::ok(request.id, result),
        Err((code, message)) => Response::err(request.id, code, message),
    }
}

fn lock<'a, T>(mutex: &'a Mutex<T>) -> std::sync::MutexGuard<'a, T> {
    // A poisoned lock means a prior connection panicked mid-op; the engine state
    // is still structurally valid, so recover rather than propagate the panic.
    mutex.lock().unwrap_or_else(|poison| poison.into_inner())
}

fn require_str(params: &serde_json::Value, field: &str) -> Result<String, (i32, String)> {
    params
        .get(field)
        .and_then(|value| value.as_str())
        .filter(|value| !value.trim().is_empty())
        .map(|value| value.to_string())
        .ok_or_else(|| (ERR_INVALID_REQUEST, format!("missing string `{field}`")))
}

fn render_start(engine: &Engine, params: &serde_json::Value) -> Handled {
    let task_id = require_str(params, "task_id")?;
    let input_path = require_str(params, "input_path")?;
    let timeline: Option<TimelineExport> = match params.get("timeline") {
        Some(value) if !value.is_null() => Some(
            serde_json::from_value(value.clone())
                .map_err(|error| (ERR_INVALID_REQUEST, format!("invalid timeline: {error}")))?,
        ),
        _ => None,
    };
    lock(&engine.pipeline)
        .submit(&task_id, Path::new(&input_path), timeline)
        .map_err(|error| (ERR_ENGINE, error))
}

fn render_status(engine: &Engine, params: &serde_json::Value) -> Handled {
    let pipeline = lock(&engine.pipeline);
    match params.get("task_id").and_then(|value| value.as_str()) {
        Some(task_id) => pipeline
            .generation_detail(task_id)
            .ok_or_else(|| (ERR_NOT_FOUND, format!("no render with id {task_id}"))),
        // No id: report the status of every durable local render.
        None => Ok(serde_json::json!({ "renders": pipeline.generation_details() })),
    }
}

fn project_list(engine: &Engine) -> Handled {
    let pipeline = lock(&engine.pipeline);
    Ok(serde_json::json!({ "projects": pipeline.generation_details() }))
}

fn project_open(engine: &Engine, params: &serde_json::Value) -> Handled {
    let task_id = require_str(params, "task_id")?;
    lock(&engine.pipeline)
        .project_open(&task_id)
        .map_err(|error| (ERR_ENGINE, error))?
        .ok_or_else(|| (ERR_NOT_FOUND, format!("no project with id {task_id}")))
}

fn clipfarm_run(engine: &Engine, params: &serde_json::Value) -> Handled {
    let matrix = matrix_from_params(params)?;
    let max_per_account = usize_param(params, "max_per_account");
    let max_total = usize_param(params, "max_total");
    let specs = lock(&engine.pipeline).plan_clipfarm(&matrix, max_per_account, max_total);
    let specs: Vec<serde_json::Value> = specs
        .into_iter()
        .map(|spec| {
            serde_json::json!({
                "spec_hash": spec.spec_hash,
                "body": spec.body,
                "hook": spec.hook,
                "template": spec.template,
                "aspect": spec.aspect,
                "account": spec.account,
            })
        })
        .collect();
    Ok(serde_json::json!({ "count": specs.len(), "specs": specs }))
}

fn capture_start(engine: &Engine, params: &serde_json::Value) -> Handled {
    let spec = spec_from_params(params).map_err(|error| (ERR_INVALID_REQUEST, error))?;
    let capture_id = params
        .get("capture_id")
        .and_then(|value| value.as_str())
        .map(|value| value.to_string());
    lock(&engine.captures)
        .start(capture_id, spec)
        .map_err(|error| (ERR_ENGINE, error))
}

fn capture_stop(engine: &Engine, params: &serde_json::Value) -> Handled {
    let capture_id = require_str(params, "capture_id")?;
    lock(&engine.captures)
        .stop(&capture_id)
        .map_err(|error| (ERR_ENGINE, error))?
        .ok_or_else(|| (ERR_NOT_FOUND, format!("no active capture with id {capture_id}")))
}

fn matrix_from_params(params: &serde_json::Value) -> Result<FanoutMatrix, (i32, String)> {
    let bodies = string_list(params, "bodies");
    if bodies.is_empty() {
        return Err((
            ERR_INVALID_REQUEST,
            "clipfarm.run requires a non-empty `bodies` array".into(),
        ));
    }
    let mut matrix = FanoutMatrix::new(bodies);
    if let Some(hooks) = optional_string_list(params, "hooks") {
        matrix.hooks = hooks;
    }
    if let Some(templates) = optional_string_list(params, "templates") {
        matrix.templates = templates;
    }
    if let Some(aspects) = optional_string_list(params, "aspects") {
        matrix.aspects = aspects;
    }
    if let Some(accounts) = optional_string_list(params, "accounts") {
        matrix.accounts = accounts;
    }
    Ok(matrix)
}

fn string_list(params: &serde_json::Value, field: &str) -> Vec<String> {
    optional_string_list(params, field).unwrap_or_default()
}

/// A present, non-empty JSON array of strings for `field`, or `None`.
fn optional_string_list(params: &serde_json::Value, field: &str) -> Option<Vec<String>> {
    let items: Vec<String> = params
        .get(field)?
        .as_array()?
        .iter()
        .filter_map(|value| value.as_str().map(|value| value.to_string()))
        .collect();
    if items.is_empty() {
        None
    } else {
        Some(items)
    }
}

fn usize_param(params: &serde_json::Value, field: &str) -> usize {
    params
        .get(field)
        .and_then(|value| value.as_u64())
        .map(|value| value as usize)
        .unwrap_or(0)
}
