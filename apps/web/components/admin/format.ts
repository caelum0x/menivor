import { JobState } from "@/lib/types";

/** Best-effort locale timestamp; falls back to the raw value / em dash. */
export function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** Human label for an integer job state (see `JobState`). */
export function jobStateLabel(state: number | null): string {
  switch (state) {
    case JobState.Complete:
      return "Complete";
    case JobState.Failed:
      return "Failed";
    case JobState.Processing:
      return "Processing";
    case null:
    case undefined:
      return "—";
    default:
      return `State ${state}`;
  }
}
