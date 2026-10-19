/**
 * Typed client for the AI-film planner — Expo. Decompose a beat sheet + a
 * character into an identity-locked shot list + execution DAG. Mirrors the web
 * `src/features/film/api.ts`.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";

export interface BeatIn {
  scene_id: string;
  summary: string;
  weight?: number;
  dialogue?: string;
}

export interface CharacterIn {
  character_id: string;
  name: string;
  descriptors?: string[];
  style?: string;
}

export interface PlannedShot {
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
  shots: PlannedShot[];
}

/**
 * The beat-sheet + character + sizing inputs shared by the DB-free `/film/plan`
 * preview and the persisted `/film/projects` create. Mirrors the API's
 * `FilmPlanBody` (see `apps/api/app/domains/film/router.py`).
 */
export interface FilmPlanBody {
  beats: BeatIn[];
  character: CharacterIn;
  total_shots?: number;
  target_runtime_s?: number;
}

export function planFilm(
  body: FilmPlanBody,
  options?: RequestOptions,
): Promise<FilmPlan> {
  return request<FilmPlan>("/film/plan", { method: "POST", body, options });
}

// ---------------------------------------------------------------------------
// Wave-2 additive: plan → persist project → shots (owner-scoped, DB-backed).
// The create/get endpoints return 503 when the API's DB layer is absent and
// 404 for a non-owner project. Auth flows through `options.token` (x-api-key).
// ---------------------------------------------------------------------------

/**
 * Request body for `POST /film/projects` — a {@link FilmPlanBody} plus the
 * human-facing project `title`. Mirrors the API's `CreateProjectBody`.
 */
export interface CreateProjectBody extends FilmPlanBody {
  title: string;
}

/**
 * The lightweight summary returned by `POST /film/projects` after the plan is
 * computed and persisted (project row + one locked shot row per planned shot).
 */
export interface FilmProjectSummary {
  id: string;
  title: string;
  status: string;
  shot_count: number;
  total_runtime_s: number;
}

/** One persisted, identity-locked shot row of a film project. */
export interface FilmProjectShot {
  shot_id: string;
  order: number;
  role: string;
  camera_motion: string;
  duration_ms: number;
  prompt: string;
  seed: number;
  status: string;
  /** Render-job id of this shot's latest render, once one was started. */
  render_job_id?: string | null;
  /** Latest render-job state folded in by the API (e.g. "COMPLETED"). */
  render_state?: string;
  output_refs?: string[];
  /** Presigned, playable URLs for the shot render outputs. */
  output_urls?: string[];
}

/** Final stitched export lifecycle: '' (never exported) | queued | running | done | failed. */
export type FilmExportState = "" | "queued" | "running" | "done" | "failed";

/** A persisted film project with its ordered shot list (owner-scoped read). */
export interface FilmProject {
  id: string;
  title: string;
  status: string;
  total_runtime_s: number;
  shots: FilmProjectShot[];
  export_state?: FilmExportState | string;
  export_error?: string;
  /** Presigned URL of the stitched final MP4, once exported. */
  final_url?: string | null;
  /** Presigned URL with a download filename (Content-Disposition). */
  final_download_url?: string | null;
  exported_at?: string | null;
  /** Server truth: every shot is done and no export is in flight. */
  can_export?: boolean;
}

/** A row of `GET /film/projects` (newest first). */
export interface FilmProjectListItem extends FilmProjectSummary {
  created_at?: string | null;
  export_state?: FilmExportState | string;
}

/** Body for the project-scoped shot render calls (all fields optional). */
export interface FilmRenderBody {
  backend?: string;
  max_cost_micros?: number;
  workspace_id?: string;
}

export interface FilmShotRenderStart {
  shot_id: string;
  render_job_id: string;
  state: string;
}

export interface FilmProjectRenderResult {
  started: FilmShotRenderStart[];
  error: string | null;
}

/** Response of `POST /film/projects/{id}/export`. */
export interface FilmExportStart {
  project_id?: string;
  export_state: FilmExportState | string;
  status?: string;
  export_error?: string;
  final_url?: string | null;
}

