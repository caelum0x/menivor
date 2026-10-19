//! Durable editor projects: the timeline an editor session is building.
//!
//! A project stores the raw field text (not the validated `rf_project` model) so
//! an unfinished edit — a half-typed caption, an out-of-range speed — survives a
//! save/open round trip exactly as the creator left it. Validation still happens
//! when the timeline is rendered or exported.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::config::app_data_dir;

/// File extension of a saved editor project (`Launch Reel.menivor`).
pub(crate) const PROJECT_EXTENSION: &str = "menivor";
const PROJECT_FORMAT: &str = "menivor.editor-project";
const PROJECT_VERSION: u8 = 1;
/// Mirrors the editor's own segment ceiling.
const MAX_PROJECT_SEGMENTS: usize = 200;
const MAX_PROJECT_OVERLAYS: usize = 200;
/// Refuse absurd files before parsing so a wrong pick cannot stall the UI.
const MAX_PROJECT_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct ProjectSegment {
    pub source_in: String,
    pub source_out: String,
    pub speed: String,
    #[serde(default)]
    pub caption: String,
    #[serde(default)]
    pub effect: String,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct ProjectOverlay {
    pub text: String,
    pub start: String,
    pub end: String,
    pub position: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct EditorProject {
    format: String,
    version: u8,
    /// The analyzed local source video, re-analyzed on open when it still exists.
    #[serde(default)]
    pub source_path: Option<PathBuf>,
    pub segments: Vec<ProjectSegment>,
    #[serde(default)]
    pub overlays: Vec<ProjectOverlay>,
}

impl EditorProject {
    pub(crate) fn new(
        source_path: Option<PathBuf>,
        segments: Vec<ProjectSegment>,
        overlays: Vec<ProjectOverlay>,
    ) -> Self {
        Self {
            format: PROJECT_FORMAT.into(),
            version: PROJECT_VERSION,
            source_path,
            segments,
            overlays,
        }
    }

    fn validate(self) -> Result<Self, String> {
        if self.format != PROJECT_FORMAT {
            return Err("This file is not a Menivor editor project.".into());
        }
        if self.version != PROJECT_VERSION {
            return Err(format!(
                "This project was saved by a newer Menivor (format v{}). Update the app to open it.",
                self.version
            ));
        }
        if self.segments.is_empty() {
            return Err("The project has no timeline segments.".into());
        }
        if self.segments.len() > MAX_PROJECT_SEGMENTS {
            return Err(format!(
                "The project has {} segments; the editor supports at most {MAX_PROJECT_SEGMENTS}.",
                self.segments.len()
            ));
        }
        if self.overlays.len() > MAX_PROJECT_OVERLAYS {
            return Err(format!(
                "The project has {} overlays; the editor supports at most {MAX_PROJECT_OVERLAYS}.",
                self.overlays.len()
            ));
        }
        Ok(self)
    }

    pub(crate) fn to_json(&self) -> Result<String, String> {
        serde_json::to_string_pretty(self)
            .map_err(|error| format!("Could not encode the project: {error}"))
    }
}

/// `true` when `path` names a saved editor project.
pub(crate) fn is_project_path(path: &Path) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.eq_ignore_ascii_case(PROJECT_EXTENSION))
}

/// Ensure a save target carries the project extension.
pub(crate) fn with_project_extension(path: PathBuf) -> PathBuf {
    if is_project_path(&path) {
        path
    } else {
        path.with_extension(PROJECT_EXTENSION)
    }
}

pub(crate) fn load_project(path: &Path) -> Result<EditorProject, String> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("Could not open {}: {error}", path.display()))?;
    if metadata.len() > MAX_PROJECT_BYTES {
        return Err(format!(
            "{} is too large to be an editor project.",
            path.display()
        ));
    }
    let bytes =
        fs::read(path).map_err(|error| format!("Could not read {}: {error}", path.display()))?;
    let project: EditorProject = serde_json::from_slice(&bytes)
        .map_err(|error| format!("{} is not a valid editor project: {error}", path.display()))?;
    project.validate()
}

/// Atomically write `project` to `path` (temp file + rename).
pub(crate) fn save_project(path: &Path, project: &EditorProject) -> Result<(), String> {
    let body = project.to_json()?;
    write_atomic(path, body.as_bytes())
        .map_err(|error| format!("Could not save {}: {error}", path.display()))
}

/// The autosaved last editor session, restored on the next launch.
pub(crate) fn session_path() -> io::Result<PathBuf> {
    Ok(app_data_dir()?.join("editor-session-v1.json"))
}

pub(crate) fn load_session() -> Option<EditorProject> {
    let path = session_path().ok()?;
    if !path.exists() {
        return None;
    }
    load_project(&path).ok()
}

/// Persist the pre-encoded session JSON (the caller already diffed it).
pub(crate) fn save_session_json(json: &str) -> io::Result<()> {
    let path = session_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    write_atomic(&path, json.as_bytes())
}

fn write_atomic(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("project");
    let temporary = path.with_file_name(format!(".{file_name}.tmp"));
    fs::write(&temporary, bytes)?;
    fs::rename(&temporary, path)
}
