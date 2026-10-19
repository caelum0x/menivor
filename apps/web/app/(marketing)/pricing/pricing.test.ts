import { describe, expect, it } from "vitest";
import {
  COMPETITOR_PRICING,
  competitorCostForReels,
  menivorCostForReels,
} from "@/lib/seo/competitors";
import { byokFeeMicros, validateProviderKeyInput } from "@/lib/byok";

const bySlug = (slug: string) => COMPETITOR_PRICING.find((entry) => entry.slug === slug)!;

describe("menivorCostForReels", () => {
  it("picks the cheapest pack mix", () => {
    expect(menivorCostForReels(30)).toEqual({ usd: 19, packs: "1 x Starter pack" });
    expect(menivorCostForReels(100).usd).toBe(59);
    expect(menivorCostForReels(150)).toEqual({ usd: 78, packs: "1 x Pro pack + 1 x Starter pack" });
    expect(menivorCostForReels(0).usd).toBe(0);
  });
});

describe("competitorCostForReels", () => {
  it("uses the cheapest plan that includes enough videos", () => {
    expect(competitorCostForReels(bySlug("submagic"), 30)).toEqual({ kind: "plan", usd: 39, plan: "Pro" });
  });
  it("flags volume above the largest plan", () => {
    expect(competitorCostForReels(bySlug("arcads"), 50).kind).toBe("overLargest");
  });
  it("never invents a per-video price for credit plans", () => {
    expect(competitorCostForReels(bySlug("creatify"), 30)).toEqual({
      kind: "creditsOnly",
      fromUsd: 39,
      plan: "Starter",
    });
  });
  it("cites a source for every competitor", () => {
    for (const entry of COMPETITOR_PRICING) expect(entry.sourceUrl).toMatch(/^https:\/\//);
  });
});

describe("byok", () => {
  it("charges 10% with a $0.001 floor", () => {
    expect(byokFeeMicros(1_000_000)).toBe(100_000);
    expect(byokFeeMicros(5_000)).toBe(1_000);
    expect(byokFeeMicros(0)).toBe(0);
  });
  it("validates keys before sending", () => {
    expect(validateProviderKeyInput({ provider_key: "nope", secret: "abcdefghij" })).not.toBeNull();
    expect(validateProviderKeyInput({ provider_key: "elevenlabs", secret: "short" })).not.toBeNull();
    expect(validateProviderKeyInput({ provider_key: "elevenlabs", secret: "sk_live_abcdefgh" })).toBeNull();
  });
});
