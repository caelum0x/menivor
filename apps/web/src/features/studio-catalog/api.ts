/**
 * Studio catalog API client.
 *
 * Thin typed wrappers over existing real backend routes — nothing fabricated.
 *
 *   GET  /voices                               reels domain voice catalog
 *   GET  /generation/speak/providers           speak domain lipsync providers
 *   GET  /avatars                              reels domain avatar catalog
 *   GET  /clipping/jobs                        clipping domain job list
 *   GET  /clipping/jobs/{id}/clips             clipping domain clip list
 *   POST /clipping/clips/{clip_id}/promote     promote a clip → reel draft
 *   GET  /captions/safezones                   captions domain per-platform safe-zones
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

// ── Voices ──────────────────────────────────────────────────────────────────

export interface CatalogVoice {
  id: string;
  name: string;
  language: string;
  gender: string;
  description: string;
  provider: string;
}

export async function listVoicesCatalog(
  options?: RequestOptions,
): Promise<CatalogVoice[]> {
  const data = await apiRequest<CatalogVoice[] | { voices?: CatalogVoice[] }>(
    "/voices",
    { options },
  );
  if (Array.isArray(data)) return data;
  return (data as { voices?: CatalogVoice[] }).voices ?? [];
}

// ── Speak providers ──────────────────────────────────────────────────────────

export interface SpeakProvider {
  provider: string;
  display_name?: string;
  license_class?: string;
  available: boolean;
}

export interface SpeakProvidersResult {
  modes: string[];
  runtime: string;
  providers: SpeakProvider[];
}

export function listSpeakProviders(
  options?: RequestOptions,
): Promise<SpeakProvidersResult> {
  return apiRequest<SpeakProvidersResult>("/generation/speak/providers", {
    options,
  });
}

// ── Avatars ──────────────────────────────────────────────────────────────────

export interface CatalogAvatar {
  id: string;
  provider: string;
  provider_avatar_id: string;
  display_name: string;
  voice_name: string;
  thumbnail_url: string;
  source: "preset" | "provider";
  avatar_id?: string;
}

export async function listAvatarsCatalog(
  options?: RequestOptions,
): Promise<CatalogAvatar[]> {
  const data = await apiRequest<CatalogAvatar[] | { avatars?: CatalogAvatar[] }>(
    "/avatars",
    { options },
  );
  if (Array.isArray(data)) return data;
  return (data as { avatars?: CatalogAvatar[] }).avatars ?? [];
}

// ── Clipping jobs ────────────────────────────────────────────────────────────

export interface ClippingJob {
  id: string;
  state: string;
  progress: number;
  language: string;
  target_count: number;
  clip_count: number;
  stitched_key: string;
  error: string;
  correlation_id: string;
}

export interface ClippingJobClip {
  id: string;
  clip_job_id: string;
  title?: string;
  hook?: string;
  score?: number;
  start_s?: number;
  end_s?: number;
  length_s?: number;
  source_in_s?: number;
  source_out_s?: number;
  result_key?: string;
  transcript?: string;
}

export interface ReelDraft {
  video_subject: string;
  video_script: string;
  source_kind: string;
  source_ref: string;
  start_s: number;
  end_s: number;
}

export async function listClippingJobs(
  params: { limit?: number; offset?: number } = {},
  options?: RequestOptions,
): Promise<ClippingJob[]> {
  const limit = Math.max(1, Math.min(100, Math.trunc(params.limit ?? 50)));
  const offset = Math.max(0, Math.trunc(params.offset ?? 0));
  const data = await apiRequest<{ jobs: ClippingJob[] }>(
    `/clipping/jobs?limit=${limit}&offset=${offset}`,
    { options },
  );
  return data.jobs ?? [];
}

export async function getClippingJobClips(
  jobId: string,
  options?: RequestOptions,
): Promise<ClippingJobClip[]> {
  const data = await apiRequest<{ clips: ClippingJobClip[] }>(
    `/clipping/jobs/${encodeURIComponent(jobId)}/clips`,
    { options },
  );
  return data.clips ?? [];
}

export interface PromoteClipResult {
  clip: ClippingJobClip;
  reel_draft: ReelDraft;
}

export function promoteClip(
  clipId: string,
  options?: RequestOptions,
): Promise<PromoteClipResult> {
  return apiRequest<PromoteClipResult>(
    `/clipping/clips/${encodeURIComponent(clipId)}/promote`,
    { method: "POST", options },
  );
}

// ── Caption safezones ────────────────────────────────────────────────────────

export interface SafezoneEntry {
  fontsize: number;
  margin_v: number;
  y_frac: number;
}

export interface SafezonesResult {
  play_h: number;
  safezones: Record<string, SafezoneEntry>;
}

export function getCaptionSafezones(
  playH: number = 1920,
  options?: RequestOptions,
): Promise<SafezonesResult> {
  return apiRequest<SafezonesResult>(`/captions/safezones?play_h=${playH}`, {
    options,
  });
}
