import { NextResponse } from "next/server";

import { createPrincipalResolver } from "@/lib/api-principal";
import { createRateLimiter } from "@/lib/rate-limit";
import {
  heuristicRank,
  parseVariants,
  rankHooksWithJev,
} from "@/lib/growth/rank-hooks";
import { TypeSafeClient } from "@/lib/growth/typesafe-client";
import { MAX_HOOK_VARIANTS } from "@/lib/growth/types";

/**
 * POST /api/v1/growth/rank-hooks — the "Winning Hook Finder" contract.
 *
 * Body: `{ variants: [{ text }] }` or `{ hooks: string[] }`. Returns the variants
 * ranked strongest-first with a crowned winner, per-variant strength/slop/policy
 * signals, and the winner's recommended angle (see {@link RankHooksResponse}).
 *
 * Powered by TypeSafe's Jev model: each variant is scored in one batched
 * `systemOne` call (questions run in parallel), then composited + ranked in code
 * so weights can change without re-running inference.
 *
 * Runs on Cloudflare Workers via @opennextjs/cloudflare. The `TYPESAFE_API_KEY`
 * secret is resolved SERVER-SIDE only (Worker env binding, or `process.env` under
 * local `next dev`) — it never reaches the browser.
 *
 * Degradation contract: when the key is unset OR the Jev call fails, this NEVER
 * fabricates a key or fakes model output. It returns a 200 with a transparent,
 * code-only heuristic ranking (`engine: "heuristic"`, `degraded: true`, `note`),
 * and logs a structured warning. The page renders the fallback with a clear
 * "heuristic only" banner so nothing silently pretends to be Jev.
 *
 * Auth + abuse contract: every ranking can spend TypeSafe/Jev credits, so the
 * caller must present the credential the web app already sends to the Menivor
 * API (this browser's free device-session key, or a signed-in account token)
 * as `x-api-key` or `Authorization: Bearer`. It is verified by the API's
 * `resolve_principal` (see lib/api-principal.ts); missing/invalid => 401, API
 * unreachable => 503. Each principal then gets RANKINGS_PER_HOUR rankings per
 * hour (in-memory per Worker isolate, lib/rate-limit.ts) => 429 + Retry-After.
 */

/** Cap the request body so a hostile caller can't force a huge parse. */
const MAX_BODY_BYTES = 16 * 1024;

/** Per-user ranking budget; matches the API's `/growth/rank-hooks` limit. */
const RANKINGS_PER_HOUR = 60;
const HOUR_MS = 60 * 60 * 1000;

const principalResolver = createPrincipalResolver();
const rankingLimiter = createRateLimiter({ capacity: RANKINGS_PER_HOUR, refillMs: HOUR_MS });

function jsonResponse(status: number, body: Record<string, unknown>): NextResponse {
  return NextResponse.json(body, { status });
}

/**
 * Resolve the TypeSafe API key from the Worker env binding first (production),
 * falling back to `process.env` for local `next dev`/`next start`. Returns null
 * when unconfigured so the caller can degrade instead of 500-ing.
 */
async function resolveTypeSafeKey(): Promise<string | null> {
  const fromProcess = process.env.TYPESAFE_API_KEY ?? process.env.typesafe_api_key;
  if (fromProcess && fromProcess.trim()) return fromProcess.trim();
  try {
    const { getCloudflareContext } = await import("@opennextjs/cloudflare");
    const { env } = getCloudflareContext();
    const binding = (env as Record<string, unknown>).TYPESAFE_API_KEY;
    if (typeof binding === "string" && binding.trim()) return binding.trim();
    return null;
  } catch {
    // Not on Workers (plain Node dev/build) — process.env was the only source.
    return null;
  }
}

export async function POST(request: Request): Promise<NextResponse> {
  const auth = await principalResolver.resolve(request);
  if (!auth.ok) {
    if (auth.reason === "unavailable") {
      return jsonResponse(503, {
        error: "We couldn't verify your session right now. Please try again in a moment.",
      });
    }
    return jsonResponse(401, {
      error:
        auth.reason === "missing"
          ? "Sign in, or reload this page to start a free session, to rank hooks."
          : "Your session has expired. Reload the page and try again.",
    });
  }

  const decision = rankingLimiter.check(auth.principal.userId);
  if (!decision.allowed) {
    const limited = jsonResponse(429, {
      error: `You've ranked ${RANKINGS_PER_HOUR} hook sets in the last hour. Try again in a few minutes.`,
    });
    limited.headers.set("Retry-After", String(decision.retryAfterSeconds));
    return limited;
  }

  let raw: string;
  try {
    raw = await request.text();
  } catch {
    return jsonResponse(400, { error: "Could not read request body." });
  }
  if (raw.length > MAX_BODY_BYTES) {
    return jsonResponse(413, { error: "Request body too large." });
  }

  let parsedBody: unknown;
  try {
    parsedBody = JSON.parse(raw);
  } catch {
    return jsonResponse(400, { error: "Request body must be JSON." });
  }

  const parsed = parseVariants(parsedBody);
  if (!parsed.ok) {
    return jsonResponse(400, { error: parsed.error });
  }

  const apiKey = await resolveTypeSafeKey();
  if (!apiKey) {
    console.warn(
      JSON.stringify({
        event: "rank_hooks_degraded",
        reason: "typesafe_api_key_unset",
        variants: parsed.variants.length,
      }),
    );
    return jsonResponse(
      200,
      heuristicRank(
        parsed.variants,
        "Ranked with a fast text heuristic — TYPESAFE_API_KEY is not configured, so the Jev model did not run.",
      ) as unknown as Record<string, unknown>,
    );
  }

  try {
    const client = new TypeSafeClient({ apiKey, maxRetries: 2, timeoutMs: 18_000 });
    const result = await rankHooksWithJev(client, parsed.variants);
    return jsonResponse(200, result as unknown as Record<string, unknown>);
  } catch (error) {
    // Jev call failed (network/timeout/upstream). Degrade rather than 500 so the
    // creator still gets a usable ordering; surface it honestly as heuristic.
    console.warn(
      JSON.stringify({
        event: "rank_hooks_degraded",
        reason: "jev_call_failed",
        message: error instanceof Error ? error.message : "unknown",
        variants: parsed.variants.length,
      }),
    );
    return jsonResponse(
      200,
      heuristicRank(
        parsed.variants,
        "Ranked with a fast text heuristic — the Jev model was unreachable just now. Try again in a moment for a full analysis.",
      ) as unknown as Record<string, unknown>,
    );
  }
}

/** Reject non-POST verbs cleanly (documents the surface for probes). */
export function GET(): NextResponse {
  return jsonResponse(405, {
    error: "Use POST with { variants: [{ text }] } to rank hooks.",
    maxVariants: MAX_HOOK_VARIANTS,
  });
}
