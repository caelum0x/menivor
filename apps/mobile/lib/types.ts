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
  REEL_LAYOUTS,
  isFailedJobState,
  isTerminalJobState,
  type ReelAspect,
  type ReelAvatarProvider,
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
  PresignUploadInput,
  PresignUploadResult,
} from "@reelforge/api-contract";

export { JobState, type JobStateValue };

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
  correlation_id?: string;
  retry_eligible?: boolean;
  /** R2 key for the generated poster/thumbnail image, when available. */
  poster_key?: string;
  /** R2 key for a short preview clip, when available. */
  preview_key?: string;
  /**
   * R2 key (or already-presigned URL) for the creator-generated cover /
   * thumbnail image (HOOK headline over the poster frame). Set by
   * POST /jobs/{id}/cover and regenerable with a new headline/style.
   */
  cover_key?: string;
  /** Creator-facing reel name set via PATCH /jobs/{id}; absent until renamed. */
  title?: string | null;
  /** True once the reel was archived (hidden from the default library view). */
  archived?: boolean;
  /** True when the creator cancelled the reel before it finished rendering. */
  cancelled?: boolean;
}

/** Body for PATCH /jobs/{id} — only supplied fields change. */
export interface JobUpdateRequest {
  title?: string | null;
  archived?: boolean;
}

/**
 * Result of POST /jobs/{id}/cancel — the terminal job snapshot plus the
 * credits released back to the caller's balance (unspent held credits).
 */
export interface JobCancelResult extends Job {
  refunded_credits?: number;
}

/** Result of DELETE /jobs/{id}. */
export interface JobDeleteResult {
  job_id: string;
  deleted: boolean;
  refunded_credits?: number;
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
  /** Shared batch id of a multi-variant create (the winner-loop project id). */
  batch_id?: string;
  /**
   * Per-variant opening-hook angle (`pov`, `question`, `nobody_tells_you`,
   * `stat`, `story`), index-aligned with `job_ids`. Present when the API
   * rotated hook styles across the variants.
   */
  hook_styles?: string[];
}

/** A curated looping background clip from GET /templates/backgrounds. */
export interface BackgroundClip {
  id: string;
  category: string;
  label: string;
  source: string;
  provider: string;
  loopable: boolean;
  license_note: string;
  /** False when the clip is catalogued but its file is not on this server. */
  available: boolean;
}

/** Submittable reel draft written from an ingested page. */
export interface ReelDraft {
  video_subject: string;
  hook: string;
  video_script: string;
  broll_prompts: string[];
}

/** Result of POST /ingest/url: extracted page content plus a reel draft. */
export interface UrlIngestResult {
  url: string;
  content: { title: string; description: string; features: string[] };
  reel_draft: ReelDraft;
}

// ---------------------------------------------------------------------------
// ReelForge params (POST /jobs body)
// ---------------------------------------------------------------------------

export type Layout = ReelLayout;
export type Aspect = ReelAspect;
export type Language = ReelLanguage;
export type AvatarProvider = ReelAvatarProvider;

/** Selectable layouts for the layout picker, in display order. */
export const LAYOUTS = REEL_LAYOUTS;

/**
 * Scene-driven camera-motion preset applied to the SCREEN RECORDING pre-compose
 * (mirrors the backend `_CAMERA_MOTION_PRESETS` enum). `"none"` disables the
 * pass. The server validates + lowercases this at the request boundary and
 * rejects any other value with 422; the pass is duration-preserving and
 * degrade-safe (a failure returns the original clip unchanged).
 */
export type CameraMotion = ReelCameraMotion;

/** The selectable camera-motion presets, in display order (`"none"` = off). */
export const CAMERA_MOTIONS = REEL_CAMERA_MOTIONS;

/** Human-readable labels for each camera-motion preset, for a motion picker. */
export const CAMERA_MOTION_LABELS: Readonly<Record<CameraMotion, string>> = {
  none: "None",
  ken_burns: "Ken Burns",
  push_in: "Push in",
  pull_out: "Pull out",
  whip_pan: "Whip pan",
};

/** Column-default camera motion (mirrors `ReelForgeParams.camera_motion`). */
export const DEFAULT_CAMERA_MOTION: CameraMotion = "none";

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
  /**
   * BRING YOUR OWN VOICEOVER (BYOV): R2 key (from the presign upload flow) of a
   * narration audio the creator recorded/picked themselves. When set, this
   * uploaded audio becomes the reel's narration INSTEAD of TTS / a voice clone:
   * the backend transcribes it with faster-whisper (app/services/subtitle.py) so
   * the whisper WORD timings drive the ASS karaoke captions AND the same audio
   * drives the HeyGen avatar lip-sync + duration — the §8 timing single source of
   * truth is preserved. Omit for the default TTS narration (then `voice_name` /
   * `voice_id` select the narrator).
   */
  voiceover_key?: string;
}

/** Request body for POST /jobs. */
export interface JobCreateRequest extends ReelJobCreateInput {
  params: ReelForgeParams;
  /** Attribution carried from discovery → render → publish analytics. */
  source_kind?: "trend";
  source_id?: string;
  source_label?: string;
  forecast_id?: string;
  avatar_id?: string;
  voice_id?: string;
  /**
   * Optional workspace to charge instead of the caller's personal credits. When
   * present, the backend debits the workspace's SHARED credit pool (the caller
   * must be a member; a non-member yields 403, an empty pool 402). Omit for the
   * normal per-user credit flow. See {@link Workspace} and getWorkspaceCredits.
   */
  workspace_id?: string;
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
   * AI background-music brief. When non-empty the backend generates a custom
   * royalty-free BGM track from this prompt (via the vendored MPT providers) and
   * feeds it to compose as the ducked music bed. Mutually exclusive with
   * `music_id` — send one or the other, not both.
   */
  music_prompt?: string;
  /**
   * AI-BGM provider id (from GET /catalog/music-generators). Omit or send `""`
   * to let the backend auto-select the first enabled provider. Only meaningful
   * alongside `music_prompt`. See {@link MusicGenerator}.
   */
  bgm_provider?: string;
  /** Optional webhook URL notified when the job reaches a terminal state. */
  webhook_url?: string;
  /** Per-job ToS / AI-disclosure acknowledgement, coerced to a bool server-side. */
  tos_disclosure?: boolean;
  /**
   * OPTIONAL stock B-roll cutaway spliced as a brief MUTED intro BEFORE the
   * hook. The value is a {@link BrollClip.key} from POST /jobs/{id}/broll/suggest
   * (MPT's vendored Pexels/Pixabay path). The main reel keeps its full audio +
   * captions; omit for no intro cutaway.
   */
  broll_intro_key?: string;
  /**
   * OPTIONAL stock B-roll cutaway spliced as a brief MUTED outro AFTER the
   * composed reel. The value is a {@link BrollClip.key} from
   * POST /jobs/{id}/broll/suggest; omit for no outro cutaway.
   */
  broll_outro_key?: string;
  /**
   * Opt-in dead-air auto-cut. When true, the raw SCREEN RECORDING is
   * pre-processed to remove silent audio gaps and static/low-motion stretches
   * BEFORE compose (Submagic "Remove Silences" retention feature). The
   * voiceover + caption timeline is never touched, so caption drift is
   * unaffected. Degrade-safe: returns the original clip when nothing is
   * removable. Persisted in `Job.params` JSON. Defaults to false server-side.
   */
  auto_tighten?: boolean;
  /**
   * Opt-in scene-driven punch-in zoom. When true, the SCREEN RECORDING is
   * pre-processed (before compose) with an auto-zoom pass that eases into a
   * subtle punch-in on detected scene changes. The voiceover + caption timeline
   * is never touched (the pass is duration-preserving) so caption drift is
   * unaffected. Degrade-safe (returns the original clip on any failure or when
   * the optional PySceneDetect dep is absent) and persisted in `Job.params`
   * JSON. Defaults to false server-side.
   */
  auto_zoom?: boolean;
  /**
   * Opt-in camera-motion preset applied to the SCREEN RECORDING pre-compose
   * (one of {@link CAMERA_MOTIONS}). `"none"` (or omitted) disables the pass.
   * The pass is duration-preserving so the voiceover + caption timeline is
   * untouched, and degrade-safe (returns the original clip on any failure). The
   * server validates + lowercases the value and rejects any other with 422.
   * Persisted in `Job.params` JSON. Defaults to `"none"` server-side.
   */
  camera_motion?: CameraMotion;
  /**
   * Opt-in neural background matting of the AVATAR. When true, the avatar clip's
   * background is removed (rembg) and replaced with a spill-free key colour that
   * compose's existing chromakey drops, so the avatar composites cleanly over
   * the reel. Never touches the voiceover/caption timeline. Degrade-safe
   * (returns the original clip on any failure or when the optional rembg dep is
   * absent) and persisted in `Job.params` JSON. Defaults to false server-side.
   */
  remove_bg?: boolean;
}

