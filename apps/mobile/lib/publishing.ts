/**
 * Typed client for native multi-platform publishing — Expo. Publish a completed
 * reel straight to a connected platform's native API. Mirrors the web
 * `src/features/publishing/api.ts`.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface NativePublishResult {
  platform: string;
  status: string;
  external_id: string;
  url: string;
}

export function listNativePlatforms(options?: RequestOptions): Promise<{ platforms: string[] }> {
  return request<{ platforms: string[] }>("/publishing/native/platforms", { options });
}

export function publishNative(
  jobId: string,
  body: { platform: string; title?: string; caption?: string; hashtags?: string[]; privacy?: string },
  options?: RequestOptions,
): Promise<NativePublishResult> {
  return request<NativePublishResult>(`/jobs/${encodeURIComponent(jobId)}/publish/native`, {
    method: "POST",
    body,
    options,
  });
}
