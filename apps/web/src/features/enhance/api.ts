/**
 * Upscale and smooth (MH7) API. Image upscales are free inside a daily cap;
 * video work is quoted in AI-video credits first and started with that price.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type VideoOp = "upscale" | "smooth";

export interface VideoQuote {
  readonly op: VideoOp;
  readonly ai_video_credits: number;
  readonly seconds: number;
  readonly output?: readonly [number, number];
}

export interface EnhanceJob {
  readonly job_id: string;
  readonly kind: "enhance_image" | "enhance_video";
  readonly op: VideoOp;
  readonly state: number;
  readonly result_url: string;
  readonly seconds: number | null;
  readonly output: readonly [number, number] | null;
  readonly error: string;
  readonly refunded: boolean;
}

export function upscaleStill(sourceJobId: string, options?: RequestOptions) {
  return apiRequest<{ job_id: string; state: number }>("/enhance/image", {
    method: "POST",
    body: { source_job_id: sourceJobId },
    options,
  });
}

export function quoteVideo(sourceJobId: string, op: VideoOp, options?: RequestOptions): Promise<VideoQuote> {
  return apiRequest<VideoQuote>("/enhance/video/quote", { method: "POST", body: { source_job_id: sourceJobId, op }, options });
}

export function startVideo(sourceJobId: string, op: VideoOp, quotedCredits: number, options?: RequestOptions) {
  return apiRequest<{ job_id: string; state: number }>("/enhance/video", {
    method: "POST",
    body: { source_job_id: sourceJobId, op, quoted_credits: quotedCredits },
    options,
  });
}

export function getEnhance(jobId: string, options?: RequestOptions): Promise<EnhanceJob> {
  const jid = encodeURIComponent(jobId);
  return apiRequest<EnhanceJob>(`/enhance/${jid}`, { options });
}
