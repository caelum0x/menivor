"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { listJobs, rerunJob } from "@/lib/api";
import { jobThumbnailUrl } from "@/lib/job-media";
import { JobState, type Job } from "@/lib/types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

import { MAX_BATCH_VIDEOS, MAX_VARIATIONS, variationHooks } from "../plan";

function jobLabel(job: Job): string {
  const title = (job.title ?? "").trim();
  if (title) return title;
  const created = job.created_at ? new Date(job.created_at).toLocaleString() : "";
  return created ? `Video from ${created}` : "Untitled video";
}

/**
 * Step 1: which videos. Pick finished (or still rendering) videos, or make new
 * variations of one finished video, each with a different opening hook.
 */
export function VideosStep({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [jobs, setJobs] = React.useState<Job[] | null>(null);
  const [error, setError] = React.useState("");
  const [source, setSource] = React.useState("");
  const [count, setCount] = React.useState(5);
  const [making, setMaking] = React.useState<{ done: number; total: number } | null>(null);

  const reload = React.useCallback(async () => {
    try {
      const all = await listJobs();
      setJobs(all.filter((j) => j.state === JobState.Complete || j.state === JobState.Processing));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not load your videos."));
      setJobs([]);
    }
  }, []);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const toggle = (id: string) => {
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  };

  const makeVariations = async () => {
    const hooks = variationHooks(count);
    setError("");
    setMaking({ done: 0, total: hooks.length });
    const made: string[] = [];
    try {
      for (const hook of hooks) {
        const job = await rerunJob(source, { hook_style: hook });
        made.push(job.job_id);
        setMaking({ done: made.length, total: hooks.length });
      }
    } catch (err) {
      setError(friendlyErrorMessage(err, "Some variations could not be started."));
    } finally {
      setMaking(null);
      if (made.length > 0) {
        onChange(Array.from(new Set([...selected, ...made])));
        await reload();
      }
    }
  };

  if (jobs === null) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Loading videos
      </p>
    );
  }

  const finished = jobs.filter((j) => j.state === JobState.Complete);
  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h3 className="text-sm font-medium">Make variations of a finished video</h3>
        <p className="text-xs text-muted-foreground">
          Each variation gets a freshly written script with a different opening hook and uses credits
          like a new video. They join this batch and post once they finish rendering.
        </p>
        <div className="grid gap-3 sm:grid-cols-[1fr_8rem_auto] sm:items-end">
          <div className="space-y-1.5">
            <Label htmlFor="variation-source">Video</Label>
            <Select id="variation-source" value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">Choose a video</option>
              {finished.map((j) => (
                <option key={j.job_id} value={j.job_id}>
                  {jobLabel(j)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="variation-count">How many</Label>
            <Select id="variation-count" value={String(count)} onChange={(e) => setCount(Number(e.target.value))}>
              {Array.from({ length: MAX_VARIATIONS - 1 }, (_, i) => i + 2).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </div>
          <Button variant="secondary" disabled={!source || making !== null} onClick={() => void makeVariations()}>
            {making ? <Loader2 className="animate-spin" aria-hidden /> : null}
            {making ? `Starting ${making.done} of ${making.total}` : "Make variations"}
          </Button>
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-medium">
          Videos in this batch ({selected.length} of up to {MAX_BATCH_VIDEOS})
        </h3>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {jobs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No videos yet. Make one first.</p>
        ) : (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {jobs.map((job) => {
              const checked = selected.includes(job.job_id);
              const thumb = jobThumbnailUrl(job);
              return (
                <li key={job.job_id}>
                  <label
                    className={`block cursor-pointer overflow-hidden rounded-lg border ${
                      checked ? "border-primary" : "border-white/10"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      onChange={() => toggle(job.job_id)}
                      aria-label={jobLabel(job)}
                    />
                    {thumb ? (
                      // eslint-disable-next-line @next/next/no-img-element -- presigned media URL
                      <img src={thumb} alt="" className="aspect-[9/16] w-full object-cover" />
                    ) : (
                      <span className="flex aspect-[9/16] w-full items-center justify-center bg-white/[0.04] text-xs text-muted-foreground">
                        {job.state === JobState.Processing ? "Rendering" : "No preview"}
                      </span>
                    )}
                    <span className="block truncate px-2 py-1.5 text-xs">{jobLabel(job)}</span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
