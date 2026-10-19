//! The daemon's render pipeline — a headless port of the desktop host's
//! `DesktopLocalExecutor` (`apps/desktop/src/workspace/local_executor.rs`).
//!
//! It drives the exact same durable engine (`rf_runtime::Runtime`) the GUI host
//! drives: stage the immutable source into the confined artifact root, submit a
//! `rf_project::Project`, lease it, transcode it with a real `ffmpeg` process
//! assembled by `rf_encode`, then complete it only after the runtime verifies
//! the MP4 digest. Nothing here is stubbed; the same lease/fingerprint/attempt
//! invariants gate every terminal transition.

use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use rf_clipfarm::{ClipSpec, FanoutMatrix};
use rf_encode::{build_encode_argv, build_timeline_encode_argv, EncodeTarget, Quality};
use rf_project::{AssetRef, Project, Shot, TimelineExport};
use rf_runtime::{
    Capabilities, LocalArtifactCompletion, LocalJobView, Platform, Runtime, SubmitOutcome,
    TaskExecutionInput,
};
use sha2::{Digest, Sha256};

const LOCAL_NODE_ID: &str = "desktop-local";
const LOCAL_NODE_CAPACITY: u32 = 1;
const LEASE_TTL_SECONDS: u64 = 60;
const DEFAULT_VRAM_BUDGET_MB: u32 = 24_000;
const MAX_DRAIN_ITERATIONS: usize = 1_024;

/// Current wall-clock seconds since the Unix epoch.
pub(crate) fn now_s() -> Result<u64, String> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|error| format!("system clock is before the Unix epoch: {error}"))
}

/// The durable local render engine — the runtime plus its confined artifact root.
pub(crate) struct RenderPipeline {
    runtime: Runtime,
    artifact_root: PathBuf,
}

impl RenderPipeline {
    /// Reopen (or create) the durable render runtime at `snapshot_path`, recover
    /// any interrupted work, and register the single local render lease.
    pub(crate) fn open(snapshot_path: &Path) -> Result<Self, String> {
        let mut runtime = Runtime::open_local(
            snapshot_path.to_path_buf(),
            LEASE_TTL_SECONDS,
            DEFAULT_VRAM_BUDGET_MB,
            now_s()?,
        )
        .map_err(|error| format!("open durable local jobs: {error}"))?;
        let artifact_root = runtime
            .artifact_root()
            .ok_or_else(|| "durable local runtime has no confined artifact root".to_string())?
            .to_path_buf();
        runtime
            .try_add_node(LOCAL_NODE_ID, LOCAL_NODE_CAPACITY)
            .map_err(|error| format!("restore local render lease: {error}"))?;
        Ok(Self {
            runtime,
            artifact_root,
        })
    }

    /// Every local job projected into the shared media-job contract.
    pub(crate) fn generation_details(&self) -> Vec<serde_json::Value> {
        self.runtime
            .generation_details()
            .into_iter()
            .filter_map(|detail| serde_json::to_value(detail).ok())
            .collect()
    }

    /// One local job by task id, or `None` when the id is unknown.
    pub(crate) fn generation_detail(&self, task_id: &str) -> Option<serde_json::Value> {
        self.runtime
            .generation_detail(task_id)
            .and_then(|detail| serde_json::to_value(detail).ok())
    }

    /// One local project by task id, projected as its durable generation detail
    /// plus — only when the runtime has actually verified the artifact digest on
    /// disk — the confined output path. `Ok(None)` when the id is unknown.
    pub(crate) fn project_open(&self, task_id: &str) -> Result<Option<serde_json::Value>, String> {
        let Some(detail) = self.generation_detail(task_id) else {
            return Ok(None);
        };
        let artifact_path = self
            .runtime
            .resolve_verified_artifact_path(task_id)
            .map_err(|error| format!("resolve verified artifact for {task_id}: {error}"))?
            .map(|path| path.display().to_string());
        Ok(Some(serde_json::json!({
            "detail": detail,
            "artifact_path": artifact_path,
        })))
    }

