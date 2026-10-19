/**
 * Dub Studio API client — typed calls over the shared `apiRequest` transport.
 *
 *   GET  /dub/options          languages, free voices, prices, availability
 *   POST /dub/videos           start a dub of a video the caller owns
 *   GET  /dub/videos           the caller's dubs, newest first
 *   GET  /dub/videos/{id}      poll one dub
 *
 * Backed by `apps/api/app/domains/dub/router.py`. Responses arrive in the
 * shared `{ status, data }` envelope; `apiRequest` returns `data`.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface DubLanguage {
  code: string;
  label: string;
  /** Free edge-tts voices for this language; the first is the default. */
  voices: string[];
}

export interface DubVoiceEngine {
  id: "edge" | "elevenlabs";
  label: string;
  available: boolean;
  free: boolean;
}

export interface DubOptions {
  /** False until the operator sets up the dubbing engine on this deployment. */
  available: boolean;
  engine: string;
  languages: DubLanguage[];
  voice_engines: DubVoiceEngine[];
  whisper_models: string[];
  default_whisper_model: string;
  translation: "google" | "relay";
  /** Standard credits per dub, plus premium voice credits for an ElevenLabs dub. */
  costs: { free: number; premium: number; premium_voice_credits?: number };
  max_seconds: number;
  max_bytes: number;
}

export interface DubSubtitle {
  language: string;
  key: string;
  url: string;
}

export type DubState = "processing" | "complete" | "failed";

export interface DubJob {
  dub_id: string;
  state: DubState;
  progress: number;
  source_key: string;
  source_language: string;
  target_language: string;
  voice_engine: string;
  voice: string;
  free: boolean;
  credits_cost: number;
  refunded: boolean;
  video_key: string;
  video_url: string;
  subtitles: DubSubtitle[];
  error: string;
  created_at: string | null;
}

export interface CreateDubRequest {
  video_key: string;
  source_language: string;
  target_language: string;
  voice_engine?: "edge" | "elevenlabs";
  voice?: string;
  whisper_model?: string;
}

export function getDubOptions(options?: RequestOptions): Promise<DubOptions> {
  return apiRequest<DubOptions>("/dub/options", { options });
}

export function createDub(body: CreateDubRequest, options?: RequestOptions): Promise<DubJob> {
  return apiRequest<DubJob>("/dub/videos", { method: "POST", body, options });
}

export async function listDubs(limit = 20, options?: RequestOptions): Promise<DubJob[]> {
  const n = Math.max(1, Math.min(50, Math.trunc(limit) || 20));
  const data = await apiRequest<{ dubs?: DubJob[] }>(`/dub/videos?limit=${n}`, { options });
  return Array.isArray(data?.dubs) ? data.dubs : [];
}

export function getDub(dubId: string, options?: RequestOptions): Promise<DubJob> {
  return apiRequest<DubJob>(`/dub/videos/${encodeURIComponent(dubId)}`, { options });
}

export function isTerminalDub(job: Pick<DubJob, "state">): boolean {
  return job.state === "complete" || job.state === "failed";
}

/** Label for a language code using the options list (falls back to the code). */
export function languageLabel(languages: readonly DubLanguage[], code: string): string {
  return languages.find((l) => l.code === code)?.label ?? code;
}
