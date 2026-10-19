/**
 * Domain types for the ReelForge Desktop renderer — the API-facing subset of the
 * backend v1 contract that the desktop client actually uses (record → upload →
 * create job → poll → show result). Mirrors `web/lib/types.ts`; kept intentionally
 * small since the desktop app drives the pipeline rather than reimplementing it.
 */

// ---------------------------------------------------------------------------
// Job state
// ---------------------------------------------------------------------------

/** Integer job states used by the backend (`app/models/const.py`). */
export const JobState = {
  Failed: -1,
  Complete: 1,
  Processing: 4,
} as const;

export type JobStateValue = number;

/** A job is terminal once it has succeeded or failed; polling stops here. */
export function isTerminalState(state: JobStateValue): boolean {
  return state === JobState.Complete || state === JobState.Failed;
}

export function isFailedState(state: JobStateValue): boolean {
  return state === JobState.Failed;
}

/** Per-stage status map values. */
export type StageStatus = "pending" | "running" | "complete" | "failed";

/** The pipeline stages, in DAG order. */
export const JOB_STAGES = [
  "script",
  "tts",
  "avatar",
  "captions",
  "compose",
  "upload",
] as const;

export type JobStage = (typeof JOB_STAGES)[number];

// ---------------------------------------------------------------------------
// Job
// ---------------------------------------------------------------------------

/** Job status returned by POST /jobs and GET /jobs/{id}. */
export interface Job {
  job_id: string;
  state: JobStateValue;
  progress: number;
  stages?: Partial<Record<JobStage, StageStatus>>;
  failed_stage?: string;
  error?: string;
  result_url?: string;
  poster_key?: string;
  preview_key?: string;
  language?: string;
  hook?: string;
}

/** Result of POST /jobs. */
export interface JobCreateResult {
  job_id: string;
  state: JobStateValue;
  progress: number;
  job_ids?: string[];
  batch_id?: string;
}

// ---------------------------------------------------------------------------
// Reel — the media-facing view of a COMPLETED job (what the Library/result UI
// renders). A structural subset of {@link Job}: only the fields needed to play,
// preview, and label a finished reel.
// ---------------------------------------------------------------------------

/** A finished reel: a completed job whose rendered media is ready to view. */
export interface Reel {
  job_id: string;
  /** Presigned URL of the rendered 9:16 MP4, when available. */
  result_url?: string;
  /** R2 key for the generated poster/thumbnail image. */
  poster_key?: string;
  /** R2 key for a short preview clip. */
  preview_key?: string;
  /** The reel's hook / opening line, when the backend surfaces it. */
  hook?: string;
  /** Source reel language code (e.g. "en", "tr"). */
  language?: string;
}

/**
 * True when a job has finished successfully AND exposes a playable result URL —
 * i.e. it can be shown as a {@link Reel}.
 */
export function isReelReady(job: Job): boolean {
  return job.state === JobState.Complete && Boolean(job.result_url);
}

/** Project a {@link Job} onto its media-facing {@link Reel} subset. */
export function toReel(job: Job): Reel {
  return {
    job_id: job.job_id,
    result_url: job.result_url,
    poster_key: job.poster_key,
    preview_key: job.preview_key,
    hook: job.hook,
    language: job.language,
  };
}

// ---------------------------------------------------------------------------
// ReelForge params (POST /jobs body)
// ---------------------------------------------------------------------------

export type Layout = "pip" | "hook_intro" | "split";
export type Aspect = "9:16";
export type Language = "auto" | "tr" | "en";
export type AvatarProvider = "heygen";

/** The ReelForge-shape params object sent inside JobCreateRequest.params. */
export interface ReelForgeParams {
  video_subject: string;
  video_script?: string;
  voice_name: string;
  avatar_id: string;
  avatar_provider: AvatarProvider;
  caption_style: string;
  layout: Layout;
  aspect: Aspect;
  language: Language;
  target_duration_s: number;
  platforms: string[];
  screen_recording_key: string;
}

/** Request body for POST /jobs. */
export interface JobCreateRequest {
  params: ReelForgeParams;
  avatar_id?: string;
  voice_id?: string;
  variants?: number;
  caption_style?: string;
  music_id?: string;
  webhook_url?: string;
  tos_disclosure?: boolean;
}

// ---------------------------------------------------------------------------
// Uploads / presign
// ---------------------------------------------------------------------------

/** Request body for POST /uploads/presign. */
export interface PresignRequest {
  filename: string;
  content_type: string;
  size: number;
}

/**
 * Response from POST /uploads/presign. `headers` are the signed headers the
 * client MUST echo on the PUT to `upload_url`. `key` is used as
 * `screen_recording_key` when creating a job.
 */
export interface PresignResult {
  upload_url: string;
  get_url: string;
  key: string;
  headers: Record<string, string>;
}
