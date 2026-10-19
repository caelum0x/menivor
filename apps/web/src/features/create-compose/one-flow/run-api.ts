/**
 * `POST /experiments/runs`: link a link-mode run (one job per hook) into one
 * 1-body/N-hooks experiment so the remake-winner loop tracks it. Topic runs
 * are registered by `POST /jobs` itself and never call this.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import { VARIANT_COUNT, type RunRegistrationBody } from "./plan";

export interface RunRegistrationResult {
  readonly batch_id: string;
  readonly experiment_key: string;
  readonly created: boolean;
  readonly loop: { readonly status: string; readonly mode: string };
  readonly loop_error?: string;
}

export function registerRun(
  body: RunRegistrationBody,
  options?: RequestOptions,
): Promise<RunRegistrationResult> {
  return apiRequest<RunRegistrationResult>("/experiments/runs", {
    method: "POST",
    body,
    options,
  });
}

export interface StyleHooksBody {
  readonly style: string;
  readonly title: string;
  readonly description?: string;
  readonly features?: readonly string[];
  readonly language?: string;
}

export interface StyleHooksResult {
  readonly style: string;
  readonly hooks: readonly { hook_style: string; hook: string; source: string }[];
}

/**
 * `POST /styles/hooks`: one opening hook per format of the style's hook
 * family (meme captions, POV, before/after ...), written by the LLM from the
 * pasted page's facts, with template fallbacks server-side.
 */
export function writeStyleHooks(
  body: StyleHooksBody,
  options?: RequestOptions,
): Promise<StyleHooksResult> {
  return apiRequest<StyleHooksResult>("/styles/hooks", {
    method: "POST",
    body: {
      style: body.style,
      title: body.title.slice(0, 300),
      description: (body.description ?? "").slice(0, 2000),
      features: (body.features ?? []).slice(0, 8).map((item) => String(item).slice(0, 200)),
      language: body.language ?? "auto",
    },
    options,
  });
}

/**
 * MG11: how many reels one run makes for this balance. A run asks for the full
 * {@link VARIANT_COUNT} when the balance covers it, otherwise one reel per
 * credit left, so one or two stranded credits still make reels instead of
 * ending in a 402. `0` means nothing can start (show the plan screen). An
 * unknown balance (`null`, still loading or signed out) asks for the full run;
 * the server re-checks either way.
 */
export function runVariantCount(credits: number | null | undefined): number {
  if (credits === null || credits === undefined || !Number.isFinite(credits)) return VARIANT_COUNT;
  return Math.max(0, Math.min(VARIANT_COUNT, Math.floor(credits)));
}

export interface RunCopy {
  /** Cost line next to the button, e.g. "2 credits". */
  readonly cost: string;
  /** Button label, e.g. "Make 2 reels". */
  readonly button: string;
  /** Busy label, e.g. "Starting 2 renders…". */
  readonly starting: string;
}

/** Button and cost copy for a run of `count` reels (1 credit each). */
export function runCopy(count: number): RunCopy {
  const n = Math.max(1, Math.floor(count));
  return {
    cost: n === 1 ? "1 credit" : `${n} credits`,
    button: n === 1 ? "Make 1 reel" : `Make ${n} reels`,
    starting: n === 1 ? "Starting 1 render…" : `Starting ${n} renders…`,
  };
}

/** The line above the plan screen when the balance cannot start a run. */
export function outOfCreditsLine(credits: number | null | undefined): string {
  if (credits !== null && credits !== undefined && credits > 0) {
    return `Each reel uses 1 credit and you have ${credits}. Top up in one click:`;
  }
  return "You are out of credits. Each reel uses 1 credit. Top up in one click:";
}
