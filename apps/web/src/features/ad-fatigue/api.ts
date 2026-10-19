/** Ad fatigue client: `/api/v1/ad-fatigue` (connected ad-account metrics). */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type FatigueStatus = "fatigued" | "watch" | "fresh" | "not_enough_data";

export interface FatigueCreative {
  ad_account_id: string;
  ad_account_name: string;
  provider: string;
  entity_id: string;
  entity_name: string;
  currency: string;
  spend: number;
  days: number;
  impressions: number;
  series: { day: string; ctr: number | null; frequency: number | null }[];
  frequency: number | null;
  ctr_decay: number | null;
  cpa_drift: number | null;
  score: number | null;
  status: FatigueStatus;
  reasons: string[];
}

export interface FatigueReport {
  since: string;
  until: string;
  creatives: FatigueCreative[];
  counts: Record<FatigueStatus, number>;
  accounts: { id: string; name: string; provider: string }[];
}

export interface VariationsOut {
  action: { id: string; status: string; credits_estimate: number; title: string };
  creative: { entity_id: string; entity_name: string; score: number | null; status: string };
}

export const getReport = (days: number, options?: RequestOptions) =>
  apiRequest<FatigueReport>(`/ad-fatigue?days=${days}`, { options });

export const makeVariations = (adAccountId: string, entityId: string, options?: RequestOptions) =>
  apiRequest<VariationsOut>("/ad-fatigue/variations", {
    method: "POST",
    body: { ad_account_id: adAccountId, entity_id: entityId },
    options,
  });

/** 0.38 -> "38%"; null -> "not reported" (never an invented 0). */
export function pct(value: number | null): string {
  return value === null ? "not reported" : `${Math.round(value * 100)}%`;
}
