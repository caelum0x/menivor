import { describe, expect, it } from "vitest";
import {
  INDEXABLE_VERTICAL_SLUGS,
  VERTICALS,
  VERTICAL_SLUGS,
  getVertical,
  isIndexableVertical,
  relatedVerticals,
} from "@/lib/seo/verticals";
import { buildSitemapEntries } from "@/lib/seo/urls";

const allText = (value: unknown): string => JSON.stringify(value);

describe("video-ads verticals", () => {
  it("has about twenty unique verticals, all indexable", () => {
    expect(VERTICALS.length).toBeGreaterThanOrEqual(20);
    expect(new Set(VERTICAL_SLUGS).size).toBe(VERTICAL_SLUGS.length);
    expect(INDEXABLE_VERTICAL_SLUGS).toEqual(VERTICAL_SLUGS);
  });

  it("gives every vertical three unique hooks of its own", () => {
    const lines = VERTICALS.flatMap((vertical) => vertical.hooks.map((hook) => hook.line));
    expect(new Set(lines).size).toBe(lines.length);
    for (const vertical of VERTICALS) expect(vertical.hooks).toHaveLength(3);
  });

  it("marks a thin entry noindex", () => {
    const thin = { ...VERTICALS[0]!, hooks: VERTICALS[0]!.hooks.slice(0, 1) };
    expect(isIndexableVertical(thin)).toBe(false);
  });

  it("never uses fabricated stats, emoji or competitor names", () => {
    const text = allText(VERTICALS);
    expect(text).not.toMatch(/\d+\s?%/);
    expect(text).not.toMatch(/\p{Extended_Pictographic}/u);
    expect(text).not.toMatch(/\b(canva|capcut|invideo|synthesia|heygen|arcads|creatify|veed|zeely)\b/i);
  });

  it("lists indexable pages in the sitemap and cross-links other verticals", () => {
    const urls = buildSitemapEntries(new Date(0)).map((entry) => entry.url);
    expect(urls).toContain("https://menivor.com/video-ads");
    for (const slug of INDEXABLE_VERTICAL_SLUGS) expect(urls).toContain(`https://menivor.com/video-ads/${slug}`);
    const related = relatedVerticals("gym");
    expect(related.length).toBe(6);
    expect(related.some((vertical) => vertical.slug === "gym")).toBe(false);
    expect(getVertical("nope")).toBeUndefined();
  });
});
