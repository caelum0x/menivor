/**
 * Film Studio API client — plan a shot list (preview), persist it as a
 * project, list / rename / delete projects, render shots (wallet-metered) and
 * stitch the finished shots into one final video, all over the shared
 * authenticated transport.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";

export interface Beat {
  scene_id: string;
  summary: string;
  weight?: number;
  dialogue?: string;
}

export interface Character {
  character_id: string;
  name: string;
  descriptors?: string[];
  style?: string;
}

export interface PlanFilmBody {
  beats: Beat[];
  character: Character;
  total_shots?: number;
  target_runtime_s?: number;
}

export interface Shot {
  shot_id: string;
  scene_id: string;
  order: number;
  role: string;
  camera_motion: string;
  duration_s: number;
  prompt: string;
  seed: number;
}

export interface FilmPlan {
  total_runtime_s: number;
  node_order: string[];
  shots: Shot[];
}

export function planFilm(body: PlanFilmBody, options?: RequestOptions): Promise<FilmPlan> {
  return apiRequest<FilmPlan>("/film/plan", { method: "POST", body, options });
}

/** Body for POST /film/projects — a plan body plus a display title. */
export interface CreateProjectBody extends PlanFilmBody {
  title?: string;
}

/** Summary returned by POST /film/projects and GET /film/projects rows. */
export interface FilmProjectSummary {
  id: string;
  title: string;
  status: string;
  shot_count: number;
  total_runtime_s: number;
  created_at?: string | null;
  export_state?: string | null;
  has_final?: boolean;
}

/** One persisted shot row from GET /film/projects/{id}. */
export interface ProjectShot {
  shot_id: string;
  order: number;
  role: string;
  camera_motion: string;
  duration_ms: number;
  prompt: string;
  seed: number;
  status: string;
  render_job_id?: string | null;
  /** Envelope state of the shot's render job (IN_QUEUE … COMPLETED). */
  render_state?: string;
  render_error?: string | null;
  output_refs?: string[];
  /** Presigned / public URLs a browser can play. */
  output_urls?: string[];
  unusable_output_refs?: number;
}

/** Final-export state of a film: "" | queued | running | done | failed. */
export type FilmExportState = "queued" | "running" | "done" | "failed";

/** Full project detail returned by GET /film/projects/{id}. */
export interface FilmProject {
  id: string;
  title: string;
  status: string;
  total_runtime_s: number;
  shots: ProjectShot[];
  created_at?: string | null;
  updated_at?: string | null;
  /** True when every shot is rendered and no export is in flight. */
  can_export?: boolean;
  export_state?: FilmExportState | null;
  export_error?: string | null;
  exported_at?: string | null;
  /** Presigned URL of the stitched final video (export_state === "done"). */
  final_url?: string | null;
  /** Presigned URL that downloads the final video as `<title>.mp4`. */
  final_download_url?: string | null;
}

/**
 * Plan + persist a film project. Sends an `Idempotency-Key` so an ambiguous
 * transport retry never creates two projects for the same submission.
 */
export function createProject(
  body: CreateProjectBody,
  options?: RequestOptions,
): Promise<FilmProjectSummary> {
  return apiRequest<FilmProjectSummary>("/film/projects", {
    method: "POST",
    body,
    options,
  });
}

/** Load a persisted project (with its locked shot rows) by id. */
export function getProject(
  projectId: string,
  options?: RequestOptions,
): Promise<FilmProject> {
  return apiRequest<FilmProject>(
    `/film/projects/${encodeURIComponent(projectId)}`,
    { options },
  );
}

/** GET /film/projects — the caller's film projects, newest first. */
export async function listProjects(
  params: { limit?: number; offset?: number } = {},
  options?: RequestOptions,
): Promise<FilmProjectSummary[]> {
  const search = new URLSearchParams({
    limit: String(params.limit ?? 50),
    offset: String(params.offset ?? 0),
  });
  const data = await apiRequest<FilmProjectSummary[] | { projects?: FilmProjectSummary[] }>(
    `/film/projects?${search.toString()}`,
    { options },
  );
  return Array.isArray(data) ? data : (data?.projects ?? []);
}

/** PATCH /film/projects/{id} — rename a project. */
export function renameProject(
  projectId: string,
  title: string,
  options?: RequestOptions,
): Promise<Pick<FilmProjectSummary, "id" | "title" | "status">> {
  return apiRequest<Pick<FilmProjectSummary, "id" | "title" | "status">>(`/film/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    body: { title },
    options,
  });
}

export interface FilmDeleteResult {
  deleted: boolean;
  id: string;
  cancelled_renders?: number;
}

/** DELETE /film/projects/{id} — cancel + refund in-flight shots, then delete. */
export function deleteProject(
  projectId: string,
  options?: RequestOptions,
): Promise<FilmDeleteResult> {
  return apiRequest<FilmDeleteResult>(`/film/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
    options,
  });
}

/** Spend options for a shot render (wallet hold per shot). */
export interface RenderShotBody {
  backend?: string;
  max_cost_micros?: number;
  workspace_id?: string | null;
  /** Re-render a shot that already finished (a new take). */
  rerender?: boolean;
}

export interface StartedShot {
  shot_id: string;
  render_job_id: string;
  state: string;
}

/** POST /film/projects/{id}/shots/{shotId}/render — render one shot. */
export function renderShot(
  projectId: string,
  shotId: string,
  body: RenderShotBody = {},
  options?: RequestOptions,
): Promise<StartedShot> {
  return apiRequest<StartedShot>(
    `/film/projects/${encodeURIComponent(projectId)}/shots/${encodeURIComponent(shotId)}/render`,
    { method: "POST", body, options },
  );
}

export interface RenderAllResult {
  started: StartedShot[];
  /** Shots still pending after this call (e.g. the wallet ran out). */
  remaining?: number;
  error?: string | null;
}

/** POST /film/projects/{id}/render — render every shot not yet rendering/done. */
export function renderAllShots(
  projectId: string,
  body: RenderShotBody = {},
  options?: RequestOptions,
): Promise<RenderAllResult> {
  return apiRequest<RenderAllResult>(
    `/film/projects/${encodeURIComponent(projectId)}/render`,
    { method: "POST", body, options },
  );
}

/** POST /film/projects/{id}/export — stitch every finished shot into one MP4. */
export function exportFilm(
  projectId: string,
  options?: RequestOptions,
): Promise<unknown> {
  return apiRequest<unknown>(`/film/projects/${encodeURIComponent(projectId)}/export`, {
    method: "POST",
    options,
  });
}

/** Browser-playable URLs for a shot's render output. */
export function shotOutputUrls(shot: Pick<ProjectShot, "output_urls" | "output_refs">): string[] {
  if (Array.isArray(shot.output_urls)) return shot.output_urls;
  return (shot.output_refs ?? []).filter((ref) => /^https?:\/\//i.test(ref));
}

/** Generate an Idempotency-Key for a create-project submission. */
export function newIdempotencyKey(): string {
  const g = globalThis as { crypto?: { randomUUID?: () => string } };
  if (g.crypto?.randomUUID) return g.crypto.randomUUID();
  return `film-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
