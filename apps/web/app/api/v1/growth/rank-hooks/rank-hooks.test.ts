import { describe, expect, it } from "vitest";

import {
  heuristicRank,
  parseVariants,
  rankHooksWithJev,
} from "@/lib/growth/rank-hooks";
import { TypeSafeClient } from "@/lib/growth/typesafe-client";
import { MAX_HOOK_VARIANTS } from "@/lib/growth/types";

/**
 * Build a canned /v1/systemone response for one variant. `strength`/`slop` are
 * level indices 0..3 (matching the 4-level legends in rank-hooks.ts).
 */
function jevAnswers(opts: {
  strength: number;
  slop: number;
  policy: number;
  angle: string;
}): Response {
  const legend = { "0": "a", "1": "b", "2": "c", "3": "d" };
  const body = {
    model: "jev-latest",
    answers: {
      strength: { type: "score", score: opts.strength, legend, probabilities: {}, confidence: 0.9 },
      slop: { type: "score", score: opts.slop, legend, probabilities: {}, confidence: 0.8 },
      policyRisk: { type: "noul", noul: opts.policy },
      angle: { type: "choice", choice: opts.angle, probabilities: { [opts.angle]: 1 }, confidence: 0.9 },
    },
  };
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

/**
 * A fake fetch that returns a different score per hook so ranking is
 * deterministic: the strong/fresh hook must win over the weak/sloppy one.
 */
function fakeFetch(): typeof fetch {
  return (async (_url: string, init?: RequestInit) => {
    const payload = JSON.parse(String(init?.body ?? "{}")) as {
      state?: { hook?: string };
    };
    const hook = payload.state?.hook ?? "";
    if (hook.includes("STRONG")) {
      return jevAnswers({ strength: 3, slop: 0, policy: 0.02, angle: "curiosity_gap" });
    }
    if (hook.includes("RISKY")) {
      return jevAnswers({ strength: 2, slop: 1, policy: 0.8, angle: "bold_claim" });
    }
    return jevAnswers({ strength: 0, slop: 3, policy: 0.05, angle: "other" });
  }) as unknown as typeof fetch;
}

describe("parseVariants", () => {
  it("accepts { hooks: string[] }, trims, dedupes, and assigns stable ids", () => {
    const parsed = parseVariants({ hooks: ["  a hook  ", "a hook", "another"] });
    expect(parsed.ok).toBe(true);
    expect(parsed.variants.map((v) => v.text)).toEqual(["a hook", "another"]);
    expect(parsed.variants.map((v) => v.id)).toEqual(["h1", "h2"]);
  });

  it("accepts { variants: [{ text }] } and caps the count", () => {
    const many = Array.from({ length: MAX_HOOK_VARIANTS + 3 }, (_, i) => ({ text: `hook ${i}` }));
    const parsed = parseVariants({ variants: many });
    expect(parsed.variants).toHaveLength(MAX_HOOK_VARIANTS);
  });

  it("fails clean on empty / non-object input", () => {
    expect(parseVariants({ hooks: ["   "] }).ok).toBe(false);
    expect(parseVariants(null).ok).toBe(false);
    expect(parseVariants("nope").ok).toBe(false);
  });
});

describe("rankHooksWithJev", () => {
  it("ranks the strong hook first, crowns it, and surfaces its angle", async () => {
    const client = new TypeSafeClient({ apiKey: "test-key", maxRetries: 0, fetchImpl: fakeFetch() });
    const result = await rankHooksWithJev(client, [
      { id: "h1", text: "a WEAK sloppy line" },
      { id: "h2", text: "a STRONG scroll-stopping line" },
      { id: "h3", text: "a RISKY miracle-cure claim" },
    ]);

    expect(result.engine).toBe("jev");
    expect(result.degraded).toBe(false);
    expect(result.winner?.text).toContain("STRONG");
    expect(result.winner?.isWinner).toBe(true);
    expect(result.variants[0]?.rank).toBe(1);
    expect(result.recommendedAngle?.key).toBe("curiosity_gap");

    const risky = result.variants.find((v) => v.text.includes("RISKY"));
    expect(risky?.policyRisk).toBe("high");

    const weak = result.variants.find((v) => v.text.includes("WEAK"));
    expect(weak?.slop).toBeGreaterThan(0.9);
    expect(weak?.rank).toBe(3);
  });
});

describe("heuristicRank (degraded fallback)", () => {
  it("labels itself heuristic + degraded and still ranks deterministically", () => {
    const result = heuristicRank(
      [
        { id: "h1", text: "unlock next-level game-changer synergy" },
        { id: "h2", text: "How I edited 30 reels in one afternoon" },
      ],
      "no key",
    );
    expect(result.engine).toBe("heuristic");
    expect(result.degraded).toBe(true);
    expect(result.note).toBe("no key");
    expect(result.winner?.text).toContain("How I edited");
    // The buzzword-stuffed line should score as sloppier than the concrete one.
    const sloppy = result.variants.find((v) => v.text.includes("game-changer"));
    expect(sloppy?.slop).toBeGreaterThan(0);
  });
});
