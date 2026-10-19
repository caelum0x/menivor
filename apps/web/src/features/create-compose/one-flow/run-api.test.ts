import { describe, expect, it } from "vitest";
import { outOfCreditsLine, runCopy, runVariantCount } from "./run-api";

describe("runVariantCount (MG11)", () => {
  it("makes one reel per credit up to three", () => {
    expect(runVariantCount(0)).toBe(0);
    expect(runVariantCount(1)).toBe(1);
    expect(runVariantCount(2)).toBe(2);
    expect(runVariantCount(3)).toBe(3);
    expect(runVariantCount(250)).toBe(3);
  });

  it("asks for the full run while the balance is unknown and never goes negative", () => {
    expect(runVariantCount(null)).toBe(3);
    expect(runVariantCount(undefined)).toBe(3);
    expect(runVariantCount(Number.NaN)).toBe(3);
    expect(runVariantCount(-2)).toBe(0);
    expect(runVariantCount(1.7)).toBe(1);
  });
});

describe("run copy", () => {
  it("matches the number of reels the run makes", () => {
    expect(runCopy(1)).toEqual({ cost: "1 credit", button: "Make 1 reel", starting: "Starting 1 render…" });
    expect(runCopy(2).button).toBe("Make 2 reels");
    expect(runCopy(3).cost).toBe("3 credits");
  });

  it("says out of credits plainly", () => {
    expect(outOfCreditsLine(0)).toContain("out of credits");
    expect(outOfCreditsLine(null)).toContain("out of credits");
    expect(outOfCreditsLine(2)).toContain("you have 2");
  });
});
