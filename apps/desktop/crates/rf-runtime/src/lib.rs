//! Runtime facade (`rf-runtime`) — the single API the desktop GUI + the on-device
//! MCP daemon call. It composes the engine crates into coherent operations so the
//! UI layer never touches the low-level scheduler/pool directly:
//!
//! * open a `.reelforge` project (`rf-project`) and **pre-flight** it against the
//!   wallet (`rf-sync`),
//! * submit its shots to the **local render farm** (`rf-render` leases +
//!   `rf-jobs` envelopes), keeping models **warm** within VRAM (`rf-comfy`),
//! * expand a **clipfarm** batch (`rf-clipfarm`).
//!
//! Pure orchestration over the crates' pure cores — deterministic + testable; the
//! actual node transport / GPU calls are injected by the app layer.

use std::collections::{HashMap, HashSet};
use std::fmt;
use std::fs::{self, File};
use std::io::Read;
use std::path::{Component, Path, PathBuf};

use rf_clipfarm::{cap_total, pace_by_account, plan_fanout, ClipSpec, FanoutMatrix};
use rf_comfy::{Model, WarmPool};
use rf_gateway::{
    GenerationDetail, MediaExecutionState, MediaLocalArtifactVerification, MediaLocalAttempt,
    MediaLocalAttemptLease, MediaLocalExecutionHistory,
};
use rf_jobs::{RenderJob, State};
use rf_project::{AssetRef, Project, Shot, TimelineExport};
use rf_render::{Coordinator, Lease as CoordinatorLease};
use rf_sync::{wallet_preflight, PreflightResult};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

mod storage;
pub use storage::{JobStorage, LocalAtomicJobStorage, StorageError};

// Re-export the render-chain types so callers use the facade's paths.
pub use rf_hardware::{Capabilities, Platform};
pub use rf_plan::RenderPlan;
pub use rf_render_cmd::RenderRequest;

