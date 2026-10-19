/**
 * M3.1: the pricing page states the one public pricing model (MD8): one
 * credit per reel up to 60 s, one per started minute for longer videos, and
 * premium add-ons on their own credits shown before render. It never claims
 * that length does not change the price.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { creditsForSeconds, perReelRows } from "./PerReelPrice";

describe("credits by length", () => {
  it("matches the API table", () => {
    expect([15, 60, 61, 90, 150, 180, 600].map(creditsForSeconds)).toEqual([1, 1, 2, 2, 3, 3, 10]);
  });
});

describe("per-reel copy", () => {
  const source = fs.readFileSync(path.join(__dirname, "PerReelPrice.tsx"), "utf8");

  it("states the per-minute rule and no longer denies length pricing", () => {
    expect(source).toMatch(/one credit per started minute/);
    expect(source).not.toMatch(/Length doesn&apos;t change/);
    expect(source).not.toMatch(/separate credit types/);
  });

  it("the worked example agrees with the table", () => {
    expect(source).toMatch(/2\.5-minute video uses 3/);
    expect(creditsForSeconds(150)).toBe(3);
  });

  it("per-reel rows still come from the pack list", () => {
    const rows = perReelRows([
      { name: "Starter", price: "$19", credits: 30 } as never,
      { name: "Free", price: "$0", credits: 3 } as never,
    ]);
    expect(rows.map((row) => row.perReel)).toEqual(["$0.63", "Free"]);
  });
});
