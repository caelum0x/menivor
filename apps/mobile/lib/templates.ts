/**
 * Typed client for the genre shot-template engine — Expo.
 *
 * Mirrors the web `src/features/templates/api.ts`. Browse the seeded viral
 * formats and instantiate one into a reel draft the wizard can submit.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface TemplateSummary {
  slug: string;
  name: string;
  genre: string;
  description: string;
  aspect: string;
  min_duration_s: number;
  max_duration_s: number;
  loopable: boolean;
  tags: string[];
  slot_count: number;
}

export interface ReelDraft {
  video_subject: string;
  video_script: string;
  layout: string;
  caption_style: string;
  camera_motion: string;
  effects?: string[];
  music_prompt?: string;
  screen_recording_key?: string;
}

export interface InstantiateResult {
  template: string;
  version: string;
  reel_draft: ReelDraft;
}

/** A resolved source bound to a track within a compiled segment. */
export interface CompiledMediaBinding {
  track: string;
  kind: string;
  ref: string;
  loop: boolean;
}

/** A resolved caption directive on a compiled segment. */
export interface CompiledCaption {
  text: string;
  style: string;
  highlight: string;
  all_caps: boolean;
  y_frac: number;
  height_frac: number;
}

/** One realized audio layer under a compiled segment. */
export interface CompiledAudioCue {
  layer: string;
  gain_db: number;
  ducked: boolean;
}

/** Character identity conditioning attached to a compiled segment (optional). */
export interface CompiledIdentityLock {
  character_id: string;
  identity_key: string;
  seed: number;
  reference_images: string[];
  ip_adapter_weight: number;
  lora_ref: string;
  lora_weight: number;
  negative_prompt: string;
}

/** A compiled segment: a slot with resolved absolute timing + bound sources. */
export interface CompiledSegment {
  role: string;
  order: number;
  t_start: number;
  t_end: number;
  track: string;
  media: CompiledMediaBinding[];
  caption: CompiledCaption | null;
  audio: CompiledAudioCue[];
  transition_in: string;
  transition_out: string;
  hook_gate: boolean;
  label: string;
  identity_lock: CompiledIdentityLock | null;
}

/** Seamless-loop intent (ASMR / loop-back genres) on a compiled spec. */
export interface CompiledLoopPlan {
  enabled: boolean;
  match_last_to_first: boolean;
  max_discontinuity: number;
}

/**
 * The full compose plan produced by POST /templates/{slug}/compile — the timed
 * RenderSpec the composer/worker consumes. This is a dry-run preview: nothing is
 * queued and no job is created, so callers can show the resolved output before
 * committing via instantiate.
 */
export interface CompiledRenderSpec {
  template_slug: string;
  template_version: string;
  genre: string;
  aspect: string;
  layout: string;
  duration_s: number;
  segments: CompiledSegment[];
  camera_motion: string;
  effects: string[];
  vfx_intensity: number;
  motion_class: string;
  motion_preset: string;
  caption_style: string;
  music_prompt: string;
  audio_foreground: string;
  duck: boolean;
  trend_relink: boolean;
  loop: CompiledLoopPlan;
  background_id: string;
  warnings: string[];
}

/** One creator input a template requires (rendered by the input form). */
export interface TemplateInputDef {
  key: string;
  kind: string;
  label: string;
  required: boolean;
  help: string;
  choices: string[];
  default: unknown;
}

/** A timeline slot in a template's shot structure (detail view only). */
export interface TemplateSlotDef {
  role: string;
  order: number;
  label: string;
  t_start_frac: number;
  t_end_frac: number;
  track: string;
  audio: string[];
  caption: boolean;
  hook_gate: boolean;
  notes: string;
}

/** Full template detail (GET /templates/{slug}) — summary + slots + inputs. */
export interface TemplateDetail extends TemplateSummary {
  version: string;
  layout: string;
  default_duration_s: number;
  caption_style: string;
  camera_motion: string;
  effects: string[];
  vfx_intensity?: number;
  audio?: {
    foreground?: string | null;
    bgm_prompt?: string | null;
    duck?: boolean;
    trend_relink?: boolean;
  };
  slots: TemplateSlotDef[];
  inputs: TemplateInputDef[];
}

/** One row of the most-instantiated-templates analytics list. */
export interface PopularTemplate {
  template_slug: string;
  count: number;
}

