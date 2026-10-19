/**
 * TypeScript types mirroring the ReelForge backend v1 contract (§5 of
 * docs/reelforge/INTEGRATION_CONTRACT.md). Shared primitives are imported from
 * `@reelforge/api-contract`; feature DTOs remain here while migration proceeds.
 */

import {
  JobState,
  MAX_REEL_JOB_VARIANTS,
  REEL_CAMERA_MOTIONS,
  REEL_JOB_STAGES,
  isFailedJobState,
  isTerminalJobState,
  type ReelAspect,
  type ReelAvatarProvider,
  type ReelBatch,
  type ReelBatchJob,
  type ReelCameraMotion,
  type ReelCreateParams,
  type ReelJobCreateInput,
  type ReelJobCreateResult,
  type ReelJobSnapshot,
  type ReelJobStage,
  type ReelLanguage,
  type ReelLayout,
  type ReelStageStatus,
  type JobStateValue,
} from "@reelforge/api-contract";
import type { PilotCapabilities as ContractPilotCapabilities } from "@reelforge/api-contract";
import type {
  BrollGenerateInput,
  BrollGenerationMode,
  BrollGenerationSnapshot,
  EditorExportRequest as ContractEditorExportRequest,
  PresignUploadInput,
  PresignUploadResult,
} from "@reelforge/api-contract";

export { JobState, type JobStateValue };

/** Exact non-destructive range submitted to POST /jobs/{id}/exports. */
export type EditorExportRequest = ContractEditorExportRequest;

// ---------------------------------------------------------------------------
// Job state (backend integer TASK_STATE_* constants)
// ---------------------------------------------------------------------------

/** A job is terminal once it has succeeded or failed; polling stops here. */
export const TERMINAL_JOB_STATES: readonly JobStateValue[] = [
  JobState.Complete,
  JobState.Failed,
];

export function isTerminalState(state: JobStateValue): boolean {
  return isTerminalJobState(state);
}

export function isFailedState(state: JobStateValue): boolean {
  return isFailedJobState(state);
}

/** Per-stage status map values (REELFORGE_STAGE_* constants). */
export type StageStatus = ReelStageStatus;

/** The pipeline stages, in DAG order. */
export const JOB_STAGES = REEL_JOB_STAGES;

export type JobStage = ReelJobStage;

// ---------------------------------------------------------------------------
// Job
// ---------------------------------------------------------------------------

/**
 * Job status returned by POST /jobs and GET /jobs/{id}.
 * POST /jobs returns only { job_id, state, progress }; GET adds the rest.
 */
export interface Job extends ReelJobSnapshot {
  job_id: string;
  state: JobStateValue;
  progress: number;
  stages?: Partial<Record<JobStage, StageStatus>>;
  failed_stage?: string;
  error?: string;
  result_url?: string;
  /** MN5: media is soft-blocked after a content report (no media URLs). */
  media_blocked?: boolean;
  media_blocked_message?: string;
  /** Request correlation id for matching client/API/worker logs. */
  correlation_id?: string;
  /** Whether the terminal failure can be submitted again. */
  retry_eligible?: boolean;
  /** R2 key for the generated poster/thumbnail image, when available. */
  poster_key?: string;
  /** R2 key for a short preview clip, when available. */
  preview_key?: string;
  /**
   * Source reel language code (e.g. "en", "tr"). Additive: only GET /jobs/{id}
   * populates it. Used to seed the Dub flow (exclude the source language from
   * the target picker). `"auto"` means the language was not pinned.
   */
  language?: string;
  /**
   * R2 key for the creator-generated cover / thumbnail image (Cover Generator).
   * Additive: populated after {@link generateCover} runs. May arrive already
   * presigned to an absolute URL.
   */
  cover_key?: string;
  /**
   * Presigned URL for the generated cover image, when the backend surfaces one
   * on GET /jobs/{id}. Preferred over `poster_key` as the reel thumbnail.
   */
  cover_url?: string;
  /**
   * The reel's hook / opening line, when the backend surfaces it. Additive:
   * used to prefill the Cover Generator's headline input.
   */
  hook?: string;
  /**
   * Creator-chosen display name (PATCH /jobs/{id} `{ title }`). Additive:
   * absent until the reel is renamed; the UI falls back to the hook / id.
   */
  title?: string | null;
  /** True once the reel has been archived (PATCH /jobs/{id} `{ archived }`). */
  archived?: boolean;
  /** ISO-8601 archive timestamp, when the backend surfaces it. */
  archived_at?: string | null;
  /** True when the caller cancelled the job (POST /jobs/{id}/cancel). */
  cancelled?: boolean;
  /** Credits returned to the payer by a cancel, when the backend reports it. */
  refunded_credits?: number;
  /**
   * Live queue position while the job is unfinished (GET /jobs/{id} only).
   * `ahead` is a real count of unfinished jobs created before this one;
   * `eta_s` is measured from recent renders and is `null` when there is not
   * enough history to say (the UI then shows only the position).
   */
  queue?: JobQueueStatus;
}

export interface JobQueueStatus {
  ahead: number;
  eta_s: number | null;
  slots?: number;
}

/**
 * Result of POST /jobs. The backend returns the classic single-job envelope
 * ``{ job_id, state, progress }`` for ``variants === 1`` and additionally
 * carries ``job_ids`` (every created variant; ``job_id`` is the first) when
 * ``variants > 1``. Consumers can branch on the presence of ``job_ids``.
 */
export interface JobCreateResult extends ReelJobCreateResult {
  job_id: string;
  state: JobStateValue;
  progress: number;
  /** Present only for batch (multi-variant) creates; all created job ids. */
  job_ids?: string[];
  /**
   * Batch identifier for multi-variant creates. When present, the created
   * variants can be reviewed together via GET /batches/{batch_id}
   * (see {@link BatchData}). Additive: absent for classic single-job creates.
   */
  batch_id?: string;
}

// ---------------------------------------------------------------------------
// Batch (multi-variant) review — GET /batches/{id}
// ---------------------------------------------------------------------------

/**
 * A single variant within a batch, as returned by GET /batches/{id}. A
 * structural subset of {@link Job} (compatible with the `lib/job-media`
 * helpers and {@link JobStatusBadge}); the batch endpoint returns the fields
 * needed to render the review grid.
 */
export interface BatchJob extends ReelBatchJob {
  job_id: string;
  state: JobStateValue;
  progress: number;
  result_url?: string;
  /** R2 key for the generated poster/thumbnail image, when available. */
  poster_key?: string;
  /** R2 key for a short preview clip, when available. */
  preview_key?: string;
}

/**
 * Response from GET /batches/{id}: every variant job created by a single
 * multi-variant `POST /jobs`, in creation order.
 */
export interface BatchData extends ReelBatch {
  /** The batch identifier, echoed by the backend when present. */
  batch_id?: string;
  /** Every variant job in the batch, in creation order. */
  jobs: BatchJob[];
}

// ---------------------------------------------------------------------------
// ReelForge params (POST /jobs body)
// ---------------------------------------------------------------------------

export type Layout = ReelLayout;
export type Aspect = ReelAspect;
export type Language = ReelLanguage;
export type AvatarProvider = ReelAvatarProvider;

/**
 * The ReelForge-shape params object sent inside JobCreateRequest.params.
 * Mirrors the API-facing subset of the backend ReelForgeParams DTO (§2.8/§5).
 */
