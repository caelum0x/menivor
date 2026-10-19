import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { checkUnits, type Denylist } from "@/src/shared/policy/copy-check";
import { offersFromPlanConfig } from "./entity";
import { buildLlmsText, llmsFlagsFromEnv } from "./llms";

const DENYLIST = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../../policy/copy-denylist.json"), "utf8"),
) as Denylist;

const OFF = { presenterLive: false, publishingLive: false } as const;
const GATED = /\b(presenters?|lip[- ]?sync(ed)?|avatars?|talking head|publish(ing)?|schedul(e|ing) posts?)\b/i;

describe("MA2 llms.txt", () => {
  it("names no flag-gated feature while the flags are off", () => {
    const text = buildLlmsText({ flags: OFF });
    expect(text).not.toMatch(GATED);
  });

  it("reads the flags from the environment, off by default", () => {
    expect(llmsFlagsFromEnv({})).toEqual(OFF);
    expect(llmsFlagsFromEnv({ NEXT_PUBLIC_PRESENTER_LIVE: "1", NEXT_PUBLIC_PUBLISHING_LIVE: "true" })).toEqual({
      presenterLive: true,
      publishingLive: true,
    });
  });

  it("describes a gated feature only when its flag is on", () => {
    expect(buildLlmsText({ flags: { ...OFF, presenterLive: true } })).toMatch(/lip-synced/);
    expect(buildLlmsText({ flags: { ...OFF, publishingLive: true } })).toMatch(/Publishing:/);
  });

  it("lists prices from plan config", () => {
    const offers = offersFromPlanConfig();
    const text = buildLlmsText({ flags: OFF, offers });
    for (const offer of offers) expect(text).toContain(offer.name);
    const typed = [
      { "@type": "Offer", name: "Test pack", price: "23.00", priceCurrency: "USD", description: "x.", url: "u" },
    ] as const;
    expect(buildLlmsText({ flags: OFF, offers: typed })).toContain("Test pack: $23.");
  });

  it("is plain markdown with the canonical links", () => {
    const text = buildLlmsText({ flags: OFF });
    expect(text.startsWith("# Menivor\n")).toBe(true);
    for (const p of ["/pricing", "/about", "/press", "/mcp"]) expect(text).toContain(`https://menivor.com${p}`);
    expect(text).not.toMatch(/<[a-z]/i);
  });

  it("passes the copy denylist with the flags off", () => {
    const units = buildLlmsText({ flags: OFF })
      .split("\n")
      .filter(Boolean)
      .map((line) => ({ text: line, path: "app/llms.txt/route.ts", surface: "marketing" as const }));
    const hits = checkUnits(DENYLIST, units, { flags: {} }).filter((h) => h.severity === "error");
    expect(hits).toEqual([]);
  });
});