    /// Expand a clipfarm batch through the real durable runtime, which dedupes
    /// against everything already planned this session, paces per account, and
    /// caps the total. `max_*` of 0 means no cap.
    pub(crate) fn plan_clipfarm(
        &mut self,
        matrix: &FanoutMatrix,
        max_per_account: usize,
        max_total: usize,
    ) -> Vec<ClipSpec> {
        self.runtime
            .plan_clipfarm(matrix, max_per_account, max_total)
    }

    /// Stage, submit, lease, transcode, and verify one local portrait render,
    /// returning the terminal generation detail for `task_id`.
    pub(crate) fn submit(
        &mut self,
        task_id: &str,
        input_path: &Path,
        timeline: Option<TimelineExport>,
    ) -> Result<serde_json::Value, String> {
        let project = project_from_request(task_id, input_path, timeline, &self.artifact_root)?;
        self.advance_clock()?;
        match self
            .runtime
            .try_submit_project(&project, 0)
            .map_err(|error| format!("could not persist local work: {error}"))?
        {
            SubmitOutcome::Scheduled { .. } | SubmitOutcome::Partial { .. } => {}
            SubmitOutcome::Blocked { shortfall_micros } => {
                return Err(format!(
                    "local render preflight blocked by {shortfall_micros} micros"
                ));
            }
            SubmitOutcome::Rejected { reason } => {
                return Err(format!("local render rejected: {reason}"));
            }
        }
        self.drain_leased()?;
        self.generation_detail(task_id)
            .ok_or_else(|| format!("render {task_id} left no durable record"))
    }

    fn drain_leased(&mut self) -> Result<(), String> {
        let mut attempted: std::collections::HashSet<String> = std::collections::HashSet::new();
        for _ in 0..MAX_DRAIN_ITERATIONS {
            let next = self.runtime.local_jobs().into_iter().find(|job| {
                job.lease_node.as_deref() == Some(LOCAL_NODE_ID)
                    && !attempted.contains(&job.task_id)
            });
            let Some(job) = next else {
                self.advance_clock()?;
                match self
                    .runtime
                    .try_schedule_queued_jobs()
                    .map_err(|error| format!("could not lease the next local task: {error}"))?
                {
                    SubmitOutcome::Scheduled { leased } if leased > 0 => continue,
                    SubmitOutcome::Partial { leased, .. } if leased > 0 => continue,
                    _ => break,
                }
            };
            attempted.insert(job.task_id.clone());
            self.execute_one(job)?;
        }
        Ok(())
    }

