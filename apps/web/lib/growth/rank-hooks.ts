/**
 * Winning Hook Finder — SERVER ranking logic.
 *
 * Given several hook/caption variants for one reel, score each variant ONCE with
 * Jev across independent dimensions (strength, slop, policy-risk) and let it PICK
 * an angle from a code-supplied candidate list, then combine those raw signals in
 * code (tunable weights, no re-inference) to rank the variants and crown a winner.
 *
 * Doctrine mirrored from `products/openjev/sdk/js-lite/modules/meta-ads.ts`:
 *   pull candidates → score each (batched, one call/variant, run in parallel)
 *   → composite in code → sort → surface the winner + its recommended angle.
 *
 * Degradation: when Jev is unavailable (no key) or the call fails, the caller
 * falls back to {@link heuristicRank} — a transparent, code-only ranking clearly
 * labeled `engine: "heuristic"`. It never fabricates Jev signals.
 */

import {
  clamp01,
  compositeScore,
  isChoice,
  isNoul,
  isScore,
  noul,
  normalizeScore,
  score,
  choice,
  type ScoreAnswer,
  type TypeSafeClient,
} from "./typesafe-client";
import {
  HOOK_ANGLE_CRITERIA,
  HOOK_ANGLES,
  MAX_HOOK_LENGTH,
  MAX_HOOK_VARIANTS,
  type HookAngle,
  type HookVariantInput,
  type PolicyRisk,
  type RankedHook,
  type RankHooksResponse,
} from "./types";

// --- Weights (tune without re-running inference) ----------------------------

/** Composite weights: strength lifts, slop penalizes. */
const WEIGHTS = { strength: 1, slop: -0.5 } as const;

// --- Score legends (each level stands on its own) ---------------------------

const STRENGTH_LEVELS = [
  "Weak: generic opener, no reason to stop scrolling.",
  "Okay: a mild angle or benefit, easy to scroll past.",
  "Strong: a specific, curiosity- or pain-driven hook.",
  "Exceptional: a scroll-stopping hook that names the exact desire.",
];

const SLOP_LEVELS = [
  "Fresh: sounds like a real person, specific and human.",
  "Slightly templated: a little generic but still fine.",
  "Sloppy: obvious AI-template phrasing, vague filler.",
  "Pure slop: hollow buzzwords, engagement-bait, says nothing.",
];

// --- Public API -------------------------------------------------------------

/**
 * Rank hook variants with Jev. Each variant is one batched `systemOne` call; the
 * calls run in parallel. Returns the strongest-first ranking + winner + angle.
 * Throws if the underlying client throws (the route decides whether to degrade).
 */
export async function rankHooksWithJev(
  client: TypeSafeClient,
  variants: readonly HookVariantInput[],
): Promise<RankHooksResponse> {
  const graded = await Promise.all(variants.map((v) => scoreVariant(client, v)));
  return assemble(graded, "jev", false);
}

/**
 * Transparent code-only fallback used when Jev is unavailable. Uses cheap,
 * deterministic text heuristics (length, specificity signals, buzzword density)
 * — clearly labeled so a creator knows this is NOT a Jev judgment.
 */
export function heuristicRank(
  variants: readonly HookVariantInput[],
  note: string,
): RankHooksResponse {
  const graded = variants.map((v) => heuristicScoreVariant(v));
  return assemble(graded, "heuristic", true, note);
}

// --- Per-variant Jev scoring ------------------------------------------------

interface GradedVariant {
  id: string;
  text: string;
  strength: number;
  slop: number;
  policyRiskProb: number;
  angle: HookAngle;
  confidence: number;
  composite: number;
}

async function scoreVariant(
  client: TypeSafeClient,
  variant: HookVariantInput,
): Promise<GradedVariant> {
  const res = await client.systemOne({
    state: {
      hook: variant.text,
      note: "Judge this as the FIRST on-screen line / spoken hook of a short vertical video (a reel/Short/TikTok). The goal is to stop the scroll in the first 2 seconds.",
    },
    questions: {
      strength: score("How strong is this hook at stopping the scroll for a cold viewer?", STRENGTH_LEVELS),
      slop: score("How much does this read as generic AI slop / engagement-bait rather than a specific human hook?", SLOP_LEVELS),
      policyRisk: noul(
        "Might this hook trip a platform or ad policy (unverifiable claims, medical/financial promises, shock/hate, personal-attribute targeting)?",
        { true: "Plausible policy issue that needs a human look", false: "No obvious policy issue" },
      ),
      angle: choice(
        "Which single angle best describes how this hook tries to grab attention?",
        HOOK_ANGLE_CRITERIA as Record<string, string>,
      ),
    },
  });

  const a = res.answers;
  const strengthAns = isScore(a.strength) ? a.strength : undefined;
  const slopAns = isScore(a.slop) ? a.slop : undefined;

  const strength = strengthAns ? normalizeScore(strengthAns) : 0;
  const slop = slopAns ? normalizeScore(slopAns) : 0;
  const policyRiskProb = isNoul(a.policyRisk) ? clamp01(a.policyRisk.noul) : 0;
  const angle = isChoice(a.angle) ? coerceAngle(a.angle.choice) : "other";

  const dims: Array<{ answer: ScoreAnswer; weight: number }> = [];
  if (strengthAns) dims.push({ answer: strengthAns, weight: WEIGHTS.strength });
  if (slopAns) dims.push({ answer: slopAns, weight: WEIGHTS.slop });

  return {
    id: variant.id,
    text: variant.text,
    strength,
    slop,
    policyRiskProb,
    angle,
    confidence: strengthAns?.confidence ?? 0,
    composite: compositeScore(dims),
  };
}

// --- Heuristic fallback scoring (code-only, no model) -----------------------

