/**
 * Standalone Dub Studio client — Expo. Dubs ANY video the caller uploaded (not
 * just a finished reel, which the in-reel `DubSheet` covers). Same backend as
 * the web's `/studio/dub` (`apps/api/app/domains/dub/router.py`):
 *
 *   GET  /dub/options          languages, free voices, prices, availability
 *   POST /dub/videos           start a dub of a video the caller owns
 *   GET  /dub/videos           the caller's dubs, newest first
 *   GET  /dub/videos/{id}      poll one dub
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface DubStudioLanguage {
  code: string;
  label: string;
  /** Free voices for this language; the first is the default. */
  voices: string[];
}

export interface DubVoiceEngine {
  id: "edge" | "elevenlabs";
  label: string;
  available: boolean;
  free: boolean;
}

export interface DubOptions {
  /** False until the dubbing engine is set up on this deployment. */
  available: boolean;
  engine: string;
  languages: DubStudioLanguage[];
  voice_engines: DubVoiceEngine[];
  whisper_models: string[];
  default_whisper_model: string;
  translation: string;
  costs: { free: number; premium: number };
  max_seconds: number;
  max_bytes: number;
}

export interface DubSubtitle {
  language: string;
  key: string;
  url: string;
}

export type DubState = "processing" | "complete" | "failed";

export interface DubVideo {
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
}

export function getDubOptions(options?: RequestOptions): Promise<DubOptions> {
  return request<DubOptions>("/dub/options", { options });
}

export function createDubVideo(
  body: CreateDubRequest,
  options?: RequestOptions,
): Promise<DubVideo> {
  return request<DubVideo>("/dub/videos", { method: "POST", body, options });
}

export async function listDubVideos(limit = 20, options?: RequestOptions): Promise<DubVideo[]> {
  const n = Math.max(1, Math.min(50, Math.trunc(limit) || 20));
  const data = await request<{ dubs?: DubVideo[] }>(`/dub/videos?limit=${n}`, { options });
  return Array.isArray(data?.dubs) ? data.dubs : [];
}

export function getDubVideo(dubId: string, options?: RequestOptions): Promise<DubVideo> {
  return request<DubVideo>(`/dub/videos/${encodeURIComponent(dubId)}`, { options });
}

// --------------------------------------------------------------------------- //
// Pure helpers
// --------------------------------------------------------------------------- //

export function isTerminalDub(job: Pick<DubVideo, "state">): boolean {
  return job.state === "complete" || job.state === "failed";
}

export function languageLabel(languages: readonly DubStudioLanguage[], code: string): string {
  return languages.find((l) => l.code === code)?.label ?? code;
}

/** Credits this dub will cost for the chosen engine (free engine costs `costs.free`). */
export function dubCost(options: Pick<DubOptions, "costs" | "voice_engines">, engine: string): number {
  const picked = options.voice_engines.find((e) => e.id === engine);
  return picked && !picked.free ? options.costs.premium : options.costs.free;
}

/** The engine to preselect: the first available free one, else the first available. */
export function defaultEngine(engines: readonly DubVoiceEngine[]): DubVoiceEngine["id"] | "" {
  const free = engines.find((e) => e.available && e.free);
  if (free) return free.id;
  return engines.find((e) => e.available)?.id ?? "";
}

export interface DubDraft {
  videoKey: string;
  sourceLanguage: string;
  targetLanguage: string;
  engine: DubVoiceEngine["id"] | "";
  voice: string;
}

/** Validate a draft and build the request, or return the first readable problem. */
export function buildDubRequest(
  draft: DubDraft,
  options: Pick<DubOptions, "available" | "languages" | "voice_engines">,
): { ok: true; body: CreateDubRequest } | { ok: false; error: string } {
  if (!options.available) {
    return { ok: false, error: "Dubbing is not set up on this server yet." };
  }
  if (!draft.videoKey.trim()) {
    return { ok: false, error: "Upload a video or pick one you already uploaded." };
  }
  const codes = new Set(options.languages.map((l) => l.code));
  if (!codes.has(draft.sourceLanguage)) {
    return { ok: false, error: "Pick the language spoken in the video." };
  }
  if (!codes.has(draft.targetLanguage)) {
    return { ok: false, error: "Pick the language to dub into." };
  }
  if (draft.sourceLanguage === draft.targetLanguage) {
    return { ok: false, error: "Pick a different language to dub into." };
  }
  const engine = options.voice_engines.find((e) => e.id === draft.engine);
  if (draft.engine && (!engine || !engine.available)) {
    return { ok: false, error: "That voice engine is not available right now." };
  }
  const body: CreateDubRequest = {
    video_key: draft.videoKey.trim(),
    source_language: draft.sourceLanguage,
    target_language: draft.targetLanguage,
    ...(draft.engine ? { voice_engine: draft.engine } : {}),
    ...(draft.voice ? { voice: draft.voice } : {}),
  };
  return { ok: true, body };
}

/** Replace (or prepend) one dub in the history list, newest first (new array). */
export function upsertDub(list: readonly DubVideo[], dub: DubVideo): DubVideo[] {
  const exists = list.some((d) => d.dub_id === dub.dub_id);
  return exists ? list.map((d) => (d.dub_id === dub.dub_id ? dub : d)) : [dub, ...list];
}