    fn execute_one(&mut self, job: LocalJobView) -> Result<(), String> {
        let Some(lease_token) = job.lease_token.clone() else {
            return Err(format!("{}: lease token is missing", job.task_id));
        };
        let Some(input) = self.runtime.task_execution_input(&job.task_id) else {
            let reason = "persisted local execution input is missing";
            let _ = self.runtime.fail_job_for_attempt(
                &job.task_id,
                &job.execution_fingerprint,
                &job.attempt_id,
                &lease_token,
                reason,
            );
            return Err(format!("{}: {reason}", job.task_id));
        };
        self.advance_clock()?;
        match self.runtime.report_progress_for_attempt(
            &job.task_id,
            &job.execution_fingerprint,
            &job.attempt_id,
            &lease_token,
            0.10,
        ) {
            Ok(true) => {}
            Ok(false) => return Err(format!("{}: lease is no longer executable", job.task_id)),
            Err(error) => return Err(format!("{}: progress rejected: {error}", job.task_id)),
        }

        let artifact_root = self.artifact_root.clone();
        let completion_result = {
            let runtime = &mut self.runtime;
            let mut heartbeat = || -> Result<(), String> {
                let now = now_s()?;
                runtime
                    .try_advance_to(now)
                    .map_err(|error| error.to_string())?;
                match runtime.report_progress_for_attempt(
                    &job.task_id,
                    &job.execution_fingerprint,
                    &job.attempt_id,
                    &lease_token,
                    0.50,
                ) {
                    Ok(true) => Ok(()),
                    Ok(false) => Err("the active attempt lease changed".into()),
                    Err(error) => Err(error.to_string()),
                }
            };
            transcode(&artifact_root, &input, &job.attempt_id, &mut heartbeat)
        };
        let completion = match completion_result {
            Ok(completion) => completion,
            Err(error) => {
                let reason = format!("ffmpeg-local-v1 failed: {error}");
                let _ = self.runtime.fail_job_for_attempt(
                    &job.task_id,
                    &job.execution_fingerprint,
                    &job.attempt_id,
                    &lease_token,
                    &reason,
                );
                return Err(format!("{}: {reason}", job.task_id));
            }
        };

        self.advance_clock()?;
        match self.runtime.report_progress_for_attempt(
            &job.task_id,
            &job.execution_fingerprint,
            &job.attempt_id,
            &lease_token,
            0.90,
        ) {
            Ok(true) => {}
            Ok(false) => return Err(format!("{}: verification lost its live lease", job.task_id)),
            Err(error) => {
                let reason = format!("artifact verification could not start: {error}");
                let _ = self.runtime.fail_job_for_attempt(
                    &job.task_id,
                    &job.execution_fingerprint,
                    &job.attempt_id,
                    &lease_token,
                    &reason,
                );
                return Err(format!("{}: {reason}", job.task_id));
            }
        }

        match self.runtime.complete_job_with_verified_artifact(
            &job.task_id,
            &job.execution_fingerprint,
            &job.attempt_id,
            &lease_token,
            completion,
        ) {
            Ok(true) => Ok(()),
            Ok(false) => Err(format!(
                "{}: completion was rejected by the current lease",
                job.task_id
            )),
            Err(error) => {
                let reason = format!("artifact verification failed: {error}");
                let _ = self.runtime.fail_job_for_attempt(
                    &job.task_id,
                    &job.execution_fingerprint,
                    &job.attempt_id,
                    &lease_token,
                    &reason,
                );
                Err(format!("{}: {reason}", job.task_id))
            }
        }
    }

    fn advance_clock(&mut self) -> Result<(), String> {
        let now = now_s()?;
        self.runtime
            .try_advance_to(now)
            .map_err(|error| error.to_string())
    }
}

/// Build the durable project for one local render — the headless mirror of the
/// host's `project_from_request`. Validates the input, stages an immutable
/// copy into the confined artifact root, and pins it by content hash.
fn project_from_request(
    task_id: &str,
    input_path: &Path,
    timeline: Option<TimelineExport>,
    artifact_root: &Path,
) -> Result<Project, String> {
    if task_id.trim().is_empty() {
        return Err("render.start requires a non-empty task id".into());
    }
    if let Some(timeline) = timeline.as_ref() {
        timeline
            .validate()
            .map_err(|error| format!("the local timeline is not renderable: {error}"))?;
    }
    validate_supported_video(input_path)?;
    let metadata = fs::metadata(input_path)
        .map_err(|error| format!("could not read the selected local video: {error}"))?;
    if !metadata.is_file() {
        return Err("the selected local render input is not a regular file".into());
    }
    let title = input_path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("Local video")
        .to_string();
    let (staged_path, source_sha256) = stage_source(input_path, artifact_root, task_id)?;
    let mut project = Project::new(format!("project-{task_id}"), title);
    project.aspect = "9:16".into();
    project.assets.push(AssetRef {
        cas_key: source_sha256,
        kind: "clip".into(),
        local_path: staged_path.display().to_string(),
    });
    project.timeline = timeline;
    project.shots.push(Shot {
        shot_id: task_id.to_string(),
        order: 0,
        camera_motion: "none".into(),
        duration_ms: 0,
        prompt: "Local portrait transcode".into(),
        seed: 0,
    });
    // Local ffmpeg never contacts a paid provider, so it reserves no wallet spend.
    project.estimate_micros = 0;
    Ok(project)
}

