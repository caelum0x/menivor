//! Desktop-local render execution behind an injected adapter boundary.
//!
//! Production executes a real ffmpeg portrait transcode assembled by
//! `rf-encode`. Tests inject a byte writer. Both paths must pass the resulting
//! artifact through `rf-runtime`'s digest verification before completion.

use std::collections::HashSet;
use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use rf_encode::{build_timeline_encode_argv, EncodeTarget, Quality};
use rf_project::{AssetRef, Project, Shot, TimelineExport};
use rf_runtime::{
    Capabilities, LocalArtifactCompletion, LocalJobView, Platform, Runtime, SubmitOutcome,
    TaskExecutionInput,
};
use sha2::{Digest, Sha256};

use crate::api::GenerationDetail;
use crate::media::toolchain::{ffmpeg_has_filter, media_command, MediaTool};

#[cfg(test)]
use std::process::Command;

const LOCAL_NODE_ID: &str = "desktop-local";
const MAX_DRAIN_ITERATIONS: usize = 1_024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct LocalRenderRequest {
    pub task_id: String,
    pub input_path: PathBuf,
    pub expected_source_sha256: Option<String>,
    pub timeline: Option<TimelineExport>,
}

#[derive(Clone, Debug)]
pub(crate) struct LocalExecutorEvent {
    pub generations: Vec<GenerationDetail>,
    pub message: String,
    pub failed: bool,
}

trait LocalExecutionAdapter {
    fn label(&self) -> &'static str;

    fn execute(
        &self,
        artifact_root: &Path,
        input: &TaskExecutionInput,
        attempt_id: &str,
        heartbeat: &mut dyn FnMut() -> Result<(), String>,
    ) -> Result<LocalArtifactCompletion, String>;
}

trait LocalClock {
    fn now_s(&self) -> Result<u64, String>;
}

struct SystemClock;

impl LocalClock for SystemClock {
    fn now_s(&self) -> Result<u64, String> {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_secs())
            .map_err(|error| format!("system clock is before the Unix epoch: {error}"))
    }
}

#[derive(Default)]
struct FfmpegTranscodeExecutor;

struct TemporarySidecar {
    path: PathBuf,
}

impl Drop for TemporarySidecar {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

impl LocalExecutionAdapter for FfmpegTranscodeExecutor {
    fn label(&self) -> &'static str {
        "ffmpeg-local-v1"
    }

    fn execute(
        &self,
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
        let source = source
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
        let subtitle = input
            .timeline
            .as_ref()
            .map(|timeline| write_timeline_ass(parent, attempt_id, timeline))
            .transpose()?
            .flatten();
        if subtitle.is_some() && !ffmpeg_has_filter("ass")? {
            return Err(
                "local caption burn-in requires an ffmpeg build with the ass/libass filter".into(),
            );
        }
        let argv = match input.timeline.as_ref() {
            Some(timeline) => build_timeline_encode_argv(
                host_platform(),
                &Capabilities::default(),
                source,
                temporary_string,
                &target,
                timeline,
                subtitle.as_ref().and_then(|file| file.path.to_str()),
                source_has_audio(Path::new(source))?,
            )?,
            None => rf_encode::build_encode_argv(
                host_platform(),
                &Capabilities::default(),
                source,
                temporary_string,
                &target,
            ),
        };
        let mut child = media_command(MediaTool::Ffmpeg)?
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
        // Fail closed if even the private staged source changed while ffmpeg
        // held it open. The output is never attributed to the old fingerprint.
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
            if existing == rendered {
                let _ = fs::remove_file(&temporary);
            } else {
                let _ = fs::remove_file(&temporary);
                return Err("existing output for this attempt has different bytes".into());
            }
        } else {
            fs::rename(&temporary, &destination)
                .map_err(|error| format!("publish rendered video atomically: {error}"))?;
            #[cfg(unix)]
            let _ = File::open(parent).and_then(|directory| directory.sync_all());
        }
        Ok(LocalArtifactCompletion {
            relative_path,
            expected_sha256: sha256_file(&destination)?,
        })
    }
}

