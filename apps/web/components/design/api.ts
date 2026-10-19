/**
 * Design Studio API client. JSON calls go through the shared authenticated
 * transport; image bytes are fetched with the same credential so the export
 * canvas never gets tainted by a cross-origin image.
 */

import { API_BASE, ApiError, apiRequest, type RequestOptions } from "@/src/shared/api";
import { getStoredDeviceApiKey } from "@/src/shared/device/session";
import { getSessionToken } from "@/src/shared/api/session-token";

import type {
  ApprovalItemView,
  BrandKitInfo,
  Canvas,
  DesignDoc,
  DesignSummary,
  GenerateResult,
  SizePreset,
  StoredImage,
  TemplateInfo,
} from "./types";

export function listTemplates(options?: RequestOptions) {
  return apiRequest<{ sizes: SizePreset[]; templates: TemplateInfo[] }>("/design/templates", { options });
}

export function listBrandKits(options?: RequestOptions) {
  return apiRequest<{ kits: BrandKitInfo[] }>("/design/brand-kits", { options });
}

export function generateDesigns(
  body: { prompt: string; size_preset: string; brand_kit_id?: string | null; use_llm?: boolean },
  options?: RequestOptions,
) {
  return apiRequest<GenerateResult>("/design/generate", { method: "POST", body, options });
}

export function listDesigns(options?: RequestOptions, limit = 30, offset = 0) {
  return apiRequest<{ designs: DesignSummary[]; total: number }>(
    `/design/docs?limit=${limit}&offset=${offset}`,
    { options },
  );
}

export function createDesign(
  body: {
    title?: string;
    size_preset: string;
    canvas?: Canvas | null;
    template?: string;
    template_id?: string | null;
    brand_kit_id?: string | null;
    prompt?: string;
  },
  options?: RequestOptions,
) {
  return apiRequest<DesignDoc>("/design/docs", { method: "POST", body, options });
}

export function getDesign(id: string, options?: RequestOptions) {
  return apiRequest<DesignDoc>(`/design/docs/${encodeURIComponent(id)}`, { options });
}

export function saveDesign(id: string, body: { title?: string; canvas?: Canvas }, options?: RequestOptions) {
  return apiRequest<DesignDoc>(`/design/docs/${encodeURIComponent(id)}`, { method: "PATCH", body, options });
}

export function deleteDesign(id: string, options?: RequestOptions) {
  return apiRequest<{ deleted: boolean }>(`/design/docs/${encodeURIComponent(id)}`, { method: "DELETE", options });
}

export function duplicateDesign(id: string, options?: RequestOptions) {
  return apiRequest<DesignDoc>(`/design/docs/${encodeURIComponent(id)}/duplicate`, { method: "POST", options });
}

export function exportDesign(id: string, pages: string[], options?: RequestOptions) {
  return apiRequest<DesignDoc>(`/design/docs/${encodeURIComponent(id)}/export`, {
    method: "POST",
    body: { pages },
    options,
  });
}

export function generateAiImage(id: string, prompt: string, options?: RequestOptions) {
  return apiRequest<StoredImage>(`/design/docs/${encodeURIComponent(id)}/ai-image`, {
    method: "POST",
    body: { prompt },
    options,
  });
}

export function scheduleDesign(
  id: string,
  body: { platforms: string[]; caption: string; scheduled_at?: string | null; channel_ids?: string[] },
  options?: RequestOptions,
) {
  return apiRequest<{ design: DesignDoc; approval: ApprovalItemView }>(
    `/design/docs/${encodeURIComponent(id)}/schedule`,
    { method: "POST", body, options },
  );
}

export function saveAsTemplate(id: string, name: string, options?: RequestOptions) {
  return apiRequest<TemplateInfo>(`/design/docs/${encodeURIComponent(id)}/save-template`, {
    method: "POST",
    body: { name },
    options,
  });
}

export function uploadDesignImage(dataUrl: string, options?: RequestOptions) {
  return apiRequest<StoredImage>("/design/images", { method: "POST", body: { data: dataUrl }, options });
}

async function credential(options?: RequestOptions): Promise<string> {
  if (options?.token) return options.token;
  const session = await getSessionToken();
  if (session) return session;
  const stored = getStoredDeviceApiKey();
  if (stored) return stored;
  return process.env.NEXT_PUBLIC_APP_API_KEY || "";
}

/** Fetch an owned image through the API and return a same-origin blob URL. */
export async function fetchImageBlobUrl(key: string, options?: RequestOptions): Promise<string> {
  const cred = await credential(options);
  const res = await fetch(`${API_BASE}/design/media?key=${encodeURIComponent(key)}`, {
    headers: cred ? { "x-api-key": cred } : {},
    cache: "force-cache",
  });
  if (!res.ok) throw new ApiError(`Could not load an image (${res.status})`, res.status);
  return URL.createObjectURL(await res.blob());
}
