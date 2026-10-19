import { describe, expect, it } from "vitest";

import {
  formatCount,
  formatPct,
  isCollecting,
  parseLoopSettings,
  platformLabel,
  relativeTime,
  remakeAction,
  remakeNotice,
  statusLabel,
  timelineLabel,
} from "../format";

describe("winner loop format helpers", () => {
  it("labels statuses, platforms and timeline kinds", () => {
    expect(statusLabel("winner_ready")).toBe("Winner picked");
    expect(statusLabel("")).toBe("Unknown");
    expect(statusLabel("new_state")).toBe("new_state");
    expect(platformLabel("youtube")).toBe("YouTube Shorts");
    expect(timelineLabel("remake_started")).toBe("Remake started");
    expect(timelineLabel("custom")).toBe("custom");
  });

  it("formats counts and percentages, with a dash for missing data", () => {
    expect(formatCount(null)).toBe("-");
    expect(formatCount(950)).toBe("950");
    expect(formatCount(12_300)).toBe("12.3K");
    expect(formatCount(2_000_000)).toBe("2M");
    expect(formatPct(0.4567)).toBe("45.7%");
    expect(formatPct(undefined)).toBe("-");
  });

  it("phrases relative time", () => {
    const now = Date.parse("2026-09-24T12:00:00Z");
    expect(relativeTime("2026-09-24T17:00:00Z", now)).toBe("in 5h");
    expect(relativeTime("2026-09-24T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-09-28T12:00:00Z", now)).toBe("in 4d");
    expect(relativeTime("nope", now)).toBe("");
  });

  it("knows when a loop is collecting data", () => {
    expect(isCollecting("live")).toBe(true);
    expect(isCollecting("measuring")).toBe(true);
    expect(isCollecting("winner_ready")).toBe(false);
  });

  it("gates the remake button on a winner and low-confidence confirmation", () => {
    const base = { winner_job_id: "j1", remake_batch_id: "", conclusive: true, remake_cost_credits: 3 };
    expect(remakeAction(base, false)).toEqual({ label: "Remake winner (3 credits)", needsConfirm: false });
    expect(remakeAction({ ...base, conclusive: false }, false)).toEqual({
      label: "Remake winner (3 credits)",
      needsConfirm: true,
    });
    expect(remakeAction({ ...base, conclusive: false }, true)).toEqual({
      label: "Confirm remake (3 credits)",
      needsConfirm: false,
    });
    expect(remakeAction({ ...base, winner_job_id: "" }, false)).toBeNull();
    expect(remakeAction({ ...base, remake_batch_id: "b2" }, false)).toBeNull();
  });

  it("describes remake outcomes honestly", () => {
    expect(remakeNotice({ job_ids: ["a", "b", "c"], enqueue_failures: [], credits: 3, replayed: false })).toBe(
      "3 new variants are rendering (3 credits).",
    );
    expect(remakeNotice({ job_ids: ["a", "b", "c"], enqueue_failures: ["c"], credits: 3, replayed: false })).toBe(
      "2 of 3 new variants started; the rest were refunded.",
    );
    expect(remakeNotice({ job_ids: [], enqueue_failures: [], credits: 0, replayed: true })).toContain("already remade");
  });

  it("validates loop settings inputs", () => {
    expect(parseLoopSettings({ cap: "12", minViews: "100" })).toEqual({ cap: 12, minViews: 100 });
    expect(parseLoopSettings({ cap: "5000", minViews: "-1" })).toEqual({ cap: null, minViews: null });
    expect(parseLoopSettings({ cap: "1e3", minViews: "" })).toEqual({ cap: null, minViews: null });
  });
});
