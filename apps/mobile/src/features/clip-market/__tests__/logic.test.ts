/**
 * Unit tests for the ClipMarket pure logic: USD↔micros conversion, campaign +
 * review form validation, clip-URL guarding, lifecycle transitions, and spend
 * aggregation. No network, no renderer — pure functions only.
 */

import { describe, expect, it } from "vitest";
import type { Campaign } from "@/lib/clipmarket";
import {
  USD_TO_MICROS,
  isHttpUrl,
  parseCampaignForm,
  parseReviewForm,
  statusActions,
  summarizeSpend,
  usdToMicros,
} from "../logic";

describe("usdToMicros", () => {
  it("converts a decimal USD string to integer micros", () => {
    expect(usdToMicros("1")).toBe(1_000_000);
    expect(usdToMicros("2.50")).toBe(2_500_000);
    expect(usdToMicros(" 0 ")).toBe(0);
  });

  it("rejects blanks, negatives, and non-numbers", () => {
    expect(usdToMicros("")).toBeNull();
    expect(usdToMicros("-3")).toBeNull();
    expect(usdToMicros("abc")).toBeNull();
  });
});

describe("parseCampaignForm", () => {
  it("builds a CreateCampaignBody with micros + trimmed title + min_views", () => {
    const result = parseCampaignForm({
      title: "  Summer push  ",
      cpmUsd: "3",
      budgetUsd: "100",
      minViews: "500",
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toEqual({
        title: "Summer push",
        cpm_micros: 3 * USD_TO_MICROS,
        budget_micros: 100 * USD_TO_MICROS,
        min_views: 500,
      });
    }
  });

  it("omits an empty title and omits min_views when blank", () => {
    const result = parseCampaignForm({ title: "", cpmUsd: "1", budgetUsd: "10" });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toEqual({
        cpm_micros: 1_000_000,
        budget_micros: 10_000_000,
      });
    }
  });

  it("rejects a non-positive CPM or budget", () => {
    expect(parseCampaignForm({ title: "", cpmUsd: "0", budgetUsd: "10" }).ok).toBe(false);
    expect(parseCampaignForm({ title: "", cpmUsd: "1", budgetUsd: "0" }).ok).toBe(false);
  });

  it("rejects a fractional min_views", () => {
    const result = parseCampaignForm({
      title: "",
      cpmUsd: "1",
      budgetUsd: "10",
      minViews: "1.5",
    });
    expect(result.ok).toBe(false);
  });
});

describe("isHttpUrl", () => {
  it("accepts absolute http(s) URLs", () => {
    expect(isHttpUrl("https://youtu.be/abc")).toBe(true);
    expect(isHttpUrl(" http://example.com/x ")).toBe(true);
  });

  it("rejects blanks, relative paths, and non-http schemes", () => {
    expect(isHttpUrl("")).toBe(false);
    expect(isHttpUrl("/clips/1")).toBe(false);
    expect(isHttpUrl("ftp://host/f")).toBe(false);
  });
});

describe("statusActions", () => {
  it("offers pause + end for an active campaign", () => {
    expect(statusActions("active")).toEqual([
      { status: "paused", label: "Pause" },
      { status: "ended", label: "End" },
    ]);
  });

  it("offers resume + end for a paused campaign", () => {
    expect(statusActions("paused")).toEqual([
      { status: "active", label: "Resume" },
      { status: "ended", label: "End" },
    ]);
  });

  it("offers no transitions for an ended (terminal) campaign", () => {
    expect(statusActions("ended")).toEqual([]);
  });
});

describe("summarizeSpend", () => {
  const campaign = (over: Partial<Campaign>): Campaign => ({
    id: "c",
    title: "t",
    cpm_micros: 0,
    budget_micros: 0,
    spent_micros: 0,
    status: "active",
    ...over,
  });

  it("sums spend + budget, clamps remaining at 0, and counts active", () => {
    const summary = summarizeSpend([
      campaign({ id: "a", spent_micros: 30, budget_micros: 100, status: "active" }),
      campaign({ id: "b", spent_micros: 80, budget_micros: 50, status: "paused" }),
    ]);
    expect(summary.totalSpentMicros).toBe(110);
    expect(summary.totalBudgetMicros).toBe(150);
    expect(summary.remainingMicros).toBe(40);
    expect(summary.activeCount).toBe(1);
    expect(summary.campaignCount).toBe(2);
  });

  it("returns zeros for an empty portfolio", () => {
    const summary = summarizeSpend([]);
    expect(summary.totalSpentMicros).toBe(0);
    expect(summary.remainingMicros).toBe(0);
    expect(summary.activeCount).toBe(0);
  });
});

describe("parseReviewForm", () => {
  it("requires views and includes only supplied signals", () => {
    const result = parseReviewForm({
      views: "1200",
      velocityZscore: "2.1",
      engagementRate: "0.08",
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toEqual({
        views: 1200,
        velocity_zscore: 2.1,
        engagement_rate: 0.08,
      });
    }
  });

  it("rejects a missing or fractional view count", () => {
    expect(parseReviewForm({ views: "" }).ok).toBe(false);
    expect(parseReviewForm({ views: "1.5" }).ok).toBe(false);
    expect(parseReviewForm({ views: "-1" }).ok).toBe(false);
  });

  it("rejects a non-numeric fraud signal", () => {
    const result = parseReviewForm({ views: "10", geoConcentration: "high" });
    expect(result.ok).toBe(false);
  });
});
