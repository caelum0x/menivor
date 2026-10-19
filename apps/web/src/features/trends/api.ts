/** Trends explorer — rank pasted trend counts by opportunity + phase. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface TrendInput {
  trend_id: string;
  kind: string;
  counts: number[];
}

export interface RankedTrend {
  trend_id: string;
  velocity: number;
  acceleration: number;
  saturation: number;
  opportunity: number;
  phase: string;
  recommend: boolean;
}

export interface RankBody {
  trends: TrendInput[];
  limit?: number;
}

export function rankTrends(
  body: RankBody,
  options?: RequestOptions,
): Promise<{ trends: RankedTrend[] }> {
  return apiRequest<{ trends: RankedTrend[] }>("/trends/rank", {
    method: "POST",
    body,
    options,
  });
}

/** One row from the live, server-ranked trends feed. */
export interface FeedTrend {
  id: string;
  trend_id: string;
  kind: string;
  label: string;
  opportunity: number;
  saturation: number;
  phase: string;
  recommend: boolean;
}

/**
 * Fetch the live ranked trends feed (GET /trends/recommended) — server-scored rising,
 * not-yet-peaked trends, highest-opportunity first.
 */
export function getTrendsFeed(
  params: { limit?: number } = {},
  options?: RequestOptions,
): Promise<{ trends: FeedTrend[] }> {
  const limit = params.limit ?? 20;
  return apiRequest<{ trends: FeedTrend[] }>(
    `/trends/recommended?limit=${encodeURIComponent(limit)}`,
    { options },
  );
}

/** Parse lines like "trend_id: 100,400,1200,3000" into rank inputs. */
export function parseTrendLines(text: string): TrendInput[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      const [rawId = "", rawCounts = ""] = line.split(":");
      const counts = rawCounts
        .split(",")
        .map((n) => Number(n.trim()))
        .filter((n) => Number.isFinite(n));
      return { trend_id: rawId.trim(), kind: "custom", counts };
    })
    .filter((t) => t.trend_id.length > 0 && t.counts.length > 0);
}
