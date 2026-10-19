import * as React from "react";
import { BatchVariantCard } from "@/components/batch/BatchVariantCard";
import type { BatchJob } from "@/lib/types";

/**
 * Responsive grid of the variants in a batch. `highlightIndex` is the 0-based
 * index of the first finished variant to highlight (or -1 for none). Read-only.
 */

export interface BatchGridProps {
  jobs: readonly BatchJob[];
  highlightIndex: number;
}

export function BatchGrid({ jobs, highlightIndex }: Readonly<BatchGridProps>) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {jobs.map((job, i) => (
        <BatchVariantCard
          key={job.job_id}
          job={job}
          index={i + 1}
          highlighted={i === highlightIndex}
        />
      ))}
    </div>
  );
}
