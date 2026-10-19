/**
 * Pure, framework-free helpers for the Reels library: state filtering,
 * free-text search, newest-first sorting, and pagination over the rows loaded
 * so far. The library pages through `GET /jobs?limit&offset` (load older
 * reels on demand); filtering + display paging happen here over that set.
 */

import { JobState, isFailedState, isTerminalState, type Job } from "@/lib/types";

/** The state buckets a creator can filter their reel library by. */
export type ReelFilter =
  | "all"
  | "queued"
  | "processing"
  | "complete"
  | "failed"
  | "archived";

export const REEL_FILTERS: readonly { value: ReelFilter; label: string }[] = [
  { value: "all", label: "All reels" },
  { value: "processing", label: "Processing" },
  { value: "queued", label: "Queued" },
  { value: "complete", label: "Complete" },
  { value: "failed", label: "Failed" },
  { value: "archived", label: "Archived" },
];

/** True when the job belongs to the given filter bucket. */
export function matchesFilter(job: Readonly<Job>, filter: ReelFilter): boolean {
  // Archived reels only show in their own bucket, never in the live views.
  if (filter === "archived") return Boolean(job.archived);
  if (job.archived) return false;
  switch (filter) {
    case "all":
      return true;
    case "complete":
      return isTerminalState(job.state) && !isFailedState(job.state);
    case "failed":
      return isFailedState(job.state);
    case "processing":
      return job.state === JobState.Processing;
    case "queued":
      // Anything not yet terminal and not actively processing is still queued.
      return !isTerminalState(job.state) && job.state !== JobState.Processing;
    default:
      return true;
  }
}

/** Case-insensitive match against the job id, title and hook/opening line. */
export function matchesQuery(job: Readonly<Job>, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystacks = [job.job_id, job.title, job.hook, job.language, job.failed_stage];
  return haystacks.some((value) =>
    typeof value === "string" && value.toLowerCase().includes(q),
  );
}

/** Milliseconds since epoch for a job's created_at, or 0 when absent/invalid. */
function createdAtMs(job: Readonly<Job>): number {
  if (!job.created_at) return 0;
  const t = Date.parse(job.created_at);
  return Number.isNaN(t) ? 0 : t;
}

/** Sort comparator: newest reels first (undated rows sink to the bottom). */
export function byNewest(a: Readonly<Job>, b: Readonly<Job>): number {
  return createdAtMs(b) - createdAtMs(a);
}

/** Count how many jobs fall into each filter bucket (for filter labels). */
export function countByFilter(
  jobs: readonly Job[],
): Record<ReelFilter, number> {
  return {
    all: jobs.filter((j) => matchesFilter(j, "all")).length,
    processing: jobs.filter((j) => matchesFilter(j, "processing")).length,
    queued: jobs.filter((j) => matchesFilter(j, "queued")).length,
    complete: jobs.filter((j) => matchesFilter(j, "complete")).length,
    failed: jobs.filter((j) => matchesFilter(j, "failed")).length,
    archived: jobs.filter((j) => matchesFilter(j, "archived")).length,
  };
}

/** Apply filter + query + newest-first sort in one pass. */
export function selectReels(
  jobs: readonly Job[],
  filter: ReelFilter,
  query: string,
): Job[] {
  return jobs
    .filter((job) => matchesFilter(job, filter) && matchesQuery(job, query))
    .sort(byNewest);
}

export interface PageResult<T> {
  /** The slice of items on the requested (clamped) page. */
  items: readonly T[];
  /** 1-based page actually returned after clamping. */
  page: number;
  /** Total number of pages (at least 1). */
  pageCount: number;
  /** Total number of items across all pages. */
  total: number;
  /** 1-based index of the first item on this page (0 when empty). */
  from: number;
  /** 1-based index of the last item on this page (0 when empty). */
  to: number;
}

/** Clamp `page` into range and return the corresponding slice + metadata. */
export function paginate<T>(
  items: readonly T[],
  page: number,
  pageSize: number,
): PageResult<T> {
  const total = items.length;
  const size = Math.max(1, pageSize);
  const pageCount = Math.max(1, Math.ceil(total / size));
  const clamped = Math.min(Math.max(1, page), pageCount);
  const start = (clamped - 1) * size;
  const slice = items.slice(start, start + size);
  return {
    items: slice,
    page: clamped,
    pageCount,
    total,
    from: total === 0 ? 0 : start + 1,
    to: total === 0 ? 0 : start + slice.length,
  };
}

export const REEL_PAGE_SIZE = 10;
