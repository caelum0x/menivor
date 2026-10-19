"use client";

import * as React from "react";
import Link from "next/link";
import { Download, Loader2, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { STORY_DONE, STORY_FAILED } from "@/src/features/story8/api";

import type { VeryTimeJob } from "./api";

function heading(job: VeryTimeJob): string {
  if (job.state === STORY_DONE) return "Your video is ready";
  if (job.state === STORY_FAILED) return "This video failed";
  return "Making your video";
}

/** After the price: progress while it renders, then the finished video. Fixed-size frame, no layout shift. */
export function ResultView({
  job,
  onAnother,
  endCta = "",
}: Readonly<{ job: VeryTimeJob; onAnother: () => void; endCta?: string }>) {
  const done = job.state === STORY_DONE && Boolean(job.video_url);
  const failed = job.state === STORY_FAILED;
  const overlays = (job.chest ?? []).filter((c) => c.status === "overlay").length;
  return (
    <section aria-labelledby="vt-result" className="space-y-4">
      <h2 id="vt-result" className="text-xl font-semibold" aria-live="polite">
        {heading(job)}
      </h2>
      <div className="glass-subtle relative aspect-[9/16] w-full max-w-xs overflow-hidden rounded-2xl">
        {done ? (
          <video className="h-full w-full object-cover" src={job.video_url} poster={job.poster_url || undefined} controls playsInline />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center text-sm text-muted-foreground">
            {failed ? null : <Loader2 className="size-5 animate-spin" aria-hidden />}
            <span>{failed ? "Nothing to show." : job.stage ? `Working on: ${job.stage.replace(/[_-]+/g, " ")}` : "Starting"}</span>
          </div>
        )}
      </div>
      {endCta.trim() ? (
        <p className="text-sm text-muted-foreground" data-testid="vt-result-end-card">
          Ends with: {endCta.trim()}
        </p>
      ) : null}
      {job.sheet_url ? (
        <figure className="flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- presigned media URL */}
          <img src={job.sheet_url} alt="Character sheet" className="h-20 w-auto rounded-lg object-contain" />
          <figcaption className="text-xs text-muted-foreground">The character sheet every shot follows.</figcaption>
        </figure>
      ) : null}
      {overlays > 0 ? (
        <p className="text-xs text-muted-foreground" data-testid="vt-overlay-note">
          The chest words were set cleanly on {overlays === 1 ? "one frame" : `${overlays} frames`} where the picture
          misspelled them.
        </p>
      ) : null}
      {failed ? (
        <p role="alert" className="text-sm">
          {job.error || "Something went wrong while making it."}{" "}
          {job.refunded === false ? "" : "Everything it held was refunded."}
        </p>
      ) : null}
      <div className="flex min-h-10 flex-wrap items-center gap-3">
        {done ? (
          <>
            <Button asChild>
              <a href={job.video_url} download>
                <Download className="size-4" aria-hidden /> Download
              </a>
            </Button>
            <Button asChild variant="outline">
              <Link href="/autopost/new">
                <Send className="size-4" aria-hidden /> Post it with Autopost
              </Link>
            </Button>
          </>
        ) : null}
        {done || failed ? (
          <Button variant="ghost" onClick={onAnother}>
            Make another
          </Button>
        ) : null}
      </div>
    </section>
  );
}
