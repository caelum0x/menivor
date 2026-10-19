"use client";

import * as React from "react";
import { CalendarClock } from "lucide-react";
import { isFailedState, isTerminalState, type Job } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { SchedulePublishDialog } from "@/components/schedule/SchedulePublishDialog";

export interface SchedulePublishButtonProps {
  job: Job;
}

/**
 * "Schedule publish" entry point shown on a finished reel. Disabled with an
 * explanatory hint until the source job has completed (only a rendered reel can
 * be published). Opening it mounts {@link SchedulePublishDialog}.
 */
export function SchedulePublishButton({
  job,
}: Readonly<SchedulePublishButtonProps>) {
  const [open, setOpen] = React.useState(false);

  const isComplete = isTerminalState(job.state) && !isFailedState(job.state);

  const hint = !isComplete
    ? isFailedState(job.state)
      ? "Retry this reel before scheduling it to publish."
      : "Finish rendering this reel to schedule publishing."
    : "";

  return (
    <div className="space-y-1.5">
      <Button
        variant="outline"
        disabled={!isComplete}
        title={hint || undefined}
        aria-disabled={!isComplete}
        onClick={() => setOpen(true)}
      >
        <CalendarClock className="size-4" aria-hidden />
        Schedule publish
      </Button>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}

      {isComplete && (
        <SchedulePublishDialog
          jobId={job.job_id}
          open={open}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}
