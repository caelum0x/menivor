/**
 * Shared types + constants for the Winning Hook Finder (growth surface).
 *
 * Types-and-constants only: NO runtime I/O, NO server-only imports, so both the
 * server ranking route (`app/api/v1/growth/rank-hooks`) and the browser page
 * (`app/hook-finder`) can import from one place without leaking the TypeSafe
 * client (or its API key) into the client bundle.
 */

/** One creator-supplied hook/caption variant awaiting judgment. */
export interface HookVariantInput {
  /** Stable id the caller assigns so answers map back to the right line. */
  readonly id: string;
  /** The hook/caption copy exactly as the creator would post it. */
  readonly text: string;
}

/** Coarse policy-risk band derived (in code) from the model's probability. */
export type PolicyRisk = "low" | "medium" | "high";

/** Which inference engine produced a result — `heuristic` = degraded fallback. */
export type RankEngine = "jev" | "heuristic";

/**
 * The candidate emotional/structural angles the model PICKS from (it never
 * invents one — see the TypeSafe doctrine: candidate lists are built in code).
 * `other` is the mandatory no-match escape hatch.
 */
export const HOOK_ANGLES = {
  curiosity_gap: "Curiosity gap",
  bold_claim: "Bold claim",
  problem_agitate: "Problem / pain",
  transformation: "Before → after",
  social_proof: "Social proof",
  contrarian: "Contrarian take",
  how_to: "How-to / value",
  urgency: "Urgency / FOMO",
  relatability: "Relatable moment",
  other: "Other",
} as const satisfies Record<string, string>;

export type HookAngle = keyof typeof HOOK_ANGLES;

/** Longer descriptions handed to the model as the `choice` criteria. */
export const HOOK_ANGLE_CRITERIA: Readonly<Record<HookAngle, string>> = {
  curiosity_gap: "Opens an information gap that demands the viewer keep watching.",
  bold_claim: "Leads with a big, specific, attention-grabbing claim or result.",
  problem_agitate: "Names a painful problem the target viewer feels right now.",
  transformation: "Frames a clear before → after change or outcome.",
  social_proof: "Leans on numbers, popularity, authority, or what others did.",
  contrarian: "Challenges a common belief or takes an against-the-grain stance.",
  how_to: "Promises concrete, actionable value or a step-by-step payoff.",
  urgency: "Uses scarcity, timing, or fear of missing out to compel action now.",
  relatability: "A relatable everyday moment the viewer sees themselves in.",
  other: "None of the above angles fit this hook.",
};

/** One ranked variant with the per-signal breakdown the UI renders as badges. */
export interface RankedHook {
  readonly id: string;
  readonly text: string;
  /** 1-based position after ranking (1 = strongest). */
  readonly rank: number;
  /** True for the single top-ranked variant. */
  readonly isWinner: boolean;
  /** Weighted 0..1 composite the ranking sorts on. */
  readonly composite: number;
  /** 0..1 hook strength / scroll-stopping power (higher = better). */
  readonly strength: number;
  /** 0..1 AI-slop / generic-template feel (higher = worse). */
  readonly slop: number;
  /** Coarse policy-risk band. */
  readonly policyRisk: PolicyRisk;
  /** Raw 0..1 probability the copy trips a platform/ad policy. */
  readonly policyRiskProb: number;
  /** The angle the model picked for this variant. */
  readonly angle: HookAngle;
  /** Human label for {@link angle}. */
  readonly angleLabel: string;
  /** 0..1 model confidence on the strength judgment. */
  readonly confidence: number;
}

/** The full ranking envelope returned by `POST /api/v1/growth/rank-hooks`. */
export interface RankHooksResponse {
  /** Every variant, strongest first. */
  readonly variants: readonly RankedHook[];
  /** The winning variant, or null when no variants were supplied. */
  readonly winner: RankedHook | null;
  /** The winner's recommended angle, surfaced for quick reuse. */
  readonly recommendedAngle: { readonly key: HookAngle; readonly label: string } | null;
  /** Which engine ran. */
  readonly engine: RankEngine;
  /** True when the graceful fallback ran instead of Jev (key unset / call failed). */
  readonly degraded: boolean;
  /** Optional human-facing note (e.g. why the run was degraded). */
  readonly note?: string;
}

/** Upper bound on variants per request — keeps a single call bounded + cheap. */
export const MAX_HOOK_VARIANTS = 8;
/** Max characters per hook line accepted at the boundary. */
export const MAX_HOOK_LENGTH = 400;