pub(super) struct DesktopLocalExecutor {
    runtime: Runtime,
    artifact_root: PathBuf,
    adapter: Box<dyn LocalExecutionAdapter>,
    clock: Box<dyn LocalClock>,
}

impl DesktopLocalExecutor {
    pub(super) fn new(runtime: Runtime, artifact_root: PathBuf) -> Self {
        Self {
            runtime,
            artifact_root,
            adapter: Box::<FfmpegTranscodeExecutor>::default(),
            clock: Box::new(SystemClock),
        }
    }

    #[cfg(test)]
    fn with_adapter(
        runtime: Runtime,
        artifact_root: PathBuf,
        adapter: Box<dyn LocalExecutionAdapter>,
    ) -> Self {
        Self {
            runtime,
            artifact_root,
            adapter,
            clock: Box::new(SystemClock),
        }
    }

    pub(super) fn generations(&self) -> Vec<GenerationDetail> {
        self.runtime.generation_details()
    }

    pub(super) fn resolve_verified_artifact_path(
        &self,
        task_id: &str,
    ) -> Result<Option<PathBuf>, String> {
        self.runtime
            .resolve_verified_artifact_path(task_id)
            .map_err(|error| error.to_string())
    }

    pub(super) fn submit(
        &mut self,
        request: LocalRenderRequest,
        emit: &mut dyn FnMut(LocalExecutorEvent),
    ) {
        let project = match project_from_request(request, &self.artifact_root) {
            Ok(project) => project,
            Err(message) => {
                emit(self.event(message, true));
                return;
            }
        };
        if let Err(error) = self.advance_clock() {
            emit(self.event(
                format!("Could not advance local render clock: {error}"),
                true,
            ));
            return;
        }
        // The runtime atomically persists the project execution input and lease
        // before this method is allowed to invoke ffmpeg.
        match self.runtime.try_submit_project(&project, 0) {
            Ok(SubmitOutcome::Scheduled { leased }) => emit(self.event(
                format!("Persisted project and leased {leased} local render."),
                false,
            )),
            Ok(SubmitOutcome::Partial { leased, pending }) => emit(self.event(
                format!("Persisted project: {leased} leased, {pending} waiting for capacity."),
                false,
            )),
            Ok(SubmitOutcome::Blocked { shortfall_micros }) => {
                emit(self.event(
                    format!("Local render preflight blocked by {shortfall_micros} micros."),
                    true,
                ));
                return;
            }
            Ok(SubmitOutcome::Rejected { reason }) => {
                emit(self.event(format!("Local render rejected: {reason}"), true));
                return;
            }
            Err(error) => {
                emit(self.event(format!("Could not persist local work: {error}"), true));
                return;
            }
        }
        self.drain_leased(emit);
    }

    pub(super) fn resume(&mut self, emit: &mut dyn FnMut(LocalExecutorEvent)) {
        if let Err(error) = self.advance_clock() {
            emit(self.event(
                format!("Could not advance local recovery clock: {error}"),
                true,
            ));
            return;
        }
        match self.runtime.try_schedule_queued_jobs() {
            Ok(SubmitOutcome::Scheduled { leased }) if leased > 0 => emit(self.event(
                format!("Recovered and leased {leased} local render."),
                false,
            )),
            Ok(SubmitOutcome::Partial { leased, pending }) => emit(self.event(
                format!("Recovered {leased} local lease; {pending} waiting."),
                false,
            )),
            Ok(SubmitOutcome::Rejected { reason }) => {
                emit(self.event(format!("Local recovery rejected: {reason}"), true));
                return;
            }
            Err(error) => {
                emit(self.event(format!("Could not schedule recovered work: {error}"), true));
                return;
            }
            _ => {}
        }
        self.drain_leased(emit);
    }

