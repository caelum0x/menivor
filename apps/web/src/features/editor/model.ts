import type { Job } from "@/lib/types";
import { isFailedState, isTerminalState } from "@/lib/types";
import { jobResultUrl, jobThumbnailUrl } from "@/lib/job-media";

export interface EditorSource {
  jobId: string;
  state: Job["state"];
  progress: number;
  resultUrl?: string;
  posterUrl?: string;
  correlationId?: string;
  failed: boolean;
  terminal: boolean;
  error?: string;
}

export interface CutRange {
  inPoint: number;
  outPoint: number;
  duration: number;
}

export function mapJobToEditorSource(job: Job): EditorSource {
  return {
    jobId: job.job_id,
    state: job.state,
    progress: job.progress,
    resultUrl: jobResultUrl(job),
    posterUrl: jobThumbnailUrl(job),
    correlationId: job.correlation_id,
    failed: isFailedState(job.state),
    terminal: isTerminalState(job.state),
    error: job.error,
  };
}

export function normalizeCutRange(
  inPoint: number,
  outPoint: number,
  duration: number,
  minimumLength = 0.1,
): CutRange {
  const safeDuration = Number.isFinite(duration) ? Math.max(0, duration) : 0;
  const safeIn = Math.min(Math.max(0, inPoint), Math.max(0, safeDuration - minimumLength));
  const safeOut = Math.min(
    safeDuration,
    Math.max(safeIn + minimumLength, outPoint),
  );
  return { inPoint: safeIn, outPoint: safeOut, duration: safeOut - safeIn };
}

export function formatTimecode(seconds: number): string {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const minutes = Math.floor(safe / 60);
  const remaining = safe - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${remaining.toFixed(2).padStart(5, "0")}`;
}
