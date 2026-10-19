import { describe, expect, it } from "vitest";

import { DASH, formatMinor, formatPercent, minorFactor, toMinor } from "./format";

describe("paid ads formatting", () => {
  it("renders unreported values as a dash, never zero", () => {
    expect(formatPercent(null)).toBe(DASH);
    expect(formatMinor(null, "USD")).toBe(DASH);
  });

  it("handles zero-decimal currencies", () => {
    expect(minorFactor("JPY")).toBe(1);
    expect(toMinor(500, "JPY")).toBe(500);
    expect(toMinor(12.34, "USD")).toBe(1234);
  });

  it("formats rates as percentages", () => {
    expect(formatPercent(0.0234)).toBe("2.34%");
  });
});