    fn drain_leased(&mut self, emit: &mut dyn FnMut(LocalExecutorEvent)) {
        let mut attempted = HashSet::new();
        for _ in 0..MAX_DRAIN_ITERATIONS {
            let Some(job) = self.runtime.local_jobs().into_iter().find(|job| {
                job.lease_node.as_deref() == Some(LOCAL_NODE_ID)
                    && !attempted.contains(&job.task_id)
            }) else {
                if let Err(error) = self.advance_clock() {
                    emit(self.event(
                        format!("Could not advance local scheduler clock: {error}"),
                        true,
                    ));
                    break;
                }
                match self.runtime.try_schedule_queued_jobs() {
                    Ok(SubmitOutcome::Scheduled { leased }) if leased > 0 => continue,
                    Ok(SubmitOutcome::Partial { leased, .. }) if leased > 0 => continue,
                    Ok(_) => break,
                    Err(error) => {
                        emit(self.event(
                            format!("Could not lease the next local task: {error}"),
                            true,
                        ));
                        break;
                    }
                }
            };
            attempted.insert(job.task_id.clone());
            self.execute_one(job, emit);
        }
    }

    fn execute_one(&mut self, job: LocalJobView, emit: &mut dyn FnMut(LocalExecutorEvent)) {
        let Some(lease_token) = job.lease_token.as_deref() else {
            emit(self.event(format!("{}: lease token is missing.", job.task_id), true));
            return;
        };
        let Some(input) = self.runtime.task_execution_input(&job.task_id) else {
            let reason = "persisted local execution input is missing";
            let _ = self.runtime.fail_job_for_attempt(
                &job.task_id,
                &job.execution_fingerprint,
                &job.attempt_id,
                lease_token,
                reason,
            );
            emit(self.event(format!("{}: {reason}.", job.task_id), true));
            return;
        };
        if let Err(error) = self.advance_clock() {
            let reason = format!("could not advance execution clock: {error}");
            let _ = self.runtime.fail_job_for_attempt(
                &job.task_id,
                &job.execution_fingerprint,
                &job.attempt_id,
                lease_token,
                &reason,
            );
            emit(self.event(format!("{}: {reason}", job.task_id), true));
            return;
        }
        match self.runtime.report_progress_for_attempt(
            &job.task_id,
            &job.execution_fingerprint,
            &job.attempt_id,
            lease_token,
            0.10,
        ) {
            Ok(true) => emit(self.event(
                format!("{}: running {}.", job.task_id, self.adapter.label()),
                false,
            )),
            Ok(false) => {
                emit(self.event(
                    format!("{}: lease is no longer executable.", job.task_id),
                    true,
                ));
                return;
            }
            Err(error) => {
                emit(self.event(format!("{}: progress rejected: {error}", job.task_id), true));
                return;
            }
        }

        let completion_result = {
            let runtime = &mut self.runtime;
            let clock = &self.clock;
            let mut heartbeat = || {
                let now_s = clock.now_s()?;
                runtime
                    .try_advance_to(now_s)
                    .map_err(|error| error.to_string())?;
                match runtime.report_progress_for_attempt(
                    &job.task_id,
                    &job.execution_fingerprint,
                    &job.attempt_id,
                    lease_token,
                    0.50,
                ) {
                    Ok(true) => {
                        emit(LocalExecutorEvent {
                            generations: runtime.generation_details(),
                            message: format!("{}: ffmpeg running; lease renewed.", job.task_id),
                            failed: false,
                        });
                        Ok(())
                    }
                    Ok(false) => Err("the active attempt lease changed".into()),
                    Err(error) => Err(error.to_string()),
                }
            };
            self.adapter
                .execute(&self.artifact_root, &input, &job.attempt_id, &mut heartbeat)
        };
        let completion = match completion_result {
            Ok(completion) => completion,
            Err(error) => {
                let reason = format!("{} failed: {error}", self.adapter.label());
                let _ = self.runtime.fail_job_for_attempt(
                    &job.task_id,
                    &job.execution_fingerprint,
                    &job.attempt_id,
                    lease_token,
                    &reason,
                );
                emit(self.event(format!("{}: {reason}", job.task_id), true));
                return;
            }
        };

        if let Err(error) = self.advance_clock() {
            let reason = format!("could not advance verification clock: {error}");
            let _ = self.runtime.fail_job_for_attempt(
                &job.task_id,
                &job.execution_fingerprint,
                &job.attempt_id,
                lease_token,
                &reason,
            );
            emit(self.event(format!("{}: {reason}", job.task_id), true));
            return;
        }

        match self.runtime.report_progress_for_attempt(
            &job.task_id,
            &job.execution_fingerprint,
            &job.attempt_id,
            lease_token,
            0.90,
        ) {
            Ok(true) => emit(self.event(format!("{}: verifying MP4 digest.", job.task_id), false)),
            Ok(false) => {
                emit(self.event(
                    format!("{}: verification lost its live lease.", job.task_id),
                    true,
                ));
                return;
            }
            Err(error) => {
                let reason = format!("artifact verification could not start: {error}");
                let _ = self.runtime.fail_job_for_attempt(
                    &job.task_id,
                    &job.execution_fingerprint,
                    &job.attempt_id,
                    lease_token,
                    &reason,
                );
                emit(self.event(format!("{}: {reason}", job.task_id), true));
                return;
            }
        }

        match self.runtime.complete_job_with_verified_artifact(
            &job.task_id,
            &job.execution_fingerprint,
            &job.attempt_id,
            lease_token,
            completion,
        ) {
            Ok(true) => emit(self.event(
                format!("{}: MP4 verified; local render complete.", job.task_id),
                false,
            )),
            Ok(false) => emit(self.event(
                format!(
                    "{}: completion was rejected by the current lease.",
                    job.task_id
                ),
                true,
            )),
            Err(error) => {
                let reason = format!("artifact verification failed: {error}");
                let _ = self.runtime.fail_job_for_attempt(
                    &job.task_id,
                    &job.execution_fingerprint,
                    &job.attempt_id,
                    lease_token,
                    &reason,
                );
                emit(self.event(format!("{}: {reason}", job.task_id), true));
            }
        }
    }

