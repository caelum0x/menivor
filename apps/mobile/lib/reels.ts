/**
 * Presentation + filtering helpers for the Reels ([jobs]) surfaces — the Reels
 * library, the rich reel detail, and the schedule manager.
 *
 * The wire calls themselves (GET /jobs, GET /jobs/{id}, POST /jobs/{id}/retry |
 * /rerun | /dub | /schedule | /cover | /broll/suggest | /social, GET/DELETE
 * /me/scheduled) already have typed client functions in {@link module:lib/api};
 * this module only adds the pure, typed domain helpers the screens layer on top
 * so the components stay lean. Everything here is side-effect free.
 */

import {
  JobState,
  isFailedState,
  isTerminalState,
  type Job,
  type JobStateValue,
  type ScheduledPublish,
  type ScheduleStatus,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Job status filtering (Reels library)
// ---------------------------------------------------------------------------

/** The status buckets a creator can filter their reels by. */
export type ReelStatusFilterId = "all" | "processing" | "complete" | "failed";

export interface ReelStatusFilter {
  readonly id: ReelStatusFilterId;
  readonly label: string;
}

/** The library filter chips, in display order. */
export const REEL_STATUS_FILTERS: readonly ReelStatusFilter[] = [
  { id: "all", label: "All" },
  { id: "processing", label: "Processing" },
  { id: "complete", label: "Complete" },
  { id: "failed", label: "Failed" },
];

/** Whether a job belongs to the given status bucket. */
export function jobMatchesStatusFilter(
  job: Job,
  filter: ReelStatusFilterId,
): boolean {
  switch (filter) {
    case "all":
      return true;
    case "complete":
      return job.state === JobState.Complete;
    case "failed":
      return isFailedState(job.state);
    case "processing":
      return !isTerminalState(job.state);
    default:
      return true;
  }
}

/** A human label for a raw integer job state. */
export function jobStateLabel(state: JobStateValue): string {
  if (state === JobState.Complete) return "Complete";
  if (isFailedState(state)) return "Failed";
  return "Processing";
}

/**
 * Count how many jobs fall into each library filter bucket, for the chip
 * badges. Runs in a single pass.
 */
export function summarizeJobsByStatus(
  jobs: readonly Job[],
): Record<ReelStatusFilterId, number> {
  const counts: Record<ReelStatusFilterId, number> = {
    all: jobs.length,
    processing: 0,
    complete: 0,
    failed: 0,
  };
  for (const job of jobs) {
    if (job.state === JobState.Complete) counts.complete += 1;
    else if (isFailedState(job.state)) counts.failed += 1;
    else counts.processing += 1;
  }
  return counts;
}

/**
 * Short, human display label for a reel derived from its persisted brief. Falls
 * back to the job id when no hook/subject is present yet.
 */
export function reelTitle(job: Job): string {
  const hook = (job.hook ?? "").trim();
  if (hook) return hook;
  return job.job_id;
}

/** Friendly local date for an ISO timestamp, e.g. "Sep 8". Blank when absent. */
export function formatReelDate(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  try {
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

// ---------------------------------------------------------------------------
// Scheduled-publish filtering (Schedule manager)
// ---------------------------------------------------------------------------

/** The schedule filter chips (an "all" pseudo-status plus the real ones). */
export type ScheduleStatusFilterId = "all" | ScheduleStatus;

export interface ScheduleStatusFilter {
  readonly id: ScheduleStatusFilterId;
  readonly label: string;
}

export const SCHEDULE_STATUS_FILTERS: readonly ScheduleStatusFilter[] = [
  { id: "all", label: "All" },
  { id: "pending", label: "Pending" },
  { id: "publishing", label: "Publishing" },
  { id: "published", label: "Published" },
  { id: "failed", label: "Failed" },
  { id: "canceled", label: "Canceled" },
];

/** Whether a scheduled publish belongs to the given filter bucket. */
export function scheduleMatchesFilter(
  schedule: ScheduledPublish,
  filter: ScheduleStatusFilterId,
): boolean {
  if (filter === "all") return true;
  return schedule.status === filter;
}

/** Count scheduled publishes per filter bucket, in one pass. */
export function summarizeSchedulesByStatus(
  schedules: readonly ScheduledPublish[],
): Record<ScheduleStatusFilterId, number> {
  const counts: Record<ScheduleStatusFilterId, number> = {
    all: schedules.length,
    pending: 0,
    publishing: 0,
    published: 0,
    failed: 0,
    canceled: 0,
  };
  for (const schedule of schedules) {
    const status = schedule.status as ScheduleStatusFilterId;
    if (status in counts && status !== "all") counts[status] += 1;
  }
  return counts;
}

/** A signal color for a schedule lifecycle status. */
export function scheduleStatusColor(status: string): string {
  switch (status) {
    case "published":
      return "#5DB585";
    case "failed":
      return "#D0605B";
    case "canceled":
      return "#9b978d";
    case "publishing":
      return "#E6C76A";
    case "pending":
    default:
      return "#A49CE0";
  }
}

/** Only still-`pending` schedules can be canceled by the owner. */
export function scheduleIsCancelable(schedule: ScheduledPublish): boolean {
  return schedule.status === "pending";
}

/** Friendly local date-time for a scheduled instant, e.g. "Sep 8, 2:30 PM". */
export function formatScheduleTime(iso?: string | null): string {
  if (!iso) return "Time not set";
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

/** A readable platforms line, e.g. "TikTok, Instagram". */
export function formatPlatforms(platforms: readonly string[]): string {
  if (platforms.length === 0) return "No platforms";
  return platforms
    .map((p) =>
      p
        .split("_")
        .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
        .join(" "),
    )
    .join(", ");
}
