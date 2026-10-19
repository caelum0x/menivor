import { describe, expect, it } from "vitest";
import {
  ApiError,
  conflictCheckOf,
  normalizeEntry,
  problemsOf,
} from "@/components/calendar/board-api";
import { bucketEntriesByDay } from "@/components/calendar/calendar-month";
import { sameTimeOnDay } from "@/components/calendar/use-calendar-board";

describe("calendar board api", () => {
  it("normalizes entries and drops malformed rows", () => {
    expect(normalizeEntry({ id: "a" })).toBeNull();
    expect(normalizeEntry(null)).toBeNull();
    const entry = normalizeEntry({
      source: "post",
      id: "p1",
      platforms: ["telegram", 3],
      scheduled_at: "2030-01-01T10:00:00+00:00",
      status: "scheduled",
      can_move: true,
    });
    expect(entry?.platforms).toEqual(["telegram"]);
    expect(entry?.can_move).toBe(true);
    expect(entry?.channel_label).toBe("");
  });

  it("reads the slot check from a refused move", () => {
    const err = new ApiError("x: TikTok posts need at least 3 hours", 409, {
      data: { check: { allow: false, reason: "gap", suggested_at: "2030-01-01T16:00:00+00:00", platforms: [] } },
    });
    expect(conflictCheckOf(err)?.suggested_at).toBe("2030-01-01T16:00:00+00:00");
    expect(conflictCheckOf(new ApiError("nope", 400, {}))).toBeNull();
    const problems = new ApiError("x", 409, { data: { problems: [{ channel_id: "c1", message: "reconnect" }] } });
    expect(problemsOf(problems)).toEqual([{ channel_id: "c1", message: "reconnect" }]);
  });

  it("keeps the local time of day when dropped on another day", () => {
    const original = new Date(2030, 0, 5, 14, 30).toISOString();
    const moved = sameTimeOnDay(original, new Date(2030, 0, 9));
    expect(moved.getDate()).toBe(9);
    expect(moved.getHours()).toBe(14);
    expect(moved.getMinutes()).toBe(30);
  });

  it("buckets any entry shape by local day", () => {
    const at = new Date(2030, 0, 5, 9).toISOString();
    const buckets = bucketEntriesByDay([{ scheduled_at: at, id: "x" }, { scheduled_at: null, id: "y" }]);
    expect([...buckets.values()].flat().map((e) => e.id)).toEqual(["x"]);
  });
});
