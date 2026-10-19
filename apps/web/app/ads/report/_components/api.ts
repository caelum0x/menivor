/**
 * Cross-network allocator client: "which network pays off" report and daily
 * budget-split proposals. Money is in account-currency minor units. A cost per
 * result the data cannot support is `null`, never 0.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type NetworkId = "meta" | "tiktok" | "organic_boost" | "google" | "linkedin";
export type ProposalStatus = "proposed" | "approved" | "applied" | "rejected" | "superseded" | "failed";
export type ManualNetworkId = Exclude<NetworkId, "meta" | "tiktok">;

export const MANUAL_NETWORKS: { id: ManualNetworkId; label: string }[] = [
  { id: "organic_boost", label: "Organic boosts" },
  { id: "google", label: "Google" },
  { id: "linkedin", label: "LinkedIn" },
];

export interface NetworkRow {
  network: NetworkId;
  label: string;
  source: "measured" | "manual";
  spend_minor: number;
  results: number;
  impressions: number;
  clicks: number;
  leads: number | null;
  campaigns: number;
  current_daily_minor: number;
  cost_per_result_minor: number | null;
  ctr: number | null;
  warning: string;
}

export interface ProposalNetwork {
  network: NetworkId;
  label: string;
  source: "measured" | "manual";
  current_share: number;
  proposed_share: number;
  current_daily_minor: number;
  proposed_daily_minor: number;
  p_best: number | null;
  warning: string;
  spend_minor: number;
  results: number;
  cost_per_result_minor: number | null;
}

export interface ApplyNetworkResult {
  network: NetworkId;
  ok: boolean;
  manual?: boolean;
  daily_minor: number;
  detail: string;
}

export interface Proposal {
  id: string;
  run_date: string;
  currency: string;
  metric: "clicks" | "leads";
  total_daily_minor: number;
  max_delta: number;
  method: string;
  reason: string;
  status: ProposalStatus;
  approval_item_id: string | null;
  error: string | null;
  applied_at: string | null;
  apply_result: { networks: ApplyNetworkResult[]; at: string } | null;
  networks: ProposalNetwork[];
  created_at: string | null;
}

export interface HistoryRow {
  id: string;
  run_date: string;
  status: ProposalStatus;
  max_delta: number;
  reason: string;
  proposed_split: Record<string, number>;
  current_split: Record<string, number>;
}

export interface NetworkReport {
  currency: string;
  metric: "clicks" | "leads";
  networks: NetworkRow[];
  excluded: { key: string; platform: string; name: string; currency: string; reason: string }[];
  cheapest: NetworkId | null;
  settings: { max_step: number; min_share: number; min_results: number; auto_apply_delta: number };
  gate: { enabled: boolean; reason: string; platforms: { platform: string; label: string; enabled: boolean }[] };
  latest: Proposal | null;
  history: HistoryRow[];
}

export interface ManualNetworkInput {
  network: ManualNetworkId;
  spend_minor: number;
  results: number;
  current_daily_minor: number;
}

export interface ProposeInput {
  total_daily_minor?: number;
  manual_networks?: ManualNetworkInput[];
}

export function getNetworkReport(options?: RequestOptions): Promise<NetworkReport> {
  return apiRequest<NetworkReport>("/ads/allocator/report", { options });
}

export function proposeSplit(body: ProposeInput, options?: RequestOptions): Promise<Proposal> {
  return apiRequest<Proposal>("/ads/allocator/proposals", { method: "POST", body, options });
}

export function decideProposal(
  id: string,
  body: { decision: "approve" | "reject"; note?: string; split?: Record<string, number> },
  options?: RequestOptions,
): Promise<Proposal> {
  return apiRequest<Proposal>(`/ads/allocator/proposals/${encodeURIComponent(id)}/decision`, {
    method: "POST",
    body,
    options,
  });
}

/** Apply a proposal that was approved in the approvals feed but not yet applied. */
export function applyProposal(id: string, options?: RequestOptions): Promise<Proposal> {
  return apiRequest<Proposal>(`/ads/allocator/proposals/${encodeURIComponent(id)}/apply`, { method: "POST", options });
}
