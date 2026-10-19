/**
 * Typed client for the non-destructive editor — Expo.
 *
 * A completed reel (or an imported clip that became a job) can be re-exported as
 * a single trimmed range or a multi-segment timeline (trims + captions +
 * overlays), OpenCut-style. Export execution is dispatched to the render workers.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface TimelineSegment {
  source_in: number;
  source_out: number;
  speed?: number;
  caption?: string | null;
}

export interface TextOverlay {
  text: string;
  start_s: number;
  end_s: number;
  position?: "top" | "center" | "bottom";
}

export interface ExportJob {
  job_id: string;
  state: string;
}

/** Export a single trimmed range from a completed reel. */
export function exportRange(
  jobId: string,
  body: { in_point: number; out_point: number },
  options?: RequestOptions,
): Promise<ExportJob> {
  return request<ExportJob>(`/jobs/${encodeURIComponent(jobId)}/exports`, {
    method: "POST",
    body,
    options,
  });
}

/** Export a multi-segment timeline (trims + captions + overlays). */
export function exportTimeline(
  jobId: string,
  body: { segments: TimelineSegment[]; overlays?: TextOverlay[] },
  options?: RequestOptions,
): Promise<ExportJob> {
  return request<ExportJob>(`/jobs/${encodeURIComponent(jobId)}/timeline-exports`, {
    method: "POST",
    body,
    options,
  });
}
