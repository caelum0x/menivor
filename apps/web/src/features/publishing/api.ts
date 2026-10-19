/** Native publishing — post a rendered job straight to a social platform. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface NativePublishBody {
  platform: string;
  title?: string;
  caption?: string;
  hashtags?: string[];
  privacy?: string;
}

export interface NativePublishResult {
  platform: string;
  status: string;
  external_id: string;
  url: string;
}

export function listNativePlatforms(
  options?: RequestOptions,
): Promise<{ platforms: string[] }> {
  return apiRequest<{ platforms: string[] }>("/publishing/native/platforms", { options });
}

export function publishNative(
  jobId: string,
  body: NativePublishBody,
  options?: RequestOptions,
): Promise<NativePublishResult> {
  return apiRequest<NativePublishResult>(
    `/jobs/${encodeURIComponent(jobId)}/publish/native`,
    { method: "POST", body, options },
  );
}
