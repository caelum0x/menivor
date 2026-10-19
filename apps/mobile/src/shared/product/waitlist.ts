/**
 * Client for the Menivor public waitlist.
 *
 * Posts signups to the live, KV-backed endpoint the web app already serves
 * (menivor.com/api/waitlist — see apps/web/app/api/waitlist/route.ts). The
 * mobile app is not served from that origin, so we target the absolute URL
 * (overridable with EXPO_PUBLIC_WAITLIST_URL for staging).
 *
 * Everything here is fail-open and honest: validation matches the server's, a
 * 503 (KV binding absent) surfaces as "signups paused — email us", and a
 * network failure degrades the same way rather than throwing a dead end. No
 * data is fabricated; a signup is only ever "on the list" when the server
 * confirms it with a 2xx.
 */

/** Where signups fall back to when the endpoint is unavailable. */
export const WAITLIST_FALLBACK_EMAIL = "hello@menivor.com";

const DEFAULT_WAITLIST_URL = "https://menivor.com/api/waitlist";

/** RFC 5321 caps the full address at 254 octets. */
const MAX_EMAIL_LENGTH = 254;

/**
 * Pragmatic email shape check, identical to the server's (apps/web/lib/waitlist).
 * One `@`, a non-empty local part, and a dotted domain with a 2+ char TLD.
 */
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/** The absolute endpoint, honouring an env override. */
export function waitlistUrl(): string {
  const configured = process.env.EXPO_PUBLIC_WAITLIST_URL;
  return configured && configured.trim() ? configured.trim() : DEFAULT_WAITLIST_URL;
}

export type EmailValidation =
  | { readonly ok: true; readonly email: string }
  | { readonly ok: false; readonly error: string };

/**
 * Validate and normalize a raw email string. Returns the trimmed, lowercased
 * address or a user-facing error message. Pure — safe to call on every
 * keystroke and to unit test.
 */
export function validateEmail(raw: string): EmailValidation {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return { ok: false, error: "Please enter your email address." };
  }
  const email = trimmed.toLowerCase();
  if (email.length > MAX_EMAIL_LENGTH || !EMAIL_PATTERN.test(email)) {
    return { ok: false, error: "Please enter a valid email address." };
  }
  return { ok: true, email };
}

export type WaitlistOutcome =
  /** Server confirmed the signup (new or idempotent repeat). */
  | { readonly status: "ok" }
  /** Client-side validation rejected the input before any request. */
  | { readonly status: "invalid"; readonly message: string }
  /** Endpoint reachable but signups are paused (KV binding absent → 503). */
  | { readonly status: "unavailable" }
  /** Endpoint returned a 4xx with a message, e.g. malformed body. */
  | { readonly status: "error"; readonly message: string };

/** Minimal fetch surface so tests can inject a stub. */
export type FetchLike = (
  input: string,
  init: { method: string; headers: Record<string, string>; body: string },
) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>;

/**
 * Interpret a waitlist HTTP response into a {@link WaitlistOutcome}. Split from
 * the network call so the mapping is unit-testable without a live server.
 */
export async function interpretWaitlistResponse(response: {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}): Promise<WaitlistOutcome> {
  if (response.ok) return { status: "ok" };
  if (response.status === 503) return { status: "unavailable" };

  const body: unknown = await response.json().catch(() => null);
  const message =
    typeof body === "object" && body !== null && "error" in body
      ? String((body as { error: unknown }).error)
      : "Something went wrong. Please try again.";
  return { status: "error", message };
}

/**
 * Submit a waitlist signup. Validates first, then POSTs the same payload shape
 * the web form uses (`{ email, source, company }`, `company` is the honeypot).
 * Any network failure degrades to "unavailable" so the UI can offer a mailto
 * fallback instead of trapping the user.
 */
export async function submitWaitlist(
  rawEmail: string,
  source: string,
  deps: { fetch?: FetchLike; honeypot?: string } = {},
): Promise<WaitlistOutcome> {
  const validation = validateEmail(rawEmail);
  if (!validation.ok) {
    return { status: "invalid", message: validation.error };
  }

  const fetchImpl = deps.fetch ?? (globalThis.fetch as unknown as FetchLike);
  try {
    const response = await fetchImpl(waitlistUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: validation.email,
        source,
        company: deps.honeypot ?? "",
      }),
    });
    return interpretWaitlistResponse(response);
  } catch {
    // Network failure — same graceful path as a missing backend binding.
    return { status: "unavailable" };
  }
}
