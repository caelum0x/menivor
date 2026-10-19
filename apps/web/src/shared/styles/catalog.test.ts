import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { REEL_STYLES, findStyle, isStyleId, styleCreateHref } from "@/lib/styles/catalog";
import {
  SHOWCASE_BASE_URL,
  SHOWCASE_MISSING_FULL_KEYS,
  SHOWCASE_REELS,
  VOICEOVER_LABEL,
  allocateStyleGallery,
  showcaseCredit,
  showcaseLayout,
  showcaseMedia,
  showcaseStyles,
} from "@/lib/styles/showcase";

const SAMPLE_DIR = path.join(process.cwd(), "public", "samples", "showcase");
const OWN_PRODUCTS = /menivor|scribase|vcpeer|rally|recoder/i;

describe("reel styles catalog", () => {
  it("has unique ids and never calls a style a template", () => {
    const ids = REEL_STYLES.map((style) => style.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const style of REEL_STYLES) {
      expect(`${style.label} ${style.blurb}`.toLowerCase()).not.toContain("template");
      expect(style.hookFamily.length).toBeGreaterThan(0);
      expect(style.needsPresenter).toBe(style.layout !== "captions_only");
    }
  });

  it("covers the viral formats", () => {
    for (const id of ["gameplay_split", "meme_hook", "anime", "before_after", "pov_text"]) {
      expect(isStyleId(id)).toBe(true);
    }
    expect(isStyleId("minecraft")).toBe(false);
    expect(findStyle("meme_hook")?.hookFamily).toContain("met_me_at");
  });

  it("builds a create deep link that preselects the style", () => {
    expect(styleCreateHref("anime")).toBe("/create?preset=anime");
    expect(styleCreateHref("meme_hook", "https://a.com")).toBe(
      "/create?preset=meme_hook&q=https%3A%2F%2Fa.com",
    );
  });
});

describe("showcase reels", () => {
  it("has a varied set: 24 to 36 reels, unique keys, unique opening lines", () => {
    expect(SHOWCASE_REELS.length).toBeGreaterThanOrEqual(24);
    expect(SHOWCASE_REELS.length).toBeLessThanOrEqual(36);
    const keys = SHOWCASE_REELS.map((reel) => reel.key);
    expect(new Set(keys).size).toBe(keys.length);
    const hooks = SHOWCASE_REELS.map((reel) => reel.hook.toLowerCase());
    expect(new Set(hooks).size).toBe(hooks.length);
  });

  it("advertises our own products at most twice, each in a different style", () => {
    const own = SHOWCASE_REELS.filter(
      (reel) => reel.ownProduct || OWN_PRODUCTS.test(`${reel.niche} ${reel.hook}`),
    );
    expect(own.length).toBeLessThanOrEqual(2);
    expect(new Set(own.map((reel) => reel.styleId)).size).toBe(own.length);
    for (const reel of own) expect(reel.ownProduct).toBeTruthy();
  });

  it("spreads across styles and never lets one style dominate", () => {
    const counts = new Map<string, number>();
    for (const reel of SHOWCASE_REELS) {
      const label = reel.styleId ?? VOICEOVER_LABEL;
      counts.set(label, (counts.get(label) ?? 0) + 1);
      if (reel.styleId) expect(isStyleId(reel.styleId)).toBe(true);
    }
    expect(counts.size).toBeGreaterThanOrEqual(7);
    for (const count of counts.values()) expect(count).toBeLessThanOrEqual(8);
  });

  it("labels every reel honestly", () => {
    for (const reel of SHOWCASE_REELS) {
      const credit = showcaseCredit(reel);
      if (reel.ownProduct) expect(credit).toMatch(/our own product/i);
      else expect(credit).toMatch(/^Example .+, stock footage$/);
    }
  });

  it("builds media URLs for the loop, poster and full reel", () => {
    for (const reel of showcaseMedia()) {
      expect(reel.mp4).toBe(`${SHOWCASE_BASE_URL}/${reel.key}.mp4`);
      expect(reel.poster).toMatch(/-poster\.jpg$/);
      // null for the known-missing sound variants (SHOWCASE_MISSING_FULL_KEYS):
      // no URL means the UI never links to their 404.
      if (SHOWCASE_MISSING_FULL_KEYS.has(reel.key)) {
        expect(reel.full).toBeNull();
      } else {
        expect(reel.full).toMatch(new RegExp(`/${reel.key}-full\\.mp4$`));
      }
      expect(reel.label.length).toBeGreaterThan(0);
    }
  });
});

describe("landing layout", () => {
  it("shows every reel exactly once", () => {
    const { hero, heroSide, groups } = showcaseLayout();
    const keys = [hero, ...heroSide, ...groups.flatMap((group) => group.reels)].map((r) => r.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.length).toBe(SHOWCASE_REELS.length);
    expect(heroSide.length).toBe(2);
    for (const group of groups) expect(group.reels.length).toBeGreaterThan(0);
  });

  it("gives every showcased style one gallery card and never repeats a reel", () => {
    const { cards, rest } = allocateStyleGallery();
    expect(cards.map((card) => card.style.id)).toEqual(showcaseStyles().map((style) => style.id));
    for (const card of cards) expect(card.reel.styleId).toBe(card.style.id);
    const keys = [...cards.map((card) => card.reel.key), ...rest.map((reel) => reel.key)];
    expect(new Set(keys).size).toBe(SHOWCASE_REELS.length);
  });
});

describe("shipped showcase files", () => {
  it("ships a distinct, small loop and a poster for every reel", () => {
    const hashes = new Map<string, string>();
    for (const reel of SHOWCASE_REELS) {
      const file = path.join(SAMPLE_DIR, `${reel.key}.mp4`);
      expect(fs.existsSync(file), file).toBe(true);
      const bytes = fs.readFileSync(file);
      expect(bytes.byteLength, `${reel.key} loop too large`).toBeLessThan(1.5 * 1024 * 1024);
      const digest = crypto.createHash("sha256").update(bytes).digest("hex");
      expect(hashes.get(digest), `${reel.key} duplicates ${hashes.get(digest)}`).toBeUndefined();
      hashes.set(digest, reel.key);
      expect(fs.existsSync(path.join(SAMPLE_DIR, `${reel.key}-poster.jpg`))).toBe(true);
    }
  });
});
