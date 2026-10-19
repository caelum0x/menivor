/**
 * Capture API client: URL -> recorded promo video -> reel-pipeline ads.
 *
 * Ads are made by posting the server-built `job_request` bodies to the regular
 * reel pipeline (`POST /jobs`), so captions, voice, avatars, auto-publish and
 * the winner loop apply exactly as they do for any other reel.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

/** Kinds a new capture can use. `web_game` only appears on old rows (web game capture was removed). */
export type NewCaptureKind = "website" | "native_game" | "app_store" | "play_store";
export type CaptureKind = NewCaptureKind | "web_game";
export type NativePlatform = "ios" | "android";
export type CaptureStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";
export type CaptureFormat = "9:16" | "16:9" | "1:1";
export type AdMode = "captions" | "voiceover" | "avatar";

export const KIND_LABELS: Record<CaptureKind, string> = {
  website: "Website",
  native_game: "Mobile game (simulator)",
  web_game: "Web game (retired)",
  app_store: "App Store",
  play_store: "Google Play",
};

export const KIND_HELP: Record<CaptureKind, string> = {
  website: "A headless browser loads the page and records a smooth scroll-through with a highlighted cursor.",
  native_game:
    "Records gameplay from an iOS Simulator or Android emulator on the capture server. Give a deep link into the game's demo mode for a self-playing run.",
  web_game: "Web game capture was retired; record the mobile game from a simulator instead.",
  app_store: "Reads the listing (icon, screenshots, description, rating) and builds a slideshow video.",
  play_store: "Reads the public listing page (icon, screenshots, description, rating) and builds a slideshow video.",
};

export const FORMAT_OPTIONS: { id: CaptureFormat; label: string }[] = [
  { id: "9:16", label: "9:16 vertical" },
  { id: "16:9", label: "16:9 landscape" },
  { id: "1:1", label: "1:1 square" },
];

export const AD_MODES: { id: AdMode; label: string; detail: string }[] = [
  { id: "captions", label: "Captions", detail: "The capture with your script as timed on-screen captions. No voice." },
  {
    id: "voiceover",
    label: "Free voiceover",
    detail: "A free narration voice reads your script, and word-timed captions come from the narration.",
  },
  { id: "avatar", label: "AI avatar", detail: "An AI avatar reads your script over the capture. Uses reel credits." },
];

export const FREE_VOICES: { id: string; label: string }[] = [
  { id: "en-US-AriaNeural-Female", label: "Aria (English, female)" },
  { id: "en-US-GuyNeural-Male", label: "Guy (English, male)" },
  { id: "tr-TR-EmelNeural-Female", label: "Emel (Turkish, female)" },
];

export interface DetectResult {
  kind: CaptureKind;
  url: string;
  ref: Record<string, string>;
  duration: { min: number; default: number; max: number } | null;
}

export interface CaptureSummary {
  id: string;
  source_url: string;
  source_kind: CaptureKind;
  status: CaptureStatus;
  progress: number;
  title: string;
  formats: CaptureFormat[];
  poster_url: string | null;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
}

export interface CaptureOutput {
  aspect: CaptureFormat;
  key: string;
  duration_ms: number;
  video_url: string | null;
  download_url: string | null;
  poster_url: string | null;
}

export interface CaptureScreenshot {
  key: string;
  width: number;
  height: number;
  label: string;
  url: string | null;
}

export interface ScriptDraft {
  hook: string;
  lines: string[];
  cta: string;
  script: string;
  title: string;
}

export interface CaptureDetail extends CaptureSummary {
  options: { formats?: CaptureFormat[]; duration_s?: number; cursor?: boolean };
  outputs: CaptureOutput[];
  screenshots: CaptureScreenshot[];
  listing: Record<string, unknown> | null;
  page: Record<string, unknown> | null;
  capture_mode: string | null;
  started_at: string | null;
  script_draft?: ScriptDraft;
}

export interface NativeTargetInput {
  platform: NativePlatform;
  device?: string;
  app_id?: string;
  deep_link?: string;
  title?: string;
  settle_s?: number;
}

export interface NativeStatus {
  enabled: boolean;
  platforms: NativePlatform[];
  app_ids: string[];
  duration: { min: number; default: number; max: number };
}

export interface CreateCaptureInput {
  url?: string;
  kind: NewCaptureKind | "auto";
  native?: NativeTargetInput;
  formats: CaptureFormat[];
  duration_s?: number;
  cursor: boolean;
}

export interface AdsInput {
  mode: AdMode;
  aspects: CaptureFormat[];
  script: string;
  language: "en" | "tr" | "auto";
  avatar_id?: string;
  voice_id?: string;
  voice_name?: string;
  caption_style?: string;
}

export interface AdJobRequest {
  aspect: CaptureFormat;
  job_request: Record<string, unknown>;
}

// Path literals are spelled out in full (not built from a shared prefix) so the
// production API allowlist audit (apps/api/tools/ops/api_surface_audit.py)
// can see every route this screen calls.
const enc = encodeURIComponent;

export function detectCapture(url: string, options?: RequestOptions): Promise<DetectResult> {
  return apiRequest<DetectResult>("/capture/detect", { method: "POST", body: { url }, options });
}

export function getNativeStatus(options?: RequestOptions): Promise<NativeStatus> {
  return apiRequest<NativeStatus>("/capture/native", { options });
}

export function createCapture(body: CreateCaptureInput, options?: RequestOptions): Promise<CaptureDetail> {
  return apiRequest<CaptureDetail>("/capture", { method: "POST", body, options });
}

export function listCaptures(
  options?: RequestOptions,
): Promise<{ captures: CaptureSummary[]; total: number; has_more: boolean }> {
  return apiRequest("/capture?limit=48", { options });
}

export function getCapture(id: string, options?: RequestOptions): Promise<CaptureDetail> {
  return apiRequest<CaptureDetail>(`/capture/${enc(id)}`, { options });
}

export function retryCapture(id: string, options?: RequestOptions): Promise<{ status: CaptureStatus }> {
  return apiRequest(`/capture/${enc(id)}/retry`, { method: "POST", options });
}

export function cancelCapture(id: string, options?: RequestOptions): Promise<{ status: CaptureStatus }> {
  return apiRequest(`/capture/${enc(id)}/cancel`, { method: "POST", options });
}

export function deleteCapture(id: string, options?: RequestOptions): Promise<{ deleted: boolean }> {
  return apiRequest(`/capture/${enc(id)}`, { method: "DELETE", options });
}

export function buildAdRequests(
  id: string,
  body: AdsInput,
  options?: RequestOptions,
): Promise<{ capture_id: string; mode: AdMode; requests: AdJobRequest[] }> {
  return apiRequest(`/capture/${enc(id)}/ads`, { method: "POST", body, options });
}

/** Submit one server-built reel request to the regular pipeline. */
export function submitReel(
  jobRequest: Record<string, unknown>,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<{ job_id: string }> {
  return apiRequest<{ job_id: string }>("/jobs", {
    method: "POST",
    body: jobRequest,
    options: { ...options, idempotencyKey },
  });
}

export function isActive(status: CaptureStatus): boolean {
  return status === "queued" || status === "running";
}

export function formatSeconds(ms: number): string {
  const s = Math.round(ms / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : `${s}s`;
}
