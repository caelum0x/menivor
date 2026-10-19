/**
 * Waitlist input validation shared by the `/api/waitlist` route handler and its
 * tests. Hand-rolled (this app carries no schema-validation dependency) and
 * fail-closed: anything that is not a small, well-shaped JSON object with a
 * plausible email is rejected before it ever reaches storage.
 */

/** Where signups fall back to when the KV binding is unavailable (local dev). */
export const WAITLIST_FALLBACK_EMAIL = "hello@menivor.com";

/** Anchor id of the landing-page waitlist section (`/#waitlist`). */
export const WAITLIST_ANCHOR = "waitlist";

/** Hard cap on the raw request body; a real signup is well under 1 KiB. */
export const MAX_WAITLIST_BODY_BYTES = 4096;

/** RFC 5321 caps the full address at 254 octets. */
const MAX_EMAIL_LENGTH = 254;

/** Free-form "where did this signup come from" tag, e.g. `landing-cta`. */
const MAX_SOURCE_LENGTH = 64;

/**
 * Pragmatic email shape check: one `@`, a non-empty local part, and a dotted
 * domain with a 2+ character TLD. Deliverability is not verifiable offline, so
 * this only screens out obvious garbage without rejecting unusual-but-valid
 * addresses.
 */
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export interface WaitlistEntry {
  /** Normalized (trimmed, lowercased) email address. */
  readonly email: string;
  /** Sanitized attribution tag; empty when the client sent none. */
  readonly source: string;
}

export type WaitlistValidation =
  | { readonly ok: true; readonly entry: WaitlistEntry; readonly honeypotTripped: boolean }
  | { readonly ok: false; readonly error: string };

/**
 * Validate an already-JSON-parsed request body. Returns a normalized entry or
 * a user-facing error message. A filled honeypot field (`company` — hidden from
 * humans by the form) marks the submission as bot traffic; callers should
 * pretend success without storing anything so bots learn nothing.
 */
export function validateWaitlistPayload(input: unknown): WaitlistValidation {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    return { ok: false, error: "Request body must be a JSON object." };
  }
  const body = input as Record<string, unknown>;

  const rawEmail = body.email;
  if (typeof rawEmail !== "string" || rawEmail.trim().length === 0) {
    return { ok: false, error: "Please enter your email address." };
  }
  const email = rawEmail.trim().toLowerCase();
  if (email.length > MAX_EMAIL_LENGTH || !EMAIL_PATTERN.test(email)) {
    return { ok: false, error: "Please enter a valid email address." };
  }

  const rawSource = body.source;
  if (rawSource !== undefined && typeof rawSource !== "string") {
    return { ok: false, error: "Invalid signup source." };
  }
  // Keep the tag log/key safe: drop anything but a short slug-ish string.
  const source = (rawSource ?? "")
    .trim()
    .slice(0, MAX_SOURCE_LENGTH)
    .replace(/[^a-zA-Z0-9_/#.-]/g, "");

  const honeypot = body.company;
  if (honeypot !== undefined && typeof honeypot !== "string") {
    return { ok: false, error: "Invalid request." };
  }
  const honeypotTripped = typeof honeypot === "string" && honeypot.trim().length > 0;

  return { ok: true, entry: { email, source }, honeypotTripped };
}
