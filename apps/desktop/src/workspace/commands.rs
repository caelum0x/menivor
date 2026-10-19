//! Immutable UI-to-worker commands and worker-to-UI updates.

use std::path::PathBuf;

use rf_project::TimelineExport;

use crate::api::{
    ApiFailure, CatalogEntry, Credits, GenerationDetail, MediaIdentityOption, MediaModel, UsageRow,
    WalletReceiveAddress, WalletRecipient, WalletSavedRecipient, WalletSource,
    WalletTransferChallenge, WalletTransferResult,
};
use crate::domain::{BrollDraft, JobKind, JobSnapshot, ReelDraft};
use crate::updater::ReleaseChannel;
use crate::workspace::{EditorSourceAnalysis, LocalRenderRequest, WorkspaceCache};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum UploadTarget {
    ReelRecording,
    BrollReference,
}

// Deliberately not `Debug`: SaveConfiguration can carry an API key while it is
// in transit to the worker and must never become loggable by accident.
#[derive(Clone, Eq, PartialEq)]
pub(crate) enum WorkerCommand {
    LoadConfiguration,
    LoadWorkspace,
    PersistWorkspace(WorkspaceCache),
    SaveConfiguration {
        base_url: String,
        api_key: Option<String>,
        /// Explicit WolfCut location; empty means auto-detect.
        editor_path: String,
        /// When true, route all API calls to the local freegen sidecar; no API
        /// key is required and the sidecar is started automatically.
        use_local_engine: bool,
    },
    ClearCredentials,
    CheckConnection,
    CheckForUpdates {
        channel: ReleaseChannel,
    },
    DownloadAvailableUpdate,
    InstallStagedUpdate,
    RefreshLibrary,
    AnalyzeEditorSource {
        request_id: String,
        path: PathBuf,
    },
    /// Persist, lease and execute a selected local video through ffmpeg.
    SubmitLocalRender(LocalRenderRequest),
    /// Resolve through the private runtime verifier, then open as a local file.
    OpenLocalArtifact {
        task_id: String,
    },
    /// Fetch the media-gateway wallet balance + spend-by-model usage.
    RefreshMediaWallet,
    RefreshWalletSources,
    RefreshWalletSourceBalance {
        source_account_id: String,
    },
    RefreshWalletReceiveAddress {
        source_account_id: String,
    },
    ResolveWalletRecipient {
        handle: String,
    },
    ReviewWalletTransfer {
        source_account_id: String,
        recipient_handle: String,
        saved_recipient_id: Option<String>,
        amount_micros: u64,
        idempotency_key: String,
        submitted: bool,
    },
    SendWalletTransfer {
        source_account_id: String,
        challenge_id: String,
        recipient_handle: String,
        amount_micros: u64,
        idempotency_key: String,
        /// Durable snapshot containing the pending key; must save before POST.
        workspace: WorkspaceCache,
    },
    /// Read a sender-owned transfer after an ambiguous response; never creates one.
    RecoverWalletTransfer {
        transfer_id: String,
    },
    RefreshSavedRecipients {
        source_account_id: String,
    },
    SaveWalletRecipient {
        source_account_id: String,
        recipient_handle: String,
    },
    DeleteWalletRecipient {
        source_account_id: String,
        saved_recipient_id: String,
    },
    /// Fetch the media-gateway model catalog, optionally filtered to one modality
    /// (`image` / `video` / `audio`; `None` = the whole catalog).
    RefreshMediaModels {
        modality: Option<String>,
    },
    /// Synchronous image generation through the media gateway.
    GenerateMediaImage {
        model: String,
        prompt: String,
    },
    /// Submit an async video generation. `image_url` enables image-to-video
    /// models while remaining optional for text-to-video models.
    GenerateMediaVideo {
        model: String,
        prompt: String,
        image_url: String,
        duration: u32,
        identity_passport_id: String,
        identity_version: Option<u32>,
    },
    /// Submit an async music/audio generation (`POST /media/audio`).
    GenerateMediaAudio {
        model: String,
        prompt: String,
        instrumental: bool,
    },
    /// Fetch the next (older) page of the media generation timeline.
    LoadMoreMediaGenerations {
        offset: u64,
    },
    /// Inspect one generation's cost + status by id.
    LookupGeneration {
        id: String,
    },
    ExportGenerationProvenance {
        id: String,
        path: PathBuf,
    },
    Upload {
        target: UploadTarget,
        path: PathBuf,
        content_type: String,
    },
    SubmitReel {
        draft: ReelDraft,
        idempotency_key: String,
    },
    SubmitBroll {
        draft: BrollDraft,
        idempotency_key: String,
    },
    /// Validate and enqueue a non-destructive edit of one completed reel.
    SubmitTimelineExport {
        source_job_id: String,
        timeline: TimelineExport,
        idempotency_key: String,
    },
    /// Delete a finished reel and its stored media.
    DeleteReel {
        job_id: String,
    },
    /// Publish a finished reel through the studio API (launch-gated server-side).
    PublishReel {
        job_id: String,
        idempotency_key: String,
    },
    /// Load the reviewed reel pickers (avatars, voices, caption styles).
    RefreshReelCatalog,
    PollJob {
        id: String,
        kind: JobKind,
    },
    OpenPreview {
        url: String,
    },
    /// Open a finished job in WolfCut, the Menivor editor, through the
    /// `--open-generated-clip` handoff.
    OpenJobInEditor {
        job_id: String,
        kind: JobKind,
        result_url: String,
    },
    /// Launch WolfCut on its start screen (no handoff).
    LaunchEditor,
    /// Stream a finished job's signed result URL to a user-chosen file so the
    /// creator keeps a durable copy after the transient preview URL expires.
    SaveResultToDisk {
        url: String,
        dest: PathBuf,
    },
    Shutdown,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum WorkerUpdate {
    ConfigurationLoaded {
        api_base: String,
        editor_path: String,
        use_local_engine: bool,
    },
    WorkspaceRestored(WorkspaceCache),
    Disconnected,
    ConnectionChecking,
    Connected,
    UpdateChecking {
        channel: ReleaseChannel,
    },
    UpdateAvailable {
        channel: ReleaseChannel,
        version: String,
        notes_url: String,
        size_bytes: u64,
    },
    UpdateCurrent {
        channel: ReleaseChannel,
        version: String,
    },
    UpdateDownloadStarted {
        version: String,
    },
    UpdateStaged {
        version: String,
        artifact: String,
    },
    UpdateInstallerLaunched {
        version: String,
    },
    UpdateFailed {
        operation: String,
        message: String,
    },
    Capabilities {
        mode: String,
        reels: bool,
        broll: bool,
    },
    /// Reviewed reel pickers fetched after a successful connection.
    ReelCatalog {
        avatars: Vec<CatalogEntry>,
        voices: Vec<CatalogEntry>,
        caption_styles: Vec<CatalogEntry>,
    },
    /// A finished reel was published through the studio API.
    ReelPublished {
        job_id: String,
        summary: String,
    },
    ReelDeleted {
        job_id: String,
    },
    ConnectionFailed(ApiFailure),
    Library(Vec<JobSnapshot>),
    /// The media-gateway wallet balance + spend-by-model usage.
    MediaWallet {
        credits: Credits,
        usage: Vec<UsageRow>,
        generations: Vec<GenerationDetail>,
        /// Whether older generations exist beyond the first page.
        generations_has_more: bool,
    },
    /// An older page of the generation timeline, appended after `offset` rows.
    MediaGenerationsPage {
        offset: u64,
        generations: Vec<GenerationDetail>,
        has_more: bool,
    },
    MediaToolchainInspected {
        ready: bool,
        message: String,
    },
    /// Durable desktop-local runtime opened before the worker accepts commands.
    LocalRuntimeRestored {
        generations: Vec<GenerationDetail>,
    },
    /// Local state failed closed; cloud generation remains available.
    LocalRuntimeFailed {
        message: String,
    },
    /// A durable local lifecycle transition. No lease token or host path crosses
    /// this worker-to-UI boundary.
    LocalRuntimeUpdated {
        generations: Vec<GenerationDetail>,
        message: String,
        failed: bool,
    },
    EditorSourceAnalyzed(EditorSourceAnalysis),
    EditorSourceAnalysisFailed {
        request_id: String,
        message: String,
    },
    WalletRecipientResolved(WalletRecipient),
    WalletSources(Vec<WalletSource>),
    WalletSourceBalance {
        source_account_id: String,
        balance: Credits,
    },
    WalletReceiveAddress(WalletReceiveAddress),
    WalletTransferReviewed {
        challenge: WalletTransferChallenge,
        idempotency_key: String,
        submitted: bool,
    },
    WalletSavedRecipients(Vec<WalletSavedRecipient>),
    WalletRecipientSaved(WalletSavedRecipient),
    WalletRecipientDeleted(String),
    WalletTransferComplete(WalletTransferResult),
    /// Definitive 4xx rejection: no transfer happened, so a new review is safe.
    WalletTransferRejected(ApiFailure),
    /// A completed synchronous image generation.
    MediaImageComplete {
        url: String,
        cost_micros: u64,
    },
    /// A media video has been accepted and will be polled by the worker.
    MediaVideoQueued {
        id: String,
        cost_micros: u64,
    },
    MediaVideoProgress {
        id: String,
        status: String,
    },
    MediaVideoComplete {
        id: String,
        url: String,
        cost_micros: u64,
    },
    /// A music/audio job has been accepted and will be polled by the worker.
    MediaAudioQueued {
        id: String,
        cost_micros: u64,
    },
    MediaAudioProgress {
        id: String,
        status: String,
    },
    MediaAudioComplete {
        id: String,
        url: String,
        cost_micros: u64,
    },
    /// The unified media-gateway model catalog.
    MediaModels(Vec<MediaModel>),
    MediaIdentities(Vec<MediaIdentityOption>),
    /// A looked-up per-generation cost/status detail.
    GenerationDetailLoaded(GenerationDetail),
    ProvenanceExported {
        generation_id: String,
        path: PathBuf,
    },
    UploadStarted(UploadTarget),
    UploadComplete {
        target: UploadTarget,
        key: String,
    },
    /// A finished result was streamed to a user-chosen path on disk.
    ResultSaved {
        path: String,
    },
    /// Writing a finished result to disk failed (expired URL, I/O error, …).
    ResultSaveFailed {
        message: String,
    },
    /// WolfCut was launched (on a job, or on its start screen).
    EditorOpened {
        message: String,
    },
    /// WolfCut could not be found or launched, or the job had nothing to edit.
    EditorOpenFailed {
        message: String,
    },
    OperationFailed {
        operation: String,
        failure: ApiFailure,
    },
    Queued {
        id: String,
        kind: JobKind,
        correlation_id: String,
    },
    TimelineExportQueued {
        id: String,
        source_job_id: String,
        output_duration_ms: u64,
        segments: usize,
        overlays: usize,
        correlation_id: String,
    },
    Progress {
        id: String,
        kind: JobKind,
        progress: i32,
        correlation_id: String,
    },
    Complete {
        id: String,
        kind: JobKind,
        result_url: String,
        result_key: String,
        correlation_id: String,
    },
    Failed {
        id: String,
        kind: JobKind,
        message: String,
        retry_eligible: bool,
        correlation_id: String,
    },
}
