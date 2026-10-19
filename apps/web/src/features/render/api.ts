/** Async-GPU render jobs — start, status, advance, cancel, history (wallet-metered). */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface RenderJob {
  id: string;
  backend: string;
  state: string;
  progress: number;
  provider_ref: string;
  output_refs: string[];
  cost_micros: number;
  error: string;
  /** Browser-usable (presigned / public) URLs for the outputs. */
  output_urls?: string[];
  /** Outputs that exist but cannot be served to a browser (e.g. LAN-only). */
  unusable_output_refs?: number;
  created_at?: string | null;
  updated_at?: string | null;
  /** Short title recorded at start (defaults to the prompt). */
  label?: string;
  /** `render` for the render panel, `film` for film shots. */
  source?: string;
  held_cost_micros?: number;
  actual_cost_micros?: number;
}

export interface StartRenderBody {
  backend: string;
  spec: Record<string, unknown>;
  max_cost_micros: number;
  workflow_version?: string;
  workspace_id?: string | null;
  /** Short title stored with the render for the history list. */
  label?: string;
}

export function startRender(body: StartRenderBody, options?: RequestOptions): Promise<RenderJob> {
  return apiRequest<RenderJob>("/render/jobs", { method: "POST", body, options });
}

export function getRender(jobId: string, options?: RequestOptions): Promise<RenderJob> {
  return apiRequest<RenderJob>(`/render/jobs/${encodeURIComponent(jobId)}`, { options });
}

export function advanceRender(jobId: string, options?: RequestOptions): Promise<RenderJob> {
  return apiRequest<RenderJob>(`/render/jobs/${encodeURIComponent(jobId)}/advance`, {
    method: "POST",
    options,
  });
}

export function cancelRender(jobId: string, options?: RequestOptions): Promise<RenderJob> {
  return apiRequest<RenderJob>(`/render/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
    options,
  });
}

export interface RenderHistoryPage {
  jobs: RenderJob[];
  total: number;
  hasMore: boolean;
}

/** GET /render/jobs — the caller's render history (newest first, owner-scoped). */
export async function listRenders(
  params: { limit?: number; offset?: number; source?: "render" | "film" } = {},
  options?: RequestOptions,
): Promise<RenderHistoryPage> {
  const search = new URLSearchParams();
  search.set("limit", String(params.limit ?? 30));
  search.set("offset", String(params.offset ?? 0));
  if (params.source) search.set("source", params.source);
  const data = await apiRequest<
    RenderJob[] | { jobs?: RenderJob[]; total?: number; has_more?: boolean }
  >(`/render/jobs?${search.toString()}`, { options });
  if (Array.isArray(data)) {
    return { jobs: data, total: data.length, hasMore: false };
  }
  const jobs = data?.jobs ?? [];
  return {
    jobs,
    total: typeof data?.total === "number" ? data.total : jobs.length,
    hasMore: Boolean(data?.has_more),
  };
}

/** URLs a browser can play/download: server-signed URLs, else absolute refs. */
export function playableOutputs(job: Pick<RenderJob, "output_refs" | "output_urls">): string[] {
  if (Array.isArray(job.output_urls)) return job.output_urls;
  return (job.output_refs ?? []).filter((ref) => /^https?:\/\//i.test(ref));
}
