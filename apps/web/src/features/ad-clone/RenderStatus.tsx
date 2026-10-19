"use client";

import * as React from "react";
import Link from "next/link";

import { RENDER_DONE, RENDER_FAILED, type AdCloneRenderJob } from "./api";
import { usd } from "./model";

const STAGES: Record<string, string> = {
  queued: "Waiting for a worker",
  voices: "Recording the voices",
  frames: "Checking your Midjourney frames",
  shots: "Animating and lip-syncing the shots",
  assemble: "Cutting the video",
  finished: "Done",
  failed: "Stopped",
};

/** Progress of an approved render; the finished video also lands in My reels and the film project. */
export function RenderStatus({ job }: Readonly<{ job: AdCloneRenderJob }>) {
  return (
    <section aria-label="Render" className="glass-subtle space-y-2 rounded-2xl p-5 text-sm">
      <p className="font-medium">{STAGES[job.stage] ?? job.stage}</p>
      <p className="text-muted-foreground">
        Spent so far {usd(job.spent_usd)} of the {usd(job.quoted_usd)} quote.
      </p>
      {job.state === RENDER_DONE && job.video_url ? (
        <>
          <video src={job.video_url} poster={job.poster_url || undefined} controls className="w-full rounded-xl" />
          <Link href="/reels" className="underline underline-offset-4">
            Open in My reels
          </Link>
        </>
      ) : null}
      {job.state === RENDER_FAILED ? (
        <p role="alert" className="text-destructive">
          {job.error || "The render stopped."} Unused credits were returned.
        </p>
      ) : null}
    </section>
  );
}
