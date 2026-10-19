import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { PRICING_PLANS } from "@/components/marketing/plans";
import { FALLBACK_CATALOG, type MonthlyCatalog } from "@/src/features/plans/api";
import { softwareApplicationLd } from "./jsonld";
import {
  BRAND_HANDLES,
  OWNER_ITEM_17_PENDING,
  PRESS_DESCRIPTION_LONG,
  PRESS_DESCRIPTION_SHORT,
  cardCheckDollars,
  liveHandles,
  offersFromPlanConfig,
  organizationLd,
  planConfigPrices,
  siteEntityGraph,
  type OfferSources,
} from "./entity";

const WEB_ROOT = path.resolve(__dirname, "../..");

function collectPrices(node: unknown, out: string[] = []): string[] {
  if (Array.isArray(node)) node.forEach((n) => collectPrices(n, out));
  else if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) {
      if (key === "price") out.push(String(value));
      else collectPrices(value, out);
    }
  }
  return out;
}

const onSale: MonthlyCatalog = {
  ...FALLBACK_CATALOG,
  plans: FALLBACK_CATALOG.plans.map((p) => ({ ...p, available: { month: true, year: false } })),
};
const sources = (over: Partial<OfferSources> = {}): OfferSources => ({
  paymentsPaused: false,
  cardCheck: cardCheckDollars("A $1 card check unlocks 3 free reels."),
  packs: PRICING_PLANS,
  monthly: onSale,
  ...over,
});

describe("MB1 entity graph", () => {
  it("never declares a price of 0 or a 'Free account' offer", () => {
    const json = JSON.stringify(siteEntityGraph());
    expect(json).not.toMatch(/"price":"0(\.00)?"/);
    expect(json).not.toMatch(/Free account/i);
    expect(JSON.stringify(softwareApplicationLd())).not.toMatch(/"price":"0(\.00)?"/);
  });

  it("every JSON-LD price comes from plan config", () => {
    const allowed = planConfigPrices(sources());
    const prices = collectPrices(siteEntityGraph(sources()));
    expect(prices.length).toBeGreaterThan(0);
    for (const price of prices) expect(allowed.has(price)).toBe(true);
    // The rendered offers follow plan config when it changes.
    const cheaper = PRICING_PLANS.map((p) => (p.price === "$19" ? { ...p, price: "$17" } : p));
    const moved = offersFromPlanConfig(sources({ packs: cheaper }));
    expect(moved.map((o) => o.price)).toContain("17.00");
  });

  it("orders the card check, the lowest pack, then the lowest monthly plan on sale", () => {
    const offers = offersFromPlanConfig(sources());
    expect(offers.map((o) => o.name)).toEqual(["Card check", "Starter pack", "Creator monthly plan"]);
    expect(offers.map((o) => o.price)).toEqual(["1.00", "19.00", "15.00"]);
  });

  it("drops the card check while payments are paused and monthly plans not on sale", () => {
    const offers = offersFromPlanConfig(
      sources({ paymentsPaused: true, cardCheck: null, monthly: FALLBACK_CATALOG }),
    );
    expect(offers.map((o) => o.name)).toEqual(["Starter pack"]);
  });

  it("fails on a typed price in the JSON-LD sources", () => {
    for (const rel of ["lib/seo/entity.ts", "lib/seo/jsonld.ts", "app/layout.tsx"]) {
      const text = fs.readFileSync(path.join(WEB_ROOT, rel), "utf8");
      expect(text, rel).not.toMatch(/price:\s*["'`]\s*\$?\d/);
      expect(text, rel).not.toMatch(/priceCurrency:[^\n]*\n[^\n]*price:\s*\d/);
    }
  });

  it("sameAs renders only handles marked live", () => {
    expect(organizationLd().sameAs ?? []).toEqual(liveHandles());
    const mixed = [
      { platform: "X", url: "https://x.com/menivor", live: true },
      { platform: "TikTok", url: "https://www.tiktok.com/@menivor", live: false },
    ];
    expect(organizationLd(mixed).sameAs).toEqual(["https://x.com/menivor"]);
    const none = BRAND_HANDLES.map((h) => ({ ...h, live: false }));
    expect("sameAs" in organizationLd(none)).toBe(false);
  });

  it("names the product only until owner item 17 is answered", () => {
    expect(OWNER_ITEM_17_PENDING).toBe(true);
    const org = organizationLd() as Record<string, unknown>;
    expect(org.legalName).toBeUndefined();
    expect(org.founder).toBeUndefined();
    expect(org.alternateName).toBe("Menivor AI");
  });

  it("keeps the directory descriptions at 50 and 150 words", () => {
    const words = (s: string) => s.split(/\s+/).filter(Boolean).length;
    expect(words(PRESS_DESCRIPTION_SHORT)).toBeGreaterThanOrEqual(40);
    expect(words(PRESS_DESCRIPTION_SHORT)).toBeLessThanOrEqual(55);
    expect(words(PRESS_DESCRIPTION_LONG)).toBeGreaterThanOrEqual(130);
    expect(words(PRESS_DESCRIPTION_LONG)).toBeLessThanOrEqual(160);
  });
});
