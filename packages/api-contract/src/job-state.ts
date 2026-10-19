export const JobState = {
  Failed: -1,
  Complete: 1,
  Processing: 4,
} as const;

export type JobStateValue = number;
export type KnownJobState = (typeof JobState)[keyof typeof JobState];

export function isTerminalJobState(state: JobStateValue): boolean {
  return state === JobState.Complete || state === JobState.Failed;
}

export function isFailedJobState(state: JobStateValue): boolean {
  return state === JobState.Failed;
}

export type GenerationPhase =
  | "queued"
  | "running"
  | "completed"
  | "failed";

export function generationPhase(
  state: JobStateValue,
  progress: number,
): GenerationPhase {
  if (state === JobState.Complete) return "completed";
  if (state === JobState.Failed) return "failed";
  return progress > 0 ? "running" : "queued";
}
