import { describe, expect, it } from "vitest";
import {
  appStoreUrl,
  changeTone,
  formatChange,
  formatPopularity,
  formatRank,
  hasReading,
  rankChartGeometry,
  shortDate,
} from "./view-model";
import type { HistoryPoint, TrackedKeyword } from "./api";

const keyword = (over: Partial<TrackedKeyword>): TrackedKeyword => ({
  id: "k1", app_id: "999", app_name: "CalDesk", country: "us", term: "fitness", current_rank: null,
  checked_count: 0, last_checked_at: null, last_error: "", change_7d: null, change_30d: null, history: [],
  popularity: null,
  ...over,
});

describe("keyword tracker view model", () => {
  it("formats rank honestly (never a fake 0)", () => {
    expect(formatRank(1)).toBe("#1");
    expect(formatRank(50)).toBe("#50");
    expect(formatRank(null)).toBe("Not in top 50");
  });

  it("formats popularity out of 100, and blank when not available (never a fake difficulty number)", () => {
    expect(formatPopularity(72)).toBe("72/100");
    expect(formatPopularity(5)).toBe("5/100");
    expect(formatPopularity(null)).toBe("");
  });

  it("formats change with a sign, and blank when there is no baseline", () => {
    expect(formatChange(4)).toBe("+4");
    expect(formatChange(-3)).toBe("-3");
    expect(formatChange(0)).toBe("No change");
    expect(formatChange(null)).toBe("");
  });

  it("colors improvement green and drops red, neutral otherwise", () => {
    expect(changeTone(4)).toContain("emerald");
    expect(changeTone(-3)).toBe("text-destructive");
    expect(changeTone(0)).toBe("text-muted-foreground");
    expect(changeTone(null)).toBe("text-muted-foreground");
  });

  it("knows whether a keyword has ever been checked", () => {
    expect(hasReading(keyword({ last_checked_at: null }))).toBe(false);
    expect(hasReading(keyword({ last_checked_at: "2026-10-15T00:00:00Z" }))).toBe(true);
  });

  it("builds the App Store listing url from the numeric id", () => {
    expect(appStoreUrl("6780166477")).toBe("https://apps.apple.com/app/id6780166477");
  });

  it("formats a short date", () => {
    expect(shortDate("2026-10-09")).toBe("Oct 9");
    expect(shortDate("not-a-date")).toBe("");
  });

  describe("rankChartGeometry", () => {
    it("needs at least two ranked days to draw anything", () => {
      const one: HistoryPoint[] = [{ date: "2026-10-14", position: 5 }];
      expect(rankChartGeometry(one, 100, 30)).toBeNull();

      const allUnranked: HistoryPoint[] = [
        { date: "2026-10-13", position: null },
        { date: "2026-10-14", position: null },
      ];
      expect(rankChartGeometry(allUnranked, 100, 30)).toBeNull();
    });

    it("draws an improving rank line (better rank nearer the top)", () => {
      const history: HistoryPoint[] = [
        { date: "2026-10-13", position: 10 },
        { date: "2026-10-14", position: 2 },
      ];
      const geo = rankChartGeometry(history, 100, 30);
      expect(geo).not.toBeNull();
      expect(geo?.worst).toBe(10);
      // Two points, two dots, a single "M...L..." segment.
      expect(geo?.dots).toHaveLength(2);
      expect(geo?.path.startsWith("M0.0,")).toBe(true);
      expect(geo?.path).toContain("L100.0,");
      // The better (lower) rank on day 2 should sit higher on the chart (smaller y).
      const [first, second] = geo?.dots ?? [];
      expect(second?.y).toBeLessThan(first?.y ?? Infinity);
    });

    it("breaks the line across an unranked day instead of faking a position", () => {
      const history: HistoryPoint[] = [
        { date: "2026-10-12", position: 5 },
        { date: "2026-10-13", position: null },
        { date: "2026-10-14", position: 3 },
      ];
      const geo = rankChartGeometry(history, 100, 30);
      expect(geo).not.toBeNull();
      // Three days -> three slots, but only two ranked dots are drawn.
      expect(geo?.dots).toHaveLength(2);
      // The gap produces a fresh "M" (moveto) for the second ranked point
      // instead of a continuous "L" through the missing day.
      expect(geo?.path.split(" ").filter((seg) => seg.startsWith("M"))).toHaveLength(2);
    });
  });
});