/// Run one real `ffmpeg` portrait transcode assembled by `rf_encode`, publish
/// it atomically, and return the verified completion — the headless port of
/// `FfmpegTranscodeExecutor::execute`.
fn transcode(
    artifact_root: &Path,
    input: &TaskExecutionInput,
    attempt_id: &str,
    heartbeat: &mut dyn FnMut() -> Result<(), String>,
) -> Result<LocalArtifactCompletion, String> {
    let source = validated_source(input)?;
    let relative_path = PathBuf::from("outputs")
        .join(artifact_file_stem(&input.shot.shot_id))
        .join(format!("{}.mp4", artifact_file_stem(attempt_id)));
    let destination = artifact_root.join(&relative_path);
    let parent = destination
        .parent()
        .ok_or_else(|| "local render output has no parent directory".to_string())?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("create local render directory: {error}"))?;
    reject_symlink_destination(&destination)?;
    let temporary = parent.join(format!(".{}.rendering.mp4", artifact_file_stem(attempt_id)));
    if temporary.exists() {
        fs::remove_file(&temporary)
            .map_err(|error| format!("remove interrupted render output: {error}"))?;
    }
    let source_str = source
        .to_str()
        .ok_or_else(|| "local input path is not valid UTF-8".to_string())?;
    let temporary_string = temporary
        .to_str()
        .ok_or_else(|| "local output path is not valid UTF-8".to_string())?;
    let target = EncodeTarget {
        width: 1080,
        height: 1920,
        fps: 30,
        quality: Quality::Standard,
        watermark_free: true,
    };
    let argv = match input.timeline.as_ref() {
        Some(timeline) => build_timeline_encode_argv(
            host_platform(),
            &Capabilities::default(),
            source_str,
            temporary_string,
            &target,
            timeline,
            None,
            source_has_audio(&source)?,
        )?,
        None => build_encode_argv(
            host_platform(),
            &Capabilities::default(),
            source_str,
            temporary_string,
            &target,
        ),
    };

    let mut child = Command::new("ffmpeg")
        .args(["-hide_banner", "-loglevel", "error"])
        .args(&argv)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("start ffmpeg: {error}"))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "capture ffmpeg diagnostics: stderr pipe is missing".to_string())?;
    let stderr_reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut stderr = stderr;
        stderr.read_to_end(&mut bytes).map(|_| bytes)
    });
    let status = loop {
        match child
            .try_wait()
            .map_err(|error| format!("wait for ffmpeg: {error}"))?
        {
            Some(status) => break status,
            None => {
                thread::sleep(Duration::from_secs(1));
                if let Err(error) = heartbeat() {
                    let _ = child.kill();
                    let _ = child.wait();
                    let _ = stderr_reader.join();
                    let _ = fs::remove_file(&temporary);
                    return Err(format!("local render heartbeat failed: {error}"));
                }
            }
        }
    };
    let diagnostics = stderr_reader
        .join()
        .map_err(|_| "ffmpeg diagnostic reader panicked".to_string())?
        .map_err(|error| format!("read ffmpeg diagnostics: {error}"))?;
    if !status.success() {
        let _ = fs::remove_file(&temporary);
        let diagnostics = String::from_utf8_lossy(&diagnostics);
        let diagnostics = diagnostics.trim();
        return Err(if diagnostics.is_empty() {
            format!("ffmpeg exited with {status}")
        } else {
            format!("ffmpeg exited with {status}: {diagnostics}")
        });
    }
    // Fail closed if the pinned source changed while ffmpeg held it open.
    if let Err(error) = validated_source(input) {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }
    File::open(&temporary)
        .and_then(|file| file.sync_all())
        .map_err(|error| format!("fsync rendered video: {error}"))?;
    if destination.exists() {
        let existing = sha256_file(&destination)?;
        let rendered = sha256_file(&temporary)?;
        let _ = fs::remove_file(&temporary);
        if existing != rendered {
            return Err("existing output for this attempt has different bytes".into());
        }
    } else {
        fs::rename(&temporary, &destination)
            .map_err(|error| format!("publish rendered video atomically: {error}"))?;
        let _ = File::open(parent).and_then(|directory| directory.sync_all());
    }
    Ok(LocalArtifactCompletion {
        relative_path,
        expected_sha256: sha256_file(&destination)?,
    })
}

