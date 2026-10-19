import * as React from "react";
import Link from "next/link";
import { ArrowUpRight, Film } from "lucide-react";
import { JOB_STAGES, type Job, type JobStage, type StageStatus } from "@/lib/types";
import { jobThumbnailUrl } from "@/lib/job-media";
import { jobDisplayTitle } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { JobStatusBadge } from "@/src/features/jobs-library";
import type { ReelActionHandlers } from "../use-reel-actions";
import { ReelActions } from "./ReelActions";

export interface ReelsTableProps {
  reels: readonly Job[];
  /** Row-level rename / archive / cancel / delete controls. */
  actions: ReelActionHandlers;
}

function stageProgressLabel(
  stages: Partial<Record<JobStage, StageStatus>> | undefined,
): string {
  if (!stages) return "—";
  const present = JOB_STAGES.filter((stage) => stage in stages);
  if (present.length === 0) return "—";
  const done = present.filter((stage) => stages[stage] === "complete").length;
  return `${done}/${present.length}`;
}

function formatCreated(value?: string): string {
  if (!value) return "—";
  const t = Date.parse(value);
  if (Number.isNaN(t)) return "—";
  return new Date(t).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Dense table of the caller's reels with per-row rename / archive / cancel /
 * delete controls. Each row links through to the live reel-detail page. Thumbnails only render when the backend hands
 * back an absolute (presigned) URL — bare R2 keys degrade to an icon.
 */
export function ReelsTable({ reels, actions }: Readonly<ReelsTableProps>) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th scope="col" className="px-4 py-3 font-medium">
              Reel
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              Status
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              Progress
            </th>
            <th scope="col" className="hidden px-4 py-3 font-medium md:table-cell">
              Stages
            </th>
            <th scope="col" className="hidden px-4 py-3 font-medium lg:table-cell">
              Created
            </th>
            <th scope="col" className="px-4 py-3 text-right font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {reels.map((reel) => (
            <ReelRow key={reel.job_id} reel={reel} actions={actions} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReelRow({
  reel,
  actions,
}: Readonly<{ reel: Job; actions: ReelActionHandlers }>) {
  const shortId = reel.job_id.slice(0, 10);
  const title = jobDisplayTitle(reel);
  const thumb = jobThumbnailUrl(reel);
  const href = `/reels/${encodeURIComponent(reel.job_id)}`;

  return (
    <tr className="border-b border-border transition-colors last:border-b-0 hover:bg-muted/40">
      <td className="px-4 py-3">
        <Link
          href={href}
          className="flex items-center gap-3 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex h-11 w-8 shrink-0 items-center justify-center overflow-hidden rounded border border-border bg-muted">
            {thumb ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={thumb}
                alt=""
                className="h-full w-full object-cover"
                loading="lazy"
              />
            ) : (
              <Film className="size-4 text-muted-foreground" aria-hidden />
            )}
          </span>
          <span className="min-w-0">
            <span className="block max-w-[16rem] truncate text-sm font-medium text-foreground">
              {title}
            </span>
            <span className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
              {shortId}
              {reel.archived ? (
                <Badge variant="outline" className="px-1.5 py-0 font-sans text-[10px]">
                  Archived
                </Badge>
              ) : null}
            </span>
          </span>
        </Link>
      </td>
      <td className="px-4 py-3">
        <JobStatusBadge state={reel.state} />
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
            <span
              className="block h-full rounded-full bg-primary"
              style={{ width: `${Math.min(100, Math.max(0, reel.progress))}%` }}
            />
          </span>
          <span className="tabular-nums text-xs text-muted-foreground">
            {reel.progress}%
          </span>
        </div>
      </td>
      <td className="hidden px-4 py-3 text-muted-foreground md:table-cell">
        {stageProgressLabel(reel.stages)}
      </td>
      <td className="hidden px-4 py-3 text-muted-foreground lg:table-cell">
        {formatCreated(reel.created_at)}
      </td>
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-1">
          <ReelActions job={reel} actions={actions} />
          <Button asChild variant="ghost" size="sm">
            <Link href={href} aria-label={`Open reel ${shortId}`}>
              View
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          </Button>
        </div>
      </td>
    </tr>
  );
}
