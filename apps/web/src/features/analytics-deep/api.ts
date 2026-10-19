/**
 * Analytics deep-dive API — wraps GET /me/analytics.
 *
 * Re-exports the Analytics type from lib/types so the per-metric sub-pages
 * share the same contract without reaching into lib/types directly.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import type { Analytics, AnalyticsWindowDays } from "@/lib/types";

export type { Analytics, AnalyticsWindowDays } from "@/lib/types";

export const DEEP_WINDOW_DAYS = [7, 30, 90] as const;
export const DEEP_DEFAULT_DAYS: AnalyticsWindowDays = 30;

/**
 * Fetch the caller's BI analytics for the given trailing window.
 * Mirrors GET /me/analytics?days=<n> (§ creator-analytics).
 */
export function getAnalyticsDeep(
  days: AnalyticsWindowDays = DEEP_DEFAULT_DAYS,
  options?: RequestOptions,
): Promise<Analytics> {
  return apiRequest<Analytics>(
    `/me/analytics?days=${encodeURIComponent(days)}`,
    { options },
  );
}
