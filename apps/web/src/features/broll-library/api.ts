/**
 * B-roll Library API client.
 *
 * Typed fns over the shared `apiRequest` transport for reusing AI B-roll clips.
 * Every function targets an EXISTING `/generation/broll/*` route (see
 * `apps/api/app/domains/broll/router.py`) — this feature adds no backend:
 *
 *   GET  /generation/broll/generations         the caller's rendered clips (library)
 *   GET  /generation/broll/generations/{id}    poll one clip's live state/progress
 *   GET  /generation/broll/presets             the caller's available motion presets
 *
 * The list/detail routes are owner-scoped: a foreign or unknown id is a 404 with
 * no existence leak. Responses arrive as the shared `{ status, data }` envelope,
 * so `apiRequest` returns `data` directly. A list route may return the array
 * bare OR wrapped (`{ generations: [] }` / `{ presets: [] }`); both are
 * normalized here so callers always receive a plain array.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import type { BrollGenerationSnapshot } from "@reelforge/api-contract";

/** One rendered/pending AI B-roll clip in the caller's library. */
export type BrollClip = BrollGenerationSnapshot;

/** A curated/owned AI B-roll motion preset (GET /generation/broll/presets). */
export interface BrollPreset {
  id: string;
  name: string;
  description: string;
  mode: string;
  prompt_template: string;
  thumbnail_url: string;
  workflow_id: string;
  default_params: Record<string, unknown>;
}

/** Server may return the list bare or wrapped under a named key. */
function unwrapList<T>(data: T[] | Record<string, unknown>, key: string): T[] {
  if (Array.isArray(data)) return data;
  const wrapped = (data as Record<string, unknown>)[key];
  return Array.isArray(wrapped) ? (wrapped as T[]) : [];
}

/** Clamp a requested page size to the backend's accepted `[1, 100]` window. */
export const BROLL_LIBRARY_MIN_LIMIT = 1;
export const BROLL_LIBRARY_MAX_LIMIT = 100;
export const BROLL_LIBRARY_DEFAULT_LIMIT = 30;

function clampLimit(limit: number): number {
  const n = Math.trunc(limit);
  if (!Number.isFinite(n)) return BROLL_LIBRARY_DEFAULT_LIMIT;
  return Math.max(BROLL_LIBRARY_MIN_LIMIT, Math.min(BROLL_LIBRARY_MAX_LIMIT, n));
}

/**
 * GET /generation/broll/generations — the caller's recent B-roll clips (newest
 * first). `limit` is clamped to the backend's `[1, 100]` window before it is
 * sent. Used to populate the library gallery so a finished clip can be reused
 * (e.g. attached to a reel as intro/outro B-roll) without a re-generation.
 */
export async function listBrollClips(
  params: { limit?: number } = {},
  options?: RequestOptions,
): Promise<BrollClip[]> {
  const limit = clampLimit(params.limit ?? BROLL_LIBRARY_DEFAULT_LIMIT);
  const data = await apiRequest<
    BrollClip[] | { generations?: BrollClip[] }
  >(`/generation/broll/generations?limit=${encodeURIComponent(limit)}`, {
    options,
  });
  return unwrapList<BrollClip>(data, "generations");
}

/**
 * GET /generation/broll/generations/{id} — poll one clip's live state/progress
 * (and, once complete, its `broll_key` + `result_url`). Owner-scoped: an
 * unknown/foreign id is a 404.
 */
export function getBrollClip(
  id: string,
  options?: RequestOptions,
): Promise<BrollClip> {
  return apiRequest<BrollClip>(
    `/generation/broll/generations/${encodeURIComponent(id)}`,
    { options },
  );
}

/**
 * GET /generation/broll/presets — the caller's available motion presets (curated
 * global presets + any the caller owns). Surfaced in the library so a preset can
 * seed a new generation over in the studio.
 */
export async function listBrollPresets(
  options?: RequestOptions,
): Promise<BrollPreset[]> {
  const data = await apiRequest<
    BrollPreset[] | { presets?: BrollPreset[] }
  >("/generation/broll/presets", { options });
  return unwrapList<BrollPreset>(data, "presets");
}
