/** Live and chat API (MV10, MV11). Viewer calls carry the channel session in `X-OTT-Viewer`. */

import { API_BASE, apiRequest, type RequestOptions } from "@/src/shared/api";
import type { ChatMessage } from "./realtime";

export interface LiveSummary {
  readonly id: string;
  readonly title: string;
  readonly access_tier: "free" | "paid";
  readonly started_at: string | null;
  readonly chat_enabled: boolean;
}

export interface StudioStream {
  readonly id: string;
  readonly title: string;
  readonly status: "idle" | "live" | "ended";
  readonly peak_viewers: number;
  readonly latency_s: { median: number; samples: number } | null;
  readonly vod_title_ids: readonly string[];
  readonly slow_mode_s: number;
  readonly chat_enabled: boolean;
  readonly ingest?: { server: string; stream_key: string; srt: string };
}

async function call<T>(route: string, init: { method?: string; body?: unknown; session?: string } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (init.session) headers["X-OTT-Viewer"] = init.session;
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API_BASE}${route}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
  });
  if (response.status === 204) return undefined as T;
  const payload = (await response.json().catch(() => ({}))) as { data?: T; message?: string };
  if (!response.ok) throw new Error(payload.message || "Something went wrong. Try again.");
  return payload.data as T;
}

export async function liveNow(handle: string): Promise<readonly LiveSummary[]> {
  const h = encodeURIComponent(handle);
  try {
    return (await call<{ streams: LiveSummary[] }>(`/ott/c/${h}/live`)).streams;
  } catch {
    return [];
  }
}

export function watchLive(streamId: string, session?: string) {
  const sid = encodeURIComponent(streamId);
  return call<{ hls_url: string; expires_at: number }>(`/ott/live/${sid}/watch`, { method: "POST", session });
}

export function reportLatency(streamId: string, seconds: number) {
  const sid = encodeURIComponent(streamId);
  return call<void>(`/ott/live/${sid}/latency`, { method: "POST", body: { seconds } });
}

export function readChat(streamId: string, after?: string) {
  const sid = encodeURIComponent(streamId);
  const query = after ? `?after=${encodeURIComponent(after)}` : "";
  return call<{ messages: ChatMessage[]; topic: string }>(`/ott/live/${sid}/chat${query}`);
}

export function postChat(streamId: string, session: string, body: string) {
  const sid = encodeURIComponent(streamId);
  return call<ChatMessage>(`/ott/live/${sid}/chat`, { method: "POST", session, body: { body } });
}

export const listStreams = (options?: RequestOptions) =>
  apiRequest<{ streams: StudioStream[]; max_streams: number; max_viewers: number }>("/ott/studio/live", { options });
export const createStream = (title: string, options?: RequestOptions) =>
  apiRequest<StudioStream>("/ott/studio/live", { method: "POST", body: { title }, options });
export function studioChat(streamId: string, options?: RequestOptions) {
  const sid = encodeURIComponent(streamId);
  return apiRequest<{ messages: (ChatMessage & { viewer_id: string; hidden: boolean })[]; slow_mode_s: number }>(
    `/ott/studio/live/${sid}/chat`, { options });
}
export function hideMessage(streamId: string, messageId: string, options?: RequestOptions) {
  const sid = encodeURIComponent(streamId);
  const mid = encodeURIComponent(messageId);
  return apiRequest(`/ott/studio/live/${sid}/chat/${mid}/hide`, { method: "POST", options });
}
export function banViewer(streamId: string, viewerId: string, options?: RequestOptions) {
  const sid = encodeURIComponent(streamId);
  return apiRequest(`/ott/studio/live/${sid}/chat/ban`, { method: "POST", body: { viewer_id: viewerId }, options });
}
export function setSlowMode(streamId: string, seconds: number, options?: RequestOptions) {
  const sid = encodeURIComponent(streamId);
  return apiRequest(`/ott/studio/live/${sid}/chat`, { method: "PUT", body: { slow_mode_s: seconds }, options });
}
export function rotateKey(streamId: string, options?: RequestOptions) {
  const sid = encodeURIComponent(streamId);
  return apiRequest<{ ingest: { server: string; stream_key: string; srt: string } }>(`/ott/studio/live/${sid}/key`, {
    method: "POST",
    options,
  });
}
