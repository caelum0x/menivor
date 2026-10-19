/**
 * Unit tests for the schedule-time helpers. Pure logic (no network, no RN) — the
 * scheduled_at the client sends must always be a valid, strictly-future ISO-8601
 * UTC timestamp.
 */

import { describe, expect, it } from "vitest";
import {
  SCHEDULE_OFFSETS,
  findOffset,
  formatLocalTime,
  scheduledAtFromOffset,
} from "../schedule-time";

describe("scheduledAtFromOffset", () => {
  it("returns an ISO-8601 UTC timestamp offset into the future", () => {
    const now = Date.parse("2026-08-19T12:00:00.000Z");
    const iso = scheduledAtFromOffset(60 * 60 * 1000, now);
    expect(iso).toBe("2026-08-19T13:00:00.000Z");
  });

  it("is strictly in the future for every preset offset", () => {
    const now = Date.parse("2026-08-19T12:00:00.000Z");
    for (const offset of SCHEDULE_OFFSETS) {
      const iso = scheduledAtFromOffset(offset.ms, now);
      expect(Date.parse(iso)).toBeGreaterThan(now);
    }
  });
});

describe("findOffset", () => {
  it("resolves a known offset id", () => {
    expect(findOffset("1h")?.ms).toBe(60 * 60 * 1000);
  });

  it("returns undefined for an unknown id", () => {
    expect(findOffset("nope")).toBeUndefined();
  });
});

describe("formatLocalTime", () => {
  it("renders an em dash for a null time", () => {
    expect(formatLocalTime(null)).toBe("—");
  });

  it("returns the raw string when the value is unparseable", () => {
    expect(formatLocalTime("not-a-date")).toBe("not-a-date");
  });
});
