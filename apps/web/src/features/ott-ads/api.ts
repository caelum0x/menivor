/** Ads on my channel (MV14): rules, sponsor slots made from my own free titles, and their counts. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface AdView {
  readonly id: string;
  readonly name: string;
  readonly sponsor: string;
  readonly title_id: string;
  readonly click_url: string;
  readonly active: boolean;
  readonly stats: { impressions: number; completes: number; skips: number; clicks: number };
}

export interface StudioAdsView {
  readonly settings: { ads_on_free: boolean; ads_on_paid: boolean; house_ads: boolean; skip_after_s: number };
  readonly ads: readonly AdView[];
}

export type AdRule = "ads_on_free" | "ads_on_paid" | "house_ads";

export const getStudioAds = (options?: RequestOptions) => apiRequest<StudioAdsView>("/ott/studio/ads", { options });
export const putAdSettings = (body: Partial<Record<AdRule, boolean>>, options?: RequestOptions) =>
  apiRequest<StudioAdsView>("/ott/studio/ads/settings", { method: "PUT", body, options });
export const addSponsor = (body: { title_id: string; name: string; sponsor: string; click_url: string }, options?: RequestOptions) =>
  apiRequest<AdView>("/ott/studio/ads", { method: "POST", body, options });
export function stopSponsor(id: string, options?: RequestOptions) {
  const aid = encodeURIComponent(id);
  return apiRequest<AdView>(`/ott/studio/ads/${aid}/deactivate`, { method: "POST", options });
}
