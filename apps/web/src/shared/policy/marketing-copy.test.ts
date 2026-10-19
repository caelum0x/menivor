/**
 * M0.3 honesty gate: the public landing, pricing and styles pages (and the
 * shared marketing chrome) carry no vendor, competitor, internal or env names,
 * no presenter promises while presenter is locked, no stale waitlist copy and
 * no unsourced numbers. Rules: policy/copy-denylist.json (vendored verbatim
 * from gtm/policy, see CLAIMS-RULES.md section 4).
 *
 * Two checks:
 * - Always: string literals + JSX text of every first-party file the pages
 *   import (plus the i18n messages they reference).
 * - With COPY_CHECK_BASE_URL set (e.g. http://localhost:3000 after
 *   `next start`, or https://menivor.com after a deploy): the rendered HTML of
 *   each page, which is the acceptance check.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { en } from "@/lib/i18n/dictionaries/en";
import { checkUnits, htmlUnits, selfTest, type CopyHit, type Denylist, type TextUnit } from "./copy-check";
import { reachableFiles, sourceUnits } from "./source-units";
import { ALL_REEL_STYLES, REEL_STYLES, visibleStyles } from "@/lib/styles/catalog";

const WEB_ROOT = path.resolve(__dirname, "../../..");
const DENYLIST_PATH = path.resolve(WEB_ROOT, "../../policy/copy-denylist.json");
const VENDORED_VERSION = "2026-09-29.3";

const list = JSON.parse(fs.readFileSync(DENYLIST_PATH, "utf8")) as Denylist;

/** The real product flag (rule 4.3.4): presenter copy is allowed only when this is on. */
const FLAGS = { PRESENTER_LIVE: process.env.NEXT_PUBLIC_PRESENTER_LIVE ?? process.env.PRESENTER_LIVE };

const PAGES = ["/", "/pricing", "/styles"] as const;

const ENTRIES = [
  "app/layout.tsx",
  "app/(marketing)/layout.tsx",
  "app/(marketing)/page.tsx",
  "app/(marketing)/pricing/page.tsx",
  "app/(marketing)/styles/page.tsx",
];

/**
 * Files reachable by import but not rendered on these pages, with the reason.
 * The SEO content modules render the /tools, /for, /make, /guides, /features,
 * /providers and comparison pages; those pages are a separate honesty pass.
 */
