/**
 * OTT viewer API (MV4/MV5). Storefront reads are public and edge-cached; the
 * server pages forward the visitor's country so geo rules apply. Playback
 * grants are fetched by the player in the browser, never rendered into HTML.
 */

import { API_BASE, apiRequest, type RequestOptions } from "@/src/shared/api";
import type { PlaybackGrant } from "@menivor/ott-player";

export interface TitleCard {
  readonly id: string;
  readonly title: string;
  readonly synopsis: string;
  readonly kind: "short" | "episode" | "movie" | "audio";
  readonly artwork_url: string;
  readonly duration_s: number;
  readonly genres: readonly string[];
  readonly rating: string;
  readonly series_id: string | null;
  readonly season: number | null;
  readonly episode: number | null;
  readonly access_tier: "free" | "paid";
  readonly available_here: boolean;
  readonly credits?: readonly { readonly name: string; readonly role: string }[];
}

export interface Storefront {
  readonly handle: string;
  readonly title: string;
  readonly tagline: string;
  readonly layout: "grid" | "rails" | "course";
  readonly brand_colors: readonly string[];
  readonly titles: readonly TitleCard[];
  readonly rails: readonly { id: string; title: string; items: readonly TitleCard[] }[];
  readonly series: readonly { id: string; title: string; synopsis: string; episodes: readonly TitleCard[] }[];
}

export interface TitlePage extends TitleCard {
  readonly channel: { readonly handle: string; readonly title: string };
  readonly watch_url?: string;
}

async function publicGet<T>(path: string, country: string | null): Promise<T | null> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: country ? { "CF-IPCountry": country } : {},
    next: { revalidate: 30 },
  } as RequestInit);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`storefront read failed (${response.status})`);
  const body = (await response.json()) as { data: T };
  return body.data;
}

export function getStorefront(handle: string, country: string | null = null): Promise<Storefront | null> {
  const h = encodeURIComponent(handle);
  return publicGet<Storefront>(`/ott/c/${h}`, country);
}

export function getTitlePage(handle: string, titleId: string, country: string | null = null): Promise<TitlePage | null> {
  const h = encodeURIComponent(handle);
  const tid = encodeURIComponent(titleId);
  return publicGet<TitlePage>(`/ott/c/${h}/titles/${tid}`, country);
}

/** Titles like this one on the same channel (Wave Q QM1.4); public and edge-cached. */
export function getRelated(titleId: string, country: string | null = null): Promise<{ results: TitleCard[] } | null> {
  const tid = encodeURIComponent(titleId);
  return publicGet<{ results: TitleCard[] }>(`/ott/titles/${tid}/related?limit=8`, country);
}

export function getEmbed(titleId: string, country: string | null = null): Promise<TitlePage | null> {
  const tid = encodeURIComponent(titleId);
  return publicGet<TitlePage>(`/ott/embed/${tid}`, country);
}

export function startPlayback(titleId: string, viewerId: string, options?: RequestOptions): Promise<PlaybackGrant> {
  const tid = encodeURIComponent(titleId);
  return apiRequest<PlaybackGrant>(`/ott/play/${tid}`, { method: "POST", body: { viewer_id: viewerId }, options });
}

export function resolveCustomDomain(host: string): Promise<{ handle: string } | null> {
  const h = encodeURIComponent(host);
  return publicGet<{ handle: string }>(`/ott/domains/${h}`, null);
}
