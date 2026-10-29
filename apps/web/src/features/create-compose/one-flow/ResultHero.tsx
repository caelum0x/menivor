"use client";

/**
 * The win moment after a run: the chosen reel big on screen with the two
 * things people do next (Publish, Download), the creator credited for it, and
 * their real finished-reel count ticking up. Nothing here is estimated: the
 * count comes from GET /jobs and "first reel" only shows when it is true.
 */

import * as React from "react";
import Link from "next/link";
import { Download, Pencil, Send } from "lucide-react";
import { listJobsPage } from "@/lib/api";
import type { Job } from "@/lib/types";
import { jobResultUrl, jobThumbnailUrl } from "@/lib/job-media";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import { IconTip } from "@/components/app-shell/PrimaryNav";
import { ShareButton } from "@/components/share/ShareButton";
import { ShareToX } from "@/src/features/share-x/ShareToX";
import {
  CountUp,
  WinCheck,
  milestoneTitle,
  reachedMilestone,
  tallyFinishedReels,
  type ReelTally,
} from "@/src/shared/wins";
import { ShareActions } from "@/src/features/share-actions/ShareActions";

export interface ResultHeroProps {
  readonly job: Job;
  readonly letter: string;
  /** Finished reels in this run (drives the headline). */
  readonly readyInRun: number;
  /** What the creator typed, to credit them with the result. */
  readonly input?: string;
  /** Chosen hook, or the planned hook for this variant. Falls back to `job.hook`. */
  readonly hook?: string;
  /** Product or page link, when this run started from one. */
  readonly sourceUrl?: string;
}

/** Headline for the moment, honest about whether this is the first reel. */
export function resultHeadline(tally: ReelTally | null, readyInRun: number): string {
  if (tally && isFirstReelMoment(tally, readyInRun)) {
    return tally.count === 1 ? "Your first reel is ready" : "Your first reels are ready";
  }
  return readyInRun === 1 ? "Your reel is ready" : `${readyInRun} reels ready`;
}

/** True only when this run produced the creator's first finished reel(s). */
export function isFirstReelMoment(tally: ReelTally | null, readyInRun: number): boolean {
  return Boolean(tally && !tally.atLeast && tally.count > 0 && tally.count <= readyInRun);
}

/**
 * A milestone crossed by this run ("You made 10 reels"), or "" when none was.
 * The first-reel milestone is already the headline, so it is skipped here.
 */
export function crossedMilestone(tally: ReelTally | null, readyInRun: number): string {
  if (!tally || tally.atLeast) return "";
  const now = reachedMilestone(tally.count);
  const before = reachedMilestone(Math.max(0, tally.count - readyInRun));
  return now > 1 && now > before ? milestoneTitle(now) : "";
}

function useReelTally(refreshKey: number): ReelTally | null {
  const getApiToken = useApiToken();
  const [tally, setTally] = React.useState<ReelTally | null>(null);
  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const token = await getApiToken();
        const page = await listJobsPage(
          { limit: 100, offset: 0, includeArchived: true },
          { token, signal: controller.signal },
        );
        if (active) setTally(tallyFinishedReels(page.jobs, page.hasMore));
      } catch {
        // The counter is a bonus; the reel itself is already on screen.
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [getApiToken, refreshKey]);
  return tally;
}

export function ResultHero({ job, letter, readyInRun, input, hook, sourceUrl }: ResultHeroProps) {
  const tally = useReelTally(readyInRun);
  const resultUrl = jobResultUrl(job);
  const poster = jobThumbnailUrl(job);
  const jobId = job.job_id;
  const milestone = crossedMilestone(tally, readyInRun);
  const firstReel = isFirstReelMoment(tally, readyInRun);

  return (
    <section
      aria-label="Your reel"
      className="glass-subtle grid gap-6 rounded-2xl p-4 sm:p-6 md:grid-cols-[minmax(0,320px)_1fr] md:items-center"
    >
      <div className="mx-auto aspect-[9/16] w-full max-w-[240px] overflow-hidden rounded-xl bg-secondary sm:max-w-[320px]">
        {resultUrl ? (
          <video
            src={resultUrl}
            poster={poster}
            controls
            playsInline
            preload="metadata"
            className="h-full w-full object-cover"
          >
            <track kind="captions" />
          </video>
        ) : null}
      </div>

      <div className="space-y-5">
        <div className="flex items-center gap-3" aria-live="polite">
          <WinCheck size={44} />
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              {resultHeadline(tally, readyInRun)}
            </h2>
            {input ? (
              <p className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">
                You made this from &ldquo;{input}&rdquo;. Showing version {letter}.
              </p>
            ) : (
              <p className="mt-0.5 text-sm text-muted-foreground">Showing version {letter}.</p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {resultUrl ? <ShareActions source="reel" sourceId={jobId} kind="video" /> : null}
          {/* First reel: sharing is the one big action; afterwards Publish leads. */}
          <Button asChild size="lg" variant={firstReel ? "outline" : "default"}>
            <Link href={`/publish?job=${encodeURIComponent(jobId)}`}>
              <Send className="size-4" aria-hidden /> Publish
            </Link>
          </Button>
          <ShareButton jobId={jobId} size="lg" variant={firstReel ? "default" : "outline"} />
          {resultUrl && (
            <Button asChild size="lg" variant="outline">
              <a href={resultUrl} download={`menivor-reel-${letter.toLowerCase()}.mp4`}>
                <Download className="size-4" aria-hidden /> Download
              </a>
            </Button>
          )}
          {resultUrl && (
            <ShareToX
              hook={hook || job.hook}
              hashtags={job.hashtags}
              sourceUrl={sourceUrl || job.source_url}
              downloadUrl={resultUrl}
              downloadFilename={`menivor-reel-${letter.toLowerCase()}.mp4`}
              size="lg"
            />
          )}
          <IconTip label="Edit">
            <Button asChild size="lg" variant="ghost">
              <Link href={`/editor?job=${encodeURIComponent(jobId)}`} aria-label="Edit this reel">
                <Pencil className="size-4" aria-hidden />
              </Link>
            </Button>
          </IconTip>
        </div>

        {firstReel && (
          <p className="text-sm text-muted-foreground">
            Share it with one link, download the file, or publish it straight to your channels.
          </p>
        )}

        {tally && tally.count > 0 && (
          <div className="flex items-baseline gap-2 border-t border-border pt-4">
            <CountUp
              value={tally.count}
              suffix={tally.atLeast ? "+" : ""}
              className="text-3xl font-semibold"
            />
            <span className="text-sm text-muted-foreground">
              {tally.count === 1 ? "reel made" : "reels made"}
            </span>
            {milestone && (
              <span className="ml-auto text-sm font-medium text-primary animate-fade-in">
                {milestone}
              </span>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
