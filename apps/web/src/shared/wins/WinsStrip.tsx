"use client";

import { CountUp } from "./CountUp";
import { ProgressRing } from "./ProgressRing";
import { WinCheck } from "./WinCheck";
import {
  milestoneProgress,
  milestoneTitle,
  nextMilestone,
  reachedMilestone,
  type ReelTally,
} from "./milestones";

interface WinsStripProps {
  readonly tally: ReelTally;
}

/**
 * The creator's scoreboard: finished reels ticking up inside a ring that
 * fills toward the next milestone, plus the last milestone they reached.
 * Hidden until there is at least one finished reel, so it never shows zeros.
 */
export function WinsStrip({ tally }: WinsStripProps) {
  if (tally.count === 0) return null;
  const reached = reachedMilestone(tally.count);
  const next = tally.atLeast ? null : nextMilestone(tally.count);
  return (
    <section
      aria-label="Your progress"
      className="glass-subtle mb-6 flex flex-wrap items-center gap-5 rounded-2xl p-4 sm:p-5"
    >
      <ProgressRing
        value={tally.atLeast ? 1 : milestoneProgress(tally.count)}
        size={72}
        label={next ? `${tally.count} of ${next} reels toward your next milestone` : "Reels made"}
      >
        <CountUp
          value={tally.count}
          suffix={tally.atLeast ? "+" : ""}
          className="text-lg font-semibold"
        />
      </ProgressRing>
      <div className="min-w-0 flex-1">
        <p className="text-sm text-muted-foreground">Reels you&apos;ve made</p>
        <p className="text-base font-medium">
          {next
            ? `${next - tally.count} more to reach ${next}.`
            : "Keep them coming."}
        </p>
      </div>
      {reached > 0 && (
        <div className="flex items-center gap-3 animate-fade-in">
          <WinCheck size={36} />
          <p className="text-sm font-medium">{milestoneTitle(reached)}</p>
        </div>
      )}
    </section>
  );
}
