/**
 * Typed fetch client for the ReelForge backend v1 API (§5 of
 * docs/reelforge/INTEGRATION_CONTRACT.md). This is the React Native / Expo
 * mirror of web/lib/api.ts — same endpoints, same envelope handling, same
 * §5 shapes. The only platform difference is the binary upload path, which
 * uses expo-file-system's uploadAsync (React Native has no `File` object).
 *
 * Auth: every request sends an `x-api-key` header. The value is either an
 * explicit per-call token (the user's API key held in the session) or, as a
 * fallback, the public app key from EXPO_PUBLIC_APP_API_KEY. No secrets are
 * hardcoded here.
 */

import * as FileSystem from "expo-file-system/legacy";

import type {
  Avatar,
  CreateAvatarRequest,
  CreateAvatarResult,
  CaptionStyle,
  CheckoutRequest,
  CheckoutResult,
  HookCatalog,
  Insights,
  Analytics,
  AnalyticsBreakdownItem,
  AnalyticsFunnel,
  AnalyticsPoint,
  RenderTimeStats,
  Job,
  JobCancelResult,
  JobCreateRequest,
  JobCreateResult,
  JobDeleteResult,
  JobUpdateRequest,
  LayoutOption,
  Me,
  MusicTrack,
  MusicGenerator,
  StockLibraryFile,
  StockLibraryListResult,
  StockLibraryUploadResult,
  Plan,
  PaymentProvider,
  ProvidersResult,
  Preset,
  PresetCreateRequest,
  PresetDeleteResult,
  PresignRequest,
  PresignResult,
  RedeemResult,
  Referral,
  RerunOverrides,
  Template,
  UserVoice,
  CloneVoiceRequest,
  VoiceDeleteResult,
  Voice,
  Idea,
  GenerateIdeasRequest,
  SavedIdea,
  SaveIdeaResult,
  IdeaDeleteResult,
  NotificationsResult,
  ListNotificationsQuery,
  MarkNotificationReadResult,
  MarkAllNotificationsReadResult,
  DubLanguage,
  DubJobRequest,
  DubJobResult,
  ScheduledPublish,
  SchedulePublishRequest,
  ListScheduledQuery,
  CancelScheduledResult,
  CoverStyle,
  GenerateCoverRequest,
  CoverResult,
  Workspace,
  WorkspaceMember,
  CreateWorkspaceRequest,
  InviteMemberRequest,
  SetMemberRoleRequest,
  WorkspaceRole,
  RemoveMemberResult,
  LeaveWorkspaceResult,
  WorkspaceCredits,
  GrantWorkspaceCreditsRequest,
  Permission,
  Permissions,
  AuditEntry,
  AuditLogParams,
  AdminUser,
  AdminWorkspace,
  AdminJob,
  AdminListParams,
  Impersonation,
  Brand,
  BrandUpdate,
  BrollClip,
  SuggestBrollRequest,
  BrollGenerateRequest,
  BrollGeneration,
  BrollPreset,
  SocialPlatform,
  SocialRequest,
  SocialMetadataRequest,
  SocialMeta,
  ApiKey,
  ApiKeyCreated,
  ApiKeyRevokeResult,
  ApiKeyUsage,
  Connection,
  AuthorizeInfo,
  PublishResult,
  PilotCapabilities,
  LaunchStatus,
  DisconnectResult,
  SocialProvider,
  MarketplaceTemplate,
  MarketplaceBrowseParams,
  PublishTemplateRequest,
  ClonedTemplate,
  MarketplaceUnpublishResult,
  LogPerformanceRequest,
  JobPerformance,
  WinningHook,
  WinningTemplate,
  MarketplaceLineage,
  ShareLink,
  SharePublic,
  ShareRevokeResult,
  CreatorProfile,
  FollowResult,
  LeaderboardEntry,
  LeaderboardMetric,
  ProfileUpdateRequest,
  BackgroundClip,
  UrlIngestResult,
} from "./types";
import {
  API_BASE,
  ApiError,
  POLL_INTERVAL_MS,
  apiRequest as request,
  isAbortError,
  type RequestOptions,
} from "@/src/shared/api";
import { pollUntilTerminal } from "@/src/shared/lifecycle";
export {
  API_BASE,
  ApiError,
  POLL_INTERVAL_MS,
  isAbortError,
  type RequestOptions,
} from "@/src/shared/api";
import {
  isTerminalState,
  PAYMENT_PROVIDERS,
  MAX_MARKETPLACE_LIMIT,
  MAX_LEADERBOARD_LIMIT,
} from "./types";

// ---------------------------------------------------------------------------
// §5 endpoints
// ---------------------------------------------------------------------------

export interface DeviceSession {
  api_key: string;
  created: boolean;
  credits: number;
  user_id: string;
  /**
   * True when the server bound this install to a verified Apple/Google
   * identity. Present on identity exchanges; false/absent for plain device
   * sessions.
   */
  linked?: boolean;
}

/**
 * POST /auth/device — exchange a SecureStore installation id for an account.
 *
 * When the user signed in with Apple/Google, pass the Supabase access token as
 * `identityToken`: the backend verifies it and resolves the named account for
 * that identity (so a reinstall or a second device lands on the same account)
 * instead of deriving a fresh device account from `install_id` alone.
 */
export function createDeviceSession(
  installId: string,
  platform: "ios" | "android",
  identityToken?: string,
): Promise<DeviceSession> {
  const token = identityToken?.trim();
  return request<DeviceSession>("/auth/device", {
    method: "POST",
    body: token
      ? { install_id: installId, platform, supabase_access_token: token }
      : { install_id: installId, platform },
  });
}

/** The outcome of a push-token registration. */
export interface PushTokenRegistration {
  registered: boolean;
}

/**
 * POST /me/push-tokens — register (upsert) this install's Expo push token so the
 * backend can deliver an out-of-app push the moment a render finishes, alongside
 * the in-app notification it already creates on job completion. Mirrors
 * {@link createDeviceSession}'s shape and auth: the caller passes the same stable
 * SecureStore `installId` (so re-registering just refreshes the token for this
 * device rather than piling up rows) and authenticates with the session key via
 * `options.token`, exactly like every other authed call.
 *
 * `expoToken` is the value from `Notifications.getExpoPushTokenAsync` — an
 * `ExponentPushToken[...]` string that Expo's push service maps to the device's
 * APNs/FCM token, so no native APNs/FCM code lives on the client. `platform`
 * lets the backend pick the right delivery channel. The response reports whether
 * the token is now stored.
 */
export function registerPushToken(
  expoToken: string,
  platform: "ios" | "android",
  installId: string,
  options?: RequestOptions,
): Promise<PushTokenRegistration> {
  return request<PushTokenRegistration>("/me/push-tokens", {
    method: "POST",
    body: { expo_token: expoToken, platform, install_id: installId },
    options,
  });
}

/**
 * DELETE /me/push-tokens/{install_id} — stop delivering pushes to this install
 * for the signed-in account. Called on sign-out (with the outgoing session key)
 * so the next person on this phone never receives the previous account's job
 * or publish notifications. A 404 means the install had no active token for
 * this account, which is already the desired end state.
 */
export async function unregisterPushToken(
  installId: string,
  options?: RequestOptions,
): Promise<void> {
  try {
    await request<{ deleted: boolean }>(
      `/me/push-tokens/${encodeURIComponent(installId)}`,
      { method: "DELETE", options },
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return;
    throw error;
  }
}

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
 * variant (see {@link JobCreateResult}).
 *
 * EDITING POLISH: `body` may also carry the three opt-in, default-off polish
 * passes applied to the SCREEN RECORDING pre-compose — `auto_zoom` (scene-driven
 * punch-in), `camera_motion` (a {@link CameraMotion} preset), and `remove_bg`
 * (neural avatar background matting). Each is duration-preserving, degrade-safe,
 * and persisted in `Job.params`; omitting all three preserves current behaviour.
 *
 * BRING YOUR OWN VOICEOVER (BYOV): set `params.voiceover_key` to the R2 key of a
 * narration audio the creator uploaded via {@link presignAndUpload}. The backend
 * then transcribes that audio (faster-whisper) for the captions and uses it as
 * the reel's narration + avatar lip-sync instead of TTS — no `voice_id` needed.
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
export async function listJobs(
  options?: RequestOptions,
  query?: { includeArchived?: boolean },
): Promise<Job[]> {
  const path = query?.includeArchived ? "/jobs?include_archived=true" : "/jobs";
  const data = await request<Job[] | { jobs?: Job[] }>(path, { options });
  if (Array.isArray(data)) return data;
  return data?.jobs ?? [];
}

/**
 * PATCH /jobs/{id} — rename and/or archive a reel the caller owns. Only the
 * supplied fields change; returns the updated job snapshot.
 */
export function updateJob(
  id: string,
  body: JobUpdateRequest,
  options?: RequestOptions,
): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body,
    options,
  });
}

/** Rename a reel. An empty title clears it back to the job id. */
export function renameJob(
  id: string,
  title: string,
  options?: RequestOptions,
): Promise<Job> {
  const trimmed = title.trim();
  return updateJob(id, { title: trimmed ? trimmed : null }, options);
}

/** Archive (or restore) a reel. */
export function archiveJob(
  id: string,
  archived: boolean,
  options?: RequestOptions,
): Promise<Job> {
  return updateJob(id, { archived }, options);
}

/**
 * POST /jobs/{id}/cancel — stop an in-flight reel. The backend releases any
 * unspent held credits through the wallet ledger and reports them as
 * `refunded_credits`.
 */
export async function cancelJob(
  id: string,
  options?: RequestOptions,
): Promise<JobCancelResult> {
  // The API returns either the cancelled job directly or `{ job, refunded_credits }`.
  const data = await request<JobCancelResult | { job?: Job; refunded_credits?: number }>(
    `/jobs/${encodeURIComponent(id)}/cancel`,
    { method: "POST", options },
  );
  if (data && typeof data === "object" && "job" in data && data.job) {
    return { ...data.job, cancelled: true, refunded_credits: data.refunded_credits };
  }
  return { ...(data as JobCancelResult), cancelled: true };
}

