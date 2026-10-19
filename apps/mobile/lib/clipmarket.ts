/**
 * Typed client for the ClipMarket campaign engine — Expo.
 *
 * Browse active pay-per-view campaigns, launch one, moderate its lifecycle, let
 * clippers submit clips, and review verified views into a fraud-gated payout.
 * Every route mirrors `apps/api/app/domains/clipmarket/router.py`. Money values
 * are carried as integer micros (1 USD = 1_000_000 micros) end to end; render
 * them with {@link formatUsdMicros} and never derive totals on the client.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

// --------------------------------------------------------------------------- //
// Types
// --------------------------------------------------------------------------- //

/** Lifecycle state a brand can move a campaign through (`POST .../status`). */
export type CampaignStatus = "active" | "paused" | "ended";

/**
 * A campaign row as returned by `_campaign_view` on the backend. `brand_id` and
 * `min_views` are always present on server reads; they are optional here only so
 * older call-sites that build partial fixtures keep compiling.
 */
export interface Campaign {
  id: string;
  brand_id?: string;
  title: string;
  cpm_micros: number;
  budget_micros: number;
  spent_micros: number;
  min_views?: number;
  status: string;
}

export interface CreateCampaignBody {
  title?: string;
  cpm_micros: number;
  budget_micros: number;
  min_views?: number;
}

/** Body for `POST /clipmarket/campaigns/{id}/status`. */
export interface SetCampaignStatusBody {
  status: CampaignStatus;
}

/** Body for `POST /clipmarket/campaigns/{id}/submit`. */
export interface SubmitClipBody {
  clip_url: string;
}

/**
 * A clip submission as returned by `_submission_view`. `fraud_flags` is the
 * backend's free-form flag list (shape not guaranteed), so it is typed as
 * `unknown` and must be narrowed before use.
 */
export interface Submission {
  id: string;
  campaign_id: string;
  clipper_id: string;
  clip_url: string;
  verified_views: number;
  payable_micros: number;
  status: string;
  fraud_score: number;
  fraud_flags: unknown;
}

/**
 * Body for `POST /clipmarket/submissions/{id}/review`. Mirrors the backend
 * `ReviewBody` / `ViewSignals`: `views` are the verified views to settle, the
 * remaining ratios are fraud signals (all default to 0 server-side).
 */
export interface ReviewBody {
  views: number;
  velocity_zscore?: number;
  avg_watch_frac?: number;
  engagement_rate?: number;
  geo_concentration?: number;
  retention_cliff?: number;
}

// --------------------------------------------------------------------------- //
// Money formatting
// --------------------------------------------------------------------------- //

/** Format an integer micros amount (1 USD = 1_000_000 micros) as a USD string. */
export function formatUsdMicros(micros: number): string {
  return `$${(micros / 1_000_000).toFixed(2)}`;
}

// --------------------------------------------------------------------------- //
// Client
// --------------------------------------------------------------------------- //

export function listCampaigns(options?: RequestOptions): Promise<{ campaigns: Campaign[] }> {
  return request<{ campaigns: Campaign[] }>("/clipmarket/campaigns", { options });
}

export function createCampaign(
  body: CreateCampaignBody,
  options?: RequestOptions,
): Promise<Campaign> {
  return request<Campaign>("/clipmarket/campaigns", {
    method: "POST",
    body,
    options,
  });
}

/**
 * POST /clipmarket/campaigns/{id}/status — move a campaign through its
 * lifecycle (pause / resume / end). Brand-owner scoped server-side. Returns the
 * updated campaign snapshot.
 */
export function setCampaignStatus(
  campaignId: string,
  body: SetCampaignStatusBody,
  options?: RequestOptions,
): Promise<Campaign> {
  return request<Campaign>(
    `/clipmarket/campaigns/${encodeURIComponent(campaignId)}/status`,
    { method: "POST", body, options },
  );
}

/**
 * POST /clipmarket/campaigns/{id}/submit — a clipper submits a clip URL to a
 * campaign. `idempotencyKey` is sent as the `Idempotency-Key` header so a
 * repeated submit resolves to a single submission (never two). Returns the new
 * submission snapshot.
 */
export function submitClip(
  campaignId: string,
  body: SubmitClipBody,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<Submission> {
  return request<Submission>(
    `/clipmarket/campaigns/${encodeURIComponent(campaignId)}/submit`,
    { method: "POST", body, options: { ...options, idempotencyKey } },
  );
}

/**
 * POST /clipmarket/submissions/{id}/review — settle a submission: the backend
 * runs the fraud gate over the supplied view signals and, if it passes, computes
 * the payout. Returns the reviewed submission (status + `payable_micros` +
 * `fraud_score`).
 */
export function reviewSubmission(
  submissionId: string,
  body: ReviewBody,
  options?: RequestOptions,
): Promise<Submission> {
  return request<Submission>(
    `/clipmarket/submissions/${encodeURIComponent(submissionId)}/review`,
    { method: "POST", body, options },
  );
}

/** Mint a stable idempotency key for one logical clip submission. */
export function newSubmitIdempotencyKey(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `clip-submit-${Date.now().toString(36)}-${rand}`;
}