fn validated_source(input: &TaskExecutionInput) -> Result<PathBuf, String> {
    if input.shot.shot_id.is_empty() {
        return Err("persisted local task has no shot identity".into());
    }
    let clips: Vec<&AssetRef> = input
        .assets
        .iter()
        .filter(|asset| asset.kind == "clip")
        .collect();
    if clips.len() != 1 {
        return Err("local portrait render requires exactly one clip asset".into());
    }
    let source = PathBuf::from(&clips[0].local_path);
    validate_supported_video(&source)?;
    let metadata =
        fs::metadata(&source).map_err(|error| format!("read persisted local source: {error}"))?;
    if !metadata.is_file() {
        return Err("persisted local source is not a regular file".into());
    }
    if sha256_file(&source)? != clips[0].cas_key {
        return Err("selected input changed after the project was persisted".into());
    }
    Ok(source)
}

fn validate_supported_video(path: &Path) -> Result<(), String> {
    let extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if matches!(extension.as_str(), "mp4" | "mov" | "webm" | "mkv") {
        Ok(())
    } else {
        Err("choose an MP4, MOV, WebM, or MKV video for local rendering".into())
    }
}

fn source_has_audio(source: &Path) -> Result<bool, String> {
    let output = Command::new("ffprobe")
        .args([
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
        ])
        .arg(source)
        .stdin(Stdio::null())
        .output()
        .map_err(|error| format!("start ffprobe for local timeline: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "ffprobe could not inspect the local timeline source ({})",
            output.status
        ));
    }
    Ok(!String::from_utf8_lossy(&output.stdout).trim().is_empty())
}

fn stage_source(
    selected: &Path,
    artifact_root: &Path,
    task_id: &str,
) -> Result<(PathBuf, String), String> {
    let extension = selected
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or("mp4")
        .to_ascii_lowercase();
    let inputs = artifact_root.join("inputs");
    fs::create_dir_all(&inputs)
        .map_err(|error| format!("create local input staging directory: {error}"))?;
    let temporary = inputs.join(format!(".{}.staging", artifact_file_stem(task_id)));
    if temporary.exists() {
        fs::remove_file(&temporary)
            .map_err(|error| format!("remove interrupted local input staging file: {error}"))?;
    }
    fs::copy(selected, &temporary)
        .map_err(|error| format!("stage selected local video: {error}"))?;
    File::open(&temporary)
        .and_then(|file| file.sync_all())
        .map_err(|error| format!("fsync staged local video: {error}"))?;
    let source_sha256 = sha256_file(&temporary)?;
    let content_id = source_sha256
        .strip_prefix("sha256:")
        .ok_or_else(|| "staged source digest has an invalid format".to_string())?;
    let destination = inputs.join(format!("{content_id}.{extension}"));
    reject_symlink_destination(&destination)?;
    if destination.exists() {
        if sha256_file(&destination)? != source_sha256 {
            let _ = fs::remove_file(&temporary);
            return Err("existing staged source does not match its content id".into());
        }
        let _ = fs::remove_file(&temporary);
    } else {
        fs::rename(&temporary, &destination)
            .map_err(|error| format!("publish staged local video atomically: {error}"))?;
        let _ = File::open(&inputs).and_then(|directory| directory.sync_all());
    }
    let mut permissions = fs::metadata(&destination)
        .map_err(|error| format!("inspect staged local video: {error}"))?
        .permissions();
    permissions.set_readonly(true);
    fs::set_permissions(&destination, permissions)
        .map_err(|error| format!("protect staged local video: {error}"))?;
    Ok((destination, source_sha256))
}

pub(crate) fn host_platform() -> Platform {
    #[cfg(target_os = "macos")]
    return Platform::MacOs;
    #[cfg(target_os = "windows")]
    return Platform::Windows;
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    Platform::Linux
}

/// Collapse an arbitrary id into a filesystem-safe, escape-proof stem.
fn artifact_file_stem(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(|error| format!("open {}: {error}", path.display()))?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| format!("read {}: {error}", path.display()))?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("sha256:{:x}", digest.finalize()))
}

fn reject_symlink_destination(path: &Path) -> Result<(), String> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            Err("refusing a symlink local render destination".into())
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!("inspect local render destination: {error}")),
    }
}
