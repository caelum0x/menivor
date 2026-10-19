import type { Requester } from "../transport.js";

/** A brand clipping campaign paying a CPM up to a budget. */
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

export interface ReviewRequest {
  views: number;
  velocity_zscore?: number;
  avg_watch_frac?: number;
  engagement_rate?: number;
  geo_concentration?: number;
  retention_cliff?: number;
}

/** Clipping marketplace — campaigns, submissions, fraud-gated CPM payout. */
export class ClipmarketResource {
  constructor(private readonly request: Requester) {}

  createCampaign(body: {
    title?: string;
    cpm_micros: number;
    budget_micros: number;
    min_views?: number;
  }): Promise<Campaign> {
    return this.request("POST", "/clipmarket/campaigns", { body });
  }

  listCampaigns(params: { limit?: number } = {}): Promise<{ campaigns: Campaign[] }> {
    return this.request("GET", "/clipmarket/campaigns", { query: params });
  }

  submit(campaignId: string, clipUrl: string): Promise<Submission> {
    return this.request("POST", `/clipmarket/campaigns/${encodeURIComponent(campaignId)}/submit`, {
      body: { clip_url: clipUrl },
    });
  }

  review(submissionId: string, body: ReviewRequest): Promise<Submission> {
    return this.request("POST", `/clipmarket/submissions/${encodeURIComponent(submissionId)}/review`, {
      body,
    });
  }
}