/**
 * Plan + persist a film project via `POST /film/projects`.
 *
 * The `idempotencyKey` is sent as the `Idempotency-Key` header so an ambiguous
 * transport retry cannot create two projects for the same submission. The
 * endpoint returns 503 when the API's persistence layer is unavailable.
 */
export function createFilmProject(
  body: CreateProjectBody,
  idempotencyKey: string,
  options?: RequestOptions,
): Promise<FilmProjectSummary> {
  return request<FilmProjectSummary>("/film/projects", {
    method: "POST",
    body,
    options: { ...options, idempotencyKey },
  });
}

/**
 * Read a persisted film project + its shots via `GET /film/projects/{id}`.
 *
 * Owner-scoped: the API returns 404 for a project the caller does not own and
 * 503 when persistence is unavailable. The `projectId` is URL-encoded.
 */
export function getFilmProject(
  projectId: string,
  options?: RequestOptions,
): Promise<FilmProject> {
  return request<FilmProject>(
    `/film/projects/${encodeURIComponent(projectId)}`,
    { options },
  );
}

/** Parse "scene_id | summary" lines into BeatIn[]. */
export function parseBeatLines(text: string): BeatIn[] {
  return text
    .split("\n")
    .map((line, i) => {
      const [sceneId = "", ...rest] = line.split("|");
      const summary = rest.join("|").trim();
      return { scene_id: sceneId.trim() || `scene_${i + 1}`, summary: summary || sceneId.trim() };
    })
    .filter((b) => b.summary.length > 0);
}

/** `GET /film/projects` — the caller's saved film projects, newest first. */
export async function listFilmProjects(
  options?: RequestOptions,
): Promise<FilmProjectListItem[]> {
  const data = await request<FilmProjectListItem[] | { projects?: FilmProjectListItem[] }>(
    "/film/projects",
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.projects ?? [];
}

/**
 * `POST /film/projects/{id}/shots/{shot_id}/render` — render one shot through
 * the project so the shot row tracks its render job (and the project learns
 * when every shot is done). Wallet-metered; 409 when already rendering/done.
 */
export function renderFilmShot(
  projectId: string,
  shotId: string,
  body: FilmRenderBody = {},
  options?: RequestOptions,
): Promise<FilmShotRenderStart> {
  return request<FilmShotRenderStart>(
    `/film/projects/${encodeURIComponent(projectId)}/shots/${encodeURIComponent(shotId)}/render`,
    { method: "POST", body, options },
  );
}

/**
 * `POST /film/projects/{id}/render` — start a render for every pending shot.
 * Stops at the first wallet/backend error and reports what was started, so a
 * partially funded film can be topped up and resumed with the same call.
 */
export function renderFilmProject(
  projectId: string,
  body: FilmRenderBody = {},
  options?: RequestOptions,
): Promise<FilmProjectRenderResult> {
  return request<FilmProjectRenderResult>(
    `/film/projects/${encodeURIComponent(projectId)}/render`,
    { method: "POST", body, options },
  );
}

/**
 * `POST /film/projects/{id}/export` — stitch every finished shot render into
 * one final MP4 (server-side ffmpeg). Poll {@link getFilmProject} until
 * `export_state` is `done` (then `final_url` is playable) or `failed`.
 */
export function exportFilmProject(
  projectId: string,
  options?: RequestOptions,
): Promise<FilmExportStart> {
  return request<FilmExportStart>(
    `/film/projects/${encodeURIComponent(projectId)}/export`,
    { method: "POST", options },
  );
}

/** `PATCH /film/projects/{id}` — rename a project. */
export function renameFilmProject(
  projectId: string,
  title: string,
  options?: RequestOptions,
): Promise<FilmProjectSummary> {
  return request<FilmProjectSummary>(`/film/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    body: { title: title.trim() },
    options,
  });
}

/** `DELETE /film/projects/{id}` — delete a project and its shot rows. */
export function deleteFilmProject(
  projectId: string,
  options?: RequestOptions,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/film/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
    options,
  });
}

/** Whether a film export is still in flight. */
export function isExportPending(state: string | undefined): boolean {
  return state === "queued" || state === "running";
}
