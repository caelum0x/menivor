/**
 * Typed fetch client for the ReelForge backend v1 API (§5 of
 * docs/reelforge/INTEGRATION_CONTRACT.md).
 *
 * Auth: every request sends an `x-api-key` header. The value is either an
 * explicit per-call token (e.g. a Clerk JWT retrieved via `getToken()`) or,
 * as a fallback, the public app key from NEXT_PUBLIC_APP_API_KEY. No secrets
 * are hardcoded here.
 */

import type {
  AdminJob,
  AdminListParams,
  AdminUser,
  AdminWorkspace,
  SSOConnection,
  SSOConfigRequest,
  SSOMetadata,
  ScimToken,
  SecurityPolicy,
  SecurityPolicyRequest,
  Subscription,
  SubscribeRequest,
  SubscribeResult,
  ChangePlanRequest,
  Entitlements,
  Usage,
  Invoice,
  Revenue,
  WebhookSubscription,
  CreatedWebhookSubscription,
  WebhookSubscribeRequest,
  WebhookDelivery,
  DeveloperPortal,
  DataExport,
  ErasureRequest,
  ConsentRecord,
  ConsentUpdateRequest,
  RetentionPolicy,
  RetentionUpdateRequest,
  Analytics,
  AnalyticsBurnPoint,
  AnalyticsCostPoint,
  AnalyticsHookCount,
  AnalyticsTemplateCount,
  ApiKey,
  AuditEntry,
  AuditLogParams,
  Impersonation,
  Permission,
  Permissions,
  ApiKeyCreateRequest,
  ApiKeyRevokeResult,
  ApiKeyUsage,
  CreatedApiKey,
  Connection,
  AuthorizeInfo,
  PublishResult,
  PilotCapabilities,
  DisconnectResult,
  SocialProvider,
  Avatar,
  BackgroundClip,
  LaunchStatus,
  CreateAvatarRequest,
  CustomAvatar,
  BatchData,
  BatchJob,
  Brand,
  BrandUpdateRequest,
  BrollClip,
  BrollGenerateRequest,
  BrollGeneration,
  BrollPreset,
  SuggestBrollParams,
  SuggestBrollResult,
  CaptionStyle,
  CheckoutRequest,
  CheckoutResult,
  CloneVoiceRequest,
  VoiceVerificationPhrase,
  CoverStyle,
  CreateWorkspaceRequest,
  GenerateCoverRequest,
  GenerateCoverResult,
  DubLanguage,
  DubResult,
  EditorExportRequest,
  GrantWorkspaceCreditsRequest,
  InviteMemberRequest,
  LeaveWorkspaceResult,
  Member,
  RemoveMemberResult,
  Workspace,
  WorkspaceCredits,
  WorkspaceRole,
  GenerateIdeasRequest,
  HookCatalog,
  Idea,
  Insights,
  Job,
  JobCreateRequest,
  JobCreateResult,
  JobPerformance,
  LogPerformanceRequest,
  ListPerformanceParams,
  WinningHook,
  WinningTemplate,
  LayoutOption,
  MarketplaceBrowseParams,
  MarketplaceLineage,
  MarketplaceTemplate,
  PublishTemplateRequest,
  ClonedTemplate,
  UnpublishTemplateResult,
  ShareLink,
  SharePublic,
  ShareRevokeResult,
  CreatorProfile,
  FollowResult,
  LeaderboardEntry,
  LeaderboardParams,
  ProfileUpdateRequest,
  ListNotificationsParams,
  MarkAllNotificationsReadResult,
  MarkNotificationReadResult,
  Me,
  MusicGenerator,
  MusicTrack,
  Notification,
  NotificationListResult,
  PaymentProvider,
  Plan,
  Preset,
  PresetCreateRequest,
  PresetDeleteResult,
  PresignRequest,
  PresignResult,
  RedeemResult,
  Referral,
  RerunOverrides,
  SavedIdea,
  SavedIdeaDeleteResult,
  ScheduledCancelResult,
  ScheduledPublish,
  ScheduledPublishStatus,
  SchedulePublishRequest,
  SocialMeta,
  SocialPlatform,
  GenerateSocialRequest,
  Template,
  UnreadCountResult,
  UserVoice,
  Voice,
  VoiceDeleteResult,
} from "@/lib/types";
import {
  API_BASE,
  ApiError,
  POLL_INTERVAL_MS,
  apiRequest as request,
  type RequestOptions,
} from "@/src/shared/api";
export { API_BASE, ApiError, POLL_INTERVAL_MS, type RequestOptions } from "@/src/shared/api";
export * from "@/lib/library-api";
import {
  BROLL_MAX_AMOUNT,
  BROLL_MIN_AMOUNT,
  isTerminalState,
  LEADERBOARD_LIMIT_MAX,
  LEADERBOARD_LIMIT_MIN,
  MARKETPLACE_LIMIT_MAX,
  MARKETPLACE_LIMIT_MIN,
  PAYMENT_PROVIDERS,
  PERFORMANCE_LIMIT_MAX,
  PERFORMANCE_LIMIT_MIN,
  RATING_MAX,
  RATING_MIN,
  RETENTION_PCT_MAX,
  RETENTION_PCT_MIN,
  WATERMARK_DEFAULT_OPACITY,
  WATERMARK_DEFAULT_POSITION,
  WATERMARK_OPACITY_MAX,
  WATERMARK_OPACITY_MIN,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// §5 endpoints
// ---------------------------------------------------------------------------

/** POST /uploads/presign */
export function presign(
  body: PresignRequest,
  options?: RequestOptions,
): Promise<PresignResult> {
  return request<PresignResult>("/uploads/presign", {
    method: "POST",
    body,
    options,
  });
}

/**
 * POST /jobs — create + enqueue one or more ReelForge jobs.
 *
 * `body` may carry the creator-studio fields (`variants`, `caption_style`,
 * `music_id`, `webhook_url`, `tos_disclosure`) in addition to `params`. With
 * `variants > 1` the result additionally carries `job_ids` for every created
 * variant (see {@link JobCreateResult}). Set `body.workspace_id` to charge the
 * job to a workspace's SHARED credit pool instead of the caller's personal
 * balance (the caller must be a member of that workspace). Set
 * `body.voiceover_key` (BRING YOUR OWN VOICEOVER) to the R2 key of the creator's
 * own uploaded narration audio, in which case that audio replaces TTS and its
 * whisper transcript drives the captions + avatar lip-sync (see
 * {@link JobCreateRequest.voiceover_key}). Set `body.auto_tighten` to remove
 * dead air (silent/static gaps) from the screen recording before compose (see
 * {@link JobCreateRequest.auto_tighten}). The opt-in editing-polish flags
 * `body.auto_zoom` / `body.camera_motion` / `body.remove_bg` add scene-driven
 * punch-in zoom, a virtual camera move, and avatar background matting — each a
 * degrade-safe pre-compose pass that never touches narration or captions.
 */
export function createJob(
  body: JobCreateRequest,
  options?: RequestOptions,
): Promise<JobCreateResult> {
  return request<JobCreateResult>("/jobs", { method: "POST", body, options });
}

/**
 * POST /jobs/{id}/rerun — clone a job's params, apply `overrides`, and enqueue
 * it as a brand-new job. Returns the new job's status envelope.
 */
export function rerunJob(
  id: string,
  overrides: RerunOverrides,
  options?: RequestOptions,
): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}/rerun`, {
    method: "POST",
    body: { overrides },
    options,
  });
}

/**
 * GET /jobs — the caller's job history (backed by `JobRepository.list_for_user`,
 * §4.3). The backend may return the list directly as `data` or wrapped as
 * `{ jobs: [...] }`; both shapes are normalized to a `Job[]` here.
 */
export async function listJobs(options?: RequestOptions): Promise<Job[]> {
  const data = await request<Job[] | { jobs?: Job[] }>("/jobs", { options });
  if (Array.isArray(data)) return data;
  return data?.jobs ?? [];
}

/** GET /jobs/{id} */
export function getJob(id: string, options?: RequestOptions): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}`, { options });
}

/** POST /jobs/{id}/exports — enqueue an exact non-destructive reel cut. */
export function createEditorExport(
  id: string,
  body: EditorExportRequest,
  options?: RequestOptions,
): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}/exports`, {
    method: "POST",
    body,
    options,
  });
}

/** OpenCut-style timeline export: multi-segment trims + captions + overlays. */
export interface TimelineExportBody {
  segments: {
    source_in: number;
    source_out: number;
    speed?: number;
    caption?: string | null;
  }[];
  overlays: {
    text: string;
    start_s: number;
    end_s: number;
    position: "top" | "center" | "bottom";
  }[];
}

/** POST /jobs/{id}/timeline-exports — enqueue a multi-clip EDL export. */
export function createTimelineExport(
  id: string,
  body: TimelineExportBody,
  options?: RequestOptions,
): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}/timeline-exports`, {
    method: "POST",
    body,
    options,
  });
}

/** URL → reel: extracted content + a submittable reel draft. */
export interface ReelDraft {
  video_subject: string;
  hook: string;
  video_script: string;
  broll_prompts: string[];
}

export interface UrlIngestResult {
  url: string;
  content: { title: string; description: string; features: string[] };
  reel_draft: ReelDraft;
}

/** POST /ingest/url — turn a product/article URL into a reel draft. */
export function ingestUrl(
  url: string,
  options?: RequestOptions,
): Promise<UrlIngestResult> {
  return request<UrlIngestResult>("/ingest/url", {
    method: "POST",
    body: { url },
    options,
  });
}

/**
 * GET /batches/{id} — every variant job created by a single multi-variant
 * `POST /jobs`. The backend may return the list directly as `data`, wrapped as
 * `{ jobs: [...] }`, or as a bare array; all shapes are normalized to
 * {@link BatchData} here.
 */
export async function getBatch(
  id: string,
  options?: RequestOptions,
): Promise<BatchData> {
  const data = await request<BatchData | BatchJob[]>(
    `/batches/${encodeURIComponent(id)}`,
    { options },
  );
  if (Array.isArray(data)) return { jobs: data };
  return { batch_id: data.batch_id, jobs: data.jobs ?? [] };
}

