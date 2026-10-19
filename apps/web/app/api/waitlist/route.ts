import { NextResponse } from "next/server";
import {
  MAX_WAITLIST_BODY_BYTES,
  WAITLIST_FALLBACK_EMAIL,
  validateWaitlistPayload,
} from "@/lib/waitlist";

/**
 * Waitlist signup endpoint.
 *
 * Runs on Cloudflare Workers via @opennextjs/cloudflare and persists signups to
 * the `WAITLIST` KV namespace declared in `apps/web/wrangler.jsonc` (creation +
 * id wiring documented in the root `DEPLOY.md`). Storage is keyed by the
 * normalized email, so repeat signups are idempotent overwrites — no dedupe
 * table needed at waitlist scale.
 *
 * Degradation contract: when the KV binding is unavailable (plain `next dev`,
 * `next start`, or a preview without the namespace) this returns 503 with a
 * clear message and the client form falls back to a `mailto:` link. It never
 * crashes the page.
 */

interface WaitlistKvNamespace {
  put(key: string, value: string): Promise<void>;
}

/** JSON body for every response so the form can always read `error`/`ok`. */
function jsonResponse(status: number, body: Record<string, unknown>): NextResponse {
  return NextResponse.json(body, { status });
}

function unavailableResponse(): NextResponse {
  return jsonResponse(503, {
    ok: false,
    error:
      "Waitlist signups are not available right now. " +
      `Email ${WAITLIST_FALLBACK_EMAIL} and we will add you by hand.`,
    fallbackEmail: WAITLIST_FALLBACK_EMAIL,
  });
}

/**
 * Resolve the KV binding from the Cloudflare request context. Imported lazily
 * and wrapped: outside the Workers runtime `getCloudflareContext()` throws,
 * which we translate into "binding absent" rather than a 500.
 */
async function resolveWaitlistKv(): Promise<WaitlistKvNamespace | null> {
  try {
    const { getCloudflareContext } = await import("@opennextjs/cloudflare");
    const { env } = getCloudflareContext();
    const binding = (env as Record<string, unknown>).WAITLIST;
    if (
      binding &&
      typeof (binding as WaitlistKvNamespace).put === "function"
    ) {
      return binding as WaitlistKvNamespace;
    }
    return null;
  } catch {
    // Not running on Workers (local `next dev`/`next start`).
    return null;
  }
}

export async function POST(request: Request): Promise<NextResponse> {
  let raw: string;
  try {
    raw = await request.text();
  } catch {
    return jsonResponse(400, { ok: false, error: "Could not read request body." });
  }
  if (raw.length > MAX_WAITLIST_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "Request body too large." });
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return jsonResponse(400, { ok: false, error: "Request body must be JSON." });
  }

  const validation = validateWaitlistPayload(parsed);
  if (!validation.ok) {
    return jsonResponse(400, { ok: false, error: validation.error });
  }

  // Bots that fill the hidden honeypot field get a success response and no
  // stored row — they learn nothing and pollute nothing.
  if (validation.honeypotTripped) {
    return jsonResponse(200, { ok: true });
  }

  const kv = await resolveWaitlistKv();
  if (!kv) {
    return unavailableResponse();
  }

  const { email, source } = validation.entry;
  try {
    await kv.put(
      `waitlist:${email}`,
      JSON.stringify({
        email,
        source,
        createdAt: new Date().toISOString(),
      }),
    );
  } catch (error) {
    // Structured, PII-free log so failures are visible in worker observability.
    console.error(
      JSON.stringify({
        event: "waitlist_signup_failed",
        source,
        reason: error instanceof Error ? error.message : "unknown",
      }),
    );
    return unavailableResponse();
  }

  // Structured, PII-free signup counter for Cloudflare worker observability
  // (observability is enabled in wrangler.jsonc; filter on `waitlist_signup`).
  console.info(JSON.stringify({ event: "waitlist_signup", source }));

  return jsonResponse(200, { ok: true });
}
