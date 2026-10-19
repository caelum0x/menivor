/** Competitor tracker client: `/api/v1/competitors/...` (official ad libraries only). */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import { apiPath } from "@/src/shared/api/path";

export type Tier = "winner" | "proven" | "testing" | "unknown";

export interface TrackedBrand {
  id: string;
  name: string;
  meta_page_ids: string[];
  tiktok_advertiser_ids: string[];
  search_terms: string;
  countries: string[];
  last_checked_at: string | null;
  last_error: string;
  ads: number;
  active: number;
  new: number;
  winners: number;
}

export interface AdSource {
  id: string;
  name: string;
  connected: boolean;
  detail: string;
}

export interface CompetitorAd {
  id: string;
  brand_id: string;
  brand_name: string;
  source: string;
  advertiser: string;
  body: string;
  title: string;
  page_url: string;
  media_url: string;
  thumbnail_url: string;
  platforms: string[];
  started_at: string | null;
  stopped_at: string | null;
  active: boolean;
  is_new: boolean;
  days_running: number | null;
  tier: Tier;
  scaled: boolean;
  score: number;
  can_clone: boolean;
}

export interface Overview {
  brands: TrackedBrand[];
  sources: AdSource[];
  alerts: number;
}

export interface BrandInput {
  name: string;
  meta_page_ids: string[];
  tiktok_advertiser_ids: string[];
  search_terms: string;
  countries: string[];
}

export interface CloneOut {
  brief: Record<string, unknown>;
  source_url: string;
  ad_clone_path: string;
}

export const TRACKED_BRIEF_KEY = "menivor.adclone.trackedBrief";

export const getOverview = (options?: RequestOptions) => apiRequest<Overview>("/competitors", { options });

export const addBrand = (body: BrandInput, options?: RequestOptions) =>
  apiRequest<{ brand: TrackedBrand }>("/competitors", { method: "POST", body, options });

export const refreshBrand = (id: string, options?: RequestOptions) =>
  apiRequest<{ added: number; new: number; sources: Record<string, string> }>(
    apiPath`/competitors/${id}/refresh`,
    { method: "POST", options },
  );

export const listAds = (tier: Tier | "", options?: RequestOptions) =>
  apiRequest<{ ads: CompetitorAd[] }>(tier ? `/competitors/ads?tier=${tier}` : "/competitors/ads", { options });

export const dismissAlerts = (options?: RequestOptions) =>
  apiRequest<{ dismissed: number }>("/competitors/alerts/dismiss", { method: "POST", body: { ad_ids: [] }, options });

export const cloneAd = (id: string, options?: RequestOptions) =>
  apiRequest<CloneOut>(apiPath`/competitors/ads/${id}/clone`, { method: "POST", body: {}, options });

/** "a, b  c" -> ["a", "b", "c"] */
export function splitList(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}