/** Backend hard cap on batch variant fan-out (`_MAX_VARIANTS`). */
export const MAX_JOB_VARIANTS = MAX_REEL_JOB_VARIANTS;

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
 * Where a GET /avatars entry came from: a persisted `AvatarPreset` row
 * (`preset` — includes a creator's custom photo→avatar) or the live provider
 * catalog (`provider`). Widened to `string` at use sites for
 * forward-compatibility.
 */
export type AvatarSource = "preset" | "provider";

/**
 * `AvatarPreset.config.kind` marker for a creator photo→avatar preset: a selfie
 * turned into a HeyGen *talking-photo* that lip-syncs the reel's narration. Only
 * present on the POST /avatars response (the GET /avatars list does not echo
 * `kind`), so custom avatars are recognised in a list via {@link isCustomAvatar}.
 */
export const TALKING_PHOTO_KIND = "talking_photo";

/**
 * Avatar entry from GET /avatars (merged AvatarPreset rows + provider
 * list_avatars()). Backend returns loosely-typed dicts, so optional fields
 * are permissive; `[key: string]` preserves any provider-specific extras.
 *
 * A provider (catalog) avatar carries `avatar_id`; a creator preset carries the
 * row `id` + `provider_avatar_id` (HeyGen's `talking_photo_id`) instead. Use
 * {@link avatarSelectId} to get the value to send as `params.avatar_id` (the job
 * pipeline accepts either the preset's `provider_avatar_id` or its `id`).
 */
export interface Avatar {
  /** Provider (catalog) avatar id; absent for creator presets. */
  avatar_id?: string;
  /** Preset row id; present for creator presets (`source === "preset"`). */
  id?: string;
  /** HeyGen `talking_photo_id` for a photo→avatar preset. */
  provider_avatar_id?: string;
  name?: string;
  display_name?: string;
  provider?: string;
  thumbnail_url?: string;
  voice_name?: string;
  is_active?: boolean;
  /** Preset config marker (e.g. {@link TALKING_PHOTO_KIND}); list may omit it. */
  kind?: string;
  /** Origin of the entry; widened to `string` for forward-compatibility. */
  source?: AvatarSource | string;
  [key: string]: unknown;
}

/**
 * The value to send as `params.avatar_id` when creating a job with `avatar`.
 * Provider avatars use `avatar_id`; creator presets use `provider_avatar_id`
 * (the HeyGen `talking_photo_id`) and finally fall back to the preset row `id` —
 * all three are accepted server-side (`app/services/reelforge.py`).
 */
export function avatarSelectId(avatar: Avatar): string {
  const catalogId =
    typeof avatar.avatar_id === "string" ? avatar.avatar_id.trim() : "";
  if (catalogId) return catalogId;
  const providerId =
    typeof avatar.provider_avatar_id === "string"
      ? avatar.provider_avatar_id.trim()
      : "";
  if (providerId) return providerId;
  return typeof avatar.id === "string" ? avatar.id.trim() : "";
}

/**
 * True for a creator-owned custom avatar (an `AvatarPreset` row, including a
 * photo→avatar selfie) rather than a live provider-catalog avatar. The GET
 * /avatars list does not echo `config.kind`, so `source === "preset"` is the
 * available signal.
 */
export function isCustomAvatar(avatar: Avatar): boolean {
  return avatar.source === "preset";
}

/** Human-readable label for an avatar chip/card (display name → name → id). */
export function avatarLabel(avatar: Avatar): string {
  const name = (avatar.display_name || avatar.name || "").trim();
  return name || avatarSelectId(avatar) || "Avatar";
}

/**
 * Request body for POST /avatars — turn a creator's uploaded selfie
 * (`image_key`, an R2 key from the presign/upload flow that the caller owns)
 * into a private HeyGen *talking-photo* avatar that lip-syncs the reel's
 * narration. `display_name` labels it in the picker; `voice_name` optionally
 * pins a default narrator selector (`"elevenlabs:<voice_id>"`). Both optional.
 */
export interface CreateAvatarRequest {
  /** R2 key of the uploaded selfie (must be an upload the caller owns). */
  image_key: string;
  /** Display label for the avatar (optional). */
  display_name?: string;
  /** Default narrator selector `"elevenlabs:<voice_id>"` (optional). */
  voice_name?: string;
}

/**
 * Result of POST /avatars: the persisted `AvatarPreset` serialised to the public
 * envelope. `provider_avatar_id` carries HeyGen's `talking_photo_id` and `kind`
 * is {@link TALKING_PHOTO_KIND}. It appears in GET /avatars (as `source:
 * "preset"`) for use in jobs. Shaped so it can be dropped straight into an
 * {@link Avatar} list.
 */
export interface CreateAvatarResult {
  /** Preset row id. */
  id: string;
  provider: string;
  /** HeyGen `talking_photo_id`. */
  provider_avatar_id: string;
  display_name: string;
  voice_name: string;
  thumbnail_url: string;
  /** Preset kind — {@link TALKING_PHOTO_KIND} for a photo→avatar. */
  kind: string;
  is_active: boolean;
  /** Present so the row can be merged into an avatar list ("preset"). */
  source?: AvatarSource | string;
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
}

// ---------------------------------------------------------------------------
// Billing / plans (POST /billing/checkout, GET /billing/plans)
// ---------------------------------------------------------------------------

/**
 * Payment providers supported at checkout. iyzico is used for Turkey (TR);
 * Creem (creem.io) and Polar (polar.sh) are merchant-of-record checkout
 * platforms. Which of these are actually usable in the current environment is
 * decided server-side (a provider only appears from {@link getProviders} when
 * its required secrets are configured), so treat this union as the full
 * catalogue, not the enabled set.
 */
export type PaymentProvider = "stripe" | "iyzico" | "creem" | "polar";

/** Ordered list of selectable payment providers for a provider toggle. */
export const PAYMENT_PROVIDERS: readonly PaymentProvider[] = [
  "stripe",
  "iyzico",
  "creem",
  "polar",
];

/**
 * Response from GET /billing/providers: the provider ids whose required
 * secret(s) are configured server-side, so the client renders only the rails
 * that will actually work. Values are widened to `string` for
 * forward-compatibility if the backend adds a new provider before this union
 * catches up.
 */
export interface ProvidersResult {
  providers: (PaymentProvider | string)[];
}

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
   * When set, buy the pack for a workspace's SHARED credit pool instead of the
   * caller's personal balance. The backend carries this id in the provider's
   * checkout-session metadata (Stripe, Creem and Polar) and, on webhook
   * fulfillment, grants to the workspace pool (`CreditRepository.workspace_grant`)
   * — still fully idempotent. The caller must be an owner/admin of the workspace
   * (authorized server-side).
   */
  workspace_id?: string;
}

/**
 * Response from POST /billing/checkout. `checkout_url` is the hosted payment
 * page (Stripe / iyzico / Creem / Polar) the client redirects the buyer to.
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

/**
 * A single file in a legacy MoneyPrinterTurbo standalone stock library —
 * either the background-music library (`GET /musics`) or the local
 * video-materials library (`GET /video_materials`). The backend deliberately
 * returns only the basename in `file` (never the host's absolute path); that
 * basename is what a job references (`bgm_file` / a local material path).
 */
export interface StockLibraryFile {
  /** Display filename (basename). */
  name: string;
  /** File size in bytes. */
  size: number;
  /** Server-relative basename re-resolved inside the storage allow-list. */
  file: string;
}

/** Envelope payload of `GET /musics` and `GET /video_materials`. */
export interface StockLibraryListResult {
  files: StockLibraryFile[];
}