const SNAPSHOT_SCHEMA_VERSION: u32 = 3;
const LEGACY_SNAPSHOT_SCHEMA_VERSION: u32 = 1;
const PRE_TOKEN_SNAPSHOT_SCHEMA_VERSION: u32 = 2;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LocalArtifactCompletion {
    pub relative_path: PathBuf,
    pub expected_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct VerifiedArtifact {
    /// Content address. Equal to `sha256` and intentionally independent of path.
    pub content_id: String,
    /// Path below the configured artifact root. Absolute host paths are never persisted.
    pub relative_path: PathBuf,
    pub byte_length: u64,
    pub sha256: String,
    pub execution_fingerprint: String,
    pub verified_at_s: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct AttemptLease {
    pub node_id: String,
    pub leased_at_s: u64,
    pub expires_at_s: u64,
    #[serde(default)]
    pub lease_token: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum AttemptOutcome {
    Queued,
    InProgress,
    Verified,
    Failed {
        reason: String,
    },
    ArtifactMissing,
    ArtifactCorrupt {
        expected_sha256: String,
        actual_sha256: String,
    },
    RecoveryExhausted {
        reason: String,
    },
    /// Imported v1 terminal output. It is historical evidence, not verification.
    LegacyUnverified,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct AttemptRecord {
    pub attempt: u32,
    pub attempt_id: String,
    pub retry_of: Option<u32>,
    pub retry_reason: Option<String>,
    pub started_at_s: u64,
    pub finished_at_s: Option<u64>,
    pub outcome: AttemptOutcome,
    pub lease: Option<AttemptLease>,
    pub artifact: Option<VerifiedArtifact>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalJobView {
    pub task_id: String,
    pub state: State,
    pub execution_fingerprint: String,
    pub current_attempt: u32,
    pub attempt_id: String,
    pub lease_node: Option<String>,
    pub lease_token: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct TaskExecutionInput {
    pub project_schema_version: u32,
    pub project_id: String,
    pub aspect: String,
    pub shot: Shot,
    pub assets: Vec<AssetRef>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timeline: Option<TimelineExport>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeSnapshot {
    schema_version: u32,
    saved_at_s: u64,
    jobs: Vec<PersistedJob>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PersistedJob {
    id: String,
    state: String,
    progress: f32,
    output_refs: Vec<String>,
    error: String,
    execution_fingerprint: String,
    created_at_s: u64,
    updated_at_s: u64,
    lease: Option<PersistedLease>,
    #[serde(default)]
    artifact: Option<VerifiedArtifact>,
    #[serde(default)]
    current_attempt: u32,
    #[serde(default)]
    attempt_history: Vec<AttemptRecord>,
    #[serde(default)]
    artifact_recovery_retry_used: bool,
    #[serde(default)]
    execution_input: Option<TaskExecutionInput>,
    #[serde(default)]
    legacy_without_execution_input: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct PersistedLease {
    node_id: String,
    leased_at_s: u64,
    expires_at_s: u64,
    #[serde(default)]
    lease_token: String,
}

#[derive(Debug, Clone)]
struct JobMetadata {
    execution_fingerprint: String,
    created_at_s: u64,
    updated_at_s: u64,
    lease: Option<PersistedLease>,
    artifact: Option<VerifiedArtifact>,
    current_attempt: u32,
    attempt_history: Vec<AttemptRecord>,
    artifact_recovery_retry_used: bool,
    execution_input: Option<TaskExecutionInput>,
    legacy_without_execution_input: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimeError {
    Storage(StorageError),
    ExecutionFingerprintConflict {
        task_id: String,
        persisted: String,
        requested: String,
    },
    InvalidSnapshot(String),
    LeaseRestore(String),
    ArtifactVerification(String),
    ClockRollback {
        current_s: u64,
        requested_s: u64,
    },
}

impl fmt::Display for RuntimeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RuntimeError::Storage(error) => error.fmt(f),
            RuntimeError::ExecutionFingerprintConflict {
                task_id,
                persisted,
                requested,
            } => write!(
                f,
                "execution fingerprint conflict for {task_id}: persisted {persisted}, requested {requested}"
            ),
            RuntimeError::InvalidSnapshot(message) => {
                write!(f, "invalid desktop job snapshot: {message}")
            }
            RuntimeError::LeaseRestore(message) => {
                write!(f, "desktop lease recovery is incomplete: {message}")
            }
            RuntimeError::ArtifactVerification(message) => {
                write!(f, "desktop artifact verification failed: {message}")
            }
            RuntimeError::ClockRollback {
                current_s,
                requested_s,
            } => write!(
                f,
                "desktop runtime clock cannot move backward from {current_s} to {requested_s}"
            ),
        }
    }
}

impl std::error::Error for RuntimeError {}

impl From<StorageError> for RuntimeError {
    fn from(value: StorageError) -> Self {
        RuntimeError::Storage(value)
    }
}

/// The composed desktop runtime.
pub struct Runtime {
    coordinator: Coordinator,
    pool: WarmPool,
    /// task_id -> job envelope (mirrors the cloud render_jobs table locally).
    jobs: HashMap<String, RenderJob>,
    /// Clipfarm spec-hashes planned this session, so repeated batches dedupe.
    seen_clipfarm: HashSet<String>,
    now: u64,
    lease_ttl_s: u64,
    metadata: HashMap<String, JobMetadata>,
    lease_restore_error: Option<String>,
    storage: Option<Box<dyn JobStorage>>,
    artifact_root: Option<PathBuf>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum SubmitOutcome {
    /// All shots leased to local nodes.
    Scheduled { leased: usize },
    /// Some shots leased; `pending` had no free capacity this tick.
    Partial { leased: usize, pending: usize },
    /// The project cannot run: the wallet estimate isn't covered.
    Blocked { shortfall_micros: u64 },
    /// Durable state rejected the request; no work was leased or mutated.
    Rejected { reason: String },
}

impl Runtime {
    pub fn new(lease_ttl_s: u64, vram_budget_mb: u32) -> Self {
        Runtime {
            coordinator: Coordinator::new(lease_ttl_s),
            pool: WarmPool::new(vram_budget_mb),
            jobs: HashMap::new(),
            seen_clipfarm: HashSet::new(),
            now: 0,
            lease_ttl_s,
            metadata: HashMap::new(),
            lease_restore_error: None,
            storage: None,
            artifact_root: None,
        }
    }

    /// Reopen a durable desktop runtime at an injected wall-clock timestamp.
    /// Expired running work is recovered as a fresh queued envelope; live
    /// leases continue to reserve capacity and terminal work remains terminal.
    pub fn open<S: JobStorage + 'static>(
        storage: S,
        lease_ttl_s: u64,
        vram_budget_mb: u32,
        now_s: u64,
    ) -> Result<Self, RuntimeError> {
        if lease_ttl_s == 0 {
            return Err(RuntimeError::InvalidSnapshot(
                "lease TTL must be greater than zero".into(),
            ));
        }
        let bytes = storage.load()?;
        let mut runtime = Runtime {
            coordinator: Coordinator::new(lease_ttl_s),
            pool: WarmPool::new(vram_budget_mb),
            jobs: HashMap::new(),
            seen_clipfarm: HashSet::new(),
            now: now_s,
            lease_ttl_s,
            metadata: HashMap::new(),
            lease_restore_error: None,
            storage: Some(Box::new(storage)),
            artifact_root: None,
        };
        let Some(bytes) = bytes else {
            runtime.persist()?;
            return Ok(runtime);
        };
        let snapshot: RuntimeSnapshot = serde_json::from_slice(&bytes).map_err(|error| {
            RuntimeError::Storage(StorageError::Corrupt(format!("invalid JSON: {error}")))
        })?;
        let recovered = runtime.restore_snapshot(snapshot)?;
        if recovered {
            runtime.persist()?;
        }
        Ok(runtime)
    }

    pub fn open_local(
        path: impl Into<PathBuf>,
        lease_ttl_s: u64,
        vram_budget_mb: u32,
        now_s: u64,
    ) -> Result<Self, RuntimeError> {
        let path = path.into();
        let artifact_root = path.with_extension("artifacts");
        Self::open_local_with_artifact_root(path, artifact_root, lease_ttl_s, vram_budget_mb, now_s)
    }

    pub fn open_local_with_artifact_root(
        path: impl Into<PathBuf>,
        artifact_root: impl Into<PathBuf>,
        lease_ttl_s: u64,
        vram_budget_mb: u32,
        now_s: u64,
    ) -> Result<Self, RuntimeError> {
        let artifact_root = artifact_root.into();
        fs::create_dir_all(&artifact_root).map_err(|error| {
            RuntimeError::ArtifactVerification(format!(
                "create artifact root {}: {error}",
                artifact_root.display()
            ))
        })?;
        let artifact_root = artifact_root.canonicalize().map_err(|error| {
            RuntimeError::ArtifactVerification(format!(
                "canonicalize artifact root {}: {error}",
                artifact_root.display()
            ))
        })?;
        let mut runtime = Self::open(
            LocalAtomicJobStorage::new(path),
            lease_ttl_s,
            vram_budget_mb,
            now_s,
        )?;
        runtime.artifact_root = Some(artifact_root);
        // Generic storage is deliberately unable to trust host paths. Once a
        // confined root is installed, re-check terminal artifacts and durably
        // record any deterministic recovery transition.
        if runtime.recover_invalid_completed_artifacts()? {
            runtime.persist()?;
        }
        Ok(runtime)
    }

    fn restore_snapshot(&mut self, snapshot: RuntimeSnapshot) -> Result<bool, RuntimeError> {
        if !matches!(
            snapshot.schema_version,
            LEGACY_SNAPSHOT_SCHEMA_VERSION
                | PRE_TOKEN_SNAPSHOT_SCHEMA_VERSION
                | SNAPSHOT_SCHEMA_VERSION
        ) {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "unsupported schema version {} (expected {LEGACY_SNAPSHOT_SCHEMA_VERSION}..={SNAPSHOT_SCHEMA_VERSION})",
                snapshot.schema_version
            )));
        }
        let mut recovered_any = false;
        for persisted in snapshot.jobs {
            validate_persisted_job(&persisted, snapshot.schema_version)?;
            if self.jobs.contains_key(&persisted.id) {
                return Err(RuntimeError::InvalidSnapshot(format!(
                    "duplicate task id {}",
                    persisted.id
                )));
            }
            let state = strict_state(&persisted.state)?;
            let mut job = RenderJob::new(persisted.id.clone());
            job.state = state;
            job.progress = persisted.progress;
            job.output_refs = persisted.output_refs;
            job.error = persisted.error;
            let legacy_without_execution_input = persisted.legacy_without_execution_input
                || (snapshot.schema_version < SNAPSHOT_SCHEMA_VERSION
                    && persisted.execution_input.is_none());
            let mut metadata = JobMetadata {
                execution_fingerprint: persisted.execution_fingerprint,
                created_at_s: persisted.created_at_s,
                updated_at_s: persisted.updated_at_s,
                lease: persisted.lease,
                artifact: persisted.artifact,
                current_attempt: persisted.current_attempt,
                attempt_history: persisted.attempt_history,
                artifact_recovery_retry_used: persisted.artifact_recovery_retry_used,
                execution_input: persisted.execution_input,
                legacy_without_execution_input,
            };
            if metadata.current_attempt == 0 {
                metadata.current_attempt = 1;
                metadata.attempt_history = vec![legacy_attempt_record(
                    &job,
                    &metadata,
                    snapshot.schema_version == LEGACY_SNAPSHOT_SCHEMA_VERSION,
                )];
            }
            let missing_current_lease_token = state == State::InProgress
                && metadata
                    .lease
                    .as_ref()
                    .map(|lease| lease.lease_token.is_empty())
                    .unwrap_or(false);
            upgrade_lease_tokens(&mut metadata);

            if state == State::InProgress {
                let lease = metadata.lease.as_ref().expect("validated lease");
                let recovery_reason = if missing_current_lease_token {
                    Some("migration_missing_lease_token")
                } else if lease.expires_at_s <= self.now {
                    Some("lease_expired")
                } else {
                    None
                };
                if let Some(recovery_reason) = recovery_reason {
                    // Recovery is a new envelope rather than an illegal
                    // IN_PROGRESS -> IN_QUEUE transition on the old envelope.
                    job = RenderJob::new(job.id.clone());
                    advance_attempt(&job.id, &mut metadata, self.now, recovery_reason);
                    metadata.lease = None;
                    metadata.updated_at_s = self.now;
                    recovered_any = true;
                }
            }
            self.metadata.insert(job.id.clone(), metadata);
            self.jobs.insert(job.id.clone(), job);
        }
        if self.artifact_root.is_some() && self.recover_invalid_completed_artifacts()? {
            recovered_any = true;
        }
        Ok(recovered_any)
    }

    fn snapshot_from(
        &self,
        jobs: &HashMap<String, RenderJob>,
        metadata: &HashMap<String, JobMetadata>,
        saved_at_s: u64,
    ) -> Result<RuntimeSnapshot, RuntimeError> {
        let mut ids: Vec<&String> = jobs.keys().collect();
        ids.sort();
        let mut persisted = Vec::with_capacity(ids.len());
        for id in ids {
            let job = jobs.get(id).expect("id came from jobs");
            let meta = metadata.get(id).ok_or_else(|| {
                RuntimeError::InvalidSnapshot(format!("job {id} has no durable metadata"))
            })?;
            persisted.push(PersistedJob {
                id: id.clone(),
                state: job.state.to_string(),
                progress: job.progress,
                output_refs: job.output_refs.clone(),
                error: job.error.clone(),
                execution_fingerprint: meta.execution_fingerprint.clone(),
                created_at_s: meta.created_at_s,
                updated_at_s: meta.updated_at_s,
                lease: meta.lease.clone(),
                artifact: meta.artifact.clone(),
                current_attempt: meta.current_attempt,
                attempt_history: meta.attempt_history.clone(),
                artifact_recovery_retry_used: meta.artifact_recovery_retry_used,
                execution_input: meta.execution_input.clone(),
                legacy_without_execution_input: meta.legacy_without_execution_input,
            });
        }
        Ok(RuntimeSnapshot {
            schema_version: SNAPSHOT_SCHEMA_VERSION,
            saved_at_s,
            jobs: persisted,
        })
    }

    fn persist_candidate(
        &self,
        jobs: &HashMap<String, RenderJob>,
        metadata: &HashMap<String, JobMetadata>,
        saved_at_s: u64,
    ) -> Result<(), RuntimeError> {
        let Some(storage) = self.storage.as_ref() else {
            return Ok(());
        };
        let snapshot = self.snapshot_from(jobs, metadata, saved_at_s)?;
        let bytes = serde_json::to_vec_pretty(&snapshot).map_err(|error| {
            RuntimeError::InvalidSnapshot(format!("serialize snapshot: {error}"))
        })?;
        storage.replace(&bytes)?;
        Ok(())
    }

    fn persist(&self) -> Result<(), RuntimeError> {
        self.persist_candidate(&self.jobs, &self.metadata, self.now)
    }

    pub fn add_node(&mut self, id: &str, capacity: u32) {
        if let Err(error) = self.try_add_node(id, capacity) {
            self.lease_restore_error = Some(error.to_string());
        }
    }

    pub fn try_add_node(&mut self, id: &str, capacity: u32) -> Result<(), RuntimeError> {
        if self.coordinator.has_node(id) {
            return Err(RuntimeError::LeaseRestore(format!(
                "node {id} is already registered"
            )));
        }
        let recovered: Vec<CoordinatorLease> = self
            .metadata
            .iter()
            .filter_map(|(task_id, metadata)| {
                let lease = metadata.lease.as_ref()?;
                if lease.node_id != id
                    || lease.expires_at_s <= self.now
                    || self.coordinator.has_active_lease(task_id, self.now)
                {
                    return None;
                }
                Some(CoordinatorLease {
                    task_id: task_id.clone(),
                    node_id: lease.node_id.clone(),
                    expires_at: lease.expires_at_s,
                })
            })
            .collect();
        // Validate the only caller-controlled restore constraint before adding
        // the node. A failed registration must not leave a hidden duplicate
        // node/capacity entry behind for the next retry.
        if recovered.len() > capacity as usize {
            return Err(RuntimeError::LeaseRestore(format!(
                "node {id} capacity {capacity} cannot restore {} live leases",
                recovered.len()
            )));
        }
        self.coordinator.add_node(id, capacity);
        if let Err(error) = self.coordinator.restore_leases(&recovered, self.now) {
            let message = error.to_string();
            self.lease_restore_error = Some(message.clone());
            return Err(RuntimeError::LeaseRestore(message));
        }
        // Any earlier registration error has been corrected. Remaining
        // unregistered live nodes are detected directly by
        // `ensure_leases_restored` rather than cached here.
        self.lease_restore_error = None;
        Ok(())
    }

    pub fn tick(&mut self, seconds: u64) {
        let _ = self.try_tick(seconds);
    }

    pub fn now_s(&self) -> u64 {
        self.now
    }

    pub fn try_advance_to(&mut self, wall_now_s: u64) -> Result<(), RuntimeError> {
        if wall_now_s < self.now {
            return Err(RuntimeError::ClockRollback {
                current_s: self.now,
                requested_s: wall_now_s,
            });
        }
        self.try_tick(wall_now_s - self.now)
    }

    pub fn try_tick(&mut self, seconds: u64) -> Result<(), RuntimeError> {
        let next_now = self.now.saturating_add(seconds);
        let mut next_jobs = self.jobs.clone();
        let mut next_metadata = self.metadata.clone();
        let expired: Vec<String> = next_metadata
            .iter()
            .filter_map(|(task_id, metadata)| {
                metadata
                    .lease
                    .as_ref()
                    .filter(|lease| lease.expires_at_s <= next_now)
                    .map(|_| task_id.clone())
            })
            .collect();
        for task_id in &expired {
            let still_live = next_jobs
                .get(task_id)
                .map(|job| !job.state.is_terminal())
                .unwrap_or(false);
            if still_live {
                // A retry is a fresh envelope; never drive the old envelope
                // backward through an illegal transition.
                next_jobs.insert(task_id.clone(), RenderJob::new(task_id));
                if let Some(metadata) = next_metadata.get_mut(task_id) {
                    advance_attempt(task_id, metadata, next_now, "lease_expired");
                    metadata.lease = None;
                    metadata.updated_at_s = next_now;
                }
            }
        }
        self.persist_candidate(&next_jobs, &next_metadata, next_now)?;
        self.jobs = next_jobs;
        self.metadata = next_metadata;
        self.now = next_now;
        // A prior restore error may have referred only to leases that have now
        // expired. Recompute truth from durable metadata on the next operation.
        self.lease_restore_error = None;
        for task_id in expired {
            self.coordinator.complete_task(&task_id);
        }
        let _ = self.coordinator.reclaim_expired(self.now);
        Ok(())
    }

    /// A node reports progress on a running task: advance the envelope and
    /// heartbeat its lease so a long render isn't reclaimed mid-flight. Returns
    /// false if the task is unknown.
    pub fn report_progress(&mut self, task_id: &str, progress: f32) -> bool {
        self.try_report_progress(task_id, None, None, progress)
            .unwrap_or(false)
    }

    pub fn report_progress_with_fingerprint(
        &mut self,
        task_id: &str,
        execution_fingerprint: &str,
        progress: f32,
    ) -> Result<bool, RuntimeError> {
        self.try_report_progress(task_id, Some(execution_fingerprint), None, progress)
    }

    pub fn report_progress_for_attempt(
        &mut self,
        task_id: &str,
        execution_fingerprint: &str,
        attempt_id: &str,
        lease_token: &str,
        progress: f32,
    ) -> Result<bool, RuntimeError> {
        self.try_report_progress(
            task_id,
            Some(execution_fingerprint),
            Some((attempt_id, lease_token)),
            progress,
        )
    }

    fn try_report_progress(
        &mut self,
        task_id: &str,
        fingerprint: Option<&str>,
        attempt_auth: Option<(&str, &str)>,
        progress: f32,
    ) -> Result<bool, RuntimeError> {
        if self.storage.is_some() && attempt_auth.is_none() {
            return Err(RuntimeError::ArtifactVerification(
                "durable progress callback requires attempt_id and lease_token".into(),
            ));
        }
        if !self.check_execution_fingerprint(task_id, fingerprint)? {
            return Ok(false);
        }
        if let Some((attempt_id, lease_token)) = attempt_auth {
            if !self.check_attempt_lease(task_id, attempt_id, lease_token) {
                return Ok(false);
            }
        }
        let Some(metadata) = self.metadata.get(task_id) else {
            return Ok(false);
        };
        let Some(lease) = metadata.lease.as_ref() else {
            return Ok(false);
        };
        if lease.expires_at_s <= self.now || !self.has_live_lease(task_id) {
            return Ok(false);
        }
        let mut next_jobs = self.jobs.clone();
        let mut next_metadata = self.metadata.clone();
        let job = next_jobs.get_mut(task_id).expect("metadata has job");
        if job.state.is_terminal() || job.transition(State::InProgress, Some(progress)).is_err() {
            return Ok(false);
        }
        let metadata = next_metadata.get_mut(task_id).expect("metadata exists");
        metadata.updated_at_s = self.now;
        let expires_at_s = self.now.saturating_add(self.lease_ttl_s);
        metadata.lease.as_mut().expect("checked lease").expires_at_s = expires_at_s;
        if let Some(attempt) = current_attempt_mut(metadata) {
            attempt.outcome = AttemptOutcome::InProgress;
            if let Some(lease) = attempt.lease.as_mut() {
                lease.expires_at_s = expires_at_s;
            }
        }
        self.persist_candidate(&next_jobs, &next_metadata, self.now)?;
        self.jobs = next_jobs;
        self.metadata = next_metadata;
        debug_assert!(self.coordinator.renew_lease(task_id, self.now));
        Ok(true)
    }

    /// A node finished a task: complete the envelope (attaching outputs) and free
    /// its lease slot immediately for the next shot. Returns false if unknown.
    pub fn complete_job(&mut self, task_id: &str, output_refs: Vec<String>) -> bool {
        self.try_complete_legacy_job(task_id, None, output_refs)
            .unwrap_or(false)
    }

    pub fn complete_job_with_fingerprint(
        &mut self,
        task_id: &str,
        execution_fingerprint: &str,
        output_refs: Vec<String>,
    ) -> Result<bool, RuntimeError> {
        self.try_complete_legacy_job(task_id, Some(execution_fingerprint), output_refs)
    }

    /// Backward-compatible completion for ephemeral runtimes only. Durable
    /// runtimes reject it because opaque references cannot prove output bytes.
    fn try_complete_legacy_job(
        &mut self,
        task_id: &str,
        fingerprint: Option<&str>,
        output_refs: Vec<String>,
    ) -> Result<bool, RuntimeError> {
        if !self.check_execution_fingerprint(task_id, fingerprint)? {
            return Ok(false);
        }
        if self.storage.is_some() {
            return Err(RuntimeError::ArtifactVerification(
                "durable completion requires complete_job_with_verified_artifact".into(),
            ));
        }
        let Some(current) = self.jobs.get(task_id) else {
            return Ok(false);
        };
        if current.state.is_terminal() {
            return Ok(current.state == State::Completed && current.output_refs == output_refs);
        }
        if !self.has_live_lease(task_id) {
            return Ok(false);
        }
        let mut next_jobs = self.jobs.clone();
        let mut next_metadata = self.metadata.clone();
        if next_jobs
            .get_mut(task_id)
            .expect("known job")
            .complete(output_refs)
            .is_err()
        {
            return Ok(false);
        }
        let metadata = next_metadata.get_mut(task_id).expect("known metadata");
        metadata.lease = None;
        metadata.updated_at_s = self.now;
        metadata.artifact = None;
        if let Some(attempt) = current_attempt_mut(metadata) {
            attempt.finished_at_s = Some(self.now);
            attempt.outcome = AttemptOutcome::LegacyUnverified;
            attempt.artifact = None;
        }
        self.persist_candidate(&next_jobs, &next_metadata, self.now)?;
        self.jobs = next_jobs;
        self.metadata = next_metadata;
        self.coordinator.complete_task(task_id);
        Ok(true)
    }

    pub fn complete_job_with_verified_artifact(
        &mut self,
        task_id: &str,
        execution_fingerprint: &str,
        attempt_id: &str,
        lease_token: &str,
        completion: LocalArtifactCompletion,
    ) -> Result<bool, RuntimeError> {
        if !self.check_execution_fingerprint(task_id, Some(execution_fingerprint))? {
            return Ok(false);
        }
        let Some(current) = self.jobs.get(task_id) else {
            return Ok(false);
        };
        if !self.check_attempt_lease(task_id, attempt_id, lease_token) {
            return Ok(false);
        }
        if self.artifact_root.is_none() {
            return Err(RuntimeError::ArtifactVerification(
                "runtime has no configured confined artifact root".into(),
            ));
        }
        if !is_sha256(&completion.expected_sha256) {
            return Err(RuntimeError::ArtifactVerification(
                "expected_sha256 must be lowercase sha256:<64 hex>".into(),
            ));
        }
        if !is_safe_output_path(&completion.relative_path) {
            return Err(RuntimeError::ArtifactVerification(
                "artifact path must be a normalized relative path below outputs/".into(),
            ));
        }
        let artifact = match self.verify_completion_artifact(execution_fingerprint, &completion) {
            Ok(artifact) => artifact,
            Err(failure) => {
                self.record_artifact_failure(task_id, failure.clone(), None)?;
                return Err(RuntimeError::ArtifactVerification(failure.message()));
            }
        };
        if artifact.sha256 != completion.expected_sha256 {
            self.record_artifact_digest_rejection(
                task_id,
                &completion.expected_sha256,
                artifact.clone(),
            )?;
            return Err(RuntimeError::ArtifactVerification(format!(
                "digest mismatch for {}: expected {}, computed {}",
                completion.relative_path.display(),
                completion.expected_sha256,
                artifact.sha256
            )));
        }
        if current.state.is_terminal() {
            let persisted = self
                .metadata
                .get(task_id)
                .and_then(|metadata| metadata.artifact.as_ref());
            return Ok(current.state == State::Completed
                && persisted
                    .map(|persisted| {
                        persisted.content_id == artifact.content_id
                            && persisted.relative_path == artifact.relative_path
                            && persisted.byte_length == artifact.byte_length
                            && persisted.execution_fingerprint == artifact.execution_fingerprint
                    })
                    .unwrap_or(false));
        }
        if !self.has_live_lease(task_id) {
            return Ok(false);
        }
        let output_ref = format!("artifact://{}", artifact.content_id);
        let mut next_jobs = self.jobs.clone();
        let mut next_metadata = self.metadata.clone();
        if next_jobs
            .get_mut(task_id)
            .expect("known job")
            .complete(vec![output_ref])
            .is_err()
        {
            return Ok(false);
        }
        let metadata = next_metadata.get_mut(task_id).expect("known metadata");
        metadata.lease = None;
        metadata.updated_at_s = self.now;
        metadata.artifact = Some(artifact.clone());
        if let Some(attempt) = current_attempt_mut(metadata) {
            attempt.finished_at_s = Some(self.now);
            attempt.outcome = AttemptOutcome::Verified;
            attempt.artifact = Some(artifact);
        }
        self.persist_candidate(&next_jobs, &next_metadata, self.now)?;
        self.jobs = next_jobs;
        self.metadata = next_metadata;
        self.coordinator.complete_task(task_id);
        Ok(true)
    }

    /// A node crashed / a render errored: fail the envelope and free its slot (a
    /// retry is a fresh submit). Returns false if unknown.
    pub fn fail_job(&mut self, task_id: &str, reason: &str) -> bool {
        self.try_fail_job(task_id, None, reason).unwrap_or(false)
    }

    pub fn fail_job_with_fingerprint(
        &mut self,
        task_id: &str,
        execution_fingerprint: &str,
        reason: &str,
    ) -> Result<bool, RuntimeError> {
        self.try_fail_job(task_id, Some(execution_fingerprint), reason)
    }

    pub fn fail_job_for_attempt(
        &mut self,
        task_id: &str,
        execution_fingerprint: &str,
        attempt_id: &str,
        lease_token: &str,
        reason: &str,
    ) -> Result<bool, RuntimeError> {
        self.try_fail_job_authorized(
            task_id,
            Some(execution_fingerprint),
            Some((attempt_id, lease_token)),
            reason,
        )
    }

    fn try_fail_job(
        &mut self,
        task_id: &str,
        fingerprint: Option<&str>,
        reason: &str,
    ) -> Result<bool, RuntimeError> {
        self.try_fail_job_authorized(task_id, fingerprint, None, reason)
    }

    fn try_fail_job_authorized(
        &mut self,
        task_id: &str,
        fingerprint: Option<&str>,
        attempt_auth: Option<(&str, &str)>,
        reason: &str,
    ) -> Result<bool, RuntimeError> {
        if self.storage.is_some() && attempt_auth.is_none() {
            return Err(RuntimeError::ArtifactVerification(
                "durable failure callback requires attempt_id and lease_token".into(),
            ));
        }
        if !self.check_execution_fingerprint(task_id, fingerprint)? {
            return Ok(false);
        }
        if let Some((attempt_id, lease_token)) = attempt_auth {
            if !self.check_attempt_lease(task_id, attempt_id, lease_token) {
                return Ok(false);
            }
        }
        let Some(current) = self.jobs.get(task_id) else {
            return Ok(false);
        };
        if current.state.is_terminal() {
            return Ok(current.state == State::Failed && current.error == reason);
        }
        if !self.has_live_lease(task_id) {
            return Ok(false);
        }
        let mut next_jobs = self.jobs.clone();
        let mut next_metadata = self.metadata.clone();
        if next_jobs
            .get_mut(task_id)
            .expect("known job")
            .fail(reason)
            .is_err()
        {
            return Ok(false);
        }
        let metadata = next_metadata.get_mut(task_id).expect("known metadata");
        metadata.lease = None;
        metadata.updated_at_s = self.now;
        metadata.artifact = None;
        if let Some(attempt) = current_attempt_mut(metadata) {
            attempt.finished_at_s = Some(self.now);
            attempt.outcome = AttemptOutcome::Failed {
                reason: reason.to_string(),
            };
            attempt.artifact = None;
        }
        self.persist_candidate(&next_jobs, &next_metadata, self.now)?;
        self.jobs = next_jobs;
        self.metadata = next_metadata;
        self.coordinator.complete_task(task_id);
        Ok(true)
    }

    /// Expand a clipfarm batch, deduping against everything planned earlier this
    /// session, then pace per account and cap the total. Remembers the new
    /// spec-hashes so a later batch won't repeat them. This is the runtime's
    /// composition of `rf-clipfarm` the module doc promises. `max_*` of 0 = no cap.
    pub fn plan_clipfarm(
        &mut self,
        matrix: &FanoutMatrix,
        max_per_account: usize,
        max_total: usize,
    ) -> Vec<ClipSpec> {
        let plan = plan_fanout(matrix, &self.seen_clipfarm);
        for spec in &plan.specs {
            self.seen_clipfarm.insert(spec.spec_hash.clone());
        }
        let paced = pace_by_account(&plan.specs, max_per_account);
        cap_total(&paced, max_total)
    }

    /// Ensure the render model is warm before scheduling (VRAM-budgeted).
    pub fn warm_model(&mut self, name: &str, vram_mb: u32) -> bool {
        !matches!(
            self.pool.request(&Model {
                name: name.to_string(),
                vram_mb
            }),
            rf_comfy::Admit::TooLarge
        )
    }

    fn has_live_lease(&self, task_id: &str) -> bool {
        let Some(durable) = self
            .metadata
            .get(task_id)
            .and_then(|metadata| metadata.lease.as_ref())
        else {
            return false;
        };
        if durable.expires_at_s <= self.now {
            return false;
        }
        self.coordinator
            .lease_for(task_id, self.now)
            .map(|lease| {
                lease.node_id == durable.node_id && lease.expires_at == durable.expires_at_s
            })
            .unwrap_or(false)
    }

    fn ensure_leases_restored(&self) -> Result<(), RuntimeError> {
        if let Some(message) = &self.lease_restore_error {
            return Err(RuntimeError::LeaseRestore(message.clone()));
        }
        let missing: Vec<String> = self
            .metadata
            .iter()
            .filter_map(|(task_id, metadata)| {
                metadata
                    .lease
                    .as_ref()
                    .filter(|lease| lease.expires_at_s > self.now)
                    .filter(|_| !self.has_live_lease(task_id))
                    .map(|lease| format!("{task_id}@{}", lease.node_id))
            })
            .collect();
        if missing.is_empty() {
            Ok(())
        } else {
            Err(RuntimeError::LeaseRestore(format!(
                "register the persisted lease nodes before scheduling: {}",
                missing.join(", ")
            )))
        }
    }

    pub fn lease_node(&self, task_id: &str) -> Option<&str> {
        self.metadata
            .get(task_id)
            .and_then(|metadata| metadata.lease.as_ref())
            .filter(|lease| lease.expires_at_s > self.now)
            .map(|lease| lease.node_id.as_str())
    }

    fn check_execution_fingerprint(
        &self,
        task_id: &str,
        requested: Option<&str>,
    ) -> Result<bool, RuntimeError> {
        let Some(metadata) = self.metadata.get(task_id) else {
            return Ok(false);
        };
        let Some(requested) = requested else {
            return Ok(true);
        };
        if requested == metadata.execution_fingerprint {
            return Ok(true);
        }
        Err(RuntimeError::ExecutionFingerprintConflict {
            task_id: task_id.to_string(),
            persisted: metadata.execution_fingerprint.clone(),
            requested: requested.to_string(),
        })
    }

    fn check_attempt_lease(&self, task_id: &str, attempt_id: &str, lease_token: &str) -> bool {
        let Some(metadata) = self.metadata.get(task_id) else {
            return false;
        };
        let Some(current_lease) = metadata.lease.as_ref() else {
            // Terminal idempotent completion authenticates against retained
            // history after the live lease is intentionally cleared.
            return current_attempt(metadata)
                .filter(|attempt| attempt.attempt_id == attempt_id)
                .and_then(|attempt| attempt.lease.as_ref())
                .map(|lease| lease.lease_token == lease_token)
                .unwrap_or(false);
        };
        current_attempt(metadata)
            .filter(|attempt| attempt.attempt_id == attempt_id)
            .and_then(|attempt| attempt.lease.as_ref())
            .map(|lease| {
                lease.lease_token == lease_token
                    && current_lease.lease_token == lease_token
                    && lease.node_id == current_lease.node_id
                    && lease.leased_at_s == current_lease.leased_at_s
                    && lease.expires_at_s == current_lease.expires_at_s
            })
            .unwrap_or(false)
    }

    pub fn execution_fingerprint(&self, task_id: &str) -> Option<&str> {
        self.metadata
            .get(task_id)
            .map(|metadata| metadata.execution_fingerprint.as_str())
    }

    pub fn artifact_root(&self) -> Option<&Path> {
        self.artifact_root.as_deref()
    }

    pub fn task_execution_input(&self, task_id: &str) -> Option<TaskExecutionInput> {
        self.metadata.get(task_id)?.execution_input.clone()
    }

    pub fn resolve_verified_artifact_path(
        &self,
        task_id: &str,
    ) -> Result<Option<PathBuf>, RuntimeError> {
        let Some(artifact) = self.verified_artifact(task_id) else {
            return Ok(None);
        };
        let root = self.artifact_root.as_ref().ok_or_else(|| {
            RuntimeError::ArtifactVerification("runtime has no artifact root".into())
        })?;
        let (byte_length, digest) =
            inspect_confined_artifact(root, &artifact.relative_path, &artifact.sha256)
                .map_err(|failure| RuntimeError::ArtifactVerification(failure.message()))?;
        if byte_length != artifact.byte_length || digest != artifact.sha256 {
            return Err(RuntimeError::ArtifactVerification(format!(
                "artifact {} changed after verification",
                artifact.relative_path.display()
            )));
        }
        Ok(Some(root.join(&artifact.relative_path)))
    }

    pub fn verified_artifact(&self, task_id: &str) -> Option<&VerifiedArtifact> {
        let job = self.jobs.get(task_id)?;
        if job.state != State::Completed {
            return None;
        }
        self.metadata.get(task_id)?.artifact.as_ref()
    }

    pub fn attempt_history(&self, task_id: &str) -> Option<&[AttemptRecord]> {
        self.metadata
            .get(task_id)
            .map(|metadata| metadata.attempt_history.as_slice())
    }

    pub fn local_jobs(&self) -> Vec<LocalJobView> {
        let mut task_ids: Vec<&String> = self.jobs.keys().collect();
        task_ids.sort();
        task_ids
            .into_iter()
            .filter_map(|task_id| {
                let job = self.jobs.get(task_id)?;
                let metadata = self.metadata.get(task_id)?;
                Some(LocalJobView {
                    task_id: task_id.clone(),
                    state: job.state,
                    execution_fingerprint: metadata.execution_fingerprint.clone(),
                    current_attempt: metadata.current_attempt,
                    attempt_id: current_attempt(metadata)
                        .map(|attempt| attempt.attempt_id.clone())
                        .unwrap_or_default(),
                    lease_node: metadata.lease.as_ref().map(|lease| lease.node_id.clone()),
                    lease_token: metadata
                        .lease
                        .as_ref()
                        .map(|lease| lease.lease_token.clone()),
                })
            })
            .collect()
    }

    fn verify_completion_artifact(
        &self,
        execution_fingerprint: &str,
        completion: &LocalArtifactCompletion,
    ) -> Result<VerifiedArtifact, ArtifactFailure> {
        let root = self
            .artifact_root
            .as_ref()
            .expect("completion validated root");
        let (byte_length, actual_sha256) = inspect_confined_artifact(
            root,
            &completion.relative_path,
            &completion.expected_sha256,
        )?;
        Ok(VerifiedArtifact {
            content_id: actual_sha256.clone(),
            relative_path: completion.relative_path.clone(),
            byte_length,
            sha256: actual_sha256,
            execution_fingerprint: execution_fingerprint.to_string(),
            verified_at_s: self.now,
        })
    }

    fn record_artifact_digest_rejection(
        &mut self,
        task_id: &str,
        expected_sha256: &str,
        observed: VerifiedArtifact,
    ) -> Result<(), RuntimeError> {
        self.record_artifact_failure(
            task_id,
            ArtifactFailure::Corrupt {
                expected_sha256: expected_sha256.to_string(),
                actual_sha256: observed.sha256.clone(),
            },
            Some(observed),
        )
    }

    fn record_artifact_failure(
        &mut self,
        task_id: &str,
        failure: ArtifactFailure,
        observed: Option<VerifiedArtifact>,
    ) -> Result<(), RuntimeError> {
        let mut next_jobs = self.jobs.clone();
        let mut next_metadata = self.metadata.clone();
        let job = next_jobs.get_mut(task_id).expect("known artifact job");
        if !job.state.is_terminal() {
            job.fail("local artifact digest mismatch")
                .expect("live local job may fail");
        }
        let metadata = next_metadata
            .get_mut(task_id)
            .expect("known artifact metadata");
        metadata.lease = None;
        metadata.artifact = None;
        metadata.updated_at_s = self.now;
        if let Some(attempt) = current_attempt_mut(metadata) {
            attempt.finished_at_s = Some(self.now);
            attempt.outcome = failure.outcome();
            attempt.artifact = observed;
        }
        self.persist_candidate(&next_jobs, &next_metadata, self.now)?;
        self.jobs = next_jobs;
        self.metadata = next_metadata;
        self.coordinator.complete_task(task_id);
        Ok(())
    }

    fn recover_invalid_completed_artifacts(&mut self) -> Result<bool, RuntimeError> {
        let Some(root) = self.artifact_root.as_ref() else {
            return Ok(false);
        };
        let mut task_ids: Vec<String> = self
            .jobs
            .iter()
            .filter(|(_, job)| job.state == State::Completed)
            .map(|(task_id, _)| task_id.clone())
            .collect();
        task_ids.sort();
        let mut changed = false;
        for task_id in task_ids {
            let metadata = self.metadata.get(&task_id).expect("completed job metadata");
            let failure = match metadata.artifact.as_ref() {
                None => Some(ArtifactFailure::LegacyUnverified),
                Some(artifact)
                    if artifact.content_id != artifact.sha256
                        || artifact.execution_fingerprint != metadata.execution_fingerprint
                        || !is_sha256(&artifact.sha256) =>
                {
                    Some(ArtifactFailure::Corrupt {
                        expected_sha256: artifact.sha256.clone(),
                        actual_sha256: "invalid_record_binding".into(),
                    })
                }
                Some(artifact) => {
                    match inspect_confined_artifact(root, &artifact.relative_path, &artifact.sha256)
                    {
                        Ok((byte_length, actual_sha256))
                            if byte_length == artifact.byte_length
                                && actual_sha256 == artifact.sha256 =>
                        {
                            None
                        }
                        Ok((_, actual_sha256)) => Some(ArtifactFailure::Corrupt {
                            expected_sha256: artifact.sha256.clone(),
                            actual_sha256,
                        }),
                        Err(failure) => Some(failure),
                    }
                }
            };
            let Some(failure) = failure else {
                continue;
            };
            let reason = failure.retry_reason();
            let metadata = self
                .metadata
                .get_mut(&task_id)
                .expect("completed job metadata");
            if let Some(attempt) = current_attempt_mut(metadata) {
                attempt.outcome = failure.outcome();
            }
            metadata.artifact = None;
            metadata.lease = None;
            metadata.updated_at_s = self.now;
            if metadata.artifact_recovery_retry_used {
                if let Some(attempt) = current_attempt_mut(metadata) {
                    attempt.outcome = AttemptOutcome::RecoveryExhausted {
                        reason: reason.clone(),
                    };
                }
                let mut failed = RenderJob::new(&task_id);
                failed
                    .fail(format!("artifact recovery exhausted: {reason}"))
                    .expect("queued job may fail");
                self.jobs.insert(task_id.clone(), failed);
            } else {
                metadata.artifact_recovery_retry_used = true;
                advance_attempt(&task_id, metadata, self.now, &reason);
                self.jobs.insert(task_id.clone(), RenderJob::new(&task_id));
            }
            changed = true;
        }
        Ok(changed)
    }

    /// Open + pre-flight a project, then submit its shots to the local farm.
    /// Returns `Blocked` (nothing scheduled) when the wallet doesn't cover the
    /// project's estimate.
    pub fn submit_project(&mut self, project: &Project, available_micros: u64) -> SubmitOutcome {
        self.try_submit_project(project, available_micros)
            .unwrap_or_else(|error| SubmitOutcome::Rejected {
                reason: error.to_string(),
            })
    }

    pub fn try_submit_project(
        &mut self,
        project: &Project,
        available_micros: u64,
    ) -> Result<SubmitOutcome, RuntimeError> {
        self.ensure_leases_restored()?;
        match wallet_preflight(project.estimate_micros, available_micros) {
            PreflightResult::Insufficient { shortfall_micros } => {
                return Ok(SubmitOutcome::Blocked { shortfall_micros });
            }
            PreflightResult::Ok { .. } => {}
        }

        let requested: Vec<(String, String, TaskExecutionInput)> = project
            .shots
            .iter()
            .map(|shot| {
                (
                    shot.shot_id.clone(),
                    project_execution_fingerprint(project, shot),
                    TaskExecutionInput::from_project_shot(project, shot),
                )
            })
            .collect();
        let mut seen = HashSet::new();
        for (task_id, fingerprint, execution_input) in &requested {
            if task_id.is_empty() || !seen.insert(task_id) {
                return Err(RuntimeError::InvalidSnapshot(format!(
                    "project contains empty or duplicate task id {task_id:?}"
                )));
            }
            if let Some(existing) = self.metadata.get(task_id) {
                if existing.execution_fingerprint != *fingerprint {
                    return Err(RuntimeError::ExecutionFingerprintConflict {
                        task_id: task_id.clone(),
                        persisted: existing.execution_fingerprint.clone(),
                        requested: fingerprint.clone(),
                    });
                }
                if existing.execution_input.as_ref() != Some(execution_input) {
                    return Err(RuntimeError::ExecutionFingerprintConflict {
                        task_id: task_id.clone(),
                        persisted: existing.execution_fingerprint.clone(),
                        requested: execution_input.execution_fingerprint(),
                    });
                }
            }
        }

        let mut next_jobs = self.jobs.clone();
        let mut next_metadata = self.metadata.clone();
        for (task_id, fingerprint, execution_input) in &requested {
            next_jobs
                .entry(task_id.clone())
                .or_insert_with(|| RenderJob::new(task_id));
            next_metadata
                .entry(task_id.clone())
                .or_insert_with(|| JobMetadata {
                    execution_fingerprint: fingerprint.clone(),
                    created_at_s: self.now,
                    updated_at_s: self.now,
                    lease: None,
                    artifact: None,
                    current_attempt: 1,
                    attempt_history: vec![new_attempt_record(
                        task_id,
                        fingerprint,
                        1,
                        None,
                        None,
                        self.now,
                    )],
                    artifact_recovery_retry_used: false,
                    execution_input: Some(execution_input.clone()),
                    legacy_without_execution_input: false,
                });
        }
        let task_ids: Vec<String> = requested
            .iter()
            .map(|(task_id, _, _)| task_id.clone())
            .collect();

        // Only truly queued envelopes are eligible. In-progress and recovered
        // live envelopes already have exact-node coordinator leases.
        let envelopes: Vec<RenderJob> = task_ids
            .iter()
            .filter_map(|id| {
                next_jobs
                    .get(id)
                    .filter(|job| job.state == State::InQueue)
                    .cloned()
            })
            .collect();
        let schedulable = envelopes.len();
        let leases = self.coordinator.assign_jobs(&envelopes, self.now);
        for lease in &leases {
            let job = next_jobs.get_mut(&lease.task_id).expect("leased known job");
            let _ = job.transition(State::InProgress, Some(0.0));
            let metadata = next_metadata
                .get_mut(&lease.task_id)
                .expect("leased known metadata");
            metadata.updated_at_s = self.now;
            let attempt_id = current_attempt(metadata)
                .expect("leased metadata has current attempt")
                .attempt_id
                .clone();
            let lease_token =
                make_lease_token(&attempt_id, &lease.node_id, self.now, lease.expires_at);
            metadata.lease = Some(PersistedLease {
                node_id: lease.node_id.clone(),
                leased_at_s: self.now,
                expires_at_s: lease.expires_at,
                lease_token: lease_token.clone(),
            });
            if let Some(attempt) = current_attempt_mut(metadata) {
                attempt.outcome = AttemptOutcome::InProgress;
                attempt.lease = Some(AttemptLease {
                    node_id: lease.node_id.clone(),
                    leased_at_s: self.now,
                    expires_at_s: lease.expires_at,
                    lease_token,
                });
            }
        }
        if let Err(error) = self.persist_candidate(&next_jobs, &next_metadata, self.now) {
            for lease in &leases {
                self.coordinator.complete_task(&lease.task_id);
            }
            return Err(error);
        }
        self.jobs = next_jobs;
        self.metadata = next_metadata;
        let leased = leases.len();
        let pending = schedulable.saturating_sub(leased);
        if pending == 0 {
            Ok(SubmitOutcome::Scheduled { leased })
        } else {
            Ok(SubmitOutcome::Partial { leased, pending })
        }
    }

    /// Lease all durable queued envelopes without requiring the original
    /// project. Their execution fingerprints were committed at first submit.
    pub fn try_schedule_queued_jobs(&mut self) -> Result<SubmitOutcome, RuntimeError> {
        self.ensure_leases_restored()?;
        let mut next_jobs = self.jobs.clone();
        let mut next_metadata = self.metadata.clone();
        let mut task_ids: Vec<String> = next_jobs
            .iter()
            .filter(|(_, job)| job.state == State::InQueue)
            .map(|(task_id, _)| task_id.clone())
            .collect();
        task_ids.sort();
        if let Some(task_id) = task_ids.iter().find(|task_id| {
            next_metadata
                .get(*task_id)
                .and_then(|metadata| metadata.execution_input.as_ref())
                .is_none()
        }) {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "queued legacy job {task_id} has no recoverable execution input"
            )));
        }
        let envelopes: Vec<RenderJob> = task_ids
            .iter()
            .filter_map(|task_id| next_jobs.get(task_id).cloned())
            .collect();
        let schedulable = envelopes.len();
        let leases = self.coordinator.assign_jobs(&envelopes, self.now);
        for lease in &leases {
            let job = next_jobs.get_mut(&lease.task_id).expect("leased known job");
            let _ = job.transition(State::InProgress, Some(0.0));
            let metadata = next_metadata
                .get_mut(&lease.task_id)
                .expect("leased known metadata");
            metadata.updated_at_s = self.now;
            let attempt_id = current_attempt(metadata)
                .expect("leased metadata has current attempt")
                .attempt_id
                .clone();
            let lease_token =
                make_lease_token(&attempt_id, &lease.node_id, self.now, lease.expires_at);
            metadata.lease = Some(PersistedLease {
                node_id: lease.node_id.clone(),
                leased_at_s: self.now,
                expires_at_s: lease.expires_at,
                lease_token: lease_token.clone(),
            });
            if let Some(attempt) = current_attempt_mut(metadata) {
                attempt.outcome = AttemptOutcome::InProgress;
                attempt.lease = Some(AttemptLease {
                    node_id: lease.node_id.clone(),
                    leased_at_s: self.now,
                    expires_at_s: lease.expires_at,
                    lease_token,
                });
            }
        }
        if let Err(error) = self.persist_candidate(&next_jobs, &next_metadata, self.now) {
            for lease in &leases {
                self.coordinator.complete_task(&lease.task_id);
            }
            return Err(error);
        }
        self.jobs = next_jobs;
        self.metadata = next_metadata;
        let leased = leases.len();
        let pending = schedulable.saturating_sub(leased);
        if pending == 0 {
            Ok(SubmitOutcome::Scheduled { leased })
        } else {
            Ok(SubmitOutcome::Partial { leased, pending })
        }
    }

    pub fn job_state(&self, task_id: &str) -> Option<State> {
        self.jobs.get(task_id).map(|j| j.state)
    }

    /// Project a local render into the same durable media-job contract used by
    /// the API and Prism. This is a read-only view: local execution never
    /// synthesizes a Mint charge, Identity Lock binding, or signed receipt.
    pub fn generation_detail(&self, task_id: &str) -> Option<GenerationDetail> {
        let job = self.jobs.get(task_id)?;
        let status = match job.state {
            State::InQueue => "queued",
            State::InProgress => "in_progress",
            State::Completed => "completed",
            State::Failed | State::Cancelled => "failed",
        };
        let terminal = job.state.is_terminal();
        // Host paths and non-URL artifact references stay inside local history.
        let output_url = String::new();
        let error = if job.state == State::Cancelled && job.error.is_empty() {
            "local render cancelled".to_string()
        } else {
            job.error.clone()
        };
        Some(GenerationDetail {
            id: task_id.to_string(),
            model: "local-render".into(),
            modality: "video".into(),
            provider: "desktop-local".into(),
            status: status.into(),
            seconds: 0,
            held_cost_micros: 0,
            actual_cost_micros: 0,
            effective_cost_micros: 0,
            cost_micros: 0,
            settlement_status: if terminal { "released" } else { "held" }.into(),
            settlement_rail: "desktop_local".into(),
            output_url: output_url.clone(),
            url: output_url,
            error,
            correlation_id: format!("desktop_{task_id}"),
            provider_request_id: task_id.to_string(),
            execution: MediaExecutionState {
                kind: "desktop_local".into(),
                provider_request_id: task_id.to_string(),
                resumable: !terminal,
                local: self
                    .metadata
                    .get(task_id)
                    .map(|metadata| MediaLocalExecutionHistory {
                        schema: "menivor.desktop-local-execution/v1".into(),
                        executor: "ffmpeg-local-v1".into(),
                        execution_fingerprint: metadata.execution_fingerprint.clone(),
                        attempts: metadata
                            .attempt_history
                            .iter()
                            .map(|attempt| {
                                project_attempt(attempt, &metadata.execution_fingerprint)
                            })
                            .collect(),
                    }),
            },
            created_at: None,
            updated_at: None,
            is_terminal: terminal,
            identity: None,
            settlement_evidence: None,
            margin_source: None,
        })
    }

    /// Stable task-id ordered projection used by the desktop bootstrap to show
    /// every recovered local job before it accepts new work.
    pub fn generation_details(&self) -> Vec<GenerationDetail> {
        let mut task_ids: Vec<&String> = self.jobs.keys().collect();
        task_ids.sort();
        task_ids
            .into_iter()
            .filter_map(|task_id| self.generation_detail(task_id))
            .collect()
    }

    pub fn active_jobs(&self) -> usize {
        self.metadata
            .values()
            .filter(|metadata| {
                metadata
                    .lease
                    .as_ref()
                    .map(|lease| lease.expires_at_s > self.now)
                    .unwrap_or(false)
            })
            .count()
    }

    /// Assemble the full local `ffmpeg` render command for a reel from its
    /// resolved [`RenderPlan`] + concrete inputs. The facade entry point the GUI
    /// / on-device daemon call so the whole render chain (shots → plan → compose
    /// + audio → argv) sits behind one API alongside scheduling.
    pub fn render_command(&self, plan: &RenderPlan, request: &RenderRequest) -> Vec<String> {
        rf_render_cmd::build_render_argv(plan, request)
    }

    /// Like [`render_command`](Self::render_command), but encodes with the host's
    /// best available **hardware** encoder (VideoToolbox/NVENC/QSV/VAAPI/AMF),
    /// falling back to software x264 when the box has no GPU encoder — the path a
    /// desktop "render locally, use my GPU" toggle drives. The `platform` + probed
    /// [`Capabilities`] are supplied by the app layer.
    pub fn render_command_hw(
        &self,
        plan: &RenderPlan,
        request: &RenderRequest,
        platform: Platform,
        caps: &Capabilities,
    ) -> Vec<String> {
        rf_render_cmd::build_render_argv_hw(plan, request, platform, caps)
    }
}

impl TaskExecutionInput {
    fn from_project_shot(project: &Project, shot: &Shot) -> Self {
        Self {
            project_schema_version: project.schema_version,
            project_id: project.id.clone(),
            aspect: project.aspect.clone(),
            shot: shot.clone(),
            assets: project.assets.clone(),
            timeline: project.timeline.clone(),
        }
    }

    pub fn execution_fingerprint(&self) -> String {
        match &self.timeline {
            None => hash_serializable(&(
                "desktop-local-execution-v1",
                self.project_schema_version,
                &self.project_id,
                &self.aspect,
                &self.shot,
                &self.assets,
            )),
            Some(timeline) => hash_serializable(&(
                "desktop-local-execution-v2",
                self.project_schema_version,
                &self.project_id,
                &self.aspect,
                &self.shot,
                &self.assets,
                timeline,
            )),
        }
    }
}

#[derive(Debug, Clone)]
enum ArtifactFailure {
    Missing,
    Corrupt {
        expected_sha256: String,
        actual_sha256: String,
    },
    LegacyUnverified,
}

impl ArtifactFailure {
    fn outcome(&self) -> AttemptOutcome {
        match self {
            Self::Missing => AttemptOutcome::ArtifactMissing,
            Self::Corrupt {
                expected_sha256,
                actual_sha256,
            } => AttemptOutcome::ArtifactCorrupt {
                expected_sha256: expected_sha256.clone(),
                actual_sha256: actual_sha256.clone(),
            },
            Self::LegacyUnverified => AttemptOutcome::LegacyUnverified,
        }
    }

    fn retry_reason(&self) -> String {
        match self {
            Self::Missing => "artifact_missing".into(),
            Self::Corrupt { .. } => "artifact_corrupt".into(),
            Self::LegacyUnverified => "legacy_output_unverified".into(),
        }
    }

    fn message(&self) -> String {
        match self {
            Self::Missing => "artifact is missing or not a confined regular file".into(),
            Self::Corrupt {
                expected_sha256,
                actual_sha256,
            } => format!(
                "artifact digest mismatch: expected {expected_sha256}, computed {actual_sha256}"
            ),
            Self::LegacyUnverified => "legacy artifact has no verifiable record".into(),
        }
    }
}

fn inspect_confined_artifact(
    root: &Path,
    relative_path: &Path,
    expected_sha256: &str,
) -> Result<(u64, String), ArtifactFailure> {
    if !is_safe_relative_path(relative_path) {
        return Err(ArtifactFailure::Corrupt {
            expected_sha256: expected_sha256.to_string(),
            actual_sha256: "invalid_relative_path".into(),
        });
    }
    let candidate = root.join(relative_path);
    let metadata = match fs::symlink_metadata(&candidate) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Err(ArtifactFailure::Missing)
        }
        Err(_) => return Err(ArtifactFailure::Missing),
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(ArtifactFailure::Corrupt {
            expected_sha256: expected_sha256.to_string(),
            actual_sha256: "not_regular_file".into(),
        });
    }
    let canonical = candidate
        .canonicalize()
        .map_err(|_| ArtifactFailure::Missing)?;
    if !canonical.starts_with(root) {
        return Err(ArtifactFailure::Corrupt {
            expected_sha256: expected_sha256.to_string(),
            actual_sha256: "path_escape".into(),
        });
    }
    let mut file = File::open(&canonical).map_err(|_| ArtifactFailure::Missing)?;
    let mut hasher = Sha256::new();
    let mut byte_length = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| ArtifactFailure::Missing)?;
        if count == 0 {
            break;
        }
        byte_length = byte_length.saturating_add(count as u64);
        hasher.update(&buffer[..count]);
    }
    if byte_length == 0 {
        return Err(ArtifactFailure::Corrupt {
            expected_sha256: expected_sha256.to_string(),
            actual_sha256: format_digest(hasher.finalize()),
        });
    }
    Ok((byte_length, format_digest(hasher.finalize())))
}