/** One row of the caller's own template instantiation history. */
export interface TemplateHistoryEntry {
  id: string;
  template_slug: string;
  template_version: string;
  duration_s: number;
  reel_job_id: string;
}

/**
 * One curated loop-able background from the footage library
 * (GET /templates/backgrounds). These are the "second-stimulation" clips
 * (gameplay parkour, satisfying ASMR, driving …) that split-screen / loop
 * formats auto-fill when the creator supplies no clip of their own.
 *
 * `source` is `"stock"` (resolvable today via the stock fetcher) or `"bundled"`
 * (a first-party loop). `available` is false when a bundled loop hasn't been
 * uploaded yet, so the UI can flag it rather than fail silently at render time.
 */
export interface BackgroundClip {
  id: string;
  category: string;
  label: string;
  source: string;
  provider: string;
  loopable: boolean;
  license_note: string;
  available: boolean;
}

/**
 * GET /templates/backgrounds — browse the curated background-footage library.
 * Pass a `category` to narrow the list (e.g. "gameplay", "asmr-satisfying",
 * "driving", "nature"); omit it for everything. Returns [] when the payload is
 * missing/garbled so callers can render a clean empty state.
 */
export async function listBackgrounds(
  options?: RequestOptions & { category?: string },
): Promise<BackgroundClip[]> {
  const category = options?.category;
  const q = category && category.trim() ? `?category=${encodeURIComponent(category.trim())}` : "";
  const data = await request<{ backgrounds?: BackgroundClip[] }>(`/templates/backgrounds${q}`, {
    options,
  });
  return Array.isArray(data?.backgrounds) ? data.backgrounds : [];
}

export function listTemplates(options?: RequestOptions): Promise<{ templates: TemplateSummary[] }> {
  return request<{ templates: TemplateSummary[] }>("/templates", { options });
}

/** GET /templates/{slug} — full template detail (slots + required inputs). */
export function getTemplate(slug: string, options?: RequestOptions): Promise<TemplateDetail> {
  return request<TemplateDetail>(`/templates/${encodeURIComponent(slug)}`, { options });
}

/**
 * GET /templates/analytics/popular — the most-instantiated templates. May 503
 * when the analytics DB layer is unavailable; callers should degrade to the
 * plain browse list. Returns [] when the payload is missing/garbled.
 */
export async function getPopularTemplates(
  options?: RequestOptions,
  limit = 10,
): Promise<PopularTemplate[]> {
  const data = await request<{ popular?: PopularTemplate[] }>(
    `/templates/analytics/popular?limit=${encodeURIComponent(String(limit))}`,
    { options },
  );
  return Array.isArray(data?.popular) ? data.popular : [];
}

/**
 * GET /templates/history — the caller's own recent instantiations (for quick
 * reproduce). Returns [] when the payload is missing/garbled.
 */
export async function getTemplateHistory(
  options?: RequestOptions,
  limit = 50,
): Promise<TemplateHistoryEntry[]> {
  const data = await request<{ history?: TemplateHistoryEntry[] }>(
    `/templates/history?limit=${encodeURIComponent(String(limit))}`,
    { options },
  );
  return Array.isArray(data?.history) ? data.history : [];
}

export function instantiateTemplate(
  slug: string,
  body: { inputs: Record<string, unknown>; duration_s?: number },
  options?: RequestOptions,
): Promise<InstantiateResult> {
  return request<InstantiateResult>(`/templates/${encodeURIComponent(slug)}/instantiate`, {
    method: "POST",
    body,
    options,
  });
}

/**
 * POST /templates/{slug}/compile — validate the creator's inputs and expand the
 * template into a timed {@link CompiledRenderSpec} WITHOUT creating a job (a pure
 * dry-run preview). Invalid inputs return a clean 422 (surfaced as an ApiError).
 * `surface` biases platform-specific timing (tiktok | reels | shorts).
 */
export function compileTemplate(
  slug: string,
  body: { inputs: Record<string, unknown>; duration_s?: number; surface?: string },
  options?: RequestOptions,
): Promise<CompiledRenderSpec> {
  return request<CompiledRenderSpec>(`/templates/${encodeURIComponent(slug)}/compile`, {
    method: "POST",
    body,
    options,
  });
}