const EXCLUDED_FILES: readonly { readonly pattern: RegExp; readonly reason: string }[] = [
  { pattern: /\.test\.tsx?$/, reason: "tests" },
  { pattern: /^lib\/i18n\/dictionaries\//, reason: "messages are checked per referenced key" },
  { pattern: /^lib\/clerk-appearance\.ts$/, reason: "CSS values for the auth widget" },
  {
    pattern: /^lib\/seo\/(usecases|competitors|guides|make|templates|providers|features|verticals|platforms|graph)\.ts$/,
    reason: "content of the SEO sub-pages, not rendered on /, /pricing or /styles",
  },
  { pattern: /^src\/features\/create-compose\//, reason: "signed-in create flow (app-ui), mounted after sign-in" },
];

/**
 * Units that exist in source but are not rendered in public launch mode, or
 * are ids rather than copy. Each names the rule, file and a substring.
 */
const NOT_RENDERED: readonly { rule: string; file: RegExp; contains: string; reason: string }[] = [
  { rule: "menivor-stale-waitlist", file: /./, contains: "waitlist", reason: "WAITLIST_MODE / waitlist launch mode only" },
  { rule: "menivor-stale-waitlist", file: /./, contains: "early access", reason: "private-beta launch mode only" },
  { rule: "vendor-infra", file: /^lib\/styles\/(catalog|showcase)\.ts$/, contains: ".r2.dev", reason: "media URL, not copy" },
  { rule: "vendor-names", file: /^src\/shared\/payments\/mode\.ts$/, contains: "Creem", reason: "payment line on pricing and billing only (rule 3)" },
  { rule: "vendor-infra", file: /^src\/shared\/payments\/mode\.ts$/, contains: "Dodo", reason: "payment line on pricing and billing only (rule 3)" },
  { rule: "vendor-names", file: /^components\/marketing\/ProviderToggle\.tsx$/, contains: "Creem", reason: "checkout provider picker on /pricing (rule 3)" },
  { rule: "vendor-infra", file: /^components\/marketing\/ProviderToggle\.tsx$/, contains: "Dodo", reason: "checkout provider picker on /pricing (rule 3)" },
  ...["UGC presenter", "An AI presenter pitches", "An AI presenter reacts"].map((contains) => ({
    rule: "menivor-presenter-locked",
    file: /^lib\/styles\/catalog\.ts$/,
    contains,
    reason: "presenter styles, filtered out of REEL_STYLES unless NEXT_PUBLIC_PRESENTER_LIVE=1 (tested below)",
  })),
  { rule: "unlimited-generic", file: /^components\/billing\/format\.ts$/, contains: "Unlimited", reason: "warn only; plan limit label" },
];

function excluded(rel: string): boolean {
  return EXCLUDED_FILES.some(({ pattern }) => pattern.test(rel));
}

function lookup(key: string): unknown {
  return key.split(".").reduce<unknown>((acc, part) => (acc as Record<string, unknown> | undefined)?.[part], en);
}

function notRendered(hit: CopyHit): boolean {
  return NOT_RENDERED.some(
    (entry) =>
      entry.rule === hit.ruleId &&
      entry.file.test(hit.path.replace(/^i18n:.*/, hit.path)) &&
      hit.excerpt.toLowerCase().includes(entry.contains.toLowerCase()),
  );
}

function report(hits: readonly CopyHit[]): string {
  return hits.map((h) => `${h.severity} ${h.ruleId} ${h.path}: ${h.excerpt}`).join("\n");
}

describe("copy denylist (vendored)", () => {
  it("is the vendored version, unedited", () => {
    expect(list.version).toBe(VENDORED_VERSION);
  });

  it("every hit/miss example behaves as labelled in this matcher", () => {
    expect(selfTest(list)).toEqual([]);
  });
});

describe("marketing copy (source)", () => {
  const files = reachableFiles(ENTRIES, WEB_ROOT, excluded);

  it("reaches the landing, pricing and styles components", () => {
    expect(files).toEqual(
      expect.arrayContaining([
        "app/(marketing)/page.tsx",
        "app/(marketing)/pricing/page.tsx",
        "lib/styles/catalog.ts",
        "components/marketing/NewsletterForm.tsx",
      ]),
    );
  });

  it("has no denylisted copy", () => {
    const units: TextUnit[] = [];
    const keys = new Set<string>();
    for (const rel of files) {
      const scan = sourceUnits(fs.readFileSync(path.join(WEB_ROOT, rel), "utf8"), rel);
      units.push(...scan.units);
      scan.keys.forEach((key) => keys.add(key));
    }
    for (const key of keys) {
      const value = lookup(key);
      if (typeof value === "string") units.push({ text: value, path: `i18n:${key}`, surface: "marketing" });
    }
    const hits = checkUnits(list, units, { flags: FLAGS }).filter(
      (hit) => hit.severity === "error" && !notRendered(hit),
    );
    expect(report(hits)).toBe("");
  });
});

describe("presenter styles", () => {
  it("are hidden unless the presenter capability is live", () => {
    expect(ALL_REEL_STYLES.some((style) => style.needsPresenter)).toBe(true);
    expect(visibleStyles(false).some((style) => style.needsPresenter)).toBe(false);
    expect(visibleStyles(true)).toHaveLength(ALL_REEL_STYLES.length);
    if (!FLAGS.PRESENTER_LIVE) expect(REEL_STYLES.some((style) => style.needsPresenter)).toBe(false);
  });
});

const BASE_URL = process.env.COPY_CHECK_BASE_URL;

describe.skipIf(!BASE_URL)("marketing copy (rendered HTML)", () => {
  it.each(PAGES)("%s has no denylisted copy", async (page) => {
    const response = await fetch(`${BASE_URL!.replace(/\/+$/, "")}${page}`);
    expect(response.ok).toBe(true);
    const html = await response.text();
    const hits = checkUnits(list, htmlUnits(html, page), { flags: FLAGS }).filter(
      (hit) => hit.severity === "error",
    );
    expect(report(hits)).toBe("");
  }, 30_000);
});
