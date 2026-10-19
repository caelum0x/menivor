"use client";

import * as React from "react";
import { Languages } from "lucide-react";
import { isFailedState, isTerminalState, type Job } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { DubDialog } from "@/components/dub/DubDialog";

export interface DubButtonProps {
  job: Job;
}

/**
 * "Dub / Translate" entry point shown on a finished reel. Disabled with an
 * explanatory hint until the source job has completed (a completed job always
 * has a generated script to translate). Opening it mounts {@link DubDialog}.
 */
export function DubButton({ job }: Readonly<DubButtonProps>) {
  const [open, setOpen] = React.useState(false);

  const isComplete = isTerminalState(job.state) && !isFailedState(job.state);
  // A completed reel has necessarily produced a script; treat its presence as
  // the enable condition, honouring an explicit stage flag when the backend
  // reports one.
  const hasScript = job.stages ? job.stages.script !== "failed" : true;
  const ready = isComplete && hasScript;

  const hint = !isComplete
    ? isFailedState(job.state)
      ? "Retry this reel before dubbing it into other languages."
      : "Finish rendering this reel to dub it into other languages."
    : !hasScript
      ? "This reel has no script to translate."
      : "";

  return (
    <div className="space-y-1.5">
      <Button
        variant="outline"
        disabled={!ready}
        title={hint || undefined}
        aria-disabled={!ready}
        onClick={() => setOpen(true)}
      >
        <Languages className="size-4" aria-hidden />
        Dub / Translate
      </Button>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}

      {ready && (
        <DubDialog
          jobId={job.job_id}
          sourceLanguage={job.language}
          open={open}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}
