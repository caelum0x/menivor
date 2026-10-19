import { describe, expect, it } from "vitest";

import { JobState, type Job } from "@/lib/types";

import { initialBaseline, reelLevel, reelWin, reelsMade } from "../reel-wins";

const job = (state: Job["state"], archived = false) => ({ job_id: Math.random().toString(), state, archived }) as unknown as Job;

describe("reel wins", () => {
  it("counts only finished reels, archived included", () => {
    expect(
      reelsMade([job(JobState.Complete), job(JobState.Processing), job(JobState.Failed), job(JobState.Complete, true)]),
    ).toBe(2);
  });

  it("levels follow real counts", () => {
    expect(reelLevel(0)).toBe(0);
    expect(reelLevel(1)).toBe(1);
    expect(reelLevel(9)).toBe(5);
    expect(reelLevel(10)).toBe(10);
  });

  it("new users still get the first-reel moment; existing libraries baseline silently", () => {
    expect(initialBaseline(0)).toBe(0);
    expect(initialBaseline(1)).toBe(0);
    expect(initialBaseline(12)).toBe(10);
    expect(reelWin(initialBaseline(12), 12)).toBeNull();
  });

  it("fires once per milestone, crediting the user", () => {
    expect(reelWin(0, 1)?.title).toBe("Your first reel is ready");
    expect(reelWin(1, 4)).toBeNull();
    expect(reelWin(1, 5)).toMatchObject({ level: 5, title: "You made 5 reels" });
    expect(reelWin(5, 5)).toBeNull();
  });
});
