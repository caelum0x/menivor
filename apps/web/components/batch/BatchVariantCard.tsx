import * as React from "react";
import Link from "next/link";
import { ArrowUpRight, Download, Star } from "lucide-react";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { JobPoster, JobStatusBadge } from "@/src/features/jobs-library";
import { jobPosterUrl, jobResultUrl } from "@/lib/job-media";
import { JobState, type BatchJob } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * One variant tile in the batch-review grid: poster preview, per-variant status
 * + progress, and actions (open the job-detail page, plus Download/Publish once
 * the render is complete — reusing the same `result_url` action as job detail).
 * Props are read-only.
 */

export interface BatchVariantCardProps {
  job: BatchJob;
  /** 1-based label for this variant within the batch. */
  index: number;
  /** Highlights this tile as the first finished variant. */
  highlighted?: boolean;
}

export function BatchVariantCard({
  job,
  index,
  highlighted = false,
}: Readonly<BatchVariantCardProps>) {
  const shortId = job.job_id.slice(0, 8);
  const posterUrl = jobPosterUrl(job);
  const resultUrl = jobResultUrl(job);
  const isComplete = job.state === JobState.Complete;

  return (
    <Card
      className={cn(
        "flex flex-col overflow-hidden transition-colors",
        highlighted
          ? "border-success/60 ring-2 ring-success/40"
          : "hover:border-primary/40",
      )}
    >
      <div className="relative">
        <JobPoster
          posterUrl={posterUrl}
          alt={`Variant ${index} poster`}
          className="h-52 w-full border-b border-border"
        />
        {highlighted && (
          <Badge variant="success" className="absolute left-2 top-2 shadow">
            <Star className="size-3" aria-hidden /> First finished
          </Badge>
        )}
      </div>

      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
        <span className="flex items-center gap-2 font-medium">
          <span className="text-sm">Variant {index}</span>
          <span className="font-mono text-xs text-muted-foreground">
            {shortId}
          </span>
        </span>
        <JobStatusBadge state={job.state} />
      </CardHeader>

      <CardContent className="space-y-2">
        <Progress value={job.progress} />
        <p className="text-xs text-muted-foreground">
          {job.progress}% complete
        </p>
      </CardContent>

      <CardFooter className="mt-auto flex-wrap justify-end gap-2">
        <Button asChild variant="ghost" size="sm">
          <Link
            href={`/jobs/${job.job_id}`}
            aria-label={`Open variant ${index} detail`}
          >
            Open <ArrowUpRight className="size-3.5" aria-hidden />
          </Link>
        </Button>
        {isComplete && resultUrl && (
          <Button asChild variant="outline" size="sm">
            <a
              href={resultUrl}
              download
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Download variant ${index}`}
            >
              <Download aria-hidden /> Download
            </a>
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