fn is_safe_relative_path(path: &Path) -> bool {
    !path.as_os_str().is_empty()
        && path
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
}

fn is_safe_output_path(path: &Path) -> bool {
    is_safe_relative_path(path)
        && matches!(path.components().next(), Some(Component::Normal(component)) if component == "outputs")
        && path.components().count() > 1
}

fn portable_relative_reference(path: &Path) -> Option<String> {
    is_safe_relative_path(path).then(|| {
        path.components()
            .filter_map(|component| match component {
                Component::Normal(part) => Some(part.to_string_lossy()),
                _ => None,
            })
            .collect::<Vec<_>>()
            .join("/")
    })
}

fn current_attempt(metadata: &JobMetadata) -> Option<&AttemptRecord> {
    metadata
        .attempt_history
        .last()
        .filter(|attempt| attempt.attempt == metadata.current_attempt)
}

fn current_attempt_mut(metadata: &mut JobMetadata) -> Option<&mut AttemptRecord> {
    metadata
        .attempt_history
        .last_mut()
        .filter(|attempt| attempt.attempt == metadata.current_attempt)
}

fn new_attempt_record(
    task_id: &str,
    execution_fingerprint: &str,
    attempt: u32,
    retry_of: Option<u32>,
    retry_reason: Option<String>,
    started_at_s: u64,
) -> AttemptRecord {
    AttemptRecord {
        attempt,
        attempt_id: make_attempt_id(task_id, execution_fingerprint, attempt),
        retry_of,
        retry_reason,
        started_at_s,
        finished_at_s: None,
        outcome: AttemptOutcome::Queued,
        lease: None,
        artifact: None,
    }
}

