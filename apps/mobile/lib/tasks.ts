/**
 * Typed client + domain helpers for the async task queue and reel batches — Expo.
 *
 * Two related surfaces share this module:
 *
 *   - The GENERIC async task queue (`/api/v1/tasks`, `/api/v1/tasks/{task_id}`):
 *     long-running video-generation tasks the backend tracks out-of-band from a
 *     reel Job. Each carries a live {@link TaskProgress} and a lifecycle
 *     {@link TaskStatus}; a running/pending task can be cancelled (DELETE).
 *
 *   - The REEL BATCH view (`/api/v1/batches/{batch_id}`): the N variant jobs a
 *     single `POST /jobs {variants:N}` request fanned out (they share one
 *     `batch_id`). This is what {@link module:src/features/reel-create} produces
 *     when a creator fires several variants at once.
 *
 * The task endpoints return their payload directly (a FastAPI `response_model`),
 * while the batch endpoint uses the standard `{status,data,message}` envelope;
 * {@link apiRequest} normalizes both to the resolved value here.
 *
 * Everything below the client functions is pure and side-effect free.
 */

import { apiRequest as request, type RequestOptions } from "@/src/shared/api";
import type { BatchData, BatchJobData } from "@reelforge/api-contract";

// ---------------------------------------------------------------------------
// Task wire types (mirror app/generation/tasks/models.py)
// ---------------------------------------------------------------------------

/** Lifecycle of an async task (backend `TaskStatus` enum). */
export type TaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

/** The kind of work a task performs (backend `TaskType` enum). */
export type TaskType = "video_generation";

/** Live progress counters for an in-flight task. */
export interface TaskProgress {
  current: number;
  total: number;
  /** 0–100. The backend computes this; we still clamp defensively for the UI. */
  percentage: number;
  message: string;
}

/**
 * One async task as returned by `GET /api/v1/tasks` and
 * `GET /api/v1/tasks/{task_id}`. `task_type` is kept widened to `string` so an
 * unknown future kind never fails to parse — the UI degrades to the raw label.
 */
export interface Task {
  task_id: string;
  task_type: TaskType | string;
  status: TaskStatus;
  progress?: TaskProgress | null;
  result?: unknown;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  request_params?: Record<string, unknown> | null;
}

/** Result of `DELETE /api/v1/tasks/{task_id}`. */
export interface CancelTaskResult {
  success: boolean;
  message: string;
}

/** Query filters for the task list. */
export interface ListTasksParams {
  /** Restrict to a single lifecycle status. */
  status?: TaskStatus;
  /** Server-side cap (1–1000). */
  limit?: number;
}

// Re-exported for screens that render a batch listing.
export type { BatchData, BatchJobData };

// ---------------------------------------------------------------------------
// Client functions
// ---------------------------------------------------------------------------

