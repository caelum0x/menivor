/**
 * Turn any thrown value into one short sentence a person can act on.
 *
 * API errors can carry request ids, header names, status lines or stack
 * text. None of that is useful to a user, so server text is only shown when
 * it already reads like a plain sentence (validation messages such as
 * "Enter a valid product link."); everything else maps to a calm default.
 */

import { ApiError } from "../api/client";

export const DEFAULT_ERROR_MESSAGE = "Something went wrong. Please try again.";
export const SIGNED_OUT_MESSAGE = "Please sign in to continue.";

const MAX_SAFE_LENGTH = 160;

/** Patterns that mark text as technical detail rather than a human sentence. */
const TECHNICAL_PATTERNS: readonly RegExp[] = [
  /\b[0-9a-f]{8,}\b/i, // request / correlation ids, hashes
  /\b[0-9a-f]{8}-[0-9a-f]{4}-/i, // uuids
  /\bx-[a-z-]+\b/i, // header names (x-api-key)
  /\bheader\b/i,
  /\bcorrelation\b/i,
  /\bstatus \d{3}\b/i,
  /\b(request failed|malformed|envelope|network error|fetch|stack|traceback)\b/i,
  /\b(undefined|null|NaN|TypeError|SyntaxError|ReferenceError)\b/,
  /\bat [\w.<>]+ \(/, // stack frames
  /[{}[\]<>`]/, // JSON, markup, code
  /https?:\/\//i,
  /\b(sql|postgres|prisma|database|db|internal server)\b/i,
  /\b[a-z]+_[a-z_]+\b/, // snake_case identifiers
];

/** True when the text reads like a short sentence meant for people. */
export function isHumanReadable(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed || trimmed.length > MAX_SAFE_LENGTH) return false;
  return !TECHNICAL_PATTERNS.some((pattern) => pattern.test(trimmed));
}

/** The request failed because nobody is signed in (or the session lapsed). */
export function isSignedOutError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

function statusMessage(status: number): string | null {
  if (status === 0) return "We couldn't reach Menivor. Check your connection and try again.";
  if (status === 401) return SIGNED_OUT_MESSAGE;
  if (status === 402) return "You're out of credits. Add credits to keep going.";
  if (status === 403) return "You don't have access to this.";
  if (status === 404) return "We couldn't find that. It may have been removed.";
  if (status === 408 || status === 504) return "That took too long. Please try again.";
  if (status === 413) return "That file is too large.";
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  if (status >= 500) return "Something went wrong on our side. Please try again in a moment.";
  return null;
}

/** Drop the "<request id>: " prefix and "(correlation ...)" suffix the API adds. */
function stripCorrelation(message: string): string {
  return message
    .replace(/^[0-9a-f-]{16,}:\s*/i, "")
    .replace(/\s*\(correlation [^)]*\)\s*$/i, "")
    .trim();
}

/** Short, human error text for any failure. `fallback` is used when unsure. */
export function friendlyErrorMessage(
  err: unknown,
  fallback: string = DEFAULT_ERROR_MESSAGE,
): string {
  if (err instanceof ApiError) {
    const { status } = err;
    // Transport, auth, throttling and server faults: the server text is
    // never about the user's input, so use a fixed sentence.
    if (status === 0 || status === 401 || status === 429 || status >= 500) {
      return statusMessage(status) ?? fallback;
    }
    // Other 4xx replies (validation, conflict, balance) often carry a plain
    // sentence worth showing as-is.
    const text = stripCorrelation(err.message);
    if (isHumanReadable(text)) return text;
    return statusMessage(status) ?? fallback;
  }
  if (err instanceof DOMException && err.name === "AbortError") return fallback;
  if (err instanceof Error && isHumanReadable(err.message)) return err.message;
  return fallback;
}

/** Show server-provided status text only when it is already a plain sentence. */
export function safeServerText(text: string | null | undefined, fallback: string): string {
  return text && isHumanReadable(text) ? text.trim() : fallback;
}
