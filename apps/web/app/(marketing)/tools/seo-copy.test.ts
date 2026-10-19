/**
 * MV-SEO1 honesty gate for the SEO sub-pages: /tools, /for, /make, /guides,
 * /providers, /video-ads, /features, the model comparison page and the
 * site-wide metadata. Same vendored denylist and scanner as the landing gate
 * (src/shared/policy/marketing-copy.test.ts): no competitor, vendor or
 * internal names, no presenter or lip-sync promises while the avatar format
 * is locked, no unsourced numbers. Pages are rewritten, never removed: the
 * sitemap keeps every URL it had before the pass.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { en } from "@/lib/i18n/dictionaries/en";
import { buildSitemapEntries, pageExists } from "@/lib/seo";
import { checkUnits, type CopyHit, type Denylist, type TextUnit } from "@/src/shared/policy/copy-check";
import { reachableFiles, sourceUnits } from "@/src/shared/policy/source-units";

const WEB_ROOT = path.resolve(__dirname, "../../..");
const DENYLIST_PATH = path.resolve(WEB_ROOT, "../../policy/copy-denylist.json");
const SITEMAP_BEFORE = path.resolve(__dirname, "sitemap-urls.before.json");
const list = JSON.parse(fs.readFileSync(DENYLIST_PATH, "utf8")) as Denylist;
const FLAGS = { PRESENTER_LIVE: process.env.NEXT_PUBLIC_PRESENTER_LIVE ?? process.env.PRESENTER_LIVE };

const SEO_DIRS = ["tools", "for", "make", "guides", "providers", "video-ads", "features"] as const;

function pageEntries(): string[] {
  const out: string[] = ["app/layout.tsx", "app/models/compare/page.tsx"];
  const walk = (dir: string) => {
    for (const name of fs.readdirSync(path.join(WEB_ROOT, dir))) {
      const rel = path.join(dir, name);
      if (fs.statSync(path.join(WEB_ROOT, rel)).isDirectory()) walk(rel);
      else if (/^(page|opengraph-image)\.tsx$/.test(name)) out.push(rel);
    }
  };
  for (const dir of SEO_DIRS) walk(`app/(marketing)/${dir}`);
  return out;
}

/**
 * Reachable files that are shared chrome or app code, checked by the landing
 * gate or owned elsewhere; this gate covers the SEO content itself.
 */
const EXCLUDED: readonly RegExp[] = [
  /\.test\.tsx?$/,
  /^lib\/i18n\/dictionaries\//,
  /^lib\/clerk-appearance\.ts$/,
  /^src\/features\/create-compose\//,
  /^components\/ui\//,
  /^lib\/(utils|site-url|env)\.ts$/,
];

/**
 * Internal datasets that no page renders: there is no /vs, /alternatives or
 * /templates route, and the graph's dead-link guard drops every link to one
 * (proved below). They stop being excluded the moment such a route exists.
 */
const UNRENDERED_ROUTES = ["vs", "alternatives", "templates"] as const;
const UNRENDERED_DATA: readonly RegExp[] = [/^lib\/seo\/competitors\.ts$/, /^lib\/seo\/templates\.ts$/];

function routeExists(segment: string): boolean {
  return (
    fs.existsSync(path.join(WEB_ROOT, "app", "(marketing)", segment)) ||
    fs.existsSync(path.join(WEB_ROOT, "app", segment))
  );
}

/** Units present in source but not rendered in public launch mode, or not copy. */
const NOT_RENDERED: readonly { rule: string; file: RegExp; contains: string; reason: string }[] = [
  ...["waitlist", "early access"].map((contains) => ({
    rule: "menivor-stale-waitlist",
    file: /^(lib\/seo\/site\.ts|lib\/waitlist\.ts|components\/marketing\/WaitlistForm\.tsx|app\/beta\/|app\/\(marketing\)\/_components\/ReadinessCta\.tsx|src\/shared\/launch-posture\/posture\.ts)/,
    contains,
    reason: "waitlist or beta launch mode only (same rule as the landing gate)",
  })),
  ...["UGC presenter", "An AI presenter pitches", "An AI presenter reacts"].map((contains) => ({
    rule: "menivor-presenter-locked",
    file: /^lib\/styles\/catalog\.ts$/,
    contains,
    reason: "presenter styles, filtered out of REEL_STYLES unless NEXT_PUBLIC_PRESENTER_LIVE=1",
  })),
  { rule: "number-percent-claim", file: /^lib\/seo\/og\.tsx$/, contains: "100%", reason: "CSS size, not copy" },
  ...["kokoro-js@", "Kokoro-82M"].map((contains) => ({
    rule: "vendor-names",
    file: /^components\/marketing\/free-tools\/browser-workers\.ts$/,
    contains,
    reason: "CDN module URL and model id the in-browser worker loads, never rendered",
  })),
];

