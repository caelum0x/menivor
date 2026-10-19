/** The AI panel for a title (MV16): subtitles, chapters, metadata suggestions and dubbed audio. */

import { API_BASE, apiRequest, type RequestOptions } from "@/src/shared/api";

export type AiKind = "subtitles" | "chapters" | "metadata" | "dub";

export interface Chapter {
  readonly start_s: number;
  readonly end_s: number;
  readonly title: string;
}

export interface AiOutput {
  readonly kind: AiKind | "transcript";
  readonly language: string;
  readonly status: "queued" | "done" | "failed";
  readonly error: string;
  readonly chapters?: readonly Chapter[];
  readonly suggestion?: { title?: string; synopsis?: string; tags?: readonly string[] };
}

export function runAi(titleId: string, body: { kinds: AiKind[]; languages: string[]; source_language: string },
  options?: RequestOptions) {
  const tid = encodeURIComponent(titleId);
  return apiRequest<{ outputs: AiOutput[] }>(`/ott/studio/titles/${tid}/ai`, { method: "POST", body, options });
}

export function getAi(titleId: string, options?: RequestOptions) {
  const tid = encodeURIComponent(titleId);
  return apiRequest<{ outputs: AiOutput[] }>(`/ott/studio/titles/${tid}/ai`, { options });
}

export async function publicChapters(titleId: string): Promise<readonly Chapter[]> {
  const tid = encodeURIComponent(titleId);
  const route = `/ott/titles/${tid}/chapters`;
  const response = await fetch(`${API_BASE}${route}`);
  if (!response.ok) return [];
  return ((await response.json()) as { data: { chapters: Chapter[] } }).data.chapters;
}

export const LANGUAGES: readonly [string, string][] = [
  ["en", "English"], ["es", "Spanish"], ["fr", "French"], ["de", "German"], ["pt", "Portuguese"], ["it", "Italian"],
  ["tr", "Turkish"], ["ja", "Japanese"], ["hi", "Hindi"], ["ar", "Arabic"],
];

export function clock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}
