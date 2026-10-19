/**
 * Showcase API — templates catalog + caller's completed reels.
 *
 * Real backend endpoints:
 *   GET /templates          — seeded genre shot-templates (no auth)
 *   GET /jobs?limit=<n>     — caller's jobs, filtered to state=3 (complete)
 *
 * There is no dedicated public "published reels" endpoint. The showcase
 * surface uses:
 *   1. The templates catalog as the always-visible public gallery.
 *   2. The caller's own completed jobs when authenticated.
 *
 * Both sources are labelled honestly in the UI.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import type { TemplateSummary } from "@/src/features/templates/api";

export type { TemplateSummary } from "@/src/features/templates/api";

/** Minimal job shape needed by the showcase reel card. */
export interface ShowcaseReel {
  job_id: string;
  /** 3 = complete */
  state: number;
  progress: number;
  hook?: string;
  poster_url?: string;
  result_url?: string;
  created_at?: string;
}

/** Fetch the full templates catalog (no auth required). */
export function listShowcaseTemplates(
  options?: RequestOptions,
): Promise<{ templates: TemplateSummary[] }> {
  return apiRequest<{ templates: TemplateSummary[] }>("/templates", {
    options,
    anonymous: true,
  });
}

/** Fetch the caller's jobs and keep only completed ones. */
export async function listCompletedReels(
  limit: number = 20,
  options?: RequestOptions,
): Promise<ShowcaseReel[]> {
  const result = await apiRequest<{ jobs: ShowcaseReel[] }>(
    `/jobs?limit=${encodeURIComponent(limit)}&offset=0`,
    { options },
  );
  // state === 3 is TASK_STATE_COMPLETE on the backend
  return result.jobs.filter((j) => j.state === 3);
}
