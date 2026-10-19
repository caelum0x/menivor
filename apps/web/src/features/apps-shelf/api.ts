/**
 * Apps shelf (MH8) API. The shelf is public (apps with a live preview only);
 * quotes, plans and runs are signed in and priced first.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type InputKind = "link" | "topic" | "text" | "image" | "image_text" | "image_choice" | "two_images" | "video_music" | "video_text";

export interface AppInputSpec {
  readonly kind: InputKind;
  readonly label: string;
  readonly text_label?: string;
  readonly second_label?: string;
  readonly choices?: readonly string[];
}

export interface AppPrice {
  readonly credit_kind: "standard" | "ai_video";
  readonly credits: number | null;
  readonly priced_by?: "create";
  readonly daily_cap?: number | null;
}

export interface ShelfApp {
  readonly id: string;
  readonly name: string;
  readonly blurb: string;
  readonly input: AppInputSpec;
  readonly preview_url: string;
  readonly price: AppPrice;
}

export interface AppInputs {
  image_key?: string;
  image_key_2?: string;
  video_key?: string;
  music_id?: string;
  text?: string;
  choice?: string;
}

export interface AppRun {
  readonly job_id: string;
  readonly app_id: string;
  readonly state: number;
  readonly outputs: readonly string[];
  readonly result: Record<string, unknown> | null;
  readonly error: string;
  readonly refunded: boolean;
}

export async function listApps(options?: RequestOptions): Promise<readonly ShelfApp[]> {
  const data = await apiRequest<{ apps: ShelfApp[] }>("/apps", { anonymous: true, options });
  return data.apps ?? [];
}

export function quoteApp(appId: string, inputs: AppInputs, options?: RequestOptions) {
  const aid = encodeURIComponent(appId);
  return apiRequest<AppPrice & { app_id: string }>(`/apps/${aid}/quote`, { method: "POST", body: inputs, options });
}

export function planApp(appId: string, inputs: AppInputs, options?: RequestOptions) {
  const aid = encodeURIComponent(appId);
  return apiRequest<{ route: "jobs"; body: Record<string, unknown>; app_id: string }>(`/apps/${aid}/plan`, {
    method: "POST",
    body: inputs,
    options,
  });
}

export function runApp(appId: string, inputs: AppInputs, quotedCredits: number, options?: RequestOptions) {
  const aid = encodeURIComponent(appId);
  return apiRequest<{ job_id: string; state: number }>(`/apps/${aid}/runs`, {
    method: "POST",
    body: { inputs, quoted_credits: quotedCredits },
    options,
  });
}

export function getAppRun(jobId: string, options?: RequestOptions): Promise<AppRun> {
  const jid = encodeURIComponent(jobId);
  return apiRequest<AppRun>(`/apps/runs/${jid}`, { options });
}

export function priceText(price: AppPrice): string {
  if (price.priced_by === "create" || price.credits === null) return "Priced before it starts";
  if (price.credits === 0) return "Free";
  return price.credit_kind === "ai_video" ? `${price.credits} AI-video credits` : `${price.credits} credit${price.credits === 1 ? "" : "s"}`;
}
