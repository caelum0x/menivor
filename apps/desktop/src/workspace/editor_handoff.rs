//! Generate -> edit handoff into WolfCut, the Menivor editor of record
//! (EDITING-SUITE-PLAN Phase 2: GPUI is the generation shell, WolfCut edits).
//!
//! A completed job carries a WolfCut `GeneratedClip` descriptor
//! (`generated_clip` on `GET /jobs/{id}`, built by
//! `apps/api/app/services/generated_clip.py`). The shell writes it to a JSON
//! file and launches WolfCut with `--open-generated-clip <file>`; WolfCut
//! downloads the signed media into the new project's own folder, re-probes it,
//! and lands in the editor on the reel (`wolfcut/desktop/src-tauri/src/handoff.rs`).

use std::path::PathBuf;
use std::process::{Command, Stdio};

use crate::config::{app_data_dir, Preferences};

const HANDOFF_FLAG: &str = "--open-generated-clip";

/// Bundle names WolfCut ships under on macOS, current name first.
#[cfg(target_os = "macos")]
const APP_BUNDLES: &[&str] = &["WolfCut.app", "Menivor Editor.app"];

/// Executable names WolfCut installs as on Windows and Linux.
#[cfg(target_os = "windows")]
const BINARY_NAMES: &[&str] = &["WolfCut.exe", "wolfcut-desktop.exe", "Menivor Editor.exe"];
#[cfg(not(target_os = "windows"))]
const BINARY_NAMES: &[&str] = &["wolfcut-desktop", "WolfCut", "wolfcut", "wolf-cut"];

/// Where the editor was found.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum EditorLocation {
    /// A macOS `.app` bundle, launched through `open`.
    Bundle(PathBuf),
    /// A plain executable.
    Binary(PathBuf),
}

const NOT_INSTALLED: &str = "The Menivor editor (WolfCut) is not installed. Install it, or set \
     its location in Settings (or the MENIVOR_EDITOR_PATH environment variable).";

/// Finds WolfCut: the saved preference, then the `MENIVOR_EDITOR_PATH` /
/// `WOLFCUT_PATH` override, then the platform's standard install locations.
pub(crate) fn locate_editor() -> Result<EditorLocation, String> {
    let configured = Preferences::load()
        .map(|preferences| preferences.editor_path)
        .unwrap_or_default();
    let override_path = std::env::var("MENIVOR_EDITOR_PATH")
        .or_else(|_| std::env::var("WOLFCUT_PATH"))
        .unwrap_or_default();
    for candidate in [configured.trim(), override_path.trim()] {
        if candidate.is_empty() {
            continue;
        }
        let path = PathBuf::from(candidate);
        if path.exists() {
            return Ok(classify(path));
        }
    }

    #[cfg(target_os = "macos")]
    {
        let mut roots = vec![PathBuf::from("/Applications")];
        if let Some(home) = std::env::var_os("HOME") {
            roots.push(PathBuf::from(home).join("Applications"));
        }
        for root in &roots {
            for bundle in APP_BUNDLES {
                let candidate = root.join(bundle);
                if candidate.is_dir() {
                    return Ok(EditorLocation::Bundle(candidate));
                }
            }
        }
    }

    let mut directories: Vec<PathBuf> = Vec::new();
    #[cfg(target_os = "windows")]
    for base in ["LOCALAPPDATA", "ProgramFiles"] {
        if let Some(base) = std::env::var_os(base) {
            let base = PathBuf::from(base);
            directories.push(base.join("WolfCut"));
            directories.push(base.join("Menivor Editor"));
        }
    }
    #[cfg(target_os = "linux")]
    {
        directories.push(PathBuf::from("/usr/bin"));
        directories.push(PathBuf::from("/usr/local/bin"));
        if let Some(home) = std::env::var_os("HOME") {
            directories.push(PathBuf::from(home).join(".local/bin"));
        }
    }
    if let Some(path) = std::env::var_os("PATH") {
        directories.extend(std::env::split_paths(&path));
    }
    for directory in directories {
        for name in BINARY_NAMES {
            let candidate = directory.join(name);
            if candidate.is_file() {
                return Ok(EditorLocation::Binary(candidate));
            }
        }
    }
    Err(NOT_INSTALLED.to_owned())
}

fn classify(path: PathBuf) -> EditorLocation {
    if path.extension().is_some_and(|ext| ext == "app") && path.is_dir() {
        EditorLocation::Bundle(path)
    } else {
        EditorLocation::Binary(path)
    }
}

