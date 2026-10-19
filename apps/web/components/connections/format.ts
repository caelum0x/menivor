/**
 * Formatting helpers for the social-connections UI. All timestamps returned by
 * the backend are UTC ISO-8601 instants; these render them in the viewer's local
 * timezone. SECURITY: nothing here ever touches a token — the connection shape is
 * token-free by construction (see {@link Connection}).
 */

import type { Connection } from "@/lib/types";

/** Format an ISO-8601 instant as a readable local date + time, or a fallback. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  return new Date(ms).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * Split a connection's comma-separated `scopes` string into a clean, de-duped
 * list of scope tokens (blank entries dropped). Order is preserved.
 */
export function formatScopes(scopes: string | null | undefined): string[] {
  if (!scopes) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of scopes.split(/[,\s]+/)) {
    const scope = raw.trim();
    if (scope && !seen.has(scope)) {
      seen.add(scope);
      out.push(scope);
    }
  }
  return out;
}

/**
 * Whether a connection needs a reconnect: the backend flagged it `expired`, or a
 * known `token_expires_at` is already in the past. A connection with no expiry is
 * treated as valid.
 */
export function isConnectionExpired(
  connection: Connection,
  nowMs = Date.now(),
): boolean {
  if (connection.status === "expired") return true;
  const expiry = connection.token_expires_at;
  if (!expiry) return false;
  const ms = new Date(expiry).getTime();
  return !Number.isNaN(ms) && ms <= nowMs;
}