/**
 * Copy in files outside MV-SEO1's ownership (Wave C section 7). Listed so the
 * gate stays green on MV-SEO1's files and the hand-off stays visible.
 * Empty since the features index copy was rewritten.
 */
const HAND_OFFS: readonly { rule: string; file: RegExp; contains: string; owner: string }[] = [];

function allowed(hit: CopyHit): boolean {
  const matches = (entry: { rule: string; file: RegExp; contains: string }) =>
    entry.rule === hit.ruleId && entry.file.test(hit.path) && hit.excerpt.toLowerCase().includes(entry.contains.toLowerCase());
  return NOT_RENDERED.some(matches) || HAND_OFFS.some(matches);
}

function scan(): { hits: CopyHit[]; files: string[] } {
  const unrendered = UNRENDERED_ROUTES.some(routeExists) ? [] : UNRENDERED_DATA;
  const skip = [...EXCLUDED, ...unrendered];
  const files = reachableFiles(pageEntries(), WEB_ROOT, (rel) => skip.some((re) => re.test(rel)));
  const units: TextUnit[] = [];
  const keys = new Set<string>();
  for (const rel of files) {
    const result = sourceUnits(fs.readFileSync(path.join(WEB_ROOT, rel), "utf8"), rel);
    units.push(...result.units);
    result.keys.forEach((key) => keys.add(key));
  }
  for (const key of keys) {
    const value = key.split(".").reduce<unknown>((acc, part) => (acc as Record<string, unknown> | undefined)?.[part], en);
    if (typeof value === "string") units.push({ text: value, path: `i18n:${key}`, surface: "marketing" });
  }
  const hits = checkUnits(list, units, { flags: FLAGS }).filter((hit) => hit.severity === "error" && !allowed(hit));
  return { hits, files };
}

describe("internal datasets are not rendered", () => {
  it("has no /vs, /alternatives or /templates route", () => {
    for (const segment of UNRENDERED_ROUTES) expect(routeExists(segment)).toBe(false);
  });

  it("the dead-link guard drops every link into them", () => {
    expect(pageExists("/vs/any")).toBe(false);
    expect(pageExists("/alternatives/any")).toBe(false);
    expect(pageExists("/templates/any")).toBe(false);
  });

  it("no page imports the competitor or template data directly", () => {
    for (const rel of pageEntries()) {
      const code = fs.readFileSync(path.join(WEB_ROOT, rel), "utf8");
      expect(code, rel).not.toMatch(/\b(COMPETITORS|COMPETITOR_PRICING|getCompetitor|REEL_TEMPLATES|getReelTemplate)\b/);
    }
  });
});

describe("SEO sub-pages copy (MV-SEO1)", () => {
  const { hits, files } = scan();

  it("reaches the SEO content modules", () => {
    expect(files).toEqual(
      expect.arrayContaining([
        "lib/seo/usecases.ts",
        "lib/seo/providers.ts",
        "lib/seo/guides.ts",
        "lib/seo/make.ts",
        "lib/seo/platforms.ts",
        "lib/seo/verticals.ts",
        "lib/seo/features.ts",
        "app/models/compare/page.tsx",
      ]),
    );
  });

  it("has no denylisted copy", () => {
    expect(hits.map((h) => `${h.ruleId} ${h.path}: ${h.excerpt}`).join("\n")).toBe("");
  });

});

describe("site metadata (LIVE-QA M-3)", () => {
  it("sells no avatar presenters or lip-sync in the meta tags", () => {
    const layout = fs.readFileSync(path.join(WEB_ROOT, "app/layout.tsx"), "utf8");
    expect(layout).not.toMatch(/avatar presenters?|lip-?synced|presenter/i);
  });

  it("the dictionary carries no presenter or lip-sync promise", () => {
    const json = JSON.stringify(en);
    expect(json).not.toMatch(/lip-?synced|avatar presenters?/i);
  });
});

describe("pages are rewritten, never removed", () => {
  it("keeps every sitemap URL", () => {
    const before = JSON.parse(fs.readFileSync(SITEMAP_BEFORE, "utf8")) as string[];
    const now = buildSitemapEntries(new Date(0)).map((entry) => entry.url.replace(/^https?:\/\/[^/]+/, ""));
    expect(now.length).toBe(before.length);
    expect([...now].sort()).toEqual([...before].sort());
  });
});
