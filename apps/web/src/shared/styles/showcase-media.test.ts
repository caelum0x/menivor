import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  MEDIA_ORIGIN,
  SHOWCASE_MISSING_FULL_KEYS,
  SHOWCASE_REELS,
  mediaBase,
  showcaseMedia,
} from "@/lib/styles/showcase";

const WEB_ROOT = path.resolve(__dirname, "../../..");
const SOURCES = path.resolve(WEB_ROOT, "../api/tools/ops/showcase/sources.json");

interface SourceReel {
  readonly key: string;
  readonly niche: string;
  readonly loop: { readonly file?: string; readonly id?: string; readonly source: string } | null;
  readonly voice: { readonly name: string };
}

const sources = JSON.parse(readFileSync(SOURCES, "utf8")) as { reels: SourceReel[] };

describe("showcase media origin (M2.1)", () => {
  it("serves every loop, poster and full reel from media.menivor.com, never r2.dev", () => {
    for (const reel of showcaseMedia()) {
      // `full` is null for the known-missing sound variants (SHOWCASE_MISSING_FULL_KEYS):
      // no URL means no dead link ever rendered, so there is nothing to check here.
      for (const url of [reel.mp4, reel.poster, reel.full].filter((value): value is string => value !== null)) {
        expect(url.startsWith(`${MEDIA_ORIGIN}/showcase/`)).toBe(true);
        expect(url).not.toMatch(/r2\.dev/);
      }
    }
  });

  it("ignores an r2.dev override and keeps our media domain", () => {
    const fallback = `${MEDIA_ORIGIN}/showcase`;
    expect(mediaBase("https://pub-abc.r2.dev/marketing/showcase", fallback)).toBe(fallback);
    expect(mediaBase("", fallback)).toBe(fallback);
    expect(mediaBase("https://media.menivor.com/v2/", fallback)).toBe("https://media.menivor.com/v2");
    expect(mediaBase("/samples/showcase", fallback)).toBe("/samples/showcase");
  });

  it("reports no full-reel URL for a known-missing key, so the UI never links to its 404", () => {
    const keys = new Set(SHOWCASE_REELS.map((r) => r.key));
    // Every missing key must be a real catalog entry (catches typos/renames).
    for (const key of SHOWCASE_MISSING_FULL_KEYS) expect(keys.has(key)).toBe(true);
    for (const reel of showcaseMedia()) {
      if (SHOWCASE_MISSING_FULL_KEYS.has(reel.key)) {
        expect(reel.full).toBeNull();
      } else {
        expect(reel.full).not.toBeNull();
      }
    }
  });

  it("ships a same-origin fallback loop and poster for every reel", () => {
    for (const reel of showcaseMedia()) {
      expect(existsSync(path.join(WEB_ROOT, "public", reel.fallbackMp4))).toBe(true);
      expect(existsSync(path.join(WEB_ROOT, "public", reel.fallbackPoster))).toBe(true);
    }
  });
});

describe("showcase variety rules (M2.1)", () => {
  it("lists the same reels as the render plan's sources.json", () => {
    expect(new Set(SHOWCASE_REELS.map((r) => r.key))).toEqual(new Set(sources.reels.map((r) => r.key)));
  });

  it("gives every reel its own niche", () => {
    const niches = SHOWCASE_REELS.map((r) => r.niche.toLowerCase());
    expect(new Set(niches).size).toBe(niches.length);
  });

  it("never shares a background loop or narrator voice between two reels", () => {
    const persona = (name: string) => name.replace(/(Multilingual)?Neural$/, "").toLowerCase();
    const voices = sources.reels.map((r) => persona(r.voice.name));
    expect(new Set(voices).size).toBe(voices.length);
    const loops = sources.reels
      .filter((r) => r.loop && r.loop.source !== "footage montage")
      .map((r) => r.loop?.file ?? r.loop?.id);
    expect(new Set(loops).size).toBe(loops.length);
  });

  it("advertises at most two of our own products", () => {
    expect(SHOWCASE_REELS.filter((r) => r.ownProduct).length).toBeLessThanOrEqual(2);
  });
});
