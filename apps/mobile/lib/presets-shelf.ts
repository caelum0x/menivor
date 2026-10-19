/**
 * Preset shelf client — Expo mirror of apps/web/src/features/presets-shelf/api.ts.
 * Backs the mobile "one preset, one input, one button" flow (MH2 backend,
 * `app/domains/presets_hub`): tap a preset tile, type a topic (or attach an
 * already-uploaded photo), see the price, make it, then poll the same job the
 * normal Create flow produces.
 *
 *   GET  /presets/shelf                 public, the tile list
 *   GET  /presets/shelf/{id}            public, one tile
 *   POST /presets/shelf/{id}/plan       signed in: resolve subject/image/brand/character into a Create body
 *   POST /jobs/quote                    signed in: price a standard-credit plan
 *   POST /jobs/quote/preset             signed in: price an AI-video-credit plan
 *   POST /jobs | /generation/broll/generate   signed in: start the render through the normal create route
 *   POST /presets/shelf/{id}/runs       signed in: stamp the tap time on the caller's job
 *   GET  /presets/runs/{job_id}         signed in: tap-to-first-result timing
 *
 * Money only ever moves through the existing, already-tested `/jobs*` routes —
 * this client just prices and starts the same plans the web shelf uses.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

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

export interface PresetQuote {
  readonly credits: number;
  readonly affordable: boolean;
  readonly route?: string;
}

/** GET /presets/shelf — the public tile list (no sign-in needed to browse). */
export async function listShelf(options?: RequestOptions): Promise<readonly PresetTile[]> {
  const data = await request<{ presets: PresetTile[] }>("/presets/shelf", { options });
  return data.presets ?? [];
}

/** GET /presets/shelf/{id} — one public tile. */
export function getTile(id: string, options?: RequestOptions): Promise<PresetTile> {
  const pid = encodeURIComponent(id);
  return request<PresetTile>(`/presets/shelf/${pid}`, { options });
}

/** POST /presets/shelf/{id}/plan — resolve the tapped tile + inputs into the Create body. */
export function planPreset(
  id: string,
  body: { subject: string; image_key?: string; brand_kit_id?: string; character_id?: string },
  options?: RequestOptions,
): Promise<PresetPlan> {
  const pid = encodeURIComponent(id);
  return request<PresetPlan>(`/presets/shelf/${pid}/plan`, { method: "POST", body, options });
}

/** The same price-first call for any resolved plan (standard route vs AI-video preset route). */
export async function quoteForPlan(
  plan: Pick<PresetPlan, "route" | "body">,
  animatesImage: boolean,
  options?: RequestOptions,
): Promise<PresetQuote> {
  if (plan.route === "jobs") {
    const quote = await request<{ total: CreditTotals; affordable: boolean }>("/jobs/quote", {
      method: "POST",
      body: plan.body,
      options,
    });
    return { credits: quote.total?.standard ?? 0, affordable: Boolean(quote.affordable) };
  }
  const quote = await request<{ total: CreditTotals; affordable: boolean; route?: { model_id?: string; tier?: string } }>(
    "/jobs/quote/preset",
    { method: "POST", body: { preset_sku: animatesImage ? "animate_image" : "text_to_video", tier: "draft", seconds: 5 }, options },
  );
  return {
    credits: quote.total?.ai_video ?? 0,
    affordable: Boolean(quote.affordable),
    route: quote.route?.model_id ?? quote.route?.tier ?? "",
  };
}

/** Price before render: standard presets via /jobs/quote, model presets via /jobs/quote/preset. */
export function quotePlan(
  tile: PresetTile,
  plan: PresetPlan,
  options?: RequestOptions,
): Promise<PresetQuote> {
  return quoteForPlan(plan, tile.inputs.includes("image"), options);
}

/** Starts the render through the existing create route; returns the job id. */
export async function startPlan(
  plan: Pick<PresetPlan, "route" | "body">,
  options?: RequestOptions,
): Promise<string> {
  if (plan.route === "jobs") {
    const job = await request<{ job_id: string }>("/jobs", { method: "POST", body: plan.body, options });
    return job.job_id;
  }
  const generation = await request<{ id?: string; job_id?: string; generation_id?: string }>(
    "/generation/broll/generate",
    { method: "POST", body: plan.body, options },
  );
  return String(generation.generation_id ?? generation.job_id ?? generation.id ?? "");
}

/** POST /presets/shelf/{id}/runs — stamp the tap time on the just-started job. */
export function recordRun(
  id: string,
  body: { job_id: string; opened_at: string },
  options?: RequestOptions,
): Promise<{ job_id: string }> {
  const pid = encodeURIComponent(id);
  return request(`/presets/shelf/${pid}/runs`, { method: "POST", body, options });
}

/** GET /presets/runs/{job_id} — tap-to-first-result timing for a preset run. */
export function getRun(jobId: string, options?: RequestOptions): Promise<PresetRunView> {
  const jid = encodeURIComponent(jobId);
  return request<PresetRunView>(`/presets/runs/${jid}`, { options });
}

/** "2 min 14 s" / "48 s". */
export function formatSeconds(total: number): string {
  const s = Math.max(0, Math.round(total));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m} min ${s % 60} s` : `${s} s`;
}
