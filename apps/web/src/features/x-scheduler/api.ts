/**
 * Buffer / Typefully connections. The API key is write-only: it is sent once
 * on save and never returned. Lists carry a masked hint only.
 *
 * Paths are the REST routes in apps/api `domains/x_scheduler/router.py`.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export const SCHEDULER_PROVIDERS = ["buffer", "typefully"] as const;
export type SchedulerProvider = (typeof SCHEDULER_PROVIDERS)[number];
export type ScheduleWhen = "now" | "queue" | "schedule";
export type SchedulerSource = "reel" | "render" | "media";

export interface SchedulerConnection {
  readonly provider: SchedulerProvider;
  readonly connected: boolean;
  readonly key_hint: string;
  readonly created_at: string | null;
}

export interface SchedulerTarget {
  readonly id: string;
  readonly name: string;
  readonly handle: string;
  readonly organization: string;
  readonly service: "x";
  readonly provider: SchedulerProvider;
  readonly publishing_quota?: {
    readonly used: number | null;
    readonly remaining: number | null;
    readonly resets_at: string | null;
  } | null;
}

export interface ScheduleInput {
  readonly provider: SchedulerProvider;
  readonly target_id: string;
  readonly source: SchedulerSource;
  readonly source_id: string;
  readonly caption: string;
  readonly when: ScheduleWhen;
  readonly scheduled_at?: string;
}

export interface ScheduleResult {
  readonly provider: SchedulerProvider;
  readonly target_id: string;
  readonly external_id: string;
  readonly status: string;
  readonly when: ScheduleWhen;
  readonly private_url: string;
  readonly message: string;
}

export const X_CAPTION_MAX = 280;

export function providerLabel(provider: SchedulerProvider): string {
  return provider === "buffer" ? "Buffer" : "Typefully";
}

/** Client-side check before the key leaves the browser. */
export function validateSchedulerKey(apiKey: string): string | null {
  const secret = apiKey.trim();
  if (secret.length < 8) return "Paste the full API key.";
  if (secret.length > 512) return "That key is too long.";
  if (/\s/.test(secret)) return "API keys do not contain spaces.";
  return null;
}

export function captionTooLong(caption: string): boolean {
  return caption.length > X_CAPTION_MAX;
}

/** Image vs video from a finished-output URL, for the send button's label. */
export function mediaKindFromUrl(url: string): "image" | "video" {
  const path = url.split("?")[0]?.toLowerCase() ?? "";
  return /\.(png|jpe?g|gif|webp)$/.test(path) ? "image" : "video";
}

/** GET /scheduler/connections — status only, never the saved key. */
export async function listSchedulerConnections(options?: RequestOptions): Promise<SchedulerConnection[]> {
  const data = await apiRequest<{ connections?: SchedulerConnection[] }>("/scheduler/connections", { options });
  return data.connections ?? [];
}

/** PUT /scheduler/connections/{provider} — store one key, encrypted at rest. */
export function saveSchedulerKey(
  provider: SchedulerProvider,
  apiKey: string,
  options?: RequestOptions,
): Promise<SchedulerConnection> {
  return apiRequest<SchedulerConnection>(`/scheduler/connections/${provider}`, {
    method: "PUT",
    body: { api_key: apiKey.trim() },
    options,
  });
}

/** DELETE /scheduler/connections/{provider} */
export function disconnectScheduler(
  provider: SchedulerProvider,
  options?: RequestOptions,
): Promise<{ provider: SchedulerProvider; connected: boolean }> {
  return apiRequest(`/scheduler/connections/${provider}`, { method: "DELETE", options });
}

/** GET /scheduler/connections/{provider}/targets — X accounts on that connection. */
export function listSchedulerTargets(
  provider: SchedulerProvider,
  options?: RequestOptions,
): Promise<SchedulerTarget[]> {
  return apiRequest<{ targets?: SchedulerTarget[] }>(`/scheduler/connections/${provider}/targets`, { options }).then(
    (data) => data.targets ?? [],
  );
}

/** POST /scheduler/posts — send one finished render through Buffer or Typefully. */
export function scheduleSchedulerPost(input: ScheduleInput, options?: RequestOptions): Promise<ScheduleResult> {
  return apiRequest<ScheduleResult>("/scheduler/posts", { method: "POST", body: input, options });
}
