import type { JobStateValue } from "./job-state.js";

/** Stable stage statuses emitted by the ReelForge worker pipeline. */
export type ReelStageStatus = "pending" | "running" | "complete" | "failed";

/** Canonical reel pipeline order used by every client progress view. */
export const REEL_JOB_STAGES = [
  "script",
  "tts",
  "avatar",
  "captions",
  "compose",
  "upload",
] as const;

export type ReelJobStage = (typeof REEL_JOB_STAGES)[number];

// "captions_only" is the avatar-less path: captions burned over the uploaded
// screen recording with no HeyGen avatar. It requires no paid avatar/voice
// provider, so it is producible with only the core backend.
export type ReelLayout = "pip" | "hook_intro" | "split" | "captions_only";
export type ReelAspect = "9:16";
export type ReelLanguage = "auto" | "tr" | "en";
export type ReelAvatarProvider = "heygen";

export const REEL_LAYOUTS: readonly ReelLayout[] = [
  "captions_only",
  "pip",
  "hook_intro",
  "split",
];

export type ReelCameraMotion =
  | "none"
  | "ken_burns"
  | "push_in"
  | "pull_out"
  | "whip_pan";

export const REEL_CAMERA_MOTIONS: readonly ReelCameraMotion[] = [
  "none",
  "ken_burns",
  "push_in",
  "pull_out",
  "whip_pan",
];

export const MAX_REEL_JOB_VARIANTS = 3;

/**
 * Reviewed client-facing subset of the backend ReelForgeParams dataclass.
 * Provider-only/internal fields stay backend-owned; fields used to create and
 * rerun a reel are shared here so web, mobile, and desktop send one shape.
 */
export interface ReelCreateParams {
  video_subject: string;
  video_script?: string;
  translate_source_script?: string;
  voice_name: string;
  voice_rate?: number;
  avatar_id: string;
  avatar_provider: ReelAvatarProvider;
  caption_style: string;
  layout: ReelLayout;
  aspect: ReelAspect;
  language: ReelLanguage;
  target_duration_s: number;
  platforms: string[];
  youtube_privacy_status?: string;
  screen_recording_key: string;
  /**
   * Curated background-library clip id (GET /templates/backgrounds). When no
   * `screen_recording_key` is supplied the backend materializes this clip
   * into a looping companion track sized to the narration — the footage a
   * `captions_only` reel plays under its captions.
   */
  background_id?: string;
  voiceover_key?: string;
  watermark_key?: string;
  watermark_position?: string;
  watermark_opacity?: number;
  watermark_enabled?: boolean;
}

/** Canonical POST /api/v1/jobs request used by first-party clients. */
export interface ReelJobCreateInput {
  params: ReelCreateParams;
  avatar_id?: string;
  voice_id?: string;
  caption_style?: string;
  music_id?: string;
  webhook_url?: string;
  webhook_secret?: string;
  music_prompt?: string;
  bgm_provider?: string;
  broll_intro_key?: string;
  broll_outro_key?: string;
  voiceover_key?: string;
  variants?: number;
  tos_disclosure?: boolean;
  auto_tighten?: boolean;
  auto_zoom?: boolean;
  camera_motion?: ReelCameraMotion;
  remove_bg?: boolean;
  workspace_id?: string;
}

/**
 * Additive-compatible job snapshot returned by create, list, read, retry, and
 * rerun endpoints. Keys are durable handoff references; *_url fields are the
 * signed presentation URLs clients should render.
 */
export interface ReelJobSnapshot {
  job_id: string;
  kind?: string;
  state: JobStateValue;
  progress: number;
  stages?: Partial<Record<ReelJobStage, ReelStageStatus>>;
  failed_stage?: string;
  error?: string;
  result_url?: string;
  correlation_id?: string;
  retry_eligible?: boolean;
  poster_key?: string;
  poster_url?: string;
  preview_key?: string;
  preview_url?: string;
  cover_key?: string;
  cover_url?: string;
  language?: string;
  hook?: string;
  created_at?: string;
  /** Persisted job params contain an owned screen-recording object key. */
  source_footage_ready?: boolean;
  /** Persisted subject/script data contains the creator's render brief. */
  brief_ready?: boolean;
}

export interface ReelJobCreateResult extends ReelJobSnapshot {
  job_ids?: string[];
  batch_id?: string;
}

export interface ReelBatchJob {
  job_id: string;
  state: JobStateValue;
  progress: number;
  result_url?: string;
  poster_key?: string;
  poster_url?: string;
  preview_key?: string;
  preview_url?: string;
  cover_key?: string;
  cover_url?: string;
}

export interface ReelBatch {
  batch_id?: string;
  jobs: ReelBatchJob[];
}
