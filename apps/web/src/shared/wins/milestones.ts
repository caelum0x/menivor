/**
 * Honest win moments for the reel counter. Every number here comes from the
 * creator's real finished reels; nothing is padded or estimated.
 */

import { JobState, type Job } from "@/lib/types";

/** Reel counts worth celebrating, in order. */
export const REEL_MILESTONES = [1, 5, 10, 25, 50, 100, 250, 500, 1000] as const;

export interface ReelTally {
  /** Finished (downloadable) reels counted. */
  readonly count: number;
  /** True when more reels exist than were loaded, so `count` is a floor. */
  readonly atLeast: boolean;
}

/** Count finished reels in a loaded list. */
export function tallyFinishedReels(jobs: readonly Pick<Job, "state">[], hasMore = false): ReelTally {
  return {
    count: jobs.filter((job) => job.state === JobState.Complete).length,
    atLeast: hasMore,
  };
}

/** The highest milestone already reached, or 0 before the first reel. */
export function reachedMilestone(count: number): number {
  return REEL_MILESTONES.filter((m) => m <= count).at(-1) ?? 0;
}

/** The next milestone to aim for, or null past the last one. */
export function nextMilestone(count: number): number | null {
  return REEL_MILESTONES.find((m) => m > count) ?? null;
}

/**
 * Progress (0-1) from the last reached milestone to the next one, so the ring
 * restarts after every win instead of crawling toward 1000.
 */
export function milestoneProgress(count: number): number {
  const next = nextMilestone(count);
  if (next === null) return 1;
  const from = reachedMilestone(count);
  return Math.min(1, Math.max(0, (count - from) / (next - from)));
}

/** Headline for a reached milestone, crediting the creator. */
export function milestoneTitle(milestone: number): string {
  if (milestone <= 0) return "";
  if (milestone === 1) return "Your first reel is ready";
  return `You made ${milestone} reels`;
}

/** Display form of a tally: "12" or "100+". */
export function formatTally(tally: ReelTally): string {
  return tally.atLeast ? `${tally.count}+` : String(tally.count);
}
