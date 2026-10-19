import { describe, expect, it } from "vitest";
import { crossedMilestone, isFirstReelMoment, resultHeadline } from "./ResultHero";

describe("result win moment", () => {
  it("says first reel only when it truly is the first", () => {
    expect(resultHeadline({ count: 1, atLeast: false }, 1)).toBe("Your first reel is ready");
    expect(resultHeadline({ count: 3, atLeast: false }, 3)).toBe("Your first reels are ready");
    expect(resultHeadline({ count: 7, atLeast: false }, 3)).toBe("3 reels ready");
    expect(resultHeadline({ count: 100, atLeast: true }, 1)).toBe("Your reel is ready");
    expect(resultHeadline(null, 1)).toBe("Your reel is ready");
  });

  it("names a milestone only when this run crossed it", () => {
    expect(crossedMilestone({ count: 6, atLeast: false }, 3)).toBe("You made 5 reels");
    expect(crossedMilestone({ count: 8, atLeast: false }, 2)).toBe("");
    expect(crossedMilestone({ count: 1, atLeast: false }, 1)).toBe("");
    expect(crossedMilestone({ count: 100, atLeast: true }, 3)).toBe("");
    expect(crossedMilestone(null, 3)).toBe("");
  });

  it("marks the first-reel share moment only for a real first run", () => {
    expect(isFirstReelMoment({ count: 1, atLeast: false }, 1)).toBe(true);
    expect(isFirstReelMoment({ count: 3, atLeast: false }, 3)).toBe(true);
    expect(isFirstReelMoment({ count: 4, atLeast: false }, 3)).toBe(false);
    expect(isFirstReelMoment({ count: 0, atLeast: false }, 1)).toBe(false);
    expect(isFirstReelMoment({ count: 100, atLeast: true }, 1)).toBe(false);
    expect(isFirstReelMoment(null, 1)).toBe(false);
  });
});
