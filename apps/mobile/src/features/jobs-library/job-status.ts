/**
 * Presentation helpers mapping backend job state / stage values to labels and
 * colors. Shared by the jobs list and the job detail screen.
 */

import { JobState, type JobStateValue, type StageStatus } from "@/lib/types";

export interface StateBadge {
  label: string;
  color: string;
}

export function stateBadge(state: JobStateValue): StateBadge {
  switch (state) {
    case JobState.Complete:
      return { label: "Complete", color: "#7CC39B" };
    case JobState.Failed:
      return { label: "Failed", color: "#E0847F" };
    case JobState.Processing:
    default:
      return { label: "Processing", color: "#E6C76A" };
  }
}

export function stageColor(status: StageStatus | undefined): string {
  switch (status) {
    case "complete":
      return "#7CC39B";
    case "running":
      return "#E6C76A";
    case "failed":
      return "#E0847F";
    case "pending":
    default:
      return "#6f6c65";
  }
}
