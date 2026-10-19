/**
 * Motion / camera-move studio domain — the React Native mirror of the web
 * `apps/web/src/features/motion/api.ts`. Typed fns over the shared `apiRequest`
 * transport for the `/motion` domain:
 *
 *   GET  /motion                     browse the versioned camera-move catalog
 *   GET  /motion/history             the caller's recent compiled moves (DB)
 *   GET  /motion/{preset_id}         one preset's full detail
 *   POST /motion/{preset_id}/compile preset + intensity -> deterministic MotionPlan
 *
 * The catalog / detail / compile routes are DB-free (never 503); history needs
 * the DB and degrades to a 503 the caller can surface as "history unavailable".
 * Auth is carried by the shared client (`x-api-key`); no secrets live here.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

/** Bounds the backend enforces on the compile intensity (Field(ge=0, le=100)). */
export const MOTION_INTENSITY_MIN = 0;
export const MOTION_INTENSITY_MAX = 100;
/** Backend clamps GET /motion/history to 1..100. */
export const MAX_MOTION_HISTORY_LIMIT = 100;

/** A preset's render strategy. */
export type RenderClass = "filter" | "model" | "hybrid";

/** Compact gallery card for a catalog preset (GET /motion). */
export interface MotionSummary {
  id: string;
  name: string;
  category: string;
  render_class: RenderClass;
  description: string;
  intensity: number;
  tags: string[];
  /** True when the move needs the model provider (model / hybrid). */
  requires_provider: boolean;
}

/** Path A: a pure-FFmpeg camera move (+ optional VFX mix). */
export interface MotionFilterSpec {
  camera_motion: string;
  effects: string[];
}

/** Path B: the model-class camera-control contract summary. */
export interface MotionModelSpec {
  capability: string;
  camera_pose: string;
  prompt_fragment: string;
  speed: number;
  supports_intensity: boolean;
  license_class: string;
}

/** Full preset detail (GET /motion/{preset_id}). */
export interface MotionDetail extends MotionSummary {
  filter?: MotionFilterSpec;
  model?: MotionModelSpec;
}

/** Compiled filter plan (present for filter + hybrid). */
export interface CompiledFilterPlan {
  camera_motion: string;
  intensity: number;
  effects: string[];
}

/** Compiled model plan (present for model + hybrid) — the render-worker view. */
export interface CompiledModelPlan {
  preset_id: string;
  capability: string;
  camera_pose: string;
  prompt_fragment: string;
  speed: number;
  width: number;
  height: number;
  length: number;
  provider_hints: string[];
  param_map: [string, string][];
  license_class: string;
  intensity: number;
}

/** Deterministic compiled plan (POST /motion/{preset_id}/compile). */
export interface MotionPlan {
  preset_id: string;
  motion_class: RenderClass;
  filter: CompiledFilterPlan | null;
  model: CompiledModelPlan | null;
}

/** One row of the caller's motion-render history (GET /motion/history). */
export interface MotionHistoryEntry {
  id: string;
  preset_id: string;
  motion_class: string;
  intensity: number;
  provider_key: string;
  output_ref: string | null;
}

/** Body for POST /motion/{preset_id}/compile. */
export interface CompileMotionRequest {
  intensity: number;
}

/**
 * GET /motion — list the versioned camera-move catalog. The list is normalized
 * to a plain `MotionSummary[]` (the backend wraps it as `{ motions: [...] }`).
 */
export async function listMotions(
  options?: RequestOptions,
): Promise<MotionSummary[]> {
  const data = await apiRequest<MotionSummary[] | { motions?: MotionSummary[] }>(
    "/motion",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.motions ?? [];
}

/**
 * GET /motion/history — the caller's recent compiled/dispatched moves, newest
 * first. Normalized to `MotionHistoryEntry[]` (backend wraps as `{ history }`).
 * `limit` is clamped to 1..{@link MAX_MOTION_HISTORY_LIMIT} before sending.
 */
export async function getMotionHistory(
  params: { limit?: number } = {},
  options?: RequestOptions,
): Promise<MotionHistoryEntry[]> {
  const requested = params.limit ?? 50;
  const limit = Math.max(1, Math.min(MAX_MOTION_HISTORY_LIMIT, Math.trunc(requested)));
  const query = `?limit=${encodeURIComponent(limit)}`;
  const data = await apiRequest<
    MotionHistoryEntry[] | { history?: MotionHistoryEntry[] }
  >(`/motion/history${query}`, { options });
  if (Array.isArray(data)) return data;
  return data?.history ?? [];
}

/** GET /motion/{preset_id} — one preset's full detail. */
export function getMotion(
  presetId: string,
  options?: RequestOptions,
): Promise<MotionDetail> {
  return apiRequest<MotionDetail>(
    `/motion/${encodeURIComponent(presetId)}`,
    { options },
  );
}

/**
 * POST /motion/{preset_id}/compile — compile a preset + intensity into a
 * deterministic {@link MotionPlan}. `intensity` is clamped to the backend's
 * 0..100 range so an out-of-range value never round-trips a 422.
 */
export function compileMotion(
  presetId: string,
  body: CompileMotionRequest,
  options?: RequestOptions,
): Promise<MotionPlan> {
  const intensity = Math.max(
    MOTION_INTENSITY_MIN,
    Math.min(MOTION_INTENSITY_MAX, Math.trunc(body.intensity)),
  );
  return apiRequest<MotionPlan>(
    `/motion/${encodeURIComponent(presetId)}/compile`,
    { method: "POST", body: { intensity }, options },
  );
}
