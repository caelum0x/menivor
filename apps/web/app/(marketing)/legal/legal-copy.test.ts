/**
 * P-A3 copy lint for the legal and privacy pages (M7.1, M7.3).
 *
 * These pages are the "legal" surface of CLAIMS-RULES.md (terms, privacy,
 * DPA, subprocessors, licence pages), which is exempt from most rules on
 * purpose: it must name vendors and state response times. The rules that still
 * apply there (secrets, region choice) are checked, and so are the owner's
 * standing rules for every surface: no emoji and no "indie" audience wording.
 * Rules: policy/copy-denylist.json (vendored).
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { checkUnits, type CopyHit, type Denylist, type TextUnit } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";

const WEB_ROOT = path.resolve(__dirname, "../../..");
const list = JSON.parse(
  fs.readFileSync(path.resolve(WEB_ROOT, "../../policy/copy-denylist.json"), "utf8"),
) as Denylist;

const ROOTS = ["app/(marketing)/legal", "app/(marketing)/privacy"];
const EVERY_SURFACE_RULES = new Set(["emoji", "indie-audience"]);

function sources(dir: string): string[] {
  const abs = path.join(WEB_ROOT, dir);
  if (!fs.existsSync(abs)) return [];
  return fs.readdirSync(abs, { withFileTypes: true }).flatMap((entry) => {
    const rel = path.join(dir, entry.name);
    if (entry.isDirectory()) return sources(rel);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [rel] : [];
  });
}

function units(files: readonly string[], surface: "legal" | "docs"): TextUnit[] {
  return files.flatMap(
    (rel) => sourceUnits(fs.readFileSync(path.join(WEB_ROOT, rel), "utf8"), rel, surface).units,
  );
}

function report(hits: readonly CopyHit[]): string {
  return hits.map((h) => `${h.ruleId} ${h.path}: ${h.excerpt}`).join("\n");
}

describe("legal and privacy copy", () => {
  const files = ROOTS.flatMap(sources);

  it("covers the legal pages", () => {
    expect(files).toEqual(
      expect.arrayContaining([
        "app/(marketing)/legal/content-credentials/page.tsx",
        "app/(marketing)/legal/subprocessors/page.tsx",
        "app/(marketing)/legal/subprocessors/subprocessors.ts",
        "app/(marketing)/legal/data-requests/page.tsx",
        "app/(marketing)/privacy/page.tsx",
      ]),
    );
  });

  it("breaks no rule of the legal surface", () => {
    const hits = checkUnits(list, units(files, "legal")).filter((hit) => hit.severity === "error");
    expect(report(hits)).toBe("");
  });

  it("has no emoji and no indie wording", () => {
    const hits = checkUnits(list, units(files, "docs")).filter((hit) => EVERY_SURFACE_RULES.has(hit.ruleId));
    expect(report(hits)).toBe("");
  });
});
