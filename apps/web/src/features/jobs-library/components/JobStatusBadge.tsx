import * as React from "react";
import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import { Badge, type BadgeProps, type BadgeVariant } from "@/components/ui/badge";
import { JobState, type JobStateValue } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Jobs-library rendering of a job's integer `state` as a labelled status badge.
 * Used in the dashboard history grid and the live job-detail header.
 */

interface StatePresentation {
  label: string;
  variant: BadgeVariant;
  icon: React.ComponentType<{ className?: string }>;
  spin?: boolean;
}

function presentationFor(state: JobStateValue): StatePresentation {
  switch (state) {
    case JobState.Complete:
      return { label: "Complete", variant: "success", icon: CheckCircle2 };
    case JobState.Failed:
      return { label: "Failed", variant: "destructive", icon: XCircle };
    case JobState.Processing:
      return { label: "Processing", variant: "default", icon: Loader2, spin: true };
    default:
      return { label: "Queued", variant: "secondary", icon: Clock };
  }
}

export interface JobStatusBadgeProps
  extends Omit<BadgeProps, "variant" | "children"> {
  state: JobStateValue;
}

export function JobStatusBadge({
  state,
  className,
  ...props
}: Readonly<JobStatusBadgeProps>) {
  const { label, variant, icon: Icon, spin } = presentationFor(state);
  return (
    <Badge variant={variant} className={className} {...props}>
      <Icon className={cn("size-3", spin && "animate-spin")} aria-hidden />
      {label}
    </Badge>
  );
}