fn advance_attempt(task_id: &str, metadata: &mut JobMetadata, now_s: u64, reason: &str) {
    let previous = metadata.current_attempt;
    if let Some(attempt) = current_attempt_mut(metadata) {
        attempt.finished_at_s = Some(now_s);
        if matches!(
            attempt.outcome,
            AttemptOutcome::Queued | AttemptOutcome::InProgress
        ) {
            attempt.outcome = AttemptOutcome::Failed {
                reason: reason.to_string(),
            };
        }
    }
    metadata.current_attempt = previous.saturating_add(1);
    metadata.attempt_history.push(new_attempt_record(
        task_id,
        &metadata.execution_fingerprint,
        metadata.current_attempt,
        Some(previous),
        Some(reason.to_string()),
        now_s,
    ));
}

fn upgrade_lease_tokens(metadata: &mut JobMetadata) {
    for attempt in &mut metadata.attempt_history {
        if let Some(lease) = attempt.lease.as_mut() {
            if lease.lease_token.is_empty() {
                lease.lease_token = make_lease_token(
                    &attempt.attempt_id,
                    &lease.node_id,
                    lease.leased_at_s,
                    lease.expires_at_s,
                );
            }
        }
    }
    if let Some(lease) = metadata.lease.as_mut() {
        if lease.lease_token.is_empty() {
            let attempt_id = metadata
                .attempt_history
                .last()
                .map(|attempt| attempt.attempt_id.as_str())
                .unwrap_or("legacy-attempt");
            lease.lease_token = make_lease_token(
                attempt_id,
                &lease.node_id,
                lease.leased_at_s,
                lease.expires_at_s,
            );
        }
    }
}

