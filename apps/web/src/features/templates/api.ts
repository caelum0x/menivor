/** Genre shot-template API — list gallery, detail, compile, instantiate. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface TemplateSummary {
  slug: string;
  name: string;
  genre: string;
  version: string;
  description: string;
  aspect: string;
  layout: string;
  default_duration_s: number;
  min_duration_s: number;
  max_duration_s: number;
  caption_style: string;
  camera_motion: string;
  effects: string[];
  loopable: boolean;
  tags: string[];
  slot_count: number;
}

export interface TemplateSlot {
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

export interface TemplateInput {
  key: string;
  kind: string;
  label: string;
  required: boolean;
  help: string;
  choices: string[];
  default: string;
}

export interface TemplateDetail extends TemplateSummary {
  vfx_intensity: number;
  audio: { foreground: string; bgm_prompt: string; duck: boolean; trend_relink: boolean };
  slots: TemplateSlot[];
  inputs: TemplateInput[];
}

export interface ReelDraft {
  video_subject: string;
  video_script: string;
  layout: string;
  caption_style: string;
  camera_motion: string;
  effects?: string[];
  vfx_intensity?: number;
  music_prompt?: string;
  screen_recording_key?: string;
}

export interface InstantiateResult {
  template: string;
  version: string;
  render_spec: Record<string, unknown>;
  reel_draft: ReelDraft;
}

export function listTemplates(options?: RequestOptions): Promise<{ templates: TemplateSummary[] }> {
  return apiRequest<{ templates: TemplateSummary[] }>("/templates", { options });
}

export function getTemplate(slug: string, options?: RequestOptions): Promise<TemplateDetail> {
  return apiRequest<TemplateDetail>(`/templates/${encodeURIComponent(slug)}`, { options });
}

export function instantiateTemplate(
  slug: string,
  body: { inputs: Record<string, unknown>; duration_s?: number; surface?: string },
  options?: RequestOptions,
): Promise<InstantiateResult> {
  return apiRequest<InstantiateResult>(`/templates/${encodeURIComponent(slug)}/instantiate`, {
    method: "POST",
    body,
    options,
  });
}
