/**
 * Motion / camera-move studio API client.
 *
 * Typed fns over the shared `apiRequest` transport for the /motion domain:
 *   GET  /motion                     browse the camera-move catalog
 *   GET  /motion/history             the caller's recent compiled moves
 *   GET  /motion/{preset_id}         one preset's full detail
 *   POST /motion/{preset_id}/compile preset + intensity -> deterministic MotionPlan
 *
 * The catalog/compile routes are DB-free (never 503); history needs the DB.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

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

/** List the versioned camera-move catalog. */
export function listMotions(options?: RequestOptions): Promise<{ motions: MotionSummary[] }> {
  return apiRequest<{ motions: MotionSummary[] }>("/motion", { options });
}

/** Fetch the caller's recent compiled/dispatched moves (newest first). */
export function getMotionHistory(
  params: { limit?: number } = {},
  options?: RequestOptions,
): Promise<{ history: MotionHistoryEntry[] }> {
  const limit = params.limit ?? 50;
  const query = `?limit=${encodeURIComponent(limit)}`;
  return apiRequest<{ history: MotionHistoryEntry[] }>(`/motion/history${query}`, { options });
}

/** Fetch one preset's full detail. */
export function getMotion(presetId: string, options?: RequestOptions): Promise<MotionDetail> {
  return apiRequest<MotionDetail>(`/motion/${encodeURIComponent(presetId)}`, { options });
}

/** Compile a preset + intensity into a deterministic MotionPlan. */
export function compileMotion(
  presetId: string,
  body: { intensity: number },
  options?: RequestOptions,
): Promise<MotionPlan> {
  return apiRequest<MotionPlan>(`/motion/${encodeURIComponent(presetId)}/compile`, {
    method: "POST",
    body,
    options,
  });
}