/**
 * DELETE /jobs/{id} — permanently delete a reel and its stored outputs. An
 * in-flight reel is cancelled (and refunded) first by the backend.
 */
export function deleteJob(
  id: string,
  options?: RequestOptions,
): Promise<JobDeleteResult> {
  return request<JobDeleteResult>(`/jobs/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}

/** The display name for a reel: its title when set, otherwise its hook or id. */
export function jobDisplayName(job: Job): string {
  const title = typeof job.title === "string" ? job.title.trim() : "";
  if (title) return title;
  const hook = typeof job.hook === "string" ? job.hook.trim() : "";
  return hook || job.job_id;
}

/** GET /jobs/{id} */
export function getJob(id: string, options?: RequestOptions): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}`, { options });
}

/** POST /jobs/{id}/retry */
export function retryJob(id: string, options?: RequestOptions): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(id)}/retry`, {
    method: "POST",
    options,
  });
}

/**
 * POST /ingest/url — read a product or article page and return its extracted
 * content (title, description, features) plus a submittable reel draft. The
 * one-flow create writes its three hook variants from this content.
 */
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
 * GET /templates/backgrounds — curated looping background clips a reel can sit
 * over when there is no screen recording. `available: false` rows are
 * catalogued but missing on this server; callers pick an available one.
 */
export async function listBackgrounds(
  category?: string,
  options?: RequestOptions,
): Promise<BackgroundClip[]> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : "";
  const data = await request<{ backgrounds?: BackgroundClip[] } | BackgroundClip[]>(
    `/templates/backgrounds${qs}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return Array.isArray(data?.backgrounds) ? data.backgrounds : [];
}

/** GET /avatars */
export function listAvatars(options?: RequestOptions): Promise<Avatar[]> {
  return request<Avatar[]>("/avatars", { options });
}

/**
 * POST /avatars — turn a creator's uploaded selfie into a private HeyGen
 * *talking-photo* avatar. `body.image_key` is the R2 key of a photo the caller
 * uploaded via {@link presignAndUpload} (and owns — a foreign key is rejected
 * 403 server-side before any provider work). The backend uploads the image to
 * HeyGen, mints a `talking_photo_id`, and stores an owner-scoped `AvatarPreset`
 * (`provider='heygen'`, `config.kind='talking_photo'`) that then appears in
 * {@link listAvatars} (as `source: "preset"`) for use in jobs — its
 * `provider_avatar_id` is what drives the reel's avatar lip-sync. Requires
 * HeyGen to be configured server-side (503 otherwise).
 */
export function createAvatarFromPhoto(
  body: CreateAvatarRequest,
  options?: RequestOptions,
): Promise<CreateAvatarResult> {
  return request<CreateAvatarResult>("/avatars", {
    method: "POST",
    body,
    options,
  });
}

/** GET /voices */
export function listVoices(options?: RequestOptions): Promise<Voice[]> {
  return request<Voice[]>("/voices", { options });
}

/** GET /me */
export function me(options?: RequestOptions): Promise<Me> {
  return request<Me>("/me", { options });
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
 * GET /billing/providers — the payment providers that are enabled (configured)
 * for checkout right now. A provider only appears when its required secret(s)
 * are present server-side, so the UI can render only the rails that will
 * actually work (Stripe / iyzico / Creem / Polar). No auth required. The backend
 * may return the list wrapped as `{ providers: [...] }` or directly as `data`;
 * both shapes are normalized to a `PaymentProvider[]` here (unknown/blank values
 * are dropped so a garbled payload degrades to an empty list rather than
 * rendering a dead rail).
 */
export async function getProviders(
  options?: RequestOptions,
): Promise<PaymentProvider[]> {
  const data = await request<ProvidersResult | PaymentProvider[]>(
    "/billing/providers",
    { options },
  );
  const raw = Array.isArray(data) ? data : data?.providers;
  if (!Array.isArray(raw)) return [];
  return raw.filter((p): p is PaymentProvider =>
    (PAYMENT_PROVIDERS as readonly string[]).includes(p),
  );
}

/**
 * POST /billing/checkout — starts a hosted checkout for `plan_key` via the
 * chosen `provider` (Stripe, iyzico for TR, or the Creem / Polar
 * merchant-of-record rails) and returns the URL the buyer should be opened to
 * (via expo-web-browser / Linking).
 *
 * Set `body.workspace_id` to buy the SAME pack for a workspace's SHARED credit
 * pool instead of the caller's personal balance: the backend carries that id in
 * the Stripe Checkout metadata and, on webhook fulfillment, grants to the
 * workspace pool (`CreditRepository.workspace_grant`) rather than the user —
 * still fully idempotent. Requires the caller to be an owner/admin (authorized
 * server-side). Omitting it preserves the existing personal-purchase behaviour.
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
 * GET /catalog/music-generators — the AI background-music providers whose API
 * keys are configured server-side (`is_enabled()`), reusing MPT's vendored
 * `elevenlabs_music` / `sonilo` integrations. Each entry is
 * `{ id, name, max_prompt_length }`; `id` is what {@link createJob} accepts as
 * `bgm_provider`. The UI shows a "Generate with AI" option only when this list
 * is non-empty. The backend degrades to `[]` (never 500) when no provider is
 * available, so an empty list simply hides the feature.
 */
export function listMusicGenerators(
  options?: RequestOptions,
): Promise<MusicGenerator[]> {
  return request<MusicGenerator[]>("/catalog/music-generators", { options });
}

// ---------------------------------------------------------------------------
// Legacy MoneyPrinterTurbo standalone stock libraries
//   GET/POST /musics           — background-music (BGM) library
//   GET/POST /video_materials  — local video-materials library
//
// These predate the creator-studio `GET /catalog/*` galleries and expose the
// raw server-side file stores. GET returns `{ files: StockLibraryFile[] }`;
// POST is a multipart/form-data upload of a single `file` field and returns the
// stored basename. Binary upload uses expo-file-system's MULTIPART task because
// React Native has no `File`/`FormData(file)` primitive (mirrors
// {@link presignAndUpload}). The auth credential (`x-api-key`) is echoed
// exactly the way {@link apiRequest} builds it.
// ---------------------------------------------------------------------------

/** The public app key used when no per-call token is supplied (mirrors client). */
const STOCK_APP_API_KEY = process.env.EXPO_PUBLIC_APP_API_KEY || "";

/** MIME types the backend accepts for a video-material upload. */
const VIDEO_MATERIAL_MIME_BY_EXT: Readonly<Record<string, string>> = {
  mp4: "video/mp4",
  mov: "video/quicktime",
  avi: "video/x-msvideo",
  flv: "video/x-flv",
  mkv: "video/x-matroska",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
};

/** MIME types the backend accepts for a background-music upload. */
const BGM_MIME_BY_EXT: Readonly<Record<string, string>> = {
  mp3: "audio/mpeg",
  m4a: "audio/mp4",
  aac: "audio/aac",
  wav: "audio/wav",
  flac: "audio/flac",
  ogg: "audio/ogg",
  opus: "audio/opus",
  wma: "audio/x-ms-wma",
};

/**
 * POST a single file to a legacy stock-library endpoint as multipart/form-data
 * and return the stored basename. Shared by {@link uploadBgmFile} and
 * {@link uploadVideoMaterial}. Streams from disk (never buffered into JS) and
 * unwraps the standard `{ data }` envelope from the raw response body.
 */
async function uploadStockLibraryFile(
  path: "/musics" | "/video_materials",
  file: LocalFile,
  options?: RequestOptions & { onProgress?: (fraction: number) => void },
): Promise<StockLibraryUploadResult> {
  const { onProgress, token } = options ?? {};
  const credential = token || STOCK_APP_API_KEY;
  const headers: Record<string, string> = {};
  if (credential) headers["x-api-key"] = credential;

  onProgress?.(0);

  const task = FileSystem.createUploadTask(
    `${API_BASE}${path}`,
    file.uri,
    {
      httpMethod: "POST",
      uploadType: FileSystem.FileSystemUploadType.MULTIPART,
      fieldName: "file",
      mimeType: file.mimeType || "application/octet-stream",
      // The FastAPI handler reads `UploadFile.filename`; send the real name so
      // its extension allow-list check passes.
      parameters: { filename: file.name },
      headers,
    },
    (progress) => {
      if (progress.totalBytesExpectedToSend > 0) {
        onProgress?.(
          progress.totalBytesSent / progress.totalBytesExpectedToSend,
        );
      }
    },
  );

  let result: FileSystem.FileSystemUploadResult | null | undefined;
  try {
    result = await task.uploadAsync();
  } catch (err) {
    throw new ApiError(
      `Failed to upload file: ${err instanceof Error ? err.message : String(err)}`,
      0,
      err,
    );
  }

  const body = result?.body ?? "";
  let envelope: { data?: StockLibraryUploadResult; message?: string | null } | null =
    null;
  if (body) {
    try {
      envelope = JSON.parse(body) as {
        data?: StockLibraryUploadResult;
        message?: string | null;
      };
    } catch {
      envelope = null;
    }
  }

  if (!result || result.status < 200 || result.status >= 300) {
    throw new ApiError(
      envelope?.message || `Upload rejected (${result?.status ?? "no response"}).`,
      result?.status ?? 0,
      envelope ?? body,
    );
  }

  const payload = envelope?.data ?? (envelope as unknown as StockLibraryUploadResult);
  if (!payload || typeof payload.file !== "string" || payload.file.length === 0) {
    throw new ApiError(
      "Malformed upload response: the API did not return a stored filename.",
      result.status,
      body,
    );
  }
  onProgress?.(1);
  return { file: payload.file };
}

/** Guess the MIME type for a stock upload from its filename extension. */
function stockMimeFor(
  name: string,
  table: Readonly<Record<string, string>>,
  fallback: string,
): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return table[ext] ?? fallback;
}

/**
 * GET /musics — the standalone background-music (BGM) library. Returns the
 * files stored under the server's `storage/bgm` + `resource/songs` allow-list;
 * each entry's `file` is a basename to reference as a job's `bgm_file`.
 */
