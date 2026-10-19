/** Lip-sync translation client: options, priced plan, approval submit and recent renders. */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import { apiPath } from "@/src/shared/api/path";
import type { StudioRender } from "@/src/features/ai-actors/api";

export type { StudioRender } from "@/src/features/ai-actors/api";

export interface TranslateOptions {
  languages: { code: string; label: string }[];
  engines: { id: "kling" | "infinitetalk"; label: string; configured: boolean }[];
  videos: { id: string; title: string; url: string }[];
  voices: { actor_id: string; name: string; ready: boolean }[];
  rules: string[];
}

export interface PlanInput {
  video_url: string;
  actor_id: string;
  targets: string[];
  seconds: number;
  engine: "kling" | "infinitetalk";
  captions: boolean;
  transcript: string;
}

export const MAX_TARGETS = 10;

export function getOptions(options?: RequestOptions): Promise<TranslateOptions> {
  return apiRequest<TranslateOptions>("/translate/options", { options });
}

export async function planTranslation(input: PlanInput, options?: RequestOptions): Promise<StudioRender> {
  return (await apiRequest<{ render: StudioRender }>("/translate/plan", { method: "POST", body: input, options })).render;
}

export async function submitTranslation(renderId: string, options?: RequestOptions): Promise<StudioRender> {
  return (
    await apiRequest<{ render: StudioRender }>(apiPath`/studio-renders/${renderId}/submit`, {
      method: "POST",
      options,
    })
  ).render;
}

export async function recentTranslations(options?: RequestOptions): Promise<StudioRender[]> {
  return (await apiRequest<{ renders: StudioRender[] }>("/studio-renders?kind=lipsync_translation", { options })).renders;
}
