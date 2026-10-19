import { describe, expect, it } from "vitest";

import {
  PACK_TRUST_NOTE,
  formatMoney,
  lowestPerReelIndex,
  perReelAmount,
  perReelLabel,
  reelsInPack,
  reelsLabel,
} from "../per-reel";

describe("per-reel pricing", () => {
  it("divides the pack price by the reels it makes", () => {
    expect(perReelAmount({ price: 9.99, credits: 25, currencyCode: "USD" })).toBeCloseTo(0.3996);
    expect(perReelLabel({ price: 9.99, credits: 25, currencyCode: "USD" })).toBe("$0.40 per reel");
    expect(perReelLabel({ price: 19, credits: 60, currencyCode: "USD" })).toBe("$0.32 per reel");
  });

  it("keeps small per-reel prices readable", () => {
    expect(perReelLabel({ price: 49, credits: 600, currencyCode: "USD" })).toBe("$0.082 per reel");
  });

  it("formats the store's own currency", () => {
    expect(perReelLabel({ price: 349.99, credits: 25, currencyCode: "TRY" }, "en-US")).toMatch(
      /^TRY\s14\.00 per reel$/,
    );
    expect(perReelLabel({ price: 8.99, credits: 25, currencyCode: "EUR" }, "en-US")).toBe(
      "€0.36 per reel",
    );
  });

  it("handles free, empty and invalid packs", () => {
    expect(perReelLabel({ price: 0, credits: 3, currencyCode: "USD" })).toBe("Free");
    expect(perReelLabel({ price: 5, credits: 0, currencyCode: "USD" })).toBe("");
    expect(perReelLabel({ price: Number.NaN, credits: 10, currencyCode: "USD" })).toBe("");
    expect(formatMoney(1.5, "not-a-code")).toBe("1.50 NOT-A-CODE");
  });

  it("counts reels in a pack", () => {
    expect(reelsInPack(25)).toBe(25);
    expect(reelsInPack(-1)).toBe(0);
    expect(reelsLabel(1)).toBe("1 reel");
    expect(reelsLabel(60)).toBe("60 reels");
  });

  it("finds the best-value pack only among comparable packs", () => {
    const packs = [
      { price: 9.99, credits: 25, currencyCode: "USD" },
      { price: 19.99, credits: 60, currencyCode: "USD" },
      { price: 49.99, credits: 200, currencyCode: "USD" },
    ];
    expect(lowestPerReelIndex(packs)).toBe(2);
    expect(lowestPerReelIndex(packs.slice(0, 1))).toBe(-1);
    expect(lowestPerReelIndex([packs[0]!, { price: 5, credits: 25, currencyCode: "EUR" }])).toBe(-1);
  });

  it("states the never-expire and refund promises", () => {
    expect(PACK_TRUST_NOTE).toContain("never expire");
    expect(PACK_TRUST_NOTE).toContain("refunds");
  });
});
