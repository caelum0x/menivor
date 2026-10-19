import * as React from "react";
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import {
  JOB_STAGES,
  type JobStage,
  type StageStatus,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Jobs-library checklist of the ReelForge DAG stages
 * (script → tts → avatar/captions → compose → upload), each reflecting its
 * per-stage status from `job.stages`. Stages absent from the map render as
 * "pending".
 */

const STAGE_LABELS: Record<JobStage, string> = {
  script: "Script",
  tts: "Voiceover",
  avatar: "Avatar",
  captions: "Captions",
  compose: "Compose",
  upload: "Publish",
};

interface StatusPresentation {
  icon: React.ComponentType<{ className?: string }>;
  className: string;
  spin?: boolean;
  label: string;
}

const STATUS_PRESENTATION: Record<StageStatus, StatusPresentation> = {
  complete: {
    icon: CheckCircle2,
    className: "text-success",
    label: "Complete",
  },
  running: {
    icon: Loader2,
    className: "text-primary",
    spin: true,
    label: "Running",
  },
  failed: { icon: XCircle, className: "text-destructive", label: "Failed" },
  pending: { icon: Circle, className: "text-muted-foreground", label: "Pending" },
};

export interface StageProgressProps {
  /** Per-stage status map from `job.stages`. */
  stages?: Partial<Record<JobStage, StageStatus>>;
  /** Which stages to display, in order. Defaults to the full DAG. */
  visibleStages?: readonly JobStage[];
  className?: string;
}

export function StageProgress({
  stages,
  visibleStages = JOB_STAGES,
  className,
}: Readonly<StageProgressProps>) {
  return (
    <ol className={cn("flex flex-col gap-1", className)}>
      {visibleStages.map((stage) => {
        const status: StageStatus = stages?.[stage] ?? "pending";
        const { icon: Icon, className: iconClass, spin, label } =
          STATUS_PRESENTATION[status];
        const isDone = status === "complete";
        return (
          <li
            key={stage}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm",
              status === "running" && "bg-primary/5",
              status === "failed" && "bg-destructive/5",
            )}
          >
            <Icon
              className={cn("size-4 shrink-0", iconClass, spin && "animate-spin")}
              aria-hidden
            />
            <span
              className={cn(
                "flex-1 font-medium",
                isDone && "text-muted-foreground",
              )}
            >
              {STAGE_LABELS[stage]}
            </span>
            <span className={cn("text-xs", iconClass)}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
