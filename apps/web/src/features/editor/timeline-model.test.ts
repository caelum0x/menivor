import { describe, expect, it } from "vitest";

import {
  MAX_OVERLAYS,
  MAX_SEGMENTS,
  newOverlay,
  newSegment,
  segmentOutputLen,
  timelineDuration,
  validateTimeline,
} from "./timeline-model";

describe("timeline model", () => {
  it("computes speed-adjusted output duration deterministically", () => {
    const normal = { ...newSegment(0, 3), speed: 1 };
    const fast = { ...newSegment(3, 7), speed: 2 };

    expect(segmentOutputLen(fast)).toBe(2);
    expect(timelineDuration([normal, fast])).toBe(5);
  });

  it("mirrors server numeric, source, and collection bounds", () => {
    expect(validateTimeline([newSegment(0, 1)], [], 0)).toMatch(/metadata/i);
    expect(validateTimeline([{ ...newSegment(0, 1), sourceIn: -1 }], [], 5)).toMatch(
      /negative/i,
    );
    expect(
      validateTimeline([{ ...newSegment(0, 1), speed: Number.NaN }], [], 5),
    ).toMatch(/finite/i);
    expect(
      validateTimeline(
        Array.from({ length: MAX_SEGMENTS + 1 }, () => newSegment(0, 1)),
        [],
        5,
      ),
    ).toMatch(/at most 200/i);
    expect(
      validateTimeline(
        [newSegment(0, 1)],
        Array.from({ length: MAX_OVERLAYS + 1 }, () => ({
          ...newOverlay(1),
          text: "label",
        })),
        5,
      ),
    ).toMatch(/at most 50/i);
  });

  it("rejects overlays outside the speed-adjusted output clock", () => {
    const segment = { ...newSegment(0, 4), speed: 2 };
    const overlay = { ...newOverlay(3), text: "Too late" };

    expect(validateTimeline([segment], [overlay], 4)).toBe(
      "Overlay 1: past the output (2s).",
    );
  });
});
