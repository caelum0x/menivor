import * as React from "react";
import Link from "next/link";
import { ArrowUpRight, Film } from "lucide-react";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { JobStatusBadge } from "./JobStatusBadge";
import { JobPoster } from "./JobPoster";
import { jobThumbnailUrl } from "@/lib/job-media";
import { jobDisplayTitle } from "@/lib/api";
import {
  JOB_STAGES,
  type Job,
  type JobStage,
  type StageStatus,
} from "@/lib/types";
import { safeServerText } from "@/src/shared/errors/friendly";

/**
 * Compact summary card for a single reel in the library grid. Links through
 * to the live reel-detail page; an optional `actions` slot renders row
 * controls (rename / archive / cancel / delete) outside the link.
 */

function countCompleteStages(
  stages: Partial<Record<JobStage, StageStatus>> | undefined,
): { done: number; total: number } {
  if (!stages) return { done: 0, total: 0 };
  const present = JOB_STAGES.filter((stage) => stage in stages);
  const done = present.filter((stage) => stages[stage] === "complete").length;
  return { done, total: present.length };
}

export interface JobCardProps {
  job: Job;
  /** Optional controls rendered in the card footer, outside the link. */
  actions?: React.ReactNode;
}

export function JobCard({ job, actions }: Readonly<JobCardProps>) {
  const shortId = job.job_id.slice(0, 8);
  const { done, total } = countCompleteStages(job.stages);
  const posterUrl = jobThumbnailUrl(job);
  const title = jobDisplayTitle(job);

  return (
    <Card className="group animate-fade-in overflow-hidden transition-colors hover:border-primary/40">
      <Link
        href={`/reels/${encodeURIComponent(job.job_id)}`}
        className="block rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`Open ${title}`}
      >
        {posterUrl && (
          <JobPoster
            posterUrl={posterUrl}
            alt={`Reel ${shortId} poster`}
            className="h-36 w-full border-b border-border"
          />
        )}
        <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
          <span className="flex min-w-0 items-center gap-2 font-medium">
            <Film className="size-4 shrink-0 text-primary" aria-hidden />
            <span className="min-w-0">
              <span className="block truncate text-sm">{title}</span>
              <span className="block font-mono text-xs text-muted-foreground">
                {shortId}
                {job.archived ? " · archived" : ""}
              </span>
            </span>
          </span>
          <JobStatusBadge state={job.state} />
        </CardHeader>

        <CardContent className="space-y-3">
          <Progress value={job.progress} />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{job.progress}% complete</span>
            {total > 0 && (
              <span>
                {done}/{total} stages
              </span>
            )}
          </div>
          {job.error && (
            <p className="line-clamp-2 text-xs text-destructive">
              {safeServerText(job.error, "This reel could not be finished.")}
            </p>
          )}
        </CardContent>

        <CardFooter className="justify-end pb-3">
          <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors group-hover:text-primary">
            View details
            <ArrowUpRight className="size-3.5" aria-hidden />
          </span>
        </CardFooter>
      </Link>
      {actions ? (
        <div className="border-t border-border px-4 py-2">{actions}</div>
      ) : null}
    </Card>
  );
}