/** POST /jobs/{id}/retry */
export function retryJob(id: string, options?: RequestOptions): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}/retry`, {
    method: "POST",
    options,
  });
}

// ---------------------------------------------------------------------------
// AI B-roll cutaways (POST /jobs/{id}/broll/suggest)
// ---------------------------------------------------------------------------

/**
 * POST /jobs/{id}/broll/suggest — suggest short, muted stock clips relevant to
 * the reel. The backend derives keywords from the reel's subject/script (via
 * `generate_terms`) and pulls candidate clips from MPT's vendored Pexels/Pixabay
 * integration (`download_videos` + `material_cache`), returning each cached
 * clip's R2 `key` to send as a job's `broll_intro_key` / `broll_outro_key`.
 *
 * `params.source` optionally pins the provider and `params.amount` bounds the
 * count (clamped to `[BROLL_MIN_AMOUNT, BROLL_MAX_AMOUNT]` before sending). The
 * backend may return the list directly as `data`, wrapped as `{ clips: [...] }`,
 * or as a bare array; all shapes are normalized to `{ clips }` here, and entries
 * without a usable `key` are dropped at this boundary.
 */
export async function suggestBroll(
  jobId: string,
  params: SuggestBrollParams = {},
  options?: RequestOptions,
): Promise<SuggestBrollResult> {
  const body: SuggestBrollParams = {};
  if (params.source) body.source = params.source;
  if (typeof params.amount === "number" && Number.isFinite(params.amount)) {
    body.amount = Math.min(
      BROLL_MAX_AMOUNT,
      Math.max(BROLL_MIN_AMOUNT, Math.trunc(params.amount)),
    );
  }

  const data = await request<SuggestBrollResult | { clips?: BrollClip[] } | BrollClip[]>(
    `/jobs/${encodeURIComponent(jobId)}/broll/suggest`,
    { method: "POST", body, options },
  );

  const list = Array.isArray(data) ? data : (data?.clips ?? []);
  const clips = list.filter(
    (c): c is BrollClip =>
      Boolean(c) && typeof c.key === "string" && c.key.length > 0,
  );
  return { clips };
}

// ---------------------------------------------------------------------------
// AI B-roll Studio (POST /generation/broll/generate, GET /generation/broll/generations/{id})
// ---------------------------------------------------------------------------

/** Read the authenticated user's pilot feature availability before rendering generation controls. */
export function getPilotCapabilities(
  options?: RequestOptions,
): Promise<PilotCapabilities> {
  return request<PilotCapabilities>("/pilot/capabilities", { options });
}

/**
 * POST /broll/generate — start ONE async AI B-roll generation (text->video, or
 * image->video with an owned `image_key`). Generation is 30-120s of GPU, so the
 * backend returns immediately with an initial {@link BrollGeneration} snapshot
 * (`state === JobState.Processing`); poll {@link getBrollGeneration} until it
 * reaches a terminal state. On completion the snapshot carries the rendered
 * `broll_key` to send as a job's `broll_intro_key` / `broll_outro_key`.
 *
 * Fails clean: 503 when the generation provider is not configured, 402 on
 * insufficient credits, 400 on an empty/disallowed prompt, 403 for an
 * `image_key` the caller does not own.
 */
export function generateBroll(
  body: BrollGenerateRequest,
  options?: RequestOptions,
): Promise<BrollGeneration> {
  return request<BrollGeneration>("/generation/broll/generate", {
    method: "POST",
    body,
    options,
  });
}

/**
 * GET /broll/generations/{id} — poll one generation's state/progress (and, once
 * complete, its `broll_key`). Owner-scoped: an unknown/foreign id is a 404.
 */
export function getBrollGeneration(
  id: string,
  options?: RequestOptions,
): Promise<BrollGeneration> {
  return request<BrollGeneration>(
    `/generation/broll/generations/${encodeURIComponent(id)}`,
    { options },
  );
}

/**
 * GET /broll/presets — the caller's available AI B-roll motion presets (curated
 * global presets + any the caller owns/shared). The backend may return the list
 * directly as `data` or wrapped as `{ presets: [...] }`; both are normalized to
 * a `BrollPreset[]` here.
 */
export async function listBrollPresets(
  options?: RequestOptions,
): Promise<BrollPreset[]> {
  const data = await request<BrollPreset[] | { presets?: BrollPreset[] }>(
    "/generation/broll/presets",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.presets ?? [];
}

/**
 * GET /broll/generations — the caller's recent studio generations (newest
 * first), so a finished AI clip can be reused (e.g. as a reel's intro/outro
 * B-roll) without copy-paste. The backend may return the list directly as `data`
 * or wrapped as `{ generations: [...] }`; both are normalized here.
 */
export async function listBrollGenerations(
  options?: RequestOptions,
): Promise<BrollGeneration[]> {
  const data = await request<
    BrollGeneration[] | { generations?: BrollGeneration[] }
  >("/generation/broll/generations", { options });
  if (Array.isArray(data)) return data;
  return data?.generations ?? [];
}

/**
 * POST /uploads/register — record an already-uploaded `uploads/<uuid>` object
 * (from {@link presignAndUpload}) as an Asset OWNED by the caller, so a later
 * feature can verify ownership. Returns the uploaded `key` (echoed) to pass on.
 * Idempotent server-side. Only `uploads/` keys are accepted.
 */
export async function registerUpload(
  key: string,
  kind = "image",
  options?: RequestOptions,
): Promise<string> {
  const data = await request<{ key: string; asset_id: string }>(
    "/uploads/register",
    { method: "POST", body: { key, kind }, options },
  );
  return data.key;
}

/**
 * Upload an image and register it as a caller-owned Asset in one step, returning
 * its R2 key — ready to pass as an i2v reference (`image_key`) or avatar source.
 */
export async function uploadAndRegisterImage(
  file: File,
  options?: RequestOptions & { onProgress?: (fraction: number) => void },
): Promise<string> {
  const { key } = await presignAndUpload(file, options);
  return key;
}

// ---------------------------------------------------------------------------
// Multi-language dubbing (GET /dub/languages, POST /jobs/{id}/dub)
// ---------------------------------------------------------------------------

/**
 * GET /dub/languages — the languages a finished reel can be dubbed into. The
 * backend may return the list directly as `data` or wrapped as
 * `{ languages: [...] }`; both shapes are normalized to a `DubLanguage[]` here.
 */
export async function listDubLanguages(
  options?: RequestOptions,
): Promise<DubLanguage[]> {
  const data = await request<DubLanguage[] | { languages?: DubLanguage[] }>(
    "/dub/languages",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.languages ?? [];
}

/**
 * POST /jobs/{id}/dub — translate the source reel's script and render one dubbed
 * variant per language code in `languages`, reusing the source's screen
 * recording, avatar, voice, layout, and caption style. The created jobs share a
 * single `batch_id` reviewable via {@link getBatch}. `languages` must be a
 * non-empty list of supported codes (see {@link listDubLanguages}).
 */
export function dubJob(
  id: string,
  languages: string[],
  options?: RequestOptions,
): Promise<DubResult> {
  return request<DubResult>(`/jobs/${encodeURIComponent(id)}/dub`, {
    method: "POST",
    body: { languages },
    options,
  });
}

/**
 * Coerce a raw merged-avatar dict into a fully-usable {@link Avatar}. Preset
 * rows are serialised with `id` + `provider_avatar_id` but no `avatar_id`, so
 * derive a stable `avatar_id` (the value sent as `params.avatar_id`) from
 * whichever id is present. Entries that yield no usable id are dropped by the
 * caller. Never mutates the input.
 */
function normalizeAvatar(raw: Avatar): Avatar {
  const pick = (value: unknown): string =>
    typeof value === "string" ? value.trim() : "";
  const avatarId =
    pick(raw.avatar_id) || pick(raw.provider_avatar_id) || pick(raw.id);
  return { ...raw, avatar_id: avatarId };
}

/**
 * GET /avatars — the selectable avatars (the caller's stored `AvatarPreset`
 * rows, including CUSTOM photo→avatars, merged with the live provider catalog).
 * The backend may return the list directly as `data` or wrapped as
 * `{ avatars: [...] }`; both shapes are normalized to an `Avatar[]` here. Every
 * entry is normalized so `avatar_id` is always populated (preset rows carry
 * `id`/`provider_avatar_id` instead), and entries without any usable id are
 * dropped so callers only ever see selectable avatars.
 */
export async function listAvatars(
  options?: RequestOptions,
): Promise<Avatar[]> {
  const data = await request<Avatar[] | { avatars?: Avatar[] }>("/avatars", {
    options,
  });
  const list = Array.isArray(data) ? data : (data?.avatars ?? []);
  return list
    .map(normalizeAvatar)
    .filter((a): a is Avatar => a.avatar_id.length > 0);
}

/**
 * POST /avatars — CUSTOM AVATAR FROM A PHOTO. Turns the caller's uploaded selfie
 * (`body.image_key`, the R2 key from {@link presignAndUpload}) into a HeyGen
 * talking-photo avatar that lip-syncs a reel's narration, and stores it as an
 * owner-scoped `AvatarPreset`. `body.image_key` MUST reference an upload the
 * caller owns (403 otherwise). Returns the created {@link CustomAvatar}, whose
 * `provider_avatar_id` (HeyGen's `talking_photo_id`) is the value later sent as
 * a reel's `params.avatar_id`; it also appears in {@link listAvatars}.
 */
export function createAvatarFromPhoto(
  body: CreateAvatarRequest,
  options?: RequestOptions,
): Promise<CustomAvatar> {
  const payload: CreateAvatarRequest = { image_key: body.image_key };
  const displayName = body.display_name?.trim();
  if (displayName) payload.display_name = displayName;
  const voiceName = body.voice_name?.trim();
  if (voiceName) payload.voice_name = voiceName;
  return request<CustomAvatar>("/avatars", {
    method: "POST",
    body: payload,
    options,
  });
}

/** GET /voices */
export function listVoices(options?: RequestOptions): Promise<Voice[]> {
  return request<Voice[]>("/voices", { options });
}

/** GET /me */
export function getMe(options?: RequestOptions): Promise<Me> {
  return request<Me>("/me", { options });
}

// ---------------------------------------------------------------------------
// Brand Voice (voice cloning; auth-gated /voices/*)
// ---------------------------------------------------------------------------

/**
 * POST /voices/clone — turn a previously uploaded voice sample into a private
 * "brand voice" via ElevenLabs Instant Voice Clone. `body.sample_key` is the R2
 * key returned by {@link presignAndUpload}; `body.consent` MUST be `true` (the
 * caller's mandatory ownership/authorization attestation). Returns the new
 * {@link UserVoice}, whose `voice_id` is the `"elevenlabs:<id>"` narrator
 * selector selectable as a reel's `voice_name`.
 */
export function cloneVoice(
  body: CloneVoiceRequest,
  options?: RequestOptions,
): Promise<UserVoice> {
  return request<UserVoice>("/voices/clone", { method: "POST", body, options });
}

/**
 * POST /voices/verification-phrase — a fresh phrase the caller reads aloud
 * (M7.2). The recording is uploaded with {@link presignAndUpload} and sent with
 * the returned token to {@link cloneVoice}.
 */
export function getVoiceVerificationPhrase(
  options?: RequestOptions,
): Promise<VoiceVerificationPhrase> {
  return request<VoiceVerificationPhrase>("/voices/verification-phrase", {
    method: "POST",
    options,
  });
}

/**
 * GET /voices/mine — the caller's cloned brand voices (newest first). The
 * backend may return the list directly as `data` or wrapped as
 * `{ voices: [...] }`; both shapes are normalized to a `UserVoice[]` here.
 */
export async function listMyVoices(
  options?: RequestOptions,
): Promise<UserVoice[]> {
  const data = await request<UserVoice[] | { voices?: UserVoice[] }>(
    "/voices/mine",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.voices ?? [];
}

/**
 * DELETE /voices/mine/{id} — delete a cloned voice the caller owns. `id` is the
 * {@link UserVoice.id} row id (NOT the `voice_id` narrator selector).
 */
export function deleteMyVoice(
  id: string,
  options?: RequestOptions,
): Promise<VoiceDeleteResult> {
  return request<VoiceDeleteResult>(`/voices/mine/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}

// ---------------------------------------------------------------------------
// Billing endpoints
// ---------------------------------------------------------------------------

/**
 * GET /billing/plans — the purchasable credit packs. The backend may return
 * the list directly as `data` or wrapped as `{ plans: [...] }`; both shapes
 * are normalized to a `Plan[]` here.
 */
export async function listPlans(options?: RequestOptions): Promise<Plan[]> {
  const data = await request<Plan[] | { plans?: Plan[] }>("/billing/plans", {
    options,
  });
  if (Array.isArray(data)) return data;
  return data?.plans ?? [];
}

/**
 * GET /billing/providers — the payment providers currently ENABLED for checkout
 * (only those whose secrets are configured server-side). The backend may return
 * the list directly as `data` or wrapped as `{ providers: [...] }`; both shapes
 * are normalized here. Unknown provider strings are dropped at this boundary so
 * callers only ever see values the client knows how to render, preserving the
 * server's ordering.
 */
export async function getProviders(
  options?: RequestOptions,
): Promise<PaymentProvider[]> {
  const data = await request<
    PaymentProvider[] | { providers?: PaymentProvider[] }
  >("/billing/providers", { options });
  const list = Array.isArray(data) ? data : (data?.providers ?? []);
  const known = new Set<string>(PAYMENT_PROVIDERS);
  return list.filter((p): p is PaymentProvider => known.has(p as string));
}

/**
 * POST /billing/checkout — starts a hosted checkout for `plan_key` via the
 * chosen `provider` (`stripe`, `iyzico` for TR, or the merchant-of-record
 * platforms `creem`/`polar`) and returns the URL the buyer should be redirected
 * to. Only providers returned by {@link getProviders} are enabled. Pass
 * `body.workspace_id` to buy the pack for a workspace's SHARED credit pool
 * (admins/owners only) instead of the buyer's personal balance; the backend
 * fulfils it to the workspace pool idempotently.
 */
export function createCheckout(
  body: CheckoutRequest,
  options?: RequestOptions,
): Promise<CheckoutResult> {
  return request<CheckoutResult>("/billing/checkout", {
    method: "POST",
    body,
    options,
  });
}

// ---------------------------------------------------------------------------
// Creator-studio catalogs (read-only; GET /catalog/*)
// ---------------------------------------------------------------------------

/** GET /catalog/caption-styles */
export function listCaptionStyles(
  options?: RequestOptions,
): Promise<CaptionStyle[]> {
  return request<CaptionStyle[]>("/catalog/caption-styles", { options });
}

/** GET /catalog/music */
export function listMusic(options?: RequestOptions): Promise<MusicTrack[]> {
  return request<MusicTrack[]>("/catalog/music", { options });
}

/**
 * GET /catalog/music-generators — the AI background-music providers ENABLED for
 * the caller (only those whose API keys are configured server-side, via each
 * vendored provider's `is_enabled()` guard). Each entry is
 * `{ id, name, max_prompt_length }`; the UI shows "Generate with AI" only when
 * at least one is returned. The backend may return the list directly as `data`
 * or wrapped as `{ generators: [...] }`; both shapes are normalized here, and
 * malformed entries are dropped so callers only see usable providers (a
 * non-positive `max_prompt_length` is treated as "no cap").
 */
export async function listMusicGenerators(
  options?: RequestOptions,
): Promise<MusicGenerator[]> {
  const data = await request<MusicGenerator[] | { generators?: MusicGenerator[] }>(
    "/catalog/music-generators",
    { options },
  );
  const list = Array.isArray(data) ? data : (data?.generators ?? []);
  return list
    .filter(
      (g): g is MusicGenerator =>
        Boolean(g) && typeof g.id === "string" && g.id.length > 0,
    )
    .map((g) => ({
      ...g,
      name: typeof g.name === "string" && g.name ? g.name : g.id,
      max_prompt_length:
        typeof g.max_prompt_length === "number" &&
        Number.isFinite(g.max_prompt_length) &&
        g.max_prompt_length > 0
          ? Math.trunc(g.max_prompt_length)
          : 0,
    }));
}

/** GET /catalog/layouts */
export function listLayouts(options?: RequestOptions): Promise<LayoutOption[]> {
  return request<LayoutOption[]>("/catalog/layouts", { options });
}

/** GET /catalog/templates */
export function listTemplates(options?: RequestOptions): Promise<Template[]> {
  return request<Template[]>("/catalog/templates", { options });
}

/**
 * GET /templates/backgrounds — the curated loop-able background-footage
 * library for reels built WITHOUT a screen recording (`params.background_id`
 * on the avatar-less `captions_only` path). Optionally filtered by category.
 */
export async function listBackgrounds(
  category?: string,
  options?: RequestOptions,
): Promise<BackgroundClip[]> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : "";
  const data = await request<{ backgrounds?: BackgroundClip[] }>(
    `/templates/backgrounds${qs}`,
    { options },
  );
  return data?.backgrounds ?? [];
}

/**
 * GET /launch/status — non-sensitive server launch gates (`features.checkout`
 * gates purchases, `features.publishing` gates cross-posting). Public route:
 * requested anonymously so marketing surfaces can read it pre-session.
 */
export function getLaunchStatus(
  options?: RequestOptions,
): Promise<LaunchStatus> {
  return request<LaunchStatus>("/launch/status", { options, anonymous: true });
}

/**
 * GET /catalog/hooks — native hook lines keyed by language code. Returns an
 * empty map when the catalog is unavailable (the backend degrades to `{}`).
 */
export function listHooks(options?: RequestOptions): Promise<HookCatalog> {
  return request<HookCatalog>("/catalog/hooks", { options });
}

// ---------------------------------------------------------------------------
// Cover / thumbnail generator (GET /catalog/cover-styles, POST /jobs/{id}/cover)
// ---------------------------------------------------------------------------

/**
 * GET /catalog/cover-styles — the selectable cover/thumbnail render styles. The
 * backend may return the list directly as `data` or wrapped as
 * `{ styles: [...] }`; both shapes are normalized to a `CoverStyle[]` here.
 */
