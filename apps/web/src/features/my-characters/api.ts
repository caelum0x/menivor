/** My characters and brands (MH4) API. Everything here is signed in and owner-scoped. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface MyCharacter {
  readonly id: string;
  readonly name: string;
  readonly kind: "original" | "real_face" | "described";
  readonly reference_count: number;
  readonly trained: boolean;
  readonly consent?: { readonly verified: boolean; readonly words_heard: number; readonly words_total: number };
  readonly identity_lock?: { readonly passport_id: string; readonly version: number };
  readonly narrator_id?: string;
}

export interface Narrator {
  readonly id: string;
  readonly name: string;
  readonly personality: string;
}

export interface Passport {
  readonly passport_id: string;
  readonly version: number;
  readonly kind: string;
}

export interface BrandKit {
  readonly id: string;
  readonly name: string;
  readonly logo: string;
  readonly colors: readonly string[];
  readonly voice_name: string;
  readonly caption_style: string;
  readonly product_shots: readonly string[];
}

export interface TrainingQuote {
  readonly character_id: string;
  readonly credit_kind: "ai_video";
  readonly credits: number;
  readonly references: number;
}

export interface ScoreSummary {
  readonly count: number;
  readonly presets: number;
  readonly models: number;
  readonly min: number | null;
  readonly mean: number | null;
}

export const MIN_PHOTOS = 10;
export const MAX_PHOTOS = 20;

export async function listMyCharacters(options?: RequestOptions): Promise<readonly MyCharacter[]> {
  return (await apiRequest<{ characters: MyCharacter[] }>("/my/characters", { options })).characters ?? [];
}

export async function listNarrators(options?: RequestOptions): Promise<{ available: boolean; narrators: readonly Narrator[] }> {
  return apiRequest("/characters/narrators", { options });
}

export function addOriginal(narratorId: string, options?: RequestOptions): Promise<MyCharacter> {
  return apiRequest<MyCharacter>("/my/characters/original", { method: "POST", body: { narrator_id: narratorId }, options });
}

export function consentPhrase(options?: RequestOptions): Promise<{ token: string; phrase: string; expires_at: number }> {
  return apiRequest("/my/characters/consent-phrase", { method: "POST", options });
}

export async function listPassports(options?: RequestOptions): Promise<readonly Passport[]> {
  const data = await apiRequest<Passport[] | { identities?: Passport[] }>("/media/identities", { options });
  return Array.isArray(data) ? data : data.identities ?? [];
}

export function createRealFace(
  body: {
    name: string;
    reference_keys: readonly string[];
    consent_token: string;
    recording_key: string;
    passport_id: string;
    passport_version: number;
    self_declared: boolean;
  },
  options?: RequestOptions,
): Promise<MyCharacter> {
  return apiRequest<MyCharacter>("/my/characters/real-face", { method: "POST", body, options });
}

export function trainingQuote(id: string, options?: RequestOptions): Promise<TrainingQuote> {
  const cid = encodeURIComponent(id);
  return apiRequest<TrainingQuote>(`/my/characters/${cid}/train/quote`, { method: "POST", options });
}

export function startTraining(id: string, quotedCredits: number, options?: RequestOptions) {
  const cid = encodeURIComponent(id);
  return apiRequest<{ job_id: string }>(`/my/characters/${cid}/train`, {
    method: "POST",
    body: { quoted_credits: quotedCredits },
    options,
  });
}

export function recordIdentityScore(
  id: string,
  body: { job_id: string; preset_id: string; model: string },
  options?: RequestOptions,
): Promise<{ score: number }> {
  const cid = encodeURIComponent(id);
  return apiRequest<{ score: number }>(`/my/characters/${cid}/identity-scores`, { method: "POST", body, options });
}

export async function scoreSummary(id: string, options?: RequestOptions): Promise<ScoreSummary> {
  const cid = encodeURIComponent(id);
  return (await apiRequest<{ summary: ScoreSummary }>(`/my/characters/${cid}/identity-scores`, { options })).summary;
}

export async function listBrands(options?: RequestOptions): Promise<readonly BrandKit[]> {
  return (await apiRequest<{ brands: BrandKit[] }>("/my/brands", { options })).brands ?? [];
}

export function setProductShots(kitId: string, keys: readonly string[], options?: RequestOptions): Promise<BrandKit> {
  const kid = encodeURIComponent(kitId);
  return apiRequest<BrandKit>(`/my/brands/${kid}/product-shots`, { method: "PUT", body: { keys }, options });
}