function buildTasksQuery(params?: ListTasksParams): string {
  if (!params) return "";
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (typeof params.limit === "number") {
    search.set("limit", String(clampLimit(params.limit)));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

function clampLimit(limit: number): number {
  if (!Number.isFinite(limit)) return 100;
  return Math.max(1, Math.min(1000, Math.trunc(limit)));
}

/**
 * GET /api/v1/tasks — the async task queue (newest first). The endpoint returns
 * the array directly; a malformed/empty body degrades to an empty list so the
 * queue screen always renders.
 */
export async function listTasks(
  params?: ListTasksParams,
  options?: RequestOptions,
): Promise<Task[]> {
  const data = await request<Task[] | { tasks?: Task[] } | null>(
    `/tasks${buildTasksQuery(params)}`,
    { options },
  );
  if (Array.isArray(data)) return data;
  return data?.tasks ?? [];
}

/** GET /api/v1/tasks/{task_id} — full detail for one task. */
export function getTask(
  taskId: string,
  options?: RequestOptions,
): Promise<Task> {
  return request<Task>(`/tasks/${encodeURIComponent(taskId)}`, { options });
}

/**
 * DELETE /api/v1/tasks/{task_id} — cancel a pending/running task. Safe to call
 * on an already-terminal task (the backend 404s an unknown id — surfaced as an
 * {@link ApiError} the caller can display).
 */
export function cancelTask(
  taskId: string,
  options?: RequestOptions,
): Promise<CancelTaskResult> {
  return request<CancelTaskResult>(`/tasks/${encodeURIComponent(taskId)}`, {
    method: "DELETE",
    options,
  });
}

/**
 * GET /api/v1/batches/{batch_id} — every variant job of a reel batch, scoped to
 * the caller. Returns `{ batch_id, jobs }`; a 404 (unknown/foreign/empty batch)
 * surfaces as an {@link ApiError}.
 */
export function getBatch(
  batchId: string,
  options?: RequestOptions,
): Promise<BatchData> {
  return request<BatchData>(`/batches/${encodeURIComponent(batchId)}`, {
    options,
  });
}

// ---------------------------------------------------------------------------
// Pure domain helpers (task queue)
// ---------------------------------------------------------------------------

/** Task lifecycle statuses that will never change again — polling can stop. */
const TERMINAL_TASK_STATUSES: readonly TaskStatus[] = [
  "completed",
  "failed",
  "cancelled",
];

/** Whether a task has reached a final state (no more polling needed). */
export function isTerminalTaskStatus(status: TaskStatus): boolean {
  return TERMINAL_TASK_STATUSES.includes(status);
}

/** Whether a task is still in flight (pending or running). */
export function isActiveTaskStatus(status: TaskStatus): boolean {
  return !isTerminalTaskStatus(status);
}

/** Only pending/running tasks can be cancelled by the owner. */
export function taskIsCancelable(task: Pick<Task, "status">): boolean {
  return isActiveTaskStatus(task.status);
}

/** Human label for a task lifecycle status. */
export function taskStatusLabel(status: TaskStatus): string {
  switch (status) {
    case "pending":
      return "Queued";
    case "running":
      return "Running";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return status;
  }
}

/** A signal color for a task lifecycle status (mirrors the reels palette). */
export function taskStatusColor(status: TaskStatus): string {
  switch (status) {
    case "completed":
      return "#5DB585";
    case "failed":
      return "#D0605B";
    case "cancelled":
      return "#9b978d";
    case "running":
      return "#A49CE0";
    case "pending":
    default:
      return "#E6C76A";
  }
}

/**
 * A 0–100 completion percentage for a task, clamped and defaulted. Falls back to
 * 0 when no progress payload is present yet.
 */
export function taskPercentage(task: Pick<Task, "progress">): number {
  const raw = task.progress?.percentage;
  if (typeof raw !== "number" || !Number.isFinite(raw)) return 0;
  return Math.max(0, Math.min(100, Math.round(raw)));
}

/** A short "3 / 8" style counter, or an empty string when totals are unknown. */
export function taskProgressCounter(task: Pick<Task, "progress">): string {
  const p = task.progress;
  if (!p || p.total <= 0) return "";
  const current = Math.max(0, Math.min(p.total, p.current));
  return `${current} / ${p.total}`;
}

/** The task filter chips a user can narrow the queue by, in display order. */
export type TaskStatusFilterId = "all" | "active" | TaskStatus;

export interface TaskStatusFilter {
  readonly id: TaskStatusFilterId;
  readonly label: string;
}

export const TASK_STATUS_FILTERS: readonly TaskStatusFilter[] = [
  { id: "all", label: "All" },
  { id: "active", label: "Active" },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed" },
  { id: "cancelled", label: "Cancelled" },
];

/** Whether a task belongs to the given filter bucket. */
export function taskMatchesFilter(
  task: Pick<Task, "status">,
  filter: TaskStatusFilterId,
): boolean {
  switch (filter) {
    case "all":
      return true;
    case "active":
      return isActiveTaskStatus(task.status);
    default:
      return task.status === filter;
  }
}

/** Count tasks per filter bucket in a single pass, for chip badges. */
export function summarizeTasksByStatus(
  tasks: readonly Task[],
): Record<TaskStatusFilterId, number> {
  const counts: Record<TaskStatusFilterId, number> = {
    all: tasks.length,
    active: 0,
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
  };
  for (const task of tasks) {
    counts[task.status] += 1;
    if (isActiveTaskStatus(task.status)) counts.active += 1;
  }
  return counts;
}

/** Friendly local date-time for an ISO instant, e.g. "Sep 8, 2:30 PM". */
export function formatTaskTime(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  try {
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** A readable task-kind label, e.g. "video_generation" -> "Video generation". */
export function taskTypeLabel(type: TaskType | string): string {
  const words = type.split(/[_\s]+/).filter(Boolean);
  if (words.length === 0) return type;
  const [first, ...rest] = words;
  return [first[0].toUpperCase() + first.slice(1), ...rest].join(" ");
}

// ---------------------------------------------------------------------------
// Pure domain helpers (reel batch)
// ---------------------------------------------------------------------------

/** Per-variant counts for a batch, used for the batch header summary. */
export interface BatchSummary {
  readonly total: number;
  readonly complete: number;
  readonly failed: number;
  readonly processing: number;
  /** 0–100 mean of the variants' progress. */
  readonly percentage: number;
  /** True once every variant has reached a terminal state. */
  readonly settled: boolean;
}

/**
 * Aggregate a batch's variant jobs into a single progress summary. `isComplete`
 * / `isFailed` are injected so this stays free of the numeric JobState import
 * and reuses the app's single source of truth from the calling screen.
 */
export function summarizeBatch(
  jobs: readonly BatchJobData[],
  predicates: {
    isComplete: (state: number) => boolean;
    isFailed: (state: number) => boolean;
    isTerminal: (state: number) => boolean;
  },
): BatchSummary {
  const total = jobs.length;
  let complete = 0;
  let failed = 0;
  let processing = 0;
  let progressSum = 0;
  let settled = 0;
  for (const job of jobs) {
    if (predicates.isComplete(job.state)) complete += 1;
    else if (predicates.isFailed(job.state)) failed += 1;
    else processing += 1;
    if (predicates.isTerminal(job.state)) settled += 1;
    progressSum += clampPercent(job.progress);
  }
  return {
    total,
    complete,
    failed,
    processing,
    percentage: total > 0 ? Math.round(progressSum / total) : 0,
    settled: total > 0 && settled === total,
  };
}

function clampPercent(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

/** Signed poster/thumbnail URL for a batch variant, when already absolute. */
export function batchJobPosterUrl(job: BatchJobData): string | undefined {
  return absoluteUrl(job.poster_url) ?? absoluteUrl(job.poster_key);
}

/** Signed final-result URL for a batch variant, when present. */
export function batchJobResultUrl(job: BatchJobData): string | undefined {
  return absoluteUrl(job.result_url);
}

function absoluteUrl(value?: string | null): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : undefined;
}