    fn advance_clock(&mut self) -> Result<(), String> {
        let now_s = self.clock.now_s()?;
        self.runtime
            .try_advance_to(now_s)
            .map_err(|error| error.to_string())
    }

    fn event(&self, message: String, failed: bool) -> LocalExecutorEvent {
        LocalExecutorEvent {
            generations: self.runtime.generation_details(),
            message,
            failed,
        }
    }
}

fn project_from_request(
    request: LocalRenderRequest,
    artifact_root: &Path,
) -> Result<Project, String> {
    if let Some(timeline) = request.timeline.as_ref() {
        timeline
            .validate()
            .map_err(|error| format!("The local timeline is not renderable: {error}"))?;
    }
    validate_supported_video(&request.input_path)?;
    let metadata = fs::metadata(&request.input_path)
        .map_err(|error| format!("Could not read the selected local video: {error}"))?;
    if !metadata.is_file() {
        return Err("The selected local render input is not a regular file.".into());
    }
    if let Some(expected) = request.expected_source_sha256.as_ref() {
        if sha256_file(&request.input_path)? != *expected {
            return Err("The selected editor source changed after waveform analysis.".into());
        }
    }
    let title = request
        .input_path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("Local video")
        .to_string();
    let (staged_path, source_sha256) =
        stage_source(&request.input_path, artifact_root, &request.task_id)?;
    if request
        .expected_source_sha256
        .as_ref()
        .is_some_and(|expected| expected != &source_sha256)
    {
        return Err("The selected editor source changed after waveform analysis.".into());
    }
    let mut project = Project::new(format!("project-{}", request.task_id), title);
    project.aspect = "9:16".into();
    project.assets.push(AssetRef {
        cas_key: source_sha256,
        kind: "clip".into(),
        // Private durable runtime state only. It is never projected in the API,
        // public history contract, logs, or output reference.
        local_path: staged_path.display().to_string(),
    });
    project.timeline = request.timeline;
    project.shots.push(Shot {
        shot_id: request.task_id,
        order: 0,
        camera_motion: "none".into(),
        duration_ms: 0,
        prompt: "Local portrait transcode".into(),
        seed: 0,
    });
    // Local ffmpeg does not contact a paid provider and must not invent a Mint
    // reservation, debit, settlement, identity binding, or receipt.
    project.estimate_micros = 0;
    Ok(project)
}