fn legacy_attempt_record(
    job: &RenderJob,
    metadata: &JobMetadata,
    imported_v1: bool,
) -> AttemptRecord {
    let (outcome, finished_at_s) = match job.state {
        State::InQueue => (AttemptOutcome::Queued, None),
        State::InProgress => (AttemptOutcome::InProgress, None),
        State::Completed if imported_v1 => (
            AttemptOutcome::LegacyUnverified,
            Some(metadata.updated_at_s),
        ),
        State::Completed => (AttemptOutcome::Verified, Some(metadata.updated_at_s)),
        State::Failed | State::Cancelled => (
            AttemptOutcome::Failed {
                reason: job.error.clone(),
            },
            Some(metadata.updated_at_s),
        ),
    };
    AttemptRecord {
        attempt: 1,
        attempt_id: make_attempt_id(&job.id, &metadata.execution_fingerprint, 1),
        retry_of: None,
        retry_reason: None,
        started_at_s: metadata.created_at_s,
        finished_at_s,
        outcome,
        lease: metadata.lease.as_ref().map(|lease| AttemptLease {
            node_id: lease.node_id.clone(),
            leased_at_s: lease.leased_at_s,
            expires_at_s: lease.expires_at_s,
            lease_token: lease.lease_token.clone(),
        }),
        artifact: metadata.artifact.clone(),
    }
}

fn make_attempt_id(task_id: &str, execution_fingerprint: &str, attempt: u32) -> String {
    hash_serializable(&(
        "desktop-local-attempt-v1",
        task_id,
        execution_fingerprint,
        attempt,
    ))
}

fn make_lease_token(
    attempt_id: &str,
    node_id: &str,
    leased_at_s: u64,
    expires_at_s: u64,
) -> String {
    hash_serializable(&(
        "desktop-local-lease-v1",
        attempt_id,
        node_id,
        leased_at_s,
        expires_at_s,
    ))
}

fn hash_serializable(value: &impl Serialize) -> String {
    let canonical = serde_json::to_vec(value)
        .expect("serializing deterministic desktop runtime input cannot fail");
    format_digest(Sha256::digest(canonical))
}

fn format_digest(digest: impl AsRef<[u8]>) -> String {
    let mut hex = String::with_capacity(64);
    for byte in digest.as_ref() {
        use std::fmt::Write as _;
        write!(&mut hex, "{byte:02x}").expect("writing to String cannot fail");
    }
    format!("sha256:{hex}")
}

fn is_sha256(value: &str) -> bool {
    value.len() == "sha256:".len() + 64
        && value.starts_with("sha256:")
        && value["sha256:".len()..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn project_attempt(attempt: &AttemptRecord, execution_fingerprint: &str) -> MediaLocalAttempt {
    let (state, outcome) = match &attempt.outcome {
        AttemptOutcome::Queued => ("queued", "queued"),
        AttemptOutcome::InProgress => ("in_progress", "in_progress"),
        AttemptOutcome::Verified => ("completed", "verified"),
        AttemptOutcome::Failed { .. } => ("failed", "failed"),
        AttemptOutcome::ArtifactMissing => ("failed", "artifact_missing"),
        AttemptOutcome::ArtifactCorrupt { .. } => ("failed", "artifact_corrupt"),
        AttemptOutcome::RecoveryExhausted { .. } => ("failed", "recovery_exhausted"),
        AttemptOutcome::LegacyUnverified => ("completed", "legacy_unverified"),
    };
    let artifact_verification = match &attempt.outcome {
        AttemptOutcome::Verified => {
            attempt
                .artifact
                .as_ref()
                .map(|artifact| MediaLocalArtifactVerification {
                    verified: true,
                    status: "verified".into(),
                    content_id: Some(artifact.content_id.clone()),
                    sha256: Some(artifact.sha256.clone()),
                    observed_sha256: Some(artifact.sha256.clone()),
                    byte_length: Some(artifact.byte_length),
                    relative_reference: portable_relative_reference(&artifact.relative_path),
                    execution_fingerprint: artifact.execution_fingerprint.clone(),
                    verified_at_s: Some(artifact.verified_at_s),
                })
        }
        AttemptOutcome::ArtifactMissing => Some(MediaLocalArtifactVerification {
            verified: false,
            status: "missing".into(),
            content_id: attempt
                .artifact
                .as_ref()
                .map(|artifact| artifact.content_id.clone()),
            sha256: attempt
                .artifact
                .as_ref()
                .map(|artifact| artifact.sha256.clone()),
            observed_sha256: None,
            byte_length: attempt
                .artifact
                .as_ref()
                .map(|artifact| artifact.byte_length),
            relative_reference: attempt
                .artifact
                .as_ref()
                .and_then(|artifact| portable_relative_reference(&artifact.relative_path)),
            execution_fingerprint: execution_fingerprint.to_string(),
            verified_at_s: None,
        }),
        AttemptOutcome::ArtifactCorrupt {
            expected_sha256,
            actual_sha256,
        } => Some(MediaLocalArtifactVerification {
            verified: false,
            status: "digest_mismatch".into(),
            content_id: None,
            sha256: Some(expected_sha256.clone()),
            observed_sha256: Some(actual_sha256.clone()),
            byte_length: attempt
                .artifact
                .as_ref()
                .map(|artifact| artifact.byte_length),
            relative_reference: attempt
                .artifact
                .as_ref()
                .and_then(|artifact| portable_relative_reference(&artifact.relative_path)),
            execution_fingerprint: execution_fingerprint.to_string(),
            verified_at_s: attempt
                .artifact
                .as_ref()
                .map(|artifact| artifact.verified_at_s),
        }),
        AttemptOutcome::RecoveryExhausted { .. } => Some(MediaLocalArtifactVerification {
            verified: false,
            status: "recovery_exhausted".into(),
            content_id: None,
            sha256: None,
            observed_sha256: None,
            byte_length: None,
            relative_reference: None,
            execution_fingerprint: execution_fingerprint.to_string(),
            verified_at_s: None,
        }),
        AttemptOutcome::LegacyUnverified => Some(MediaLocalArtifactVerification {
            verified: false,
            status: "legacy_unverified".into(),
            content_id: None,
            sha256: None,
            observed_sha256: None,
            byte_length: None,
            relative_reference: None,
            execution_fingerprint: execution_fingerprint.to_string(),
            verified_at_s: None,
        }),
        _ => None,
    };
    MediaLocalAttempt {
        attempt: attempt.attempt,
        attempt_id: attempt.attempt_id.clone(),
        state: state.into(),
        outcome: outcome.into(),
        started_at_s: attempt.started_at_s,
        finished_at_s: attempt.finished_at_s,
        lease: attempt.lease.as_ref().map(|lease| MediaLocalAttemptLease {
            node_id: lease.node_id.clone(),
            leased_at_s: lease.leased_at_s,
            expires_at_s: lease.expires_at_s,
        }),
        artifact_verification,
        retry_parent_attempt: attempt.retry_of,
        retry_reason: attempt.retry_reason.clone(),
    }
}

fn strict_state(raw: &str) -> Result<State, RuntimeError> {
    match raw {
        "IN_QUEUE" => Ok(State::InQueue),
        "IN_PROGRESS" => Ok(State::InProgress),
        "COMPLETED" => Ok(State::Completed),
        "FAILED" => Ok(State::Failed),
        "CANCELLED" => Ok(State::Cancelled),
        other => Err(RuntimeError::InvalidSnapshot(format!(
            "unknown job state {other:?}"
        ))),
    }
}

fn validate_persisted_job(job: &PersistedJob, schema_version: u32) -> Result<(), RuntimeError> {
    if job.id.is_empty() {
        return Err(RuntimeError::InvalidSnapshot("empty task id".into()));
    }
    if !is_sha256(&job.execution_fingerprint) {
        return Err(RuntimeError::InvalidSnapshot(format!(
            "job {} has malformed execution fingerprint",
            job.id
        )));
    }
    if !job.progress.is_finite() || !(0.0..=1.0).contains(&job.progress) {
        return Err(RuntimeError::InvalidSnapshot(format!(
            "job {} has invalid progress {}",
            job.id, job.progress
        )));
    }
    if job.created_at_s > job.updated_at_s {
        return Err(RuntimeError::InvalidSnapshot(format!(
            "job {} was updated before it was created",
            job.id
        )));
    }
    let state = strict_state(&job.state)?;
    match (state, job.lease.as_ref()) {
        (State::InProgress, None) => {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "running job {} has no lease",
                job.id
            )))
        }
        (State::InQueue, Some(_)) => {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "queued job {} unexpectedly has a lease",
                job.id
            )))
        }
        (state, Some(_)) if state.is_terminal() => {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "terminal job {} unexpectedly has a lease",
                job.id
            )))
        }
        _ => {}
    }
    if state == State::Completed && job.progress != 1.0 {
        return Err(RuntimeError::InvalidSnapshot(format!(
            "completed job {} does not have complete progress",
            job.id
        )));
    }
    if let Some(lease) = &job.lease {
        if lease.node_id.is_empty() || lease.leased_at_s >= lease.expires_at_s {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "job {} has an invalid lease",
                job.id
            )));
        }
        if schema_version == SNAPSHOT_SCHEMA_VERSION && !is_sha256(&lease.lease_token) {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "job {} has a malformed current lease token",
                job.id
            )));
        }
    }
    if schema_version == SNAPSHOT_SCHEMA_VERSION
        && job.execution_input.is_none()
        && !job.legacy_without_execution_input
    {
        return Err(RuntimeError::InvalidSnapshot(format!(
            "job {} has no durable execution input",
            job.id
        )));
    }
    if let Some(input) = &job.execution_input {
        let recomputed = input.execution_fingerprint();
        if recomputed != job.execution_fingerprint {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "job {} execution input does not match fingerprint",
                job.id
            )));
        }
        if input.shot.shot_id != job.id {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "job {} execution input has a different shot id",
                job.id
            )));
        }
    }
    if job.legacy_without_execution_input && job.execution_input.is_some() {
        return Err(RuntimeError::InvalidSnapshot(format!(
            "job {} marks a present execution input as legacy-missing",
            job.id
        )));
    }
    if schema_version == SNAPSHOT_SCHEMA_VERSION {
        if job.current_attempt == 0 || job.attempt_history.is_empty() {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "job {} has no attempt lineage",
                job.id
            )));
        }
        let mut previous = 0;
        let mut ids = HashSet::new();
        for attempt in &job.attempt_history {
            if attempt.attempt != previous + 1
                || attempt.attempt_id
                    != make_attempt_id(&job.id, &job.execution_fingerprint, attempt.attempt)
                || !ids.insert(&attempt.attempt_id)
            {
                return Err(RuntimeError::InvalidSnapshot(format!(
                    "job {} has non-deterministic attempt lineage",
                    job.id
                )));
            }
            if attempt.attempt == 1 {
                if attempt.retry_of.is_some() {
                    return Err(RuntimeError::InvalidSnapshot(format!(
                        "job {} first attempt has a retry parent",
                        job.id
                    )));
                }
            } else if attempt.retry_of != Some(attempt.attempt - 1) {
                return Err(RuntimeError::InvalidSnapshot(format!(
                    "job {} attempt {} has an invalid retry parent",
                    job.id, attempt.attempt
                )));
            }
            if let Some(lease) = &attempt.lease {
                if lease.node_id.is_empty()
                    || lease.leased_at_s >= lease.expires_at_s
                    || !is_sha256(&lease.lease_token)
                {
                    return Err(RuntimeError::InvalidSnapshot(format!(
                        "job {} attempt {} has invalid lease history",
                        job.id, attempt.attempt
                    )));
                }
            }
            if let Some(artifact) = &attempt.artifact {
                validate_artifact_record(&job.id, &job.execution_fingerprint, artifact)?;
            }
            previous = attempt.attempt;
        }
        if previous != job.current_attempt {
            return Err(RuntimeError::InvalidSnapshot(format!(
                "job {} current attempt does not match lineage tail",
                job.id
            )));
        }
        let current_history_lease = job
            .attempt_history
            .last()
            .and_then(|attempt| attempt.lease.as_ref());
        match (state, job.lease.as_ref(), current_history_lease) {
            (State::InProgress, Some(current), Some(historical))
                if current.node_id == historical.node_id
                    && current.leased_at_s == historical.leased_at_s
                    && current.expires_at_s == historical.expires_at_s
                    && current.lease_token == historical.lease_token => {}
            (State::InProgress, _, _) => {
                return Err(RuntimeError::InvalidSnapshot(format!(
                    "job {} current lease does not match attempt history",
                    job.id
                )))
            }
            (_, None, _) => {}
            (_, Some(_), _) => unreachable!("terminal/queued lease rejected above"),
        }
        if let Some(artifact) = &job.artifact {
            validate_artifact_record(&job.id, &job.execution_fingerprint, artifact)?;
        }
        if state == State::Completed {
            let artifact = job.artifact.as_ref().ok_or_else(|| {
                RuntimeError::InvalidSnapshot(format!(
                    "completed job {} has no verified artifact",
                    job.id
                ))
            })?;
            if job
                .attempt_history
                .last()
                .and_then(|attempt| attempt.artifact.as_ref())
                != Some(artifact)
            {
                return Err(RuntimeError::InvalidSnapshot(format!(
                    "completed job {} artifact does not match current attempt",
                    job.id
                )));
            }
        }
    }
    Ok(())
}