export async function listCoverStyles(
  options?: RequestOptions,
): Promise<CoverStyle[]> {
  const data = await request<CoverStyle[] | { styles?: CoverStyle[] }>(
    "/catalog/cover-styles",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.styles ?? [];
}

/**
 * POST /jobs/{id}/cover — render a 1080x1920 cover image for the reel: the job's
 * poster frame (or a gradient fallback) with `body.headline` overlaid as a bold
 * headline in the chosen `body.style`. Both fields are optional (the backend
 * defaults the headline to the reel's hook and the style to the first preset).
 * The result is uploaded to R2 and stored as `Job.cover_key`; call again with a
 * different headline/style to regenerate. Returns {@link GenerateCoverResult}.
 */
export function generateCover(
  jobId: string,
  body: GenerateCoverRequest = {},
  options?: RequestOptions,
): Promise<GenerateCoverResult> {
  return request<GenerateCoverResult>(
    `/jobs/${encodeURIComponent(jobId)}/cover`,
    { method: "POST", body, options },
  );
}

// ---------------------------------------------------------------------------
// AI Social Caption & Hashtags (GET /catalog/social-platforms,
// POST /jobs/{id}/social) — generate an optimized post title + caption +
// hashtags for a finished reel, tailored to a target platform. Built server-side
// on the vendored MPT `generate_social_metadata`; the subject/script come from
// the job's own persisted data (no free-text prompt is accepted).
// ---------------------------------------------------------------------------

/**
 * GET /catalog/social-platforms — the platforms the social-caption generator can
 * tailor copy for (each `{ id, name }`). The backend may return the list directly
 * as `data` or wrapped as `{ platforms: [...] }`; both shapes are normalized to a
 * `SocialPlatform[]` here, and entries without a usable `id` are dropped so
 * callers only ever see selectable platforms.
 */
export async function listSocialPlatforms(
  options?: RequestOptions,
): Promise<SocialPlatform[]> {
  const data = await request<SocialPlatform[] | { platforms?: SocialPlatform[] }>(
    "/catalog/social-platforms",
    { options },
  );
  const list = Array.isArray(data) ? data : (data?.platforms ?? []);
  return list
    .filter(
      (p): p is SocialPlatform =>
        Boolean(p) && typeof p.id === "string" && p.id.length > 0,
    )
    .map((p) => ({
      ...p,
      name: typeof p.name === "string" && p.name ? p.name : String(p.id),
    }));
}

/**
 * POST /jobs/{id}/social — generate optimized post copy (title + caption +
 * hashtags) for a finished reel, tailored to `body.platform`. `body.language` is
 * optional: omit it to generate in the job's own configured language. The
 * subject/script are derived server-side from the job's persisted data, so no
 * free-text prompt is sent. The result is normalized so `title`/`caption` are
 * always strings and `hashtags` a string array (blank tags dropped) even if the
 * backend envelope is partial.
 */
export async function generateSocial(
  jobId: string,
  body: GenerateSocialRequest,
  options?: RequestOptions,
): Promise<SocialMeta> {
  const payload: GenerateSocialRequest = { platform: body.platform };
  const language = body.language?.trim();
  if (language) payload.language = language;

  const data = await request<Partial<SocialMeta>>(
    `/jobs/${encodeURIComponent(jobId)}/social`,
    { method: "POST", body: payload, options },
  );

  const hashtags = Array.isArray(data?.hashtags)
    ? data.hashtags.filter(
        (t): t is string => typeof t === "string" && t.trim().length > 0,
      )
    : [];
  return {
    title: typeof data?.title === "string" ? data.title : "",
    caption: typeof data?.caption === "string" ? data.caption : "",
    hashtags,
  };
}

// ---------------------------------------------------------------------------
// Growth surfaces (auth-gated; GET/POST /me/*)
// ---------------------------------------------------------------------------

/** GET /me/insights */
export function getInsights(options?: RequestOptions): Promise<Insights> {
  return request<Insights>("/me/insights", { options });
}

// ---------------------------------------------------------------------------
// Creator BI analytics (GET /me/analytics?days=) — a richer, strictly
// caller-scoped dashboard. The backend clamps `days` to [1, 365]; this client
// normalizes a possibly-partial envelope so every field is populated (arrays
// never null, numeric metrics never NaN) and the dashboard always renders.
// ---------------------------------------------------------------------------

function toFiniteNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function toCountMap(value: unknown): Record<string, number> {
  if (!value || typeof value !== "object") return {};
  const out: Record<string, number> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    out[key] = toFiniteNumber(raw);
  }
  return out;
}

function normalizeCostByDay(value: unknown): AnalyticsCostPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((p): p is Record<string, unknown> => Boolean(p) && typeof p === "object")
    .map((p) => ({
      date: typeof p.date === "string" ? p.date : "",
      cost_usd: toFiniteNumber(p.cost_usd),
    }))
    .filter((p) => p.date.length > 0);
}

function normalizeBurnByDay(value: unknown): AnalyticsBurnPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((p): p is Record<string, unknown> => Boolean(p) && typeof p === "object")
    .map((p) => ({
      date: typeof p.date === "string" ? p.date : "",
      spent: toFiniteNumber(p.spent),
    }))
    .filter((p) => p.date.length > 0);
}

function normalizeTemplates(value: unknown): AnalyticsTemplateCount[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((e): e is Record<string, unknown> => Boolean(e) && typeof e === "object")
    .map((e) => ({
      name: typeof e.name === "string" ? e.name : "",
      count: toFiniteNumber(e.count),
    }))
    .filter((e) => e.name.length > 0);
}

function normalizeHooks(value: unknown): AnalyticsHookCount[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((e): e is Record<string, unknown> => Boolean(e) && typeof e === "object")
    .map((e) => ({
      hook: typeof e.hook === "string" ? e.hook : "",
      count: toFiniteNumber(e.count),
    }))
    .filter((e) => e.hook.length > 0);
}

function normalizeAnalytics(
  data: Partial<Analytics> | null | undefined,
  requestedDays: number,
): Analytics {
  const funnel = (data?.funnel ?? {}) as Partial<Analytics["funnel"]>;
  const credits = (data?.credits ?? {}) as Partial<Analytics["credits"]>;
  const render = (data?.render_time ?? {}) as Partial<Analytics["render_time"]>;
  const totals = (data?.totals ?? {}) as Partial<Analytics["totals"]>;
  const top = (data?.top_content ?? {}) as Partial<Analytics["top_content"]>;

  return {
    user_id: typeof data?.user_id === "string" ? data.user_id : "",
    days: toFiniteNumber(data?.days, requestedDays),
    funnel: {
      created: toFiniteNumber(funnel.created),
      completed: toFiniteNumber(funnel.completed),
      failed: toFiniteNumber(funnel.failed),
      published: toFiniteNumber(funnel.published),
    },
    cost_by_day: normalizeCostByDay(data?.cost_by_day),
    credits: {
      balance: toFiniteNumber(credits.balance),
      spent: toFiniteNumber(credits.spent),
      burn_by_day: normalizeBurnByDay(credits.burn_by_day),
    },
    render_time: {
      p50_ms: toFiniteNumber(render.p50_ms),
      p90_ms: toFiniteNumber(render.p90_ms),
      avg_ms: toFiniteNumber(render.avg_ms),
      samples: toFiniteNumber(render.samples),
    },
    by_layout: toCountMap(data?.by_layout),
    by_language: toCountMap(data?.by_language),
    by_variants: toCountMap(data?.by_variants),
    totals: {
      jobs_total: toFiniteNumber(totals.jobs_total),
      videos_generated: toFiniteNumber(totals.videos_generated),
      total_cost_usd: toFiniteNumber(totals.total_cost_usd),
    },
    top_content: {
      templates: normalizeTemplates(top.templates),
      hooks: normalizeHooks(top.hooks),
    },
  };
}

/**
 * GET /me/analytics — the caller's BI analytics dashboard over the trailing
 * `days` window (funnel, cost-over-time, credit burn + live balance,
 * render-time percentiles, usage breakdowns and most-used templates/hooks).
 * Strictly caller-scoped server-side. `days` is sent as a query param when
 * provided (the backend clamps it to [1, 365]); the possibly-partial envelope
 * is normalized so every field is populated.
 */
export async function getAnalytics(
  days?: number,
  options?: RequestOptions,
): Promise<Analytics> {
  const requestedDays =
    typeof days === "number" && Number.isFinite(days) ? Math.trunc(days) : 30;
  const qs =
    typeof days === "number" && Number.isFinite(days)
      ? `?days=${requestedDays}`
      : "";
  const data = await request<Partial<Analytics>>(`/me/analytics${qs}`, {
    options,
  });
  return normalizeAnalytics(data, requestedDays);
}

/** GET /me/referral */
export function getReferral(options?: RequestOptions): Promise<Referral> {
  return request<Referral>("/me/referral", { options });
}

/** POST /me/referral/redeem */
export function redeemReferral(
  code: string,
  options?: RequestOptions,
): Promise<RedeemResult> {
  return request<RedeemResult>("/me/referral/redeem", {
    method: "POST",
    body: { code },
    options,
  });
}

/**
 * GET /me/presets — the caller's saved presets (newest first). The backend may
 * return the list directly as `data` or wrapped as `{ presets: [...] }`; both
 * shapes are normalized to a `Preset[]` here.
 */
export async function listPresets(
  options?: RequestOptions,
): Promise<Preset[]> {
  const data = await request<Preset[] | { presets?: Preset[] }>("/me/presets", {
    options,
  });
  if (Array.isArray(data)) return data;
  return data?.presets ?? [];
}

/**
 * POST /me/presets — save a brand kit. Set `body.workspace_id` to SHARE it to a
 * workspace so every member sees it (the caller must be a member); omit to keep
 * it private to the caller.
 */
export function createPreset(
  body: PresetCreateRequest,
  options?: RequestOptions,
): Promise<Preset> {
  return request<Preset>("/me/presets", { method: "POST", body, options });
}

/** DELETE /me/presets/{id} */
export function deletePreset(
  id: string,
  options?: RequestOptions,
): Promise<PresetDeleteResult> {
  return request<PresetDeleteResult>(`/me/presets/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}

// ---------------------------------------------------------------------------
// Brand watermark (GET/PUT /me/brand) — the caller's per-user transparent-PNG
// logo overlaid on their reels in the compose stage at a chosen corner +
// opacity. The logo is uploaded via {@link presignAndUpload} (image/png) and
// referenced by its R2 `logo_key`. Applied by default when `enabled`.
// ---------------------------------------------------------------------------

/**
 * Coerce a possibly-partial brand envelope into a fully-populated {@link Brand},
 * clamping opacity into `[0, 1]` and falling back to the documented column
 * defaults so callers never have to guard individual fields.
 */
function normalizeBrand(data: Partial<Brand> | null | undefined): Brand {
  const rawOpacity =
    typeof data?.opacity === "number" && Number.isFinite(data.opacity)
      ? data.opacity
      : WATERMARK_DEFAULT_OPACITY;
  return {
    logo_key: typeof data?.logo_key === "string" ? data.logo_key : "",
    position:
      typeof data?.position === "string" && data.position
        ? data.position
        : WATERMARK_DEFAULT_POSITION,
    opacity: Math.min(
      WATERMARK_OPACITY_MAX,
      Math.max(WATERMARK_OPACITY_MIN, rawOpacity),
    ),
    enabled: typeof data?.enabled === "boolean" ? data.enabled : true,
    logo_url: typeof data?.logo_url === "string" ? data.logo_url : null,
    updated_at: typeof data?.updated_at === "string" ? data.updated_at : null,
  };
}

/**
 * GET /me/brand — the caller's brand watermark settings (the backend defaults
 * when never configured). When a `logo_key` is set the payload also carries a
 * short-lived presigned `logo_url` for previewing the uploaded logo. The result
 * is normalized so every field is populated.
 */
export async function getBrand(options?: RequestOptions): Promise<Brand> {
  const data = await request<Partial<Brand>>("/me/brand", { options });
  return normalizeBrand(data);
}

/**
 * PUT /me/brand — update the caller's brand watermark (a partial update; omit a
 * field to leave it untouched). `position` must be a known corner and `opacity`
 * must be in `[0, 1]` (both 400 otherwise). A supplied non-empty `logo_key` must
 * reference an upload the caller owns (403 otherwise); pass `logo_key: ""` to
 * clear the logo. Returns the updated, normalized {@link Brand}.
 */
export async function updateBrand(
  body: BrandUpdateRequest,
  options?: RequestOptions,
): Promise<Brand> {
  const data = await request<Partial<Brand>>("/me/brand", {
    method: "PUT",
    body,
    options,
  });
  return normalizeBrand(data);
}

// ---------------------------------------------------------------------------
// SPARK — AI Idea Engine (POST /ideas/generate, auth-gated /me/ideas/*)
// ---------------------------------------------------------------------------

/**
 * POST /ideas/generate — turn an app/niche description into N ready-to-shoot
 * viral UGC video concepts. The backend may return the list directly as `data`
 * or wrapped as `{ ideas: [...] }`; both shapes are normalized to an `Idea[]`.
 */
export async function generateIdeas(
  body: GenerateIdeasRequest,
  options?: RequestOptions,
): Promise<Idea[]> {
  const data = await request<Idea[] | { ideas?: Idea[] }>("/ideas/generate", {
    method: "POST",
    body,
    options,
  });
  if (Array.isArray(data)) return data;
  return data?.ideas ?? [];
}

/** POST /me/ideas — save a generated idea to the caller's collection. */
export function saveIdea(
  idea: Idea,
  options?: RequestOptions,
): Promise<SavedIdea> {
  return request<SavedIdea>("/me/ideas", { method: "POST", body: idea, options });
}

/**
 * GET /me/ideas — the caller's saved ideas (newest first). The backend may
 * return the list directly as `data` or wrapped as `{ ideas: [...] }`; both
 * shapes are normalized to a `SavedIdea[]` here.
 */
export async function listSavedIdeas(
  options?: RequestOptions,
): Promise<SavedIdea[]> {
  const data = await request<SavedIdea[] | { ideas?: SavedIdea[] }>(
    "/me/ideas",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.ideas ?? [];
}

/** DELETE /me/ideas/{id} — remove a saved idea the caller owns. */
export function deleteSavedIdea(
  id: string,
  options?: RequestOptions,
): Promise<SavedIdeaDeleteResult> {
  return request<SavedIdeaDeleteResult>(`/me/ideas/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}

// ---------------------------------------------------------------------------
// Hook Performance Loop (POST/GET /jobs/{id}/performance, GET /me/performance,
// GET /me/winning-hooks, GET /me/winning-templates) — creators SELF-REPORT the
// real-world outcome of a posted reel; the backend aggregates outcomes per HOOK
// and per TEMPLATE into a deterministic `win_score`. Strictly caller-scoped: a
// creator only logs metrics for their OWN job and only reads their OWN
// aggregates. All numeric inputs are clamped at this boundary (non-negative
// counts; retention in [0, 100]; limit in [1, 100]) so an untrusted value can
// never reach the API out of range.
// ---------------------------------------------------------------------------

/** Clamp an untrusted numeric to a non-negative integer (0 when non-finite). */
function clampCount(value: number | undefined): number | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
  return Math.max(0, Math.trunc(value));
}

