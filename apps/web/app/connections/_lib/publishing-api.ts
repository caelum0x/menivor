/**
 * Extended publish platforms API (Facebook Pages, LinkedIn, X, Threads,
 * Pinterest, Bluesky). Mirrors apps/api/app/domains/publishing/extended/router.py.
 * Every response is token-free.
 */

import { ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type ExtendedPlatform =
  | "facebook"
  | "linkedin"
  | "x"
  | "threads"
  | "pinterest"
  | "bluesky";

export type PlatformState =
  | "not_configured"
  | "plan_required"
  | "not_connected"
  | "needs_target"
  | "needs_reauth"
  | "connected";

export type TargetKind = "self" | "page" | "organization" | "board";

export interface PostTarget {
  id: string;
  name: string;
  kind: TargetKind;
}

export interface FormatRules {
  caption_max: number;
  title_max: number;
  hashtags_max: number;
  video_min_seconds: number;
  video_max_seconds: number;
  max_bytes: number;
  aspect_note: string;
}

export interface ExtendedConnection {
  platform: ExtendedPlatform;
  status: string;
  status_note: string;
  account_name: string;
  external_account_id: string;
  target_kind: TargetKind;
  target_id: string;
  target_name: string;
  targets: PostTarget[];
  scopes: string;
  token_expires_at: string | null;
  connected_at: string | null;
}

export interface PlatformRecord {
  platform: ExtendedPlatform;
  label: string;
  auth: "oauth2" | "app_password";
  target_kind: TargetKind;
  state: PlatformState;
  server_state: string;
  server_note: string;
  review_note: string;
  cost_note: string;
  supports_organization: boolean;
  rules: FormatRules;
  connection: ExtendedConnection | null;
}

export interface PlatformsOverview {
  platforms: PlatformRecord[];
  publishing_enabled: boolean;
}

export interface FormatIssue {
  level: "warning" | "error";
  field: string;
  message: string;
}

export interface FittedPost {
  platform: ExtendedPlatform;
  text: string;
  title: string;
  hashtags: string[];
  length: number;
  limit: number;
  ok: boolean;
  issues: FormatIssue[];
}

export interface PostDraft {
  platform: ExtendedPlatform;
  caption: string;
  title: string;
  hashtags: string[];
}

export type PostStatus =
  | "scheduled"
  | "publishing"
  | "processing"
  | "published"
  | "failed"
  | "canceled"
  | "held";

export interface PlatformPost {
  id: string;
  job_id: string;
  platform: ExtendedPlatform;
  platform_label: string;
  status: PostStatus;
  scheduled_at: string | null;
  published_at: string | null;
  attempts: number;
  title: string;
  text: string;
  hashtags: string[];
  external_id: string;
  url: string;
  error: string;
  note: string;
  can_cancel: boolean;
  can_retry: boolean;
  created_at: string | null;
}

export interface PostPage {
  posts: PlatformPost[];
  total: number;
  limit: number;
  offset: number;
}

export interface Problem {
  platform: string;
  message: string;
}

/** Platform order and short labels used before the overview loads. */
export const EXTENDED_PLATFORMS: readonly ExtendedPlatform[] = [
  "facebook",
  "linkedin",
  "x",
  "threads",
  "pinterest",
  "bluesky",
];

/** Marker stored with the OAuth state so the callback knows which API to call. */
export const EXTENDED_STATE_PREFIX = "ext:";

export function getPlatforms(options?: RequestOptions): Promise<PlatformsOverview> {
  return apiRequest<PlatformsOverview>("/publishing/platforms", { options });
}

export function startConnect(
  platform: ExtendedPlatform,
  organization: boolean,
  options?: RequestOptions,
): Promise<{ platform: ExtendedPlatform; authorize_url: string; state: string }> {
  const query = organization ? "?organization=true" : "";
  return apiRequest(`/publishing/connect/${platform}/authorize${query}`, { options });
}

export function finishConnect(
  code: string,
  state: string,
  options?: RequestOptions,
): Promise<PlatformRecord> {
  return apiRequest<PlatformRecord>("/publishing/connect/callback", {
    method: "POST",
    body: { code, state },
    options,
  });
}

export function connectBluesky(
  handle: string,
  appPassword: string,
  pds: string,
  options?: RequestOptions,
): Promise<PlatformRecord> {
  return apiRequest<PlatformRecord>("/publishing/connect/bluesky", {
    method: "POST",
    body: { handle, app_password: appPassword, pds },
    options,
  });
}

export function chooseTarget(
  platform: ExtendedPlatform,
  targetId: string,
  options?: RequestOptions,
): Promise<PlatformRecord> {
  return apiRequest<PlatformRecord>(`/publishing/connections/${platform}/target`, {
    method: "POST",
    body: { target_id: targetId },
    options,
  });
}

export function refreshTargets(
  platform: ExtendedPlatform,
  options?: RequestOptions,
): Promise<PlatformRecord> {
  return apiRequest<PlatformRecord>(`/publishing/connections/${platform}/refresh`, {
    method: "POST",
    options,
  });
}

export function disconnectPlatform(
  platform: ExtendedPlatform,
  options?: RequestOptions,
): Promise<{ platform: string; disconnected: boolean }> {
  return apiRequest(`/publishing/connections/${platform}`, { method: "DELETE", options });
}

export function checkFormats(
  drafts: PostDraft[],
  options?: RequestOptions,
): Promise<{ results: FittedPost[] }> {
  return apiRequest("/publishing/format-check", {
    method: "POST",
    body: { drafts },
    options,
  });
}

export function createPosts(
  jobId: string,
  drafts: PostDraft[],
  scheduledAt: string | null,
  options?: RequestOptions,
): Promise<{ posts: PlatformPost[] }> {
  return apiRequest("/publishing/posts", {
    method: "POST",
    body: { job_id: jobId, drafts, scheduled_at: scheduledAt },
    options,
  });
}

export function listPosts(
  statuses: readonly PostStatus[],
  offset = 0,
  options?: RequestOptions,
): Promise<PostPage> {
  const params = new URLSearchParams();
  if (statuses.length) params.set("status", statuses.join(","));
  params.set("limit", "50");
  params.set("offset", String(offset));
  return apiRequest<PostPage>(`/publishing/posts?${params.toString()}`, { options });
}

export function cancelPost(postId: string, options?: RequestOptions): Promise<PlatformPost> {
  return apiRequest<PlatformPost>(`/publishing/posts/${encodeURIComponent(postId)}/cancel`, {
    method: "POST",
    options,
  });
}

export function retryPost(postId: string, options?: RequestOptions): Promise<PlatformPost> {
  return apiRequest<PlatformPost>(`/publishing/posts/${encodeURIComponent(postId)}/retry`, {
    method: "POST",
    options,
  });
}

/** Strip the request-id prefix the API puts in front of messages. */
export function cleanMessage(message: string): string {
  return message.replace(/^[0-9a-f]{32}:\s*/i, "").replace(/\s*\(correlation [^)]+\)$/, "");
}

export function errorText(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/** Per-platform problems returned with a 409 from POST /publishing/posts. */
export function problemsOf(err: unknown): Problem[] {
  if (!(err instanceof ApiError)) return [];
  const detail = err.detail as { data?: { problems?: Problem[] } } | undefined;
  const problems = detail?.data?.problems;
  return Array.isArray(problems) ? problems : [];
}
