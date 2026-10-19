/**
 * Free App Store / Play audit (Menivor Growth phase 1). Public read: the API
 * route (`POST /audit`) needs no sign-in, so every call here is `anonymous`.
 * Shape matches `app/domains/appaudit/service.py:run_audit` on the API.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type CheckStatus = "pass" | "warn" | "fail";

export interface PackagingCheck {
  readonly id: string;
  readonly label: string;
  readonly status: CheckStatus;
  readonly why: string;
  readonly heuristic: boolean;
}

export interface PackagingScore {
  readonly score: number;
  readonly checks: readonly PackagingCheck[];
}

export interface TermRank {
  readonly term: string;
  readonly position: number | null;
  readonly checked_count: number;
}

export interface Competitor {
  readonly app_id: string;
  readonly title: string;
  readonly count: number;
}

export interface SearchVisibility {
  readonly available: boolean;
  readonly reason?: string;
  readonly terms: readonly string[];
  readonly results: readonly TermRank[];
  readonly top_competitors: readonly Competitor[];
  readonly cached: boolean;
  readonly errors: readonly string[];
}

export interface AuditListing {
  readonly store: "app_store" | "play_store";
  readonly url: string;
  readonly title: string;
  readonly subtitle: string | null;
  readonly subtitle_available: boolean;
  readonly developer: string;
  readonly rating: number | null;
  readonly rating_count: number | null;
  readonly price_label: string;
  readonly genre: string;
  readonly screenshot_count: number;
  readonly description_length: number;
  readonly icon_url: string;
  readonly last_updated: string | null;
  readonly version: string | null;
}

export interface AuditRewrite {
  readonly promo_text: string;
  readonly subtitle: string;
  readonly source: "relay" | "fallback";
}

export interface AuditResult {
  readonly input_url: string;
  readonly listing: AuditListing;
  readonly packaging_score: PackagingScore;
  readonly search_visibility: SearchVisibility;
  readonly rewrite: AuditRewrite;
  readonly generated_at: string;
}

/** Offline guess of whether a pasted link is an App Store / Play app link (mirrors the API's classifier). */
export function isStoreLink(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase().replace(/^www\./, "");
    return host === "apps.apple.com" || host === "itunes.apple.com" || host === "play.google.com";
  } catch {
    return false;
  }
}

export function runAudit(url: string, options?: RequestOptions): Promise<AuditResult> {
  return apiRequest<AuditResult>("/audit", { method: "POST", body: { url }, anonymous: true, options });
}