/** Clamp an untrusted retention value to `[RETENTION_PCT_MIN, RETENTION_PCT_MAX]`. */
function clampRetention(value: number | undefined): number | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
  return Math.min(RETENTION_PCT_MAX, Math.max(RETENTION_PCT_MIN, value));
}

/** Coerce a raw record into a fully-populated {@link JobPerformance}. */
function normalizeJobPerformance(
  data: Partial<JobPerformance> | null | undefined,
): JobPerformance {
  return {
    id: typeof data?.id === "string" ? data.id : "",
    job_id: typeof data?.job_id === "string" ? data.job_id : "",
    platform: typeof data?.platform === "string" ? data.platform : "",
    views: Math.max(0, toFiniteNumber(data?.views)),
    likes: Math.max(0, toFiniteNumber(data?.likes)),
    comments: Math.max(0, toFiniteNumber(data?.comments)),
    shares: Math.max(0, toFiniteNumber(data?.shares)),
    saves: Math.max(0, toFiniteNumber(data?.saves)),
    retention_pct: Math.min(
      RETENTION_PCT_MAX,
      Math.max(RETENTION_PCT_MIN, toFiniteNumber(data?.retention_pct)),
    ),
    logged_at: typeof data?.logged_at === "string" ? data.logged_at : null,
    updated_at: typeof data?.updated_at === "string" ? data.updated_at : null,
  };
}

/**
 * Coerce a possibly-wrapped list envelope into an array of plain records. The
 * backend may return the list directly as `data` or wrapped under `key`; either
 * way, only object entries survive (so `.map` sees `Record<string, unknown>`).
 */
function extractList(
  data: unknown,
  key: string,
): Record<string, unknown>[] {
  const raw = Array.isArray(data)
    ? data
    : data && typeof data === "object"
      ? (data as Record<string, unknown>)[key]
      : undefined;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (e): e is Record<string, unknown> => Boolean(e) && typeof e === "object",
  );
}

/** Shared numeric normalization for a winning-hook / winning-template aggregate. */
function normalizeWinAggregate(data: Record<string, unknown>): {
  win_score: number;
  reels: number;
  views: number;
  engagements: number;
  avg_retention_pct: number;
} {
  return {
    win_score: Math.max(0, toFiniteNumber(data.win_score)),
    reels: Math.max(0, toFiniteNumber(data.reels)),
    views: Math.max(0, toFiniteNumber(data.views)),
    engagements: Math.max(0, toFiniteNumber(data.engagements)),
    avg_retention_pct: Math.min(
      RETENTION_PCT_MAX,
      Math.max(RETENTION_PCT_MIN, toFiniteNumber(data.avg_retention_pct)),
    ),
  };
}

/**
 * POST /jobs/{id}/performance — LOG or UPDATE (idempotent upsert) the caller's
 * OWN reel's self-reported metrics. Ownership is enforced server-side (a foreign
 * job is a 403, an unknown one a 404). Every count is clamped non-negative and
 * `retention_pct` into `[0, 100]` before sending. Returns the stored record.
 */
export function logJobPerformance(
  jobId: string,
  body: LogPerformanceRequest,
  options?: RequestOptions,
): Promise<JobPerformance> {
  const payload: LogPerformanceRequest = {};
  const platform = body.platform?.trim();
  if (platform) payload.platform = platform;
  const views = clampCount(body.views);
  if (views !== undefined) payload.views = views;
  const likes = clampCount(body.likes);
  if (likes !== undefined) payload.likes = likes;
  const comments = clampCount(body.comments);
  if (comments !== undefined) payload.comments = comments;
  const shares = clampCount(body.shares);
  if (shares !== undefined) payload.shares = shares;
  const saves = clampCount(body.saves);
  if (saves !== undefined) payload.saves = saves;
  const retention = clampRetention(body.retention_pct);
  if (retention !== undefined) payload.retention_pct = retention;

  return request<Partial<JobPerformance>>(
    `/jobs/${encodeURIComponent(jobId)}/performance`,
    { method: "POST", body: payload, options },
  ).then(normalizeJobPerformance);
}

/**
 * GET /jobs/{id}/performance — the caller's logged metrics for that reel. A
 * missing or foreign job id yields a 404 (surfaced as {@link ApiError}). The
 * possibly-partial envelope is normalized so every field is populated.
 */
export function getJobPerformance(
  jobId: string,
  options?: RequestOptions,
): Promise<JobPerformance> {
  return request<Partial<JobPerformance>>(
    `/jobs/${encodeURIComponent(jobId)}/performance`,
    { options },
  ).then(normalizeJobPerformance);
}

/**
 * GET /me/performance — the caller's logged reels (newest first). `opts.limit` is
 * clamped to `[PERFORMANCE_LIMIT_MIN, PERFORMANCE_LIMIT_MAX]` and `opts.offset`
 * floored at 0 before sending, so an untrusted page request can never trigger an
 * unbounded scan. The backend may return the list directly as `data` or wrapped
 * as `{ performance: [...] }`; both shapes are normalized to a `JobPerformance[]`.
 */
export async function listMyPerformance(
  opts: ListPerformanceParams = {},
  options?: RequestOptions,
): Promise<JobPerformance[]> {
  const query = new URLSearchParams();
  if (typeof opts.limit === "number" && Number.isFinite(opts.limit)) {
    query.set(
      "limit",
      String(
        Math.min(
          PERFORMANCE_LIMIT_MAX,
          Math.max(PERFORMANCE_LIMIT_MIN, Math.trunc(opts.limit)),
        ),
      ),
    );
  }
  if (typeof opts.offset === "number" && Number.isFinite(opts.offset)) {
    query.set("offset", String(Math.max(0, Math.trunc(opts.offset))));
  }

  const qs = query.toString();
  const data = await request<
    JobPerformance[] | { performance?: JobPerformance[] }
  >(`/me/performance${qs ? `?${qs}` : ""}`, { options });
  const list = Array.isArray(data) ? data : (data?.performance ?? []);
  return list.map(normalizeJobPerformance);
}

/** Clamp an optional `limit` into the performance page-size bounds for a query. */
function performanceLimitQuery(limit: number | undefined): string {
  if (typeof limit !== "number" || !Number.isFinite(limit)) return "";
  const clamped = Math.min(
    PERFORMANCE_LIMIT_MAX,
    Math.max(PERFORMANCE_LIMIT_MIN, Math.trunc(limit)),
  );
  return `?limit=${clamped}`;
}

/**
 * GET /me/winning-hooks — the caller's top hooks by `win_score` (best first).
 * `limit` is clamped to `[1, 100]`. The backend may return the list directly as
 * `data` or wrapped as `{ hooks: [...] }`; both shapes are normalized to a
 * `WinningHook[]`, with every numeric field coerced non-negative (never NaN/Inf)
 * and entries without a usable `hook` dropped.
 */
export async function getWinningHooks(
  limit?: number,
  options?: RequestOptions,
): Promise<WinningHook[]> {
  const data = await request<unknown>(
    `/me/winning-hooks${performanceLimitQuery(limit)}`,
    { options },
  );
  const list = extractList(data, "hooks");
  return list
    .map((e) => ({
      hook: typeof e.hook === "string" ? e.hook : "",
      ...normalizeWinAggregate(e),
    }))
    .filter((e) => e.hook.length > 0);
}

/**
 * GET /me/winning-templates — the caller's top templates by `win_score` (best
 * first). `limit` is clamped to `[1, 100]`. The backend may return the list
 * directly as `data` or wrapped as `{ templates: [...] }`; both shapes are
 * normalized to a `WinningTemplate[]`, with every numeric field coerced
 * non-negative (never NaN/Inf) and entries without a usable `template` dropped.
 */
export async function getWinningTemplates(
  limit?: number,
  options?: RequestOptions,
): Promise<WinningTemplate[]> {
  const data = await request<unknown>(
    `/me/winning-templates${performanceLimitQuery(limit)}`,
    { options },
  );
  const list = extractList(data, "templates");
  return list
    .map((e) => ({
      template: typeof e.template === "string" ? e.template : "",
      ...normalizeWinAggregate(e),
    }))
    .filter((e) => e.template.length > 0);
}

// ---------------------------------------------------------------------------
// In-app notifications (auth-gated; GET/POST /me/notifications*) — the in-app
// counterpart to the external webhook. Bell + unread badge + notification
// center.
// ---------------------------------------------------------------------------

/**
 * GET /me/notifications — the caller's notifications (newest first) plus the
 * live total `unread_count`. `params.unread_only` restricts to unread rows and
 * `params.limit` bounds the page (backend clamps to [1, 200]). The result is
 * normalized so `notifications` is always an array and `unread_count` a number,
 * even if the backend envelope is partial.
 */
export async function listNotifications(
  params: ListNotificationsParams = {},
  options?: RequestOptions,
): Promise<NotificationListResult> {
  const query = new URLSearchParams();
  if (params.unread_only) query.set("unread_only", "true");
  if (typeof params.limit === "number" && Number.isFinite(params.limit)) {
    query.set("limit", String(Math.trunc(params.limit)));
  }
  const qs = query.toString();
  const data = await request<Partial<NotificationListResult>>(
    `/me/notifications${qs ? `?${qs}` : ""}`,
    { options },
  );
  return {
    notifications: Array.isArray(data?.notifications) ? data.notifications : [],
    unread_count:
      typeof data?.unread_count === "number" ? data.unread_count : 0,
  };
}

/**
 * GET /me/notifications/unread_count — count-only endpoint, cheap enough to poll
 * on a short interval for the bell badge. Returns 0 on a malformed envelope.
 */
export async function getUnreadCount(
  options?: RequestOptions,
): Promise<number> {
  const data = await request<Partial<UnreadCountResult>>(
    "/me/notifications/unread_count",
    { options },
  );
  return typeof data?.unread_count === "number" ? data.unread_count : 0;
}

/**
 * POST /me/notifications/{id}/read — flip one notification to read. Ownership is
 * enforced server-side; a missing/foreign id yields a 404 (surfaced as
 * {@link ApiError}). Marking an already-read notification is idempotent.
 */
export function markNotificationRead(
  id: string,
  options?: RequestOptions,
): Promise<MarkNotificationReadResult> {
  return request<MarkNotificationReadResult>(
    `/me/notifications/${encodeURIComponent(id)}/read`,
    { method: "POST", options },
  );
}

/**
 * POST /me/notifications/read_all — mark every one of the caller's notifications
 * read and report how many were flipped (`unread_count` is 0 afterwards).
 */
export function markAllNotificationsRead(
  options?: RequestOptions,
): Promise<MarkAllNotificationsReadResult> {
  return request<MarkAllNotificationsReadResult>(
    "/me/notifications/read_all",
    { method: "POST", options },
  );
}

// ---------------------------------------------------------------------------
// Scheduled publishing (POST /jobs/{id}/schedule, GET/DELETE /me/scheduled) —
// auto-publish a finished reel to platforms at a future UTC time; a Celery-beat
// due-runner publishes pending schedules once their time arrives.
// ---------------------------------------------------------------------------

/**
 * POST /jobs/{id}/schedule — schedule a finished reel to auto-publish to
 * `body.platforms` at `body.scheduled_at` (a future ISO-8601 UTC instant). The
 * created schedule starts in a pending state; a background due-runner publishes
 * it when the time arrives. Returns the created {@link ScheduledPublish}.
 */
export function schedulePublish(
  jobId: string,
  body: SchedulePublishRequest,
  options?: RequestOptions,
): Promise<ScheduledPublish> {
  return request<ScheduledPublish>(
    `/jobs/${encodeURIComponent(jobId)}/schedule`,
    { method: "POST", body, options },
  );
}

/**
 * GET /me/scheduled — the caller's scheduled publishes (newest first),
 * optionally filtered to a single `status` (e.g. "pending"). The backend may
 * return the list directly as `data` or wrapped as `{ scheduled: [...] }`; both
 * shapes are normalized to a `ScheduledPublish[]` here.
 */
export async function listScheduled(
  status?: ScheduledPublishStatus,
  options?: RequestOptions,
): Promise<ScheduledPublish[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const data = await request<
    ScheduledPublish[] | { scheduled?: ScheduledPublish[] }
  >(`/me/scheduled${qs}`, { options });
  if (Array.isArray(data)) return data;
  return data?.scheduled ?? [];
}

/**
 * DELETE /me/scheduled/{id} — cancel a pending scheduled publish the caller
 * owns. Only pending/queued schedules can be canceled (the backend rejects an
 * already-run schedule). `id` is the {@link ScheduledPublish.id} row id.
 */
export function cancelScheduled(
  id: string,
  options?: RequestOptions,
): Promise<ScheduledCancelResult> {
  return request<ScheduledCancelResult>(
    `/me/scheduled/${encodeURIComponent(id)}`,
    { method: "DELETE", options },
  );
}

// ---------------------------------------------------------------------------
// Team workspaces (GET/POST /workspaces, /workspaces/{id}/members*) — an
// ADDITIVE membership layer. Owners/admins invite (by email), remove, and
// change roles; members view + leave. Does NOT change per-user job/credit
// ownership.
// ---------------------------------------------------------------------------

/** POST /workspaces — create a workspace the caller owns. */
export function createWorkspace(
  name: string,
  options?: RequestOptions,
): Promise<Workspace> {
  const body: CreateWorkspaceRequest = { name };
  return request<Workspace>("/workspaces", { method: "POST", body, options });
}

/**
 * GET /workspaces — every workspace the caller belongs to (each carries the
 * caller's own `role`). The backend may return the list directly as `data` or
 * wrapped as `{ workspaces: [...] }`; both shapes are normalized to a
 * `Workspace[]` here.
 */