fn validate_artifact_record(
    task_id: &str,
    execution_fingerprint: &str,
    artifact: &VerifiedArtifact,
) -> Result<(), RuntimeError> {
    if artifact.content_id != artifact.sha256
        || !is_sha256(&artifact.sha256)
        || artifact.execution_fingerprint != execution_fingerprint
        || !is_safe_output_path(&artifact.relative_path)
    {
        return Err(RuntimeError::InvalidSnapshot(format!(
            "job {task_id} has an unsafe or inconsistent artifact record"
        )));
    }
    Ok(())
}

fn project_execution_fingerprint(project: &Project, shot: &Shot) -> String {
    TaskExecutionInput::from_project_shot(project, shot).execution_fingerprint()
}

#[cfg(test)]
mod tests {
    use super::*;
    use rf_testkit::sample_project;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_SEQUENCE: AtomicU64 = AtomicU64::new(0);

    struct TestDirectory(PathBuf);

    impl TestDirectory {
        fn new(label: &str) -> Self {
            let sequence = TEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "rf-runtime-{label}-{}-{sequence}",
                std::process::id()
            ));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }

        fn snapshot(&self) -> PathBuf {
            self.0.join("jobs.json")
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn one_shot_project() -> Project {
        let mut project = sample_project();
        project.shots.truncate(1);
        project
    }

    fn lease_auth(runtime: &Runtime, task_id: &str) -> (String, String, String) {
        let view = runtime
            .local_jobs()
            .into_iter()
            .find(|job| job.task_id == task_id)
            .unwrap();
        (
            view.execution_fingerprint,
            view.attempt_id,
            view.lease_token.expect("job is leased"),
        )
    }

    fn write_artifact(root: &Path, relative: &str, bytes: &[u8]) -> LocalArtifactCompletion {
        let path = root.join(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, bytes).unwrap();
        LocalArtifactCompletion {
            relative_path: PathBuf::from(relative),
            expected_sha256: format_digest(Sha256::digest(bytes)),
        }
    }

    fn complete_verified(
        runtime: &mut Runtime,
        task_id: &str,
        completion: LocalArtifactCompletion,
    ) -> Result<bool, RuntimeError> {
        let (fingerprint, attempt_id, lease_token) = lease_auth(runtime, task_id);
        runtime.complete_job_with_verified_artifact(
            task_id,
            &fingerprint,
            &attempt_id,
            &lease_token,
            completion,
        )
    }

    fn durable_running(label: &str) -> (TestDirectory, Runtime, (String, String, String)) {
        let directory = TestDirectory::new(label);
        let mut runtime = Runtime::open_local(directory.snapshot(), 60, 24_000, 100).unwrap();
        runtime.add_node("gpu-a", 1);
        runtime.submit_project(&one_shot_project(), 500_000);
        let auth = lease_auth(&runtime, "sc1-s1");
        (directory, runtime, auth)
    }

    #[test]
    fn submits_project_when_wallet_covers() {
        let mut rt = Runtime::new(60, 24_000);
        rt.add_node("gpu-a", 2);
        let project = sample_project(); // 2 shots, estimate 100_000
        let outcome = rt.submit_project(&project, 500_000);
        assert_eq!(outcome, SubmitOutcome::Scheduled { leased: 2 });
        assert_eq!(rt.active_jobs(), 2);
        assert_eq!(rt.job_state("sc1-s1"), Some(State::InProgress));
        let generation = rt.generation_detail("sc1-s1").unwrap();
        assert_eq!(generation.status, "in_progress");
        assert_eq!(generation.execution.kind, "desktop_local");
        assert!(generation.execution.resumable);
        assert_eq!(generation.settlement_status, "held");
        assert_eq!(generation.settlement_rail, "desktop_local");
        assert_eq!(
            generation.settlement_proof_view().outcome,
            rf_gateway::SettlementProofOutcome::Unsigned
        );
        assert!(generation.settlement_evidence.is_none());
    }

    #[test]
    fn local_completion_uses_the_shared_terminal_generation_contract() {
        let mut rt = Runtime::new(60, 24_000);
        rt.add_node("gpu-a", 2);
        rt.submit_project(&sample_project(), 500_000);
        assert!(rt.complete_job("sc1-s1", vec!["file:///renders/out.mp4".into()]));

        let generation = rt.generation_detail("sc1-s1").unwrap();
        assert_eq!(generation.status, "completed");
        assert!(generation.output_url.is_empty());
        assert_eq!(generation.url, generation.output_url);
        assert_eq!(generation.effective_cost_micros(), 0);
        assert_eq!(generation.settlement_status, "released");
        assert_eq!(generation.settlement_rail, "desktop_local");
        assert_eq!(
            generation.settlement_proof_view().outcome,
            rf_gateway::SettlementProofOutcome::Unsigned
        );
        assert!(generation.is_terminal);
        assert!(!generation.execution.resumable);
        assert!(generation.identity.is_none());
        assert!(generation.settlement_evidence.is_none());
    }

    #[test]
    fn recovered_generation_list_is_stable_and_uses_the_shared_contract() {
        let mut runtime = Runtime::new(60, 24_000);
        runtime.add_node("gpu-a", 2);
        runtime.submit_project(&sample_project(), 500_000);

        let generations = runtime.generation_details();
        let ids: Vec<&str> = generations
            .iter()
            .map(|generation| generation.id.as_str())
            .collect();
        assert_eq!(ids, vec!["sc1-s1", "sc1-s2"]);
        assert!(generations
            .iter()
            .all(|generation| generation.execution.kind == "desktop_local"
                && generation.effective_cost_micros() == 0
                && generation.settlement_evidence.is_none()));
    }

    #[test]
    fn blocks_when_wallet_short() {
        let mut rt = Runtime::new(60, 24_000);
        rt.add_node("gpu-a", 2);
        let project = sample_project(); // estimate 100_000
        assert_eq!(
            rt.submit_project(&project, 10_000),
            SubmitOutcome::Blocked {
                shortfall_micros: 90_000
            }
        );
        assert_eq!(rt.active_jobs(), 0); // nothing scheduled
    }

    #[test]
    fn partial_when_capacity_short() {
        let mut rt = Runtime::new(60, 24_000);
        rt.add_node("gpu-a", 1); // only 1 slot for 2 shots
        let outcome = rt.submit_project(&sample_project(), 500_000);
        assert_eq!(
            outcome,
            SubmitOutcome::Partial {
                leased: 1,
                pending: 1
            }
        );
    }

    #[test]
    fn reclaims_and_requeues_on_lease_expiry() {
        let mut rt = Runtime::new(60, 24_000);
        rt.add_node("gpu-a", 1);
        rt.submit_project(&sample_project(), 500_000); // leases 1 shot @ now=0, expires 60
        rt.tick(120); // past expiry -> reclaimed
        assert_eq!(rt.active_jobs(), 0);
        // The reclaimed shot is back IN_QUEUE, ready to re-schedule.
        assert_eq!(rt.job_state("sc1-s1"), Some(State::InQueue));
    }

    #[test]
    fn warm_model_respects_vram_budget() {
        let mut rt = Runtime::new(60, 8_000);
        assert!(rt.warm_model("wan22-small", 6_000));
        assert!(!rt.warm_model("wan22-huge", 16_000)); // exceeds budget
    }

    #[test]
    fn completing_a_job_frees_the_slot() {
        let mut rt = Runtime::new(60, 24_000);
        rt.add_node("gpu-a", 1); // 1 slot for 2 shots
        let outcome = rt.submit_project(&sample_project(), 500_000);
        assert_eq!(
            outcome,
            SubmitOutcome::Partial {
                leased: 1,
                pending: 1
            }
        );
        assert_eq!(rt.active_jobs(), 1);
        // Node finishes the first shot -> slot frees, envelope terminal.
        assert!(rt.complete_job("sc1-s1", vec!["r2://s1.mp4".into()]));
        assert_eq!(rt.job_state("sc1-s1"), Some(State::Completed));
        assert_eq!(rt.active_jobs(), 0);
        // Re-submit now schedules the previously-pending shot.
        let again = rt.submit_project(&sample_project(), 500_000);
        assert_eq!(again, SubmitOutcome::Scheduled { leased: 1 });
        assert_eq!(rt.job_state("sc1-s2"), Some(State::InProgress));
    }

    #[test]
    fn report_progress_heartbeats_lease_past_expiry() {
        let mut rt = Runtime::new(60, 24_000);
        rt.add_node("gpu-a", 1);
        rt.submit_project(&sample_project(), 500_000); // lease @0 expires 60
        rt.tick(50);
        assert!(rt.report_progress("sc1-s1", 0.5)); // renews -> expires 110
        rt.tick(55); // now=105: past the ORIGINAL expiry (60), before the renewed one (110)
        assert_eq!(rt.active_jobs(), 1); // without the renew this would have reclaimed at 60
        assert_eq!(rt.job_state("sc1-s1"), Some(State::InProgress));
    }

    #[test]
    fn failing_a_job_frees_slot_and_marks_failed() {
        let mut rt = Runtime::new(60, 24_000);
        rt.add_node("gpu-a", 1);
        rt.submit_project(&sample_project(), 500_000);
        assert!(rt.fail_job("sc1-s1", "cuda oom"));
        assert_eq!(rt.job_state("sc1-s1"), Some(State::Failed));
        assert_eq!(rt.active_jobs(), 0);
        assert!(!rt.fail_job("ghost", "x")); // unknown task
    }

    #[test]
    fn completed_job_is_not_requeued_on_tick() {
        let mut rt = Runtime::new(60, 24_000);
        rt.add_node("gpu-a", 1);
        rt.submit_project(&sample_project(), 500_000);
        rt.complete_job("sc1-s1", vec![]); // terminal, lease freed
        rt.tick(120); // well past the old expiry
                      // Must stay Completed — never reset to IN_QUEUE.
        assert_eq!(rt.job_state("sc1-s1"), Some(State::Completed));
    }

    #[test]
    fn completed_job_survives_restart_and_is_never_rescheduled() {
        let directory = TestDirectory::new("completed-restart");
        let path = directory.snapshot();
        let project = one_shot_project();
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            assert_eq!(
                runtime.submit_project(&project, 500_000),
                SubmitOutcome::Scheduled { leased: 1 }
            );
            let completion = write_artifact(
                runtime.artifact_root().unwrap(),
                "outputs/restart-safe.mp4",
                b"verified-video",
            );
            assert!(complete_verified(&mut runtime, "sc1-s1", completion).unwrap());
        }

        let mut reopened = Runtime::open_local(&path, 60, 24_000, 120).unwrap();
        reopened.add_node("gpu-a", 1);
        let detail = reopened.generation_detail("sc1-s1").unwrap();
        assert_eq!(detail.status, "completed");
        assert!(detail.output_url.is_empty());
        assert_eq!(detail.effective_cost_micros(), 0);
        assert!(detail.identity.is_none());
        assert!(detail.settlement_evidence.is_none());
        assert_eq!(
            reopened.submit_project(&project, 500_000),
            SubmitOutcome::Scheduled { leased: 0 }
        );
        assert_eq!(reopened.active_jobs(), 0);
        assert_eq!(reopened.job_state("sc1-s1"), Some(State::Completed));
    }

    #[test]
    fn verified_artifact_survives_restart_and_duplicate_completion_is_idempotent() {
        let directory = TestDirectory::new("verified-artifact");
        let path = directory.snapshot();
        let project = one_shot_project();
        let completion;
        let auth;
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.submit_project(&project, 500_000);
            auth = lease_auth(&runtime, "sc1-s1");
            completion = write_artifact(
                runtime.artifact_root().unwrap(),
                "outputs/sc1-s1/attempt-1.mp4",
                b"exact-render-bytes",
            );
            assert!(runtime
                .complete_job_with_verified_artifact(
                    "sc1-s1",
                    &auth.0,
                    &auth.1,
                    &auth.2,
                    completion.clone(),
                )
                .unwrap());
            assert!(runtime
                .complete_job_with_verified_artifact(
                    "sc1-s1",
                    &auth.0,
                    &auth.1,
                    &auth.2,
                    completion.clone(),
                )
                .unwrap());
        }
        let reopened = Runtime::open_local(&path, 60, 24_000, 120).unwrap();
        let artifact = reopened.verified_artifact("sc1-s1").unwrap();
        assert_eq!(artifact.sha256, completion.expected_sha256);
        assert_eq!(artifact.byte_length, 18);
        assert_eq!(artifact.relative_path, completion.relative_path);
        assert_eq!(reopened.attempt_history("sc1-s1").unwrap().len(), 1);
        let detail = reopened.generation_detail("sc1-s1").unwrap();
        assert!(detail.output_url.is_empty() && detail.url.is_empty());
        assert_eq!(detail.settlement_status, "released");
    }

    #[test]
    fn missing_artifact_creates_exactly_one_retry_then_exhausts_on_second_tamper() {
        let directory = TestDirectory::new("artifact-retry-lineage");
        let path = directory.snapshot();
        let project = one_shot_project();
        let first_path;
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.submit_project(&project, 500_000);
            let completion = write_artifact(
                runtime.artifact_root().unwrap(),
                "outputs/sc1-s1/attempt-1.mp4",
                b"first-render",
            );
            first_path = runtime
                .artifact_root()
                .unwrap()
                .join(&completion.relative_path);
            assert!(complete_verified(&mut runtime, "sc1-s1", completion).unwrap());
        }
        fs::remove_file(&first_path).unwrap();

        let reopened = Runtime::open_local(&path, 60, 24_000, 200).unwrap();
        assert_eq!(reopened.job_state("sc1-s1"), Some(State::InQueue));
        let attempts = reopened.attempt_history("sc1-s1").unwrap();
        assert_eq!(attempts.len(), 2);
        assert_eq!(attempts[1].retry_of, Some(1));
        assert_eq!(
            attempts[1].retry_reason.as_deref(),
            Some("artifact_missing")
        );
        assert!(attempts[0].artifact.is_some());
        let projected = reopened.generation_detail("sc1-s1").unwrap();
        let verification = projected.execution.local.unwrap().attempts[0]
            .artifact_verification
            .clone()
            .unwrap();
        assert_eq!(verification.status, "missing");
        assert_eq!(
            verification.relative_reference.as_deref(),
            Some("outputs/sc1-s1/attempt-1.mp4")
        );
        drop(reopened);

        let mut reopened = Runtime::open_local(&path, 60, 24_000, 210).unwrap();
        assert_eq!(reopened.attempt_history("sc1-s1").unwrap().len(), 2);
        reopened.add_node("gpu-a", 1);
        assert_eq!(
            reopened.try_schedule_queued_jobs().unwrap(),
            SubmitOutcome::Scheduled { leased: 1 }
        );
        let completion = write_artifact(
            reopened.artifact_root().unwrap(),
            "outputs/sc1-s1/attempt-2.mp4",
            b"second-render",
        );
        let second_path = reopened
            .artifact_root()
            .unwrap()
            .join(&completion.relative_path);
        assert!(complete_verified(&mut reopened, "sc1-s1", completion).unwrap());
        fs::write(&second_path, b"tampered-render").unwrap();
        drop(reopened);

        let exhausted = Runtime::open_local(&path, 60, 24_000, 300).unwrap();
        assert_eq!(exhausted.job_state("sc1-s1"), Some(State::Failed));
        assert_eq!(exhausted.attempt_history("sc1-s1").unwrap().len(), 2);
        assert!(matches!(
            exhausted.attempt_history("sc1-s1").unwrap()[1].outcome,
            AttemptOutcome::RecoveryExhausted { .. }
        ));
        drop(exhausted);
        let reopened_again = Runtime::open_local(&path, 60, 24_000, 400).unwrap();
        assert_eq!(reopened_again.job_state("sc1-s1"), Some(State::Failed));
        assert_eq!(reopened_again.attempt_history("sc1-s1").unwrap().len(), 2);
    }

    #[test]
    fn stale_attempt_and_lease_callbacks_cannot_mutate_retry() {
        let directory = TestDirectory::new("stale-attempt");
        let path = directory.snapshot();
        let project = one_shot_project();
        let stale_auth;
        let first_path;
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.submit_project(&project, 500_000);
            stale_auth = lease_auth(&runtime, "sc1-s1");
            let completion = write_artifact(
                runtime.artifact_root().unwrap(),
                "outputs/sc1-s1/attempt-1.mp4",
                b"first",
            );
            first_path = runtime
                .artifact_root()
                .unwrap()
                .join(&completion.relative_path);
            assert!(complete_verified(&mut runtime, "sc1-s1", completion).unwrap());
        }
        fs::remove_file(first_path).unwrap();
        let mut runtime = Runtime::open_local(&path, 60, 24_000, 200).unwrap();
        runtime.add_node("gpu-a", 1);
        runtime.try_schedule_queued_jobs().unwrap();
        let current_auth = lease_auth(&runtime, "sc1-s1");
        assert_ne!(stale_auth.1, current_auth.1);
        assert!(
            !runtime
                .report_progress_for_attempt(
                    "sc1-s1",
                    &stale_auth.0,
                    &stale_auth.1,
                    &stale_auth.2,
                    0.9,
                )
                .unwrap()
        );
        assert!(!runtime
            .fail_job_for_attempt(
                "sc1-s1",
                &stale_auth.0,
                &stale_auth.1,
                &stale_auth.2,
                "late failure",
            )
            .unwrap());
        let completion = write_artifact(
            runtime.artifact_root().unwrap(),
            "outputs/sc1-s1/attempt-2.mp4",
            b"second",
        );
        assert!(!runtime
            .complete_job_with_verified_artifact(
                "sc1-s1",
                &stale_auth.0,
                &stale_auth.1,
                &stale_auth.2,
                completion,
            )
            .unwrap());
        assert_eq!(runtime.job_state("sc1-s1"), Some(State::InProgress));
    }

    #[test]
    fn absolute_clock_advance_is_monotonic_and_expires_a_lease_once() {
        let directory = TestDirectory::new("absolute-clock");
        let mut runtime = Runtime::open_local(directory.snapshot(), 60, 24_000, 100).unwrap();
        runtime.add_node("gpu-a", 1);
        runtime.submit_project(&one_shot_project(), 500_000);
        assert_eq!(runtime.now_s(), 100);
        runtime.try_advance_to(160).unwrap();
        assert_eq!(runtime.now_s(), 160);
        assert_eq!(runtime.job_state("sc1-s1"), Some(State::InQueue));
        assert_eq!(runtime.attempt_history("sc1-s1").unwrap().len(), 2);
        runtime.try_advance_to(160).unwrap();
        assert_eq!(runtime.attempt_history("sc1-s1").unwrap().len(), 2);
        assert!(matches!(
            runtime.try_advance_to(159),
            Err(RuntimeError::ClockRollback {
                current_s: 160,
                requested_s: 159
            })
        ));
    }

    #[test]
    fn restored_execution_input_is_bound_to_fingerprint() {
        let directory = TestDirectory::new("input-binding");
        let path = directory.snapshot();
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.submit_project(&one_shot_project(), 500_000);
            let input = runtime.task_execution_input("sc1-s1").unwrap();
            assert_eq!(
                input.execution_fingerprint(),
                runtime.execution_fingerprint("sc1-s1").unwrap()
            );
        }
        let mut snapshot: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        snapshot["jobs"][0]["execution_input"]["project_id"] =
            serde_json::Value::String("tampered-project".into());
        fs::write(&path, serde_json::to_vec_pretty(&snapshot).unwrap()).unwrap();
        assert!(matches!(
            Runtime::open_local(&path, 60, 24_000, 110),
            Err(RuntimeError::InvalidSnapshot(message))
                if message.contains("does not match fingerprint")
        ));
    }

    #[test]
    fn pre_token_v2_snapshot_requeues_once_and_upgrades_lineage() {
        let directory = TestDirectory::new("pre-token-v2");
        let path = directory.snapshot();
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.submit_project(&one_shot_project(), 500_000);
        }
        let mut snapshot: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        snapshot["schema_version"] = serde_json::Value::from(2);
        snapshot["jobs"][0]["lease"]
            .as_object_mut()
            .unwrap()
            .remove("lease_token");
        snapshot["jobs"][0]["attempt_history"][0]["lease"]
            .as_object_mut()
            .unwrap()
            .remove("lease_token");
        fs::write(&path, serde_json::to_vec_pretty(&snapshot).unwrap()).unwrap();

        let reopened = Runtime::open_local(&path, 60, 24_000, 120).unwrap();
        assert_eq!(reopened.job_state("sc1-s1"), Some(State::InQueue));
        let attempts = reopened.attempt_history("sc1-s1").unwrap();
        assert_eq!(attempts.len(), 2);
        assert!(is_sha256(&attempts[0].lease.as_ref().unwrap().lease_token));
        assert_eq!(
            attempts[1].retry_reason.as_deref(),
            Some("migration_missing_lease_token")
        );
        let upgraded: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(upgraded["schema_version"], SNAPSHOT_SCHEMA_VERSION);
    }

    #[test]
    fn v1_completed_snapshot_remains_inspectable_but_unverified_across_reopens() {
        let directory = TestDirectory::new("legacy-v1-completed");
        let path = directory.snapshot();
        let legacy = serde_json::json!({
            "schema_version": 1,
            "saved_at_s": 90,
            "jobs": [{
                "id": "legacy-task",
                "state": "COMPLETED",
                "progress": 1.0,
                "output_refs": ["file:///private/legacy.mp4"],
                "error": "",
                "execution_fingerprint": format!("sha256:{}", "a".repeat(64)),
                "created_at_s": 10,
                "updated_at_s": 80,
                "lease": null
            }]
        });
        fs::write(&path, serde_json::to_vec_pretty(&legacy).unwrap()).unwrap();
        let reopened = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
        assert_eq!(reopened.job_state("legacy-task"), Some(State::InQueue));
        let attempts = reopened.attempt_history("legacy-task").unwrap();
        assert_eq!(attempts.len(), 2);
        assert!(matches!(
            attempts[0].outcome,
            AttemptOutcome::LegacyUnverified
        ));
        assert!(reopened.verified_artifact("legacy-task").is_none());
        drop(reopened);
        let reopened_again = Runtime::open_local(&path, 60, 24_000, 110).unwrap();
        assert_eq!(
            reopened_again.job_state("legacy-task"),
            Some(State::InQueue)
        );
        assert_eq!(
            reopened_again.attempt_history("legacy-task").unwrap().len(),
            2
        );
        assert!(reopened_again.task_execution_input("legacy-task").is_none());
    }

    #[test]
    fn mismatched_current_and_historical_lease_is_rejected() {
        let directory = TestDirectory::new("lease-mismatch");
        let path = directory.snapshot();
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.submit_project(&one_shot_project(), 500_000);
        }
        let mut snapshot: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        snapshot["jobs"][0]["attempt_history"][0]["lease"]["node_id"] =
            serde_json::Value::String("gpu-tampered".into());
        fs::write(&path, serde_json::to_vec_pretty(&snapshot).unwrap()).unwrap();
        assert!(matches!(
            Runtime::open_local(&path, 60, 24_000, 110),
            Err(RuntimeError::InvalidSnapshot(message))
                if message.contains("does not match attempt history")
        ));
    }

    #[test]
    fn completion_rejects_unconfined_non_output_and_empty_artifacts() {
        let directory = TestDirectory::new("artifact-confinement");
        let path = directory.snapshot();
        let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
        runtime.add_node("gpu-a", 1);
        runtime.submit_project(&one_shot_project(), 500_000);
        let (fingerprint, attempt_id, lease_token) = lease_auth(&runtime, "sc1-s1");
        let digest = format_digest(Sha256::digest(b"bytes"));
        for relative_path in ["", "../escape.mp4", "inputs/source.mp4", "/absolute.mp4"] {
            assert!(matches!(
                runtime.complete_job_with_verified_artifact(
                    "sc1-s1",
                    &fingerprint,
                    &attempt_id,
                    &lease_token,
                    LocalArtifactCompletion {
                        relative_path: PathBuf::from(relative_path),
                        expected_sha256: digest.clone(),
                    },
                ),
                Err(RuntimeError::ArtifactVerification(_))
            ));
        }
        assert_eq!(runtime.job_state("sc1-s1"), Some(State::InProgress));
    }

    #[test]
    fn missing_empty_nonregular_and_symlink_artifacts_fail_with_exact_lineage() {
        let digest = format_digest(Sha256::digest(b"bytes"));
        let (_directory, mut runtime, auth) = durable_running("missing-output");
        assert!(runtime
            .complete_job_with_verified_artifact(
                "sc1-s1",
                &auth.0,
                &auth.1,
                &auth.2,
                LocalArtifactCompletion {
                    relative_path: PathBuf::from("outputs/missing.mp4"),
                    expected_sha256: digest.clone(),
                },
            )
            .is_err());
        assert!(matches!(
            runtime.attempt_history("sc1-s1").unwrap()[0].outcome,
            AttemptOutcome::ArtifactMissing
        ));

        let (_directory, mut runtime, auth) = durable_running("empty-output");
        let root = runtime.artifact_root().unwrap().to_path_buf();
        fs::create_dir_all(root.join("outputs")).unwrap();
        fs::write(root.join("outputs/empty.mp4"), b"").unwrap();
        assert!(runtime
            .complete_job_with_verified_artifact(
                "sc1-s1",
                &auth.0,
                &auth.1,
                &auth.2,
                LocalArtifactCompletion {
                    relative_path: PathBuf::from("outputs/empty.mp4"),
                    expected_sha256: format_digest(Sha256::digest(b"")),
                },
            )
            .is_err());
        assert!(matches!(
            runtime.attempt_history("sc1-s1").unwrap()[0].outcome,
            AttemptOutcome::ArtifactCorrupt { .. }
        ));

        let (_directory, mut runtime, auth) = durable_running("directory-output");
        let root = runtime.artifact_root().unwrap().to_path_buf();
        fs::create_dir_all(root.join("outputs/directory.mp4")).unwrap();
        assert!(runtime
            .complete_job_with_verified_artifact(
                "sc1-s1",
                &auth.0,
                &auth.1,
                &auth.2,
                LocalArtifactCompletion {
                    relative_path: PathBuf::from("outputs/directory.mp4"),
                    expected_sha256: digest.clone(),
                },
            )
            .is_err());
        assert!(matches!(
            runtime.attempt_history("sc1-s1").unwrap()[0].outcome,
            AttemptOutcome::ArtifactCorrupt { .. }
        ));

        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;
            let (directory, mut runtime, auth) = durable_running("symlink-output");
            let root = runtime.artifact_root().unwrap().to_path_buf();
            fs::create_dir_all(root.join("outputs")).unwrap();
            fs::write(directory.path().join("outside.mp4"), b"bytes").unwrap();
            symlink(
                directory.path().join("outside.mp4"),
                root.join("outputs/link.mp4"),
            )
            .unwrap();
            assert!(runtime
                .complete_job_with_verified_artifact(
                    "sc1-s1",
                    &auth.0,
                    &auth.1,
                    &auth.2,
                    LocalArtifactCompletion {
                        relative_path: PathBuf::from("outputs/link.mp4"),
                        expected_sha256: digest,
                    },
                )
                .is_err());
            assert!(matches!(
                runtime.attempt_history("sc1-s1").unwrap()[0].outcome,
                AttemptOutcome::ArtifactCorrupt { .. }
            ));
        }
    }

    #[test]
    fn digest_mismatch_fails_closed_and_persists_observed_bytes() {
        let directory = TestDirectory::new("digest-mismatch");
        let path = directory.snapshot();
        let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
        runtime.add_node("gpu-a", 1);
        runtime.submit_project(&one_shot_project(), 500_000);
        let (fingerprint, attempt_id, lease_token) = lease_auth(&runtime, "sc1-s1");
        let completion = write_artifact(
            runtime.artifact_root().unwrap(),
            "outputs/sc1-s1/bad.mp4",
            b"observed",
        );
        let expected = format_digest(Sha256::digest(b"expected"));
        assert!(runtime
            .complete_job_with_verified_artifact(
                "sc1-s1",
                &fingerprint,
                &attempt_id,
                &lease_token,
                LocalArtifactCompletion {
                    expected_sha256: expected.clone(),
                    ..completion.clone()
                },
            )
            .is_err());
        assert_eq!(runtime.job_state("sc1-s1"), Some(State::Failed));
        let attempt = &runtime.attempt_history("sc1-s1").unwrap()[0];
        assert!(matches!(
            &attempt.outcome,
            AttemptOutcome::ArtifactCorrupt { expected_sha256, actual_sha256 }
                if expected_sha256 == &expected && actual_sha256 == &completion.expected_sha256
        ));
        assert_eq!(attempt.artifact.as_ref().unwrap().byte_length, 8);
        assert!(runtime.verified_artifact("sc1-s1").is_none());
    }

    #[test]
    fn restart_preserves_live_lease_then_requeues_only_after_expiry() {
        let directory = TestDirectory::new("lease-restart");
        let path = directory.snapshot();
        let project = one_shot_project();
        let fingerprint;
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.submit_project(&project, 500_000);
            fingerprint = runtime.execution_fingerprint("sc1-s1").unwrap().to_string();
        }

        let mut reopened = Runtime::open_local(&path, 60, 24_000, 120).unwrap();
        reopened.add_node("gpu-a", 1);
        assert_eq!(reopened.active_jobs(), 1);
        assert_eq!(reopened.job_state("sc1-s1"), Some(State::InProgress));
        // A live recovered lease is not handed to another node.
        assert_eq!(
            reopened.submit_project(&project, 500_000),
            SubmitOutcome::Scheduled { leased: 0 }
        );
        assert_eq!(reopened.active_jobs(), 1);

        reopened.try_tick(41).unwrap(); // now=161, persisted expiry was 160
        assert_eq!(reopened.job_state("sc1-s1"), Some(State::InQueue));
        assert_eq!(reopened.active_jobs(), 0);
        assert_eq!(
            reopened.submit_project(&project, 500_000),
            SubmitOutcome::Scheduled { leased: 1 }
        );
        assert_eq!(reopened.job_state("sc1-s1"), Some(State::InProgress));
        assert_eq!(
            reopened.execution_fingerprint("sc1-s1"),
            Some(fingerprint.as_str())
        );
    }

    #[test]
    fn restart_restores_exact_node_occupancy_before_scheduling() {
        let directory = TestDirectory::new("exact-node-restart");
        let path = directory.snapshot();
        let project = sample_project(); // two shots
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            assert_eq!(
                runtime.submit_project(&project, 500_000),
                SubmitOutcome::Partial {
                    leased: 1,
                    pending: 1
                }
            );
            assert_eq!(runtime.lease_node("sc1-s1"), Some("gpu-a"));
        }

        let mut reopened = Runtime::open_local(&path, 60, 24_000, 120).unwrap();
        // Until the original node is registered, recovered work cannot be
        // represented exactly and all new scheduling fails closed.
        assert!(matches!(
            reopened.try_submit_project(&project, 500_000),
            Err(RuntimeError::LeaseRestore(_))
        ));
        reopened.add_node("gpu-a", 1); // imports sc1-s1 onto gpu-a
        reopened.add_node("gpu-b", 1);
        assert_eq!(
            reopened.submit_project(&project, 500_000),
            SubmitOutcome::Scheduled { leased: 1 }
        );
        assert_eq!(reopened.lease_node("sc1-s1"), Some("gpu-a"));
        assert_eq!(reopened.lease_node("sc1-s2"), Some("gpu-b"));
    }

    #[test]
    fn failed_node_registration_is_retryable_without_duplicate_capacity() {
        let directory = TestDirectory::new("node-registration-retry");
        let path = directory.snapshot();
        let project = one_shot_project();
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            assert_eq!(
                runtime.submit_project(&project, 500_000),
                SubmitOutcome::Scheduled { leased: 1 }
            );
        }

        let mut reopened = Runtime::open_local(&path, 60, 24_000, 120).unwrap();
        assert!(matches!(
            reopened.try_add_node("gpu-a", 0),
            Err(RuntimeError::LeaseRestore(_))
        ));
        reopened.try_add_node("gpu-a", 1).unwrap();
        assert_eq!(reopened.active_jobs(), 1);
        assert_eq!(reopened.lease_node("sc1-s1"), Some("gpu-a"));
        assert_eq!(
            reopened.submit_project(&project, 500_000),
            SubmitOutcome::Scheduled { leased: 0 }
        );
    }

    #[test]
    fn recovered_lease_heartbeat_is_durable_across_another_restart() {
        let directory = TestDirectory::new("heartbeat-restart");
        let path = directory.snapshot();
        let project = one_shot_project();
        let fingerprint;
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.submit_project(&project, 500_000);
            fingerprint = runtime.execution_fingerprint("sc1-s1").unwrap().to_string();
        }
        {
            let mut reopened = Runtime::open_local(&path, 60, 24_000, 140).unwrap();
            reopened.add_node("gpu-a", 1);
            let (_, attempt_id, lease_token) = lease_auth(&reopened, "sc1-s1");
            assert!(
                reopened
                    .report_progress_for_attempt(
                        "sc1-s1",
                        &fingerprint,
                        &attempt_id,
                        &lease_token,
                        0.7,
                    )
                    .unwrap()
            ); // durable expiry moves from 160 to 200
        }
        let reopened_again = Runtime::open_local(&path, 60, 24_000, 180).unwrap();
        assert_eq!(reopened_again.active_jobs(), 1);
        assert_eq!(reopened_again.job_state("sc1-s1"), Some(State::InProgress));
    }

    #[test]
    fn failure_reason_and_fingerprint_survive_restart() {
        let directory = TestDirectory::new("failed-restart");
        let path = directory.snapshot();
        let project = one_shot_project();
        let fingerprint;
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 10).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.submit_project(&project, 500_000);
            fingerprint = runtime.execution_fingerprint("sc1-s1").unwrap().to_string();
            let (_, attempt_id, lease_token) = lease_auth(&runtime, "sc1-s1");
            assert!(runtime
                .fail_job_for_attempt(
                    "sc1-s1",
                    &fingerprint,
                    &attempt_id,
                    &lease_token,
                    "cuda device disappeared",
                )
                .unwrap());
        }

        let reopened = Runtime::open_local(&path, 60, 24_000, 999).unwrap();
        let detail = reopened.generation_detail("sc1-s1").unwrap();
        assert_eq!(detail.status, "failed");
        assert_eq!(detail.error, "cuda device disappeared");
        assert_eq!(
            reopened.execution_fingerprint("sc1-s1"),
            Some(fingerprint.as_str())
        );
        assert_eq!(reopened.active_jobs(), 0);
    }

    #[test]
    fn changed_execution_inputs_for_same_task_fail_closed() {
        let directory = TestDirectory::new("fingerprint-conflict");
        let path = directory.snapshot();
        let project = one_shot_project();
        let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
        runtime.add_node("gpu-a", 1);
        runtime.submit_project(&project, 500_000);
        let persisted = runtime.execution_fingerprint("sc1-s1").unwrap().to_string();

        let mut changed = project.clone();
        changed.shots[0].prompt = "a materially different render".into();
        let error = runtime.try_submit_project(&changed, 500_000).unwrap_err();
        assert!(
            matches!(
                &error,
                RuntimeError::ExecutionFingerprintConflict { ref task_id, .. }
                    if task_id == "sc1-s1"
            ),
            "unexpected error: {error:?}"
        );
        assert_eq!(
            runtime.execution_fingerprint("sc1-s1"),
            Some(persisted.as_str())
        );
        assert_eq!(runtime.active_jobs(), 1);

        let callback_error = runtime
            .complete_job_with_fingerprint(
                "sc1-s1",
                "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
                vec![],
            )
            .unwrap_err();
        assert!(matches!(
            callback_error,
            RuntimeError::ExecutionFingerprintConflict { .. }
        ));
        assert_eq!(runtime.job_state("sc1-s1"), Some(State::InProgress));
    }

    #[test]
    fn timeline_survives_restart_and_is_bound_to_the_execution_fingerprint() {
        let directory = TestDirectory::new("timeline-fingerprint");
        let path = directory.snapshot();
        let mut project = one_shot_project();
        project.timeline = Some(TimelineExport {
            segments: vec![rf_project::Segment {
                source_in_ms: 125,
                source_out_ms: 1_625,
                speed_milli: 1_250,
                caption: "durable caption".into(),
                effect_kernel: None,
            }],
            overlays: vec![],
        });
        let fingerprint;
        {
            let mut runtime = Runtime::open_local(&path, 60, 24_000, 100).unwrap();
            runtime.add_node("gpu-a", 1);
            runtime.try_submit_project(&project, 500_000).unwrap();
            fingerprint = runtime.execution_fingerprint("sc1-s1").unwrap().to_string();
        }

        let mut reopened = Runtime::open_local(&path, 60, 24_000, 101).unwrap();
        reopened.add_node("gpu-a", 1);
        assert_eq!(
            reopened
                .task_execution_input("sc1-s1")
                .and_then(|input| input.timeline),
            project.timeline.clone()
        );
        assert_eq!(
            reopened.execution_fingerprint("sc1-s1"),
            Some(fingerprint.as_str())
        );

        let mut changed = project.clone();
        changed.timeline.as_mut().unwrap().segments[0].speed_milli = 1_251;
        let error = reopened.try_submit_project(&changed, 500_000).unwrap_err();
        assert!(
            matches!(
                &error,
                RuntimeError::ExecutionFingerprintConflict { task_id, .. }
                    if task_id == "sc1-s1"
            ),
            "unexpected error: {error:?}"
        );
        assert_eq!(
            reopened.execution_fingerprint("sc1-s1"),
            Some(fingerprint.as_str())
        );
    }

    #[test]
    fn late_or_conflicting_terminal_callbacks_cannot_rewrite_a_terminal_job() {
        let mut runtime = Runtime::new(60, 24_000);
        runtime.add_node("gpu-a", 1);
        runtime.submit_project(&one_shot_project(), 500_000);
        assert!(runtime.complete_job("sc1-s1", vec!["file:///first.mp4".into()]));
        assert!(!runtime.fail_job("sc1-s1", "late worker failure"));
        assert!(!runtime.complete_job("sc1-s1", vec!["file:///conflict.mp4".into()]));
        assert!(runtime.complete_job("sc1-s1", vec!["file:///first.mp4".into()]));
        let detail = runtime.generation_detail("sc1-s1").unwrap();
        assert_eq!(detail.status, "completed");
        assert!(detail.output_url.is_empty());
        assert!(detail.error.is_empty());
    }

    #[test]
    fn corrupt_and_impossible_snapshots_are_rejected() {
        let corrupt_directory = TestDirectory::new("corrupt-json");
        fs::write(corrupt_directory.snapshot(), b"{not-json").unwrap();
        assert!(matches!(
            Runtime::open_local(corrupt_directory.snapshot(), 60, 24_000, 10),
            Err(RuntimeError::Storage(StorageError::Corrupt(_)))
        ));

        let impossible_directory = TestDirectory::new("terminal-lease");
        let storage = LocalAtomicJobStorage::new(impossible_directory.snapshot());
        let impossible = serde_json::json!({
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "saved_at_s": 10,
            "jobs": [{
                "id": "done",
                "state": "COMPLETED",
                "progress": 1.0,
                "output_refs": ["file:///done.mp4"],
                "error": "",
                "execution_fingerprint": format!("sha256:{}", "a".repeat(64)),
                "created_at_s": 1,
                "updated_at_s": 9,
                "lease": { "node_id": "gpu-a", "leased_at_s": 2, "expires_at_s": 20 }
            }]
        });
        storage
            .replace(&serde_json::to_vec(&impossible).unwrap())
            .unwrap();
        assert!(matches!(
            Runtime::open_local(impossible_directory.snapshot(), 60, 24_000, 10),
            Err(RuntimeError::InvalidSnapshot(message)) if message.contains("terminal job")
        ));
    }

    #[test]
    fn local_store_replaces_atomically_without_leaving_temp_files() {
        let directory = TestDirectory::new("atomic-replace");
        let storage = LocalAtomicJobStorage::new(directory.snapshot());
        storage.replace(b"first").unwrap();
        storage.replace(b"second").unwrap();
        assert_eq!(storage.load().unwrap(), Some(b"second".to_vec()));
        let entries: Vec<_> = fs::read_dir(directory.path())
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        assert_eq!(entries, vec![std::ffi::OsString::from("jobs.json")]);
    }

    struct RejectingStorage;

    impl JobStorage for RejectingStorage {
        fn load(&self) -> Result<Option<Vec<u8>>, StorageError> {
            Ok(None)
        }

        fn replace(&self, _snapshot: &[u8]) -> Result<(), StorageError> {
            Err(StorageError::Io("simulated disk failure".into()))
        }
    }

    #[test]
    fn storage_failure_never_starts_unrecorded_work() {
        let mut runtime = Runtime::new(60, 24_000);
        runtime.storage = Some(Box::new(RejectingStorage));
        runtime.add_node("gpu-a", 1);
        let outcome = runtime.submit_project(&one_shot_project(), 500_000);
        assert!(matches!(outcome, SubmitOutcome::Rejected { .. }));
        assert_eq!(runtime.active_jobs(), 0);
        assert_eq!(runtime.job_state("sc1-s1"), None);
    }

    #[test]
    fn plan_clipfarm_dedupes_across_batches() {
        let mut rt = Runtime::new(60, 24_000);
        let matrix = FanoutMatrix {
            bodies: vec!["b1".into(), "b2".into()],
            hooks: vec!["h1".into()],
            templates: vec!["t1".into()],
            aspects: vec!["9:16".into()],
            accounts: vec!["a1".into()],
        };
        let first = rt.plan_clipfarm(&matrix, 0, 0);
        assert_eq!(first.len(), 2);
        // Same matrix again -> all deduped against this session's seen set.
        let second = rt.plan_clipfarm(&matrix, 0, 0);
        assert!(second.is_empty());
    }

    #[test]
    fn plan_clipfarm_applies_pacing_and_cap() {
        let mut rt = Runtime::new(60, 24_000);
        let matrix = FanoutMatrix {
            bodies: vec!["b1".into(), "b2".into(), "b3".into(), "b4".into()],
            hooks: vec!["h1".into()],
            templates: vec!["t1".into()],
            aspects: vec!["9:16".into()],
            accounts: vec!["a1".into()],
        };
        // 4 combinations, but cap the batch at 2.
        let batch = rt.plan_clipfarm(&matrix, 0, 2);
        assert_eq!(batch.len(), 2);
    }

    #[test]
    fn render_command_assembles_through_the_facade() {
        use rf_shots::{SegmentSlot, ShotTemplate};
        let known = rf_captions::list_presets().into_iter().next().unwrap();
        let template = ShotTemplate {
            slug: "t".into(),
            genre: "g".into(),
            aspect: "9:16".into(),
            slots: vec![SegmentSlot {
                role: "hook".into(),
                t_start_ms: 0,
                t_end_ms: 3000,
                caption_preset: known,
                transition_out: "cut".into(),
            }],
        };
        let plan = rf_plan::plan_from_template(&template);
        let rt = Runtime::new(60, 24_000);
        let argv = rt.render_command(
            &plan,
            &RenderRequest {
                video_path: "in.mp4",
                narration_path: "nar.wav",
                bgm_path: Some("bgm.mp3"),
                ass_path: "/tmp/c.ass",
                fonts_dir: "/fonts",
                output_path: "out.mp4",
                duck: true,
            },
        );
        // The facade returns the same complete command rf-render-cmd builds.
        assert_eq!(argv.first().unwrap(), "-y");
        assert_eq!(argv.last().unwrap(), "out.mp4");
        assert!(argv
            .iter()
            .any(|a| a.contains("scale=1080:1920") && a.contains("amix")));
    }

    #[test]
    fn render_command_hw_selects_gpu_encoder() {
        use rf_shots::{SegmentSlot, ShotTemplate};
        let template = ShotTemplate {
            slug: "t".into(),
            genre: "g".into(),
            aspect: "9:16".into(),
            slots: vec![SegmentSlot {
                role: "hook".into(),
                t_start_ms: 0,
                t_end_ms: 3000,
                caption_preset: "___nope___".into(),
                transition_out: "cut".into(),
            }],
        };
        let plan = rf_plan::plan_from_template(&template);
        let rt = Runtime::new(60, 24_000);
        let req = RenderRequest {
            video_path: "in.mp4",
            narration_path: "nar.wav",
            bgm_path: None,
            ass_path: "",
            fonts_dir: "/fonts",
            output_path: "out.mp4",
            duck: false,
        };
        // Windows box with NVENC → the facade drives the hardware encoder.
        let caps = Capabilities {
            nvenc: true,
            ..Default::default()
        };
        let argv = rt.render_command_hw(&plan, &req, Platform::Windows, &caps);
        assert!(argv
            .windows(2)
            .any(|w| w[0] == "-c:v" && w[1] == "h264_nvenc"));
        assert!(argv.contains(&"-b:v".to_string()));
        // No GPU → falls back to exactly the software command.
        let sw = rt.render_command(&plan, &req);
        let fallback =
            rt.render_command_hw(&plan, &req, Platform::Windows, &Capabilities::default());
        assert_eq!(sw, fallback);
    }
}
