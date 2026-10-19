/** Unified async job envelope (mirror of `envelope.py`). */

export const STATES = ["IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED"] as const;
export type JobState = (typeof STATES)[number];

/** Collapse a provider's raw status string to the canonical state. */
export function normalizeState(raw: string): JobState {
  const s = (raw || "").trim().toUpperCase();
  if (["IN_QUEUE", "QUEUED", "PENDING", "STARTING", "CREATED", "SUBMITTED"].includes(s)) return "IN_QUEUE";
  if (["IN_PROGRESS", "RUNNING", "PROCESSING", "EXECUTING", "DREAMING", "THROTTLED"].includes(s)) return "IN_PROGRESS";
  if (["COMPLETED", "COMPLETE", "SUCCEEDED", "SUCCESS", "FINISHED"].includes(s)) return "COMPLETED";
  if (["FAILED", "ERROR", "TIMED_OUT", "CRASHED"].includes(s)) return "FAILED";
  if (["CANCELLED", "CANCELED", "ABORTED"].includes(s)) return "CANCELLED";
  return "IN_PROGRESS"; // unknown but live
}

export function isTerminal(state: string): boolean {
  return state === "COMPLETED" || state === "FAILED" || state === "CANCELLED";
}

export interface NormalizedUsage {
  units: number;
  cost_micros: number;
  success: boolean;
}

/** Success-only billing: cost is carried only when the run succeeded. */
export function normalizedUsage(units: number, costMicros: number, success: boolean): NormalizedUsage {
  return {
    units,
    cost_micros: success ? Math.trunc(costMicros) : 0,
    success,
  };
}