export interface ReelForgeParams extends ReelCreateParams {
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
export interface JobCreateRequest extends ReelJobCreateInput {
  params: ReelForgeParams;
  avatar_id?: string;
  voice_id?: string;
  /**
   * BRING YOUR OWN VOICEOVER (BYOV): R2 object key of the creator's OWN uploaded
   * narration audio (from {@link presignAndUpload}). When set, this audio becomes
   * the reel's narration INSTEAD of TTS / a cloned brand voice: the backend
   * transcribes it with faster-whisper to drive the ASS karaoke captions, and the
   * same audio drives the HeyGen avatar lip-sync + duration (preserving the §8
   * single-source-of-truth timing). Mutually exclusive with `voice_id` /
   * `params.voice_name` in practice — send a voiceover OR a TTS/clone voice.
   */
  voiceover_key?: string;
  /**
   * Number of A/B variants to fan out (1..3). The backend clamps to this range;
   * omit or pass 1 for a single job. See `MAX_JOB_VARIANTS`.
   */
  variants?: number;
  /**
   * Top-level caption-style override. Takes precedence over
   * `params.caption_style` (a real ReelForgeParams field) at the controller.
   */
  caption_style?: string;
  /** Background-music track id (from GET /catalog/music). */
  music_id?: string;
  /**
   * AI background music: a text brief the chosen enabled provider turns into a
   * custom royalty-free BGM track (fed to compose as the reel's `music_path`).
   * Mutually exclusive with `music_id` in practice — send one or the other.
   * Respect the provider's `max_prompt_length` (see {@link MusicGenerator}).
   */
  music_prompt?: string;
  /**
   * Which AI-BGM provider generates the `music_prompt` track. Omit or send `""`
   * to auto-select the first enabled provider. Only ids from
   * {@link listMusicGenerators} are accepted (a bad id is a 422 server-side).
   */
  bgm_provider?: BgmProvider;
  /** Optional webhook URL notified when the job reaches a terminal state. */
  webhook_url?: string;
  /** Per-job ToS / AI-disclosure acknowledgement, coerced to a bool server-side. */
  tos_disclosure?: boolean;
  /**
   * Charge this job to a workspace's SHARED credit pool instead of the caller's
   * personal balance. When set, the caller MUST be a member of the workspace
   * (enforced server-side; a non-member/unknown id yields a 403). Omit or leave
   * blank for the classic per-user debit.
   */
  workspace_id?: string;
  /**
   * PAY-AS-YOU-GO (optional): the selected generation-profile slug. When sent
   * with a server-signed `quote`, the backend funds this job from the USD wallet
   * (reserve -> settle/release) instead of the fixed credit ledger.
   */
  generation_profile_id?: string;
  /** Server-signed generation quote snapshot (POST /catalog/quotes/generation). */
  quote?: unknown;
  /** Effects Mix: stackable VFX preset ids (from GET /catalog/vfx-presets). */
  effects?: string[];
  /**
   * OPTIONAL AI B-roll cutaway: R2 object key of a muted stock clip spliced in
   * as a brief INTRO before the hook. Obtain it by picking a clip returned from
   * {@link suggestBroll} (its {@link BrollClip.key}). Omit for no intro clip.
   */
  broll_intro_key?: string;
  /**
   * OPTIONAL AI B-roll cutaway: R2 object key of a muted stock clip spliced in
   * as a brief OUTRO after the composed reel (see {@link broll_intro_key}).
   */
  broll_outro_key?: string;
  /**
   * AUTO-TIGHTEN (opt-in retention edit): when true, the raw screen recording is
   * pre-processed to remove dead air — silent audio gaps AND static/low-motion
   * stretches — BEFORE compose, so the reel keeps a tighter pace. Purely a
   * pre-step on the background recording; the voiceover + caption timeline is
   * never touched. Defaults to `false` (backend `auto_tighten`). Degrade-safe:
   * if no removable dead air is found, the original clip is used unchanged.
   */
  auto_tighten?: boolean;
  /**
   * EDITING POLISH — AUTO-ZOOM (opt-in): when true, scene changes in the raw
   * screen recording drive subtle punch-in zooms BEFORE compose, so the reel
   * gets dynamic, retention-boosting movement. Purely a background-recording
   * pre-step; the voiceover + caption timeline is never touched. Defaults to
   * `false` (backend `auto_zoom`). Degrade-safe: the clip is used unchanged if
   * the optional scene-detection dependency is unavailable or nothing is found.
   */
  auto_zoom?: boolean;
  /**
   * EDITING POLISH — CAMERA MOTION (opt-in): a duration-preserving virtual
   * camera move applied to the screen recording before compose. One of the
   * {@link CAMERA_MOTION_PRESETS} values; omit or send `"none"` to disable.
   * A value outside the enum is a 422 server-side. Never touches narration or
   * captions; degrade-safe (falls back to the original clip on any failure).
   */
  camera_motion?: CameraMotion;
  /**
   * EDITING POLISH — REMOVE BACKGROUND (opt-in): when true, the presenter/avatar
   * clip is neurally matted so its background is keyed out before the overlay
   * composites cleanly onto the screen recording. Defaults to `false` (backend
   * `remove_bg`). Degrade-safe: the avatar is used unchanged if the optional
   * matting dependency (rembg) is unavailable or matting fails.
   */
  remove_bg?: boolean;
}

/**
 * Virtual-camera motion presets for {@link JobCreateRequest.camera_motion}
 * (mirrors the backend `_CAMERA_MOTION_PRESETS` allow-list). `"none"` disables
 * the pass. A value outside this set is rejected server-side with a 422.
 */
export type CameraMotion = ReelCameraMotion;

/** Selectable camera-motion presets, in picker order (`"none"` = off). */
export const CAMERA_MOTION_PRESETS = REEL_CAMERA_MOTIONS;

/** Backend hard cap on batch variant fan-out (`_MAX_VARIANTS`). */
export const MAX_JOB_VARIANTS = MAX_REEL_JOB_VARIANTS;

// ---------------------------------------------------------------------------
// AI B-roll cutaways (POST /jobs/{id}/broll/suggest) — repurposes MPT's vendored
// Pexels/Pixabay stock-footage path as an OPTIONAL creative overlay: short,
// muted stock clips spliced as a brief INTRO (before the hook) and/or OUTRO
// (after) around the composed reel. The main reel keeps its full audio + captions.
// ---------------------------------------------------------------------------

/** Stock-footage provider a B-roll suggestion can be sourced from. */
export type BrollSource = "pexels" | "pixabay";

/** Selectable B-roll stock providers (mirrors MPT's vendored integrations). */
export const BROLL_SOURCES: readonly BrollSource[] = ["pexels", "pixabay"];

/** Default number of B-roll clips to suggest. */
export const BROLL_DEFAULT_AMOUNT = 6;
/** Server-side clamp on how many clips a single suggest call returns. */
export const BROLL_MIN_AMOUNT = 1;
export const BROLL_MAX_AMOUNT = 12;

/** Query for {@link suggestBroll}. Both fields are optional (server-defaulted). */
export interface SuggestBrollParams {
  /** Stock provider to pull from; omit to let the backend choose. */
  source?: BrollSource;
  /** How many clips to return (clamped to [BROLL_MIN_AMOUNT, BROLL_MAX_AMOUNT]). */
  amount?: number;
}

/**
 * A single suggested stock clip from POST /jobs/{id}/broll/suggest. The backend
 * has already downloaded + cached the muted clip (reusing MPT's `download_videos`
 * + `material_cache`); `key` is its R2 object key to send as a job's
 * `broll_intro_key` / `broll_outro_key`. Extra provider fields are preserved.
 */
export interface BrollClip {
  /** R2 object key of the cached muted clip (send as broll_intro_key/broll_outro_key). */
  key: string;
  /** Stock provider the clip came from (e.g. "pexels", "pixabay"). */
  provider?: string;
  /** Keyword (from `generate_terms`) that surfaced this clip. */
  search_term?: string;
  /** Clip duration in seconds, when known. */
  duration?: number;
  width?: number;
  height?: number;
  /** Preview thumbnail image URL for the grid. */
  thumbnail_url?: string;
  /** Short muted preview/stream URL for the clip, when available. */
  preview_url?: string;
  /** Link to the clip's page on the provider (attribution). */
  source_page?: string;
  [key: string]: unknown;
}

/** Response from POST /jobs/{id}/broll/suggest. */
export interface SuggestBrollResult {
  clips: BrollClip[];
}

// ---------------------------------------------------------------------------
// AI B-roll Studio (async text/image -> motion clip generation)
// ---------------------------------------------------------------------------

/** Generation primitive: text->video (default) or image->video. */
export type BrollGenMode = BrollGenerationMode;

/** Request body for POST /broll/generate (studio AI generation). */
export type BrollGenerateRequest = BrollGenerateInput;

/**
 * One studio generation's lifecycle snapshot (a `Job(kind="broll_gen")`).
 * `generation_id` is the pollable job id; `broll_key` is the rendered clip's R2
 * key once `state === JobState.Complete` (empty until then), ready to send as a
 * job's `broll_intro_key` / `broll_outro_key`.
 */
export type BrollGeneration = BrollGenerationSnapshot;

/** Read-only availability contract from GET /pilot/capabilities. */
export type PilotCapabilities = ContractPilotCapabilities;

/**
 * A curated (or user) motion preset for the studio picker (GET /broll/presets).
 * `prompt_template` seeds the prompt box — a `{subject}` placeholder, if present,
 * is filled by the creator. `default_params` carries motion knobs forwarded to
 * generation.
 */
export interface BrollPreset {
  id: string;
  name: string;
  description: string;
  mode: BrollGenMode;
  prompt_template: string;
  thumbnail_url: string;
  workflow_id: string;
  default_params: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Uploads / presign
// ---------------------------------------------------------------------------

/** Request body for POST /uploads/presign. */
export type PresignRequest = PresignUploadInput;

/**
 * Response from POST /uploads/presign. `headers` are the signed headers the
 * client MUST echo on the PUT to `upload_url` (e.g. Content-Type). `key` is
 * used as `screen_recording_key` when creating a job.
 */
export type PresignResult = PresignUploadResult;

// ---------------------------------------------------------------------------
// Avatars / voices / me
// ---------------------------------------------------------------------------

/**
 * Where a merged {@link Avatar} entry came from: `"preset"` is a stored
 * `AvatarPreset` row (including a creator's CUSTOM photo→avatar), `"provider"`
 * is a live entry from the provider catalog (e.g. HeyGen). Widened with `string`
 * so an unrecognised future source still renders instead of failing to
 * type-check.
 */
export type AvatarSource = "preset" | "provider" | (string & {});

/**
 * Avatar entry from GET /avatars (merged AvatarPreset rows + provider
 * list_avatars()). Backend returns loosely-typed dicts, so optional fields
 * are permissive; `[key: string]` preserves any provider-specific extras.
 *
 * NOTE: preset rows are serialised with `id` + `provider_avatar_id` but no
 * `avatar_id`; {@link listAvatars} normalises every entry so `avatar_id` is
 * always the value the wizard should send as `params.avatar_id` (the backend
 * resolves it against either `AvatarPreset.provider_avatar_id` or
 * `AvatarPreset.id`).
 */
export interface Avatar {
  avatar_id: string;
  name?: string;
  display_name?: string;
  provider?: string;
  thumbnail_url?: string;
  voice_name?: string;
  is_active?: boolean;
  /** Stored preset row id, when this entry is a preset (`source === "preset"`). */
  id?: string;
  /** Provider avatar / talking-photo id backing a preset entry. */
  provider_avatar_id?: string;
  /** `"talking_photo"` for a creator photo→avatar preset; `""`/absent otherwise. */
  kind?: string;
  /** Origin of the entry — drives the "Yours" badge on custom avatars. */
  source?: AvatarSource;
  [key: string]: unknown;
}

/**
 * A creator's CUSTOM photo→avatar is a stored preset the caller owns. GET
 * /avatars does not expose per-entry ownership, but only stored presets carry
 * `source === "preset"` (curated catalog avatars are `"provider"`), so this is
 * the signal used to badge an avatar as "Yours" in the picker.
 */
export function isCustomAvatar(avatar: Pick<Avatar, "source">): boolean {
  return avatar.source === "preset";
}

/**
 * Request body for POST /avatars (Phase 3 — CUSTOM AVATAR FROM A PHOTO). Turns a
 * previously uploaded selfie into a HeyGen talking-photo avatar that lip-syncs
 * the reel's narration. `image_key` is the R2 object key of the uploaded photo
 * (from {@link presignAndUpload}); it MUST be an upload the caller owns (403
 * otherwise). `display_name` names the avatar; `voice_name`
 * (`"elevenlabs:<voice_id>"`) is optional metadata.
 */
export interface CreateAvatarRequest {
  image_key: string;
  display_name?: string;
  voice_name?: string;
}

/**
 * The persisted avatar returned by POST /avatars — an `AvatarPreset` row.
 * `provider_avatar_id` carries HeyGen's `talking_photo_id` and `kind` is
 * `"talking_photo"`. It appears in {@link listAvatars} (as `source: "preset"`)
 * for use as a reel's avatar. The index signature preserves forward-compatible
 * fields the backend may add.
 */
export interface CustomAvatar {
  /** Stored preset row id. */
  id: string;
  provider: string;
  /** HeyGen talking-photo id that drives the avatar. */
  provider_avatar_id: string;
  display_name: string;
  voice_name: string;
  thumbnail_url: string;
  kind: string;
  is_active: boolean;
  [key: string]: unknown;
}

/** Voice entry from GET /voices (normalized ElevenLabs voices). */
export interface Voice {
  voice_id: string;
  name?: string;
  category?: string;
  labels?: Record<string, string>;
  preview_url?: string;
  [key: string]: unknown;
}

/** Current-user summary from GET /me. */
export interface Me {
  user_id: string;
  email: string;
  credits: number;
  jobs_count: number;
  /** The caller's own platform-admin flag (admin routes still gate server-side). */
  is_staff?: boolean;
}

// ---------------------------------------------------------------------------
// Brand Voice (voice cloning) — POST /voices/clone, GET /voices/mine
// ---------------------------------------------------------------------------

/**
 * A creator's cloned "brand voice" from POST /voices/clone and GET /voices/mine.
 * `voice_id` is the narrator selector (`"elevenlabs:<provider_voice_id>"`) sent
 * as `params.voice_name`; it is NOT the internal row `id`. Pass `id` (not
 * `voice_id`) to DELETE /voices/mine/{id}.
 */
export interface UserVoice {
  /** Internal row id — used to delete the voice (DELETE /voices/mine/{id}). */
  id: string;
  /** Narrator selector `"elevenlabs:<provider_voice_id>"` (send as voice_name). */
  voice_id: string;
  /** User-chosen display name for the cloned voice. */
  name: string;
  /** Provider clone status, e.g. `"ready"`. */
  status: string;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/**
 * Request body for POST /voices/clone. `sample_key` is the R2 object key of a
 * previously uploaded voice sample (from {@link presignAndUpload}). `consent`
 * MUST be `true` — it records the mandatory ownership/authorization attestation
 * (the backend rejects the request with 400 otherwise).
 */
export interface CloneVoiceRequest {
  name: string;
  sample_key: string;
  consent: boolean;
  description?: string;
  /** M7.2: token from POST /voices/verification-phrase. */
  verification_token?: string;
  /** M7.2: R2 key of the caller's recording of the phrase. */
  verification_key?: string;
}

/** M7.2: POST /voices/verification-phrase — a phrase to read aloud before cloning. */
export interface VoiceVerificationPhrase {
  token: string;
  phrase: string;
  /** Unix seconds after which the token is refused. */
  expires_at: number;
  /** False only when the owner switched the check off. */
  required: boolean;
}

/** Acknowledgement returned by DELETE /voices/mine/{id}. */
export interface VoiceDeleteResult {
  id: string;
  deleted: boolean;
}

// ---------------------------------------------------------------------------
// Billing / plans (POST /billing/checkout, GET /billing/plans)
// ---------------------------------------------------------------------------

/**
 * Payment providers supported at checkout. `iyzico` is used for Turkey (TR);
 * `creem` (creem.io) and `polar` (polar.sh) are merchant-of-record checkout
 * platforms that handle global cards, wallets, and sales tax. Which of these
 * are actually offered to a buyer is decided by the backend (only providers
 * with configured secrets are enabled) — see {@link getProviders}.
 */
export type PaymentProvider = "stripe" | "iyzico" | "creem" | "polar" | "dodo" | "paddle";

/**
 * Every payment provider the client knows how to render, in display order. Use
 * this as the client-side allow-list; the *enabled* subset for a given buyer
 * comes from `GET /billing/providers` (see {@link getProviders}).
 */
export const PAYMENT_PROVIDERS: readonly PaymentProvider[] = [
  "dodo",
  "paddle",
  "stripe",
  "iyzico",
  "creem",
  "polar",
];

/**
 * A purchasable credit pack from GET /billing/plans. The backend is the source
 * of truth for `plan_key`, `credits`, and pricing; extra provider-specific
 * fields are preserved via the index signature.
 */
export interface Plan {
  /** Stable identifier sent as `plan_key` at checkout (e.g. "starter"). */
  plan_key: string;
  name?: string;
  /** Number of reel credits granted when the pack is purchased. */
  credits?: number;
  /** Minor-unit amount (e.g. cents) if the backend returns a numeric price. */
  amount?: number;
  /** ISO currency code, e.g. "USD" or "TRY". */
  currency?: string;
  /** Pre-formatted display price, if the backend supplies one. */
  price?: string;
  [key: string]: unknown;
}

/** Request body for POST /billing/checkout. */
export interface CheckoutRequest {
  plan_key: string;
  provider: PaymentProvider;
  /**
   * When present, the pack is bought for this workspace's SHARED credit pool
   * instead of the buyer's personal balance. The backend carries it through
   * checkout metadata and, on webhook fulfilment, grants to the workspace pool
   * (idempotently). Only workspace admins/owners may buy for a workspace.
   */
  workspace_id?: string;
}

/**
 * Response from POST /billing/checkout. `checkout_url` is the hosted payment
 * page (Stripe, iyzico, Creem, or Polar) the client redirects the buyer to.
 */
export interface CheckoutResult {
  checkout_url: string;
  provider?: PaymentProvider;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Creator-studio catalogs (GET /catalog/*)
// ---------------------------------------------------------------------------

/**
 * A caption-style preset from GET /catalog/caption-styles. `id` is what you
 * send as `caption_style`. `primary`/`secondary` are ASS `&HAABBGGRR` colours.
 * The index signature preserves any forward-compatible fields the service adds.
 */
export interface CaptionStyle {
  id: string;
  name: string;
  description: string;
  primary?: string;
  secondary?: string;
  [key: string]: unknown;
}

/** A background-music track from GET /catalog/music. `id` is sent as `music_id`. */
export interface MusicTrack {
  id: string;
  name: string;
  filename: string;
  /** Track duration in seconds, present only when the backend could probe it. */
  duration_s?: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// AI background music (GET /catalog/music-generators) — the OSS music-generation
// integrations vendored server-side (`elevenlabs_music` / `sonilo`) turn a text
// `music_prompt` into a custom royalty-free BGM track fed to compose as the
// reel's `music_path`. Only providers whose API keys are configured server-side
// are returned (each provider's `is_enabled()` guard). See the AI-BGM fields on
// {@link JobCreateRequest}.
// ---------------------------------------------------------------------------

/**
 * Known AI-BGM provider ids the render pipeline can dispatch to (mirrors the
 * backend `_AI_BGM_PROVIDERS`). Sent as {@link JobCreateRequest.bgm_provider};
 * `""` (or omitting the field) auto-selects the first enabled provider.
 */
export const BGM_PROVIDERS = ["elevenlabs", "sonilo"] as const;

/**
 * An AI-BGM provider id. Widened with `string` so an unrecognised future
 * provider surfaced by the catalog still renders instead of failing to
 * type-check; validate against {@link listMusicGenerators} at the boundary.
 */
export type BgmProvider = (typeof BGM_PROVIDERS)[number] | (string & {});

/**
 * An enabled AI background-music generator from GET /catalog/music-generators.
 * `id` is sent as {@link JobCreateRequest.bgm_provider`}; `name` is the display
 * label; `max_prompt_length` is the provider's hard cap on the `music_prompt`
 * length (the UI must respect it). The endpoint only lists providers whose
 * server-side credentials are configured, so a non-empty list means AI-BGM is
 * available.
 */
export interface MusicGenerator {
  /** Provider id sent as `bgm_provider` (e.g. "elevenlabs", "sonilo"). */
  id: BgmProvider;
  /** Human-readable provider name. */
  name: string;
  /** Provider hard cap on the `music_prompt` length, in characters. */
  max_prompt_length: number;
  [key: string]: unknown;
}

/**
 * A composition-layout descriptor from GET /catalog/layouts. `id` matches the
 * `Layout` id union above (the value sent as `params.layout`); this interface is
 * the richer catalog item (id + display copy) used to render a layout picker.
 */
export interface LayoutOption {
  id: Layout | string;
  name: string;
  description: string;
  [key: string]: unknown;
}

/**
 * A curated job template from GET /catalog/templates. Pre-fills a create-job
 * form; spread the relevant fields onto `ReelForgeParams` when a user picks one.
 */
export interface Template {
  id: string;
  name: string;
  description: string;
  video_subject: string;
  prompt_scaffold: string;
  layout: Layout | string;
  caption_style: string;
  language: Language | string;
  target_duration_s: number;
  [key: string]: unknown;
}

/** A single native hook line (from the hook catalog). */
export type Hook = string;

/**
 * The hook catalog from GET /catalog/hooks: native hook lines keyed by language
 * code (e.g. `{ en: [...], tr: [...] }`).
 */
export type HookCatalog = Record<string, Hook[]>;

// ---------------------------------------------------------------------------
// Cover / thumbnail generator (GET /catalog/cover-styles, POST /jobs/{id}/cover)
// ---------------------------------------------------------------------------

/**
 * A cover / thumbnail style preset from GET /catalog/cover-styles. `id` is the
 * value sent as `style` to {@link generateCover}; `name`/`description` are
 * display copy. Optional `accent`/`background` are hex colours (`#RRGGBB`) a
 * picker may render as a swatch. The index signature preserves forward-
 * compatible fields the service adds.
 */
export interface CoverStyle {
  /** Stable identifier sent as `style` when generating a cover. */
  id: string;
  name: string;
  description: string;
  /** Optional accent (headline) colour as a `#RRGGBB` hex string. */
  accent?: string;
  /** Optional background colour as a `#RRGGBB` hex string. */
  background?: string;
  [key: string]: unknown;
}

/**
 * Request body for POST /jobs/{id}/cover. Both fields are optional: the backend
 * defaults the headline to the reel's hook and the style to the first preset.
 */
export interface GenerateCoverRequest {
  /** Headline overlaid on the cover; defaults to the reel's hook server-side. */
  headline?: string;
  /** Cover style id (see {@link CoverStyle}); defaults to the first preset. */
  style?: string;
}

/**
 * One catalog style scored by the server-side cover ranker for the reel's
 * headline. `composite` is the tunable ranking score (`stop + 0.5*legibility -
 * 0.75*generic`); the raw signals let the UI explain the ranking. `scored` is
 * `false` for a pass-through entry (ranker degraded, e.g. no TYPESAFE_API_KEY).
 */
export interface RankedCoverStyle {
  id: string;
  name: string;
  composite: number;
  stop_power: number;
  legibility: number;
  is_generic: number;
  primary_mood?: string;
  scored?: boolean;
}

/**
 * The auto-pick result surfaced alongside a generated cover. `recommended_style`
 * is the style the ranker would pick and `ranked` is every candidate ordered
 * best-first. `degraded` is `true` when the ranker fell back to the deterministic
 * default (no TYPESAFE_API_KEY or a scoring failure).
 */
export interface CoverRecommendation {
  recommended_style: string;
  degraded: boolean;
  note?: string;
  ranked: RankedCoverStyle[];
}

/**
 * Result of POST /jobs/{id}/cover — a freshly rendered 1080x1920 JPG uploaded to
 * R2. `cover_key` is the stored object key (persisted as `Job.cover_key`);
 * `cover_url` is a presigned URL to preview/download it; `style` echoes the
 * style actually applied. `auto_selected` is `true` when the style was chosen by
 * the cover ranker (no explicit style sent); `recommendation` carries the full
 * ranked list when the ranker ran (absent when there was no headline to rank).
 */
export interface GenerateCoverResult {
  cover_key: string;
  cover_url: string;
  style: string;
  auto_selected?: boolean;
  recommendation?: CoverRecommendation;
}

// ---------------------------------------------------------------------------
// Re-run (POST /jobs/{id}/rerun)
// ---------------------------------------------------------------------------

/**
 * Optional per-field tweaks applied when re-running a job. Only the fields set
 * replace the source job's stored values; `voice_id` is normalised to the
 * `elevenlabs:<id>` form server-side.
 */
export interface RerunOverrides {
  avatar_id?: string;
  voice_id?: string;
  layout?: Layout | string;
  caption_style?: string;
  music_id?: string;
  language?: Language | string;
  /** OPTIONAL AI B-roll: R2 key of a muted intro clip (see {@link BrollClip}). */
  broll_intro_key?: string;
  /** OPTIONAL AI B-roll: R2 key of a muted outro clip (see {@link BrollClip}). */
  broll_outro_key?: string;
  /**
   * Opening-hook angle for a fresh variation (e.g. "question"). Only applies
   * when Menivor writes the script; the API answers 409 for a reel whose
   * script the creator wrote.
   */
  hook_style?: string;
}

// ---------------------------------------------------------------------------
// Growth surfaces (GET /me/insights, /me/referral, /me/presets)
// ---------------------------------------------------------------------------

/** Per-user dashboard analytics from GET /me/insights (strictly caller-scoped). */
export interface Insights {
  user_id: string;
  jobs_total: number;
  /** Job counts keyed by state name, e.g. `{ complete: 9, failed: 1 }`. */
  jobs_by_state: Record<string, number>;
  credits_balance: number;
  credits_spent: number;
  total_cost_usd: number;
  avg_render_ms: number;
  videos_generated: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Creator BI analytics (GET /me/analytics?days=) — a richer, strictly
// caller-scoped business-intelligence view over the data ReelForge already
// records (jobs / job_events / credit_ledger). Mirrors the output of
// app/services/analytics.py::creator_analytics merged with top_content. Every
// figure is scoped to the trailing `days` window except `credits.balance`,
// which is the live all-time personal balance.
// ---------------------------------------------------------------------------

/** The trailing-window sizes (in days) offered by the dashboard's selector. */
export const ANALYTICS_WINDOW_DAYS = [7, 30, 90] as const;

export type AnalyticsWindowDays = (typeof ANALYTICS_WINDOW_DAYS)[number];

/** Default trailing window applied when the caller does not pick one. */
export const ANALYTICS_DEFAULT_DAYS: AnalyticsWindowDays = 30;

/**
 * The jobs funnel for the window: `created` -> `completed` (successfully
 * rendered) -> `published` (reached a completed upload stage). `failed` is the
 * count of jobs that ended in the failed state. The index signature preserves
 * forward-compatible stages the service may add.
 */
export interface AnalyticsFunnel {
  created: number;
  completed: number;
  failed: number;
  published: number;
  [key: string]: number;
}

/** A single day's summed render spend (SUM(job_events.cost_usd)). */
export interface AnalyticsCostPoint {
  /** `YYYY-MM-DD` day bucket. */
  date: string;
  cost_usd: number;
}

/** A single day's credit burn (magnitude of the day's negative ledger deltas). */
export interface AnalyticsBurnPoint {
  /** `YYYY-MM-DD` day bucket. */
  date: string;
  spent: number;
}

/**
 * Credit burn-rate + live balance. `balance` is the live all-time personal
 * balance; `spent` and `burn_by_day` cover the trailing window.
 */
export interface AnalyticsCredits {
  balance: number;
  spent: number;
  burn_by_day: AnalyticsBurnPoint[];
}

/**
 * Render-time distribution for the window, from the completed compose/upload
 * stage `duration_ms`. `samples` is the number of render events measured.
 */
export interface AnalyticsRenderTime {
  p50_ms: number;
  p90_ms: number;
  avg_ms: number;
  samples: number;
}

/** Headline totals for the window. */
export interface AnalyticsTotals {
  jobs_total: number;
  videos_generated: number;
  total_cost_usd: number;
  [key: string]: number;
}

/** One `{ name, count }` template-usage entry (most frequent first). */
export interface AnalyticsTemplateCount {
  name: string;
  count: number;
}

/** One `{ hook, count }` hook-usage entry (most frequent first). */
export interface AnalyticsHookCount {
  hook: string;
  count: number;
}

/** The creator's most-used templates and hooks (best-effort, all-time). */
export interface AnalyticsTopContent {
  templates: AnalyticsTemplateCount[];
  hooks: AnalyticsHookCount[];
}

/**
 * The caller's BI analytics dashboard from GET /me/analytics. Strictly
 * caller-scoped. The index signature preserves forward-compatible nested
 * metrics the service may add without breaking the client.
 */
export interface Analytics {
  user_id: string;
  /** The trailing window (in days) the aggregates cover. */
  days: number;
  funnel: AnalyticsFunnel;
  /** Ascending day buckets of summed render spend. */
  cost_by_day: AnalyticsCostPoint[];
  credits: AnalyticsCredits;
  render_time: AnalyticsRenderTime;
  /** Job counts keyed by composition layout (e.g. `{ pip: 4 }`). */
  by_layout: Record<string, number>;
  /** Job counts keyed by language code (e.g. `{ en: 7, tr: 2 }`). */
  by_language: Record<string, number>;
  /** Job counts keyed by requested variant count. */
  by_variants: Record<string, number>;
  totals: AnalyticsTotals;
  top_content: AnalyticsTopContent;
  [key: string]: unknown;
}

/** The caller's referral code + lifetime stats from GET /me/referral. */
export interface Referral {
  code: string;
  referred_count: number;
  credits_earned: number;
  [key: string]: unknown;
}

/** Result of POST /me/referral/redeem. `ok` is false only on a guarded failure. */
export interface RedeemResult {
  ok: boolean;
  referrer_id?: string;
  referee_id?: string;
  referrer_grant?: number;
  referee_grant?: number;
  referrer_balance?: number;
  referee_balance?: number;
  error?: string;
  message?: string;
  [key: string]: unknown;
}

/**
 * A saved wizard/job preset ("brand kit") from GET/POST /me/presets. A preset is
 * either private to the caller or SHARED to a workspace so every member sees it.
 * GET /me/presets returns the caller's own presets UNION presets any teammate
 * shared to a workspace the caller belongs to.
 */
export interface Preset {
  id: string;
  name: string;
  /** Opaque config map to spread back onto a create-job payload. */
  config: Record<string, unknown>;
  /**
   * The workspace this preset is shared to, or null/undefined when it is private
   * to the caller. Set by creating the preset with a `workspace_id`.
   */
  workspace_id?: string | null;
  /** Derived flag: true when the preset is shared to a workspace (team kit). */
  shared?: boolean;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/** Request body for POST /me/presets. */
export interface PresetCreateRequest {
  name: string;
  config: Record<string, unknown>;
  /**
   * Optional workspace id to SHARE this preset with. When set, the preset is
   * visible to every member of the workspace (the caller must be a member; a
   * non-member/unknown id yields a 403). Omit to keep the preset private.
   */
  workspace_id?: string;
}

/** Acknowledgement returned by DELETE /me/presets/{id}. */
export interface PresetDeleteResult {
  deleted: boolean;
  id: string;
}

// ---------------------------------------------------------------------------
// SPARK — AI Idea Engine (POST /ideas/generate, GET/POST/DELETE /me/ideas)
// ---------------------------------------------------------------------------

/**
 * Caption-style ids a generated idea may suggest. These mirror the built-in
 * wizard caption presets so an idea maps cleanly onto `params.caption_style`.
 */
export type IdeaCaptionStyle =
  | "karaoke_yellow"
  | "karaoke_green"
  | "clean_white"
  | "bold_violet";

/** The concrete languages a generated idea is written in. */
export type IdeaLanguage = "tr" | "en";

/**
 * A single ready-to-shoot viral UGC video concept produced by SPARK. Every
 * suggestion field aligns with a create-job input so an idea can be turned into
 * a real reel via the wizard (`suggested_layout` → `params.layout`, etc.).
 */
export interface Idea {
  /** Short, scroll-stopping concept title. */
  title: string;
  /** The opening line, kept punchy (<= 12 words). */
  hook: string;
  /** The narrative angle / why-it-works framing. */
  angle: string;
  /** The shooting format, e.g. "talking head", "tutorial", "reaction". */
  format: string;
  /** 2–4 ordered beats describing how the reel unfolds. */
  script_outline: string[];
  /** Suggested composition layout (maps to `params.layout`). */
  suggested_layout: Layout;
  /** Suggested caption style (maps to `params.caption_style`). */
  suggested_caption_style: IdeaCaptionStyle;
  /** Language the idea is written in (maps to `params.language`). */
  language: IdeaLanguage;
  /** Suggested target duration in seconds. */
  est_duration_s: number;
}

/**
 * A generated idea the caller has saved for later (GET/POST /me/ideas). Adds a
 * server-assigned `id` (used to delete it) and an optional creation timestamp.
 */
export interface SavedIdea extends Idea {
  /** Server row id — pass to DELETE /me/ideas/{id}. */
  id: string;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
}

/** Request body for POST /ideas/generate. */
export interface GenerateIdeasRequest {
  /** The creator's description of their app / product / niche. */
  app_context: string;
  /** Optional target audience to tailor the concepts toward. */
  audience?: string;
  /** How many concepts to generate (backend clamps to a sane range). */
  count?: number;
  /** Preferred output language; `"auto"` lets the engine decide. */
  language?: IdeaLanguage | "auto";
}

/** Acknowledgement returned by DELETE /me/ideas/{id}. */
export interface SavedIdeaDeleteResult {
  deleted: boolean;
  id: string;
}

// ---------------------------------------------------------------------------
// In-app notifications (GET/POST /me/notifications*) — bell + unread badge +
// notification center. The in-app counterpart to the external webhook
// (app/services/webhooks.py). Server best-effort emits on lifecycle / growth
// events; the client lists, marks-read, and polls the unread count.
// ---------------------------------------------------------------------------

/**
 * The event a notification was emitted for. Kept as a string-literal union of
 * the contract-stable kinds, widened with `string` so an unrecognised future
 * kind still renders (falling back to a generic icon/label) instead of failing
 * to type-check.
 */
export type NotificationKind =
  | "job_complete"
  | "job_failed"
  | "low_credits"
  | "referral_earned"
  | (string & {});

/**
 * A single in-app notification (public shape from GET /me/notifications). `data`
 * is an opaque, event-specific metadata map (e.g. `job_id`, `result_url`,
 * `error`, `balance`, `credits`) — never secrets. When `data.job_id` is present
 * the notification deep-links to that job. The backend serialiser omits
 * `user_id`; it is typed optional here only for completeness.
 */
export interface Notification {
  id: string;
  kind: NotificationKind;
  title: string;
  body: string;
  /** Opaque, non-sensitive event metadata. Read fields defensively. */
  data: Record<string, unknown>;
  read: boolean;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  /** Owner id — not returned by the public serialiser; optional for parity. */
  user_id?: string;
}

/** Query filters for GET /me/notifications. */
export interface ListNotificationsParams {
  /** Restrict to unread notifications only. */
  unread_only?: boolean;
  /** Page size (backend clamps to [1, 200]; default 50). */
  limit?: number;
}

/**
 * Response from GET /me/notifications: the caller's notifications (newest first)
 * plus their live total `unread_count` (independent of the page/filter) so the
 * bell badge stays correct even on a filtered or truncated list.
 */
export interface NotificationListResult {
  notifications: Notification[];
  unread_count: number;
}

/** Response from GET /me/notifications/unread_count. */
export interface UnreadCountResult {
  unread_count: number;
}

/** Acknowledgement from POST /me/notifications/{id}/read. */
export interface MarkNotificationReadResult {
  id: string;
  read: boolean;
}

/** Acknowledgement from POST /me/notifications/read_all. */
export interface MarkAllNotificationsReadResult {
  /** How many previously-unread notifications were flipped to read. */
  updated: number;
  /** Always 0 after a successful mark-all. */
  unread_count: number;
}

// ---------------------------------------------------------------------------
// Multi-language dubbing (GET /dub/languages, POST /jobs/{id}/dub)
// ---------------------------------------------------------------------------

/**
 * Language codes ReelForge can dub into. Bundled caption fonts cover exactly
 * this set; the backend `GET /dub/languages` catalog is the source of truth,
 * this constant is only a fallback / narrowing aid.
 */
export const DUB_LANGUAGE_CODES = [
  "en",
  "tr",
  "es",
  "fr",
  "de",
  "pt",
  "it",
] as const;

export type DubLanguageCode = (typeof DUB_LANGUAGE_CODES)[number];

/**
 * A supported dubbing target from GET /dub/languages. `code` is the value sent
 * in {@link dubJob}'s `languages` array; `name` is the English display label and
 * `native_name` the endonym (e.g. `{ code: "es", name: "Spanish",
 * native_name: "Español" }`). The index signature preserves forward-compatible
 * fields the catalog may add.
 */
export interface DubLanguage {
  code: string;
  name: string;
  native_name?: string;
  [key: string]: unknown;
}

/**
 * Result of POST /jobs/{id}/dub — translates the source reel's script and fans
 * out one dubbed job per requested language, all sharing a single `batch_id`
 * so they can be reviewed together via GET /batches/{batch_id}
 * (see {@link BatchData}). `job_ids` is aligned with `languages` (one per code).
 */
export interface DubResult {
  batch_id: string;
  job_ids: string[];
  languages: string[];
}

// ---------------------------------------------------------------------------
// Scheduled publishing (POST /jobs/{id}/schedule, GET/DELETE /me/scheduled) —
// auto-publish a finished reel to platforms at a future UTC time. A Celery-beat
// due-runner picks up pending schedules whose `scheduled_at` has arrived,
// publishes via app/services/publish.py + upload_post, and flips the row to
// published/failed. Users list and cancel their pending schedules.
// ---------------------------------------------------------------------------

/**
 * Platforms a scheduled reel can be auto-published to. Mirrors the destinations
 * handled by app/services/publish.py + upload_post. The union is widened with
 * `string` so an unrecognised future platform still renders instead of failing
 * to type-check.
 */
export const PUBLISH_PLATFORMS = [
  "tiktok",
  "instagram",
  "youtube_shorts",
] as const;

export type PublishPlatform = (typeof PUBLISH_PLATFORMS)[number] | (string & {});

/**
 * Visibility applied to a YouTube Shorts upload. Only meaningful when
 * `youtube_shorts` is one of the target platforms; ignored otherwise.
 */
export const YOUTUBE_PRIVACY_STATUSES = [
  "public",
  "unlisted",
  "private",
] as const;

export type YouTubePrivacyStatus = (typeof YOUTUBE_PRIVACY_STATUSES)[number];

/**
 * Lifecycle of a scheduled publish. `pending`/`queued` are the only cancelable
 * (not-yet-run) states; the due-runner transitions a row through
 * `publishing` → `published` on success or `failed` on error. `canceled` is a
 * terminal user action. Widened with `string` for forward-compatibility.
 */
export const SCHEDULE_ACTIVE_STATUSES = ["pending", "queued"] as const;

export type ScheduledPublishStatus =
  | "pending"
  | "queued"
  | "publishing"
  | "published"
  | "failed"
  | "canceled"
  | (string & {});

/** A schedule is cancelable only while it has not yet started publishing. */
export function isCancelableSchedule(status: ScheduledPublishStatus): boolean {
  return status === "pending" || status === "queued";
}

/** A schedule is terminal once it has published, failed, or been canceled. */
export function isTerminalSchedule(status: ScheduledPublishStatus): boolean {
  return (
    status === "published" || status === "failed" || status === "canceled"
  );
}

/**
 * A scheduled publish row from POST /jobs/{id}/schedule and GET /me/scheduled.
 * `scheduled_at` is an ISO-8601 UTC instant (the due time). The index signature
 * preserves forward-compatible fields the backend may add.
 */
export interface ScheduledPublish {
  /** Server row id — pass to DELETE /me/scheduled/{id} to cancel. */
  id: string;
  /** The finished reel this schedule publishes. */
  job_id: string;
  /** Target platforms (see {@link PUBLISH_PLATFORMS}). */
  platforms: PublishPlatform[];
  /** ISO-8601 UTC instant the reel should auto-publish at. */
  scheduled_at: string;
  /** Current lifecycle status. */
  status: ScheduledPublishStatus;
  /** YouTube visibility, when `youtube_shorts` is targeted. */
  youtube_privacy_status?: YouTubePrivacyStatus | string;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  /** ISO-8601 timestamp the publish actually ran, when available. */
  published_at?: string | null;
  /** Failure detail when `status === "failed"`. */
  error?: string | null;
  /** URL of the published post, when the backend surfaces one. */
  result_url?: string;
  [key: string]: unknown;
}

/**
 * Request body for POST /jobs/{id}/schedule. `platforms` must be non-empty and
 * `scheduled_at` must be a future ISO-8601 UTC instant. `youtube_privacy_status`
 * only applies when `youtube_shorts` is among the platforms.
 */
export interface SchedulePublishRequest {
  platforms: PublishPlatform[];
  scheduled_at: string;
  youtube_privacy_status?: YouTubePrivacyStatus;
}

/** Acknowledgement returned by DELETE /me/scheduled/{id}. */
export interface ScheduledCancelResult {
  id: string;
  canceled: boolean;
}

// ---------------------------------------------------------------------------
// Team workspaces (GET/POST /workspaces, /workspaces/{id}/members*) — an
// ADDITIVE membership layer on top of per-user job/credit ownership. A user
// creates a workspace and invites existing users (by email) as owner/admin/
// member. Owners/admins manage members + roles; members view + leave. This is
// the foundation for team plans + shared resources; it does NOT change how
// individual jobs or credits are owned today.
// ---------------------------------------------------------------------------

/**
 * A member's role within a workspace. The Enterprise RBAC vocabulary (backed by
 * the pycasbin enforcer server-side) is `owner` > `admin` > {`editor`,
 * `billing`} > `viewer`: `owner` has full control incl. billing + platform
 * access; `admin` manages members, settings, and reads the audit trail;
 * `editor` can create jobs; `billing` manages billing (and reads jobs);
 * `viewer` is read-only. The legacy `member` role is still tolerated for
 * backward-compatibility. Widened with `string` so an unrecognised future role
 * still renders (falling back to a generic label) instead of failing to
 * type-check.
 */
export type WorkspaceRole =
  | "owner"
  | "admin"
  | "editor"
  | "viewer"
  | "billing"
  | "member"
  | (string & {});

/** Roles a manager (owner/admin) may assign when inviting or changing a role. */
export const ASSIGNABLE_WORKSPACE_ROLES = ["admin", "member"] as const;

export type AssignableWorkspaceRole =
  (typeof ASSIGNABLE_WORKSPACE_ROLES)[number];

/** Owners and admins may invite/remove members and change roles. */
export function canManageWorkspace(role: WorkspaceRole): boolean {
  return role === "owner" || role === "admin";
}

/**
 * A workspace the caller belongs to, from GET/POST /workspaces. `role` is the
 * CALLER's role in this workspace (drives which management controls render).
 * The index signature preserves forward-compatible fields the backend may add.
 */
export interface Workspace {
  /** Server row id — used in all /workspaces/{id}/* calls. */
  id: string;
  /** Human-friendly workspace name. */
  name: string;
  /** The caller's role in this workspace. */
  role: WorkspaceRole;
  /** Total members, when the backend surfaces it (for the list summary). */
  member_count?: number;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/**
 * A single workspace member from GET /workspaces/{id}/members. `user_id` is the
 * stable id used to change a role or remove the member; `email` is always
 * present, `name` only when the backend has a display name. The index signature
 * preserves forward-compatible fields the backend may add.
 */
export interface Member {
  /** Stable user id — pass to setMemberRole / removeMember. */
  user_id: string;
  /** The member's email (the invite key). */
  email: string;
  /** Display name, when the backend has one. */
  name?: string;
  /** The member's role in this workspace. */
  role: WorkspaceRole;
  /** ISO-8601 timestamp the member joined, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/** Request body for POST /workspaces. */
export interface CreateWorkspaceRequest {
  name: string;
}

/**
 * Request body for POST /workspaces/{id}/members. `email` must belong to an
 * existing user; `role` defaults to `"member"` server-side when omitted.
 */
export interface InviteMemberRequest {
  email: string;
  role?: AssignableWorkspaceRole;
}

/** Acknowledgement returned by DELETE /workspaces/{id}/members/{userId}. */
export interface RemoveMemberResult {
  removed: boolean;
  user_id: string;
}

/** Acknowledgement returned by POST /workspaces/{id}/leave. */
export interface LeaveWorkspaceResult {
  left: boolean;
  workspace_id: string;
}

// ---------------------------------------------------------------------------
// Shared workspace credits (GET /workspaces/{id}/credits,
// POST /workspaces/{id}/credits/grant) — a workspace has a SHARED credit pool
// members can debit when creating jobs (see `JobCreateRequest.workspace_id`).
// Any member may read the balance; only owners/admins may grant credits.
// ---------------------------------------------------------------------------

/**
 * A workspace's SHARED credit pool balance, from GET /workspaces/{id}/credits
 * and POST /workspaces/{id}/credits/grant. `balance` is a whole number of reel
 * credits available to the whole team.
 */
export interface WorkspaceCredits {
  balance: number;
}

/**
 * Request body for POST /workspaces/{id}/credits/grant. `amount` must be a
 * positive integer (the backend rejects a non-positive amount with 400).
 * `reason` is an optional audit note recorded on the ledger row.
 */
export interface GrantWorkspaceCreditsRequest {
  amount: number;
  reason?: string;
}

// ---------------------------------------------------------------------------
// Brand watermark (GET/PUT /me/brand) — a per-user transparent-PNG logo overlaid
// on every reel in the pure-FFmpeg compose stage at a chosen corner + opacity.
// The logo is uploaded via the existing presign flow (image/png) and stored in
// R2 as `logo_key`. Applied by default when `enabled`; a job may override it.
// ---------------------------------------------------------------------------

/**
 * The corners a brand watermark can be pinned to. Mirrors the backend
 * `WATERMARK_POSITIONS` allow-list (`app/models/db/repositories.py`); an unknown
 * value is rejected server-side with a 400. Kept as a readonly tuple so a picker
 * can iterate it while `WatermarkPosition` narrows the accepted values.
 */
export const WATERMARK_POSITIONS = [
  "top_left",
  "top_right",
  "bottom_left",
  "bottom_right",
] as const;

export type WatermarkPosition = (typeof WATERMARK_POSITIONS)[number];

/** Default corner applied when a creator has never configured a watermark. */
export const WATERMARK_DEFAULT_POSITION: WatermarkPosition = "bottom_right";

/** Default overlay opacity (matches the `UserBrand` column default). */
export const WATERMARK_DEFAULT_OPACITY = 0.85;

/** Inclusive opacity bounds enforced by the backend (`400` outside the range). */
export const WATERMARK_OPACITY_MIN = 0;
export const WATERMARK_OPACITY_MAX = 1;

/** Narrow an arbitrary string to a known {@link WatermarkPosition}. */
export function isWatermarkPosition(value: string): value is WatermarkPosition {
  return (WATERMARK_POSITIONS as readonly string[]).includes(value);
}

/**
 * The caller's brand watermark settings from GET/PUT /me/brand. `logo_key` is
 * the R2 object key of the uploaded transparent PNG (empty string means "no
 * logo", which disables the overlay even while `enabled` is true). `logo_url` is
 * a short-lived presigned GET URL for previewing the stored logo, present only
 * when a `logo_key` is set. `position` is widened with `string` so an unknown
 * future corner still renders. The index signature preserves forward-compatible
 * fields the backend may add.
 */
export interface Brand {
  /** R2 key of the uploaded transparent-PNG logo; `""` means no watermark. */
  logo_key: string;
  /** Corner the logo is pinned to (see {@link WatermarkPosition}). */
  position: WatermarkPosition | string;
  /** Overlay opacity in `[0, 1]`. */
  opacity: number;
  /** Whether the watermark is applied to the caller's reels by default. */
  enabled: boolean;
  /** Presigned GET URL for the stored logo, when a `logo_key` is set. */
  logo_url?: string | null;
  /** ISO-8601 timestamp of the last update, when available. */
  updated_at?: string | null;
  [key: string]: unknown;
}

/**
 * Request body for PUT /me/brand (a partial update). Every field is optional; an
 * omitted field leaves the stored value untouched. Passing `logo_key: ""` clears
 * the watermark logo. A supplied non-empty `logo_key` must reference an upload
 * the caller owns (the backend rejects a foreign key with a 403).
 */
export interface BrandUpdateRequest {
  logo_key?: string;
  position?: WatermarkPosition | string;
  opacity?: number;
  enabled?: boolean;
}

// ---------------------------------------------------------------------------
// AI Social Caption & Hashtags (GET /catalog/social-platforms,
// POST /jobs/{id}/social) — for a finished reel, generate an optimized post
// title + caption + hashtags tailored to a target platform, built server-side on
// the vendored MPT `app/services/llm.py::generate_social_metadata`. The
// subject/script are derived from the job's own persisted data (no free-text
// prompt); the creator copies the result when posting.
// ---------------------------------------------------------------------------

/**
 * Platform ids the social-caption generator can tailor copy for. Mirrors the
 * backend `social._SUPPORTED_PLATFORMS` allow-list (`instagram` maps to the
 * LLM's `instagram_reels` spec server-side). Widened with `string` so an
 * unrecognised future platform surfaced by the catalog still renders instead of
 * failing to type-check; validate against {@link listSocialPlatforms} at the
 * boundary.
 */
export const SOCIAL_PLATFORMS = [
  "tiktok",
  "instagram",
  "youtube_shorts",
] as const;

export type SocialPlatformId = (typeof SOCIAL_PLATFORMS)[number] | (string & {});

/**
 * A supported social platform from GET /catalog/social-platforms. `id` is the
 * value sent as `platform` to {@link generateSocial}; `name` is the display
 * label (e.g. `{ id: "tiktok", name: "TikTok" }`). The index signature preserves
 * forward-compatible fields the catalog may add.
 */
export interface SocialPlatform {
  /** Stable id sent as `platform` when generating captions. */
  id: SocialPlatformId;
  /** Human-readable platform name. */
  name: string;
  [key: string]: unknown;
}

/**
 * The generated post copy from POST /jobs/{id}/social — a ready-to-paste
 * `title`, `caption`, and `hashtags`. Each hashtag is already `#`-prefixed by the
 * generator; `hashtags` may be empty when the model returns none. `title` /
 * `caption` may be edited by the creator before posting.
 */
export interface SocialMeta {
  title: string;
  caption: string;
  hashtags: string[];
}

/**
 * Request body for {@link generateSocial}. `platform` must be one of the
 * {@link listSocialPlatforms} ids (a bad id is a 400 server-side). `language` is
 * optional — omit it to generate in the job's own configured language.
 */
export interface GenerateSocialRequest {
  platform: SocialPlatformId;
  language?: string;
}

// ---------------------------------------------------------------------------
// Personal API keys (PUBLIC API KEYS) — auth-gated /me/api-keys. A power user
// mints a personal key used as the `x-api-key` header for programmatic access
// to the REST API. The raw secret is shown ONCE at creation and stored only as
// a SHA-256 hash server-side; list responses never carry the raw key or hash.
// ---------------------------------------------------------------------------

/**
 * One personal API key as returned by GET /me/api-keys — the public,
 * caller-scoped view. NEVER carries the raw key or the full hash: only the id,
 * label, non-secret `prefix`, and lifecycle/usage metadata. Both active and
 * revoked keys are listed (a full audit view).
 */
export interface ApiKey {
  /** Internal row id — used to revoke the key (DELETE /me/api-keys/{id}). */
  id: string;
  /** Human-friendly label to tell keys apart (e.g. "CI", "n8n"). */
  name: string;
  /** Short, non-secret leading fragment of the key (safe to display). */
  prefix: string;
  /** ISO-8601 timestamp the key was last used to authenticate, if ever. */
  last_used_at?: string | null;
  /** Whether the key has been revoked (a revoked key can no longer authenticate). */
  revoked: boolean;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  /**
   * POWER-USER TIER: the key's per-minute rate limit. `null` means it inherits
   * the plan/config default (no per-key override).
   */
  rate_limit_per_min?: number | null;
  /**
   * POWER-USER TIER: the key's monthly request quota. `null` means unlimited.
   */
  monthly_quota?: number | null;
  /**
   * POWER-USER TIER: requests already consumed by this key in the current
   * calendar month (0 when unused). Best-effort telemetry (degrades to 0).
   */
  usage_this_month?: number;
  [key: string]: unknown;
}

/**
 * One personal API key's CURRENT-MONTH usage + limits, from GET
 * /me/api-keys/usage. Strictly caller-scoped. `period_ym` is the `'YYYY-MM'`
 * month the `used` count applies to; `remaining` is `monthly_quota - used`
 * (floored at 0) or `null` when the key has no monthly quota (unlimited).
 * `rate_limit_per_min` is `null` when the key inherits the default rate limit.
 */
export interface ApiKeyUsage {
  /** Internal row id of the key (matches {@link ApiKey.id}). */
  id: string;
  /** Human-friendly label of the key. */
  name: string;
  /** Short, non-secret leading fragment of the key (safe to display). */
  prefix: string;
  /** The `'YYYY-MM'` calendar month the `used` count applies to. */
  period_ym: string;
  /** Requests consumed by this key so far this month (0 when unused). */
  used: number;
  /** The key's per-minute rate limit; `null` when it inherits the default. */
  rate_limit_per_min?: number | null;
  /** The key's monthly request quota; `null` when unlimited. */
  monthly_quota?: number | null;
  /** `monthly_quota - used` (floored at 0); `null` when the key is unlimited. */
  remaining?: number | null;
  [key: string]: unknown;
}

/**
 * The ONE-TIME reveal returned by POST /me/api-keys. `key` is the FULL raw
 * secret and is present ONLY here, exactly once — the server keeps only its
 * SHA-256 hash, so the raw value is unrecoverable afterwards (a lost key must be
 * revoked and re-created). Store it immediately.
 */
export interface CreatedApiKey {
  /** Internal row id of the newly minted key. */
  id: string;
  /** The label the caller gave the key. */
  name: string;
  /**
   * The FULL raw API key — shown ONCE and unrecoverable. Send it as the
   * `x-api-key` request header. Never persisted client-side.
   */
  key: string;
  /** Short, non-secret leading fragment of the key (safe to display later). */
  prefix: string;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
}

/**
 * Request body for POST /me/api-keys. `name` is a required human-friendly label
 * (1-200 chars, trimmed server-side); the raw secret is generated server-side
 * and is never client-supplied.
 */
export interface ApiKeyCreateRequest {
  name: string;
}

/** Acknowledgement returned by DELETE /me/api-keys/{id}. */
export interface ApiKeyRevokeResult {
  /** The revoked key's row id. */
  id: string;
  /** Always `true` on success. */
  revoked: boolean;
}

// ---------------------------------------------------------------------------
// Social connections & direct publish (GET /me/connections,
// GET /connections/{provider}/authorize, GET /connections/{provider}/callback,
// DELETE /me/connections/{provider}, POST /jobs/{id}/publish/{provider}) — a
// power user connects a social account via OAuth (the token is encrypted +
// stored server-side and NEVER returned) and publishes their OWN finished reel
// directly to that provider. Every shape here is strictly TOKEN-FREE.
// ---------------------------------------------------------------------------

/**
 * The social providers a reel can be connected to / published to. Mirrors the
 * backend `SOCIAL_PROVIDERS` allow-list (`app/models/db/repositories.py`); an
 * unknown value is rejected server-side. Widened with `string` so an unrecognised
 * future provider still renders instead of failing to type-check.
 */
export const SOCIAL_CONNECTION_PROVIDERS = [
  "tiktok",
  "instagram",
  "youtube",
] as const;

export type SocialProvider =
  | (typeof SOCIAL_CONNECTION_PROVIDERS)[number]
  | (string & {});

/**
 * The lifecycle status of a connected account. `connected` means the stored
 * token is still valid; `expired` means it needs a reconnect. Widened with
 * `string` for forward-compatibility.
 */
export type ConnectionStatus = "connected" | "expired" | (string & {});

/**
 * One connected social account from GET /me/connections — the caller's TOKEN-FREE
 * view. SECURITY: this shape NEVER carries an access or refresh token (encrypted
 * or not). Only the provider, the provider-side `external_account_id`, the
 * connection `status`, the granted `scopes`, and timestamps are exposed. The
 * index signature preserves forward-compatible fields the backend may add.
 */
export interface Connection {
  /** The social provider (see {@link SocialProvider}). */
  provider: SocialProvider;
  /** The provider-side account id (e.g. TikTok open_id); never a token. */
  external_account_id: string;
  /** Convenience flag — always `true` for a returned row. */
  connected: boolean;
  /** `connected` while the token is valid, `expired` when it needs a reconnect. */
  status: ConnectionStatus;
  /** Comma-separated granted OAuth scopes (e.g. "user.info.basic,video.publish"). */
  scopes: string;
  /** ISO-8601 token expiry instant, when known. */
  token_expires_at?: string | null;
  /** ISO-8601 timestamp the account was first connected, when available. */
  connected_at?: string | null;
  /** ISO-8601 timestamp of the last update, when available. */
  updated_at?: string | null;
  [key: string]: unknown;
}

/**
 * The result of GET /connections/{provider}/authorize — where to send the
 * browser to begin the OAuth grant. `authorize_url` already embeds the opaque,
 * single-use CSRF `state` the caller must echo back on the callback. Nothing
 * sensitive is returned.
 */
export interface AuthorizeInfo {
  /** The provider being connected. */
  provider: SocialProvider;
  /** The provider's OAuth authorize URL to redirect the browser to. */
  authorize_url: string;
  /** Opaque, single-use CSRF token embedded in `authorize_url`. */
  state: string;
}

/**
 * The outcome of POST /jobs/{id}/publish/{provider} — a TOKEN-FREE record of the
 * direct publish. `external_post_id` / `url` identify the created post when the
 * provider returns them. The index signature preserves forward-compatible fields.
 */
export interface PublishResult {
  /** The provider the reel was published to. */
  provider: SocialProvider;
  /** The provider-side id of the created post, when returned. */
  external_post_id: string;
  /** Public URL of the published post, when the provider returns one. */
  url: string;
  /** Publish status — `"published"` on success. */
  status: string;
  [key: string]: unknown;
}

/** Acknowledgement returned by DELETE /me/connections/{provider}. */
export interface DisconnectResult {
  /** Always `true` on success. */
  disconnected: boolean;
  /** The provider that was disconnected. */
  provider: SocialProvider;
}

// ---------------------------------------------------------------------------
// Template Marketplace (GET/POST/DELETE /marketplace*) — a creator publishes an
// IMMUTABLE snapshot of a private job template (title / description / prompt /
// params / tags / language / layout) to a PUBLIC marketplace; any other authed
// user browses/searches it, views its detail, CLONEs it into their own private
// templates, and RATEs it 1..5 (one rating per user, upserted). Listings sort by
// rating / recency / clone-count; browse clamps `limit` into [1, 100] so an
// untrusted page request can never trigger an unbounded scan. Backed by
// app/controllers/v1/marketplace.py + app/services/marketplace.py.
// ---------------------------------------------------------------------------

/**
 * Sort orders accepted by GET /marketplace. `top` ranks by rating (then
 * recency), `new` by recency, `clones` by clone-count, `proven` re-ranks the
 * clamped page by the real-world win-score of the reels made from each listing's
 * clones (annotating each with a `win_score`), and `most_remixed` ranks by
 * `remix_count` (REMIX TREES — how many times a listing was remixed). Mirrors the
 * backend's accepted `sort` values.
 */
export const MARKETPLACE_SORTS = [
  "top",
  "new",
  "clones",
  "proven",
  "most_remixed",
] as const;

export type MarketplaceSort = (typeof MARKETPLACE_SORTS)[number];

/** Inclusive page-size bounds the backend clamps `limit` into. */
export const MARKETPLACE_LIMIT_MIN = 1;
export const MARKETPLACE_LIMIT_MAX = 100;

/** Default page size the backend applies when the caller omits `limit`. */
export const MARKETPLACE_DEFAULT_LIMIT = 20;

/** Inclusive star bounds enforced by the backend (a value outside is a 400). */
export const RATING_MIN = 1;
export const RATING_MAX = 5;

/**
 * A public marketplace listing from GET /marketplace and GET /marketplace/{id}.
 * `params` is the opaque render-knob snapshot copied at publish time (caption
 * style, target duration, …); `rating_avg` / `rating_count` are the denormalised
 * aggregate maintained on every rating upsert. `viewer_stars` is the caller's own
 * current 1..5 rating when the backend attaches it (0/undefined when unrated).
 * The index signature preserves any forward-compatible fields the backend adds.
 */
export interface MarketplaceTemplate {
  /** Server row id — used in all /marketplace/{id}/* calls. */
  id: string;
  /** The publishing creator's user id (drives the author-only controls). */
  author_user_id: string;
  title: string;
  description: string;
  /** The snapshotted prompt/scaffold used to seed a cloned reel. */
  prompt: string;
  /** Opaque render-knob snapshot copied at publish time. */
  params: Record<string, unknown>;
  /** Discovery tags (searchable). */
  tags: string[];
  /** Persona/content language code (e.g. "en", "tr"). */
  language: string;
  /** Composition layout id (see {@link Layout}). */
  layout: string;
  /** Denormalised mean rating in [0, 5]; 0 when unrated. */
  rating_avg: number;
  /** Total ratings backing `rating_avg`. */
  rating_count: number;
  /** Times this listing has been cloned. */
  clone_count: number;
  /**
   * REMIX TREES: the marketplace listing this one was remixed from, or
   * `null`/undefined for an ORIGINAL publish (the root of a remix tree). Walk it
   * via {@link getMarketplaceLineage} to render a listing's ancestry.
   */
  parent_template_id?: string | null;
  /** REMIX TREES: how many times this listing has been remixed (0 when none). */
  remix_count: number;
  /** Whether the listing is live (unpublishing soft-hides it). */
  published: boolean;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  /** ISO-8601 timestamp of the last update, when available. */
  updated_at?: string | null;
  /** The caller's own current 1..5 rating, when the backend surfaces it. */
  viewer_stars?: number;
  /**
   * The listing's real-world "proven" performance score, attached ONLY on the
   * `sort='proven'` browse. A non-negative number when the listing's clones have
   * downstream performance data, `null`/absent otherwise (and on every other
   * sort). Higher is better.
   */
  win_score?: number | null;
  [key: string]: unknown;
}

/**
 * Query filters for {@link browseMarketplace} (GET /marketplace). Every field is
 * optional; `limit` is clamped to `[MARKETPLACE_LIMIT_MIN, MARKETPLACE_LIMIT_MAX]`
 * and `offset` floored at 0 at the boundary so an untrusted request never
 * triggers an unbounded scan.
 */
export interface MarketplaceBrowseParams {
  /** Free-text search over title/description. */
  query?: string;
  /** Single discovery tag to filter by. */
  tag?: string;
  /** Persona/language code to filter by. */
  language?: string;
  /** Sort order (defaults to `top` server-side). */
  sort?: MarketplaceSort;
  /** Page size (clamped to `[1, 100]`). */
  limit?: number;
  /** Row offset (floored at 0). */
  offset?: number;
}

/**
 * Request body for POST /marketplace/publish. Either reference an existing
 * private template the caller OWNS via `template_id` (snapshotting its config;
 * inline fields override), or omit it and pass the snapshot inline. A resolved
 * `title` is required (an empty title is a 400). The published listing is an
 * IMMUTABLE COPY — later edits to the source private template never mutate it.
 */
export interface PublishTemplateRequest {
  template_id?: string;
  title?: string;
  description?: string;
  prompt?: string;
  params?: Record<string, unknown>;
  tags?: string[];
  language?: string;
  layout?: string;
}

/**
 * The private template created by POST /marketplace/{id}/clone — a new
 * caller-owned template carrying a back-reference to the marketplace listing it
 * was cloned from.
 */
export interface ClonedTemplate {
  /** The new private template's id. */
  id: string;
  /** Its display name (copied from the listing's title). */
  name: string;
  /** The marketplace listing this template was cloned from. */
  source_marketplace_id: string;
}

/** Acknowledgement returned by DELETE /marketplace/{id} (author-only unpublish). */
export interface UnpublishTemplateResult {
  unpublished: boolean;
  id: string;
}

// ---------------------------------------------------------------------------
// Marketplace Remix Trees (GET /marketplace/{id}/lineage) — a listing carries a
// `parent_template_id` back-reference to the listing it was remixed from and a
// `remix_count`; the lineage view walks that chain UP to the root (`ancestors`)
// and lists the DIRECT still-published remixes (`children`). Every entry is a
// safe public {@link MarketplaceTemplate}. Backed by
// app/services/marketplace.py::lineage.
// ---------------------------------------------------------------------------

/**
 * The remix-tree lineage of a marketplace listing from
 * GET /marketplace/{id}/lineage. `ancestors` walks UP the `parent_template_id`
 * chain (immediate parent first → root); `children` are the DIRECT, still-
 * published remixes (newest first). Both are safe public {@link MarketplaceTemplate}
 * rows and are always arrays (empty for an unknown id or a leaf listing).
 */
export interface MarketplaceLineage {
  /** The listing's ancestors, immediate parent first through to the root. */
  ancestors: MarketplaceTemplate[];
  /** The listing's direct, still-published remixes (newest first). */
  children: MarketplaceTemplate[];
}

// ---------------------------------------------------------------------------
// Hook Performance Loop (POST/GET /jobs/{id}/performance, GET /me/performance,
// GET /me/winning-hooks, GET /me/winning-templates) — creators SELF-REPORT the
// real-world outcome (views/likes/comments/shares/saves + watch-through) of a
// reel after posting it. Metrics are aggregated per HOOK and per TEMPLATE into a
// deterministic `win_score` that surfaces the creator's best-performing patterns.
// Strictly caller-scoped: a creator only ever logs metrics for their OWN job and
// only ever reads their OWN aggregates. Fully key-free (no platform API).
// ---------------------------------------------------------------------------

/** Inclusive page-size bounds the backend clamps performance `limit` into. */
export const PERFORMANCE_LIMIT_MIN = 1;
export const PERFORMANCE_LIMIT_MAX = 100;

/** Default page size applied when the caller omits `limit`. */
export const PERFORMANCE_DEFAULT_LIMIT = 20;

/** Inclusive bounds enforced on `retention_pct` (a value outside is a 400). */
export const RETENTION_PCT_MIN = 0;
export const RETENTION_PCT_MAX = 100;

/**
 * The self-reported engagement-count fields of a performance record, in display
 * order. Each is a non-negative integer clamped at the boundary. Kept as a
 * readonly tuple so a form can iterate it while the union narrows the keys.
 */
export const PERFORMANCE_COUNT_FIELDS = [
  "views",
  "likes",
  "comments",
  "shares",
  "saves",
] as const;

export type PerformanceCountField = (typeof PERFORMANCE_COUNT_FIELDS)[number];

/**
 * Request body for POST /jobs/{id}/performance. Every field is optional (an
 * omitted field defaults to 0 / the reel's stored platform server-side). All
 * counts must be non-negative and `retention_pct` must be in `[0, 100]`; the
 * client clamps them at the boundary before sending so an untrusted form value
 * can never reach the API out of range (the backend also rejects with a 400).
 */
export interface LogPerformanceRequest {
  /** Where the reel was posted (e.g. "tiktok", "instagram", "youtube_shorts"). */
  platform?: string;
  /** Non-negative view count. */
  views?: number;
  /** Non-negative like count. */
  likes?: number;
  /** Non-negative comment count. */
  comments?: number;
  /** Non-negative share count. */
  shares?: number;
  /** Non-negative save/bookmark count. */
  saves?: number;
  /** Watch-through / retention percentage in `[0, 100]`. */
  retention_pct?: number;
}

/**
 * A creator's logged performance record for one reel, from
 * POST/GET /jobs/{id}/performance and GET /me/performance. Exactly one row exists
 * per job (re-logging updates it, never duplicates). All numeric fields are
 * non-negative; `retention_pct` is in `[0, 100]`. `logged_at`/`updated_at` are
 * ISO-8601 timestamps (null until the backend surfaces them).
 */
export interface JobPerformance {
  /** Server row id of the performance record. */
  id: string;
  /** The reel this record belongs to (the caller's own job). */
  job_id: string;
  /** Platform the reel was posted to. */
  platform: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  /** Watch-through / retention percentage in `[0, 100]`. */
  retention_pct: number;
  /** ISO-8601 timestamp the metrics were first logged, when available. */
  logged_at: string | null;
  /** ISO-8601 timestamp of the last update, when available. */
  updated_at: string | null;
}

/**
 * One winning HOOK aggregate from GET /me/winning-hooks (top hooks by
 * `win_score`, best first). `win_score` is a deterministic, non-negative score
 * (a hook with 0 logged reels contributes nothing — never NaN/Inf). `reels` is
 * how many logged reels used this hook; `engagements` is the summed
 * likes+comments+shares+saves; `avg_retention_pct` is the mean watch-through in
 * `[0, 100]`.
 */
export interface WinningHook {
  /** The hook / opening line the aggregate is keyed by. */
  hook: string;
  /** Deterministic win score (higher is better; never NaN/Inf). */
  win_score: number;
  /** Number of the caller's logged reels using this hook. */
  reels: number;
  /** Total views across those reels. */
  views: number;
  /** Total engagements (likes + comments + shares + saves) across those reels. */
  engagements: number;
  /** Mean watch-through percentage in `[0, 100]`. */
  avg_retention_pct: number;
}

/**
 * One winning TEMPLATE aggregate from GET /me/winning-templates. Same shape as
 * {@link WinningHook} but keyed by `template` instead of `hook`.
 */
export interface WinningTemplate {
  /** The template the aggregate is keyed by. */
  template: string;
  /** Deterministic win score (higher is better; never NaN/Inf). */
  win_score: number;
  /** Number of the caller's logged reels using this template. */
  reels: number;
  /** Total views across those reels. */
  views: number;
  /** Total engagements (likes + comments + shares + saves) across those reels. */
  engagements: number;
  /** Mean watch-through percentage in `[0, 100]`. */
  avg_retention_pct: number;
}

/** Query options for {@link listMyPerformance} (GET /me/performance). */
export interface ListPerformanceParams {
  /** Page size (clamped to `[PERFORMANCE_LIMIT_MIN, PERFORMANCE_LIMIT_MAX]`). */
  limit?: number;
  /** Row offset (floored at 0). */
  offset?: number;
}

// ---------------------------------------------------------------------------
// Public Watermarked Share Pages (POST /jobs/{id}/share, DELETE /me/shares/{token},
// GET /public/r/{token}) — a creator turns one of THEIR OWN completed reels into a
// public, unguessable, revocable share link; ANYONE (no auth) can view the
// resulting watermarked share page. The owner view carries the reel's own
// bookkeeping; the PUBLIC view is a STRICT safe DTO that NEVER exposes the clean
// (un-watermarked) result key, the owning user id, or any financial. Backed by
// app/services/share.py.
// ---------------------------------------------------------------------------

/**
 * The OWNER-facing share link from POST /jobs/{id}/share. `token` is the
 * unguessable 128-bit public handle; `url` is the built public share-page link
 * (absolute when the backend has a share base URL configured, otherwise a
 * site-relative `/r/{token}`). This owner view is safe to show only to the reel's
 * owner — it carries `job_id`/`view_count`; it is NEVER the shape rendered on the
 * public page (see {@link SharePublic}). The index signature preserves forward-
 * compatible fields the backend may add.
 */
export interface ShareLink {
  /** Unguessable 128-bit public token (the `{token}` in the share URL). */
  token: string;
  /** Built public share-page URL (absolute, or site-relative `/r/{token}`). */
  url: string;
  /** The reel this link shares (the caller's own job). */
  job_id: string;
  /** How many times the public page has been viewed. */
  view_count: number;
  /** Whether the link has been revoked (a revoked link 404s publicly). */
  revoked: boolean;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/**
 * The SAFE, PUBLIC share-page DTO from GET /public/r/{token} (unauthenticated).
 * SECURITY: this is the ONLY share shape exposed to anonymous viewers and is
 * STRICT by design — it carries ONLY the reel's title, a WATERMARKED preview URL,
 * the creation timestamp, and the sharer's referral code. It NEVER carries the
 * clean (un-watermarked) result key, the owning `user_id`, `view_count`, or any
 * financial (credits / cost / revenue). Mirrors the backend's strict
 * `SharePublicModel` (no extra fields).
 */
export interface SharePublic {
  /** The reel's public title / hook. */
  title: string;
  /** Presigned URL of the WATERMARKED preview clip (never the clean result). */
  watermarked_preview_url: string;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  /** The sharer's referral code (so a viewer can attribute a signup). */
  sharer_referral_code: string;
}

/**
 * Acknowledgement from DELETE /me/shares/{token}. `revoked` is `true` only when
 * the caller's OWN live link was flipped; a foreign / unknown / already-revoked
 * token is a harmless no-op `{ revoked: false }` (so a caller can never confirm
 * or revoke another creator's link by guessing its token).
 */
export interface ShareRevokeResult {
  revoked: boolean;
  token: string;
}

// ---------------------------------------------------------------------------
// Creator Profiles + Follow Graph + Leaderboards (GET /creators/leaderboard,
// GET /creators/{handleOrId}, POST/DELETE /creators/{id}/follow, GET /me/following,
// PATCH /me/profile) — public creator identity + a directed follow graph + a
// deterministic reputation leaderboard. Every PUBLIC surface exposes ONLY safe
// fields: the profile/leaderboard shapes NEVER carry credits, email, cost/revenue
// or another user's private data. Backed by app/services/creators.py.
// ---------------------------------------------------------------------------

/**
 * A SAFE, PUBLIC creator profile from GET /creators/{handleOrId}, GET /me/following,
 * and PATCH /me/profile. SECURITY: STRICT — it carries a creator's public identity
 * (handle / display name / bio) plus PUBLIC reputation aggregates, and NEVER their
 * `user_id`, email, credits, or cost/revenue. Mirrors the backend's strict
 * `CreatorProfileModel`.
 */
export interface CreatorProfile {
  /** Public handle slug (e.g. "jane-makes-reels"); may be empty until set. */
  handle: string;
  /** Public display name. */
  display_name: string;
  /** Public bio / tagline. */
  bio: string;
  /** How many templates the creator has published to the marketplace. */
  published_template_count: number;
  /** Total clones their published templates have received. */
  total_clones_received: number;
  /** Mean rating across their published templates, in [0, 5]. */
  avg_rating: number;
  /** How many creators follow them. */
  follower_count: number;
  /** How many creators they follow. */
  following_count: number;
}

/**
 * The follow-state result from POST/DELETE /creators/{id}/follow. `following` is
 * the caller's resulting follow state; `follower_count` is the followee's fresh
 * follower total; `removed` is set only on unfollow (`true` when a row was
 * deleted). The index signature preserves forward-compatible fields.
 */
export interface FollowResult {
  /** Whether the caller now follows the creator. */
  following: boolean;
  /** The followee's follower count after the change. */
  follower_count: number;
  /** Only on unfollow: whether a follow row was actually removed. */
  removed?: boolean | null;
  [key: string]: unknown;
}

/**
 * The metrics the creator leaderboard can be ranked by. `reputation` is the
 * documented composite score (the default); the rest rank by a single aggregate.
 * `win_score` is the gaming-resistant real-world performance anchor. An unknown
 * value normalises to `reputation` server-side.
 */
export const LEADERBOARD_METRICS = [
  "reputation",
  "followers",
  "clones",
  "rating",
  "published",
  "win_score",
] as const;

export type LeaderboardMetric = (typeof LEADERBOARD_METRICS)[number];

/** Default leaderboard metric applied when the caller does not pick one. */
export const LEADERBOARD_DEFAULT_METRIC: LeaderboardMetric = "reputation";

/** Inclusive page-size bounds the backend clamps the leaderboard `limit` into. */
export const LEADERBOARD_LIMIT_MIN = 1;
export const LEADERBOARD_LIMIT_MAX = 100;

/** Default leaderboard page size applied when the caller omits `limit`. */
export const LEADERBOARD_DEFAULT_LIMIT = 20;

/**
 * One ranked creator on GET /creators/leaderboard. Carries the safe profile
 * aggregates plus the deterministic `reputation_score`, the gaming-resistant
 * `win_score` anchor, a 1-based `rank`, and the addressing `user_id` / `handle`.
 * SECURITY: it NEVER exposes credits, email, or cost/revenue (only the
 * addressing `user_id` needed to link to the profile).
 */
export interface LeaderboardEntry {
  /** The creator's user id (addressing only — safe to expose). */
  user_id: string;
  /** Public handle slug. */
  handle: string;
  /** Public display name. */
  display_name: string;
  /** How many templates the creator has published. */
  published_template_count: number;
  /** Total clones their published templates have received. */
  total_clones_received: number;
  /** Mean rating across their published templates, in [0, 5]. */
  avg_rating: number;
  /** How many creators follow them. */
  follower_count: number;
  /** How many creators they follow. */
  following_count: number;
  /** Gaming-resistant real-world performance anchor. */
  win_score: number;
  /** The documented, deterministic composite reputation score. */
  reputation_score: number;
  /** 1-based rank within the leaderboard. */
  rank: number;
}

/** Query options for {@link getLeaderboard} (GET /creators/leaderboard). */
export interface LeaderboardParams {
  /** Metric to rank by (defaults to `reputation`). */
  metric?: LeaderboardMetric;
  /** Page size (clamped to `[LEADERBOARD_LIMIT_MIN, LEADERBOARD_LIMIT_MAX]`). */
  limit?: number;
}

/**
 * Request body for PATCH /me/profile. Every field is optional — only the ones set
 * are updated. `handle` is normalised to a lowercase slug and shape-validated
 * server-side (a bad shape is a 422, a taken handle a 409). All three are safe,
 * public identity fields.
 */
export interface ProfileUpdateRequest {
  /** Public handle slug (3-64 chars, `[a-z0-9]` joined by single `-`/`_`). */
  handle?: string;
  /** Public display name (<= 200 chars). */
  display_name?: string;
  /** Public bio / tagline (<= 2000 chars). */
  bio?: string;
}

// ---------------------------------------------------------------------------
// API envelope
// ---------------------------------------------------------------------------

/** Standard backend response envelope: `utils.get_response(status, data, message)`. */
export interface ApiEnvelope<T> {
  status: number;
  message?: string;
  data?: T;
}

// ---------------------------------------------------------------------------
// ENTERPRISE — Access & Governance (Epic 1): RBAC, audit trail, platform-admin
//
// The Enterprise access layer built on the pycasbin enforcer server-side. Every
// workspace-scoped read/write verifies the caller is a member with a sufficient
// role; the audit trail is APPEND-ONLY; platform-admin (`is_staff`) is a
// SEPARATE, hard-gated cross-tenant surface. These types mirror the responses of
// `app/controllers/v1/{rbac,audit,admin}.py`.
// ---------------------------------------------------------------------------

/**
 * A single Enterprise permission string, as granted by the pycasbin enforcer
 * (`app/services/rbac.py`). Widened with `string` so an unrecognised future
 * permission surfaced by `GET /me/permissions` still renders instead of failing
 * to type-check; validate against {@link getMyPermissions} at the boundary.
 */
export type Permission =
  | "jobs.create"
  | "jobs.read"
  | "members.manage"
  | "billing.manage"
  | "workspace.settings"
  | "audit.read"
  | "admin.access"
  | (string & {});

/** Every permission the client knows about, in a stable display order. */
export const PERMISSIONS: readonly Permission[] = [
  "jobs.read",
  "jobs.create",
  "members.manage",
  "billing.manage",
  "workspace.settings",
  "audit.read",
  "admin.access",
];

/**
 * The Enterprise roles a manager may assign, in DESCENDING privilege order (used
 * to render role pickers). Mirrors `app/services/rbac.py::ROLES`. The legacy
 * `member` role is intentionally excluded — it is tolerated on read but never
 * offered as an assignment target.
 */
export const ENTERPRISE_ROLES = [
  "owner",
  "admin",
  "editor",
  "billing",
  "viewer",
] as const;

export type EnterpriseRole = (typeof ENTERPRISE_ROLES)[number];

/**
 * Relative rank of each role, mirroring the backend's `_ROLE_RANK`
 * (`owner=4 > admin=3 > {editor,billing}=2 > viewer=1`; unknown/legacy = 0).
 * Used only for UI affordances — the server independently enforces every rule
 * (a caller may not grant a role above their own; the last owner cannot be
 * demoted).
 */
export const ROLE_RANK: Readonly<Record<string, number>> = {
  viewer: 1,
  editor: 2,
  billing: 2,
  admin: 3,
  owner: 4,
};

/** Numeric rank of a role for the "cannot grant above your own" UI guard. */
export function roleRank(role: WorkspaceRole | null | undefined): number {
  return role ? (ROLE_RANK[role] ?? 0) : 0;
}

/**
 * Client-side mirror of the enforcer for UI gating ONLY (the server is always
 * the source of truth). True when the role can manage members + change roles.
 */
export function canManageMembers(role: WorkspaceRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

/** Client-side mirror of the enforcer: true when the role can read the audit trail. */
export function canReadAudit(role: WorkspaceRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

/**
 * The caller's effective permissions in a workspace, from
 * `GET /me/permissions?workspace_id=`. A non-member yields `role: null` and an
 * empty `permissions` array (never another tenant's data).
 */
export interface Permissions {
  workspace_id: string;
  role: WorkspaceRole | null;
  permissions: Permission[];
}

/**
 * A single APPEND-ONLY audit-trail row from
 * `GET /me/workspaces/{id}/audit`. `action` is a stable event slug (e.g.
 * `members.role_changed`, `admin.impersonated`); `metadata` is an opaque,
 * non-sensitive event map (e.g. `{ old_role, new_role }`). Strictly
 * tenant-scoped: only rows for the requested workspace are ever returned.
 */
export interface AuditEntry {
  id: number;
  /** Owning workspace (null only for platform-level rows). */
  workspace_id: string | null;
  /** The user who performed the action. */
  actor_user_id: string;
  /** Stable event slug, e.g. `members.role_changed`. */
  action: string;
  /** Type of the affected entity, e.g. `user`. */
  target_type: string | null;
  /** Id of the affected entity. */
  target_id: string | null;
  /** Opaque, non-sensitive event detail. Read fields defensively. */
  metadata: Record<string, unknown>;
  /** Best-effort source IP of the actor, when captured. */
  ip: string | null;
  /** ISO-8601 timestamp the row was recorded, when available. */
  created_at: string | null;
}

/** Query params for {@link listAuditLog} (page window; clamped server-side). */
export interface AuditLogParams {
  /** Page size (backend clamps to `[1, 100]`; default 50). */
  limit?: number;
  /** Row offset (backend floors at 0). */
  offset?: number;
}

/**
 * A cross-tenant user row from the platform-admin listing
 * (`GET /admin/users`, staff-only). `is_staff` marks a platform administrator
 * (separate from any workspace role).
 */
export interface AdminUser {
  id: string;
  email: string | null;
  display_name: string | null;
  is_staff: boolean;
  credits: number;
  created_at: string | null;
}

/** A cross-tenant workspace row from `GET /admin/workspaces` (staff-only). */
export interface AdminWorkspace {
  id: string;
  name: string | null;
  owner_id: string;
  created_at: string | null;
}

/** A cross-tenant job row from `GET /admin/jobs` (staff-only). */
export interface AdminJob {
  id: string;
  user_id: string;
  kind: string | null;
  /** Integer job state (see {@link JobState}); may be null for legacy rows. */
  state: number | null;
  progress: number | null;
  created_at: string | null;
}

/** Query params for the admin list endpoints (page window; clamped 1..200 / >=0). */
export interface AdminListParams {
  limit?: number;
  offset?: number;
}

/**
 * A minted, time-boxed impersonation grant from `POST /admin/impersonate`
 * (staff-only, audited as `admin.impersonated`). `token` is short-lived and
 * scoped; `expires_in` is its remaining lifetime in seconds.
 */
export interface Impersonation {
  token: string;
  admin_user_id: string;
  target_user_id: string;
  scope: string;
  issued_at: string | null;
  expires_at: string | null;
  expires_in: number;
}

// ---------------------------------------------------------------------------
// ENTERPRISE — Identity & SSO (Epic 2): a workspace's SAML/OIDC connection,
// SCIM 2.0 provisioning tokens, and login security policy. Every workspace-scoped
// read/write is gated by `workspace.settings` (owner/admin) and strictly
// tenant-scoped server-side. SECRETS ARE WRITE-ONLY: the IdP signing certificate
// and OIDC client secret are never returned by any read — only the booleans
// `has_certificate` / `has_client_secret` report whether one is configured, and a
// SCIM token's raw value is present ONLY in the one-time mint response.
// ---------------------------------------------------------------------------

/** The Enterprise SSO protocols a workspace connection may use. */
export type SsoProtocol = "saml" | "oidc";

/**
 * CERT-FREE public view of a workspace's SSO connection (from
 * `GET/PUT /me/workspaces/{id}/sso`). The IdP signing certificate and OIDC
 * client secret are NEVER included — `has_certificate` / `has_client_secret`
 * only report whether one is configured. `protocol` is widened with `string` so
 * an unrecognised future protocol still renders instead of failing to type-check.
 */
export interface SSOConnection {
  workspace_id: string;
  protocol: SsoProtocol | (string & {});
  idp_entity_id: string;
  idp_sso_url: string;
  /** SP AssertionConsumerService URL to give the IdP (never a secret). */
  sp_acs_url: string;
  /** SP metadata URL to give the IdP (may be blank; derivable from the API base). */
  sp_metadata_url: string;
  oidc_client_id?: string | null;
  enabled: boolean;
  /** True when an IdP signing certificate is stored (the cert itself is never returned). */
  has_certificate: boolean;
  /** True when an OIDC client secret is stored (the secret itself is never returned). */
  has_client_secret: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * Body for `PUT /me/workspaces/{id}/sso` — configure the IdP connection.
 * `idp_x509_cert` (SAML signing cert) and `oidc_client_secret` are WRITE-ONLY:
 * they are encrypted at the service boundary and never returned by any read. Send
 * a secret field only when setting/rotating it; omit it to leave the stored value
 * unchanged.
 */
export interface SSOConfigRequest {
  protocol: SsoProtocol | (string & {});
  idp_entity_id?: string;
  idp_sso_url?: string;
  /** WRITE-ONLY SAML signing certificate (PEM). Never returned by any read. */
  idp_x509_cert?: string;
  sp_acs_url?: string;
  oidc_client_id?: string;
  /** WRITE-ONLY OIDC client secret. Never returned by any read. */
  oidc_client_secret?: string;
  enabled?: boolean;
}

/**
 * The SP (service-provider) SAML metadata descriptor for a workspace (from
 * `GET /sso/{id}/metadata`, also served raw as `application/samlmetadata+xml`).
 * Public by design — an IdP admin consumes it to wire the connection. No secret
 * is ever included.
 */
export interface SSOMetadata {
  workspace_id: string;
  entity_id: string;
  acs_url: string;
  metadata_xml: string;
}

/**
 * The ReelForge session grant issued by `POST /sso/{id}/acs` after a VALIDATED
 * SAML assertion. `session_token` is an opaque bearer credential minted only from
 * a validated grant (any validation failure mints nothing). This is IdP-facing —
 * the browser is redirected through the ACS endpoint; the app clients never call
 * it directly. Included for completeness of the SSO contract.
 */
export interface SSOSession {
  session_token: string;
  token_type: string;
  user_id: string;
  workspace_id: string;
  email: string;
  role: string;
  is_new_user: boolean;
}

/**
 * A workspace's SCIM bearer-token descriptor (from
 * `GET/POST /me/workspaces/{id}/scim/tokens`). The raw `token` is present ONLY in
 * the one-time mint response — a listing carries `token: null` and only the
 * non-secret `prefix`. The token authenticates an IdP's SCIM 2.0 provisioning
 * calls and is scoped to this workspace alone.
 */
export interface ScimToken {
  id: string;
  workspace_id: string;
  /** Short, non-secret leading fragment (safe to display in a listing). */
  prefix: string;
  /** The FULL raw bearer token — present ONCE at mint, unrecoverable afterwards. */
  token?: string | null;
  revoked: boolean;
  last_used_at?: string | null;
  created_at?: string | null;
}

/**
 * A workspace's enterprise login security policy (from
 * `GET/PUT /me/workspaces/{id}/security`). Cert-free and secret-free.
 * `session_timeout_min` of 0 means "no enforced timeout"; empty
 * `allowed_email_domains` / `ip_allowlist` mean "no restriction".
 */
export interface SecurityPolicy {
  workspace_id: string;
  require_sso: boolean;
  session_timeout_min: number;
  allowed_email_domains: string[];
  mfa_required: boolean;
  ip_allowlist: string[];
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * Body for `PUT /me/workspaces/{id}/security` — a PARTIAL policy update. Every
 * field is optional; only supplied (non-`undefined`) fields are applied, so a
 * single rule can be toggled without resending the whole policy.
 */
export interface SecurityPolicyRequest {
  require_sso?: boolean;
  session_timeout_min?: number;
  allowed_email_domains?: string[];
  mfa_required?: boolean;
  ip_allowlist?: string[];
}

// ---------------------------------------------------------------------------
// ENTERPRISE — Billing Platform (Epic 3): a workspace's subscription, metered
// usage + plan entitlements, invoices, and the platform revenue summary. The
// management + read surfaces are tenant-scoped server-side; MONEY is always an
// INTEGER minor unit (cents) — never a float. The subscription/usage/invoice
// reads are workspace-scoped (a caller can never see another tenant's rows); the
// revenue summary is served ONLY behind the platform `is_staff` gate.
// ---------------------------------------------------------------------------

/** Subscription lifecycle status. Only `active`/`trialing` grant the plan. */
export type SubscriptionStatus =
  | "active"
  | "past_due"
  | "canceled"
  | "trialing";

/** Billing cadence for a workspace subscription. */
export type SubscriptionInterval = "month" | "year";

/** The billing plan keys (mirror `app.services.entitlements.PLAN_ENTITLEMENTS`). */
export type PlanKey = "free" | "starter" | "pro" | "enterprise";

/**
 * A workspace's billing subscription (from `GET /me/workspaces/{id}/subscription`;
 * `null` when unset -> the workspace resolves to base/free entitlements). Secret-
 * free: `provider_ref` is the provider-side id (e.g. the Stripe subscription id),
 * never a secret. `status`/`plan_key`/`interval` are widened with `string` for
 * forward-compat.
 */
export interface Subscription {
  workspace_id: string;
  plan_key: PlanKey | (string & {});
  provider: string;
  provider_ref: string;
  status: SubscriptionStatus | (string & {});
  interval: SubscriptionInterval | (string & {});
  seats: number;
  current_period_end: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Payment rails that sell recurring workspace plans (iyzico has no recurring API). */
export type SubscriptionProvider = "stripe" | "creem" | "polar";

/** Body for `POST /me/workspaces/{id}/subscribe` — start a recurring checkout. */
export interface SubscribeRequest {
  plan_key: string;
  interval?: SubscriptionInterval;
  /** Seats recorded on the subscription (1..the plan's `max_seats`). */
  seats?: number;
  /** A rail listed for this plan + interval by `GET /billing/workspace-plans`. */
  provider?: SubscriptionProvider;
}

/**
 * One self-serve workspace plan from `GET /billing/workspace-plans`: live
 * prices (integer cents), the monthly credit allotment, the included seats, and
 * — per billing interval — the payment rails configured to sell it (an empty
 * list means the plan cannot be bought at that interval right now).
 */
export interface WorkspacePlanOffer {
  plan_key: string;
  name: string;
  rank: number;
  monthly_cents: number;
  yearly_cents: number;
  currency: string;
  monthly_credits: number;
  max_seats: number;
  providers: Record<SubscriptionInterval, SubscriptionProvider[]>;
}

/**
 * Hosted-checkout envelope returned by `subscribe`. `checkout_url` is the Stripe
 * hosted payment page the client redirects the buyer to; credits/entitlements are
 * granted only on webhook confirmation, never here.
 */
export interface SubscribeResult {
  checkout_url: string;
  provider?: string;
  plan_key?: string;
  workspace_id?: string | null;
  [key: string]: unknown;
}

/** Body for `POST /me/workspaces/{id}/change-plan`. */
export interface ChangePlanRequest {
  plan_key: string;
}

/**
 * The caller's active-plan entitlement bundle for a workspace (from
 * `GET /me/workspaces/{id}/entitlements`). `entitlements` maps a feature key to
 * its value — numeric limits (`max_variants`, `seats`, `monthly_credits`) and
 * boolean capabilities (`sso`, `api_access`, `priority_render`,
 * `watermark_removal`). A workspace with no live subscription resolves to `free`.
 */
export interface Entitlements {
  workspace_id: string;
  plan_key: PlanKey | (string & {});
  entitlements: Record<string, number | boolean | string>;
}

/** Per-metric usage vs plan limit for a period (integer units). */
export interface MetricOverage {
  metric: string;
  used: number;
  /** `null` when the metric is unbounded for the plan. */
  limit: number | null;
  /** `max(0, used - limit)` — 0 when within allotment or unbounded. */
  overage: number;
}

/**
 * A workspace's metered usage + overage for a billing month (from
 * `GET /me/workspaces/{id}/usage?period=YYYY-MM`). Tenant-scoped: never another
 * tenant's rows. `usage` is the per-metric `{metric: total}` aggregate.
 */
export interface Usage {
  workspace_id: string;
  period: string;
  usage: Record<string, number>;
  overage: MetricOverage[];
}

/** One line on an invoice (integer minor-unit amount). */
export interface InvoiceLineItem {
  id: string;
  description: string;
  quantity: number;
  amount_cents: number;
  created_at: string | null;
}

/**
 * A workspace's invoice (from `GET /me/workspaces/{id}/invoices`). `amount_cents`
 * is the exact integer sum of the lines in `currency` — never a float. `status`
 * is one of `draft | open | paid | void`.
 */
export interface Invoice {
  id: string;
  workspace_id: string;
  provider_ref: string;
  amount_cents: number;
  currency: string;
  status: "draft" | "open" | "paid" | "void" | (string & {});
  period_start: string | null;
  period_end: string | null;
  created_at: string | null;
  line_items: InvoiceLineItem[];
}

/**
 * Platform revenue summary (from `GET /admin/revenue`; `is_staff` ONLY).
 * `revenue_cents` is realized (`paid`) revenue across ALL tenants; `net_cents`
 * mirrors it; `credits_granted` is the outstanding liability side.
 */
export interface Revenue {
  revenue_cents: number;
  credits_granted: number;
  net_cents: number;
}

// ---------------------------------------------------------------------------
// ENTERPRISE — API Platform (Epic 4): webhook SUBSCRIPTIONS + developer portal.
// A workspace registers a callback `url` + the `event_types` it wants pushed;
// each delivery rides the EXISTING hardened, HMAC-signed, SSRF-guarded delivery
// primitive server-side. SECURITY INVARIANTS mirrored in these shapes:
//   * The HMAC signing `secret` is present ONLY on the one-time create reveal
//     ({@link CreatedWebhookSubscription}) — NEVER on a list/get/delivery shape.
//   * A subscription `url` is SSRF-validated server-side before any row exists
//     (a loopback/private/link-local/metadata target is a 400 at the boundary).
//   * Every shape is workspace/tenant-scoped — a row never carries another
//     tenant's data.
// ---------------------------------------------------------------------------

/**
 * The catalog of event types a subscription may listen for (mirrors the backend
 * `WEBHOOK_EVENT_TYPES`). `job.completed` fires when a render job finishes;
 * `job.failed` when it fails for good (the body says whether it was refunded);
 * `publish.succeeded` / `publish.failed` when a direct-publish attempt resolves;
 * `performance.ingested` when a self-reported performance datapoint is logged. A
 * subscribe request whose `event_types` are not a subset of this set is a clean
 * 400 at the boundary.
 */
export const WEBHOOK_EVENT_TYPES = [
  "job.completed",
  "job.failed",
  "publish.succeeded",
  "publish.failed",
  "performance.ingested",
] as const;

/** One of the supported webhook event types (see {@link WEBHOOK_EVENT_TYPES}). */
export type WebhookEventType = (typeof WEBHOOK_EVENT_TYPES)[number];

/**
 * A webhook subscription in its public, SECRET-FREE shape (from
 * `GET /me/workspaces/{id}/webhooks`). NEVER carries the signing secret
 * (plaintext or encrypted) — only the id, owning `workspace_id`, callback `url`,
 * subscribed `event_types`, the `enabled` kill-switch, and lifecycle timestamps.
 * The plaintext signing secret is only ever available once, at create time (see
 * {@link CreatedWebhookSubscription}).
 */
export interface WebhookSubscription {
  id: string;
  workspace_id: string;
  /** Customer callback URL (https) — SSRF-validated server-side at create time. */
  url: string;
  /** The event types this subscription receives. */
  event_types: string[];
  /** The kill-switch; a disabled subscription receives no deliveries. */
  enabled: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * The ONE-TIME reveal returned by `POST /me/workspaces/{id}/webhooks`. SECURITY:
 * `secret` is the subscription's HMAC signing key and is present ONLY here,
 * exactly once, at creation. The server persists it only as an encrypted blob,
 * so the plaintext is UNRECOVERABLE afterwards — a lost secret means the
 * subscription must be deleted and re-created. Every subsequent list/get shape
 * is the secret-free {@link WebhookSubscription}.
 */
export interface CreatedWebhookSubscription extends WebhookSubscription {
  /**
   * The HMAC signing secret — shown ONCE and unrecoverable. Verify the
   * Standard Webhooks `webhook-id` / `webhook-timestamp` / `webhook-signature`
   * headers on each delivery with it (key = the secret's raw UTF-8 bytes; the
   * body-only `X-Menivor-Signature: sha256=<hexdigest>` and the older
   * `X-ReelForge-Signature` are still sent but deprecated).
   * Store it securely; the server keeps only an encrypted blob.
   */
  secret: string;
}

/**
 * Request body for `POST /me/workspaces/{id}/webhooks`. `url` is the customer
 * callback endpoint (https), validated through the SAME SSRF guard the delivery
 * primitive uses before any row is persisted. `event_types` must be a non-empty
 * subset of {@link WEBHOOK_EVENT_TYPES}. The signing secret is minted
 * server-side (never client-supplied).
 */
export interface WebhookSubscribeRequest {
  url: string;
  event_types: string[];
}

/**
 * One delivery attempt-record of an event to a subscription (from
 * `GET /me/workspaces/{id}/webhooks/{sub}/deliveries`, and returned by the test
 * endpoint). SECRET-FREE and payload-free: only delivery metadata is exposed.
 * `status` is one of `pending | delivered | dead` (`failed` on rows written
 * before MN8); `dead` means every retry was spent; `attempts` /
 * `last_attempt_at` / `response_code` reflect the capped-backoff retry state.
 */
export interface WebhookDelivery {
  id: string;
  subscription_id: string;
  event_type: string;
  /** The idempotency id of the delivered event (dedupe key). */
  event_id: string;
  status: "pending" | "delivered" | "dead" | "failed" | (string & {});
  attempts: number;
  last_attempt_at?: string | null;
  /** HTTP status returned by the customer endpoint on the last attempt, if any. */
  response_code?: number | null;
  created_at?: string | null;
}

/**
 * The caller's API-key footprint for the developer portal (SECRET-FREE). Counts
 * only — never a raw key or hash. `requests_this_month` is the sum of the
 * current calendar month's request usage across all the caller's keys.
 */
export interface DeveloperApiKeysSummary {
  total: number;
  active: number;
  period_ym: string;
  requests_this_month: number;
}

/**
 * The caller's webhook-subscription footprint across their workspaces
 * (tenant-scoped per workspace). `active` counts only enabled subscriptions.
 */
export interface DeveloperWebhooksSummary {
  total: number;
  active: number;
  event_types: string[];
}

/**
 * The caller-scoped developer portal summary (from `GET /me/developer`). A
 * READ-only view: the caller's API-key + webhook footprints, the number of
 * workspaces they belong to, and static integration metadata (base URL,
 * OpenAPI/docs links, API version, supported webhook events). NEVER a secret.
 */
export interface DeveloperPortal {
  api_keys: DeveloperApiKeysSummary;
  webhooks: DeveloperWebhooksSummary;
  workspaces: number;
  /** The API base URL every v1 route is mounted under (e.g. `.../api/v1`). */
  api_base_url: string;
  /** Absolute URL of the machine-readable OpenAPI schema. */
  openapi_url: string;
  /** Absolute URL of the interactive API docs. */
  docs_url: string;
  api_version: string;
  webhook_event_types: string[];
}

// ---------------------------------------------------------------------------
// ENTERPRISE — Compliance (Epic 5): GDPR/SOC2 data governance. A caller can
// EXPORT all of their own data (Art. 15/20), request ERASURE of their own
// account (Art. 17, PII anonymized in place — financial/audit records kept),
// record CONSENT decisions, and (owner/admin) set a workspace's data-RETENTION
// window. Every read/write is strictly scoped to the requesting caller (or a
// workspace they are `workspace.settings`-permitted to configure) server-side —
// no path can ever touch another user's data. The platform-admin (`is_staff`)
// surface adds a cross-tenant erasure-request + retention overview.
// ---------------------------------------------------------------------------

/**
 * A short-lived, self-service data export (from `POST /me/data-export`, GDPR
 * Art. 15/20). `download_url` is a presigned GET link to the caller's OWN export
 * archive (a private R2 object — never public); `expires_in` is its lifetime in
 * seconds. The archive contains only the requesting caller's data.
 */
export interface DataExport {
  download_url: string;
  expires_in: number;
}

/** Lifecycle of a right-to-erasure request (`requested -> processing -> completed`). */
export type ErasureStatus =
  | "requested"
  | "processing"
  | "completed"
  | (string & {});

/**
 * A right-to-erasure request's public shape (GDPR Art. 17), from
 * `POST /me/erase` (the caller's own) or the platform-admin listing. Erasure
 * ANONYMIZES PII in place (email/name/handle tombstoned, credentials revoked,
 * job scripts/prompts blanked) while PRESERVING legally-required financial/audit
 * records — it never cascade-deletes. `scope` records what was erased.
 */
export interface ErasureRequest {
  id: string;
  user_id: string;
  status: ErasureStatus;
  scope: string;
  requested_at: string | null;
  completed_at: string | null;
}

/**
 * A consent dimension. `tos`, `marketing` and `ai_disclosure` are the known
 * kinds; widened with `string` so a future dimension still type-checks.
 */
export type ConsentKind =
  | "tos"
  | "marketing"
  | "ai_disclosure"
  | (string & {});

/**
 * One append-only consent decision (GDPR/SOC2 consent capture) from
 * `GET/PUT /me/consent`. Records that the caller GRANTED or withdrew consent for
 * a `kind` at a policy `version`. Strictly caller-scoped — a decision is always
 * for the requesting caller, never another user.
 */
export interface ConsentRecord {
  id: number | null;
  kind: ConsentKind;
  granted: boolean;
  version: string;
  created_at: string | null;
}

/** Body for `PUT /me/consent` — record a consent decision for the caller. */
export interface ConsentUpdateRequest {
  kind: ConsentKind;
  granted: boolean;
  version?: string;
}

/**
 * A workspace's data-retention window (from `GET/PUT
 * /me/workspaces/{id}/retention`). `jobs_retention_days` / `assets_retention_days`
 * bound how long a workspace's jobs / assets are kept before the periodic sweep
 * anonymizes the aged rows; `null` means KEEP FOREVER (that dimension is never
 * swept). Reading/writing is gated on `workspace.settings` (owner/admin).
 */
export interface RetentionPolicy {
  workspace_id: string;
  jobs_retention_days: number | null;
  assets_retention_days: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/**
 * Body for `PUT /me/workspaces/{id}/retention` — a full replace of both windows.
 * `null` (or omitted) means KEEP FOREVER for that dimension; a negative value is
 * rejected server-side (400).
 */
export interface RetentionUpdateRequest {
  jobs_retention_days: number | null;
  assets_retention_days: number | null;
}

// ---------------------------------------------------------------------------
// Background-footage library (GET /templates/backgrounds) + launch status
// ---------------------------------------------------------------------------

/**
 * A curated loop-able background clip (gameplay parkour, satisfying ASMR, …)
 * from GET /templates/backgrounds. Its `id` is sent as `params.background_id`
 * on a job with no screen recording — the backend materializes it into a
 * looping companion track sized to the narration (the avatar-less
 * `captions_only` quick-create path). `available: false` marks clips whose
 * first-party asset is not staged yet; keep them visible but unselectable.
 */
export interface BackgroundClip {
  id: string;
  category: string;
  label: string;
  source: string;
  provider: string;
  loopable: boolean;
  license_note: string;
  available: boolean;
}

/**
 * GET /launch/status — the server-owned, non-sensitive launch gates. While a
 * feature is `false` the API hard-rejects the corresponding mutation, so the
 * UI renders a friendly "opens soon" state instead of wiring a dead call
 * (e.g. `features.checkout` gates the wallet purchase buttons).
 */
/**
 * `payments` block of GET /launch/status: which merchant of record takes new
 * payments (`none` = paid plans paused; every account gets
 * `free_monthly_reels` free reels a month instead).
 */
export interface PaymentsMode {
  paused: boolean;
  provider: "creem" | "dodo" | "paddle" | "none";
  free_monthly_reels: number;
}

export interface LaunchStatus {
  mode: string;
  public_access: boolean;
  payments?: PaymentsMode;
  features: {
    signup: boolean;
    checkout: boolean;
    publishing: boolean;
    [key: string]: boolean;
  };
}
