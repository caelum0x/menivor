import { describe, expect, it } from "vitest";
import { JobState } from "@/lib/types";
import {
  formatTally,
  milestoneProgress,
  milestoneTitle,
  nextMilestone,
  reachedMilestone,
  tallyFinishedReels,
} from "./milestones";

describe("reel milestones", () => {
  it("counts only finished reels", () => {
    const jobs = [
      { state: JobState.Complete },
      { state: JobState.Failed },
      { state: JobState.Processing },
      { state: JobState.Complete },
    ];
    expect(tallyFinishedReels(jobs)).toEqual({ count: 2, atLeast: false });
    expect(formatTally(tallyFinishedReels(jobs, true))).toBe("2+");
  });

  it("finds the reached and next milestone", () => {
    expect(reachedMilestone(0)).toBe(0);
    expect(nextMilestone(0)).toBe(1);
    expect(reachedMilestone(1)).toBe(1);
    expect(nextMilestone(1)).toBe(5);
    expect(reachedMilestone(12)).toBe(10);
    expect(nextMilestone(12)).toBe(25);
    expect(nextMilestone(5000)).toBeNull();
  });

  it("restarts the ring after each milestone", () => {
    expect(milestoneProgress(0)).toBe(0);
    expect(milestoneProgress(1)).toBe(0);
    expect(milestoneProgress(3)).toBe(0.5);
    expect(milestoneProgress(5000)).toBe(1);
  });

  it("credits the creator in milestone titles", () => {
    expect(milestoneTitle(0)).toBe("");
    expect(milestoneTitle(1)).toBe("Your first reel is ready");
    expect(milestoneTitle(10)).toBe("You made 10 reels");
  });
});