const BUZZWORDS = [
  "game-changer", "game changer", "unlock", "supercharge", "revolutionize",
  "next-level", "next level", "elevate", "seamless", "leverage", "10x",
  "mind-blowing", "insane", "literally", "you won't believe", "this one trick",
];

function heuristicScoreVariant(variant: HookVariantInput): GradedVariant {
  const text = variant.text.trim();
  const lower = text.toLowerCase();
  const words = lower.split(/\s+/).filter(Boolean);

  // Strength: reward concrete signals (numbers, a question, "how/why", a sharp
  // length band); nothing here pretends to be a Jev judgment.
  const hasNumber = /\d/.test(text) ? 0.25 : 0;
  const hasQuestion = /\?/.test(text) ? 0.15 : 0;
  const hasHowWhy = /\b(how|why|what|when)\b/.test(lower) ? 0.15 : 0;
  const lengthFit = words.length >= 4 && words.length <= 14 ? 0.35 : 0.1;
  const strength = clamp01(0.1 + hasNumber + hasQuestion + hasHowWhy + lengthFit);

  // Slop: buzzword density + very generic all-caps hype.
  const buzzHits = BUZZWORDS.reduce((n, b) => (lower.includes(b) ? n + 1 : n), 0);
  const slop = clamp01(buzzHits * 0.28 + (words.length < 3 ? 0.3 : 0));

  const composite = clamp01(strength - 0.5 * slop + 0.5 * 0.5);

  return {
    id: variant.id,
    text: variant.text,
    strength,
    slop,
    policyRiskProb: 0,
    angle: hasQuestion || hasHowWhy ? "curiosity_gap" : hasNumber ? "bold_claim" : "other",
    confidence: 0,
    composite,
  };
}

// --- Assembly + ranking -----------------------------------------------------

function assemble(
  graded: readonly GradedVariant[],
  engine: "jev" | "heuristic",
  degraded: boolean,
  note?: string,
): RankHooksResponse {
  // Sort strongest-first: composite, then strength, then lower slop, then the
  // caller's original order (stable) so ties are deterministic.
  const order = new Map(graded.map((g, i) => [g.id, i]));
  const sorted = [...graded].sort((x, y) => {
    if (y.composite !== x.composite) return y.composite - x.composite;
    if (y.strength !== x.strength) return y.strength - x.strength;
    if (x.slop !== y.slop) return x.slop - y.slop;
    return (order.get(x.id) ?? 0) - (order.get(y.id) ?? 0);
  });

  const variants: RankedHook[] = sorted.map((g, i) => ({
    id: g.id,
    text: g.text,
    rank: i + 1,
    isWinner: i === 0,
    composite: round4(g.composite),
    strength: round4(g.strength),
    slop: round4(g.slop),
    policyRisk: bandPolicyRisk(g.policyRiskProb),
    policyRiskProb: round4(g.policyRiskProb),
    angle: g.angle,
    angleLabel: HOOK_ANGLES[g.angle],
    confidence: round4(g.confidence),
  }));

  const winner = variants[0] ?? null;
  const result: RankHooksResponse = {
    variants,
    winner,
    recommendedAngle: winner ? { key: winner.angle, label: winner.angleLabel } : null,
    engine,
    degraded,
  };
  return note ? { ...result, note } : result;
}

/** Map a raw p(policy issue) to a coarse band the UI renders as a badge. */
function bandPolicyRisk(prob: number): PolicyRisk {
  if (prob >= 0.6) return "high";
  if (prob >= 0.3) return "medium";
  return "low";
}

/** Guard the model's choice back into our known angle keys. */
function coerceAngle(raw: string): HookAngle {
  return raw in HOOK_ANGLES ? (raw as HookAngle) : "other";
}

function round4(n: number): number {
  return Math.round(clamp01(n) * 10000) / 10000;
}

// --- Boundary validation (untrusted request body → typed variants) ----------

export interface ParsedVariants {
  readonly ok: boolean;
  readonly variants: readonly HookVariantInput[];
  readonly error?: string;
}

/**
 * Validate + normalize an untrusted request body into hook variants. Accepts
 * either `{ variants: [{ id?, text }] }` or `{ hooks: string[] }`. Trims, drops
 * blanks, caps count + length, and assigns stable ids. Fail-fast with a clear
 * message (never trust external input).
 */
export function parseVariants(body: unknown): ParsedVariants {
  const empty: readonly HookVariantInput[] = [];
  if (!body || typeof body !== "object") {
    return { ok: false, variants: empty, error: "Request body must be a JSON object." };
  }
  const record = body as Record<string, unknown>;
  const raw: unknown[] = Array.isArray(record.variants)
    ? record.variants
    : Array.isArray(record.hooks)
      ? record.hooks
      : [];

  const seen = new Set<string>();
  const variants: HookVariantInput[] = [];
  for (const entry of raw) {
    const text = extractText(entry);
    if (!text) continue;
    const clipped = text.slice(0, MAX_HOOK_LENGTH).trim();
    if (!clipped || seen.has(clipped.toLowerCase())) continue;
    seen.add(clipped.toLowerCase());
    variants.push({ id: `h${variants.length + 1}`, text: clipped });
    if (variants.length >= MAX_HOOK_VARIANTS) break;
  }

  if (variants.length === 0) {
    return { ok: false, variants: empty, error: "Provide at least one non-empty hook variant." };
  }
  return { ok: true, variants };
}

function extractText(entry: unknown): string | null {
  if (typeof entry === "string") return entry.trim() || null;
  if (entry && typeof entry === "object") {
    const t = (entry as Record<string, unknown>).text;
    if (typeof t === "string") return t.trim() || null;
  }
  return null;
}
