"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import { AlertTriangle, Film, Loader2, RefreshCw } from "lucide-react";
import { listJobs } from "@/lib/api";
import { friendlyErrorMessage } from "@/src/shared/errors";
import { JobState, type Job } from "@/lib/types";
import { jobThumbnailUrl } from "@/lib/job-media";
import { Button } from "@/components/ui/button";

type PickerStatus = "loading" | "ready" | "error";

export interface ReelPickerProps {
  /** Build a link for each reel (navigation mode). */
  hrefFor?: (jobId: string) => string;
  /** Called with the picked reel id (in-page selection mode). */
  onSelect?: (jobId: string) => void;
  /** Currently selected reel, highlighted in selection mode. */
  selectedId?: string;
  /** Maximum number of reels shown (newest first). */
  limit?: number;
  /** Copy for the empty state. */
  emptyLabel?: string;
}

function createdAtOf(job: Job): number {
  const t = job.created_at ? Date.parse(job.created_at) : Number.NaN;
  return Number.isNaN(t) ? 0 : t;
}

function formatCreated(job: Job): string {
  const t = createdAtOf(job);
  if (!t) return "";
  return new Date(t).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Loads the caller's finished reels (GET /jobs), newest first. */
function useFinishedReels(limit: number) {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<PickerStatus>("loading");
  const [reels, setReels] = React.useState<readonly Job[]>([]);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const jobs = await listJobs({ token });
      const finished = jobs
        .filter((job) => job.state === JobState.Complete)
        .slice()
        .sort((a, b) => createdAtOf(b) - createdAtOf(a))
        .slice(0, limit);
      setReels(finished);
      setStatus("ready");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not load your reels."));
      setStatus("error");
    }
  }, [getToken, limit]);

  React.useEffect(() => {
    if (!isLoaded) return;
    void load();
  }, [isLoaded, load]);

  return { status, reels, error, reload: load } as const;
}

/**
 * A compact list of the caller's finished reels. Used wherever a flow needs a
 * reel as its source (editor, publish) so users never have to type a raw job id.
 */
export function ReelPicker({
  hrefFor,
  onSelect,
  selectedId,
  limit = 12,
  emptyLabel = "No finished reels yet.",
}: Readonly<ReelPickerProps>) {
  const { status, reels, error, reload } = useFinishedReels(limit);

  if (status === "loading") {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Loading your reels…
      </p>
    );
  }

  if (status === "error") {
    return (
      <div className="space-y-2" role="alert">
        <p className="flex items-center gap-2 text-sm text-destructive">
          <AlertTriangle className="size-4" aria-hidden /> {error}
        </p>
        <Button type="button" size="sm" variant="outline" onClick={() => void reload()}>
          <RefreshCw className="mr-1 size-4" aria-hidden /> Try again
        </Button>
      </div>
    );
  }

  if (reels.length === 0) {
    return (
      <div className="space-y-2 text-sm text-muted-foreground">
        <p>{emptyLabel}</p>
        <Link href="/create" className="text-primary underline-offset-4 hover:underline">
          Create a reel
        </Link>
      </div>
    );
  }

  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {reels.map((reel) => (
        <li key={reel.job_id}>
          <ReelPickerItem
            reel={reel}
            href={hrefFor?.(reel.job_id)}
            onSelect={onSelect}
            selected={selectedId === reel.job_id}
          />
        </li>
      ))}
    </ul>
  );
}

function ReelPickerItem({
  reel,
  href,
  onSelect,
  selected,
}: Readonly<{
  reel: Job;
  href?: string;
  onSelect?: (jobId: string) => void;
  selected: boolean;
}>) {
  const thumb = jobThumbnailUrl(reel);
  const className = `flex w-full items-center gap-3 rounded-md border p-2 text-left transition-colors hover:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
    selected ? "border-primary bg-primary/10" : "border-border"
  }`;
  const body = (
    <>
      <span className="flex h-14 w-10 shrink-0 items-center justify-center overflow-hidden rounded border border-border bg-muted">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <Film className="size-4 text-muted-foreground" aria-hidden />
        )}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm">
          {reel.hook || `Reel ${reel.job_id.slice(0, 8)}`}
        </span>
        <span className="block font-mono text-xs text-muted-foreground">
          {reel.job_id.slice(0, 10)} {formatCreated(reel)}
        </span>
      </span>
    </>
  );

  if (href) {
    return (
      <Link href={href} className={className}>
        {body}
      </Link>
    );
  }
  return (
    <button
      type="button"
      className={className}
      aria-pressed={selected}
      onClick={() => onSelect?.(reel.job_id)}
    >
      {body}
    </button>
  );
}
