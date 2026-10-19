/**
 * Preset shelf API (MH2). The shelf and tiles are public; planning, runs and
 * timings need the signed-in user. Money moves only through the existing
 * create routes (`POST /jobs`, `POST /generation/broll/generate`), each
 * priced first (`POST /jobs/quote`, `POST /jobs/quote/preset`).
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export type PresetKind = "filter" | "model";
export type CreditKind = "standard" | "ai_video";

export interface PresetTile {
  readonly id: string;
  readonly name: string;
  readonly blurb: string;
  readonly kind: PresetKind;
  readonly credit_kind: CreditKind;
  readonly credit_label: string;
  readonly inputs: readonly string[];
  readonly preview: { readonly loop_url: string; readonly poster_url: string };
  readonly create_url: string;
  readonly target_seconds: number;
}

export interface PresetPlan {
  readonly route: "jobs" | "generation/broll/generate";
  readonly body: Record<string, unknown>;
  readonly preset_id: string;
}

export interface PresetRunView {
  readonly job_id: string;
  readonly preset_id: string;
  readonly seconds_to_result: number | null;
  readonly target_seconds: number;
  readonly within_target: boolean | null;
}

export interface CreditTotals {
  readonly standard?: number;
  readonly ai_video?: number;
  readonly premium_voice?: number;
}

export async function listShelf(options?: RequestOptions): Promise<readonly PresetTile[]> {
  const data = await apiRequest<{ presets: PresetTile[] }>("/presets/shelf", { anonymous: true, options });
  return data.presets ?? [];
}

export function getTile(id: string, options?: RequestOptions): Promise<PresetTile> {
  const pid = encodeURIComponent(id);
  return apiRequest<PresetTile>(`/presets/shelf/${pid}`, { anonymous: true, options });
}

export function planPreset(
  id: string,
  body: { subject: string; image_key?: string; brand_kit_id?: string; character_id?: string },
  options?: RequestOptions,
): Promise<PresetPlan> {
  const pid = encodeURIComponent(id);
  return apiRequest<PresetPlan>(`/presets/shelf/${pid}/plan`, {
    method: "POST",
    body,
    options,
  });
}

/** Price before render: standard presets via `/jobs/quote`, model presets via `/jobs/quote/preset`. */
export function quotePlan(
  tile: PresetTile,
  plan: PresetPlan,
  options?: RequestOptions,
): Promise<{ credits: number; affordable: boolean; route?: string }> {
  return quoteForPlan(plan, tile.inputs.includes("image"), options);
}

/** The same price-first call for any create body (preset tiles and gallery Recreate). */
export async function quoteForPlan(
  plan: Pick<PresetPlan, "route" | "body">,
  animatesImage: boolean,
  options?: RequestOptions,
): Promise<{ credits: number; affordable: boolean; route?: string }> {
  if (plan.route === "jobs") {
    const quote = await apiRequest<{ total: CreditTotals; affordable: boolean }>("/jobs/quote", {
      method: "POST",
      body: plan.body,
      options,
    });
    return { credits: quote.total?.standard ?? 0, affordable: Boolean(quote.affordable) };
  }
  const quote = await apiRequest<{ total: CreditTotals; affordable: boolean; route?: { model_id?: string; tier?: string } }>("/jobs/quote/preset", {
    method: "POST",
    body: {
      preset_sku: animatesImage ? "animate_image" : "text_to_video",
      tier: "draft",
      seconds: 5,
    },
    options,
  });
  return {
    credits: quote.total?.ai_video ?? 0,
    affordable: Boolean(quote.affordable),
    route: quote.route?.model_id ?? quote.route?.tier ?? "",
  };
}

/** Starts the render through the existing create route; returns the job id. */
export async function startPlan(
  plan: Pick<PresetPlan, "route" | "body">,
  options?: RequestOptions,
): Promise<string> {
  if (plan.route === "jobs") {
    const job = await apiRequest<{ job_id: string }>("/jobs", { method: "POST", body: plan.body, options });
    return job.job_id;
  }
  const generation = await apiRequest<{ id?: string; job_id?: string; generation_id?: string }>(
    "/generation/broll/generate",
    { method: "POST", body: plan.body, options },
  );
  return String(generation.generation_id ?? generation.job_id ?? generation.id ?? "");
}

export function recordRun(
  id: string,
  body: { job_id: string; opened_at: string },
  options?: RequestOptions,
): Promise<{ job_id: string }> {
  const pid = encodeURIComponent(id);
  return apiRequest(`/presets/shelf/${pid}/runs`, { method: "POST", body, options });
}

export function getRun(jobId: string, options?: RequestOptions): Promise<PresetRunView> {
  const jid = encodeURIComponent(jobId);
  return apiRequest<PresetRunView>(`/presets/runs/${jid}`, { options });
}

/** "2 min 14 s" / "48 s". */
export function formatSeconds(total: number): string {
  const s = Math.max(0, Math.round(total));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m} min ${s % 60} s` : `${s} s`;
}
