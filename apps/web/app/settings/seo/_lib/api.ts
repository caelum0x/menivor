/**
 * Typed client for Settings > SEO (apps/api `domains/seo/router.py`).
 *
 * The OpenSEO API key is sent once and never returned; the API stores it
 * encrypted and only shows a masked hint. Every audit/research/rank-refresh
 * call spends the workspace's own OpenSEO credits and only runs when the
 * person on this page clicks the matching button -- nothing here is batched
 * or scheduled automatically.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface Scope {
  readonly workspaceId?: string | null;
}

export interface AuditRun {
  readonly id: string;
  readonly status: "queued" | "running" | "completed" | "failed";
  readonly score: number | null;
  readonly issues_count: number | null;
  readonly summary: { readonly issues?: readonly unknown[] };
  readonly requested_at: string | null;
  readonly completed_at: string | null;
}

export interface TrackedKeyword {
  readonly id: string;
  readonly keyword: string;
  readonly country: string;
  readonly current_rank: number | null;
  readonly change_7d: number | null;
  readonly last_checked_at: string | null;
}

export interface KeywordResearchRow {
  readonly keyword: string;
  readonly seed: string;
  readonly volume: number | null;
  readonly difficulty: number | null;
  readonly cpc_minor: number | null;
  readonly intent: string;
  readonly currency: string;
  readonly fetched_at: string | null;
}

export type SeoOverview =
  | { readonly connected: false; readonly can_manage: boolean }
  | {
      readonly connected: true;
      readonly status: string;
      readonly token_hint: string;
      readonly domain: string;
      readonly project_id: string;
      readonly last_error: string | null;
      readonly can_manage: boolean;
      readonly latest_audit: AuditRun | null;
      readonly tracked_keywords: readonly TrackedKeyword[];
      readonly tracked_keyword_limit: number;
      readonly research_keyword_count: number;
    };

/** Query string for the caller's workspace (empty when personal). */
export function scopeQuery(scope: Scope = {}): string {
  const params = new URLSearchParams();
  if (scope.workspaceId) params.set("workspace_id", scope.workspaceId);
  const text = params.toString();
  return text ? `?${text}` : "";
}

function scoped(path: string, scope: Scope = {}): string {
  return `${path}${scopeQuery(scope)}`;
}

/** Client-side check before the key leaves the browser. */
export function validateOpenSeoKey(value: string): string | null {
  const key = value.trim();
  if (key.length < 8) return "Paste the full OpenSEO API key.";
  if (key.length > 300) return "That key is too long.";
  if (/\s/.test(key)) return "An API key does not contain spaces.";
  return null;
}

export function getSeoOverview(scope: Scope, options?: RequestOptions): Promise<SeoOverview> {
  return request<SeoOverview>(scoped("/seo/overview", scope), { options });
}

export function connectSeo(apiKey: string, domain: string, scope: Scope, options?: RequestOptions) {
  return request<SeoOverview>(scoped("/seo/connect", scope), {
    method: "POST", body: { api_key: apiKey.trim(), domain: domain.trim() }, options,
  });
}

export function disconnectSeo(scope: Scope, options?: RequestOptions) {
  return request<{ disconnected: boolean }>(scoped("/seo", scope), { method: "DELETE", options });
}

export function runSiteAudit(scope: Scope, options?: RequestOptions) {
  return request<AuditRun>(scoped("/seo/audit/run", scope), { method: "POST", options });
}

export function getAuditStatus(auditRunId: string, scope: Scope, options?: RequestOptions) {
  const id = encodeURIComponent(auditRunId);
  return request<AuditRun>(scoped(`/seo/audit/${id}`, scope), { options });
}

export function researchKeywords(seeds: readonly string[], scope: Scope, options?: RequestOptions) {
  return request<{ keywords: readonly KeywordResearchRow[] }>(scoped("/seo/keywords/research", scope), {
    method: "POST", body: { seeds: seeds.map((s) => s.trim()).filter(Boolean) }, options,
  });
}

export function listKeywordResearch(scope: Scope, options?: RequestOptions) {
  return request<{ keywords: readonly KeywordResearchRow[] }>(scoped("/seo/keywords/research", scope), { options });
}

export function addRankKeywords(keywords: readonly string[], country: string, scope: Scope,
  options?: RequestOptions) {
  return request<{ keywords: readonly TrackedKeyword[] }>(scoped("/seo/rank-tracker/keywords", scope), {
    method: "POST", body: { keywords: keywords.map((k) => k.trim()).filter(Boolean), country }, options,
  });
}

export function removeRankKeyword(keywordId: string, scope: Scope, options?: RequestOptions) {
  const id = encodeURIComponent(keywordId);
  return request<{ removed: boolean }>(scoped(`/seo/rank-tracker/keywords/${id}`, scope), {
    method: "DELETE", options,
  });
}

export function refreshRankTracker(scope: Scope, options?: RequestOptions) {
  return request<{ keywords: readonly TrackedKeyword[] }>(scoped("/seo/rank-tracker/refresh", scope), {
    method: "POST", options,
  });
}
