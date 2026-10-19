import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { buildSitemapEntries } from "@/lib/seo/urls";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";

const WEB_ROOT = path.resolve(__dirname, "../../..");
const DENYLIST = JSON.parse(
  fs.readFileSync(path.resolve(WEB_ROOT, "../../policy/copy-denylist.json"), "utf8"),
) as Denylist;

const FILES = [
  "app/(marketing)/about/page.tsx",
  "app/(marketing)/about/family.ts",
  "app/(marketing)/press/page.tsx",
  "app/(marketing)/press/assets.ts",
  "lib/seo/entity.ts",
];

describe("MB2 /about and /press", () => {
  it("are in the sitemap", () => {
    const urls = buildSitemapEntries(new Date(0)).map((e) => e.url);
    expect(urls).toContain("https://menivor.com/about");
    expect(urls).toContain("https://menivor.com/press");
  });

  it("pass the copy denylist", () => {
    const units = FILES.flatMap(
      (rel) => sourceUnits(fs.readFileSync(path.join(WEB_ROOT, rel), "utf8"), rel).units,
    );
    expect(units.length).toBeGreaterThan(5);
    const hits = checkUnits(DENYLIST, units, { flags: {} }).filter((h) => h.severity === "error");
    expect(hits).toEqual([]);
  });

  it("link only brand and sample files that exist", async () => {
    const { LOGO_FILES, SAMPLE_REELS } = await import("../press/assets");
    for (const file of LOGO_FILES) {
      expect(fs.existsSync(path.join(WEB_ROOT, "public", file.href)), file.href).toBe(true);
    }
    for (const reel of SAMPLE_REELS) {
      for (const suffix of [".mp4", "-poster.jpg"]) {
        const rel = `public/samples/showcase/${reel.slug}${suffix}`;
        expect(fs.existsSync(path.join(WEB_ROOT, rel)), rel).toBe(true);
      }
    }
  });

  it("carry no legal or founder name until owner item 17", () => {
    const rendered = FILES.flatMap(
      (rel) => sourceUnits(fs.readFileSync(path.join(WEB_ROOT, rel), "utf8"), rel).units,
    ).map((u) => u.text);
    for (const text of rendered) {
      expect(text).not.toMatch(/\b(Ltd|LLC|Inc\.|A\.S\.|founder|founded by)\b/i);
    }
  });
});