/** Envelope payload of `POST /musics` and `POST /video_materials`. */
export interface StockLibraryUploadResult {
  /** Stored basename of the accepted upload. */
  file: string;
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

/**
 * An enabled AI background-music generator from GET /catalog/music-generators.
 * Only providers whose API keys are configured server-side (`is_enabled()`) are
 * returned, so the UI shows the "Generate with AI" option only when at least one
 * exists. `id` is the value sent as {@link JobCreateRequest.bgm_provider}.
 */
export interface MusicGenerator {
  id: string;
  name: string;
  /**
   * Provider hard cap on `music_prompt` length. `0` means the backend did not
   * report one; the pipeline clamps the prompt to this limit regardless.
   */
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
}

// ---------------------------------------------------------------------------
// Multi-language dubbing (GET /dub/languages, POST /jobs/{id}/dub)
//
// From a finished source reel, dub the same reel into N target languages. Each
// language re-translates the source SCRIPT then runs the normal pipeline
// (multilingual TTS, fresh captions from the new timestamps, avatar, compose),
// reusing the source's screen recording, avatar, voice, layout and caption
// style. The N dubbed jobs share ONE `batch_id` so they can be reviewed
// together via GET /batches/{batch_id}.
// ---------------------------------------------------------------------------

/**
 * Target languages supported for dubbing. Bundled caption fonts cover exactly
 * this set. `DubLanguage.code` widens to `string` for forward-compatibility if
 * the backend adds more.
 */
export type DubLanguageCode = "en" | "tr" | "es" | "fr" | "de" | "pt" | "it";

/** The supported dubbing target languages, in display order. */
export const DUB_LANGUAGE_CODES: readonly DubLanguageCode[] = [
  "en",
  "tr",
  "es",
  "fr",
  "de",
  "pt",
  "it",
];

/** Default credits charged to dub a source reel into one language. */
export const DEFAULT_DUB_CREDIT_COST = 1;

/**
 * A supported dubbing target language from GET /dub/languages. `code` is the
 * value sent in {@link DubJobRequest.languages}; `name`/`native_name` are for
 * display; `credit_cost` is the per-language price (defaults to
 * {@link DEFAULT_DUB_CREDIT_COST} when the backend omits it).
 */
export interface DubLanguage {
  code: DubLanguageCode | string;
  /** English display label, e.g. "Spanish". */
  name: string;
  /** Native-script display name, e.g. "Español", when available. */
  native_name?: string;
  /** Credits charged to dub into this language (defaults to 1). */
  credit_cost?: number;
  [key: string]: unknown;
}

/** Request body for POST /jobs/{id}/dub. */
export interface DubJobRequest {
  /** Target language codes to dub the source reel into (at least one). */
  languages: string[];
}

/**
 * Result of POST /jobs/{id}/dub. The N dubbed jobs share one `batch_id` so they
 * surface together in the batch-review UI (GET /batches/{batch_id}); `job_ids`
 * lists every created dubbed job in request order.
 */
export interface DubJobResult {
  /** Shared batch identifier for the created dubbed jobs. */
  batch_id: string;
  /** Every created dubbed job id, in request order. */
  job_ids: string[];
  /** The source job the dubs were derived from, echoed when present. */
  source_job_id?: string;
  [key: string]: unknown;
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
// Creator dashboard / BI analytics (GET /me/analytics?days=N)
//
// A richer, time-windowed view over the same data ReelForge already records
// (jobs / job_events / credit_ledger). Every figure is STRICTLY caller-scoped —
// there is no cross-user aggregation. The mobile client treats every field
// defensively (see api.ts::getAnalytics) so a partial/legacy payload still
// renders rather than throwing.
// ---------------------------------------------------------------------------

/** One day bucket in a daily time series (ISO `YYYY-MM-DD` date + value). */
export interface AnalyticsPoint {
  /** ISO-8601 calendar day, e.g. "2026-08-10". */
  date: string;
  /** The bucket's value (USD for cost, credit magnitude for burn). */
  value: number;
}

/**
 * Creation → completion → publish funnel counts over the window. `published`
 * counts jobs that were uploaded/published to a destination.
 */
export interface AnalyticsFunnel {
  created: number;
  completed: number;
  published: number;
}

/** Compose-stage render-time distribution (milliseconds) over the window. */
export interface RenderTimeStats {
  p50_ms: number;
  p90_ms: number;
  avg_ms: number;
  /** Number of compose-stage samples the percentiles are computed from. */
  count: number;
}

/**
 * A single row in a usage breakdown (jobs by layout / language / variants, or a
 * top hook/template). `label` is an optional human-friendly name; when absent
 * the UI falls back to `key`.
 */
export interface AnalyticsBreakdownItem {
  key: string;
  label?: string;
  count: number;
}

export interface TrendFunnelItem extends AnalyticsFunnel {
  key: string;
  label?: string;
}

export interface TrendFunnel extends AnalyticsFunnel {
  by_trend: TrendFunnelItem[];
}

export interface ForecastTraceItem {
  forecast_id: string;
  trend_observation_id: string;
  trend_id: string;
  trend_label: string;
  content_type: string;
  expected_reach: number;
  forecast_created_at: string | null;
  job_id: string | null;
  job_state: string;
  result_ready: boolean;
  publish_status: string;
  publish_platform: string | null;
  publish_event_at: string | null;
  measurement_status: "measured" | "pending";
  actual_reach: number | null;
  delta: number | null;
  delta_pct: number | null;
  reach_platform: string | null;
}

export interface ForecastContentComparison {
  content_type: string;
  measured: number;
  pending: number;
  expected_reach: number | null;
  actual_reach: number | null;
  delta: number | null;
  delta_pct: number | null;
}

export interface ForecastTrace {
  status: "available" | "unavailable";
  traces: ForecastTraceItem[];
  by_content_type: ForecastContentComparison[];
}

/** Per-user BI dashboard payload from GET /me/analytics (caller-scoped). */
export interface Analytics {
  user_id: string;
  /** The trailing window, in days, these aggregates cover. */
  days: number;
  /** Jobs created → completed → published/uploaded within the window. */
  funnel: AnalyticsFunnel;
  /** Daily SUM(job_events.cost_usd), oldest → newest. */
  cost_by_day: AnalyticsPoint[];
  /** Daily burn (magnitude of negative credit_ledger deltas), oldest → newest. */
  credits_burn_by_day: AnalyticsPoint[];
  /** Current credit balance (latest ledger balance_after; lifetime, not windowed). */
  credits_balance: number;
  /** Total render spend (USD) within the window. */
  total_cost_usd: number;
  /** Total credits burned within the window. */
  credits_burned: number;
  /** Compose-stage render-time distribution within the window. */
  render_time: RenderTimeStats;
  /** Jobs grouped by layout hint. */
  by_layout: AnalyticsBreakdownItem[];
  /** Jobs grouped by language hint. */
  by_language: AnalyticsBreakdownItem[];
  /** Jobs grouped by requested variant count. */
  by_variants: AnalyticsBreakdownItem[];
  /** Most-used hooks/templates counted from job params/script. */
  top_hooks: AnalyticsBreakdownItem[];
  trend_funnel: TrendFunnel;
  forecast_trace: ForecastTrace;
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
 * A saved wizard/job "brand kit" preset from GET/POST /me/presets. Presets are
 * caller-scoped by default, but a preset SHARED to a workspace
 * (`workspace_id` set, `shared === true`) is also visible to every member of
 * that workspace via GET /me/presets. A shared preset can be deleted by its
 * creator OR any workspace admin+; a personal preset only by its creator.
 */
export interface Preset {
  id: string;
  name: string;
  /** Opaque config map to spread back onto a create-job payload. */
  config: Record<string, unknown>;
  /**
   * The workspace this preset is shared to, or `null`/absent for a personal
   * (private) preset. When set, every member of the workspace sees this preset.
   */
  workspace_id?: string | null;
  /** True when the preset is shared to a workspace (mirrors `workspace_id`). */
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
   * Optional workspace to SHARE this preset ("brand kit") with. When present,
   * the preset becomes visible to every member of the workspace (the caller
   * must be a member; a non-member/unknown workspace yields 403). Omit to keep
   * the preset personal (private to the creator).
   */
  workspace_id?: string;
}

/** Acknowledgement returned by DELETE /me/presets/{id}. */
export interface PresetDeleteResult {
  deleted: boolean;
  id: string;
}

// ---------------------------------------------------------------------------
// Brand Voice — voice cloning (POST /voices/clone, GET /voices/mine, DELETE)
// ---------------------------------------------------------------------------

/**
 * A private cloned "brand voice" from GET /voices/mine and POST /voices/clone.
 *
 * `voice_id` is the narrator SELECTOR — `"elevenlabs:<provider_voice_id>"` —
 * sent as `params.voice_name` when creating a reel (the format
 * `app/services/voice.py::tts()` already handles). It is NOT the internal row
 * id: `id` is the row id and is the path param for DELETE /voices/mine/{id}.
 */
export interface UserVoice {
  /** Internal row id — the path param for DELETE /voices/mine/{id}. */
  id: string;
  /** Narrator selector, e.g. "elevenlabs:21m00Tcm4TlvDq8ikWAM". */
  voice_id: string;
  /** Creator-supplied display name. */
  name: string;
  /** Clone lifecycle status (e.g. "ready"). */
  status: string;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/**
 * Request body for POST /voices/clone. `sample_key` is the R2 key of a voice
 * sample previously uploaded via the presign flow. `consent` MUST be `true` —
 * it records the creator's mandatory attestation that they own or are
 * authorized to use the sampled voice (the backend rejects `false` with 400).
 */
export interface CloneVoiceRequest {
  name: string;
  sample_key: string;
  /** Mandatory ownership/authorization attestation; must be true. */
  consent: boolean;
  description?: string;
}

/** Acknowledgement returned by DELETE /voices/mine/{id}. */
export interface VoiceDeleteResult {
  id: string;
  deleted: boolean;
}

// ---------------------------------------------------------------------------
// SPARK — AI Idea Engine (POST /ideas/generate, GET/POST/DELETE /me/ideas)
// ---------------------------------------------------------------------------

/**
 * The four caption-style presets a SPARK idea can suggest. Mirrors
 * `VALID_CAPTION_STYLES` in `app/services/ideas.py`. A generated idea always
 * carries one of these, but `Idea.suggested_caption_style` stays a widened
 * `string` for forward-compatibility.
 */
export type IdeaCaptionStyle =
  | "karaoke_yellow"
  | "karaoke_green"
  | "clean_white"
  | "bold_violet";

/** The suggestable caption-style presets, in display order. */
export const IDEA_CAPTION_STYLES: readonly IdeaCaptionStyle[] = [
  "karaoke_yellow",
  "karaoke_green",
  "clean_white",
  "bold_violet",
];

/** Default idea count requested by the SPARK form (backend clamps to [1,10]). */
export const DEFAULT_IDEA_COUNT = 6;
/** Backend hard cap on ideas generated per call (`GenerateIdeasRequest.count`). */
export const MAX_IDEA_COUNT = 10;
/** Minimum ideas per call. */
export const MIN_IDEA_COUNT = 1;

/**
 * A single SPARK viral-UGC video concept from POST /ideas/generate. Mirrors
 * `IdeaData` in the backend schema (permissive: the generator may add fields).
 * `suggested_*` and `language` are widened to `string` because the backend
 * coerces unknown values to safe defaults but the response type allows any.
 */
export interface Idea {
  title: string;
  hook: string;
  angle: string;
  format: string;
  /** 2-4 shot beats making up the script. */
  script_outline: string[];
  suggested_layout?: Layout | string | null;
  suggested_caption_style?: IdeaCaptionStyle | string | null;
  language?: Language | string | null;
  est_duration_s?: number | null;
  [key: string]: unknown;
}

/** Request body for POST /ideas/generate. `app_context` is required. */
export interface GenerateIdeasRequest {
  /** The creator's app/niche description (required; max 1000 chars). */
  app_context: string;
  /** Optional target-audience note (max 300 chars). */
  audience?: string;
  /** How many concepts to generate (1..10); backend clamps out-of-range. */
  count?: number;
  /** Preferred language for the concepts. */
  language?: Language | string;
}

/**
 * A saved SPARK concept from GET /me/ideas. The whole concept is under `idea`;
 * `title`/`hook` are denormalised out of it for cheap list rendering.
 */
export interface SavedIdea {
  /** Row id — the path param for DELETE /me/ideas/{id}. */
  id: string;
  title: string;
  hook: string;
  /** The stored concept payload. */
  idea: Idea;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/** Acknowledgement returned by POST /me/ideas. */
export interface SaveIdeaResult {
  id: string;
}

/** Acknowledgement returned by DELETE /me/ideas/{id}. */
export interface IdeaDeleteResult {
  deleted: boolean;
  id: string;
}

// ---------------------------------------------------------------------------
// In-app notifications (bell + unread badge + notification center)
//
// Backs the auth-gated endpoints in app/controllers/v1/notifications.py — the
// in-app counterpart to the external webhook (app/services/webhooks.py). The
// server best-effort emits a notification row on lifecycle / growth events; the
// client renders an unread badge + list. All reads are strictly caller-scoped.
// ---------------------------------------------------------------------------

/**
 * The lifecycle / growth events the server emits a notification for. Widened to
 * `string` at the use site (see {@link Notification.kind}) so a new server-side
 * kind never breaks rendering — the UI falls back to a generic presentation.
 */
export type NotificationKind =
  | "job_complete"
  | "job_failed"
  | "low_credits"
  | "referral_earned";

/** The known notification kinds, in the order the server documents them. */
export const NOTIFICATION_KINDS: readonly NotificationKind[] = [
  "job_complete",
  "job_failed",
  "low_credits",
  "referral_earned",
];

/**
 * One notification from GET /me/notifications. `data` is the opaque per-event
 * payload (e.g. `{ job_id, result_url }` for `job_complete`, `{ error }` for
 * `job_failed`, `{ balance }` for `low_credits`, `{ credits }` for
 * `referral_earned`); its shape can grow server-side, so it stays a permissive
 * JSON map. When `data.job_id` is present the client deep-links to that job.
 */
export interface Notification {
  id: string;
  /** Widened to `string` for forward-compatibility with new server kinds. */
  kind: NotificationKind | string;
  title: string;
  body: string;
  /** Opaque per-event payload; read-only from the client's perspective. */
  data: Record<string, unknown>;
  read: boolean;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
}

/**
 * Response from GET /me/notifications: the caller's notifications (newest first)
 * plus their live total unread count (independent of any `unread_only`/`limit`
 * filter, so the bell badge stays correct on a filtered/truncated page).
 */
export interface NotificationsResult {
  notifications: Notification[];
  unread_count: number;
}

/** Optional filters for GET /me/notifications. */
export interface ListNotificationsQuery {
  /** Restrict the page to unread notifications only. */
  unreadOnly?: boolean;
  /** Cap the page size (server clamps to a sane maximum). */
  limit?: number;
}

/** Response from GET /me/notifications/unread_count. */
export interface UnreadCountResult {
  unread_count: number;
}

/** Acknowledgement returned by POST /me/notifications/{id}/read. */
export interface MarkNotificationReadResult {
  id: string;
  read: boolean;
}

/**
 * Acknowledgement returned by POST /me/notifications/read_all. `updated` is how
 * many unread rows were flipped; `unread_count` is `0` after the bulk update.
 */
export interface MarkAllNotificationsReadResult {
  updated: number;
  unread_count: number;
}

// ---------------------------------------------------------------------------
// Scheduled Publishing (POST /jobs/{id}/schedule, GET/DELETE /me/scheduled)
//
// A creator queues a *finished* reel to auto-publish to social platforms at a
// future UTC time. A background Celery-beat due-runner publishes claimed
// schedules and marks them published/failed; the client only creates, lists and
// cancels them. Backed by `app/controllers/v1/schedule.py`.
// ---------------------------------------------------------------------------

/**
 * Platforms a finished reel can be auto-published to. Mirrors
 * `scheduler.ALLOWED_PLATFORMS` (and the on-demand `app/services/publish.py`
 * targets). Widened to `string` at use sites for forward-compatibility.
 */
export type SchedulePlatform = "tiktok" | "instagram" | "youtube_shorts";

/** The publishable platforms, in display order. */
export const SCHEDULE_PLATFORMS: readonly SchedulePlatform[] = [
  "tiktok",
  "instagram",
  "youtube_shorts",
];

/** YouTube visibility applied when `youtube_shorts` is a scheduled target. */
export type YoutubePrivacyStatus = "private" | "unlisted" | "public";

/** The selectable YouTube privacy options, in display order (default first). */
export const YOUTUBE_PRIVACY_STATUSES: readonly YoutubePrivacyStatus[] = [
  "private",
  "unlisted",
  "public",
];

/**
 * Lifecycle status of a scheduled publish. `pending` rows are claimable/cancelable;
 * the due-runner flips them to `publishing` then `published`/`failed`; the owner
 * may `cancel` a still-`pending` row. Widened to `string` at use sites so a new
 * server-side status never breaks rendering.
 */
export type ScheduleStatus =
  | "pending"
  | "publishing"
  | "published"
  | "failed"
  | "canceled";

/** The known schedule statuses. */
export const SCHEDULE_STATUSES: readonly ScheduleStatus[] = [
  "pending",
  "publishing",
  "published",
  "failed",
  "canceled",
];

/**
 * A scheduled auto-publish from POST /jobs/{id}/schedule and GET /me/scheduled.
 * `id` is the path param for DELETE /me/scheduled/{id}. `scheduled_at` is an
 * ISO-8601 UTC timestamp (nullable defensively). The index signature preserves
 * any forward-compatible fields the backend adds.
 */
export interface ScheduledPublish {
  /** Row id — the path param for DELETE /me/scheduled/{id}. */
  id: string;
  /** The completed job whose final output will be published. */
  job_id: string;
  /** Target platforms (subset of {@link SCHEDULE_PLATFORMS}). */
  platforms: string[];
  /** ISO-8601 UTC time the reel will publish at. */
  scheduled_at: string | null;
  /** Lifecycle status; widened to `string` for forward-compatibility. */
  status: ScheduleStatus | string;
  /** YouTube visibility applied when publishing to youtube_shorts. */
  youtube_privacy_status?: string | null;
  /** How many publish attempts the due-runner has made. */
  attempts?: number | null;
  /** Failure detail when `status === "failed"` (empty string otherwise). */
  error?: string;
  [key: string]: unknown;
}

/** Request body for POST /jobs/{id}/schedule. */
export interface SchedulePublishRequest {
  /** Target platforms (at least one; subset of {@link SCHEDULE_PLATFORMS}). */
  platforms: string[];
  /** Future publish time as an ISO-8601 UTC timestamp (e.g. "...Z"). */
  scheduled_at: string;
  /** YouTube visibility override; defaults to "private" server-side. */
  youtube_privacy_status?: string;
}

/** Optional filter for GET /me/scheduled. */
export interface ListScheduledQuery {
  /** Restrict to one status (e.g. "pending"). */
  status?: string;
}

/** Acknowledgement returned by DELETE /me/scheduled/{id}. */
export interface CancelScheduledResult {
  id: string;
  /** The row's new status ("canceled" on success). */
  status: string;
}

// ---------------------------------------------------------------------------
// Cover / Thumbnail generator (GET /catalog/cover-styles, POST /jobs/{id}/cover)
//
// A creator turns a job into a scroll-stopping cover image: the job's poster
// frame (`poster_key` from Phase 6, else a rendered gradient) with the HOOK
// overlaid as a bold headline in a chosen style. Rendered server-side with
// Pillow using the bundled Montserrat-ExtraBold font (full Turkish glyph
// coverage — İĞÜŞÖÇ), output as a 1080x1920 JPG uploaded to R2 and stored as
// `Job.cover_key`. Regenerable with a different headline/style.
// ---------------------------------------------------------------------------

/**
 * A selectable cover style from GET /catalog/cover-styles. `id` is the value
 * sent as `style` in {@link GenerateCoverRequest}. `name`/`description` are for
 * display; `accent`/`background`/`text` are optional hex colours the client may
 * use to preview the style chip. The index signature preserves any
 * forward-compatible fields the backend adds.
 */
export interface CoverStyle {
  /** Stable identifier sent as `style` when generating a cover. */
  id: string;
  /** Human-readable style name, e.g. "Bold Punch". */
  name: string;
  /** Short description of the look. */
  description: string;
  /** Optional accent/highlight hex colour for a preview swatch. */
  accent?: string;
  /** Optional background hex colour for a preview swatch. */
  background?: string;
  /** Optional headline text hex colour for a preview swatch. */
  text?: string;
  [key: string]: unknown;
}

/**
 * Request body for POST /jobs/{id}/cover. Both fields are optional: an omitted
 * `headline` falls back to the job's HOOK server-side, and an omitted `style`
 * uses the default cover style. Sending either regenerates the cover.
 */
export interface GenerateCoverRequest {
  /** Headline text overlaid on the cover; defaults to the job's HOOK. */
  headline?: string;
  /** Cover style id (from {@link CoverStyle.id}); defaults server-side. */
  style?: string;
}

/**
 * Result of POST /jobs/{id}/cover. `cover_key` is the stored R2 key (also
 * mirrored onto {@link Job.cover_key}); `cover_url` is a presigned GET URL for
 * immediately previewing the just-rendered cover when the backend supplies one.
 * `headline`/`style` echo what was actually rendered.
 */
export interface CoverResult {
  /** The job the cover belongs to. */
  job_id: string;
  /** R2 key (or already-presigned URL) for the generated cover image. */
  cover_key: string;
  /** Presigned GET URL for previewing the cover, when supplied. */
  cover_url?: string;
  /** The headline that was rendered onto the cover. */
  headline?: string;
  /** The style id that was applied. */
  style?: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Team Workspaces (POST/GET /workspaces, GET/POST/PATCH/DELETE
// /workspaces/{id}/members, POST /workspaces/{id}/leave)
//
// An ADDITIVE membership layer on top of the existing per-user job/credit
// ownership: a user creates a Workspace and invites existing users (by email)
// as owner | admin | member. Owners/admins can invite + remove members and
// change roles; members can view + leave. This does NOT change how individual
// jobs, credits, or resources are owned — it is the foundation for team plans
// and shared resources later. All reads/mutations are scoped + authorized
// server-side; the client mirrors the caller's role for UI affordances only.
// ---------------------------------------------------------------------------

/**
 * A member's role within a workspace.
 *
 * The ENTERPRISE (Access & Governance, Epic 1) vocabulary — mirroring the
 * pycasbin enforcer in `app/services/rbac.py` — is `owner` (full control) >
 * `admin` (manage members + settings + read audit) > `editor` (create/read
 * jobs) > `viewer` (read jobs), with `billing` a standalone finance role
 * (manage billing + read jobs) ranked alongside `editor`. `owner` cannot be
 * removed/demoted while they are the sole owner (enforced server-side).
 *
 * The legacy team layer only ever used `owner | admin | member`, so `member`
 * is kept tolerated for rows created before the Enterprise vocabulary. The
 * union is widened with `(string & {})` so a new server-side role never breaks
 * rendering while preserving autocomplete for the known values.
 */
export type WorkspaceRole =
  | "owner"
  | "admin"
  | "editor"
  | "viewer"
  | "billing"
  | "member"
  | (string & {});

/** The assignable roles, in descending privilege order (for pickers). */
export const WORKSPACE_ROLES: readonly WorkspaceRole[] = [
  "owner",
  "admin",
  "member",
];

/** Roles that may manage membership (invite, remove, change roles). */
export const WORKSPACE_MANAGER_ROLES: readonly WorkspaceRole[] = [
  "owner",
  "admin",
];

/**
 * A team workspace from POST /workspaces and GET /workspaces. `my_role` is the
 * calling user's role in this workspace, used to gate management affordances in
 * the UI (the backend independently authorizes every mutation). The index
 * signature preserves any forward-compatible fields the backend adds.
 */
export interface Workspace {
  /** Stable workspace id — the path param for member endpoints. */
  id: string;
  /** Creator-supplied display name. */
  name: string;
  /** The calling user's role in this workspace; widened for forward-compat. */
  my_role: WorkspaceRole | string;
  /** Total member count, when the backend supplies it (for list summaries). */
  member_count?: number;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/**
 * A single membership row from GET /workspaces/{id}/members and the mutation
 * endpoints. `id` is the membership row id (the path param for
 * PATCH/DELETE /workspaces/{id}/members/{memberId}); `user_id`/`email` identify
 * the underlying user. `is_self` marks the calling user's own row when the
 * backend supplies it (the client also falls back to a `user_id` comparison).
 */
export interface WorkspaceMember {
  /** Membership row id — the path param for member mutations. */
  id: string;
  /** The underlying user's id. */
  user_id: string;
  /** The member's email (how they were invited). */
  email: string;
  /** This member's role; widened to `string` for forward-compatibility. */
  role: WorkspaceRole | string;
  /** Optional display name, when the backend supplies one. */
  name?: string;
  /** True when this row is the calling user (server-supplied when present). */
  is_self?: boolean;
  /** ISO-8601 join timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/** Request body for POST /workspaces. */
export interface CreateWorkspaceRequest {
  /** Display name for the new workspace (required, non-empty). */
  name: string;
}

/** Request body for POST /workspaces/{id}/members (invite by email). */
export interface InviteMemberRequest {
  /** Email of an existing user to add to the workspace. */
  email: string;
  /** Role to grant the invited member. */
  role: WorkspaceRole;
}

/** Request body for PATCH /workspaces/{id}/members/{memberId}. */
export interface SetMemberRoleRequest {
  /** The new role for the member. */
  role: WorkspaceRole;
}

/** Acknowledgement returned by DELETE /workspaces/{id}/members/{memberId}. */
export interface RemoveMemberResult {
  /** The removed membership row id. */
  id: string;
  removed: boolean;
}

/** Acknowledgement returned by POST /workspaces/{id}/leave. */
export interface LeaveWorkspaceResult {
  /** The workspace the caller left. */
  workspace_id: string;
  left: boolean;
}

// ---------------------------------------------------------------------------
// Enterprise Access & Governance (Epic 1): RBAC roster + permissions, audit
// trail, platform admin.
// (GET /me/workspaces/{id}/members, PATCH .../members/{userId}/role,
//  GET /me/permissions, GET /me/workspaces/{id}/audit,
//  GET /admin/{users,workspaces,jobs}, POST /admin/impersonate)
//
// Every authorization decision is made SERVER-SIDE by the pycasbin enforcer
// (`app/services/rbac.py`); the client only mirrors the returned role /
// permissions to gate UI affordances — it never grants access. TENANT ISOLATION
// is the #1 invariant: no shape here ever carries another tenant's data, and a
// non-member sees `role: null` with an empty permission set. The audit trail is
// APPEND-ONLY (read-only from every client). Mirrors web/lib/types.ts.
// ---------------------------------------------------------------------------

/**
 * The assignable ENTERPRISE roles, in descending privilege order (for pickers).
 * `billing` is a standalone finance role ranked alongside `editor`; it is placed
 * after `admin` here purely for display grouping.
 */
export const ENTERPRISE_ROLES = [
  "owner",
  "admin",
  "editor",
  "billing",
  "viewer",
] as const;

/** One of the concrete Enterprise roles (excludes the widened `string` member). */
export type EnterpriseRole = (typeof ENTERPRISE_ROLES)[number];

/**
 * Relative rank of each role, mirroring the server's `_ROLE_RANK`
 * (`app/controllers/v1/rbac.py`): `owner > admin > {editor, billing} > viewer`.
 * An unknown / legacy role ranks 0 so it can never out-rank a real role. Used to
 * gate the "you cannot grant a role above your own" affordance client-side (the
 * backend independently enforces the same rule with a 403).
 */
export const ROLE_RANK: Readonly<Record<string, number>> = {
  viewer: 1,
  editor: 2,
  billing: 2,
  admin: 3,
  owner: 4,
};

/** The rank of a role (0 for unknown / blank / legacy), per {@link ROLE_RANK}. */
export function roleRank(role: WorkspaceRole | string | null | undefined): number {
  if (!role) return 0;
  return ROLE_RANK[role] ?? 0;
}

/**
 * A permission in the Enterprise catalog (mirrors `app/services/rbac.py`
 * `PERMISSIONS`). Widened with `(string & {})` so a new server-side permission
 * never breaks rendering while preserving autocomplete for the known values.
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

/** The full Enterprise permission catalog, in a stable display order. */
export const PERMISSIONS: readonly Permission[] = [
  "jobs.read",
  "jobs.create",
  "members.manage",
  "workspace.settings",
  "billing.manage",
  "audit.read",
  "admin.access",
];

/**
 * The effective permissions each role holds (direct + inherited), mirroring the
 * enforcer's `_DIRECT_GRANTS` + role hierarchy in `app/services/rbac.py`. An
 * unknown / blank / legacy role holds nothing (fail-closed), matching the server.
 */
const EFFECTIVE_PERMISSIONS: Readonly<Record<string, readonly Permission[]>> = {
  viewer: ["jobs.read"],
  editor: ["jobs.create", "jobs.read"],
  admin: [
    "members.manage",
    "workspace.settings",
    "audit.read",
    "jobs.create",
    "jobs.read",
  ],
  owner: [
    "jobs.create",
    "jobs.read",
    "members.manage",
    "billing.manage",
    "workspace.settings",
    "audit.read",
    "admin.access",
  ],
  billing: ["billing.manage", "jobs.read"],
};

/**
 * The permissions `role` grants (direct + inherited), mirroring the server-side
 * enforcer for UI gating only. A `null` / unknown / legacy role yields `[]`. The
 * authoritative source for the CALLER's own permissions is {@link Permissions}
 * from `getMyPermissions`; this helper is for reasoning about OTHER roles (e.g.
 * a roster row) without a round-trip.
 */
export function effectivePermissions(
  role: WorkspaceRole | string | null | undefined,
): Permission[] {
  if (!role) return [];
  return [...(EFFECTIVE_PERMISSIONS[role] ?? [])];
}

/**
 * True when `role` may manage membership (invite / remove / change roles), i.e.
 * it holds `members.manage`. Owners and admins can; editor / viewer / billing
 * (and legacy `member`) cannot. Mirrors the enforcer — UI gating only.
 */
export function canManageMembers(
  role: WorkspaceRole | string | null | undefined,
): boolean {
  return effectivePermissions(role).includes("members.manage");
}

/**
 * True when `role` may read the workspace audit trail, i.e. it holds
 * `audit.read`. Owners and admins can. Mirrors the enforcer — UI gating only.
 */
export function canReadAudit(
  role: WorkspaceRole | string | null | undefined,
): boolean {
  return effectivePermissions(role).includes("audit.read");
}

/**
 * A single membership row from GET /me/workspaces/{id}/members (the Enterprise
 * RBAC roster) and PATCH .../members/{userId}/role. Unlike the legacy
 * {@link WorkspaceMember}, this shape is keyed by `user_id` (the path param for a
 * role change) and does NOT carry a membership row id. `email` may be `null` when
 * the joined user record is missing. The index signature preserves any
 * forward-compatible fields the backend adds.
 */
export interface Member {
  /** The member's user id — the path param for a role change. */
  user_id: string;
  /** The member's email, or `null` when the joined user is missing. */
  email: string | null;
  /** The member's Enterprise role; widened to `string` for forward-compat. */
  role: WorkspaceRole | string;
  /** ISO-8601 join timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/**
 * The caller's effective permissions in a workspace, from GET /me/permissions.
 * `role` is `null` (and `permissions` empty) when the caller is not a member —
 * the tenant-isolation signal, with no leak of the workspace's contents.
 */
export interface Permissions {
  /** The workspace the permissions were computed for. */
  workspace_id: string;
  /** The caller's role, or `null` when they are not a member. */
  role: WorkspaceRole | null;
  /** The permissions the role grants (direct + inherited); `[]` for a non-member. */
  permissions: Permission[];
}

/**
 * One APPEND-ONLY audit row from GET /me/workspaces/{id}/audit. The trail is
 * read-only — there is no create/update/delete API. `metadata` is the opaque
 * per-event detail (e.g. `{ old_role, new_role }` for `members.role_changed`).
 * `id` is a numeric row id (newest rows have the largest ids).
 */
export interface AuditEntry {
  /** Numeric row id (monotonic; newest first in the list). */
  id: number;
  /** The tenant the row belongs to, or `null` for a platform-level event. */
  workspace_id: string | null;
  /** The user who performed the action. */
  actor_user_id: string;
  /** The action key, e.g. "members.role_changed" or "admin.impersonated". */
  action: string;
  /** The kind of entity acted on (e.g. "user"), when applicable. */
  target_type: string | null;
  /** The id of the entity acted on, when applicable. */
  target_id: string | null;
  /** Opaque per-event detail; read-only from the client's perspective. */
  metadata: Record<string, unknown>;
  /** Best-effort source IP of the actor, when captured. */
  ip: string | null;
  /** ISO-8601 timestamp of the event, when available. */
  created_at: string | null;
}

/**
 * A user row in the cross-tenant platform-admin listing (GET /admin/users).
 * Platform-admin (`is_staff`) only — a non-staff caller never receives this.
 */
export interface AdminUser {
  id: string;
  email: string | null;
  display_name: string | null;
  is_staff: boolean;
  credits: number;
  created_at: string | null;
}

/** A workspace row in the cross-tenant platform-admin listing (GET /admin/workspaces). */
export interface AdminWorkspace {
  id: string;
  name: string | null;
  owner_id: string;
  created_at: string | null;
}

/** A job row in the cross-tenant platform-admin listing (GET /admin/jobs). */
export interface AdminJob {
  id: string;
  user_id: string;
  kind: string | null;
  /** Integer job state (see {@link JobState}), when known. */
  state: number | null;
  /** Progress percentage 0..100, when known. */
  progress: number | null;
  created_at: string | null;
}

/**
 * A minted, time-boxed impersonation grant from POST /admin/impersonate
 * (platform-admin only, audited as `admin.impersonated`). `token` is the opaque
 * grant; `expires_in` is its lifetime in seconds. SECURITY: treat `token` as a
 * short-lived secret — never persist it.
 */
export interface Impersonation {
  /** Opaque, short-lived impersonation token. */
  token: string;
  /** The staff user who minted the grant. */
  admin_user_id: string;
  /** The account being impersonated. */
  target_user_id: string;
  /** The grant's scope string. */
  scope: string;
  /** ISO-8601 issue timestamp, when available. */
  issued_at: string | null;
  /** ISO-8601 expiry timestamp, when available. */
  expires_at: string | null;
  /** Lifetime of the grant, in seconds. */
  expires_in: number;
}

/** Server + client cap on an Enterprise audit page (`limit`). */
export const MAX_AUDIT_LIMIT = 100;
/** Default Enterprise audit page size requested by the client. */
export const DEFAULT_AUDIT_LIMIT = 50;
/** Server + client cap on a platform-admin listing page (`limit`). */
export const MAX_ADMIN_LIMIT = 200;
/** Default platform-admin listing page size requested by the client. */
export const DEFAULT_ADMIN_LIMIT = 50;

/** Query params for {@link listAuditLog} (page window; clamped `[1,100]` / `>=0`). */
export interface AuditLogParams {
  /** Page size (backend clamps to `[1, 100]`; default 50). */
  limit?: number;
  /** Row offset (backend floors at 0). */
  offset?: number;
}

/** Query params for the platform-admin list endpoints (clamped `[1,200]` / `>=0`). */
export interface AdminListParams {
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// Shared Workspace Credits (GET /workspaces/{id}/credits,
// POST /workspaces/{id}/credits/grant)
//
// A workspace owns a SHARED credit pool, separate from any member's personal
// balance. Members can charge job creation to the pool (see
// {@link JobCreateRequest.workspace_id}); the pool is debited using the same
// locked-debit ledger pattern as personal credits. Any member may READ the pool
// balance; only owners/admins may GRANT (top up) it — the manual/dev funding
// path (real purchases flow through billing later). Grants never touch any
// personal balance; the acting admin is recorded on the ledger for audit only.
// ---------------------------------------------------------------------------

/**
 * A workspace's SHARED credit pool balance, from GET /workspaces/{id}/credits
 * and POST /workspaces/{id}/credits/grant. `balance` is the whole-credit pool
 * total available to charge team jobs against.
 */
export interface WorkspaceCredits {
  /** Whole-credit balance in the workspace's shared pool. */
  balance: number;
}

/** Request body for POST /workspaces/{id}/credits/grant. */
export interface GrantWorkspaceCreditsRequest {
  /** Credits to add to the shared pool (must be a positive integer). */
  amount: number;
  /** Optional audit note recorded on the ledger row (defaults server-side). */
  reason?: string;
}

// ---------------------------------------------------------------------------
// Brand Watermark (GET /me/brand, PUT /me/brand)
//
// A creator uploads a transparent PNG logo (via the existing presign flow,
// content_type image/png, stored in R2) which the pure-FFmpeg compose stage
// overlays onto their reels at a chosen corner + opacity. The settings are a
// per-user singleton: `enabled` gates whether the watermark is applied by
// default (a job may still override/disable it) and a blank `logo_key` means
// "no watermark" even while `enabled` is true. Backed by
// `app/controllers/v1/brand.py`.
// ---------------------------------------------------------------------------

/**
 * The four overlay corners the compositor understands (mirrors
 * `WATERMARK_POSITIONS` in `app/models/db/repositories.py`). An unknown corner
 * falls back to {@link DEFAULT_WATERMARK_POSITION} server-side.
 */
export type WatermarkPosition =
  | "bottom_right"
  | "bottom_left"
  | "top_right"
  | "top_left";

/** The selectable overlay corners, in display order. */
export const WATERMARK_POSITIONS: readonly WatermarkPosition[] = [
  "top_left",
  "top_right",
  "bottom_left",
  "bottom_right",
];

/** Human-readable labels for each corner, for a position picker. */
export const WATERMARK_POSITION_LABELS: Readonly<
  Record<WatermarkPosition, string>
> = {
  top_left: "Top left",
  top_right: "Top right",
  bottom_left: "Bottom left",
  bottom_right: "Bottom right",
};

/** Opacity is a fraction the backend clamps to this inclusive range. */
export const WATERMARK_OPACITY_MIN = 0;
export const WATERMARK_OPACITY_MAX = 1;

/** Column-default watermark shape (mirrors `UserBrand` / `BrandData`). */
export const DEFAULT_WATERMARK_POSITION: WatermarkPosition = "bottom_right";
export const DEFAULT_WATERMARK_OPACITY = 0.85;
export const DEFAULT_WATERMARK_ENABLED = true;

/**
 * The caller's brand watermark settings from GET /me/brand and PUT /me/brand.
 * `logo_url` is a short-lived presigned GET URL for the stored logo, present
 * only when a non-empty `logo_key` is set (for the preview). The index
 * signature preserves any forward-compatible fields the backend adds.
 */
export interface Brand {
  /** R2 object key of the uploaded transparent PNG logo; "" => no watermark. */
  logo_key: string;
  /** Overlay corner; widened to `string` for forward-compatibility. */
  position: WatermarkPosition | string;
  /** Overlay opacity in [0.0, 1.0]. */
  opacity: number;
  /** Whether the watermark is applied by default (a job may still disable it). */
  enabled: boolean;
  /** Presigned GET URL for previewing the stored logo, when a key is set. */
  logo_url?: string | null;
  /** ISO-8601 last-updated timestamp, when available. */
  updated_at?: string | null;
  [key: string]: unknown;
}

/**
 * Request body for PUT /me/brand (partial update). Every field is optional so a
 * caller may update just one setting; an omitted field leaves the persisted
 * value untouched. `position` must be a known corner and `opacity` must be in
 * [0.0, 1.0] (both 400 otherwise); a supplied non-empty `logo_key` must
 * reference an upload the caller owns (403 otherwise), and `logo_key === ""`
 * explicitly clears the watermark logo.
 */
export interface BrandUpdate {
  logo_key?: string;
  position?: WatermarkPosition | string;
  opacity?: number;
  enabled?: boolean;
}

// ---------------------------------------------------------------------------
// AI B-roll cutaways (POST /jobs/{id}/broll/suggest)
//
// An OPTIONAL creative overlay that repurposes MPT's already-vendored stock
// footage path (Pexels / Pixabay in `app/services/material.py`, disabled for the
// main pipeline) as short B-roll cutaways. The backend derives keywords from the
// job's subject/script (`app/services/llm.py::generate_terms`), downloads a few
// relevant stock clips (`download_videos` + `material_cache`), and returns them
// as suggestions. The creator picks one clip to splice as a brief muted INTRO
// (before the hook) and/or OUTRO (after) around the composed reel — the main reel
// keeps its full audio + captions. The chosen clips' object keys are sent back as
// {@link JobCreateRequest.broll_intro_key} / `broll_outro_key`.
// ---------------------------------------------------------------------------

/**
 * The stock-footage providers B-roll can be suggested from (mirrors MPT's
 * vendored Pexels / Pixabay integration). Widened to `string` at use sites so a
 * new server-side source never breaks rendering.
 */
export type BrollSource = "pexels" | "pixabay";

/** The selectable stock-footage sources, in display order. */
export const BROLL_SOURCES: readonly BrollSource[] = ["pexels", "pixabay"];

/** Default number of B-roll clips requested per suggestion call. */
export const DEFAULT_BROLL_AMOUNT = 6;
/** Backend hard cap on B-roll clips returned per call (server clamps). */
export const MAX_BROLL_AMOUNT = 12;
/** Minimum B-roll clips per call. */
export const MIN_BROLL_AMOUNT = 1;

/**
 * A single suggested stock B-roll clip from POST /jobs/{id}/broll/suggest.
 * `key` is the already-downloaded + cached R2 object key — the value sent as
 * {@link JobCreateRequest.broll_intro_key} / `broll_outro_key` to splice the clip
 * as a muted intro/outro. `thumbnail_url`/`preview_url` may arrive already
 * presigned to absolute URLs for previewing (a bare object key cannot be
 * resolved on-device, so the UI degrades to a placeholder). The index signature
 * preserves any forward-compatible fields the backend adds.
 */
export interface BrollClip {
  /** Cached R2 object key — sent as `broll_intro_key` / `broll_outro_key`. */
  key: string;
  /** Stock provider the clip came from; widened for forward-compatibility. */
  source: BrollSource | string;
  /** Thumbnail image URL for the clip, when the backend supplies one. */
  thumbnail_url?: string;
  /** Short preview/video URL, when available (muted when spliced). */
  preview_url?: string;
  /** Clip duration in seconds, when the backend could probe it. */
  duration_s?: number;
  /** Pixel width of the clip, when known. */
  width?: number;
  /** Pixel height of the clip, when known. */
  height?: number;
  /** Provider-native clip id, for display/debug. */
  id?: string;
  [key: string]: unknown;
}

/** Request body for POST /jobs/{id}/broll/suggest. */
export interface SuggestBrollRequest {
  /** Which stock provider to pull from; omit to let the backend choose. */
  source?: BrollSource | string;
  /** How many clips to suggest (1..12); backend clamps out-of-range. */
  amount?: number;
}

/** Standalone AI B-roll generation mode (`/generation/broll/*`). */
export type BrollGenMode = BrollGenerationMode;

export type BrollGenerateRequest = BrollGenerateInput;

export type BrollGeneration = BrollGenerationSnapshot;

export type PilotCapabilities = ContractPilotCapabilities;

// ---------------------------------------------------------------------------
// Launch gating (GET /launch/status)
// ---------------------------------------------------------------------------

/**
 * The fail-closed public-launch gates the backend exposes to first-party
 * clients (see apps/api/app/core/launch/policy.py `launch_status`). Each flag
 * is server-owned; a `false` value means the corresponding action (device
 * sign-up, paid checkout, direct social publishing) is blocked for the current
 * launch phase and the server will reject the call with HTTP 403.
 */
export interface LaunchFeatures {
  /** New device-account creation is open. */
  signup: boolean;
  /** Paid wallet top-up / plan checkout is open. */
  checkout: boolean;
  /** Direct social publishing is open. */
  publishing: boolean;
}

/** Known launch modes; unknown values are surfaced verbatim as a fallback. */
export type LaunchMode = "internal_pilot" | "public" | (string & {});

/**
 * Non-sensitive launch capability document. Contains no secrets; safe to render
 * to the signed-in user so they understand why checkout/publish is gated.
 */
export interface LaunchStatus {
  /** The active launch phase. `public` unlocks the public feature set. */
  mode: LaunchMode;
  /** True when the product is in full public access (mode === "public"). */
  public_access: boolean;
  /** Per-feature gates for this phase. */
  features: LaunchFeatures;
}

export interface BrollPreset {
  id: string;
  name: string;
  description: string;
  mode: BrollGenMode;
  prompt_template: string;
  workflow_id: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// AI Social Caption & Hashtags (GET /catalog/social-platforms,
// POST /jobs/{id}/social)
//
// For a finished reel, generate an optimized post title + caption + hashtags
// tailored to a target social network. Built on the vendored MPT LLM helper
// (app/services/llm.py::generate_social_metadata); the copy is derived
// server-side from the job's own subject/script, never from client input.
// ---------------------------------------------------------------------------

/**
 * The social networks the caption generator can tailor copy for. Matches the
 * API-facing ids the backend accepts (`SocialRequest.platform`). Widened to a
 * `string` union member on {@link SocialPlatform.id} for forward-compatibility
 * if the backend adds more.
 */
export type SocialPlatformId = "tiktok" | "instagram" | "youtube_shorts";

/** The supported social platforms, in display order. */
export const SOCIAL_PLATFORM_IDS: readonly SocialPlatformId[] = [
  "tiktok",
  "instagram",
  "youtube_shorts",
];

/**
 * A supported social platform from GET /catalog/social-platforms. `id` is the
 * value sent in {@link SocialRequest.platform}; `name` is the display label.
 * The backend sources this from a single source of truth, so the two never
 * drift.
 */
export interface SocialPlatform {
  /** Platform id, e.g. "tiktok"; widened for forward-compatibility. */
  id: SocialPlatformId | string;
  /** Human-readable display label, e.g. "TikTok". */
  name: string;
  [key: string]: unknown;
}

/** Request body for POST /jobs/{id}/social. */
export interface SocialRequest {
  /** Target platform id (one of {@link SOCIAL_PLATFORM_IDS}). */
  platform: SocialPlatformId | string;
  /**
   * Optional caption language override. When omitted, the copy is generated in
   * the job's own configured language.
   */
  language?: string;
}

/**
 * Generated post metadata from POST /jobs/{id}/social: a ready-to-copy title,
 * caption and hashtags a creator can paste when posting. `hashtags` is a list
 * of individual tags (each already `#`-prefixed by the generator) and may be
 * empty. `title` / `caption` may be edited before posting.
 */
export interface SocialMeta {
  /** Suggested post title/headline. */
  title: string;
  /** Suggested post caption/description. */
  caption: string;
  /** Suggested hashtags, each already `#`-prefixed; may be empty. */
  hashtags: string[];
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Draft Social Metadata (POST /social-metadata)
//
// Unlike POST /jobs/{id}/social — which derives copy from a FINISHED reel's own
// persisted subject/script — this endpoint generates the same ready-to-paste
// title/caption/hashtags from a free-form subject (and optional script) the
// creator types in, BEFORE any reel exists. It's the "draft copy" surface:
// plan a hook, get platform-tailored copy, then render. Same LLM helper
// (app/services/llm.py::generate_social_metadata), same {@link SocialMeta}
// response shape.
// ---------------------------------------------------------------------------

/** Max lengths enforced by the backend's VideoSocialMetadataParams schema. */
export const SOCIAL_METADATA_SUBJECT_MAX = 500;
export const SOCIAL_METADATA_SCRIPT_MAX = 8000;

/**
 * Request body for POST /social-metadata. `video_subject` is the one-line topic
 * the copy is written about (required by this client — the backend defaults it,
 * but blank copy is useless). `video_script` is optional supporting context.
 * `platform` selects the tailoring; `language` optionally overrides the output
 * language (the backend treats "auto"/blank as auto-detect).
 */
export interface SocialMetadataRequest {
  /** One-line topic the copy is about, e.g. "A day in Shanghai". */
  video_subject: string;
  /** Optional fuller script / talking points for richer copy. */
  video_script?: string;
  /** Target platform id (one of {@link SOCIAL_PLATFORM_IDS}). */
  platform: SocialPlatformId | string;
  /** Optional output-language hint; omit or "auto" to auto-detect. */
  language?: string;
}

// ---------------------------------------------------------------------------
// Public API Keys (per-user programmatic access — POST/GET/DELETE /me/api-keys)
//
// A power user mints a personal API key for programmatic access to the /api/v1
// REST API. The key is used as the `x-api-key` header (in addition to the Clerk
// JWT and the static app key) and is resolved back to its owning user by the
// backend (SHA-256 hash lookup). SECURITY: the raw key is revealed exactly ONCE
// at creation ({@link ApiKeyCreated.key}); the server stores only its hash, so
// list responses never carry the raw key — only a non-secret display `prefix`.
// ---------------------------------------------------------------------------

/** Request body for POST /me/api-keys. */
export interface ApiKeyCreateRequest {
  /** Human-friendly label to tell keys apart (e.g. "CI", "n8n", "laptop"). */
  name: string;
}

/**
 * One of the caller's API keys as returned by GET /me/api-keys. NEVER carries
 * the raw key or full hash — only the id, label, non-secret `prefix`, and
 * lifecycle metadata. The list includes both active and revoked keys (a full
 * audit view), so `revoked` gates whether the key can still authenticate.
 */
export interface ApiKey {
  /** Internal row id — used as the path param when revoking. */
  id: string;
  /** Human-friendly label the caller gave the key. */
  name: string;
  /** Non-secret leading characters of the raw key, safe to display. */
  prefix: string;
  /** ISO-8601 timestamp of the key's last authenticated use, or null. */
  last_used_at: string | null;
  /** True once the key has been revoked (can no longer authenticate). */
  revoked: boolean;
  /** ISO-8601 creation timestamp, or null when unknown. */
  created_at: string | null;
  /**
   * POWER-USER TIER: the key's per-minute rate limit, or `null` to inherit the
   * plan/config default. Enforced server-side (429 on breach); shown read-only.
   */
  rate_limit_per_min?: number | null;
  /**
   * POWER-USER TIER: the key's monthly request quota, or `null` when unlimited.
   */
  monthly_quota?: number | null;
  /** Requests this key has already consumed in the current calendar month. */
  usage_this_month?: number;
  [key: string]: unknown;
}

/**
 * The ONE-TIME reveal from POST /me/api-keys. `key` is the FULL raw secret and
 * is returned exactly once, at creation — the server keeps only its SHA-256
 * hash, so the raw value is UNRECOVERABLE afterwards (a lost key must be revoked
 * and re-created). Show it once, let the user copy it, and never persist it.
 */
export interface ApiKeyCreated {
  /** Internal row id of the freshly minted key. */
  id: string;
  /** Human-friendly label the caller gave the key. */
  name: string;
  /** The FULL raw API key — shown ONCE and unrecoverable afterwards. */
  key: string;
  /** Non-secret leading characters of the raw key, safe to display. */
  prefix: string;
  /** ISO-8601 creation timestamp, or null when unknown. */
  created_at: string | null;
  [key: string]: unknown;
}

/** Result of DELETE /me/api-keys/{id} — the revoked key's id + status. */
export interface ApiKeyRevokeResult {
  id: string;
  revoked: boolean;
  [key: string]: unknown;
}

/**
 * One API key's current-month usage + limits from GET /me/api-keys/usage
 * (POWER-USER TIER quotas). Caller-scoped and NEVER carries the raw key or hash
 * — only the id, label, non-secret `prefix`, the `period_ym` (`"YYYY-MM"`) the
 * counts apply to, the requests `used` so far this month, and the key's limits.
 * `remaining` is `monthly_quota - used` (floored at 0) or `null` when the key
 * has no monthly cap (unlimited).
 */
export interface ApiKeyUsage {
  /** Internal row id (matches {@link ApiKey.id}). */
  id: string;
  /** Human-friendly label the caller gave the key. */
  name: string;
  /** Non-secret leading characters of the raw key, safe to display. */
  prefix: string;
  /** The calendar month the counts apply to, as `"YYYY-MM"`. */
  period_ym: string;
  /** Requests this key has consumed in `period_ym`. */
  used: number;
  /** Per-minute rate limit, or `null` to inherit the plan/config default. */
  rate_limit_per_min?: number | null;
  /** Monthly request quota, or `null` when unlimited. */
  monthly_quota?: number | null;
  /** Requests left this month (`monthly_quota - used`, floored at 0), or `null`
   * when the key has no monthly cap. */
  remaining?: number | null;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Social Connections — OAuth connect + direct publish
// (GET /me/connections, GET /connections/{provider}/authorize,
//  GET /connections/{provider}/callback, DELETE /me/connections/{provider},
//  POST /jobs/{id}/publish/{provider} — see app/controllers/v1/connections.py)
//
// A creator connects a social account via OAuth (authorize -> browser -> the
// provider redirects to the callback with `code` + the single-use `state`) and
// can then publish a finished, owned job straight to it. SECURITY: no shape here
// EVER carries an access/refresh token — only the provider, the provider-side
// account id, status, scopes and timestamps. Mirrors web/lib/types.ts.
// ---------------------------------------------------------------------------

/**
 * The social providers a creator can connect + publish to. Mirrors the backend
 * `SOCIAL_PROVIDERS` (`app/models/db/repositories.py`). Widened to `string` at
 * use sites so a new server-side provider never breaks rendering.
 */
export type SocialProvider = "tiktok" | "instagram" | "youtube";

/** The connectable social providers, in display order. */
export const SOCIAL_PROVIDERS: readonly SocialProvider[] = [
  "tiktok",
  "instagram",
  "youtube",
];

/**
 * A connection's health. `connected` — the stored token is (or looks) usable;
 * `expired` — a token expiry is set and in the past, so the creator should
 * reconnect. Widened to `string` at use sites for forward-compatibility.
 */
export type ConnectionStatus = "connected" | "expired";

/**
 * One connected social account from GET /me/connections and the callback. This
 * shape NEVER carries an access/refresh token — only the `provider`, the
 * provider-side `external_account_id`, the connection `status`, the granted
 * `scopes` and timestamps, enough for a "Connected accounts" UI. `connected` is
 * a convenience boolean (always `true` for a returned row). The index signature
 * preserves any forward-compatible fields the backend adds.
 */
export interface Connection {
  /** Provider id; widened to `string` for forward-compatibility. */
  provider: SocialProvider | string;
  /** The provider-side account id (e.g. TikTok open_id); may be blank. */
  external_account_id: string;
  /** Convenience flag — always `true` for a returned connection row. */
  connected: boolean;
  /** Connection health; widened to `string` for forward-compatibility. */
  status: ConnectionStatus | string;
  /** Comma-separated granted OAuth scopes (may be blank). */
  scopes: string;
  /** ISO-8601 token expiry, when the provider supplies one. */
  token_expires_at?: string | null;
  /** ISO-8601 timestamp the account was first connected, when available. */
  connected_at?: string | null;
  /** ISO-8601 last-updated timestamp, when available. */
  updated_at?: string | null;
  [key: string]: unknown;
}

/**
 * The opaque authorize URL + single-use CSRF `state` from
 * GET /connections/{provider}/authorize. Open `authorize_url` in the browser
 * (it already embeds `state`); the provider redirects back to the callback with
 * `code` + the same `state`, which the client passes to {@link completeConnect}.
 * Nothing sensitive is returned.
 */
export interface AuthorizeInfo {
  /** Provider the authorize URL targets. */
  provider: SocialProvider | string;
  /** Provider authorize URL to send the browser to (embeds `state`). */
  authorize_url: string;
  /** Opaque, single-use CSRF token echoed back on the callback. */
  state: string;
}

/**
 * The outcome of a direct publish from POST /jobs/{id}/publish/{provider}
 * (token-free). `external_post_id`/`url` identify the created post when the
 * provider returns them; `status` is `"published"` on success. The index
 * signature preserves any forward-compatible fields the backend adds.
 */
export interface PublishResult {
  /** Provider the job was published to. */
  provider: SocialProvider | string;
  /** Provider-side post/video id, when returned. */
  external_post_id: string;
  /** Public URL of the created post, when returned. */
  url: string;
  /** Publish status; `"published"` on success. */
  status: string;
  [key: string]: unknown;
}

/** Acknowledgement returned by DELETE /me/connections/{provider}. */
export interface DisconnectResult {
  /** True when the connection was removed. */
  disconnected: boolean;
  /** The provider that was disconnected. */
  provider: SocialProvider | string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// ReelForge Template Marketplace (publish / browse / clone / rate)
//
// Backs the auth-gated endpoints in app/controllers/v1/marketplace.py. Creators
// publish an IMMUTABLE snapshot of a job template to a PUBLIC marketplace; any
// authed user can browse/search, view a listing, CLONE it into their own saved
// templates, and RATE it 1..5 (one upserted rating per user). Only the author
// can edit/unpublish their own listing. Mirrors web/lib/types.ts.
// ---------------------------------------------------------------------------

/** Lowest / highest allowed marketplace star rating (inclusive). */
export const MIN_MARKETPLACE_STARS = 1;
export const MAX_MARKETPLACE_STARS = 5;

/** Hard cap the backend enforces on a marketplace browse page (`limit`). */
export const MAX_MARKETPLACE_LIMIT = 100;
/** Default browse page size requested by the marketplace screen. */
export const DEFAULT_MARKETPLACE_LIMIT = 20;

/**
 * A public marketplace listing from GET /marketplace and
 * GET /marketplace/{id}. Mirrors `MarketplaceTemplateModel` /
 * `_listing_public_data` in the backend (permissive: the detail endpoint may
 * attach extra fields such as the caller's own `viewer_stars`). `params` is the
 * opaque render-knob snapshot copied at publish time.
 */
export interface MarketplaceTemplate {
  id: string;
  author_user_id: string;
  title: string;
  description: string;
  prompt: string;
  params: Record<string, unknown>;
  tags: string[];
  language: string;
  layout: string;
  /** Denormalised aggregate rating (0 when never rated). */
  rating_avg: number;
  /** Number of ratings backing `rating_avg`. */
  rating_count: number;
  /** How many times this listing has been cloned. */
  clone_count: number;
  published: boolean;
  created_at: string | null;
  updated_at: string | null;
  /** The caller's own rating (1..5), when the detail endpoint attaches it. */
  viewer_stars?: number | null;
  /**
   * Real-world "proven" performance score, attached ONLY on the `sort='proven'`
   * browse. It is a non-negative number for a listing whose downstream reels
   * carry logged performance, and `null`/absent otherwise (or for every other
   * sort). See {@link MarketplaceSort} and the `proven` sort.
   */
  win_score?: number | null;
  /**
   * REMIX TREES: the listing this one was remixed from, or `null` for an
   * original publish. A safe public provenance field surfaced in browse / detail
   * / lineage (never a private/financial datum). See {@link MarketplaceLineage}.
   */
  parent_template_id?: string | null;
  /** REMIX TREES: how many published listings directly descend from this one. */
  remix_count?: number;
  [key: string]: unknown;
}

/**
 * Sort order for GET /marketplace: highest-rated (`top`), newest (`new`),
 * most-cloned (`clones`), by real-world win-score (`proven`), or most-remixed
 * (`most_remixed`, ranked by {@link MarketplaceTemplate.remix_count}). Only
 * `proven` annotates each listing with a {@link MarketplaceTemplate.win_score}.
 */
export type MarketplaceSort =
  | "top"
  | "new"
  | "clones"
  | "proven"
  | "most_remixed";

/** Query params for GET /marketplace. All optional; the backend clamps them. */
export interface MarketplaceBrowseParams {
  /** Free-text search over title/description (max 200 chars server-side). */
  query?: string;
  /** Restrict to listings carrying this tag. */
  tag?: string;
  /** Restrict to a language code (e.g. "en", "tr"). */
  language?: string;
  /** Sort order (defaults to "top" server-side). */
  sort?: MarketplaceSort;
  /** Page size (clamped to 1..100 server-side). */
  limit?: number;
  /** Row offset (clamped to >= 0 server-side). */
  offset?: number;
}

/**
 * Request body for POST /marketplace/publish. Either reference a private
 * template the caller owns via `template_id` to snapshot it, or pass the
 * snapshot inline. A resolved `title` is required (empty -> 400 server-side).
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

/** The private template created by POST /marketplace/{id}/clone. */
export interface ClonedTemplate {
  id: string;
  name: string;
  source_marketplace_id: string;
  [key: string]: unknown;
}

/** Acknowledgement returned by DELETE /marketplace/{id} (author-only unpublish). */
export interface MarketplaceUnpublishResult {
  unpublished: boolean;
  id: string;
  [key: string]: unknown;
}

/**
 * The remix-tree lineage of a listing from GET /marketplace/{id}/lineage.
 * `ancestors` walks UP the `parent_template_id` chain (immediate parent first →
 * root); `children` are the DIRECT, still-published remixes (newest-first).
 * Every entry is a safe public {@link MarketplaceTemplate}. An unknown id yields
 * an empty tree (`{ ancestors: [], children: [] }`). Mirrors
 * `MarketplaceLineageData` in the backend.
 */
export interface MarketplaceLineage {
  /** Immediate parent → root (safe public listings). */
  ancestors: MarketplaceTemplate[];
  /** Direct, still-published remixes, newest-first (safe public listings). */
  children: MarketplaceTemplate[];
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Hook Performance Loop
// (POST/GET /jobs/{id}/performance, GET /me/performance,
//  GET /me/winning-hooks, GET /me/winning-templates — see
//  app/controllers/v1/performance.py)
//
// Creators self-report the real-world outcome of a posted reel (views, likes,
// comments, shares, saves, watch-through %). All writes are strictly scoped to
// the caller's OWN job; all reads only ever surface the caller's own reels and
// aggregates. Metrics are key-free (creator-entered) — no platform API.
// ---------------------------------------------------------------------------

/** Optional platforms a reel can be logged against (widened for forward-compat). */
export type PerformancePlatform =
  | "tiktok"
  | "instagram"
  | "youtube"
  | "other";

/** The platforms offered by the logging form, in display order. */
export const PERFORMANCE_PLATFORMS: readonly PerformancePlatform[] = [
  "tiktok",
  "instagram",
  "youtube",
  "other",
];

/**
 * Request body for POST /jobs/{job_id}/performance. Every field is optional so
 * a creator can log only what they have; the backend validates + clamps each
 * (non-negative counts; `retention_pct` in [0,100]) and upserts one row per job.
 */
export interface LogPerformanceRequest {
  platform?: PerformancePlatform | string;
  views?: number;
  likes?: number;
  comments?: number;
  shares?: number;
  saves?: number;
  /** Watch-through / retention percentage, 0..100. */
  retention_pct?: number;
}

/**
 * The caller's stored metrics for one job, returned by POST/GET
 * /jobs/{job_id}/performance. One row per job (re-logging updates it).
 */
export interface JobPerformance {
  id: string;
  job_id: string;
  platform: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  retention_pct: number;
  /** ISO-8601 timestamps, when available. */
  logged_at: string | null;
  updated_at: string | null;
  [key: string]: unknown;
}

/**
 * A winning hook aggregate from GET /me/winning-hooks — a hook line ranked by a
 * deterministic `win_score` over the caller's logged reels.
 */
export interface WinningHook {
  hook: string;
  win_score: number;
  reels: number;
  views: number;
  engagements: number;
  avg_retention_pct: number;
  [key: string]: unknown;
}

/** A winning template aggregate from GET /me/winning-templates. */
export interface WinningTemplate {
  template: string;
  win_score: number;
  reels: number;
  views: number;
  engagements: number;
  avg_retention_pct: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Public Share Links (POST /jobs/{id}/share, DELETE /me/shares/{token},
// GET /public/r/{token})
//
// A creator mints an unguessable, REVOCABLE public link for one of their OWN
// reels. The owner-facing {@link ShareLink} carries private-but-owner-safe fields
// (job_id, view_count); the UNAUTHENTICATED public page ({@link SharePublic}) is
// STRICT and exposes ONLY safe fields — never the clean result key, the owning
// user, or any private financial. Backed by app/controllers/v1/share.py.
// ---------------------------------------------------------------------------

/**
 * The owner-facing share link from POST /jobs/{id}/share. `token` is the
 * unguessable public handle; `url` is the built public share-page link (or a
 * relative `/r/{token}` when no base URL is configured server-side). This shape
 * is scoped to the reel's owner, so exposing `job_id` / `view_count` here is
 * safe — it is NEVER used for the unauthenticated public page.
 */
export interface ShareLink {
  /** Unguessable public token — the path param for revoke + public view. */
  token: string;
  /** Built public share-page URL (may be a relative `/r/{token}`). */
  url: string;
  /** The reel this link points at (owner-only field). */
  job_id: string;
  /** How many times the public page has been viewed (owner-only field). */
  view_count: number;
  /** True once the link has been revoked (can no longer be viewed). */
  revoked: boolean;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  [key: string]: unknown;
}

/**
 * The SAFE public share-page payload from GET /public/r/{token} (NO auth). This
 * shape is STRICT by design: it carries ONLY the reel's title, a WATERMARKED
 * preview URL, the created-at, and the sharer's referral code. It NEVER exposes
 * the clean (un-watermarked) result key, the owning `user_id`, `view_count`, or
 * any private financial (credits / cost / revenue). Mirrors `SharePublicModel`
 * / `app.services.share.SAFE_PUBLIC_FIELDS` exactly.
 */
export interface SharePublic {
  /** The reel's title/headline. */
  title: string;
  /** Presigned GET URL for the WATERMARKED preview clip (safe to show). */
  watermarked_preview_url: string;
  /** ISO-8601 creation timestamp, when available. */
  created_at?: string | null;
  /** The sharer's referral code, for a "made with ReelForge" attribution CTA. */
  sharer_referral_code: string;
}

/**
 * Acknowledgement returned by DELETE /me/shares/{token}. `revoked` is `true`
 * only when a live link belonging to the caller was flipped to revoked; a
 * foreign / unknown / already-revoked token is a harmless `{ revoked: false }`
 * (never a 404-that-confirms-existence), so a caller can never probe another
 * user's tokens.
 */
export interface ShareRevokeResult {
  revoked: boolean;
  token: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Creator Profiles + Follow Graph + Leaderboards
// (GET /creators/leaderboard, GET /creators/{handle_or_id},
//  POST/DELETE /creators/{id}/follow, GET /me/following, PATCH /me/profile)
//
// Public creator identity + a directed follow graph + a documented, deterministic
// reputation leaderboard. Every PUBLIC surface (profile / leaderboard / following)
// exposes ONLY safe fields — never credits, email, cost/revenue, or another
// user's private data. Backed by app/controllers/v1/creators.py.
// ---------------------------------------------------------------------------

/**
 * A SAFE public creator profile from GET /creators/{handle_or_id},
 * GET /me/following and PATCH /me/profile. Carries a creator's public identity
 * (handle / display_name / bio) plus their PUBLIC reputation aggregates. It
 * NEVER exposes credits, email, cost/revenue, or `user_id` (the backend model is
 * STRICT). Mirrors `CreatorProfileModel` / `app.services.creators.SAFE_PROFILE_FIELDS`.
 */
export interface CreatorProfile {
  /** Public handle slug, e.g. "jane-makes-reels" (may be blank if unset). */
  handle: string;
  /** Display name (may be blank). */
  display_name: string;
  /** Short public bio (may be blank). */
  bio: string;
  /** How many templates this creator has published to the marketplace. */
  published_template_count: number;
  /** Total clones their published listings have received. */
  total_clones_received: number;
  /** Weighted average marketplace rating across their listings, in [0, 5]. */
  avg_rating: number;
  /** How many creators follow this creator. */
  follower_count: number;
  /** How many creators this creator follows. */
  following_count: number;
}

/**
 * The result of POST/DELETE /creators/{id}/follow. `following` is the caller's
 * new follow-state toward the target; `follower_count` is the target's refreshed
 * follower total; `removed` is set (true/false) only on the DELETE (unfollow)
 * path. Safe — carries no private data.
 */
export interface FollowResult {
  /** The caller's new follow-state toward the target creator. */
  following: boolean;
  /** The target creator's refreshed follower count. */
  follower_count: number;
  /** Whether a follow row was removed (DELETE/unfollow path only). */
  removed?: boolean | null;
  [key: string]: unknown;
}

/**
 * A leaderboard ranking metric for GET /creators/leaderboard. Only these values
 * are honoured server-side; an unknown value normalises to `reputation`. Mirrors
 * `LEADERBOARD_METRICS` in `app/services/creators.py`.
 */
export type LeaderboardMetric =
  | "reputation"
  | "followers"
  | "clones"
  | "rating"
  | "published"
  | "win_score";

/** The selectable leaderboard metrics, in display order (default first). */
export const LEADERBOARD_METRICS: readonly LeaderboardMetric[] = [
  "reputation",
  "followers",
  "clones",
  "rating",
  "published",
  "win_score",
];

/** Hard cap the backend enforces on a leaderboard page (`limit`). */
export const MAX_LEADERBOARD_LIMIT = 100;
/** Default leaderboard page size requested by the leaderboard screen. */
export const DEFAULT_LEADERBOARD_LIMIT = 20;

/**
 * One ranked creator from GET /creators/leaderboard. Carries the safe public
 * profile aggregates plus the documented, deterministic `reputation_score`, the
 * gaming-resistant `win_score` anchor, a 1-based `rank`, and the addressing
 * `user_id` / `handle` (the only id kept, for deep-linking to the profile). It
 * NEVER exposes credits, email, cost/revenue, or any other private field.
 */
export interface LeaderboardEntry {
  /** Addressing id — deep-link target for GET /creators/{handle_or_id}. */
  user_id: string;
  /** Public handle slug (may be blank if unset). */
  handle: string;
  /** Display name (may be blank). */
  display_name: string;
  /** How many templates this creator has published. */
  published_template_count: number;
  /** Total clones their listings have received. */
  total_clones_received: number;
  /** Weighted average marketplace rating, in [0, 5]. */
  avg_rating: number;
  /** How many creators follow this creator. */
  follower_count: number;
  /** How many creators this creator follows. */
  following_count: number;
  /** Gaming-resistant downstream win-score anchor, in [0, 100]. */
  win_score: number;
  /** Composite, documented reputation score (see the backend formula). */
  reputation_score: number;
  /** 1-based rank in the returned page. */
  rank: number;
  [key: string]: unknown;
}

/**
 * Request body for PATCH /me/profile. Every field is optional — only the fields
 * set are updated. `handle` is normalised to a lowercase slug and shape-validated
 * server-side (a bad shape → 422, a taken handle → 409); all three are safe,
 * public identity fields.
 */
export interface ProfileUpdateRequest {
  /** New public handle (3..64 chars, `[a-z0-9]` slug joined by `-`/`_`). */
  handle?: string;
  /** New display name (max 200 chars). */
  display_name?: string;
  /** New public bio (max 2000 chars). */
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
