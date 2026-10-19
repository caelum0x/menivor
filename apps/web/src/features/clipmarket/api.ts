/** Clipping marketplace API — brand campaigns + clipper submissions. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface Campaign {
  id: string;
  brand_id: string;
  title: string;
  cpm_micros: number;
  budget_micros: number;
  spent_micros: number;
  min_views: number;
  status: string;
}

export interface CreateCampaignBody {
  title?: string;
  cpm_micros: number;
  budget_micros: number;
  min_views?: number;
}

export interface Submission {
  id: string;
  campaign_id: string;
  clipper_id: string;
  clip_url: string;
  verified_views: number;
  payable_micros: number;
  status: string;
  fraud_score: number;
  fraud_flags: string;
}

export function listCampaigns(options?: RequestOptions): Promise<{ campaigns: Campaign[] }> {
  return apiRequest<{ campaigns: Campaign[] }>("/clipmarket/campaigns", { options });
}

export function createCampaign(body: CreateCampaignBody, options?: RequestOptions): Promise<Campaign> {
  return apiRequest<Campaign>("/clipmarket/campaigns", { method: "POST", body, options });
}

export function submitClip(
  campaignId: string,
  clipUrl: string,
  options?: RequestOptions,
): Promise<Submission> {
  return apiRequest<Submission>(`/clipmarket/campaigns/${encodeURIComponent(campaignId)}/submit`, {
    method: "POST",
    body: { clip_url: clipUrl },
    options,
  });
}

/** Micro-USD → display USD string. */
export function usd(micros: number): string {
  return `$${(micros / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}