export async function listBgmFiles(
  options?: RequestOptions,
): Promise<StockLibraryFile[]> {
  const data = await request<StockLibraryListResult | StockLibraryFile[]>(
    "/musics",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.files ?? [];
}

/**
 * POST /musics — upload one MP3/M4A/AAC/WAV/FLAC/OGG/OPUS/WMA file (≤30 MB) to
 * the BGM library. The backend validates the audio stream and stores it under
 * an immutable UUID filename; the returned basename is what a job references.
 */
export function uploadBgmFile(
  file: LocalFile,
  options?: RequestOptions & { onProgress?: (fraction: number) => void },
): Promise<StockLibraryUploadResult> {
  const withMime: LocalFile = {
    ...file,
    mimeType: file.mimeType || stockMimeFor(file.name, BGM_MIME_BY_EXT, "audio/mpeg"),
  };
  return uploadStockLibraryFile("/musics", withMime, options);
}

/**
 * GET /video_materials — the standalone local video-materials library. Returns
 * the clips/images stored under the server's `local_videos` allow-list (sorted
 * by basename); each entry's `file` is a basename usable as a local material.
 */
export async function listVideoMaterials(
  options?: RequestOptions,
): Promise<StockLibraryFile[]> {
  const data = await request<StockLibraryListResult | StockLibraryFile[]>(
    "/video_materials",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.files ?? [];
}

/**
 * POST /video_materials — upload one MP4/MOV/AVI/FLV/MKV/JPG/JPEG/PNG file to
 * the local video-materials library. The backend validates the extension and
 * stores the file; the returned basename is what a job references.
 */
export function uploadVideoMaterial(
  file: LocalFile,
  options?: RequestOptions & { onProgress?: (fraction: number) => void },
): Promise<StockLibraryUploadResult> {
  const withMime: LocalFile = {
    ...file,
    mimeType:
      file.mimeType || stockMimeFor(file.name, VIDEO_MATERIAL_MIME_BY_EXT, "video/mp4"),
  };
  return uploadStockLibraryFile("/video_materials", withMime, options);
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
 * GET /catalog/hooks — native hook lines keyed by language code. Returns an
 * empty map when the catalog is unavailable (the backend degrades to `{}`).
 */
export function listHooks(options?: RequestOptions): Promise<HookCatalog> {
  return request<HookCatalog>("/catalog/hooks", { options });
}

// ---------------------------------------------------------------------------
// Growth surfaces (auth-gated; GET/POST /me/*)
// ---------------------------------------------------------------------------

/** GET /me/insights */
export function getInsights(options?: RequestOptions): Promise<Insights> {
  return request<Insights>("/me/insights", { options });
}

// --- Analytics / creator dashboard (GET /me/analytics?days=N) ---------------

/** Coerce an unknown to a finite number, falling back to `fallback` (default 0). */
function toNumber(value: unknown, fallback = 0): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}

/** Normalize an unknown array of `{ date, value }` day buckets, dropping junk. */
function normalizePoints(value: unknown, valueKey = "value"): AnalyticsPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
    .map((p) => ({ date: String(p.date ?? ""), value: toNumber(p[valueKey]) }))
    .filter((p) => p.date.length > 0);
}

/** Normalize an unknown array of `{ key, label?, count }` breakdown rows. */
function normalizeBreakdown(value: unknown): AnalyticsBreakdownItem[] {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value as Record<string, unknown>).map(([key, count]) => ({
      key,
      count: toNumber(count),
    }));
  }
  if (!Array.isArray(value)) return [];
  return value
    .filter((r): r is Record<string, unknown> => !!r && typeof r === "object")
    .map((r) => ({
      key: String(r.key ?? ""),
      label: typeof r.label === "string" ? r.label : undefined,
      count: toNumber(r.count),
    }))
    .filter((r) => r.key.length > 0);
}

function normalizeNamedBreakdown(value: unknown): AnalyticsBreakdownItem[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((row): row is Record<string, unknown> => !!row && typeof row === "object")
    .map((row) => {
      const key = String(row.key ?? row.hook ?? row.name ?? "");
      return { key, label: key, count: toNumber(row.count) };
    })
    .filter((row) => row.key.length > 0);
}

function normalizeFunnel(value: unknown): AnalyticsFunnel {
  const f = (value ?? {}) as Record<string, unknown>;
  return {
    created: toNumber(f.created),
    completed: toNumber(f.completed),
    published: toNumber(f.published),
  };
}

