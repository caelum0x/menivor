/**
 * /mcp honesty gate (DISTRIBUTION-WAVE funnel fix): the MCP page and its
 * registry manifest state only what works today. Posting to social platforms
 * is closed, so no scheduling or auto-publish promise and no posting tool is
 * listed as available; no copy asks the reader to paste or add a key; the
 * vendored copy denylist passes over every unit the page renders.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { listLiveTools, listTools, PUBLISHING_TOOL_NAMES } from "@/lib/mcp/tools";
import { checkUnits, type Denylist, type TextUnit } from "@/src/shared/policy/copy-check";
import { sourceUnits } from "@/src/shared/policy/source-units";

const WEB_ROOT = path.resolve(__dirname, "../../..");
const list = JSON.parse(fs.readFileSync(path.resolve(WEB_ROOT, "../../policy/copy-denylist.json"), "utf8")) as Denylist;
const FLAGS = { PRESENTER_LIVE: process.env.NEXT_PUBLIC_PRESENTER_LIVE ?? process.env.PRESENTER_LIVE };
const PAGE_FILES = ["app/(marketing)/mcp/page.tsx", "app/(marketing)/mcp/opengraph-image.tsx"];
const POSTING_PROMISE = /\bschedul\w*|auto-publish\w*|\bpublished reel\b|\bpost it for you\b/i;

function pageUnits(): TextUnit[] {
  const units: TextUnit[] = PAGE_FILES.flatMap(
    (rel) => sourceUnits(fs.readFileSync(path.join(WEB_ROOT, rel), "utf8"), rel).units,
  );
  // The tool list is rendered from the catalog, so its names and descriptions are page copy too.
  for (const tool of listLiveTools()) {
    units.push({ text: tool.name, path: "lib/mcp/tools.ts", surface: "marketing" });
    units.push({ text: tool.description, path: "lib/mcp/tools.ts", surface: "marketing" });
  }
  return units;
}

describe("/mcp page copy", () => {
  it("lists no posting tool on the page or in tools/list while the flag is off", () => {
    const previous = process.env.MENIVOR_MCP_PUBLISHING_TOOLS;
    delete process.env.MENIVOR_MCP_PUBLISHING_TOOLS;
    try {
      const shown = listLiveTools().map((tool) => tool.name);
      const served = listTools().map((tool) => tool.name);
      for (const name of PUBLISHING_TOOL_NAMES) {
        expect(shown).not.toContain(name);
        expect(served).not.toContain(name);
      }
      // Turning the MCP flag on serves the tools, but the page still does not list them.
      const enabled = listTools(true);
      expect(listTools(false)).toEqual(enabled.filter((tool) => !PUBLISHING_TOOL_NAMES.has(tool.name)));
      for (const name of PUBLISHING_TOOL_NAMES) {
        expect(enabled.map((tool) => tool.name)).toContain(name);
        expect(shown).not.toContain(name);
      }
      expect(shown).toEqual(expect.arrayContaining(["create_reel", "get_job", "ad_from_url", "generation_quote"]));
    } finally {
      if (previous === undefined) delete process.env.MENIVOR_MCP_PUBLISHING_TOOLS;
      else process.env.MENIVOR_MCP_PUBLISHING_TOOLS = previous;
    }
  });

  it("promises no scheduling or publishing", () => {
    const offending = pageUnits()
      .filter((unit) => POSTING_PROMISE.test(unit.text))
      .filter((unit) => !/^Not yet\. Posting to social platforms is not open/.test(unit.text));
    expect(offending.map((unit) => `${unit.path}: ${unit.text}`)).toEqual([]);
  });

  it("never asks the reader to paste, enter or bring an API key", () => {
    const text = pageUnits().map((unit) => unit.text).join("\n");
    expect(text).not.toMatch(/with your (own )?API key|(paste|enter|add|provide|bring) your (own )?(api[ -]?)?key/i);
  });

  it("passes the vendored copy denylist", () => {
    const hits = checkUnits(list, pageUnits(), { flags: FLAGS }).filter((hit) => hit.severity === "error");
    expect(hits.map((hit) => `${hit.ruleId} ${hit.path}: ${hit.excerpt}`).join("\n")).toBe("");
  });

  it("the registry manifest makes the same claims", () => {
    const manifest = JSON.parse(fs.readFileSync(path.join(WEB_ROOT, "public/server.json"), "utf8")) as { description: string };
    expect(manifest.description).not.toMatch(POSTING_PROMISE);
  });
});
