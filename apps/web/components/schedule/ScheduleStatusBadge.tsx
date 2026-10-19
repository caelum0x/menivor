import * as React from "react";
import {
  Ban,
  CheckCircle2,
  Clock,
  Loader2,
  Send,
  XCircle,
} from "lucide-react";
import { Badge, type BadgeProps, type BadgeVariant } from "@/components/ui/badge";
import type { ScheduledPublishStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Renders a scheduled publish's lifecycle `status` as a labelled badge. Used in
 * the scheduled-publishes list.
 */

interface StatusPresentation {
  label: string;
  variant: BadgeVariant;
  icon: React.ComponentType<{ className?: string }>;
  spin?: boolean;
}

function presentationFor(status: ScheduledPublishStatus): StatusPresentation {
  switch (status) {
    case "pending":
      return { label: "Pending", variant: "secondary", icon: Clock };
    case "queued":
      return { label: "Queued", variant: "default", icon: Clock };
    case "publishing":
      return {
        label: "Publishing",
        variant: "default",
        icon: Loader2,
        spin: true,
      };
    case "published":
      return { label: "Published", variant: "success", icon: CheckCircle2 };
    case "failed":
      return { label: "Failed", variant: "destructive", icon: XCircle };
    case "canceled":
      return { label: "Canceled", variant: "outline", icon: Ban };
    default:
      return { label: String(status || "Unknown"), variant: "secondary", icon: Send };
  }
}

export interface ScheduleStatusBadgeProps
  extends Omit<BadgeProps, "variant" | "children"> {
  status: ScheduledPublishStatus;
}

export function ScheduleStatusBadge({
  status,
  className,
  ...props
}: Readonly<ScheduleStatusBadgeProps>) {
  const { label, variant, icon: Icon, spin } = presentationFor(status);
  return (
    <Badge variant={variant} className={className} {...props}>
      <Icon className={cn("size-3", spin && "animate-spin")} aria-hidden />
      {label}
    </Badge>
  );
}