fn write_timeline_ass(
    parent: &Path,
    attempt_id: &str,
    timeline: &TimelineExport,
) -> Result<Option<TemporarySidecar>, String> {
    let Some(document) = rf_captions::build_timeline_ass(timeline)? else {
        return Ok(None);
    };
    let path = parent.join(format!(".{}.timeline.ass", artifact_file_stem(attempt_id)));
    reject_symlink_destination(&path)?;
    fs::write(&path, document)
        .map_err(|error| format!("write local timeline captions: {error}"))?;
    File::open(&path)
        .and_then(|file| file.sync_all())
        .map_err(|error| format!("fsync local timeline captions: {error}"))?;
    Ok(Some(TemporarySidecar { path }))
}

fn source_has_audio(source: &Path) -> Result<bool, String> {
    let output = media_command(MediaTool::Ffprobe)?
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
    let actual = sha256_file(&source)?;
    if actual != clips[0].cas_key {
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
        Err("Choose an MP4, MOV, WebM, or MKV video for local rendering.".into())
    }
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
        #[cfg(unix)]
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

fn host_platform() -> Platform {
    #[cfg(target_os = "macos")]
    return Platform::MacOs;
    #[cfg(target_os = "windows")]
    return Platform::Windows;
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    Platform::Linux
}

fn artifact_file_stem(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

#[cfg(test)]
fn sha256_hex(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temporary_root(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "menivor-local-executor-{label}-{}-{nonce}",
            std::process::id()
        ))
    }

    struct ByteWriter;

    struct FixedClock(u64);

    impl LocalClock for FixedClock {
        fn now_s(&self) -> Result<u64, String> {
            Ok(self.0)
        }
    }

    impl LocalExecutionAdapter for ByteWriter {
        fn label(&self) -> &'static str {
            "test-byte-writer"
        }

        fn execute(
            &self,
            artifact_root: &Path,
            input: &TaskExecutionInput,
            attempt_id: &str,
            _heartbeat: &mut dyn FnMut() -> Result<(), String>,
        ) -> Result<LocalArtifactCompletion, String> {
            validated_source(input)?;
            let bytes = format!("{}:{attempt_id}", input.shot.shot_id).into_bytes();
            let relative_path = PathBuf::from("outputs/test-output.mp4");
            let destination = artifact_root.join(&relative_path);
            fs::create_dir_all(destination.parent().unwrap()).unwrap();
            fs::write(&destination, &bytes).unwrap();
            Ok(LocalArtifactCompletion {
                relative_path,
                expected_sha256: sha256_hex(&bytes),
            })
        }
    }

    #[test]
    fn changed_input_is_rejected_before_execution() {
        let root = temporary_root("changed");
        fs::create_dir_all(&root).unwrap();
        let source = root.join("source.mp4");
        fs::write(&source, b"original").unwrap();
        let project = project_from_request(
            LocalRenderRequest {
                task_id: "task-two".into(),
                input_path: source.clone(),
                expected_source_sha256: None,
                timeline: None,
            },
            &root.join("artifacts"),
        )
        .unwrap();
        let staged = PathBuf::from(&project.assets[0].local_path);
        let mut permissions = fs::metadata(&staged).unwrap().permissions();
        permissions.set_readonly(false);
        fs::set_permissions(&staged, permissions).unwrap();
        fs::write(staged, b"changed").unwrap();
        let input = TaskExecutionInput {
            project_schema_version: project.schema_version,
            project_id: project.id,
            aspect: project.aspect,
            shot: project.shots[0].clone(),
            assets: project.assets,
            timeline: project.timeline,
        };
        assert!(validated_source(&input).unwrap_err().contains("changed"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn analyzed_source_digest_must_match_before_scheduling() {
        let root = temporary_root("analysis-digest");
        fs::create_dir_all(&root).unwrap();
        let source = root.join("source.mp4");
        fs::write(&source, b"changed-after-analysis").unwrap();
        let error = project_from_request(
            LocalRenderRequest {
                task_id: "task-analysis-digest".into(),
                input_path: source,
                expected_source_sha256: Some(format!("sha256:{}", "0".repeat(64))),
                timeline: None,
            },
            &root.join("artifacts"),
        )
        .unwrap_err();
        assert!(error.contains("changed after waveform analysis"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rejects_unsupported_input_before_hashing_or_scheduling() {
        let error = project_from_request(
            LocalRenderRequest {
                task_id: "task-three".into(),
                input_path: PathBuf::from("notes.txt"),
                expected_source_sha256: None,
                timeline: None,
            },
            &temporary_root("unsupported"),
        )
        .unwrap_err();
        assert!(error.contains("MP4"));
    }

    #[test]
    fn task_and_attempt_ids_cannot_escape_the_artifact_root() {
        assert!(!artifact_file_stem("../../outside").contains('/'));
    }

    #[test]
    fn injected_executor_reaches_only_verified_terminal_completion() {
        let root = temporary_root("lifecycle");
        fs::create_dir_all(&root).unwrap();
        let source = root.join("source.mp4");
        fs::write(&source, b"video-bytes").unwrap();
        let snapshot = root.join("jobs.json");
        let artifacts = root.join("artifacts");
        let mut runtime =
            Runtime::open_local_with_artifact_root(&snapshot, &artifacts, 60, 24_000, 100).unwrap();
        runtime.try_add_node(LOCAL_NODE_ID, 1).unwrap();
        let mut executor =
            DesktopLocalExecutor::with_adapter(runtime, artifacts, Box::new(ByteWriter));
        executor.clock = Box::new(FixedClock(1_000));
        let mut events = Vec::new();
        executor.submit(
            LocalRenderRequest {
                task_id: "task-lifecycle".into(),
                input_path: source,
                expected_source_sha256: None,
                timeline: None,
            },
            &mut |event| events.push(event),
        );
        assert!(!events.is_empty());
        assert!(!events.last().unwrap().failed);
        assert_eq!(executor.runtime.now_s(), 1_000);
        let artifact = executor
            .runtime
            .verified_artifact("task-lifecycle")
            .unwrap();
        assert!(artifact.sha256.starts_with("sha256:"));
        assert_eq!(
            artifact.relative_path,
            PathBuf::from("outputs/test-output.mp4")
        );
        let detail = executor
            .runtime
            .generation_detail("task-lifecycle")
            .unwrap();
        assert_eq!(detail.status, "completed");
        assert!(detail.output_url.is_empty());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn production_ffmpeg_adapter_creates_a_real_verified_mp4() {
        if Command::new("ffmpeg")
            .arg("-version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_err()
        {
            return;
        }
        let root = temporary_root("ffmpeg");
        fs::create_dir_all(&root).unwrap();
        let source = root.join("source.mp4");
        let generated = Command::new("ffmpeg")
            .args([
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=64x64:d=0.1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                source.to_str().unwrap(),
            ])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .unwrap();
        assert!(generated.success());

        let artifacts = root.join("artifacts");
        let project = project_from_request(
            LocalRenderRequest {
                task_id: "task-real-ffmpeg".into(),
                input_path: source,
                expected_source_sha256: None,
                timeline: Some(TimelineExport {
                    segments: vec![rf_project::Segment::new(0, 100)],
                    overlays: vec![],
                }),
            },
            &artifacts,
        )
        .unwrap();
        let input = TaskExecutionInput {
            project_schema_version: project.schema_version,
            project_id: project.id,
            aspect: project.aspect,
            shot: project.shots[0].clone(),
            assets: project.assets,
            timeline: project.timeline,
        };
        let completion = FfmpegTranscodeExecutor
            .execute(&artifacts, &input, "attempt-real", &mut || Ok(()))
            .unwrap();
        assert_eq!(
            completion
                .relative_path
                .components()
                .next()
                .unwrap()
                .as_os_str(),
            "outputs"
        );
        let output = artifacts.join(&completion.relative_path);
        assert!(output.metadata().unwrap().len() > 0);
        assert_eq!(completion.expected_sha256, sha256_file(&output).unwrap());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn production_timeline_render_preserves_audio_and_ordered_speed() {
        if ["ffmpeg", "ffprobe"].iter().any(|binary| {
            Command::new(binary)
                .arg("-version")
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .is_err()
        }) {
            return;
        }
        let root = temporary_root("timeline-audio");
        fs::create_dir_all(&root).unwrap();
        let source = root.join("source-with-audio.mp4");
        let generated = Command::new("ffmpeg")
            .args([
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=64x64:rate=30:duration=2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-shortest",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
                source.to_str().unwrap(),
            ])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .unwrap();
        assert!(generated.success());

        let timeline = TimelineExport {
            segments: vec![
                rf_project::Segment {
                    source_in_ms: 0,
                    source_out_ms: 500,
                    speed_milli: 1000,
                    caption: String::new(),
                    effect_kernel: None,
                },
                rf_project::Segment {
                    source_in_ms: 1000,
                    source_out_ms: 1500,
                    speed_milli: 2000,
                    caption: String::new(),
                    effect_kernel: None,
                },
            ],
            overlays: vec![],
        };
        let artifacts = root.join("artifacts");
        let project = project_from_request(
            LocalRenderRequest {
                task_id: "task-real-timeline-audio".into(),
                input_path: source,
                expected_source_sha256: None,
                timeline: Some(timeline.clone()),
            },
            &artifacts,
        )
        .unwrap();
        assert_eq!(project.timeline, Some(timeline));
        let input = TaskExecutionInput {
            project_schema_version: project.schema_version,
            project_id: project.id,
            aspect: project.aspect,
            shot: project.shots[0].clone(),
            assets: project.assets,
            timeline: project.timeline,
        };
        let completion = FfmpegTranscodeExecutor
            .execute(&artifacts, &input, "attempt-timeline-audio", &mut || Ok(()))
            .unwrap();
        let output = artifacts.join(&completion.relative_path);
        let duration = Command::new("ffprobe")
            .args([
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
            ])
            .arg(&output)
            .output()
            .unwrap();
        assert!(duration.status.success());
        let duration: f64 = String::from_utf8_lossy(&duration.stdout)
            .trim()
            .parse()
            .unwrap();
        assert!((0.65..=0.9).contains(&duration), "duration was {duration}");
        let audio = Command::new("ffprobe")
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
            .arg(&output)
            .output()
            .unwrap();
        assert!(audio.status.success());
        assert!(!String::from_utf8_lossy(&audio.stdout).trim().is_empty());
        assert!(!output.parent().unwrap().read_dir().unwrap().any(|entry| {
            entry
                .unwrap()
                .path()
                .extension()
                .is_some_and(|extension| extension == "ass")
        }));
        let _ = fs::remove_dir_all(root);
    }
}