function normalizeTrendFunnel(value: unknown): Analytics["trend_funnel"] {
  const source = (value ?? {}) as Record<string, unknown>;
  const byTrend = Array.isArray(source.by_trend) ? source.by_trend : [];
  return {
    ...normalizeFunnel(source),
    by_trend: byTrend
      .filter((row): row is Record<string, unknown> => !!row && typeof row === "object")
      .map((row) => ({
        key: String(row.key ?? ""),
        label: typeof row.label === "string" ? row.label : undefined,
        ...normalizeFunnel(row),
      }))
      .filter((row) => row.key.length > 0),
  };
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeForecastTrace(value: unknown): Analytics["forecast_trace"] {
  const source = value && typeof value === "object"
    ? value as Record<string, unknown>
    : {};
  const traces = Array.isArray(source.traces) ? source.traces : [];
  const comparisons = Array.isArray(source.by_content_type) ? source.by_content_type : [];
  return {
    status: source.status === "available" ? "available" : "unavailable",
    traces: traces
      .filter((row): row is Record<string, unknown> => !!row && typeof row === "object")
      .map((row) => ({
        forecast_id: String(row.forecast_id ?? ""),
        trend_observation_id: String(row.trend_observation_id ?? ""),
        trend_id: String(row.trend_id ?? ""),
        trend_label: String(row.trend_label ?? row.trend_id ?? ""),
        content_type: String(row.content_type ?? "short_video"),
        expected_reach: toNumber(row.expected_reach),
        forecast_created_at: typeof row.forecast_created_at === "string" ? row.forecast_created_at : null,
        job_id: typeof row.job_id === "string" ? row.job_id : null,
        job_state: String(row.job_state ?? "not_started"),
        result_ready: row.result_ready === true,
        publish_status: String(row.publish_status ?? "not_started"),
        publish_platform: typeof row.publish_platform === "string" ? row.publish_platform : null,
        publish_event_at: typeof row.publish_event_at === "string" ? row.publish_event_at : null,
        measurement_status: row.measurement_status === "measured" ? "measured" as const : "pending" as const,
        actual_reach: nullableNumber(row.actual_reach),
        delta: nullableNumber(row.delta),
        delta_pct: nullableNumber(row.delta_pct),
        reach_platform: typeof row.reach_platform === "string" ? row.reach_platform : null,
      }))
      .filter((row) => row.forecast_id.length > 0),
    by_content_type: comparisons
      .filter((row): row is Record<string, unknown> => !!row && typeof row === "object")
      .map((row) => ({
        content_type: String(row.content_type ?? "short_video"),
        measured: toNumber(row.measured),
        pending: toNumber(row.pending),
        expected_reach: nullableNumber(row.expected_reach),
        actual_reach: nullableNumber(row.actual_reach),
        delta: nullableNumber(row.delta),
        delta_pct: nullableNumber(row.delta_pct),
      })),
  };
}

function normalizeRenderTime(value: unknown): RenderTimeStats {
  const r = (value ?? {}) as Record<string, unknown>;
  return {
    p50_ms: toNumber(r.p50_ms),
    p90_ms: toNumber(r.p90_ms),
    avg_ms: toNumber(r.avg_ms),
    count: toNumber(r.count ?? r.samples),
  };
}

/**
 * GET /me/analytics — the caller-scoped BI dashboard: funnel, cost/credit-burn
 * daily series, compose render-time distribution, and usage breakdowns. `days`
 * bounds the trailing window (the backend clamps it; defaults server-side when
 * omitted). The payload is normalized defensively so a partial/legacy response
 * still renders instead of throwing.
 */
export async function getAnalytics(
  days?: number,
  options?: RequestOptions,
): Promise<Analytics> {
  const query: string[] = [];
  if (typeof days === "number" && Number.isFinite(days)) {
    query.push(`days=${encodeURIComponent(String(Math.trunc(days)))}`);
  }
  const qs = query.length > 0 ? `?${query.join("&")}` : "";

  const data = await request<Record<string, unknown>>(`/me/analytics${qs}`, {
    options,
  });
  const credits = (data.credits ?? {}) as Record<string, unknown>;
  const totals = (data.totals ?? {}) as Record<string, unknown>;
  const topContent = (data.top_content ?? {}) as Record<string, unknown>;
  return {
    user_id: typeof data.user_id === "string" ? data.user_id : "",
    days: toNumber(data.days, typeof days === "number" ? days : 0),
    funnel: normalizeFunnel(data.funnel),
    cost_by_day: normalizePoints(data.cost_by_day, "cost_usd"),
    credits_burn_by_day: normalizePoints(credits.burn_by_day, "spent"),
    credits_balance: toNumber(credits.balance),
    total_cost_usd: toNumber(totals.total_cost_usd),
    credits_burned: toNumber(credits.spent),
    render_time: normalizeRenderTime(data.render_time),
    by_layout: normalizeBreakdown(data.by_layout),
    by_language: normalizeBreakdown(data.by_language),
    by_variants: normalizeBreakdown(data.by_variants),
    top_hooks: normalizeNamedBreakdown(topContent.hooks),
    trend_funnel: normalizeTrendFunnel(data.trend_funnel),
    forecast_trace: normalizeForecastTrace(data.forecast_trace),
  };
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

/** POST /me/presets */
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
// Brand Voice — voice cloning (POST /voices/clone, GET /voices/mine, DELETE)
// ---------------------------------------------------------------------------

/**
 * POST /voices/clone — turn a previously uploaded voice sample into a private
 * ElevenLabs Instant Voice Clone. `body.consent` MUST be true (the backend
 * rejects a missing/false attestation with 400 before any provider work).
 * Returns the new voice with its narrator selector under `voice_id`
 * (`"elevenlabs:<provider_voice_id>"`).
 */
export function cloneVoice(
  body: CloneVoiceRequest,
  options?: RequestOptions,
): Promise<UserVoice> {
  return request<UserVoice>("/voices/clone", {
    method: "POST",
    body,
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
 * DELETE /voices/mine/{id} — delete one of the caller's cloned voices. `id` is
 * the internal row id (`UserVoice.id`), NOT the `elevenlabs:` selector.
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
// SPARK — AI Idea Engine (POST /ideas/generate, GET/POST/DELETE /me/ideas)
// ---------------------------------------------------------------------------

/**
 * POST /ideas/generate — turn an app/niche description into N ready-to-shoot
 * viral UGC concepts. This spends LLM tokens and is rate-limited per caller.
 * The backend may return the list directly as `data` or wrapped as
 * `{ ideas: [...] }`; both shapes are normalized to an `Idea[]` here.
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

/**
 * POST /me/ideas — persist one generated concept for the caller. `idea` is the
 * whole concept object (typically one item from {@link generateIdeas}); the
 * backend denormalises `title`/`hook` out of it for list rendering. Returns the
 * new saved-idea `{ id }`.
 */
export function saveIdea(
  idea: Idea,
  options?: RequestOptions,
): Promise<SaveIdeaResult> {
  return request<SaveIdeaResult>("/me/ideas", {
    method: "POST",
    body: { idea },
    options,
  });
}

/**
 * GET /me/ideas — the caller's saved concepts (newest first). The backend may
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

/** DELETE /me/ideas/{id} — delete one of the caller's saved ideas. */
export function deleteSavedIdea(
  id: string,
  options?: RequestOptions,
): Promise<IdeaDeleteResult> {
  return request<IdeaDeleteResult>(`/me/ideas/${encodeURIComponent(id)}`, {
    method: "DELETE",
    options,
  });
}

// ---------------------------------------------------------------------------
// ReelForge Template Marketplace
// (GET/DELETE /marketplace[/{id}], POST /marketplace/publish, /{id}/clone,
//  /{id}/rate — see app/controllers/v1/marketplace.py)
//
// Public content but still authed like every other v1 route. Browse filters
// (`query`/`tag`/`language`/`sort`) and paging (`limit` clamped 1..100,
// `offset` >= 0) are normalized here and re-clamped server-side, so an untrusted
// page request can never trigger an unbounded scan. Publish is owner-scoped and
// snapshots an IMMUTABLE copy; clone/rate are allowed for any authed user.
// ---------------------------------------------------------------------------

/**
 * GET /marketplace — published listings matching the filters, sorted +
 * paginated. `sort` is one of `top` | `new` | `clones`. The backend may return
 * the list directly as `data` or wrapped as `{ items: [...] }`; both shapes are
 * normalized to a `MarketplaceTemplate[]` here.
 */
export async function browseMarketplace(
  options?: RequestOptions & MarketplaceBrowseParams,
): Promise<MarketplaceTemplate[]> {
  const { query, tag, language, sort, limit, offset, ...reqOptions } =
    options ?? {};

  const params: string[] = [];
  const push = (key: string, value: string): void => {
    const trimmed = value.trim();
    if (trimmed) params.push(`${key}=${encodeURIComponent(trimmed)}`);
  };
  if (typeof query === "string") push("query", query);
  if (typeof tag === "string") push("tag", tag);
  if (typeof language === "string") push("language", language);
  if (typeof sort === "string") push("sort", sort);
  if (typeof limit === "number" && Number.isFinite(limit)) {
    const clamped = Math.max(
      1,
      Math.min(MAX_MARKETPLACE_LIMIT, Math.trunc(limit)),
    );
    params.push(`limit=${clamped}`);
  }
  if (typeof offset === "number" && Number.isFinite(offset)) {
    params.push(`offset=${Math.max(0, Math.trunc(offset))}`);
  }
  const qs = params.length > 0 ? `?${params.join("&")}` : "";

  const data = await request<MarketplaceTemplate[] | { items?: MarketplaceTemplate[] }>(
    `/marketplace${qs}`,
    { options: reqOptions },
  );
  if (Array.isArray(data)) return data;
  return data?.items ?? [];
}

/** GET /marketplace/{id} — one published listing (404 unknown/unpublished). */
export function getMarketplaceTemplate(
  id: string,
  options?: RequestOptions,
): Promise<MarketplaceTemplate> {
  return request<MarketplaceTemplate>(
    `/marketplace/${encodeURIComponent(id)}`,
    { options },
  );
}

/**
 * POST /marketplace/publish — publish an IMMUTABLE snapshot of a template to the
 * public marketplace (owner-scoped). Either reference a private template the
 * caller owns via `body.template_id`, or pass the snapshot inline; a resolved
 * `title` is required. Returns the new public listing.
 */
export function publishMarketplaceTemplate(
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
 * private templates (bumps `clone_count`). Allowed for any authed user. Returns
 * the new private template `{ id, name, source_marketplace_id }`.
 */
export function cloneMarketplaceTemplate(
  id: string,
  options?: RequestOptions,
): Promise<ClonedTemplate> {
  return request<ClonedTemplate>(
    `/marketplace/${encodeURIComponent(id)}/clone`,
    { method: "POST", options },
  );
}

/**
 * POST /marketplace/{id}/rate — rate a listing 1..5. Exactly one rating exists
 * per (user, template): re-rating UPSERTS rather than adding a duplicate row.
 * `stars` outside [1, 5] is a clean 400. Returns the listing with its refreshed
 * `rating_avg` / `rating_count`.
 */
export function rateMarketplaceTemplate(
  id: string,
  stars: number,
  options?: RequestOptions,
): Promise<MarketplaceTemplate> {
  return request<MarketplaceTemplate>(
    `/marketplace/${encodeURIComponent(id)}/rate`,
    { method: "POST", body: { stars: Math.trunc(stars) }, options },
  );
}

/**
 * DELETE /marketplace/{id} — author-only soft unpublish. A non-author id yields
 * a clean 404 and the listing stays published.
 */
export function unpublishMarketplaceTemplate(
  id: string,
  options?: RequestOptions,
): Promise<MarketplaceUnpublishResult> {
  return request<MarketplaceUnpublishResult>(
    `/marketplace/${encodeURIComponent(id)}`,
    { method: "DELETE", options },
  );
}

/**
 * GET /marketplace/{id}/lineage — the remix-tree lineage of a listing: its
 * `ancestors` (immediate parent → root) and direct published `children`
 * (newest-first), each a safe public {@link MarketplaceTemplate}. Authed like the
 * rest of marketplace. An unknown id yields an empty tree
 * (`{ ancestors: [], children: [] }`); the shape is normalized defensively so a
 * partial payload still renders instead of throwing.
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
// In-app notifications (bell + unread badge + notification center)
//
// The in-app counterpart to the external webhook. All reads/mutations are
// strictly caller-scoped by the backend (filtered on the authenticated user).
// ---------------------------------------------------------------------------

/**
 * GET /me/notifications — the caller's notifications (newest first) plus the
 * live total unread count for the bell badge. `unreadOnly` restricts the page
 * to unread rows; `limit` bounds the page (the backend clamps it). The shape is
 * normalized so a missing/blank payload degrades to an empty, zero-count list.
 */
export async function listNotifications(
  options?: RequestOptions & ListNotificationsQuery,
): Promise<NotificationsResult> {
  const { unreadOnly, limit, ...reqOptions } = options ?? {};

  const query: string[] = [];
  if (unreadOnly) query.push("unread_only=true");
  if (typeof limit === "number" && Number.isFinite(limit)) {
    query.push(`limit=${encodeURIComponent(String(Math.trunc(limit)))}`);
  }
  const qs = query.length > 0 ? `?${query.join("&")}` : "";

  const data = await request<Partial<NotificationsResult>>(
    `/me/notifications${qs}`,
    { options: reqOptions },
  );
  return {
    notifications: Array.isArray(data?.notifications) ? data.notifications : [],
    unread_count:
      typeof data?.unread_count === "number" ? data.unread_count : 0,
  };
}

/**
 * GET /me/notifications/unread_count — count-only endpoint, cheap enough to poll
 * on a short interval to keep the bell badge fresh. Returns `0` on a blank body.
 */
export async function getUnreadCount(options?: RequestOptions): Promise<number> {
  const data = await request<{ unread_count?: number }>(
    "/me/notifications/unread_count",
    { options },
  );
  return typeof data?.unread_count === "number" ? data.unread_count : 0;
}

/**
 * POST /me/notifications/{id}/read — flip one notification to read. Ownership is
 * enforced server-side (a missing/foreign id yields 404 → {@link ApiError}).
 * Marking an already-read notification is an idempotent success.
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
 * POST /me/notifications/read_all — mark every one of the caller's unread
 * notifications read. Returns how many rows were flipped; `unread_count` is `0`.
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
// Multi-language dubbing (GET /dub/languages, POST /jobs/{id}/dub)
// ---------------------------------------------------------------------------

/**
 * GET /dub/languages — the target languages a finished reel can be dubbed into
 * (bundled caption fonts cover exactly this set). The backend may return the
 * list directly as `data` or wrapped as `{ languages: [...] }`; both shapes are
 * normalized to a `DubLanguage[]` here.
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
 * POST /jobs/{id}/dub — from finished source job `id`, translate its SCRIPT into
 * each of `languages` and run the normal pipeline per language, reusing the
 * source's screen recording, avatar, voice, layout and caption style. The N
 * dubbed jobs share one `batch_id` (see {@link DubJobResult}) so they can be
 * watched together in the batch-review UI.
 */
export function dubJob(
  id: string,
  languages: readonly string[],
  options?: RequestOptions,
): Promise<DubJobResult> {
  const body: DubJobRequest = { languages: [...languages] };
  return request<DubJobResult>(`/jobs/${encodeURIComponent(id)}/dub`, {
    method: "POST",
    body,
    options,
  });
}

// ---------------------------------------------------------------------------
// Scheduled Publishing (POST /jobs/{id}/schedule, GET/DELETE /me/scheduled)
//
// Queue a *finished* reel to auto-publish to social platforms at a future UTC
// time. A background Celery-beat due-runner does the actual publishing; the
// client only creates, lists and cancels schedules. Strictly owner-scoped.
// ---------------------------------------------------------------------------

/**
 * POST /jobs/{id}/schedule — queue a completed, owned reel to auto-publish to
 * `body.platforms` at `body.scheduled_at` (an ISO-8601 UTC time that MUST be in
 * the future). The backend rejects a not-complete job (409), an unknown/foreign
 * job (404), and empty/invalid platforms or a past/unparseable time (400).
 * Returns the created `pending` schedule.
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
 * GET /me/scheduled — the caller's scheduled publishes (soonest-due first),
 * optionally filtered by `status` (e.g. "pending"). Strictly owner-scoped. The
 * backend may return the list directly as `data` or wrapped as
 * `{ scheduled: [...] }`; both shapes are normalized to a `ScheduledPublish[]`.
 */
export async function listScheduled(
  options?: RequestOptions & ListScheduledQuery,
): Promise<ScheduledPublish[]> {
  const { status, ...reqOptions } = options ?? {};

  const query: string[] = [];
  const trimmed = (status ?? "").trim();
  if (trimmed) query.push(`status=${encodeURIComponent(trimmed)}`);
  const qs = query.length > 0 ? `?${query.join("&")}` : "";

  const data = await request<
    ScheduledPublish[] | { scheduled?: ScheduledPublish[] }
  >(`/me/scheduled${qs}`, { options: reqOptions });
  if (Array.isArray(data)) return data;
  return data?.scheduled ?? [];
}

/**
 * DELETE /me/scheduled/{id} — cancel one of the caller's still-`pending`
 * schedules. `id` is the `ScheduledPublish.id` row id. The backend yields 404
 * for an unknown/foreign id and 409 when the schedule is no longer pending
 * (already publishing / published / failed / canceled).
 */
export function cancelScheduled(
  id: string,
  options?: RequestOptions,
): Promise<CancelScheduledResult> {
  return request<CancelScheduledResult>(
    `/me/scheduled/${encodeURIComponent(id)}`,
    { method: "DELETE", options },
  );
}

// ---------------------------------------------------------------------------
// Cover / Thumbnail generator (GET /catalog/cover-styles, POST /jobs/{id}/cover)
//
// Generate a scroll-stopping cover image for a job: its poster frame with the
// HOOK overlaid as a bold headline in a chosen style, rendered server-side with
// Pillow (1080x1920 JPG) and stored as Job.cover_key. Regenerable.
// ---------------------------------------------------------------------------

/**
 * GET /catalog/cover-styles — the selectable cover/thumbnail styles. The backend
 * may return the list directly as `data` or wrapped as `{ styles: [...] }`; both
 * shapes are normalized to a `CoverStyle[]` here.
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
 * POST /jobs/{id}/cover — render a cover image for job `id`: the job's poster
 * frame (or a gradient fallback) with `body.headline` overlaid as a bold
 * headline in `body.style`. Both fields are optional (omitted `headline` falls
 * back to the job's HOOK; omitted `style` uses the default). Calling again
 * regenerates the cover with the new headline/style. Returns the stored
 * `cover_key` plus a presigned `cover_url` for immediate preview.
 */
export function generateCover(
  jobId: string,
  body: GenerateCoverRequest,
  options?: RequestOptions,
): Promise<CoverResult> {
  return request<CoverResult>(`/jobs/${encodeURIComponent(jobId)}/cover`, {
    method: "POST",
    body,
    options,
  });
}

// ---------------------------------------------------------------------------
// Team Workspaces (POST/GET /workspaces, GET/POST/PATCH/DELETE
// /workspaces/{id}/members, POST /workspaces/{id}/leave)
//
// An additive membership layer: create a workspace, invite existing users by
// email with a role, and manage membership. Every mutation is authorized
// server-side by the caller's role; the client mirrors `Workspace.my_role`
// purely to gate UI affordances. This does NOT touch per-user job/credit
// ownership. No secrets here — auth flows through the shared `x-api-key` header.
// ---------------------------------------------------------------------------

/**
 * POST /workspaces — create a new team workspace owned by the caller. Returns
 * the created workspace with the caller's `my_role` set to `"owner"`.
 */
export function createWorkspace(
  body: CreateWorkspaceRequest,
  options?: RequestOptions,
): Promise<Workspace> {
  return request<Workspace>("/workspaces", { method: "POST", body, options });
}

/**
 * GET /workspaces — the workspaces the caller belongs to (any role). The
 * backend may return the list directly as `data` or wrapped as
 * `{ workspaces: [...] }`; both shapes are normalized to a `Workspace[]` here.
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
 * `{ members: [...] }`; both shapes are normalized to a `WorkspaceMember[]`.
 */
export async function listMembers(
  workspaceId: string,
  options?: RequestOptions,
): Promise<WorkspaceMember[]> {
  const data = await request<
    WorkspaceMember[] | { members?: WorkspaceMember[] }
  >(`/workspaces/${encodeURIComponent(workspaceId)}/members`, { options });
  if (Array.isArray(data)) return data;
  return data?.members ?? [];
}

/**
 * POST /workspaces/{id}/members — invite an existing user (by email) into the
 * workspace with `role`. Requires the caller to be an owner/admin (403
 * otherwise); an unknown email yields 404 and a duplicate membership 409.
 * Returns the created membership row.
 */
export function inviteMember(
  workspaceId: string,
  body: InviteMemberRequest,
  options?: RequestOptions,
): Promise<WorkspaceMember> {
  return request<WorkspaceMember>(
    `/workspaces/${encodeURIComponent(workspaceId)}/members`,
    { method: "POST", body, options },
  );
}

/**
 * PATCH /workspaces/{id}/members/{memberId} — change a member's role. Requires
 * the caller to be an owner/admin. `memberId` is the {@link WorkspaceMember.id}
 * membership row id (NOT the user id). Returns the updated membership row.
 */
export function setMemberRole(
  workspaceId: string,
  memberId: string,
  role: WorkspaceRole,
  options?: RequestOptions,
): Promise<WorkspaceMember> {
  const body: SetMemberRoleRequest = { role };
  return request<WorkspaceMember>(
    `/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(
      memberId,
    )}`,
    { method: "PATCH", body, options },
  );
}

/**
 * DELETE /workspaces/{id}/members/{memberId} — remove a member from the
 * workspace. Requires the caller to be an owner/admin. `memberId` is the
 * membership row id. To remove yourself, use {@link leaveWorkspace} instead.
 */
export function removeMember(
  workspaceId: string,
  memberId: string,
  options?: RequestOptions,
): Promise<RemoveMemberResult> {
  return request<RemoveMemberResult>(
    `/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(
      memberId,
    )}`,
    { method: "DELETE", options },
  );
}

/**
 * POST /workspaces/{id}/leave — the caller leaves the workspace. The backend
 * rejects the sole owner leaving (409) so a workspace is never orphaned.
 */
export function leaveWorkspace(
  workspaceId: string,
  options?: RequestOptions,
): Promise<LeaveWorkspaceResult> {
  return request<LeaveWorkspaceResult>(
    `/workspaces/${encodeURIComponent(workspaceId)}/leave`,
    { method: "POST", options },
  );
}

// ---------------------------------------------------------------------------
// Shared Workspace Credits (GET /workspaces/{id}/credits,
// POST /workspaces/{id}/credits/grant)
//
// A workspace has a SHARED credit pool that member-created jobs can be charged
// to (see `workspace_id` on {@link JobCreateRequest}). Reading the balance only
// needs membership; granting (topping up) is owner/admin-only and never touches
// any personal balance. Auth flows through the shared `x-api-key` header.
// ---------------------------------------------------------------------------

/**
 * GET /workspaces/{id}/credits — the workspace's SHARED credit pool balance.
 * The caller must be a member (a non-member yields 403; an unknown workspace
 * 404). Returns `{ balance }`.
 */
export function getWorkspaceCredits(
  workspaceId: string,
  options?: RequestOptions,
): Promise<WorkspaceCredits> {
  return request<WorkspaceCredits>(
    `/workspaces/${encodeURIComponent(workspaceId)}/credits`,
    { options },
  );
}

/**
 * POST /workspaces/{id}/credits/grant — add credits to the workspace's SHARED
 * pool. Owner/admin only (a plain member yields 403); a non-positive `amount`
 * yields 400. Returns the updated `{ balance }`. This is the manual/dev top-up
 * path — it never debits or credits any personal balance.
 */
export function grantWorkspaceCredits(
  workspaceId: string,
  body: GrantWorkspaceCreditsRequest,
  options?: RequestOptions,
): Promise<WorkspaceCredits> {
  return request<WorkspaceCredits>(
    `/workspaces/${encodeURIComponent(workspaceId)}/credits/grant`,
    { method: "POST", body, options },
  );
}

// ---------------------------------------------------------------------------
// ENTERPRISE — Access & Governance (Epic 1): RBAC, audit trail, platform-admin
//
// The Enterprise access layer, gated by the pycasbin enforcer server-side. Every
// workspace-scoped call verifies the caller is a member with a sufficient role;
// TENANT ISOLATION is the #1 invariant. The audit trail is APPEND-ONLY.
// Platform-admin is a SEPARATE, `is_staff`-gated cross-tenant surface.
// ---------------------------------------------------------------------------

/**
 * GET /me/workspaces/{id}/members — the workspace roster with each member's
 * Enterprise role. The caller must be a member (any role): a non-member gets a
 * 403 and an unknown workspace a 404. The backend returns the list under `data`;
 * a `{ members: [...] }` wrapper is also tolerated. Strictly tenant-scoped.
 */
export async function listWorkspaceMembers(
  workspaceId: string,
  options?: RequestOptions,
): Promise<WorkspaceMember[]> {
  const data = await request<
    WorkspaceMember[] | { members?: WorkspaceMember[] }
  >(`/me/workspaces/${encodeURIComponent(workspaceId)}/members`, { options });
  if (Array.isArray(data)) return data;
  return data?.members ?? [];
}

/**
 * PATCH /me/workspaces/{id}/members/{userId}/role — change a member's Enterprise
 * role. Requires the caller to hold `members.manage` (admin/owner). Server-side
 * guardrails: an unknown role is a 400, a non-member target a 404, granting a
 * role ABOVE the caller's own a 403, and demoting the LAST owner a 409. On
 * success an append-only `members.role_changed` audit row is written. Note the
 * path takes the target's USER id (not the membership row id). Returns the
 * updated membership row.
 */
export function updateMemberRole(
  workspaceId: string,
  userId: string,
  role: WorkspaceRole,
  options?: RequestOptions,
): Promise<WorkspaceMember> {
  return request<WorkspaceMember>(
    `/me/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(
      userId,
    )}/role`,
    { method: "PATCH", body: { role }, options },
  );
}

/**
 * GET /me/permissions?workspace_id= — the caller's EFFECTIVE permissions in a
 * workspace, from the enforcer. A blank `workspaceId` is a 400. A non-member
 * yields `{ role: null, permissions: [] }` (no tenant leak). The possibly-partial
 * envelope is normalized so `permissions` is always an array and `role` is `null`
 * when absent.
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
 * non-member/under-privileged caller gets a 403, an unknown workspace a 404.
 * `params.limit` is clamped to `[1, 100]` and `params.offset` floored at 0.
 * Strictly tenant-scoped. The backend returns the list under `data`; a
 * `{ audit: [...] }` wrapper is also tolerated.
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

/** Shared page-window query builder for the platform-admin list endpoints. */
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
 * PLATFORM-ADMIN ONLY (403 for non-staff; a workspace owner is NOT staff). The
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
 * PLATFORM-ADMIN ONLY. The backend returns the list under `data`; a
 * `{ workspaces: [...] }` wrapper is tolerated.
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
 * ONLY. The backend returns the list under `data`; a `{ jobs: [...] }` wrapper is
 * tolerated.
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
 * `userId`. PLATFORM-ADMIN ONLY (403 for non-staff; unknown target 400). On
 * success an append-only `admin.impersonated` audit row is written. Returns the
 * {@link Impersonation} grant (never persist the token).
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
// Brand Watermark (GET /me/brand, PUT /me/brand)
//
// A creator uploads a transparent PNG logo (via the existing presign flow) that
// the pure-FFmpeg compose stage overlays on their reels at a chosen corner +
// opacity. These two endpoints read and update the caller's per-user brand
// singleton; the logo itself is uploaded with {@link presignAndUpload} and its
// returned key is saved here as `logo_key`.
// ---------------------------------------------------------------------------

/**
 * GET /me/brand — the caller's brand watermark settings (the backend defaults
 * when the creator has never configured one). When a `logo_key` is set the
 * payload also carries a short-lived presigned `logo_url` for previewing it.
 */
export function getBrand(options?: RequestOptions): Promise<Brand> {
  return request<Brand>("/me/brand", { options });
}

/**
 * PUT /me/brand — partial update of the caller's brand watermark settings. Only
 * the supplied fields change (omitted fields are left untouched). `position`
 * must be a known corner and `opacity` in [0.0, 1.0] (both 400 otherwise); a
 * non-empty `logo_key` must reference an upload the caller owns (403 otherwise)
 * while `logo_key: ""` clears the logo. Returns the updated settings.
 */
export function updateBrand(
  body: BrandUpdate,
  options?: RequestOptions,
): Promise<Brand> {
  return request<Brand>("/me/brand", { method: "PUT", body, options });
}

// ---------------------------------------------------------------------------
// AI B-roll cutaways (POST /jobs/{id}/broll/suggest)
//
// OPTIONAL creative overlay: repurpose MPT's vendored stock-footage path
// (Pexels/Pixabay in app/services/material.py, disabled for the main pipeline)
// to suggest short relevant clips for a reel. The backend derives keywords from
// the job's subject/script (app/services/llm.py::generate_terms), downloads a
// few clips (download_videos + material_cache), and returns them as suggestions.
// The creator picks one to splice as a brief MUTED intro/outro via
// `broll_intro_key` / `broll_outro_key` on the next create/rerun. This endpoint
// only SUGGESTS — it never mutates the job.
// ---------------------------------------------------------------------------

/**
 * POST /jobs/{id}/broll/suggest — suggest short stock B-roll clips relevant to
 * job `id` (keywords derived from its subject/script). `body.source` picks the
 * stock provider (omit to let the backend choose) and `body.amount` bounds how
 * many clips are returned (backend clamps to a sane range). Returns the
 * suggestions; the backend may return the list directly as `data` or wrapped as
 * `{ clips: [...] }`, both normalized to a `BrollClip[]` here (a blank payload
 * degrades to an empty list). Spends stock-provider quota, so call it on demand.
 */
export async function suggestBroll(
  jobId: string,
  body: SuggestBrollRequest = {},
  options?: RequestOptions,
): Promise<BrollClip[]> {
  const data = await request<BrollClip[] | { clips?: BrollClip[] }>(
    `/jobs/${encodeURIComponent(jobId)}/broll/suggest`,
    { method: "POST", body, options },
  );
  if (Array.isArray(data)) return data;
  return data?.clips ?? [];
}

/** Canonical standalone AI B-roll endpoints. */
export function getPilotCapabilities(options?: RequestOptions): Promise<PilotCapabilities> {
  return request<PilotCapabilities>("/pilot/capabilities", { options });
}

/**
 * GET /launch/status — the non-sensitive, fail-closed launch capability
 * document (mode + per-feature gates for signup / checkout / publishing). This
 * is what tells a gated client WHY paid checkout or direct publishing is
 * blocked in the current launch phase; the same gates are enforced server-side
 * (HTTP 403) regardless of what the client renders. Contains no secrets.
 */
export function getLaunchStatus(options?: RequestOptions): Promise<LaunchStatus> {
  return request<LaunchStatus>("/launch/status", { options });
}

export function generateBroll(body: BrollGenerateRequest, options?: RequestOptions): Promise<BrollGeneration> {
  return request<BrollGeneration>("/generation/broll/generate", { method: "POST", body, options });
}

export function getBrollGeneration(id: string, options?: RequestOptions): Promise<BrollGeneration> {
  return request<BrollGeneration>(`/generation/broll/generations/${encodeURIComponent(id)}`, { options });
}

export async function listBrollGenerations(options?: RequestOptions): Promise<BrollGeneration[]> {
  const data = await request<BrollGeneration[] | { generations?: BrollGeneration[] }>("/generation/broll/generations", { options });
  return Array.isArray(data) ? data : (data?.generations ?? []);
}

export async function listBrollPresets(options?: RequestOptions): Promise<BrollPreset[]> {
  const data = await request<BrollPreset[] | { presets?: BrollPreset[] }>("/generation/broll/presets", { options });
  return Array.isArray(data) ? data : (data?.presets ?? []);
}

// ---------------------------------------------------------------------------
// AI Social Caption & Hashtags (GET /catalog/social-platforms,
// POST /jobs/{id}/social)
//
// For a finished reel, generate an optimized post title + caption + hashtags
// tailored to a target platform. Built on the vendored MPT LLM helper
// (app/services/llm.py::generate_social_metadata) — the subject/script the copy
// is built from come from the job's own persisted data, never from client
// input. Creators copy the result when posting.
// ---------------------------------------------------------------------------

/**
 * GET /catalog/social-platforms — the platforms the AI social-caption endpoint
 * can tailor copy for (`tiktok` / `instagram` / `youtube_shorts`). The backend
 * may return the list directly as `data` or wrapped as `{ platforms: [...] }`,
 * both normalized to a `SocialPlatform[]` here; a degraded/empty catalog
 * returns an empty list.
 */
export async function listSocialPlatforms(
  options?: RequestOptions,
): Promise<SocialPlatform[]> {
  const data = await request<SocialPlatform[] | { platforms?: SocialPlatform[] }>(
    "/catalog/social-platforms",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.platforms ?? [];
}

/**
 * POST /jobs/{id}/social — generate an optimized post `title` + `caption` +
 * `hashtags` for finished reel `jobId`, tailored to `body.platform`. An
 * optional `body.language` overrides the job's configured caption language.
 * The copy is derived server-side from the job's own subject/script. Spends LLM
 * tokens (per-user rate-limited by the backend), so call it on demand.
 */
export function generateSocial(
  jobId: string,
  body: SocialRequest,
  options?: RequestOptions,
): Promise<SocialMeta> {
  return request<SocialMeta>(`/jobs/${encodeURIComponent(jobId)}/social`, {
    method: "POST",
    body,
    options,
  });
}

/**
 * POST /social-metadata — generate a ready-to-paste `title` + `caption` +
 * `hashtags` from a free-form `video_subject` (and optional `video_script`),
 * tailored to `body.platform`. Unlike {@link generateSocial}, this does NOT
 * require a finished reel: it's the "draft copy" path for planning a post
 * before rendering. Spends LLM tokens (per-user rate-limited server-side), so
 * call it on demand. Returns the same {@link SocialMeta} shape.
 */
export function generateSocialMetadata(
  body: SocialMetadataRequest,
  options?: RequestOptions,
): Promise<SocialMeta> {
  return request<SocialMeta>("/social-metadata", {
    method: "POST",
    body,
    options,
  });
}

// ---------------------------------------------------------------------------
// Public API Keys (POST/GET/DELETE /me/api-keys)
//
// Power users mint personal API keys for programmatic access to the /api/v1
// REST API. A minted key is used as the `x-api-key` header (the same header the
// app already sends) and resolved back to its owning user server-side. SECURITY:
// the raw key is returned exactly ONCE at creation (never again), and only its
// SHA-256 hash is stored — so `listApiKeys` never carries the raw secret.
// Strictly owner-scoped by the backend; auth flows through the shared token.
// ---------------------------------------------------------------------------

/**
 * POST /me/api-keys — mint a personal API key labelled `name`. Returns the FULL
 * raw secret under {@link ApiKeyCreated.key}, revealed EXACTLY ONCE and
 * unrecoverable afterwards (the server keeps only its hash) — show it, let the
 * user copy it, and never persist it. The backend rejects a blank name (400) and
 * an over-cap number of active keys (409).
 */
export function createApiKey(
  name: string,
  options?: RequestOptions,
): Promise<ApiKeyCreated> {
  return request<ApiKeyCreated>("/me/api-keys", {
    method: "POST",
    body: { name },
    options,
  });
}

/**
 * GET /me/api-keys — the caller's API keys (newest first), active and revoked.
 * NEVER includes the raw key or hash — only the non-secret `prefix` and
 * lifecycle metadata. The backend may return the list directly as `data` or
 * wrapped as `{ keys: [...] }`; both shapes are normalized to an `ApiKey[]`.
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
 * DELETE /me/api-keys/{id} — soft-revoke one of the caller's keys so it can no
 * longer authenticate. Ownership is enforced server-side: a foreign/unknown id
 * is indistinguishable from a missing one (404 → {@link ApiError}). `id` is the
 * {@link ApiKey.id} row id.
 */
export function revokeApiKey(
  id: string,
  options?: RequestOptions,
): Promise<ApiKeyRevokeResult> {
  return request<ApiKeyRevokeResult>(
    `/me/api-keys/${encodeURIComponent(id)}`,
    { method: "DELETE", options },
  );
}

/**
 * GET /me/api-keys/usage — current-month usage + limits for each of the caller's
 * keys (POWER-USER TIER quotas). Caller-scoped and token-free (never the raw key
 * or hash). The backend may return the list directly as `data` or wrapped as
 * `{ usage: [...] }`; both shapes are normalized to an `ApiKeyUsage[]` here (a
 * caller with no keys degrades to an empty list).
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
// Social Connections — OAuth connect + direct publish
// (GET /me/connections, GET /connections/{provider}/authorize,
//  GET /connections/{provider}/callback, DELETE /me/connections/{provider},
//  POST /jobs/{id}/publish/{provider} — see app/controllers/v1/connections.py)
//
// A creator connects a social account via OAuth then publishes a finished, owned
// job straight to it. SECURITY: no response here EVER carries an access/refresh
// token — only the provider, provider-side account id, status, scopes and
// timestamps. Every read/mutation is strictly owner-scoped by the backend.
// ---------------------------------------------------------------------------

/**
 * GET /me/connections — the caller's connected social accounts (newest first),
 * token-free. The backend may return the list directly as `data` or wrapped as
 * `{ connections: [...] }`; both shapes are normalized to a `Connection[]` here
 * (a caller with no connections degrades to an empty list).
 */
export async function getConnections(
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
 * GET /connections/{provider}/authorize — mint an opaque single-use CSRF `state`
 * and return the provider `authorize_url` to open in the browser (it already
 * embeds `state`). An optional `scopes` overrides the default requested scopes.
 * The backend yields 404 for an unknown provider and 503 when the provider's
 * OAuth client id is not configured. Pass the returned `code` + `state` (from
 * the provider's redirect to the callback) to {@link completeConnect}.
 */
export function startConnect(
  provider: SocialProvider | string,
  options?: RequestOptions & { scopes?: string },
): Promise<AuthorizeInfo> {
  const { scopes, ...reqOptions } = options ?? {};
  const trimmed = (scopes ?? "").trim();
  const qs = trimmed ? `?scopes=${encodeURIComponent(trimmed)}` : "";
  return request<AuthorizeInfo>(
    `/connections/${encodeURIComponent(provider)}/authorize${qs}`,
    { options: reqOptions },
  );
}

/**
 * GET /connections/{provider}/callback — complete the OAuth handshake: the
 * backend validates `state` (single-use; an unknown/replayed state is rejected
 * BEFORE any token exchange), exchanges `code` for tokens, encrypts + stores
 * them, and returns the refreshed token-free connection list. The backend may
 * return the list directly as `data` or wrapped as `{ connections: [...] }`;
 * both shapes are normalized to a `Connection[]` here.
 */
export async function completeConnect(
  provider: SocialProvider | string,
  code: string,
  state: string,
  options?: RequestOptions,
): Promise<Connection[]> {
  const qs = `?code=${encodeURIComponent(code)}&state=${encodeURIComponent(
    state,
  )}`;
  const data = await request<Connection[] | { connections?: Connection[] }>(
    `/connections/${encodeURIComponent(provider)}/callback${qs}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.connections ?? [];
}

/**
 * DELETE /me/connections/{provider} — disconnect one of the caller's connected
 * providers. Owner-scoped: a provider the caller has not connected yields a
 * clean 404 (indistinguishable from another user's connection). Returns
 * `{ disconnected, provider }`.
 */
export function disconnect(
  provider: SocialProvider | string,
  options?: RequestOptions,
): Promise<DisconnectResult> {
  return request<DisconnectResult>(
    `/me/connections/${encodeURIComponent(provider)}`,
    { method: "DELETE", options },
  );
}

/**
 * POST /jobs/{jobId}/publish/{provider} — publish the caller's OWN completed job
 * straight to a connected provider, with an optional `caption`. The backend
 * yields 404 for an unknown job, 403 for a foreign job, and 409 when the job is
 * not complete or the provider is not connected. The decrypted token is used
 * only for the outbound upload and is never returned. Returns the token-free
 * {@link PublishResult}.
 */
export function publishJobTo(
  jobId: string,
  provider: SocialProvider | string,
  caption?: string,
  options?: RequestOptions,
): Promise<PublishResult> {
  const trimmed = (caption ?? "").trim();
  const qs = trimmed ? `?caption=${encodeURIComponent(trimmed)}` : "";
  return request<PublishResult>(
    `/jobs/${encodeURIComponent(jobId)}/publish/${encodeURIComponent(
      provider,
    )}${qs}`,
    { method: "POST", options },
  );
}

// ---------------------------------------------------------------------------
// Upload flow helper: presign -> PUT file with returned headers -> return key
// ---------------------------------------------------------------------------

/**
 * A local file picked from expo-image-picker or expo-document-picker,
 * normalized to the fields the upload flow needs. `size` may be filled in
 * from FileSystem when the picker doesn't supply it.
 */
export interface LocalFile {
  /** Local content:// or file:// URI of the picked recording. */
  uri: string;
  /** Original filename (used for the presign request and the R2 key ext). */
  name: string;
  /** MIME type, e.g. "video/mp4". */
  mimeType: string;
  /** Size in bytes. */
  size: number;
}

export interface UploadResult {
  /** R2 object key — use as `screen_recording_key` when creating a job. */
  key: string;
  /** Presigned GET URL for previewing the just-uploaded object. */
  get_url: string;
}

export async function registerUpload(
  key: string,
  kind: string,
  options?: RequestOptions,
): Promise<string> {
  const data = await request<{ key: string; asset_id: string }>(
    "/uploads/register",
    { method: "POST", body: { key, kind }, options },
  );
  return data.key;
}

/**
 * Presigns an upload for `file`, PUTs the bytes to the returned `upload_url`
 * echoing the signed `headers`, and returns the object key. `onProgress`
 * receives a 0..1 fraction throughout the PUT.
 *
 * Uses expo-file-system `uploadAsync` (BINARY_CONTENT) so large screen
 * recordings stream from disk instead of being buffered into a JS Blob.
 */
export async function presignAndUpload(
  file: LocalFile,
  options?: RequestOptions & { onProgress?: (fraction: number) => void },
): Promise<UploadResult> {
  const { onProgress, ...reqOptions } = options ?? {};

  const contentType = file.mimeType || "application/octet-stream";

  const presigned = await presign(
    {
      filename: file.name,
      content_type: contentType,
      size: file.size,
    },
    reqOptions,
  );

  onProgress?.(0);

  // Echo exactly the signed headers the backend returned. Fall back to the
  // file's content type if none were provided.
  const headers =
    presigned.headers && Object.keys(presigned.headers).length > 0
      ? presigned.headers
      : { "Content-Type": contentType };

  const task = FileSystem.createUploadTask(
    presigned.upload_url,
    file.uri,
    {
      httpMethod: "PUT",
      uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
      headers,
    },
    (progress) => {
      if (progress.totalBytesExpectedToSend > 0) {
        onProgress?.(
          progress.totalBytesSent / progress.totalBytesExpectedToSend,
        );
      }
    },
  );

  let result: FileSystem.FileSystemUploadResult | null | undefined;
  try {
    result = await task.uploadAsync();
  } catch (err) {
    throw new ApiError(
      `Failed to upload file to storage: ${
        err instanceof Error ? err.message : String(err)
      }`,
      0,
      err,
    );
  }

  if (!result || result.status < 200 || result.status >= 300) {
    throw new ApiError(
      `Storage rejected the upload (${result?.status ?? "no response"}).`,
      result?.status ?? 0,
      result?.body,
    );
  }

  await registerUpload(
    presigned.key,
    contentType.startsWith("image/")
      ? "image"
      : contentType.startsWith("video/")
        ? "video"
        : contentType.startsWith("audio/")
          ? "audio"
          : "upload",
    reqOptions,
  );
  onProgress?.(1);
  return { key: presigned.key, get_url: presigned.get_url };
}

// ---------------------------------------------------------------------------
// Hook Performance Loop (auth-gated; strictly caller-scoped)
// (POST/GET /jobs/{id}/performance, GET /me/performance,
//  GET /me/winning-hooks, GET /me/winning-templates)
//
// Creators self-report a posted reel's real-world outcome; the backend verifies
// job ownership before writing, validates + clamps every numeric input, and
// upserts one row per job. `limit` is clamped 1..100 here and re-clamped
// server-side so an untrusted page request can never trigger an unbounded scan.
// ---------------------------------------------------------------------------

/** Server + client cap on the number of rows returned by the /me lists. */
const MAX_PERFORMANCE_LIMIT = 100;

/** Clamp a caller-supplied `limit` to the safe 1..100 window, or omit it. */
function performanceLimitParam(limit: number | undefined): string {
  if (typeof limit !== "number" || !Number.isFinite(limit)) return "";
  const clamped = Math.max(
    1,
    Math.min(MAX_PERFORMANCE_LIMIT, Math.trunc(limit)),
  );
  return `?limit=${clamped}`;
}

/**
 * POST /jobs/{job_id}/performance — log or update (idempotent upsert) the
 * caller's OWN job metrics. `403` for a foreign job, `404` for an unknown one,
 * `400` on a negative count or `retention_pct` outside [0,100]. Returns the
 * stored row.
 */
export function logJobPerformance(
  jobId: string,
  body: LogPerformanceRequest,
  options?: RequestOptions,
): Promise<JobPerformance> {
  return request<JobPerformance>(
    `/jobs/${encodeURIComponent(jobId)}/performance`,
    { method: "POST", body, options },
  );
}

/**
 * GET /jobs/{job_id}/performance — the caller's logged metrics for one job
 * (`404` for a missing or foreign id).
 */
export function getJobPerformance(
  jobId: string,
  options?: RequestOptions,
): Promise<JobPerformance> {
  return request<JobPerformance>(
    `/jobs/${encodeURIComponent(jobId)}/performance`,
    { options },
  );
}

/**
 * GET /me/performance — the caller's logged reels, newest first. `limit` is
 * clamped 1..100; `offset` (>= 0) pages. The backend may return the list
 * directly as `data` or wrapped as `{ items: [...] }`; both are normalized.
 */
export async function listMyPerformance(
  opts?: RequestOptions & { limit?: number; offset?: number },
): Promise<JobPerformance[]> {
  const { limit, offset, ...reqOptions } = opts ?? {};
  const params: string[] = [];
  if (typeof limit === "number" && Number.isFinite(limit)) {
    params.push(
      `limit=${Math.max(1, Math.min(MAX_PERFORMANCE_LIMIT, Math.trunc(limit)))}`,
    );
  }
  if (typeof offset === "number" && Number.isFinite(offset)) {
    params.push(`offset=${Math.max(0, Math.trunc(offset))}`);
  }
  const qs = params.length > 0 ? `?${params.join("&")}` : "";

  const data = await request<JobPerformance[] | { items?: JobPerformance[] }>(
    `/me/performance${qs}`,
    { options: reqOptions },
  );
  if (Array.isArray(data)) return data;
  return data?.items ?? [];
}

/**
 * GET /me/winning-hooks — the caller's top hooks by deterministic `win_score`
 * (`limit` clamped 1..100). Returns `[]` when the creator has no logged reels.
 */
export async function getWinningHooks(
  limit?: number,
  options?: RequestOptions,
): Promise<WinningHook[]> {
  const data = await request<WinningHook[] | { items?: WinningHook[] }>(
    `/me/winning-hooks${performanceLimitParam(limit)}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.items ?? [];
}

/**
 * GET /me/winning-templates — the caller's top templates by `win_score`
 * (`limit` clamped 1..100). Returns `[]` when the creator has no logged reels.
 */
export async function getWinningTemplates(
  limit?: number,
  options?: RequestOptions,
): Promise<WinningTemplate[]> {
  const data = await request<WinningTemplate[] | { items?: WinningTemplate[] }>(
    `/me/winning-templates${performanceLimitParam(limit)}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.items ?? [];
}

// ---------------------------------------------------------------------------
// Public Share Links (POST /jobs/{id}/share, DELETE /me/shares/{token},
// GET /public/r/{token})
//
// A creator mints an unguessable, REVOCABLE public link for one of their OWN
// reels. Create + revoke are owner-scoped by the backend (a foreign/unknown job
// is a clean 404; a foreign/unknown token is a harmless `{ revoked: false }`).
// The public view is UNAUTHENTICATED and returns only the SAFE {@link SharePublic}
// shape — never the clean result key, the owner, or any private financial.
// ---------------------------------------------------------------------------

/**
 * POST /jobs/{id}/share — create (or return the existing live) public share link
 * for the caller's OWN reel. Owner-scoped: a foreign/unknown job is a clean 404
 * ({@link ApiError}). Idempotent — one live link per job. Returns the
 * owner-facing {@link ShareLink} (with its unguessable `token` + built `url`).
 */
export function createShareLink(
  jobId: string,
  options?: RequestOptions,
): Promise<ShareLink> {
  return request<ShareLink>(`/jobs/${encodeURIComponent(jobId)}/share`, {
    method: "POST",
    options,
  });
}

/**
 * DELETE /me/shares/{token} — revoke one of the caller's OWN live share links so
 * its public page 404s. Owner-scoped: a foreign / unknown / already-revoked token
 * is a harmless `{ revoked: false }` (never a 404-that-confirms-existence), so a
 * caller can never probe or revoke another user's tokens.
 */
export function revokeShareLink(
  token: string,
  options?: RequestOptions,
): Promise<ShareRevokeResult> {
  return request<ShareRevokeResult>(
    `/me/shares/${encodeURIComponent(token)}`,
    { method: "DELETE", options },
  );
}

/**
 * GET /public/r/{token} — resolve a live share token to the SAFE public page
 * payload and count the view. UNAUTHENTICATED: this endpoint never resolves a
 * caller, so no `token`/api-key is required (the backend ignores one if sent). An
 * unknown / revoked token (or a dangling link whose job was deleted) is a clean
 * 404 ({@link ApiError}). The returned {@link SharePublic} carries ONLY safe
 * fields (title, WATERMARKED preview URL, created-at, sharer referral code).
 */
export function getPublicShare(
  token: string,
  options?: RequestOptions,
): Promise<SharePublic> {
  return request<SharePublic>(`/public/r/${encodeURIComponent(token)}`, {
    options,
  });
}

// ---------------------------------------------------------------------------
// Creator Profiles + Follow Graph + Leaderboards
// (GET /creators/leaderboard, GET /creators/{handle_or_id},
//  POST/DELETE /creators/{id}/follow, GET /me/following, PATCH /me/profile)
//
// Public creator identity + a directed follow graph + a documented, deterministic
// reputation leaderboard. The leaderboard + profile are PUBLIC (no auth); follow
// / following / profile-update are auth-gated + owner-scoped. Every public surface
// exposes ONLY safe fields — never credits, email, cost/revenue, or another
// user's private data. `limit` is clamped 1..100 here and re-clamped server-side.
// ---------------------------------------------------------------------------

/**
 * GET /creators/leaderboard — creators ranked by `metric` (defaults to
 * `reputation`; an unknown metric normalises server-side). PUBLIC (no auth).
 * `limit` is clamped to 1..100. The backend may return the list directly as
 * `data` or wrapped as `{ items: [...] }`; both are normalized to a
 * `LeaderboardEntry[]` here (a blank payload degrades to an empty list).
 */
export async function getLeaderboard(
  opts?: RequestOptions & { metric?: LeaderboardMetric | string; limit?: number },
): Promise<LeaderboardEntry[]> {
  const { metric, limit, ...reqOptions } = opts ?? {};

  const params: string[] = [];
  const trimmedMetric = (metric ?? "").trim();
  if (trimmedMetric) params.push(`metric=${encodeURIComponent(trimmedMetric)}`);
  if (typeof limit === "number" && Number.isFinite(limit)) {
    const clamped = Math.max(1, Math.min(MAX_LEADERBOARD_LIMIT, Math.trunc(limit)));
    params.push(`limit=${clamped}`);
  }
  const qs = params.length > 0 ? `?${params.join("&")}` : "";

  const data = await request<LeaderboardEntry[] | { items?: LeaderboardEntry[] }>(
    `/creators/leaderboard${qs}`,
    { options: reqOptions },
  );
  if (Array.isArray(data)) return data;
  return data?.items ?? [];
}

/**
 * GET /creators/{handleOrId} — a creator's SAFE public profile, by user id OR
 * case-insensitive handle. PUBLIC (no auth). An unknown creator is a clean 404
 * ({@link ApiError}). The returned {@link CreatorProfile} omits `user_id`, email,
 * credits and every private financial.
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
 * POST /creators/{creatorId}/follow — follow another creator (auth). Idempotent
 * (following someone twice is a no-op success). The backend rejects a self-follow
 * (400) and an unknown followee (404). Returns the caller's new follow-state +
 * the target's refreshed follower count.
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
 * DELETE /creators/{creatorId}/follow — unfollow a creator (auth). Unfollowing
 * someone the caller does not follow is a harmless no-op. Returns
 * `{ following: false, removed, follower_count }`.
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
 * GET /me/following — the SAFE public profiles of the creators the caller follows
 * (auth; bounded server-side so a heavily-following account can never trigger an
 * unbounded fan-out). The backend may return the list directly as `data` or
 * wrapped as `{ items: [...] }`; both are normalized to a `CreatorProfile[]`.
 */
export async function listFollowing(
  options?: RequestOptions,
): Promise<CreatorProfile[]> {
  const data = await request<CreatorProfile[] | { items?: CreatorProfile[] }>(
    "/me/following",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.items ?? [];
}

/**
 * PATCH /me/profile — update the caller's own public profile (auth). Every field
 * is optional; only the fields set change. `handle` is normalised + shape-checked
 * server-side (a bad shape → 422 {@link ApiError}, a taken handle → 409). Returns
 * the caller's updated {@link CreatorProfile}.
 */
export function updateMyProfile(
  body: ProfileUpdateRequest,
  options?: RequestOptions,
): Promise<CreatorProfile> {
  return request<CreatorProfile>("/me/profile", {
    method: "PATCH",
    body,
    options,
  });
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
  return pollUntilTerminal({
    fetchSnapshot: (signal) =>
      getJob(id, { token: options?.token, signal }),
    isTerminal: (job) => isTerminalState(job.state),
    onSnapshot: onTick,
    signal: options?.signal,
    intervalMs,
    maxAttempts,
    timeoutError: () =>
      new ApiError(
        `Timed out waiting for job ${id} to complete after ${maxAttempts} polls.`,
        0,
      ),
  });
}
