/** Discovery (MV19): search titles and ask a video, answered only from its own words. */

import { API_BASE } from "@/src/shared/api";

export interface SearchHit {
  readonly id: string;
  readonly title: string;
  readonly channel: string;
  readonly artwork_url: string;
  readonly score: number;
}

export interface AskAnswer {
  readonly answer: string;
  readonly citations: readonly { start_s: number; text: string }[];
}

export async function searchTitles(q: string, channel?: string): Promise<readonly SearchHit[]> {
  const query = encodeURIComponent(q);
  const scope = channel ? `&channel=${encodeURIComponent(channel)}` : "";
  const route = `/ott/search?q=${query}${scope}`;
  const response = await fetch(`${API_BASE}${route}`);
  if (!response.ok) return [];
  return ((await response.json()) as { data: { results: SearchHit[] } }).data.results;
}

export async function askVideo(titleId: string, question: string): Promise<AskAnswer> {
  const tid = encodeURIComponent(titleId);
  const route = `/ott/titles/${tid}/ask`;
  const response = await fetch(`${API_BASE}${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  const body = (await response.json().catch(() => ({}))) as { data?: AskAnswer; message?: string };
  if (!response.ok || !body.data) throw new Error(body.message || "That question could not be answered right now.");
  return body.data;
}
