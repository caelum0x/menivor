/**
 * Multi-account publishing (Autopost) API. Mirrors
 * apps/api/app/domains/multipost/router.py. Every response is token-free.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type Provider = "tiktok" | "instagram" | "youtube";
export type Visibility = "public" | "friends" | "private";
export type PostStatus =
  | "scheduled"
  | "publishing"
  | "processing"
  | "published"
  | "failed"
  | "canceled"
  | "held";

export interface ProviderState {
  provider: Provider;
  label: string;
  ready: boolean;
  missing_settings: string[];
  daily_cap_max: number;
  default_daily_cap: number;
  default_gap_minutes: number;
  min_gap_floor_minutes: number;
  notes: string[];
}

export interface Account {
  id: string;
  provider: Provider;
  handle: string;
  display_name: string;
  avatar_url: string;
  status: "connected" | "needs_reauth" | "paused";
  workspace_id: string | null;
  shared: boolean;
  mine: boolean;
  daily_cap: number;
  min_gap_minutes: number;
  posting_hours: number[];
  timezone: string;
  posts_last_24h: number;
  token_expires_at: string | null;
  last_error: string;
  connected_at: string | null;
}

export interface AccountChange {
  daily_cap?: number;
  min_gap_minutes?: number;
  posting_hours?: number[];
  timezone?: string;
  paused?: boolean;
}

export interface CreatorInfo {
  nickname: string;
  username: string;
  avatar_url: string;
  privacy_level_options: string[];
  comment_disabled: boolean;
  duet_disabled: boolean;
  stitch_disabled: boolean;
  max_video_post_duration_sec: number;
  audited: boolean;
}

export interface CampaignBody {
  job_ids: string[];
  account_ids: string[];
  visibility: Visibility;
  name?: string;
  mode?: "spread" | "every";
  start_at?: string;
  caption?: string;
  hashtags?: string[];
  tiktok_mode?: "direct" | "draft";
  allow_comments?: boolean;
  allow_duet?: boolean;
  allow_stitch?: boolean;
  brand_content?: boolean;
  brand_organic?: boolean;
  consent?: boolean;
}

export interface PlannedPost {
  job_id: string;
  account_id: string;
  provider: Provider;
  account_name: string;
  at: string;
}

export interface Preview {
  start_at: string;
  posts: PlannedPost[];
  last_post_at: string | null;
  notes: string[];
}

export interface QueuedPost {
  id: string;
  campaign_id: string;
  job_id: string;
  account_id: string;
  account_name: string;
  provider: Provider;
  status: PostStatus;
  scheduled_at: string | null;
  next_attempt_at: string | null;
  attempts: number;
  provider_status: string;
  url: string;
  error: string;
  published_at: string | null;
}

export interface Campaign {
  id: string;
  name: string;
  status: "active" | "canceled";
  mode: string;
  visibility: Visibility;
  tiktok_mode: string;
  ai_generated: boolean;
  videos: number;
  accounts: number;
  start_at: string | null;
  created_at: string | null;
  counts: Record<PostStatus, number>;
  posts?: QueuedPost[];
}

export function listProviders(options?: RequestOptions) {
  return apiRequest<{ providers: ProviderState[] }>("/multipost/providers", { options });
}

export function listAccounts(options?: RequestOptions) {
  return apiRequest<{ accounts: Account[] }>("/multipost/accounts", { options });
}

export function startConnect(provider: Provider, workspaceId = "", options?: RequestOptions) {
  const key = encodeURIComponent(provider);
  const ws = encodeURIComponent(workspaceId);
  const path = workspaceId
    ? `/multipost/connect/${key}/authorize?workspace_id=${ws}`
    : `/multipost/connect/${key}/authorize`;
  return apiRequest<{ provider: Provider; authorize_url: string }>(path, { options });
}

export function finishConnect(code: string, state: string, options?: RequestOptions) {
  return apiRequest<Account>("/multipost/connect/callback", {
    method: "POST",
    body: { code, state },
    options,
  });
}

export function updateAccount(id: string, change: AccountChange, options?: RequestOptions) {
  const key = encodeURIComponent(id);
  return apiRequest<Account>(`/multipost/accounts/${key}`, { method: "PATCH", body: change, options });
}

export function disconnectAccount(id: string, options?: RequestOptions) {
  const key = encodeURIComponent(id);
  return apiRequest<{ id: string; disconnected: boolean; posts_canceled: number }>(
    `/multipost/accounts/${key}`,
    { method: "DELETE", options },
  );
}

export function getCreatorInfo(id: string, options?: RequestOptions) {
  const key = encodeURIComponent(id);
  return apiRequest<CreatorInfo>(`/multipost/accounts/${key}/creator-info`, { options });
}

export function previewCampaign(body: CampaignBody, options?: RequestOptions) {
  return apiRequest<Preview>("/multipost/campaigns/preview", { method: "POST", body, options });
}

export function createCampaign(body: CampaignBody, options?: RequestOptions) {
  return apiRequest<Campaign>("/multipost/campaigns", { method: "POST", body, options });
}

export function listCampaigns(options?: RequestOptions) {
  return apiRequest<{ campaigns: Campaign[] }>("/multipost/campaigns", { options });
}

export function getCampaign(id: string, options?: RequestOptions) {
  const key = encodeURIComponent(id);
  return apiRequest<Campaign>(`/multipost/campaigns/${key}`, { options });
}

export function cancelCampaign(id: string, options?: RequestOptions) {
  const key = encodeURIComponent(id);
  return apiRequest<Campaign>(`/multipost/campaigns/${key}/cancel`, { method: "POST", options });
}

export function listPosts(status = "", options?: RequestOptions) {
  const value = encodeURIComponent(status);
  const path = status ? `/multipost/posts?status=${value}` : "/multipost/posts";
  return apiRequest<{ posts: QueuedPost[] }>(path, { options });
}

export function cancelPost(id: string, options?: RequestOptions) {
  const key = encodeURIComponent(id);
  return apiRequest<QueuedPost>(`/multipost/posts/${key}/cancel`, { method: "POST", options });
}

export function retryPost(id: string, options?: RequestOptions) {
  const key = encodeURIComponent(id);
  return apiRequest<QueuedPost>(`/multipost/posts/${key}/retry`, { method: "POST", options });
}
