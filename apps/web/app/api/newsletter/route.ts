import { NextResponse } from "next/server";
import { normalizeEmail, readListmonkConfig, subscribeToListmonk } from "@/lib/listmonk";
import { clientIp, createRateLimiter, hashIp } from "@/lib/rate-limit";

/**
 * Newsletter signup proxy: browser -> this route -> listmonk public API.
 *
 * Env (server-only, Cloudflare Worker vars/secrets):
 *   LISTMONK_URL        https://letters.ereboslab.com (Rally Letters)
 *   LISTMONK_LIST_UUID  UUID of the public, double-opt-in `menivor-updates` list
 * listmonk admin credentials are never needed here (see lib/listmonk.ts).
 *
 * Unset env => 503 with a clear message; the form shows it as-is.
 * Consent is required: we only forward an address the visitor explicitly
 * agreed to receive updates at, and listmonk then asks them to confirm by email.
 *
 * Rate limit: 5 requests / hour per hashed client IP, in memory per Worker
 * isolate (see lib/rate-limit.ts). Also add a Cloudflare WAF rate-limiting rule
 * on /api/newsletter for a limit that holds across isolates and colos.
 */

const MAX_BODY_BYTES = 2048;
const SIGNUPS_PER_HOUR = 5;
const HOUR_MS = 60 * 60 * 1000;

const signupLimiter = createRateLimiter({ capacity: SIGNUPS_PER_HOUR, refillMs: HOUR_MS });

function json(status: number, body: Record<string, unknown>): NextResponse {
  return NextResponse.json(body, { status });
}

export async function POST(request: Request): Promise<NextResponse> {
  // No IP only happens off Cloudflare (local dev/tests); the edge rule covers prod.
  const ip = clientIp(request);
  if (ip) {
    const decision = signupLimiter.check(await hashIp(ip));
    if (!decision.allowed) {
      const response = json(429, { ok: false, error: "Too many signup attempts. Please try again later." });
      response.headers.set("Retry-After", String(decision.retryAfterSeconds));
      return response;
    }
  }

  const raw = await request.text().catch(() => null);
  if (raw === null) return json(400, { ok: false, error: "Could not read request body." });
  if (raw.length > MAX_BODY_BYTES) return json(413, { ok: false, error: "Request body too large." });

  let body: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return json(400, { ok: false, error: "Request body must be a JSON object." });
    }
    body = parsed as Record<string, unknown>;
  } catch {
    return json(400, { ok: false, error: "Request body must be JSON." });
  }

  const email = normalizeEmail(body.email);
  if (!email) return json(400, { ok: false, error: "Please enter a valid email address." });
  if (body.consent !== true) {
    return json(400, { ok: false, error: "Please tick the box to agree to receive updates." });
  }
  // Honeypot (`company`, hidden from humans): pretend success, forward nothing.
  if (typeof body.company === "string" && body.company.trim().length > 0) {
    return json(200, { ok: true, needsConfirmation: true });
  }

  const config = readListmonkConfig(process.env);
  if (!config) {
    return json(503, {
      ok: false,
      error: "Email updates are not switched on yet. Please check back soon.",
    });
  }

  const result = await subscribeToListmonk(config, { email });
  if (result.ok) {
    console.info(JSON.stringify({ event: "newsletter_signup", needsConfirmation: result.needsConfirmation }));
    return json(200, { ok: true, needsConfirmation: result.needsConfirmation });
  }
  // PII-free log; the detail never reaches the browser.
  console.error(JSON.stringify({ event: "newsletter_signup_failed", reason: result.reason, detail: result.detail }));
  if (result.reason === "rejected") {
    return json(400, { ok: false, error: "That address could not be subscribed. Please check it and try again." });
  }
  return json(503, { ok: false, error: "Signups are temporarily unavailable. Please try again later." });
}