export async function listMyWorkspaces(
  options?: RequestOptions,
): Promise<Workspace[]> {
  const data = await request<Workspace[] | { workspaces?: Workspace[] }>(
    "/workspaces",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.workspaces ?? [];
}

/**
 * GET /workspaces/{id}/members — the members of a workspace the caller belongs
 * to. The backend may return the list directly as `data` or wrapped as
 * `{ members: [...] }`; both shapes are normalized to a `Member[]` here.
 */
export async function listMembers(
  id: string,
  options?: RequestOptions,
): Promise<Member[]> {
  const data = await request<Member[] | { members?: Member[] }>(
    `/workspaces/${encodeURIComponent(id)}/members`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.members ?? [];
}

/**
 * POST /workspaces/{id}/members — invite an existing user (by email) into the
 * workspace. Caller must be an owner/admin (enforced server-side). `role`
 * defaults to `"member"` when omitted. Returns the created {@link Member}.
 */
export function inviteMember(
  id: string,
  body: InviteMemberRequest,
  options?: RequestOptions,
): Promise<Member> {
  return request<Member>(`/workspaces/${encodeURIComponent(id)}/members`, {
    method: "POST",
    body,
    options,
  });
}

/**
 * PATCH /workspaces/{id}/members/{userId} — change a member's role. Caller must
 * be an owner/admin (enforced server-side). Returns the updated {@link Member}.
 */
export function setMemberRole(
  id: string,
  userId: string,
  role: WorkspaceRole,
  options?: RequestOptions,
): Promise<Member> {
  return request<Member>(
    `/workspaces/${encodeURIComponent(id)}/members/${encodeURIComponent(
      userId,
    )}`,
    { method: "PATCH", body: { role }, options },
  );
}

/**
 * DELETE /workspaces/{id}/members/{userId} — remove a member from the
 * workspace. Caller must be an owner/admin (enforced server-side).
 */
export function removeMember(
  id: string,
  userId: string,
  options?: RequestOptions,
): Promise<RemoveMemberResult> {
  return request<RemoveMemberResult>(
    `/workspaces/${encodeURIComponent(id)}/members/${encodeURIComponent(
      userId,
    )}`,
    { method: "DELETE", options },
  );
}

/**
 * POST /workspaces/{id}/leave — the caller leaves a workspace they belong to.
 * (Owners may be blocked server-side until ownership is transferred.)
 */
export function leaveWorkspace(
  id: string,
  options?: RequestOptions,
): Promise<LeaveWorkspaceResult> {
  return request<LeaveWorkspaceResult>(
    `/workspaces/${encodeURIComponent(id)}/leave`,
    { method: "POST", options },
  );
}

// ---------------------------------------------------------------------------
// Shared workspace credits (GET/POST /workspaces/{id}/credits*) — a workspace's
// SHARED credit pool. Members read the balance; owners/admins grant credits.
// Jobs debit this pool via `JobCreateRequest.workspace_id` (reusing the existing
// locked-debit credit-ledger pattern server-side).
// ---------------------------------------------------------------------------

/**
 * GET /workspaces/{id}/credits — read a workspace's SHARED credit pool balance.
 * The caller must be a member (any role); a non-member gets a 403 and an unknown
 * workspace id a 404 (both surfaced as {@link ApiError}). The backend returns
 * `{ balance }` under the envelope's `data`; the balance is coerced to a number.
 */
export async function getWorkspaceCredits(
  id: string,
  options?: RequestOptions,
): Promise<WorkspaceCredits> {
  const data = await request<Partial<WorkspaceCredits>>(
    `/workspaces/${encodeURIComponent(id)}/credits`,
    { options },
  );
  return { balance: typeof data?.balance === "number" ? data.balance : 0 };
}

/**
 * POST /workspaces/{id}/credits/grant — add credits to a workspace's SHARED pool
 * (owner/admin only; a plain member gets a 403). `body.amount` must be a positive
 * integer (a non-positive amount yields a 400). `body.reason` is an optional
 * audit note. Returns the updated pool balance as {@link WorkspaceCredits}.
 */
export async function grantWorkspaceCredits(
  id: string,
  body: GrantWorkspaceCreditsRequest,
  options?: RequestOptions,
): Promise<WorkspaceCredits> {
  const data = await request<Partial<WorkspaceCredits>>(
    `/workspaces/${encodeURIComponent(id)}/credits/grant`,
    { method: "POST", body, options },
  );
  return { balance: typeof data?.balance === "number" ? data.balance : 0 };
}

// ---------------------------------------------------------------------------
// ENTERPRISE — Access & Governance (Epic 1): RBAC, audit trail, platform-admin
//
// The Enterprise access layer, gated by the pycasbin enforcer server-side. Every
// workspace-scoped call verifies the caller is a member with a sufficient role;
// TENANT ISOLATION is the #1 invariant (no endpoint returns another tenant's
// data). The audit trail is APPEND-ONLY (read-only here). Platform-admin is a
// SEPARATE, `is_staff`-gated cross-tenant surface.
// ---------------------------------------------------------------------------

/**
 * GET /me/workspaces/{id}/members — the workspace roster with each member's
 * Enterprise role. The caller must be a member (any role): a non-member gets a
 * 403 and an unknown workspace a 404 (both surfaced as {@link ApiError}). The
 * backend returns the list directly under `data`; a `{ members: [...] }` wrapper
 * is also tolerated. Strictly tenant-scoped.
 */
export async function listWorkspaceMembers(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Member[]> {
  const data = await request<Member[] | { members?: Member[] }>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/members`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.members ?? [];
}

/**
 * PATCH /me/workspaces/{id}/members/{userId}/role — change a member's Enterprise
 * role. Requires the caller to hold `members.manage` (admin/owner). Server-side
 * guardrails (all surfaced as {@link ApiError}): an unknown role is a 400, a
 * non-member target a 404, granting a role ABOVE the caller's own a 403, and
 * demoting the LAST owner a 409. On success exactly one append-only
 * `members.role_changed` audit row is written. Returns the updated {@link Member}.
 */
export function updateMemberRole(
  workspaceId: string,
  userId: string,
  role: WorkspaceRole,
  options?: RequestOptions,
): Promise<Member> {
  return request<Member>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(
      userId,
    )}/role`,
    { method: "PATCH", body: { role }, options },
  );
}

/**
 * GET /me/permissions?workspace_id= — the caller's EFFECTIVE permissions (direct
 * + inherited) in a workspace, from the enforcer. A blank `workspaceId` is a 400.
 * A non-member yields `{ role: null, permissions: [] }` (no tenant leak) rather
 * than an error. The possibly-partial envelope is normalized so `permissions` is
 * always an array and `role` is `null` when absent.
 */
export async function getMyPermissions(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Permissions> {
  const data = await request<Partial<Permissions>>(
    `/me/permissions?workspace_id=${encodeURIComponent(workspaceId)}`,
    { options },
  );
  const permissions = Array.isArray(data?.permissions)
    ? data.permissions.filter(
        (p): p is Permission => typeof p === "string" && p.length > 0,
      )
    : [];
  return {
    workspace_id:
      typeof data?.workspace_id === "string" ? data.workspace_id : workspaceId,
    role: typeof data?.role === "string" ? data.role : null,
    permissions,
  };
}

/**
 * GET /me/workspaces/{id}/audit — the workspace's APPEND-ONLY audit trail
 * (newest first). Requires the caller to hold `audit.read` (admin/owner): a
 * non-member/under-privileged caller gets a 403 and an unknown workspace a 404
 * (both surfaced as {@link ApiError}). `params.limit` is clamped to `[1, 100]`
 * and `params.offset` floored at 0 before sending. Strictly tenant-scoped — only
 * rows for `workspaceId` are ever returned. The backend returns the list under
 * `data`; a `{ audit: [...] }` wrapper is also tolerated.
 */
export async function listAuditLog(
  workspaceId: string,
  params: AuditLogParams = {},
  options?: RequestOptions,
): Promise<AuditEntry[]> {
  const query = new URLSearchParams();
  if (typeof params.limit === "number" && Number.isFinite(params.limit)) {
    query.set("limit", String(Math.min(100, Math.max(1, Math.trunc(params.limit)))));
  }
  if (typeof params.offset === "number" && Number.isFinite(params.offset)) {
    query.set("offset", String(Math.max(0, Math.trunc(params.offset))));
  }
  const qs = query.toString();
  const data = await request<AuditEntry[] | { audit?: AuditEntry[] }>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/audit${qs ? `?${qs}` : ""}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.audit ?? [];
}

/**
 * Shared page-window query builder for the platform-admin list endpoints. The
 * backend clamps `limit` to `[1, 200]` and floors `offset` at 0; this mirrors
 * that so an untrusted page can never trigger an unbounded scan.
 */
function adminListQuery(params: AdminListParams): string {
  const query = new URLSearchParams();
  if (typeof params.limit === "number" && Number.isFinite(params.limit)) {
    query.set("limit", String(Math.min(200, Math.max(1, Math.trunc(params.limit)))));
  }
  if (typeof params.offset === "number" && Number.isFinite(params.offset)) {
    query.set("offset", String(Math.max(0, Math.trunc(params.offset))));
  }
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

/**
 * GET /admin/users — every user across every tenant (newest first).
 * PLATFORM-ADMIN ONLY: a non-staff caller gets a 403 (a workspace owner is NOT
 * staff), a missing/invalid token a 401 (both surfaced as {@link ApiError}). The
 * backend returns the list under `data`; a `{ users: [...] }` wrapper is tolerated.
 */
export async function adminListUsers(
  params: AdminListParams = {},
  options?: RequestOptions,
): Promise<AdminUser[]> {
  const data = await request<AdminUser[] | { users?: AdminUser[] }>(
    `/admin/users${adminListQuery(params)}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.users ?? [];
}

/**
 * GET /admin/workspaces — every workspace across every tenant (newest first).
 * PLATFORM-ADMIN ONLY (403 for non-staff, 401 unauthenticated). The backend
 * returns the list under `data`; a `{ workspaces: [...] }` wrapper is tolerated.
 */
export async function adminListWorkspaces(
  params: AdminListParams = {},
  options?: RequestOptions,
): Promise<AdminWorkspace[]> {
  const data = await request<AdminWorkspace[] | { workspaces?: AdminWorkspace[] }>(
    `/admin/workspaces${adminListQuery(params)}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.workspaces ?? [];
}

/**
 * GET /admin/jobs — every job across every tenant (newest first). PLATFORM-ADMIN
 * ONLY (403 for non-staff, 401 unauthenticated). The backend returns the list
 * under `data`; a `{ jobs: [...] }` wrapper is tolerated.
 */
export async function adminListJobs(
  params: AdminListParams = {},
  options?: RequestOptions,
): Promise<AdminJob[]> {
  const data = await request<AdminJob[] | { jobs?: AdminJob[] }>(
    `/admin/jobs${adminListQuery(params)}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.jobs ?? [];
}

/**
 * POST /admin/impersonate — mint a short-lived, scoped impersonation token for
 * `userId`. PLATFORM-ADMIN ONLY: a non-staff caller gets a 403 and an unknown
 * target a 400 (both surfaced as {@link ApiError}). On success an append-only
 * `admin.impersonated` audit row is written. Returns the {@link Impersonation}
 * grant (the token is short-lived — never persist it).
 */
export function adminImpersonate(
  userId: string,
  options?: RequestOptions,
): Promise<Impersonation> {
  return request<Impersonation>("/admin/impersonate", {
    method: "POST",
    body: { user_id: userId },
    options,
  });
}

// ---------------------------------------------------------------------------
// Personal API keys (PUBLIC API KEYS; auth-gated /me/api-keys) — mint, list, and
// revoke personal keys for programmatic access. A minted key is sent as the
// `x-api-key` header (in addition to the Clerk JWT / static app key) and is
// resolved back to the owning user server-side. The raw secret is revealed ONCE
// at creation and stored only as a SHA-256 hash; list/revoke never expose it.
// ---------------------------------------------------------------------------

/**
 * POST /me/api-keys — mint a personal API key and return the FULL raw secret
 * **once**. `name` is a required human-friendly label (trimmed here; the backend
 * caps it at 200 chars and rejects an empty name with 400). The returned
 * {@link CreatedApiKey.key} is unrecoverable afterwards — the caller must store
 * it immediately. The backend caps the number of active keys per user (409 when
 * exceeded, surfaced as {@link ApiError}).
 */
export function createApiKey(
  name: string,
  options?: RequestOptions,
): Promise<CreatedApiKey> {
  const body: ApiKeyCreateRequest = { name: name.trim() };
  return request<CreatedApiKey>("/me/api-keys", {
    method: "POST",
    body,
    options,
  });
}

/**
 * GET /me/api-keys — the caller's API keys (newest first), active and revoked.
 * The raw key and full hash are never returned. The backend returns the list
 * directly under `data` (and omits `data` entirely when empty); both the array
 * and a `{ keys: [...] }` wrapper are normalized to an `ApiKey[]` here.
 */
export async function listApiKeys(
  options?: RequestOptions,
): Promise<ApiKey[]> {
  const data = await request<ApiKey[] | { keys?: ApiKey[] }>("/me/api-keys", {
    options,
  });
  if (Array.isArray(data)) return data;
  return data?.keys ?? [];
}

/**
 * DELETE /me/api-keys/{id} — revoke one of the caller's keys. Ownership is
 * enforced server-side: a missing or foreign id yields a 404 (surfaced as
 * {@link ApiError}). A revoked key can no longer authenticate.
 */
export function revokeApiKey(
  id: string,
  options?: RequestOptions,
): Promise<ApiKeyRevokeResult> {
  return request<ApiKeyRevokeResult>(`/me/api-keys/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}

/**
 * GET /me/api-keys/usage — each of the caller's keys with its CURRENT-MONTH
 * request usage and limits (strictly caller-scoped; still token-free). The
 * backend returns the list directly under `data` (and omits `data` entirely when
 * empty); both the array and a `{ usage: [...] }` wrapper are normalized to an
 * `ApiKeyUsage[]` here.
 */
export async function getApiKeyUsage(
  options?: RequestOptions,
): Promise<ApiKeyUsage[]> {
  const data = await request<ApiKeyUsage[] | { usage?: ApiKeyUsage[] }>(
    "/me/api-keys/usage",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.usage ?? [];
}

// ---------------------------------------------------------------------------
// Social connections & direct publish (GET /me/connections,
// GET /connections/{provider}/authorize, GET /connections/{provider}/callback,
// DELETE /me/connections/{provider}, POST /jobs/{id}/publish/{provider}) — a
// power user connects a social account via OAuth (the token is encrypted +
// stored server-side and NEVER returned) and publishes their OWN finished reel
// straight to that provider. Every payload here is strictly TOKEN-FREE.
// ---------------------------------------------------------------------------

/**
 * GET /me/connections — the caller's connected social accounts (newest first,
 * owner-scoped, TOKEN-FREE). The backend returns the list directly under `data`
 * (and omits `data` entirely when empty); both the array and a
 * `{ connections: [...] }` wrapper are normalized to a `Connection[]` here.
 */
export async function listConnections(
  options?: RequestOptions,
): Promise<Connection[]> {
  const data = await request<Connection[] | { connections?: Connection[] }>(
    "/me/connections",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.connections ?? [];
}

/**
 * GET /connections/{provider}/authorize — begin an OAuth connect. Returns the
 * provider authorize URL (already embedding an opaque single-use CSRF `state`)
 * to redirect the browser to; the caller echoes `state` back on the callback.
 * Nothing sensitive is returned. An unknown provider is a 404 (surfaced as
 * {@link ApiError}); a provider whose client id is not configured server-side is
 * a 503.
 */
export function authorizeConnection(
  provider: SocialProvider,
  options?: RequestOptions,
): Promise<AuthorizeInfo> {
  return request<AuthorizeInfo>(
    `/connections/${encodeURIComponent(provider)}/authorize`,
    { options },
  );
}

/**
 * GET /connections/{provider}/callback — finish an OAuth connect: the backend
 * validates the single-use `state` (a missing/replayed state is a clean 400
 * BEFORE any code exchange), exchanges `code`, encrypts + stores the tokens, and
 * returns the caller's refreshed connection list (TOKEN-FREE). The array and a
 * `{ connections: [...] }` wrapper are both normalized to a `Connection[]` here.
 */
export async function completeConnect(
  provider: SocialProvider,
  code: string,
  state: string,
  options?: RequestOptions,
): Promise<Connection[]> {
  const query = new URLSearchParams({ code, state });
  const data = await request<Connection[] | { connections?: Connection[] }>(
    `/connections/${encodeURIComponent(provider)}/callback?${query.toString()}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.connections ?? [];
}

/**
 * DELETE /me/connections/{provider} — disconnect one of the caller's connected
 * providers (owner-scoped). A provider the caller has not connected yields a 404
 * (surfaced as {@link ApiError}), indistinguishable from another user's
 * connection so existence is never leaked.
 */
export function disconnectConnection(
  provider: SocialProvider,
  options?: RequestOptions,
): Promise<DisconnectResult> {
  return request<DisconnectResult>(
    `/me/connections/${encodeURIComponent(provider)}`,
    { method: "DELETE", options },
  );
}

/**
 * POST /jobs/{id}/publish/{provider} — publish the caller's OWN completed job
 * straight to a connected provider. Ownership + state are enforced server-side:
 * an unknown job is a 404, a foreign job a 403, and a not-complete / not-connected
 * job a 409 (all surfaced as {@link ApiError}). The optional `caption` is sent as
 * a query param (backend caps it at 2200 chars). The decrypted token is used only
 * for the outbound upload and is NEVER returned. Returns the {@link PublishResult}.
 */
export function publishJobTo(
  jobId: string,
  provider: SocialProvider,
  caption?: string,
  options?: RequestOptions,
): Promise<PublishResult> {
  const trimmed = caption?.trim();
  const qs = trimmed ? `?caption=${encodeURIComponent(trimmed)}` : "";
  return request<PublishResult>(
    `/jobs/${encodeURIComponent(jobId)}/publish/${encodeURIComponent(provider)}${qs}`,
    { method: "POST", options },
  );
}

// ---------------------------------------------------------------------------
// Template Marketplace (GET/POST/DELETE /marketplace*) — publish an IMMUTABLE
// snapshot of a private template, browse/search published listings, view a
// listing, clone it into the caller's private templates, and rate it 1..5 (one
// rating per user, upserted). Auth-gated like every other /v1 route.
// ---------------------------------------------------------------------------

/**
 * GET /marketplace — browse/search published listings, sorted + paginated.
 * `params.limit` is clamped to `[MARKETPLACE_LIMIT_MIN, MARKETPLACE_LIMIT_MAX]`
 * and `params.offset` floored at 0 before sending, so an untrusted page request
 * can never trigger an unbounded scan. Blank text filters are omitted. The
 * backend may return the list directly as `data` or wrapped as
 * `{ templates: [...] }`; both shapes are normalized to a `MarketplaceTemplate[]`.
 */
export async function browseMarketplace(
  params: MarketplaceBrowseParams = {},
  options?: RequestOptions,
): Promise<MarketplaceTemplate[]> {
  const query = new URLSearchParams();
  const text = params.query?.trim();
  if (text) query.set("query", text);
  const tag = params.tag?.trim();
  if (tag) query.set("tag", tag);
  const language = params.language?.trim();
  if (language) query.set("language", language);
  if (params.sort) query.set("sort", params.sort);
  if (typeof params.limit === "number" && Number.isFinite(params.limit)) {
    query.set(
      "limit",
      String(
        Math.min(
          MARKETPLACE_LIMIT_MAX,
          Math.max(MARKETPLACE_LIMIT_MIN, Math.trunc(params.limit)),
        ),
      ),
    );
  }
  if (typeof params.offset === "number" && Number.isFinite(params.offset)) {
    query.set("offset", String(Math.max(0, Math.trunc(params.offset))));
  }

  const qs = query.toString();
  const data = await request<
    MarketplaceTemplate[] | { templates?: MarketplaceTemplate[] }
  >(`/marketplace${qs ? `?${qs}` : ""}`, { options });
  if (Array.isArray(data)) return data;
  return data?.templates ?? [];
}

/** GET /marketplace/{id} — a single listing (404 for an unknown/unpublished id). */
export function getMarketplaceTemplate(
  id: string,
  options?: RequestOptions,
): Promise<MarketplaceTemplate> {
  return request<MarketplaceTemplate>(`/marketplace/${encodeURIComponent(id)}`, {
    options,
  });
}

/**
 * POST /marketplace/publish — publish an IMMUTABLE snapshot of the caller's own
 * private template. Reference an owned template via `body.template_id` (a
 * foreign/missing id is a 404) or pass the snapshot inline; a resolved `title` is
 * required (an empty title is a 400). Returns the created public listing.
 */
export function publishTemplate(
  body: PublishTemplateRequest,
  options?: RequestOptions,
): Promise<MarketplaceTemplate> {
  return request<MarketplaceTemplate>("/marketplace/publish", {
    method: "POST",
    body,
    options,
  });
}

/**
 * POST /marketplace/{id}/clone — clone a published listing into the caller's
 * private templates (allowed for any authed user; bumps the listing's
 * `clone_count`). A missing/unpublished listing is a 404. Returns the new
 * {@link ClonedTemplate}.
 */
export function cloneTemplate(
  id: string,
  options?: RequestOptions,
): Promise<ClonedTemplate> {
  return request<ClonedTemplate>(`/marketplace/${encodeURIComponent(id)}/clone`, {
    method: "POST",
    options,
  });
}

/**
 * POST /marketplace/{id}/rate — upsert the caller's 1..5 rating and return the
 * listing with its fresh aggregate (`rating_avg` / `rating_count`). Exactly one
 * rating exists per (user, template): a re-rate updates the caller's row rather
 * than adding a duplicate. `stars` is clamped to `[RATING_MIN, RATING_MAX]`
 * before sending; a missing/unpublished listing is a 404.
 */
export function rateTemplate(
  id: string,
  stars: number,
  options?: RequestOptions,
): Promise<MarketplaceTemplate> {
  const clamped = Math.min(
    RATING_MAX,
    Math.max(RATING_MIN, Math.trunc(stars)),
  );
  return request<MarketplaceTemplate>(
    `/marketplace/${encodeURIComponent(id)}/rate`,
    { method: "POST", body: { stars: clamped }, options },
  );
}

/**
 * DELETE /marketplace/{id} — AUTHOR-ONLY soft unpublish. A listing that does not
 * exist, belongs to a different author, or is already unpublished is
 * indistinguishable from a missing one (a clean 404), so a caller can never
 * unpublish another creator's listing. The row is retained so its clones/ratings
 * survive.
 */
export function unpublishMarketplaceTemplate(
  id: string,
  options?: RequestOptions,
): Promise<UnpublishTemplateResult> {
  return request<UnpublishTemplateResult>(
    `/marketplace/${encodeURIComponent(id)}`,
    { method: "DELETE", options },
  );
}

/**
 * GET /marketplace/{id}/lineage — the REMIX TREE of a listing: its `ancestors`
 * (immediate parent → root) and its direct still-published `children` (newest
 * first), each a safe public {@link MarketplaceTemplate}. Authed like the rest of
 * marketplace. An unknown/unpublished id yields `{ ancestors: [], children: [] }`.
 * The possibly-partial envelope is normalized so both fields are always arrays.
 */
export async function getMarketplaceLineage(
  id: string,
  options?: RequestOptions,
): Promise<MarketplaceLineage> {
  const data = await request<Partial<MarketplaceLineage>>(
    `/marketplace/${encodeURIComponent(id)}/lineage`,
    { options },
  );
  return {
    ancestors: Array.isArray(data?.ancestors) ? data.ancestors : [],
    children: Array.isArray(data?.children) ? data.children : [],
  };
}

// ---------------------------------------------------------------------------
// Public Watermarked Share Pages (POST /jobs/{id}/share, DELETE /me/shares/{token},
// GET /public/r/{token}) — a creator mints an unguessable, revocable public link
// for one of their OWN reels; anyone can view the resulting WATERMARKED share page
// with no auth. The public read is fetched anonymously (no token / app key) and
// returns a STRICT safe DTO that never leaks the clean result key or any private
// field. Backed by app/services/share.py.
// ---------------------------------------------------------------------------

/**
 * POST /jobs/{id}/share — mint (or return the existing active) public share link
 * for the caller's OWN reel. Owner-scoped: a foreign/missing job is a clean 404
 * (surfaced as {@link ApiError}). Idempotent — one live link per job. Returns the
 * owner-facing {@link ShareLink} (with the built public `url`).
 */
export function createShare(
  jobId: string,
  options?: RequestOptions,
): Promise<ShareLink> {
  return request<ShareLink>(`/jobs/${encodeURIComponent(jobId)}/share`, {
    method: "POST",
    options,
  });
}

/**
 * DELETE /me/shares/{token} — revoke one of the caller's OWN live share links.
 * Owner-scoped and idempotent: a foreign / unknown / already-revoked token is a
 * harmless no-op `{ revoked: false }` (never a confirmation), so a caller can
 * never revoke another creator's link by guessing its token.
 */
export function revokeShare(
  token: string,
  options?: RequestOptions,
): Promise<ShareRevokeResult> {
  return request<ShareRevokeResult>(
    `/me/shares/${encodeURIComponent(token)}`,
    { method: "DELETE", options },
  );
}

/**
 * GET /public/r/{token} — resolve a live share token to the SAFE public share
 * page (title + WATERMARKED preview URL + created_at + sharer referral code) and
 * count the view. PUBLIC: fetched ANONYMOUSLY (no caller token, no app key) so it
 * works for logged-out visitors, and the strict {@link SharePublic} shape never
 * carries the clean result key or any private field. An unknown/revoked token is
 * a 404 (surfaced as {@link ApiError}).
 */
export async function getPublicShare(token: string): Promise<SharePublic> {
  const data = await request<Partial<SharePublic>>(
    `/public/r/${encodeURIComponent(token)}`,
    { anonymous: true },
  );
  return {
    title: typeof data?.title === "string" ? data.title : "",
    watermarked_preview_url:
      typeof data?.watermarked_preview_url === "string"
        ? data.watermarked_preview_url
        : "",
    created_at: typeof data?.created_at === "string" ? data.created_at : null,
    sharer_referral_code:
      typeof data?.sharer_referral_code === "string"
        ? data.sharer_referral_code
        : "",
  };
}

// ---------------------------------------------------------------------------
// Creator Profiles + Follow Graph + Leaderboards (GET /creators/leaderboard,
// GET /creators/{handleOrId}, POST/DELETE /creators/{id}/follow, GET /me/following,
// PATCH /me/profile) — public creator identity + a directed follow graph + a
// deterministic reputation leaderboard. The leaderboard and profile are PUBLIC and
// expose ONLY safe fields; follow / following / profile-update are caller-scoped.
// Backed by app/services/creators.py.
// ---------------------------------------------------------------------------

/**
 * GET /creators/leaderboard — creators ranked by `params.metric` (defaults to
 * `reputation`; an unknown value normalises server-side). PUBLIC. `params.limit`
 * is clamped to `[LEADERBOARD_LIMIT_MIN, LEADERBOARD_LIMIT_MAX]` before sending so
 * an untrusted request can never trigger an unbounded scan. The backend may return
 * the list directly as `data` or wrapped as `{ leaderboard: [...] }`; both shapes
 * are normalized to a `LeaderboardEntry[]` here.
 */
export async function getLeaderboard(
  params: LeaderboardParams = {},
  options?: RequestOptions,
): Promise<LeaderboardEntry[]> {
  const query = new URLSearchParams();
  if (params.metric) query.set("metric", params.metric);
  if (typeof params.limit === "number" && Number.isFinite(params.limit)) {
    query.set(
      "limit",
      String(
        Math.min(
          LEADERBOARD_LIMIT_MAX,
          Math.max(LEADERBOARD_LIMIT_MIN, Math.trunc(params.limit)),
        ),
      ),
    );
  }
  const qs = query.toString();
  const data = await request<
    LeaderboardEntry[] | { leaderboard?: LeaderboardEntry[] }
  >(`/creators/leaderboard${qs ? `?${qs}` : ""}`, { options });
  if (Array.isArray(data)) return data;
  return data?.leaderboard ?? [];
}

/**
 * GET /creators/{handleOrId} — a creator's SAFE public profile, addressed by
 * either their handle (case-insensitive) or user id. PUBLIC. An unknown creator is
 * a 404 (surfaced as {@link ApiError}). The strict {@link CreatorProfile} never
 * carries email / credits / cost / revenue / another user's private data.
 */
export function getCreatorProfile(
  handleOrId: string,
  options?: RequestOptions,
): Promise<CreatorProfile> {
  return request<CreatorProfile>(
    `/creators/${encodeURIComponent(handleOrId)}`,
    { options },
  );
}

/**
 * POST /creators/{id}/follow — the caller follows a creator. Auth-gated and
 * idempotent (following again is a no-op). Self-follow is a 400 and an unknown
 * followee a 404 (both surfaced as {@link ApiError}). Returns the fresh
 * {@link FollowResult} (`following: true` + the followee's new `follower_count`).
 */
export function followCreator(
  creatorId: string,
  options?: RequestOptions,
): Promise<FollowResult> {
  return request<FollowResult>(
    `/creators/${encodeURIComponent(creatorId)}/follow`,
    { method: "POST", options },
  );
}

/**
 * DELETE /creators/{id}/follow — the caller unfollows a creator. Auth-gated and
 * idempotent (unfollowing someone not followed is a no-op `removed: false`).
 * Returns the fresh {@link FollowResult} (`following: false` + the followee's new
 * `follower_count`).
 */
export function unfollowCreator(
  creatorId: string,
  options?: RequestOptions,
): Promise<FollowResult> {
  return request<FollowResult>(
    `/creators/${encodeURIComponent(creatorId)}/follow`,
    { method: "DELETE", options },
  );
}

/**
 * GET /me/following — the safe public profiles of every creator the caller
 * follows (bounded server-side). Auth-gated. The backend may return the list
 * directly as `data` or wrapped as `{ following: [...] }`; both shapes are
 * normalized to a `CreatorProfile[]` here.
 */
export async function listFollowing(
  options?: RequestOptions,
): Promise<CreatorProfile[]> {
  const data = await request<
    CreatorProfile[] | { following?: CreatorProfile[] }
  >("/me/following", { options });
  if (Array.isArray(data)) return data;
  return data?.following ?? [];
}

/**
 * PATCH /me/profile — update the caller's own public identity (handle / display
 * name / bio). Auth-gated. Every field is optional; only the ones set are updated.
 * `handle` is normalised + shape-validated server-side (a bad shape is a 422, a
 * taken handle a 409 — both surfaced as {@link ApiError}). Blank text fields are
 * omitted so an empty input never clobbers a stored value. Returns the caller's
 * updated {@link CreatorProfile}.
 */
export function updateMyProfile(
  body: ProfileUpdateRequest,
  options?: RequestOptions,
): Promise<CreatorProfile> {
  const payload: ProfileUpdateRequest = {};
  const handle = body.handle?.trim();
  if (handle) payload.handle = handle;
  if (typeof body.display_name === "string") {
    payload.display_name = body.display_name.trim();
  }
  if (typeof body.bio === "string") payload.bio = body.bio.trim();
  return request<CreatorProfile>("/me/profile", {
    method: "PATCH",
    body: payload,
    options,
  });
}

// ---------------------------------------------------------------------------
// Upload flow helper: presign -> PUT file with returned headers -> return key
// ---------------------------------------------------------------------------

export interface UploadResult {
  /** R2 object key — use as `screen_recording_key` when creating a job. */
  key: string;
  /** Presigned GET URL for previewing the just-uploaded object. */
  get_url: string;
}

/**
 * Presigns an upload for `file`, PUTs the bytes to the returned `upload_url`
 * echoing the signed `headers`, and returns the object key. `onProgress`
 * receives a 0..1 fraction (0 after presign, 1 after the PUT completes).
 */
export async function presignAndUpload(
  file: File,
  options?: RequestOptions & { onProgress?: (fraction: number) => void },
): Promise<UploadResult> {
  const { onProgress, ...reqOptions } = options ?? {};

  const presigned = await presign(
    {
      filename: file.name,
      content_type: file.type || "application/octet-stream",
      size: file.size,
    },
    reqOptions,
  );

  onProgress?.(0);

  let putRes: Response;
  try {
    putRes = await fetch(presigned.upload_url, {
      method: "PUT",
      // Echo exactly the signed headers the backend returned. Fall back to
      // the file's content type if none were provided.
      headers:
        presigned.headers && Object.keys(presigned.headers).length > 0
          ? presigned.headers
          : { "Content-Type": file.type || "application/octet-stream" },
      body: file,
      signal: reqOptions.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(
      `Failed to upload file to storage: ${
        err instanceof Error ? err.message : String(err)
      }`,
      0,
      err,
    );
  }

  if (!putRes.ok) {
    const detail = await putRes.text().catch(() => "");
    throw new ApiError(
      `Storage rejected the upload (${putRes.status} ${putRes.statusText}).`,
      putRes.status,
      detail,
    );
  }

  await registerUpload(
    presigned.key,
    file.type.startsWith("image/")
      ? "image"
      : file.type.startsWith("video/")
        ? "video"
        : file.type.startsWith("audio/")
          ? "audio"
          : "upload",
    reqOptions,
  );
  onProgress?.(1);
  return { key: presigned.key, get_url: presigned.get_url };
}

// ---------------------------------------------------------------------------
// Polling: GET /jobs/{id} every 3s until the state is terminal
// ---------------------------------------------------------------------------

export interface PollOptions extends RequestOptions {
  /** Poll cadence in ms (default 3000, per the contract). */
  intervalMs?: number;
  /** Hard cap on total attempts before giving up (default 400 ≈ 20 min). */
  maxAttempts?: number;
}

/**
 * Polls GET /jobs/{id} every `intervalMs` until the job reaches a terminal
 * state, invoking `onTick(job)` on every successful poll. Resolves with the
 * final terminal Job. Rejects on ApiError, abort, or exceeding maxAttempts.
 */
export async function pollJob(
  id: string,
  onTick: (job: Job) => void,
  options?: PollOptions,
): Promise<Job> {
  const intervalMs = options?.intervalMs ?? POLL_INTERVAL_MS;
  const maxAttempts = options?.maxAttempts ?? 400;
  const signal = options?.signal;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (signal?.aborted) {
      throw new DOMException("Polling aborted", "AbortError");
    }

    const job = await getJob(id, { token: options?.token, signal });
    onTick(job);

    if (isTerminalState(job.state)) {
      return job;
    }

    await delay(intervalMs, signal);
  }

  throw new ApiError(
    `Timed out waiting for job ${id} to complete after ${maxAttempts} polls.`,
    0,
  );
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

// ---------------------------------------------------------------------------
// ENTERPRISE — Identity & SSO (Epic 2): a workspace's SAML/OIDC connection, SCIM
// 2.0 provisioning tokens, and login security policy. Every fetcher here targets
// a workspace-scoped, `workspace.settings`-gated endpoint (owner/admin only): a
// non-member/viewer gets a 403 and an unknown workspace a 404 (both surfaced as
// {@link ApiError}). TENANT ISOLATION is the #1 invariant — no endpoint returns
// another tenant's data. SECRETS ARE WRITE-ONLY: the IdP signing cert / OIDC
// client secret are encrypted server-side and NEVER returned; a SCIM token's raw
// value is present ONLY in the one-time mint response.
// ---------------------------------------------------------------------------

/**
 * GET /me/workspaces/{id}/sso — the workspace's CERT-FREE SSO connection, or
 * `null` when none is configured. The IdP signing cert / OIDC secret are never
 * returned — only `has_certificate` / `has_client_secret`. Gated by
 * `workspace.settings`.
 */
export function getSsoConnection(
  workspaceId: string,
  options?: RequestOptions,
): Promise<SSOConnection | null> {
  return request<SSOConnection | null>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/sso`,
    { options },
  );
}

/**
 * PUT /me/workspaces/{id}/sso — create/update the workspace's IdP connection.
 * `body.idp_x509_cert` / `body.oidc_client_secret` are WRITE-ONLY (encrypted at
 * rest, never echoed back); send a secret only when setting/rotating it. `protocol`
 * must be `saml` | `oidc` (400 otherwise). Returns the cert-free connection and
 * writes an `sso.configured` audit row. Gated by `workspace.settings`.
 */
export function putSsoConnection(
  workspaceId: string,
  body: SSOConfigRequest,
  options?: RequestOptions,
): Promise<SSOConnection> {
  return request<SSOConnection>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/sso`,
    { method: "PUT", body, options },
  );
}

/**
 * DELETE /me/workspaces/{id}/sso — remove the workspace's SSO connection (404
 * when none is configured). Writes an `sso.deleted` audit row. Gated by
 * `workspace.settings`.
 */
export function deleteSsoConnection(
  workspaceId: string,
  options?: RequestOptions,
): Promise<{ deleted: boolean; workspace_id: string }> {
  return request<{ deleted: boolean; workspace_id: string }>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/sso`,
    { method: "DELETE", options },
  );
}

/**
 * The absolute, public URL an IdP admin fetches for a workspace's SP SAML
 * metadata (`GET /sso/{id}/metadata`, served as `application/samlmetadata+xml`).
 * Built from the configured API base; no secret is involved.
 */
export function ssoMetadataUrl(workspaceId: string): string {
  return `${API_BASE}/sso/${encodeURIComponent(workspaceId)}/metadata`;
}

/**
 * The absolute, canonical SP AssertionConsumerService (ACS) URL for a workspace
 * (`POST /sso/{id}/acs`) — the deterministic endpoint an IdP posts the SAML
 * assertion to. Used to seed the connection's `sp_acs_url` so the SP metadata is
 * correct from the first save. No secret.
 */
export function ssoAcsUrl(workspaceId: string): string {
  return `${API_BASE}/sso/${encodeURIComponent(workspaceId)}/acs`;
}

/**
 * The absolute base URL an IdP uses for this workspace's SCIM 2.0 provisioning
 * (`/scim/v2/{id}`), to paste alongside the minted bearer token. No secret.
 */
export function scimBaseUrl(workspaceId: string): string {
  return `${API_BASE}/scim/v2/${encodeURIComponent(workspaceId)}`;
}

/**
 * GET /sso/{id}/metadata — the workspace's SP SAML metadata as raw XML. PUBLIC by
 * design (the IdP admin consumes it). A workspace with no SSO connection is a 404
 * (surfaced as {@link ApiError}). Returns the metadata as a {@link SSOMetadata}
 * descriptor (the raw XML under `metadata_xml`).
 */
export async function getSsoMetadata(
  workspaceId: string,
  options?: RequestOptions,
): Promise<SSOMetadata> {
  const url = `${API_BASE}/sso/${encodeURIComponent(workspaceId)}/metadata`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "GET",
      // Public endpoint — fetched anonymously (no caller token, no app key).
      signal: options?.signal,
      cache: "no-store",
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(
      `Network error fetching SP metadata: ${
        err instanceof Error ? err.message : String(err)
      }`,
      0,
      err,
    );
  }
  const xml = await res.text();
  if (!res.ok) {
    throw new ApiError(
      `Could not load SP metadata (status ${res.status}).`,
      res.status,
      xml,
    );
  }
  return { workspace_id: workspaceId, entity_id: "", acs_url: "", metadata_xml: xml };
}

/**
 * GET /me/workspaces/{id}/scim/tokens — the workspace's SCIM bearer tokens
 * (ids/prefixes/status; NEVER a raw token). The backend returns the list under
 * `data` (omitted entirely when empty); both an array and a `{ tokens: [...] }`
 * wrapper are normalized to a `ScimToken[]`. Gated by `workspace.settings`.
 */
export async function listScimTokens(
  workspaceId: string,
  options?: RequestOptions,
): Promise<ScimToken[]> {
  const data = await request<ScimToken[] | { tokens?: ScimToken[] }>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/scim/tokens`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.tokens ?? [];
}

/**
 * POST /me/workspaces/{id}/scim/tokens — mint a per-workspace SCIM bearer token.
 * The raw `token` is returned EXACTLY ONCE here (store it now — only its digest is
 * persisted). Writes a `scim.token_created` audit row. Gated by
 * `workspace.settings`.
 */
export function createScimToken(
  workspaceId: string,
  options?: RequestOptions,
): Promise<ScimToken> {
  return request<ScimToken>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/scim/tokens`,
    { method: "POST", options },
  );
}

/**
 * DELETE /me/workspaces/{id}/scim/tokens/{tokenId} — revoke a workspace's SCIM
 * token (404 when unknown). Workspace-scoped: a caller can never revoke another
 * workspace's token. Writes a `scim.token_revoked` audit row. Gated by
 * `workspace.settings`.
 */
export function revokeScimToken(
  workspaceId: string,
  tokenId: string,
  options?: RequestOptions,
): Promise<{ revoked: boolean; token_id: string }> {
  return request<{ revoked: boolean; token_id: string }>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/scim/tokens/${encodeURIComponent(
      tokenId,
    )}`,
    { method: "DELETE", options },
  );
}

/**
 * GET /me/workspaces/{id}/security — the workspace's login security policy, or
 * `null` when none has been configured yet. Cert-free / secret-free. Gated by
 * `workspace.settings`.
 */
export function getSecurityPolicy(
  workspaceId: string,
  options?: RequestOptions,
): Promise<SecurityPolicy | null> {
  return request<SecurityPolicy | null>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/security`,
    { options },
  );
}

/**
 * PUT /me/workspaces/{id}/security — apply a PARTIAL security-policy update; only
 * supplied fields are changed (a single rule can be toggled without resending the
 * whole policy). Returns the persisted policy and writes a
 * `security_policy.updated` audit row. Gated by `workspace.settings`.
 */
export function putSecurityPolicy(
  workspaceId: string,
  body: SecurityPolicyRequest,
  options?: RequestOptions,
): Promise<SecurityPolicy> {
  return request<SecurityPolicy>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/security`,
    { method: "PUT", body, options },
  );
}

// ---------------------------------------------------------------------------
// ENTERPRISE — Billing Platform (Epic 3): subscription, usage/entitlements,
// invoices, revenue. Management + reads are tenant-scoped server-side; the
// subscription/invoices management surface is gated by `billing.manage`, the
// usage/entitlements reads by workspace membership, and `/admin/revenue` by the
// platform `is_staff` gate. MONEY is always an integer minor unit (cents).
// ---------------------------------------------------------------------------

/**
 * GET /me/workspaces/{id}/subscription — the workspace's subscription, or `null`
 * when unset (it then resolves to base/free entitlements). Gated by
 * `billing.manage`; a caller without it (or from another workspace) gets 403.
 */
export function getSubscription(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Subscription | null> {
  return request<Subscription | null>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/subscription`,
    { options },
  );
}

/**
 * POST /me/workspaces/{id}/subscribe — start a Stripe checkout for a workspace
 * subscription; returns the hosted-checkout envelope (redirect the buyer to
 * `checkout_url`). No credits are granted here — the webhook fulfils the
 * subscription idempotently once Stripe confirms. Gated by `billing.manage`.
 */
export function subscribeWorkspace(
  workspaceId: string,
  body: SubscribeRequest,
  options?: RequestOptions,
): Promise<SubscribeResult> {
  return request<SubscribeResult>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/subscribe`,
    { method: "POST", body, options },
  );
}

/**
 * POST /me/workspaces/{id}/change-plan — switch the workspace's subscription plan.
 * The backend moves the LIVE provider subscription first (prorated, charged now)
 * and only then updates entitlements; `free` cancels the paid plan. Returns the
 * updated subscription. Gated by `billing.manage`.
 */
export function changeWorkspacePlan(
  workspaceId: string,
  body: ChangePlanRequest,
  options?: RequestOptions,
): Promise<Subscription> {
  return request<Subscription>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/change-plan`,
    { method: "POST", body, options },
  );
}

/**
 * POST /me/workspaces/{id}/cancel — cancel the workspace's subscription (status
 * -> `canceled`, so entitlements fall back to base/free). Returns the updated
 * subscription; 404 when there is none. Gated by `billing.manage`.
 */
export function cancelWorkspaceSubscription(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Subscription> {
  return request<Subscription>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/cancel`,
    { method: "POST", options },
  );
}

/**
 * GET /me/workspaces/{id}/entitlements — the caller's active-plan entitlement
 * bundle for the workspace (base/free when no live subscription). Tenant-scoped:
 * any member may read it; a caller from another workspace gets 403.
 */
export function getEntitlements(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Entitlements> {
  return request<Entitlements>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/entitlements`,
    { options },
  );
}

/**
 * GET /me/workspaces/{id}/usage?period=YYYY-MM — the workspace's metered usage
 * aggregate + per-metric overage for a billing month (defaults to the current
 * month). Tenant-scoped: any member may read it; a foreign caller gets 403.
 */
export function getWorkspaceUsage(
  workspaceId: string,
  period?: string,
  options?: RequestOptions,
): Promise<Usage> {
  const query = period ? `?period=${encodeURIComponent(period)}` : "";
  return request<Usage>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/usage${query}`,
    { options },
  );
}

/**
 * GET /me/workspaces/{id}/invoices — the workspace's invoices (newest first),
 * TENANT-SCOPED. The backend returns the list under `data` (omitted when empty);
 * both an array and a `{ invoices: [...] }` wrapper are normalized. Gated by
 * `billing.manage`; a viewer or a foreign caller gets 403.
 */
export async function listWorkspaceInvoices(
  workspaceId: string,
  options?: RequestOptions,
): Promise<Invoice[]> {
  const data = await request<Invoice[] | { invoices?: Invoice[] }>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/invoices`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.invoices ?? [];
}

/**
 * GET /admin/revenue — the platform-wide revenue summary (realized `paid`
 * revenue across ALL tenants). HARD-GATED on `is_staff`; a non-staff caller gets
 * 403. All amounts are integer minor units (cents).
 */
export function getRevenue(options?: RequestOptions): Promise<Revenue> {
  return request<Revenue>("/admin/revenue", { options });
}

// ---------------------------------------------------------------------------
// ENTERPRISE — API Platform (Epic 4): webhook SUBSCRIPTIONS + developer portal.
// A workspace registers a callback `url` + the `event_types` it wants pushed;
// each delivery rides the EXISTING hardened, HMAC-signed, SSRF-guarded delivery
// primitive server-side. Every subscription route is RBAC `workspace.settings`-
// gated and tenant-scoped (a foreign/unknown id is a 404/403). The HMAC signing
// secret is minted server-side and returned EXACTLY ONCE on create — the list /
// delivery reads are always SECRET-FREE. The developer portal is caller-scoped
// and read-only. No secrets are handled client-side here.
// ---------------------------------------------------------------------------

/**
 * The interactive API docs URL for the SDK-facing OpenAPI spec. Derived from the
 * API base by stripping the `/api/v1` suffix and appending `/docs` (the FastAPI
 * default). Prefer {@link DeveloperPortal.docs_url} when available (it is the
 * canonical, server-derived link); this is a static fallback for a first paint.
 */
export function docsUrl(): string {
  const origin = API_BASE.replace(/\/api\/v1\/?$/, "");
  return `${origin}/docs`;
}

/**
 * POST /me/workspaces/{id}/webhooks — register a webhook subscription and return
 * the HMAC signing `secret` EXACTLY ONCE. Gated by `workspace.settings`
 * (owner/admin); a non-member/viewer is 403 and an unknown workspace is 404. The
 * `url` is SSRF-validated server-side BEFORE any row is persisted — a loopback /
 * private / link-local / metadata target is rejected with 400 (surfaced as
 * {@link ApiError}), as is an unknown `event_type`. The returned
 * {@link CreatedWebhookSubscription.secret} is unrecoverable afterwards.
 */
export function createWebhookSubscription(
  workspaceId: string,
  body: WebhookSubscribeRequest,
  options?: RequestOptions,
): Promise<CreatedWebhookSubscription> {
  return request<CreatedWebhookSubscription>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks`,
    { method: "POST", body, options },
  );
}

/**
 * GET /me/workspaces/{id}/webhooks — the workspace's webhook subscriptions
 * (newest first), SECRET-FREE. Gated by `workspace.settings` and tenant-scoped.
 * The backend returns the list under `data` (omitted entirely when empty); both
 * an array and a `{ subscriptions: [...] }` wrapper are normalized here.
 */
export async function listWebhookSubscriptions(
  workspaceId: string,
  options?: RequestOptions,
): Promise<WebhookSubscription[]> {
  const data = await request<
    WebhookSubscription[] | { subscriptions?: WebhookSubscription[] }
  >(`/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks`, { options });
  if (Array.isArray(data)) return data;
  return data?.subscriptions ?? [];
}

/**
 * POST /me/webhooks/workspace — return the workspace that holds the caller's
 * webhooks, creating a personal one when they own none. Lets a user with no
 * workspace subscribe without a separate "create workspace" step.
 */
export function ensureWebhookWorkspace(
  options?: RequestOptions,
): Promise<{ workspace_id: string }> {
  return request<{ workspace_id: string }>("/me/webhooks/workspace", {
    method: "POST",
    options,
  });
}

/**
 * DELETE /me/workspaces/{id}/webhooks/{subscriptionId} — soft-revoke a
 * subscription. Gated by `workspace.settings`; tenant-scoped, so a foreign or
 * missing id yields a 404 (surfaced as {@link ApiError}). The revoke is audited.
 */
export function deleteWebhookSubscription(
  workspaceId: string,
  subscriptionId: string,
  options?: RequestOptions,
): Promise<{ id: string; revoked: boolean }> {
  return request<{ id: string; revoked: boolean }>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks/${encodeURIComponent(
      subscriptionId,
    )}`,
    { method: "DELETE", options },
  );
}

/**
 * POST /me/workspaces/{id}/webhooks/{subscriptionId}/test — send a signed
 * `webhook.test` event to the subscription's URL via the existing SSRF-guarded
 * delivery primitive. Gated by `workspace.settings`; tenant-scoped (foreign or
 * missing id -> 404). Returns the {@link WebhookDelivery} record reflecting the
 * attempt outcome (it also appears in the deliveries view).
 */
export function testWebhookSubscription(
  workspaceId: string,
  subscriptionId: string,
  options?: RequestOptions,
): Promise<WebhookDelivery> {
  return request<WebhookDelivery>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks/${encodeURIComponent(
      subscriptionId,
    )}/test`,
    { method: "POST", options },
  );
}

/**
 * GET /me/workspaces/{id}/webhooks/{subscriptionId}/deliveries — a
 * subscription's recent deliveries (newest first) with their status. Gated by
 * `workspace.settings` and tenant-scoped; the signed payload body is never
 * returned (delivery metadata only). `limit` is clamped server-side (1..100).
 * The backend returns the list under `data` (omitted when empty); both an array
 * and a `{ deliveries: [...] }` wrapper are normalized here.
 */
export async function listWebhookDeliveries(
  workspaceId: string,
  subscriptionId: string,
  limit?: number,
  options?: RequestOptions,
): Promise<WebhookDelivery[]> {
  const query =
    typeof limit === "number" && Number.isFinite(limit)
      ? `?limit=${encodeURIComponent(String(Math.max(1, Math.floor(limit))))}`
      : "";
  const data = await request<
    WebhookDelivery[] | { deliveries?: WebhookDelivery[] }
  >(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/webhooks/${encodeURIComponent(
      subscriptionId,
    )}/deliveries${query}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.deliveries ?? [];
}

/**
 * GET /me/developer — the caller-scoped developer-portal summary (READ-only,
 * secret-free): the caller's API-key footprint (counts + current-month request
 * usage), their webhook-subscription footprint across their workspaces, the
 * number of workspaces they belong to, and static integration links (API base
 * URL, OpenAPI/docs, version, supported webhook events).
 */
export function getDeveloperPortal(
  options?: RequestOptions,
): Promise<DeveloperPortal> {
  return request<DeveloperPortal>("/me/developer", { options });
}

// ---------------------------------------------------------------------------
// ENTERPRISE — Compliance (Epic 5): GDPR/SOC2 data governance. Every route is
// STRICTLY caller-scoped server-side (or gated by `workspace.settings` for the
// retention policy) — no path can export, erase, read or write another user's
// data. The `/admin/*` compliance calls are gated by the platform `is_staff`
// gate (a workspace owner is NOT staff). Every mutation is audited server-side.
// ---------------------------------------------------------------------------

/**
 * POST /me/data-export — assemble the CALLER'S OWN complete data package (GDPR
 * Art. 15/20) and return a SHORT-LIVED presigned download link to a private R2
 * object. The archive contains only the requesting caller's data; the link is
 * never a public URL. Audited server-side.
 */
export function exportMyData(options?: RequestOptions): Promise<DataExport> {
  return request<DataExport>("/me/data-export", { method: "POST", options });
}

/**
 * POST /me/erase — irreversibly ANONYMIZE the CALLER'S OWN account (GDPR Art.
 * 17). Requires an explicit `confirm: true` gate (a missing/false confirmation is
 * a 400 and nothing is erased). PII is tombstoned and credentials revoked while
 * financial/audit records are preserved. No target id is accepted, so a caller
 * can only ever erase themselves. Audited server-side.
 */
export function eraseMyAccount(
  options?: RequestOptions,
): Promise<ErasureRequest> {
  return request<ErasureRequest>("/me/erase", {
    method: "POST",
    body: { confirm: true },
    options,
  });
}

/**
 * GET /me/consent — the caller's full consent trail (append-only, oldest first).
 * Strictly caller-scoped; the backend returns the list under `data`. A `{ consents:
 * [...] }` wrapper is tolerated for forward-compat.
 */
export async function listMyConsents(
  options?: RequestOptions,
): Promise<ConsentRecord[]> {
  const data = await request<ConsentRecord[] | { consents?: ConsentRecord[] }>(
    "/me/consent",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.consents ?? [];
}

/**
 * PUT /me/consent — append an immutable consent decision for the CALLER (never
 * another user). `kind` is the dimension (e.g. `marketing` | `ai_disclosure`),
 * `granted` records grant/withdrawal, `version` the policy version. Audited.
 */
export function recordConsent(
  body: ConsentUpdateRequest,
  options?: RequestOptions,
): Promise<ConsentRecord> {
  return request<ConsentRecord>("/me/consent", {
    method: "PUT",
    body,
    options,
  });
}

/**
 * GET /me/workspaces/{id}/retention — a workspace's data-retention policy, or a
 * keep-forever default when none is configured. Gated by `workspace.settings`; a
 * viewer/non-member gets 403 (surfaced as {@link ApiError}) and never learns
 * another tenant's posture.
 */
export function getRetentionPolicy(
  workspaceId: string,
  options?: RequestOptions,
): Promise<RetentionPolicy> {
  return request<RetentionPolicy>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/retention`,
    { options },
  );
}

/**
 * PUT /me/workspaces/{id}/retention — set a workspace's retention window (a full
 * replace of both dimensions; `null` means keep-forever, a negative value is a
 * 400). Only a workspace owner/admin (`workspace.settings`) may set it — a viewer
 * gets 403 BEFORE any write, and no other tenant's data is ever touched. Audited.
 */
export function setRetentionPolicy(
  workspaceId: string,
  body: RetentionUpdateRequest,
  options?: RequestOptions,
): Promise<RetentionPolicy> {
  return request<RetentionPolicy>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/retention`,
    { method: "PUT", body, options },
  );
}

/**
 * GET /admin/erasure-requests — every right-to-erasure request across every
 * tenant (newest first). PLATFORM-ADMIN ONLY: a non-staff caller gets a 403, a
 * missing/invalid token a 401 (both surfaced as {@link ApiError}). The backend
 * returns the list under `data`; a `{ requests: [...] }` wrapper is tolerated.
 */
export async function adminListErasureRequests(
  params: AdminListParams = {},
  options?: RequestOptions,
): Promise<ErasureRequest[]> {
  const data = await request<
    ErasureRequest[] | { requests?: ErasureRequest[] }
  >(`/admin/erasure-requests${adminListQuery(params)}`, { options });
  if (Array.isArray(data)) return data;
  return data?.requests ?? [];
}

/**
 * POST /admin/erasure/{userId} — operator-initiated erasure of a TARGET user
 * (staff-only, audited with the operator as actor). A non-staff caller gets a
 * 403, an unknown target a 400 (both surfaced as {@link ApiError}). Anonymizes
 * the target's PII in place while preserving financial/audit records.
 */
export function adminEraseUser(
  userId: string,
  options?: RequestOptions,
): Promise<ErasureRequest> {
  return request<ErasureRequest>(
    `/admin/erasure/${encodeURIComponent(userId)}`,
    { method: "POST", options },
  );
}

/**
 * GET /admin/retention — every configured workspace retention policy across all
 * tenants (an operator's retention-posture overview). PLATFORM-ADMIN ONLY (403
 * for non-staff, 401 unauthenticated). The backend returns the list under `data`;
 * a `{ policies: [...] }` wrapper is tolerated.
 */
export async function adminRetentionOverview(
  options?: RequestOptions,
): Promise<RetentionPolicy[]> {
  const data = await request<
    RetentionPolicy[] | { policies?: RetentionPolicy[] }
  >("/admin/retention", { options });
  if (Array.isArray(data)) return data;
  return data?.policies ?? [];
}
