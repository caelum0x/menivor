import { describe, expect, it } from "vitest";
import type { LaunchPlatform, PainPointDraft } from "./api";
import {
  backlinksState,
  categoriesFromPlatforms,
  checklistProgressLabel,
  domainLooksValid,
  draftStatusLabel,
  filterPlatformsByCategory,
  nextPlatformStatus,
  platformProgressLabel,
  platformStatusLabel,
  platformStatusTone,
  sortDrafts,
  threadMeta,
} from "./view-model";

const platform = (over: Partial<LaunchPlatform>): LaunchPlatform => ({
  id: "product_hunt", name: "Product Hunt", url: "https://example.com/submit", categories: ["saas"],
  note: "", status: "not_started", submitted_at: null, tracking_note: "",
  ...over,
});

const draft = (over: Partial<PainPointDraft>): PainPointDraft => ({
  id: "d1", product_name: "Menivor", query: "onboarding", subreddit: "saas",
  thread_url: "https://reddit.com/r/saas/comments/abc", thread_title: "Onboarding drop-off",
  snippet: "", upvotes: 10, age_days: 2, draft_reply: "Ran into this too...", status: "drafted",
  created_at: "2026-10-15T00:00:00Z",
  ...over,
});

describe("launch kit view model", () => {
  it("labels platform status honestly", () => {
    expect(platformStatusLabel("not_started")).toBe("Not started");
    expect(platformStatusLabel("submitted")).toBe("Submitted");
    expect(platformStatusLabel("live")).toBe("Live");
  });

  it("cycles platform status not_started -> submitted -> live -> not_started", () => {
    expect(nextPlatformStatus("not_started")).toBe("submitted");
    expect(nextPlatformStatus("submitted")).toBe("live");
    expect(nextPlatformStatus("live")).toBe("not_started");
  });

  it("tones platform status: neutral, informative, done", () => {
    expect(platformStatusTone("not_started")).toBe("outline");
    expect(platformStatusTone("submitted")).toBe("secondary");
    expect(platformStatusTone("live")).toBe("success");
  });

  it("derives sorted unique categories across platforms", () => {
    const platforms = [
      platform({ id: "a", categories: ["saas", "ai"] }),
      platform({ id: "b", categories: ["ai", "dev_tool"] }),
    ];
    expect(categoriesFromPlatforms(platforms)).toEqual(["ai", "dev_tool", "saas"]);
  });

  it("filters platforms by category, or returns all when empty", () => {
    const platforms = [
      platform({ id: "a", categories: ["saas"] }),
      platform({ id: "b", categories: ["ai"] }),
    ];
    expect(filterPlatformsByCategory(platforms, "ai").map((p) => p.id)).toEqual(["b"]);
    expect(filterPlatformsByCategory(platforms, "")).toHaveLength(2);
  });

  it("counts submitted-or-live platforms for the progress label", () => {
    const platforms = [
      platform({ id: "a", status: "submitted" }),
      platform({ id: "b", status: "live" }),
      platform({ id: "c", status: "not_started" }),
    ];
    expect(platformProgressLabel(platforms)).toBe("2 / 3 submitted or live");
  });

  it("formats checklist progress", () => {
    expect(checklistProgressLabel(3, 10)).toBe("3 / 10 steps done");
  });

  it("formats thread meta with singular/plural upvotes and a 'today' floor", () => {
    expect(threadMeta(1, 0)).toBe("1 upvote · today");
    expect(threadMeta(42, 3)).toBe("42 upvotes · 3d old");
  });

  it("labels draft status", () => {
    expect(draftStatusLabel("drafted")).toBe("Drafted");
    expect(draftStatusLabel("approved")).toBe("Approved");
    expect(draftStatusLabel("dismissed")).toBe("Dismissed");
  });

  it("sorts drafts: drafted first, then approved, then dismissed, newest first within a group", () => {
    const drafts = [
      draft({ id: "old-drafted", status: "drafted", created_at: "2026-10-10T00:00:00Z" }),
      draft({ id: "approved", status: "approved", created_at: "2026-10-14T00:00:00Z" }),
      draft({ id: "new-drafted", status: "drafted", created_at: "2026-10-15T00:00:00Z" }),
      draft({ id: "dismissed", status: "dismissed", created_at: "2026-10-13T00:00:00Z" }),
    ];
    expect(sortDrafts(drafts).map((d) => d.id)).toEqual([
      "new-drafted", "old-drafted", "approved", "dismissed",
    ]);
  });

  it("never claims live data when the backend is unconfigured", () => {
    expect(backlinksState({ live: false, configured: false })).toBe("not_configured");
    expect(backlinksState({ live: false, configured: true })).toBe("configured_not_live");
    expect(backlinksState({ live: true, configured: true })).toBe("live_data");
  });

  it("validates a domain looks like a domain, not a free-text string", () => {
    expect(domainLooksValid("example.com")).toBe(true);
    expect(domainLooksValid("not a domain")).toBe(false);
    expect(domainLooksValid("ab")).toBe(false);
    expect(domainLooksValid("")).toBe(false);
  });
});
