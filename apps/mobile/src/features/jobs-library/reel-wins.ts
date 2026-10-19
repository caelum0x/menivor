/**
 * Reel win moments: celebrate REAL finished reels (first one, 5, 10, 25...).
 * Pure logic here; the last celebrated level is persisted per install by
 * `useReelWins`. Numbers always come from the jobs API, never invented.
 */
import { JobState, type Job } from "@/lib/types";

export const REEL_MILESTONES = [1, 5, 10, 25, 50, 100, 250, 500, 1000] as const;

export interface ReelWin {
  level: number;
  title: string;
  message: string;
}

/** Finished reels the user made (archived ones still count: they were made). */
export function reelsMade(jobs: readonly Job[]): number {
  return jobs.filter((job) => job.state === JobState.Complete).length;
}

/** Highest milestone at or below `count` (0 when none). */
export function reelLevel(count: number): number {
  let level = 0;
  for (const t of REEL_MILESTONES) if (count >= t) level = t;
  return level;
}

/**
 * Baseline for a user seen for the first time: existing libraries are
 * recorded silently, but a brand-new user (0 or 1 reels) still gets the
 * "first reel" moment.
 */
export function initialBaseline(count: number): number {
  return count <= 1 ? 0 : reelLevel(count);
}

/** The win to show when `count` passes the stored `baseline`, else null. */
export function reelWin(baseline: number, count: number): ReelWin | null {
  const level = reelLevel(count);
  if (level <= baseline) return null;
  if (level === 1) {
    return {
      level,
      title: "Your first reel is ready",
      message: "You made it. Watch it, then post it or make the next one.",
    };
  }
  return {
    level,
    title: `You made ${level} reels`,
    message: "That is a real content engine. Keep it rolling.",
  };
}
