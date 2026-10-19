/**
 * Paid ads API client — launch Ad Studio variants on Meta / TikTok.
 *
 * Money is in account-currency minor units (cents for USD). Rates the platform
 * did not report are `null`, never 0.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type AdsPlatform = "meta" | "tiktok";
export type CampaignStatus = "active" | "paused" | "error" | "archived";
export type CreativePhase = "uploading" | "processing" | "live" | "failed";
export type Gender = "all" | "male" | "female";
export type OptimizeFor = "ctr" | "leads";

export const NOT_ENABLED_REASON = "Ads not enabled — requires Meta/TikTok app approval";

export const CTAS = [
  { id: "SHOP_NOW", label: "Shop now" },
  { id: "LEARN_MORE", label: "Learn more" },
  { id: "ORDER_NOW", label: "Order now" },
  { id: "GET_OFFER", label: "Get offer" },
  { id: "SIGN_UP", label: "Sign up" },
  { id: "CONTACT_US", label: "Contact us" },
] as const;

export interface PlatformGate {
  platform: AdsPlatform;
  label: string;
  enabled: boolean;
  min_daily_budget_minor: number;
  reason: string;
}

export interface AdsGate {
  enabled: boolean;
  reason: string;
  platforms: PlatformGate[];
  menivor_fee: number;
}

export interface AdAccount {
  id: string;
  name: string;
  currency: string;
  active: boolean;
}

export interface AdIdentity {
  id: string;
  name: string;
}

export interface Connection {
  platform: AdsPlatform;
  enabled: boolean;
  reason: string;
  connected: boolean;
  ready?: boolean;
  account_id?: string;
  identity_id?: string;
  currency?: string;
  token_hint?: string;
  connected_at?: string | null;
  accounts: AdAccount[];
  identities: AdIdentity[];
  error?: string;
}

export interface Metrics {
  spend: number;
  spend_minor: number;
  impressions: number;
  clicks: number;
  leads: number | null;
  ctr: number | null;
  cpc: number | null;
  cpl: number | null;
  lead_rate: number | null;
}

export interface Creative {
  variant_id: string;
  project_id: string;
  hook: string;
  format: string;
  aspect: string;
  poster_url: string | null;
  phase: CreativePhase;
  error: string | null;
  active: boolean;
  budget_minor: number;
  p_best: number | null;
  allocation_reason: string;
  ad_group_id: string;
  ad_id: string;
  metrics: Metrics;
}

export interface AllocationArm {
  arm_id: string;
  p_best: number;
  mean_rate: number;
  budget_minor: number;
  active: boolean;
  reason: string;
}

export interface Allocation {
  arms: AllocationArm[];
  total_minor: number;
  winner_id: string;
  conclusive: boolean;
  reason: string;
  metric?: "ctr" | "leads";
  applied?: boolean;
  at?: string;
}

export interface Audience {
  countries: string[];
  age_min: number;
  age_max: number;
  gender: Gender;
}

export interface CampaignSummary {
  key: string;
  platform: AdsPlatform;
  name: string;
  status: CampaignStatus;
  error: string | null;
  external_id: string;
  account_id: string;
  currency: string;
  daily_budget_minor: number;
  allocated_budget_minor: number;
  audience: Audience;
  optimize_for: OptimizeFor;
  auto_optimize: boolean;
  landing_url: string;
  created_at: string | null;
  synced_at: string | null;
  optimized_at: string | null;
  allocation: Allocation | null;
  metrics: Metrics;
  creative_count?: number;
}

export interface Campaign extends CampaignSummary {
  creatives: Creative[];
}

export interface CampaignList {
  campaigns: CampaignSummary[];
  total: number;
  gate: AdsGate;
}

export interface LaunchInput {
  project_id: string;
  platform: AdsPlatform;
  variant_ids: string[];
  daily_budget_minor: number;
  audience: Audience;
  name?: string;
  landing_url?: string;
  primary_text?: string;
  headline?: string;
  cta?: string;
  optimize_for?: OptimizeFor;
  auto_optimize?: boolean;
  start_now?: boolean;
}

const campaign = (key: string) => `/ads/campaigns/${encodeURIComponent(key)}`;
const connection = (p: AdsPlatform) => `/ads/connections/${p}`;

export function getAdsGate(options?: RequestOptions): Promise<AdsGate> {
  return apiRequest<AdsGate>("/ads/status", { options });
}

export function getConnection(platform: AdsPlatform, options?: RequestOptions): Promise<Connection> {
  return apiRequest<Connection>(connection(platform), { options });
}

export function startConnect(platform: AdsPlatform, options?: RequestOptions): Promise<{ authorize_url: string }> {
  return apiRequest<{ authorize_url: string }>(`${connection(platform)}/start`, { method: "POST", options });
}

export function finishConnect(
  platform: AdsPlatform,
  body: { code: string; state: string },
  options?: RequestOptions,
): Promise<Connection> {
  return apiRequest<Connection>(`${connection(platform)}/callback`, { method: "POST", body, options });
}

export function chooseAccount(
  platform: AdsPlatform,
  body: { account_id: string; identity_id?: string; identity_name?: string; currency?: string },
  options?: RequestOptions,
): Promise<Connection> {
  return apiRequest<Connection>(`${connection(platform)}/account`, { method: "PUT", body, options });
}

export function disconnectAds(platform: AdsPlatform, options?: RequestOptions): Promise<unknown> {
  return apiRequest<unknown>(connection(platform), { method: "DELETE", options });
}

export function listCampaigns(options?: RequestOptions): Promise<CampaignList> {
  return apiRequest<CampaignList>("/ads/campaigns", { options });
}

export function launchCampaign(body: LaunchInput, options?: RequestOptions): Promise<Campaign> {
  return apiRequest<Campaign>("/ads/campaigns", { method: "POST", body, options });
}

export function getCampaign(key: string, options?: RequestOptions): Promise<Campaign> {
  return apiRequest<Campaign>(campaign(key), { options });
}

export type CampaignAction = "sync" | "optimize" | "start" | "pause" | "archive";

export function campaignAction(key: string, action: CampaignAction, options?: RequestOptions): Promise<Campaign> {
  return apiRequest<Campaign>(`${campaign(key)}/${action}`, { method: "POST", options });
}

export function previewAllocation(key: string, options?: RequestOptions): Promise<Allocation> {
  return apiRequest<Allocation>(`${campaign(key)}/allocation`, { options });
}