/// Launches the editor with no handoff: the start screen, or the running
/// window brought forward on macOS.
pub(crate) fn launch_editor() -> Result<(), String> {
    spawn(&locate_editor()?, &[], false)
}

/// Builds the descriptor for a finished job. The API's own `generated_clip`
/// wins; a job without one (B-roll, or an older reel) gets a minimal
/// descriptor whose numeric fields WolfCut replaces after probing the file.
pub(crate) fn descriptor_for_job(
    job_id: &str,
    label: &str,
    api_clip: Option<serde_json::Value>,
    result_url: &str,
) -> Result<serde_json::Value, String> {
    let short: String = job_id.chars().take(8).collect();
    let mut clip = match api_clip {
        Some(serde_json::Value::Object(map)) if map.get("src").and_then(|v| v.as_str()).is_some() => {
            serde_json::Value::Object(map)
        }
        _ => {
            if result_url.trim().is_empty() {
                return Err("This job has no finished media to edit yet.".to_owned());
            }
            serde_json::json!({
                "src": result_url,
                "name": label,
                "width": 0,
                "height": 0,
                "rateNum": 30,
                "rateDen": 1,
                "hasAudio": true,
                "captions": [],
            })
        }
    };
    // One project folder per job: WolfCut names the folder after `name`, and
    // reopening the same job then lands on the edit already in progress.
    let base = clip
        .get("name")
        .and_then(|value| value.as_str())
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .unwrap_or(label)
        .to_owned();
    let name = if base.contains(&short) { base } else { format!("{base} {short}") };
    clip["name"] = serde_json::Value::String(name);
    Ok(clip)
}

/// Writes `descriptor` to the handoff folder and launches WolfCut on it.
pub(crate) fn open_in_editor(job_id: &str, descriptor: &serde_json::Value) -> Result<(), String> {
    let editor = locate_editor()?;
    let file = write_descriptor(job_id, descriptor)?;
    let file = file.to_string_lossy().into_owned();
    spawn(&editor, &[HANDOFF_FLAG, file.as_str()], true)
}

fn write_descriptor(job_id: &str, descriptor: &serde_json::Value) -> Result<PathBuf, String> {
    let folder = app_data_dir()
        .map_err(|error| format!("Could not locate the app data folder: {error}"))?
        .join("editor-handoff");
    std::fs::create_dir_all(&folder)
        .map_err(|error| format!("Could not create {}: {error}", folder.display()))?;
    let safe_id: String = job_id
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
        .take(64)
        .collect();
    let file = folder.join(format!("job-{safe_id}.json"));
    let encoded = serde_json::to_vec_pretty(descriptor)
        .map_err(|error| format!("Could not encode the editor handoff: {error}"))?;
    std::fs::write(&file, encoded)
        .map_err(|error| format!("Could not write {}: {error}", file.display()))?;
    Ok(file)
}

fn spawn(editor: &EditorLocation, args: &[&str], new_instance: bool) -> Result<(), String> {
    let mut command = match editor {
        EditorLocation::Bundle(bundle) => {
            let mut command = Command::new("open");
            if new_instance {
                // A running editor ignores launch arguments; a new instance
                // is what receives the handoff flag.
                command.arg("-n");
            }
            command.arg("-a").arg(bundle);
            if !args.is_empty() {
                command.arg("--args").args(args);
            }
            command
        }
        EditorLocation::Binary(binary) => {
            let mut command = Command::new(binary);
            command.args(args);
            if let Some(parent) = binary.parent().filter(|parent| !parent.as_os_str().is_empty()) {
                command.current_dir(parent);
            }
            command
        }
    };
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not launch the editor: {error}"))
}

#[cfg(test)]
mod tests {
    use super::descriptor_for_job;

    #[test]
    fn api_descriptor_is_kept_and_named_per_job() {
        let api = serde_json::json!({
            "src": "https://r2.example/reel.mp4",
            "name": "Hook line",
            "width": 1080, "height": 1920, "rateNum": 30, "rateDen": 1,
        });
        let clip = descriptor_for_job("abcdef123456", "Reel", Some(api), "").unwrap();
        assert_eq!(clip["name"], "Hook line abcdef12");
        assert_eq!(clip["width"], 1080);
    }

    #[test]
    fn fallback_descriptor_uses_the_result_url() {
        let clip = descriptor_for_job("job1", "B-roll", None, "https://r2.example/b.mp4").unwrap();
        assert_eq!(clip["src"], "https://r2.example/b.mp4");
        assert_eq!(clip["name"], "B-roll job1");
    }

    #[test]
    fn no_media_is_an_error() {
        assert!(descriptor_for_job("job1", "Reel", None, " ").is_err());
    }
}
