import { describe, expect, it } from "vitest";
import { chartGeometry, postLine, presetLabel, remakeHref, shortCount } from "./view-model";
import type { TrackedPost } from "./api";

const post = (over: Partial<TrackedPost>): TrackedPost => ({
  id: "p", platform: "tiktok", label: "TikTok", url: "", title: "", from_menivor: true, state: "tracking",
  note: "", views: null, likes: null, comments: null, shares: null, saves: null, last_checked_at: null,
  can_type_numbers: false, ...over,
});

describe("results view model", () => {
  it("never turns an unknown number into 0", () => {
    expect(shortCount(null)).toBe("");
    expect(shortCount(12400)).toBe("12.4K");
    expect(postLine(post({ likes: 5, saves: null }))).toBe("5 likes");
    expect(postLine(post({ note: "Reconnect TikTok" }))).toBe("Reconnect TikTok");
  });

  it("builds the make-more link from the winning topic and style", () => {
    expect(remakeHref({ q: "Morning routine", preset: "meme_hook" })).toBe(
      "/create?q=Morning+routine&preset=meme_hook&auto=1",
    );
    expect(remakeHref({ q: "Topic", preset: "not-a-style" })).toBe("/create?q=Topic&auto=1");
    expect(remakeHref({ q: " ", preset: "" })).toBe("/create");
    expect(presetLabel("meme_hook")).toBe("Meme hook");
    expect(presetLabel("")).toBe("");
  });

  it("draws a chart only with two or more days", () => {
    expect(chartGeometry([{ date: "2026-09-27", views: 5 }], 100, 50)).toBeNull();
    const geo = chartGeometry(
      [{ date: "2026-09-26", views: 0 }, { date: "2026-09-27", views: 10 }],
      100,
      50,
    );
    expect(geo?.line).toBe("M0.0,44.0 L100.0,6.0");
    expect(geo?.max).toBe(10);
  });
});
