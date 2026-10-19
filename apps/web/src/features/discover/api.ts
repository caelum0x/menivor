/**
 * Discover hub API — aggregates live trend feed + viral format templates.
 *
 * Wraps the real backend endpoints:
 *   GET  /trends/recommended   — server-ranked rising-not-peaked trends
 *   GET  /templates            — viral genre shot-templates
 *
 * The FeedTrend / TemplateSummary types are re-exported so consumers do not
 * need to reach into the underlying feature modules.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import type { FeedTrend } from "@/src/features/trends/api";
import type { TemplateSummary } from "@/src/features/templates/api";

export type { FeedTrend } from "@/src/features/trends/api";
export type { TemplateSummary } from "@/src/features/templates/api";

/** Fetch recommended trends, optionally filtered to a single `kind`. */
export function getRecommendedTrends(
  params: { limit?: number } = {},
  options?: RequestOptions,
): Promise<{ trends: FeedTrend[] }> {
  const limit = params.limit ?? 30;
  const qs = `limit=${encodeURIComponent(limit)}`;
  return apiRequest<{ trends: FeedTrend[] }>(`/trends/recommended?${qs}`, { options });
}

/** Fetch all available genre shot-templates. */
export function getViralTemplates(
  options?: RequestOptions,
): Promise<{ templates: TemplateSummary[] }> {
  return apiRequest<{ templates: TemplateSummary[] }>("/templates", { options });
}

/**
 * Fetch recommended trends filtered to a single `kind` client-side.
 *
 * The backend `GET /trends/recommended` does not accept a kind query param, so
 * we fetch a broader set and filter the result. This keeps the fetch path
 * consistent with the hub and avoids a second endpoint.
 */
export async function getRecommendedTrendsByKind(
  kind: string,
  params: { limit?: number } = {},
  options?: RequestOptions,
): Promise<{ trends: FeedTrend[] }> {
  const broadLimit = Math.min((params.limit ?? 50) * 4, 100);
  const res = await getRecommendedTrends({ limit: broadLimit }, options);
  return { trends: res.trends.filter((t) => t.kind === kind) };
}
