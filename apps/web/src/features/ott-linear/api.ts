/** FAST channels (MV15): the studio editor and the public now-and-next read. */

import { API_BASE, apiRequest, type RequestOptions } from "@/src/shared/api";

export interface LinearView {
  readonly id: string;
  readonly slug: string;
  readonly name: string;
  readonly title_ids: readonly string[];
  readonly ad_break_every: number;
  readonly watch_url: string;
}

export interface NowView {
  readonly slug: string;
  readonly name: string;
  readonly now: { kind: "program" | "ad"; title: string };
  readonly next: readonly { title: string; start: string }[];
  readonly watch_url: string;
}

export const listLinear = (options?: RequestOptions) =>
  apiRequest<{ linear: LinearView[] }>("/ott/studio/linear", { options });
export const saveLinear = (body: { slug?: string; name?: string; title_ids: string[]; ad_break_every: number }, options?: RequestOptions) =>
  apiRequest<LinearView>("/ott/studio/linear", { method: "POST", body, options });

export async function onNow(slug: string): Promise<NowView | null> {
  const s = encodeURIComponent(slug);
  const route = `/ott/linear/${s}/now`;
  const response = await fetch(`${API_BASE}${route}`, { next: { revalidate: 15 } } as RequestInit);
  if (!response.ok) return null;
  return ((await response.json()) as { data: NowView }).data;
}

export function guideUrl(slug: string): string {
  const s = encodeURIComponent(slug);
  return `${API_BASE}/ott/linear/${s}/epg.xml`;
}
